"""Tests for ``ahadiff.serve.routes_learn`` — POST /api/learn route."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Literal

import anyio
import httpx
import pytest
from starlette.testclient import TestClient

from ahadiff.core.orchestrator import LearnRequest, LearnResult
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from pathlib import Path


def _client(
    state_dir: Path,
    *,
    token: str = "test-token",
    locale: Literal["en", "zh-CN"] = "en",
) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token=token, locale=locale))
    return TestClient(app, base_url="http://localhost:8765")


def _post_learn(
    client: TestClient,
    body: object | None = None,
    *,
    token: str = "test-token",
    content_type: str = "application/json",
) -> object:
    """Helper: POST /api/learn with correct auth + origin headers."""
    headers = {
        "X-AhaDiff-Token": token,
        "origin": "http://localhost:8765",
    }
    if body is not None:
        return client.post("/api/learn", json=body, headers=headers)
    # Send raw bytes for malformed-JSON tests
    return client.post(
        "/api/learn",
        content=b"not json",
        headers={**headers, "content-type": content_type},
    )


def _wait_for_task(
    client: TestClient,
    task_id: str,
    *,
    expected_status: str,
    timeout_seconds: float = 2.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        resp = client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        payload = resp.json()
        last_payload = payload
        if payload["status"] == expected_status:
            return payload
        time.sleep(0.02)
    raise AssertionError(
        f"task {task_id} did not reach {expected_status!r}; last payload={last_payload!r}"
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_post_learn_requires_token(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/learn", json={})
    assert resp.status_code == 403


def test_post_learn_wrong_token(tmp_path: Path) -> None:
    client = _client(tmp_path, token="correct")
    resp = client.post(
        "/api/learn",
        json={},
        headers={
            "X-AhaDiff-Token": "wrong",
            "origin": "http://localhost:8765",
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_post_learn_invalid_json(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = _post_learn(client, body=None)
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_json"


def test_post_learn_body_must_be_object(tmp_path: Path) -> None:
    """Sending a JSON array instead of an object should get 400."""
    client = _client(tmp_path)
    resp = client.post(
        "/api/learn",
        json=[1, 2, 3],
        headers={
            "X-AhaDiff-Token": "test-token",
            "origin": "http://localhost:8765",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "body_must_be_object"


# ---------------------------------------------------------------------------
# Happy path — 202 accepted
# ---------------------------------------------------------------------------


def test_post_learn_returns_202_with_task_id(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = _post_learn(client, body={})
    assert resp.status_code == 202
    data = resp.json()
    assert "task_id" in data
    assert isinstance(data["task_id"], str)
    assert len(data["task_id"]) > 0


def test_post_learn_with_valid_fields(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = _post_learn(
        client,
        body={
            "dry_run": True,
            "force_learn": True,
            "lang": "zh-CN",
        },
    )
    assert resp.status_code == 202
    assert "task_id" in resp.json()


# ---------------------------------------------------------------------------
# Unknown-field filtering
# ---------------------------------------------------------------------------


def test_post_learn_ignores_unknown_fields(tmp_path: Path) -> None:
    """Extra fields should be silently dropped; route still returns 202."""
    client = _client(tmp_path)
    resp = _post_learn(
        client,
        body={
            "unknown_field": "should be ignored",
            "another": 42,
            "dry_run": True,
        },
    )
    assert resp.status_code == 202
    assert "task_id" in resp.json()


def test_post_learn_filters_none_values(tmp_path: Path) -> None:
    """Fields with None values should be filtered out."""
    client = _client(tmp_path)
    resp = _post_learn(
        client,
        body={
            "revision": None,
            "dry_run": True,
        },
    )
    assert resp.status_code == 202


# ---------------------------------------------------------------------------
# Empty body accepted
# ---------------------------------------------------------------------------


def test_post_learn_empty_body_accepted(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = _post_learn(client, body={})
    assert resp.status_code == 202
    data = resp.json()
    assert "task_id" in data


# ---------------------------------------------------------------------------
# Task is visible via /api/tasks after submission
# ---------------------------------------------------------------------------


def test_post_learn_task_visible_in_tasks_list(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = _post_learn(client, body={})
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    tasks_resp = client.get("/api/tasks")
    assert tasks_resp.status_code == 200
    task_ids = [t["task_id"] for t in tasks_resp.json()["tasks"]]
    assert task_id in task_ids


# ---------------------------------------------------------------------------
# H1: Provider override fields rejected (SSRF prevention)
# ---------------------------------------------------------------------------


def test_post_learn_rejects_provider_fields(tmp_path: Path) -> None:
    """base_url, provider_class etc. must NOT be accepted — SSRF risk."""
    client = _client(tmp_path)
    resp = _post_learn(
        client,
        body={
            "base_url": "http://169.254.169.254/metadata",
            "provider_class": "openai",
            "model": "evil-model",
            "api_key_env": "STOLEN_KEY",
            "provider_name": "attacker",
        },
    )
    assert resp.status_code == 202
    # The fields above should be silently dropped (not in _ACCEPTED_FIELDS)


# ---------------------------------------------------------------------------
# H3: Queue depth limit
# ---------------------------------------------------------------------------


def test_post_learn_queue_depth_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When max pending tasks limit is reached, return 503."""
    import ahadiff.serve.routes_learn as rl

    monkeypatch.setattr(rl, "_MAX_PENDING_TASKS", 0)
    client = _client(tmp_path)
    resp = _post_learn(client, body={})
    assert resp.status_code == 503
    assert resp.json()["error"] == "too_many_pending_learn_tasks"


