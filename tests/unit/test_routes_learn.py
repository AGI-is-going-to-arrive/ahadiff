"""Tests for ``ahadiff.serve.routes_learn`` — POST /api/learn route."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Literal, cast

import anyio
import httpx
import pytest
from anyio.to_thread import run_sync as run_sync_in_thread
from starlette.testclient import TestClient

from ahadiff.contracts.serve_runtime import TaskInfoResponse, TaskSubmitResponse
from ahadiff.core.orchestrator import LearnRequest, LearnResult
from ahadiff.core.task_runner import TaskRunner
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
) -> httpx.Response:
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


def _json_object(response: httpx.Response) -> dict[str, object]:
    payload = response.json()
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _task_id_from(response: httpx.Response) -> str:
    payload = TaskSubmitResponse.model_validate(_json_object(response))
    task_id = payload.task_id
    assert isinstance(task_id, str)
    return task_id


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
        payload = _json_object(resp)
        TaskInfoResponse.model_validate(payload)
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
    assert _json_object(resp)["error"] == "invalid_json"


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
    assert _json_object(resp)["error"] == "body_must_be_object"


# ---------------------------------------------------------------------------
# Happy path — 202 accepted
# ---------------------------------------------------------------------------


def test_post_learn_returns_202_with_task_id(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = _post_learn(client, body={})
    assert resp.status_code == 202
    data = _json_object(resp)
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
    assert "task_id" in _json_object(resp)


# ---------------------------------------------------------------------------
# Unknown-field filtering
# ---------------------------------------------------------------------------


def test_post_learn_rejects_unknown_fields(tmp_path: Path) -> None:
    """Extra fields must be rejected with 422, not silently dropped."""
    client = _client(tmp_path)
    resp = _post_learn(
        client,
        body={
            "unknown_field": "should be rejected",
            "another": 42,
            "dry_run": True,
        },
    )
    assert resp.status_code == 422
    body = _json_object(resp)
    assert "unknown_fields" in str(body.get("error", ""))


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
    data = _json_object(resp)
    assert "task_id" in data


# ---------------------------------------------------------------------------
# Task is visible via /api/tasks after submission
# ---------------------------------------------------------------------------


def test_post_learn_task_visible_in_tasks_list(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = _post_learn(client, body={})
    assert resp.status_code == 202
    task_id = _task_id_from(resp)

    tasks_resp = client.get("/api/tasks")
    assert tasks_resp.status_code == 200
    tasks_value = _json_object(tasks_resp)["tasks"]
    assert isinstance(tasks_value, list)
    tasks = cast("list[dict[str, object]]", tasks_value)
    task_ids = [task["task_id"] for task in tasks]
    assert task_id in task_ids


# ---------------------------------------------------------------------------
# H1: Provider override fields rejected (SSRF prevention)
# ---------------------------------------------------------------------------


def test_post_learn_drops_provider_fields_before_request_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """base_url, provider_class etc. must NOT reach LearnRequest."""
    import ahadiff.core.orchestrator as orchestrator_module

    forbidden = {"base_url", "provider_class", "model", "api_key_env", "provider_name"}
    constructed_kwargs: dict[str, Any] = {}

    def recording_learn_request(**kwargs: Any) -> LearnRequest:
        constructed_kwargs.update(kwargs)
        assert forbidden.isdisjoint(kwargs)
        return LearnRequest(**kwargs)

    def fake_run_learn_pipeline(request: LearnRequest, **_: object) -> LearnResult:
        return LearnResult(run_id="run-provider-fields", status="completed")

    monkeypatch.setattr(orchestrator_module, "LearnRequest", recording_learn_request)
    monkeypatch.setattr(orchestrator_module, "run_learn_pipeline", fake_run_learn_pipeline)

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
    assert resp.status_code == 422
    body = _json_object(resp)
    assert "unknown_fields" in str(body.get("error", ""))


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
    assert _json_object(resp)["error"] == "too_many_pending_learn_tasks"


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

    info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")
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

    info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")
    assert info["result"] is not None
    pair = captured[field]
    assert isinstance(pair, tuple)
    path_pair = cast("tuple[Path, Path]", pair)
    assert tuple(str(part) for part in path_pair) == expected


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
    assert _json_object(resp)["error"] == error


@pytest.mark.anyio
async def test_post_learn_queue_depth_limit_is_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")
    assert info["result"] == {
        "run_id": "run-complete",
        "status": "keep",
        "overall": 88.5,
        "verdict": "PASS",
        "weakest_dim": "conciseness",
        "warnings": ["warn-1"],
        "recoverable_errors": 0,
    }


# ---------------------------------------------------------------------------
# Phase 6B: error_code + elapsed_seconds in task responses
# ---------------------------------------------------------------------------


def test_completed_task_has_elapsed_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_learn_pipeline(request: LearnRequest, **_: object) -> LearnResult:
        return LearnResult(run_id="run-elapsed", status="completed")

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
    )

    client = _client(tmp_path)
    resp = _post_learn(client, body={})
    assert resp.status_code == 202

    info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")
    assert "elapsed_seconds" in info
    assert isinstance(info["elapsed_seconds"], float)
    assert info["elapsed_seconds"] >= 0


def test_failed_task_has_error_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_learn_pipeline(request: LearnRequest, **_: object) -> LearnResult:
        raise RuntimeError("claim extraction failed: parse error")

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
    )

    client = _client(tmp_path)
    resp = _post_learn(client, body={})
    assert resp.status_code == 202

    info = _wait_for_task(client, _task_id_from(resp), expected_status="failed")
    assert info["error_code"] == "claim_error"
    assert "claim" in str(info["error"]).lower()
    assert "elapsed_seconds" in info


@pytest.mark.anyio
async def test_post_learn_thread_task_uses_bounded_task_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    cancelled_seen = threading.Event()
    artifact_path = tmp_path / "thread-finished.txt"

    def fake_run_learn_pipeline(request: LearnRequest, **kwargs: object) -> LearnResult:
        cancel_check = kwargs["is_cancelled"]
        assert callable(cancel_check)
        started.set()
        release.wait(timeout=1.0)
        if cast("Any", cancel_check)():
            cancelled_seen.set()
        else:
            artifact_path.write_text("finished\n", encoding="utf-8")
        return LearnResult(run_id="run-thread", status="completed")

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
    )

    app = create_app(
        ServeState(
            state_dir=tmp_path,
            token="test-token",
            locale="en",
            task_runner=TaskRunner(max_concurrent=1, task_timeout_seconds=0.05),
        )
    )
    transport = httpx.ASGITransport(app=app)
    headers = {
        "X-AhaDiff-Token": "test-token",
        "origin": "http://localhost:8765",
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8765") as client:
        resp = await client.post("/api/learn", json={}, headers=headers)
        assert resp.status_code == 202
        task_id = _task_id_from(resp)

        try:
            assert await run_sync_in_thread(lambda: started.wait(timeout=1.0))
            await anyio.sleep(0.15)

            failed_resp = await client.get(f"/api/tasks/{task_id}")
            assert failed_resp.status_code == 200
            failed_info = _json_object(failed_resp)
            assert failed_info["status"] == "failed"
            assert failed_info["error_code"] == "timeout"
            assert "timeout" in str(failed_info["error"])
            assert not artifact_path.exists()
        finally:
            release.set()

        assert await run_sync_in_thread(lambda: cancelled_seen.wait(timeout=1.0))

    assert not artifact_path.exists()


@pytest.mark.anyio
async def test_post_learn_blocks_new_submission_while_timed_out_thread_is_still_draining(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def fake_run_learn_pipeline(request: LearnRequest, **kwargs: object) -> LearnResult:
        del request, kwargs
        started.set()
        release.wait(timeout=1.0)
        return LearnResult(run_id="run-thread", status="completed")

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
    )

    app = create_app(
        ServeState(
            state_dir=tmp_path,
            token="test-token",
            locale="en",
            task_runner=TaskRunner(max_concurrent=1, task_timeout_seconds=0.05),
        )
    )
    transport = httpx.ASGITransport(app=app)
    headers = {
        "X-AhaDiff-Token": "test-token",
        "origin": "http://localhost:8765",
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8765") as client:
        first = await client.post("/api/learn", json={}, headers=headers)
        assert first.status_code == 202
        assert await run_sync_in_thread(lambda: started.wait(timeout=1.0))

        await anyio.sleep(0.15)

        failed_resp = await client.get(f"/api/tasks/{_task_id_from(first)}")
        assert failed_resp.status_code == 200
        failed_info = _json_object(failed_resp)
        assert failed_info["status"] == "failed"
        assert failed_info["error_code"] == "timeout"

        second = await client.post("/api/learn", json={}, headers=headers)
        assert second.status_code == 503
        assert _json_object(second)["error"] == "too_many_pending_learn_tasks"

        release.set()
        deadline = anyio.current_time() + 1.0
        third: httpx.Response | None = None
        while anyio.current_time() < deadline:
            third = await client.post("/api/learn", json={}, headers=headers)
            if third.status_code == 202:
                break
            await anyio.sleep(0.02)

        assert third is not None
        assert third.status_code == 202


@pytest.mark.anyio
async def test_tasks_cancel_cancels_thread_backed_learn_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    cancelled_seen = threading.Event()

    def fake_run_learn_pipeline(request: LearnRequest, **kwargs: object) -> LearnResult:
        del request
        cancel_check = kwargs["is_cancelled"]
        assert callable(cancel_check)
        started.set()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if cast("Any", cancel_check)():
                cancelled_seen.set()
                return LearnResult(run_id="run-cancelled", status="completed")
            time.sleep(0.01)
        raise AssertionError("cancel was not propagated to learn pipeline")

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
    )

    app = create_app(
        ServeState(
            state_dir=tmp_path,
            token="test-token",
            locale="en",
            task_runner=TaskRunner(max_concurrent=1, task_timeout_seconds=5.0),
        )
    )
    transport = httpx.ASGITransport(app=app)
    headers = {
        "X-AhaDiff-Token": "test-token",
        "origin": "http://localhost:8765",
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8765") as client:
        response = await client.post("/api/learn", json={}, headers=headers)
        assert response.status_code == 202
        task_id = _task_id_from(response)
        assert await run_sync_in_thread(lambda: started.wait(timeout=1.0))

        cancel_response = await client.post(f"/api/tasks/{task_id}/cancel", headers=headers)
        assert cancel_response.status_code == 200
        assert _json_object(cancel_response) == {"cancelled": True}

        assert await run_sync_in_thread(lambda: cancelled_seen.wait(timeout=1.0))
        deadline = anyio.current_time() + 1.0
        info: dict[str, object] | None = None
        while anyio.current_time() < deadline:
            status_response = await client.get(f"/api/tasks/{task_id}")
            assert status_response.status_code == 200
            info = _json_object(status_response)
            if info["status"] == "cancelled":
                break
            await anyio.sleep(0.02)

        assert info is not None
        assert info["status"] == "cancelled"
        assert info["result"] is None
        assert info["error_code"] is None


def test_successful_task_error_code_is_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_learn_pipeline(request: LearnRequest, **_: object) -> LearnResult:
        return LearnResult(run_id="run-ok", status="completed")

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
    )

    client = _client(tmp_path)
    resp = _post_learn(client, body={})
    assert resp.status_code == 202

    info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")
    assert info["error_code"] is None
    assert info["error"] is None


__all__: list[str] = []
