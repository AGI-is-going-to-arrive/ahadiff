"""Tests for ``ahadiff.serve.routes_learn`` — POST /api/learn route."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal, cast

import anyio
import httpx
import pytest
from anyio.to_thread import run_sync as run_sync_in_thread
from starlette.testclient import TestClient

from ahadiff.contracts.serve_app import LearnEstimateResponse
from ahadiff.contracts.serve_runtime import TaskInfoResponse, TaskSubmitResponse
from ahadiff.core.budget import CaptureRecommendation
from ahadiff.core.orchestrator import LearnRequest, LearnResult
from ahadiff.core.task_runner import TaskRunner
from ahadiff.serve import ServeState, create_app, routes_learn

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


def _post_learn_estimate(
    client: TestClient,
    body: object | None = None,
    *,
    token: str = "test-token",
) -> httpx.Response:
    headers = {
        "X-AhaDiff-Token": token,
        "origin": "http://localhost:8765",
    }
    return client.post("/api/learn/estimate", json={} if body is None else body, headers=headers)


def _json_object(response: httpx.Response) -> dict[str, object]:
    payload = response.json()
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _task_id_from(response: httpx.Response) -> str:
    payload = TaskSubmitResponse.model_validate(_json_object(response))
    task_id = payload.task_id
    assert isinstance(task_id, str)
    return task_id


def _capture_recommendation(
    *,
    mode: Literal["auto", "manual"] = "auto",
    context_window: int = 16_000,
    max_input_tokens: int = 12_000,
    max_output_tokens: int = 4_000,
    source: str = "live",
) -> CaptureRecommendation:
    return CaptureRecommendation(
        mode=mode,
        max_files=8,
        hard_limit=400,
        max_patch_bytes=100_000,
        runtime_max_patch_bytes=50 * 1024 * 1024,
        payload_byte_budget=24_000,
        context_window=context_window,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        diff_token_budget=8_000,
        safety_reserve=2_000,
        output_reserve=max_output_tokens,
        system_prompt_tokens=1_220,
        fits_minimums=True,
        model_name="gpt-4o",
        source=source,
        cjk_ratio=0.0,
        cjk_factor=1.0,
        warnings=[],
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
        payload = _json_object(resp)
        TaskInfoResponse.model_validate(payload)
        last_payload = payload
        if payload["status"] == expected_status:
            return payload
        time.sleep(0.02)
    raise AssertionError(
        f"task {task_id} did not reach {expected_status!r}; last payload={last_payload!r}"
    )


def _stub_completed_learn(monkeypatch: pytest.MonkeyPatch, run_id: str) -> None:
    def fake_run_learn_pipeline(request: LearnRequest, **_: object) -> LearnResult:
        return LearnResult(run_id=run_id, status="completed")

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
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
    assert resp.status_code == 401


def test_post_learn_estimate_requires_token(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")
    resp = client.post("/api/learn/estimate", json={})
    assert resp.status_code == 403


def test_post_learn_estimate_wrong_token(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff", token="correct")
    resp = _post_learn_estimate(client, token="wrong")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Estimate
# ---------------------------------------------------------------------------


def test_post_learn_estimate_happy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text('[capture]\nmode = "manual"\n', encoding="utf-8")
    client = _client(state_dir)
    patch_text = "diff --git a/a.py b/a.py\n+print('hello')\n"

    def fake_capture_patch(**_: object) -> SimpleNamespace:
        return SimpleNamespace(
            persisted_patch_text=patch_text,
            metadata={"selected_files": ["a.py"]},
        )

    def fake_estimate_text_tokens(_text: str, _strategy: object) -> int:
        return 10

    def fake_capture_recommendation_for_estimate(**_: object) -> CaptureRecommendation:
        return _capture_recommendation(
            mode="manual",
            context_window=16_000,
            max_input_tokens=12_000,
            max_output_tokens=4_000,
        )

    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", fake_estimate_text_tokens)
    monkeypatch.setattr(
        routes_learn,
        "_capture_recommendation_for_estimate",
        fake_capture_recommendation_for_estimate,
    )

    resp = _post_learn_estimate(client)

    assert resp.status_code == 200
    payload = LearnEstimateResponse.model_validate(_json_object(resp))
    assert payload.patch_bytes == len(patch_text.encode("utf-8"))
    assert payload.file_count == 1
    assert payload.total_lines == 2
    assert payload.estimated_tokens == 10
    assert payload.provider_context_window == 16_000
    assert payload.provider_max_output == 4_000
    assert payload.risk_level == "ok"
    assert payload.warnings == []


def test_post_learn_estimate_passes_changed_paths_to_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path / ".ahadiff")
    captured_kwargs: dict[str, object] = {}

    def fake_capture_patch(**kwargs: object) -> SimpleNamespace:
        captured_kwargs.update(kwargs)
        return SimpleNamespace(
            persisted_patch_text="diff --git a/src/app.py b/src/app.py\n+print('hello')\n",
            metadata={"selected_files": ["src/app.py"]},
        )

    def fake_estimate_text_tokens(_text: str, _strategy: object) -> int:
        return 10

    def fake_capture_recommendation_for_estimate(**_: object) -> CaptureRecommendation:
        return _capture_recommendation(
            mode="manual",
            context_window=16_000,
            max_input_tokens=12_000,
            max_output_tokens=4_000,
        )

    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", fake_estimate_text_tokens)
    monkeypatch.setattr(
        routes_learn,
        "_capture_recommendation_for_estimate",
        fake_capture_recommendation_for_estimate,
    )

    resp = _post_learn_estimate(
        client,
        body={"changed_paths": ["src/app.py"], "unstaged": True},
    )

    assert resp.status_code == 200
    assert captured_kwargs["changed_paths"] == ("src/app.py",)


def test_post_learn_estimate_captures_under_repo_write_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path / ".ahadiff")
    lock_depth = 0

    class RecordingLock:
        def __enter__(self) -> None:
            nonlocal lock_depth
            lock_depth += 1

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            nonlocal lock_depth
            del exc_type, exc, tb
            lock_depth -= 1

    def fake_lock(*_args: object, **_kwargs: object) -> RecordingLock:
        return RecordingLock()

    def fake_capture_patch(**_: object) -> SimpleNamespace:
        assert lock_depth == 1
        return SimpleNamespace(
            persisted_patch_text="diff --git a/a.py b/a.py\n+print('hello')\n",
            metadata={"selected_files": ["a.py"]},
        )

    def fake_estimate_text_tokens(_text: str, _strategy: object) -> int:
        return 10

    monkeypatch.setattr(routes_learn, "serve_repo_write_lock", fake_lock)
    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", fake_estimate_text_tokens)

    response = _post_learn_estimate(client)

    assert response.status_code == 200
    assert lock_depth == 0


def test_post_learn_estimate_uses_threadpool_for_capture_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text('[capture]\nmode = "manual"\n', encoding="utf-8")
    client = _client(state_dir)
    calls: list[str] = []

    async def recording_run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
        del kwargs
        calls.append(getattr(func, "__name__", repr(func)))
        return func(*args)

    def fake_capture_patch(**_: object) -> SimpleNamespace:
        return SimpleNamespace(
            persisted_patch_text="diff --git a/a.py b/a.py\n+print('hello')\n",
            metadata={"selected_files": ["a.py"]},
        )

    def fake_estimate_text_tokens(_text: str, _strategy: object) -> int:
        return 10

    monkeypatch.setattr(routes_learn, "run_sync_in_thread", recording_run_sync)
    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", fake_estimate_text_tokens)

    response = _post_learn_estimate(client)

    assert response.status_code == 200
    assert "_capture_estimate_with_lock" in calls


@pytest.mark.parametrize(
    "changed_path",
    [
        "../outside.py",
        "/tmp/outside.py",
        "C:secret.txt",
        "C:/Users/example/app.py",
        "C:\\Users\\example\\app.py",
        "\\\\server\\share\\app.py",
        "src/\x01app.py",
        ".git/config",
    ],
)
def test_post_learn_estimate_rejects_unsafe_changed_paths(
    tmp_path: Path,
    changed_path: str,
) -> None:
    client = _client(tmp_path / ".ahadiff")

    resp = _post_learn_estimate(
        client,
        body={"changed_paths": [changed_path], "unstaged": True},
    )

    assert resp.status_code == 422
    body = _json_object(resp)
    assert body["error"] == "invalid_value_for_changed_paths"


@pytest.mark.parametrize(
    ("estimated_tokens", "context_window", "file_count", "risk_level"),
    [
        (4_000, 10_000, 2, "ok"),
        (5_001, 10_000, 2, "warn"),
        (8_001, 10_000, 2, "danger"),
        (4_000, 10_000, 31, "warn"),
        (4_000, 10_000, 51, "danger"),
    ],
)
def test_post_learn_estimate_risk_levels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    estimated_tokens: int,
    context_window: int,
    file_count: int,
    risk_level: Literal["ok", "warn", "danger"],
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text('[capture]\nmode = "manual"\n', encoding="utf-8")
    client = _client(state_dir)
    patch_text = "x\n"

    def fake_capture_patch(**_: object) -> SimpleNamespace:
        return SimpleNamespace(
            persisted_patch_text=patch_text,
            metadata={"selected_files": [f"f{i}.py" for i in range(file_count)]},
        )

    def fake_estimate_text_tokens(_text: str, _strategy: object) -> int:
        return estimated_tokens

    def fake_capture_recommendation_for_estimate(**_: object) -> CaptureRecommendation:
        return _capture_recommendation(
            mode="manual",
            context_window=context_window,
            max_input_tokens=max(context_window - 4_000, 0),
            max_output_tokens=4_000,
        )

    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(
        routes_learn,
        "estimate_text_tokens",
        fake_estimate_text_tokens,
    )
    monkeypatch.setattr(
        routes_learn,
        "_capture_recommendation_for_estimate",
        fake_capture_recommendation_for_estimate,
    )

    resp = _post_learn_estimate(client)

    assert resp.status_code == 200
    payload = LearnEstimateResponse.model_validate(_json_object(resp))
    assert payload.risk_level == risk_level
    if risk_level == "ok":
        assert payload.warnings == []
    else:
        assert payload.warnings


def test_post_learn_estimate_auto_mode_warns_on_omitted_files_not_file_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path / ".ahadiff")

    def fake_capture_patch(**_: object) -> SimpleNamespace:
        return SimpleNamespace(
            persisted_patch_text="x\n",
            metadata={
                "selected_files": [f"f{i}.py" for i in range(100)],
                "omitted_files": ["omitted.py"],
            },
        )

    def fake_estimate_text_tokens(_text: str, _strategy: object) -> int:
        return 10

    def fake_capture_recommendation_for_estimate(**_: object) -> CaptureRecommendation:
        return _capture_recommendation(
            mode="auto",
            context_window=10_000,
            max_input_tokens=6_000,
            max_output_tokens=4_000,
        )

    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", fake_estimate_text_tokens)
    monkeypatch.setattr(
        routes_learn,
        "_capture_recommendation_for_estimate",
        fake_capture_recommendation_for_estimate,
    )

    resp = _post_learn_estimate(client)

    assert resp.status_code == 200
    payload = LearnEstimateResponse.model_validate(_json_object(resp))
    assert payload.file_count == 100
    assert payload.omitted_files_count == 1
    assert payload.risk_level == "warn"
    assert all("File count" not in warning for warning in payload.warnings)


def test_post_learn_estimate_audits_clipped_diff_and_omitted_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path / ".ahadiff")
    recommendation = _capture_recommendation(mode="auto")
    captured_kwargs: dict[str, object] = {}

    def fake_capture_recommendation_for_estimate(**_: object) -> CaptureRecommendation:
        return recommendation

    def fake_capture_patch(**kwargs: object) -> SimpleNamespace:
        captured_kwargs.update(kwargs)
        return SimpleNamespace(
            persisted_patch_text="diff --git a/a.py b/a.py\n+print('hello')\n",
            metadata={
                "selected_files": ["a.py"],
                "omitted_files": ["large.py", "generated.py"],
                "degraded_flags": {"diff_clipped": True},
            },
        )

    def fake_estimate_text_tokens(_text: str, _strategy: object) -> int:
        return 10

    monkeypatch.setattr(
        routes_learn,
        "_capture_recommendation_for_estimate",
        fake_capture_recommendation_for_estimate,
    )
    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", fake_estimate_text_tokens)
    resp = _post_learn_estimate(client)

    assert resp.status_code == 200
    payload = LearnEstimateResponse.model_validate(_json_object(resp))
    assert payload.diff_clipped is True
    assert payload.omitted_files_count == 2
    assert payload.risk_level == "warn"
    assert "Capture omitted 2 files" in payload.warnings
    assert "Diff was clipped by effective capture limits" in payload.warnings
    assert captured_kwargs["max_files"] == recommendation.max_files
    assert captured_kwargs["hard_limit"] == recommendation.hard_limit
    assert captured_kwargs["max_patch_bytes"] == recommendation.max_patch_bytes


def test_post_learn_estimate_uses_one_config_snapshot_for_capture_and_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path / ".ahadiff")

    def snapshot(max_input_tokens: int) -> SimpleNamespace:
        return SimpleNamespace(
            values={
                "capture": {"mode": "auto", "max_files": 30, "hard_limit": 3000},
                "llm": {
                    "generate_model": "gpt-4o",
                    "output_token_budget": 50_000,
                    "claim_extraction_output_cap": 16_000,
                    "lesson_full_output_cap": 24_000,
                    "lesson_hint_output_cap": 3_000,
                    "lesson_compact_output_cap": 2_500,
                    "quiz_generation_output_cap": 18_000,
                    "misconception_cards_output_cap": 6_000,
                },
                "providers": {
                    "local": {
                        "provider_class": "openai",
                        "model_name": "gpt-4o",
                        "base_url": "http://127.0.0.1:8318",
                        "api_key_env": "AHADIFF_PROVIDER_API_KEY",
                        "probed_max_input_tokens": max_input_tokens,
                    }
                },
                "privacy_mode": "strict_local",
                "lang": "en",
            },
            resolved={},
        )

    snapshots = [snapshot(120_000), snapshot(4_096)]
    load_calls: list[Path] = []

    def fake_load_workspace_config(
        root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> SimpleNamespace:
        del cli_overrides
        load_calls.append(root)
        return snapshots[min(len(load_calls) - 1, len(snapshots) - 1)]

    def fake_capture_patch(**_: object) -> SimpleNamespace:
        return SimpleNamespace(
            persisted_patch_text="diff --git a/a.py b/a.py\n+print('hello')\n",
            metadata={"selected_files": ["a.py"]},
        )

    def fake_load_workspace_security_config(_root: Path) -> SimpleNamespace:
        return SimpleNamespace(
            local_hosts=("127.0.0.1",),
            strict_local_hosts=("127.0.0.1",),
        )

    def fake_estimate_text_tokens(_text: str, _strategy: object) -> int:
        return 10

    monkeypatch.setattr(routes_learn, "load_workspace_config", fake_load_workspace_config)
    monkeypatch.setattr(
        routes_learn,
        "load_workspace_security_config",
        fake_load_workspace_security_config,
    )
    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", fake_estimate_text_tokens)

    resp = _post_learn_estimate(client)

    assert resp.status_code == 200
    payload = LearnEstimateResponse.model_validate(_json_object(resp))
    assert payload.effective_capture_limits is not None
    assert payload.provider_context_window == payload.effective_capture_limits.context_window
    assert len(load_calls) == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_post_learn_invalid_json(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = _post_learn(client, body=None)
    assert resp.status_code == 400
    assert _json_object(resp)["error_code"] == "INPUT_INVALID_JSON"
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
    assert _json_object(resp)["error_code"] == "INPUT_BAD_FIELD"
    assert _json_object(resp)["error"] == "body_must_be_object"


# ---------------------------------------------------------------------------
# Happy path — 202 accepted
# ---------------------------------------------------------------------------


def test_post_learn_returns_202_with_task_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_completed_learn(monkeypatch, "run-accepted")

    with _client(tmp_path) as client:
        resp = _post_learn(client, body={})
        assert resp.status_code == 202
        data = _json_object(resp)
        assert "task_id" in data
        assert isinstance(data["task_id"], str)
        assert len(data["task_id"]) > 0
        info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")

    assert info["status"] == "completed"


def test_post_learn_with_valid_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_completed_learn(monkeypatch, "run-valid-fields")

    with _client(tmp_path) as client:
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
        info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")

    assert info["status"] == "completed"


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
    assert body["error_code"] == "INPUT_UNKNOWN_KEYS"
    assert "unknown_fields" in str(body.get("error", ""))


def test_post_learn_filters_none_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fields with None values should be filtered out."""
    _stub_completed_learn(monkeypatch, "run-none-values")
    with _client(tmp_path) as client:
        resp = _post_learn(
            client,
            body={
                "revision": None,
                "dry_run": True,
            },
        )
        assert resp.status_code == 202
        info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")
    assert info["status"] == "completed"