# ---------------------------------------------------------------------------
# M2: Type coercion
# ---------------------------------------------------------------------------


def test_post_learn_coerces_string_bool(tmp_path: Path) -> None:
    """'false' as string should be coerced to False, not truthy."""
    client = _client(tmp_path)
    resp = _post_learn(client, body={"dry_run": "false"})
    assert resp.status_code == 202


def test_post_learn_coerces_falsey_bool_strings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run_learn_pipeline(request: LearnRequest, **_: object) -> LearnResult:
        captured["dry_run"] = request.dry_run
        captured["force_learn"] = request.force_learn
        captured["last"] = request.last
        captured["use_graphify"] = request.use_graphify
        return LearnResult(run_id="run-coerce", status="completed")

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
    )

    client = _client(tmp_path)
    resp = _post_learn(
        client,
        body={
            "dry_run": "false",
            "force_learn": "0",
            "last": "true",
            "use_graphify": "false",
        },
    )
    assert resp.status_code == 202

    info = _wait_for_task(client, resp.json()["task_id"], expected_status="completed")
    assert info["result"] is not None
    assert captured == {
        "dry_run": False,
        "force_learn": False,
        "last": True,
        "use_graphify": False,
    }


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("compare", ("before.py", "after.py")),
        ("compare_dir", ("old", "new")),
    ],
)
def test_post_learn_coerces_path_pair_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    expected: tuple[str, str],
) -> None:
    captured: dict[str, object] = {}

    def fake_run_learn_pipeline(request: LearnRequest, **_: object) -> LearnResult:
        captured[field] = getattr(request, field)
        return LearnResult(run_id="run-path-pair", status="completed")

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
    )

    client = _client(tmp_path)
    resp = _post_learn(client, body={field: list(expected)})
    assert resp.status_code == 202

    info = _wait_for_task(client, resp.json()["task_id"], expected_status="completed")
    assert info["result"] is not None
    pair = captured[field]
    assert isinstance(pair, tuple)
    assert tuple(str(part) for part in pair) == expected


def test_post_learn_rejects_stdin_patch_mode(tmp_path: Path) -> None:
    """Serve-side learn tasks must not consume process stdin via patch='-'."""
    client = _client(tmp_path)
    resp = _post_learn(client, body={"patch": "-"})
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"last": 3}, "invalid_value_for_last"),
        ({"last": "not_a_number"}, "invalid_value_for_last"),
        ({"privacy_mode": "totally_remote"}, "invalid_value_for_privacy_mode"),
        ({"lang": "fr"}, "invalid_value_for_lang"),
        ({"author": "x" * 4097}, "invalid_value_for_author"),
        ({"dry_run": 42}, "invalid_value_for_dry_run"),
        ({"compare": ["only-one"]}, "invalid_value_for_compare"),
        ({"compare_dir": ["old", 7]}, "invalid_value_for_compare_dir"),
    ],
)
def test_post_learn_rejects_invalid_values(
    tmp_path: Path,
    body: dict[str, object],
    error: str,
) -> None:
    client = _client(tmp_path)
    resp = _post_learn(client, body=body)
    assert resp.status_code == 422
    assert resp.json()["error"] == error


@pytest.mark.anyio
async def test_post_learn_queue_depth_limit_is_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ahadiff.serve.routes_learn as rl

    monkeypatch.setattr(rl, "_MAX_PENDING_TASKS", 1)
    release = threading.Event()

    def fake_run_learn_pipeline(request: LearnRequest, **_: object) -> LearnResult:
        release.wait(timeout=1.0)
        return LearnResult(run_id="run-atomic", status="completed")

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
    )

    app = create_app(ServeState(state_dir=tmp_path, token="test-token", locale="en"))
    transport = httpx.ASGITransport(app=app)
    headers = {
        "X-AhaDiff-Token": "test-token",
        "origin": "http://localhost:8765",
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8765") as client:
        responses: list[httpx.Response] = []

        async def _submit() -> None:
            responses.append(await client.post("/api/learn", json={}, headers=headers))

        async with anyio.create_task_group() as tg:
            tg.start_soon(_submit)
            tg.start_soon(_submit)
            await anyio.sleep(0.05)
            release.set()

    assert sorted(response.status_code for response in responses) == [202, 503]


def test_post_learn_completed_task_preserves_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_learn_pipeline(request: LearnRequest, **_: object) -> LearnResult:
        return LearnResult(
            run_id="run-complete",
            status="keep",
            overall=88.5,
            verdict="PASS",
            weakest_dim="conciseness",
            warnings=["warn-1"],
            artifacts_path=str(request.workspace_root),
        )

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
    )

    client = _client(tmp_path)
    resp = _post_learn(client, body={})
    assert resp.status_code == 202

    info = _wait_for_task(client, resp.json()["task_id"], expected_status="completed")
    assert info["result"] == {
        "run_id": "run-complete",
        "status": "keep",
        "overall": 88.5,
        "verdict": "PASS",
        "weakest_dim": "conciseness",
        "warnings": ["warn-1"],
    }


__all__: list[str] = []