# ---------------------------------------------------------------------------
# Empty body accepted
# ---------------------------------------------------------------------------


def test_post_learn_empty_body_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_completed_learn(monkeypatch, "run-empty-body")
    with _client(tmp_path) as client:
        resp = _post_learn(client, body={})
        assert resp.status_code == 202
        data = _json_object(resp)
        assert "task_id" in data
        info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")
    assert info["status"] == "completed"


# ---------------------------------------------------------------------------
# Task is visible via /api/tasks after submission
# ---------------------------------------------------------------------------


def test_post_learn_task_visible_in_tasks_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_completed_learn(monkeypatch, "run-visible-task")
    with _client(tmp_path) as client:
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
        info = _wait_for_task(client, task_id, expected_status="completed")
    assert info["status"] == "completed"


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


def test_post_learn_passes_changed_paths_to_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ahadiff.core.orchestrator as orchestrator_module

    constructed_kwargs: dict[str, Any] = {}

    def recording_learn_request(**kwargs: Any) -> LearnRequest:
        constructed_kwargs.update(kwargs)
        assert kwargs["changed_paths"] == ("src/app.py", "tests/test_app.py")
        return LearnRequest(**kwargs)

    def fake_run_learn_pipeline(request: LearnRequest, **_: object) -> LearnResult:
        return LearnResult(run_id="run-watch-change", status="completed")

    monkeypatch.setattr(orchestrator_module, "LearnRequest", recording_learn_request)
    monkeypatch.setattr(orchestrator_module, "run_learn_pipeline", fake_run_learn_pipeline)

    with _client(tmp_path) as client:
        resp = _post_learn(
            client,
            body={"changed_paths": ["src/app.py", "tests/test_app.py"]},
        )
        assert resp.status_code == 202

        info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")

    assert info["status"] == "completed"
    assert constructed_kwargs["workspace_root"] == tmp_path.parent
    assert constructed_kwargs["changed_paths"] == ("src/app.py", "tests/test_app.py")


def test_post_learn_passes_against_spec_to_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ahadiff.core.orchestrator as orchestrator_module

    constructed_kwargs: dict[str, Any] = {}

    def recording_learn_request(**kwargs: Any) -> LearnRequest:
        constructed_kwargs.update(kwargs)
        assert kwargs["against_spec"] == (tmp_path.parent / "SPEC.md").resolve()
        assert kwargs["spec_semantic_review"] is True
        return LearnRequest(**kwargs)

    def fake_run_learn_pipeline(request: LearnRequest, **_: object) -> LearnResult:
        return LearnResult(run_id="run-against-spec", status="completed")

    monkeypatch.setattr(orchestrator_module, "LearnRequest", recording_learn_request)
    monkeypatch.setattr(orchestrator_module, "run_learn_pipeline", fake_run_learn_pipeline)

    with _client(tmp_path) as client:
        resp = _post_learn(
            client,
            body={"against_spec": "SPEC.md", "spec_semantic_review": True},
        )
        assert resp.status_code == 202

        info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")

    assert info["status"] == "completed"
    assert constructed_kwargs["against_spec"] == (tmp_path.parent / "SPEC.md").resolve()
    assert constructed_kwargs["spec_semantic_review"] is True


def test_post_learn_rejects_against_spec_outside_workspace(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = _post_learn(
        client,
        body={"against_spec": "/etc/passwd", "spec_semantic_review": True},
    )
    assert resp.status_code == 422
    body = _json_object(resp)
    assert body["error_code"] == "INPUT_VALIDATION"
    assert body["error"] == "invalid_value_for_against_spec"


def test_post_learn_estimate_rejects_against_spec_outside_workspace(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = _post_learn_estimate(client, body={"against_spec": "/etc/passwd"})
    assert resp.status_code == 422
    body = _json_object(resp)
    assert body["error_code"] == "INPUT_VALIDATION"
    assert body["error"] == "invalid_value_for_against_spec"


# ---------------------------------------------------------------------------
# H3: Queue depth limit
# ---------------------------------------------------------------------------


def test_post_learn_queue_depth_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When max pending tasks limit is reached, return a stable conflict error."""
    import ahadiff.serve.routes_learn as rl

    monkeypatch.setattr(rl, "_MAX_PENDING_TASKS", 0)
    client = _client(tmp_path)
    resp = _post_learn(client, body={})
    assert resp.status_code == 409
    body = _json_object(resp)
    assert body["error_code"] == "LOCK_CONFLICT"
    assert body["error"] == "too_many_pending_learn_tasks"


def test_post_learn_prechecks_repo_write_lock(tmp_path: Path) -> None:
    from ahadiff.git.repo import repo_write_lock

    client = _client(tmp_path)
    with repo_write_lock(tmp_path / "ahadiff.lock", command="test"):
        resp = _post_learn(client, body={})

    assert resp.status_code == 409
    body = _json_object(resp)
    assert body["error_code"] == "LOCK_CONFLICT"
    assert body["error"] == "run_in_progress"


# ---------------------------------------------------------------------------
# M2: Type coercion
# ---------------------------------------------------------------------------


def test_post_learn_coerces_string_bool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'false' as string should be coerced to False, not truthy."""
    _stub_completed_learn(monkeypatch, "run-string-bool")
    with _client(tmp_path) as client:
        resp = _post_learn(client, body={"dry_run": "false"})
        assert resp.status_code == 202
        info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")
    assert info["status"] == "completed"


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

    with _client(tmp_path) as client:
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
    assert info["result_summary"] is not None
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

    with _client(tmp_path) as client:
        resp = _post_learn(client, body={field: list(expected)})
        assert resp.status_code == 202

        info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")
    assert info["result_summary"] is not None
    pair = captured[field]
    assert isinstance(pair, tuple)
    path_pair = cast("tuple[Path, Path]", pair)
    assert tuple(str(part) for part in path_pair) == expected


def test_post_learn_rejects_stdin_patch_mode(tmp_path: Path) -> None:
    """Serve-side learn tasks must not consume process stdin via patch='-'."""
    client = _client(tmp_path)
    resp = _post_learn(client, body={"patch": "-"})
    assert resp.status_code == 422
    assert _json_object(resp)["error_code"] == "INPUT_VALIDATION"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"last": 3}, "invalid_value_for_last"),
        ({"last": "not_a_number"}, "invalid_value_for_last"),
        ({"privacy_mode": "totally_remote"}, "invalid_value_for_privacy_mode"),
        ({"lang": "fr"}, "invalid_value_for_lang"),
        ({"author": "x" * 4097}, "invalid_value_for_author"),
        ({"author": "--all"}, "invalid_value_for_author"),
        ({"author": "Ada\x7f"}, "invalid_value_for_author"),
        ({"since": "--all"}, "invalid_value_for_since"),
        ({"since": "2025-01-01\x1f"}, "invalid_value_for_since"),
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
    response_body = _json_object(resp)
    assert response_body["error_code"] == "INPUT_VALIDATION"
    assert response_body["error"] == error


def test_post_learn_estimate_rejects_since_git_option_injection(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = _post_learn_estimate(client, body={"since": "--all"})
    assert resp.status_code == 422
    body = _json_object(resp)
    assert body["error_code"] == "INPUT_VALIDATION"
    assert body["error"] == "invalid_value_for_since"


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

    assert sorted(response.status_code for response in responses) == [202, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert _json_object(conflict)["error_code"] == "LOCK_CONFLICT"


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

    with _client(tmp_path) as client:
        resp = _post_learn(client, body={})
        assert resp.status_code == 202

        info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")
    assert info["result_summary"] == {
        "run_id": "run-complete",
        "status": "keep",
        "overall": 88.5,
        "verdict": "PASS",
        "warnings": ["warn-1"],
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

    with _client(tmp_path) as client:
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

    with _client(tmp_path) as client:
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
        assert second.status_code == 409
        second_body = _json_object(second)
        assert second_body["error_code"] == "LOCK_CONFLICT"
        assert second_body["error"] == "too_many_pending_learn_tasks"

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
        assert info["result_summary"] is None
        assert info["error_code"] is None


@pytest.mark.anyio
async def test_late_cancel_after_publish_boundary_keeps_run_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    cancelled_seen = threading.Event()
    run_path = tmp_path / ".ahadiff" / "runs" / "run-published"

    def fake_run_learn_pipeline(request: LearnRequest, **kwargs: object) -> LearnResult:
        del request
        cancel_check = kwargs["is_cancelled"]
        assert callable(cancel_check)
        started.set()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if cast("Any", cancel_check)():
                cancelled_seen.set()
                run_path.mkdir(parents=True, exist_ok=True)
                (run_path / "finalized.json").write_text("{}\n", encoding="utf-8")
                (run_path / "score.json").write_text("{}\n", encoding="utf-8")
                return LearnResult(
                    run_id="run-published",
                    status="keep",
                    artifacts_path=str(run_path),
                )
            time.sleep(0.01)
        raise AssertionError("cancel was not propagated to learn pipeline")

    monkeypatch.setattr(
        "ahadiff.core.orchestrator.run_learn_pipeline",
        fake_run_learn_pipeline,
    )

    app = create_app(
        ServeState(
            state_dir=tmp_path / ".ahadiff",
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
        assert await run_sync_in_thread(lambda: cancelled_seen.wait(timeout=1.0))

        info: dict[str, object] | None = None
        deadline = anyio.current_time() + 1.0
        while anyio.current_time() < deadline:
            status_response = await client.get(f"/api/tasks/{task_id}")
            assert status_response.status_code == 200
            info = _json_object(status_response)
            if info["status"] == "cancelled":
                break
            await anyio.sleep(0.02)

    assert info is not None
    assert info["status"] == "cancelled"
    assert info["result_summary"] is None
    assert (run_path / "finalized.json").exists()
    assert (run_path / "score.json").exists()


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

    with _client(tmp_path) as client:
        resp = _post_learn(client, body={})
        assert resp.status_code == 202

        info = _wait_for_task(client, _task_id_from(resp), expected_status="completed")
    assert info["error_code"] is None
    assert info["error"] is None


__all__: list[str] = []
