from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from starlette.testclient import TestClient

from ahadiff.contracts.serve_runtime import (
    TaskInfoResponse,
    TaskListResponse,
    TaskProgressEvent,
    TaskProgressResponse,
    TaskResultSummary,
)
from ahadiff.core.task_runner import TaskInfo, TaskProgress, TaskStatus
from ahadiff.serve import ServeState, create_app
from ahadiff.serve import middleware as middleware_mod
from ahadiff.serve.middleware import (
    _rate_limit_for_path,  # pyright: ignore[reportPrivateUsage]
    _request_timeout_for,  # pyright: ignore[reportPrivateUsage]
)
from ahadiff.serve.routes_tasks import (
    _sanitize_warning,  # pyright: ignore[reportPrivateUsage]
    _user_facing_message,  # pyright: ignore[reportPrivateUsage]
)

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


def _parse_sse_data(body: str) -> dict[str, object]:
    for line in body.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line.removeprefix("data: "))
            assert isinstance(payload, dict)
            return cast("dict[str, object]", payload)
    raise AssertionError(f"SSE body has no data line: {body}")


def _parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
    return parsed


class _StaticTaskRunner:
    def __init__(self, info: TaskInfo | None) -> None:
        self.info = info
        self.pinned = False
        self.unpinned = False

    def pin_task(self, task_id: str) -> bool:
        self.pinned = self.info is not None and self.info.task_id == task_id
        return self.pinned

    def unpin_task(self, task_id: str) -> None:
        if self.info is not None and self.info.task_id == task_id:
            self.unpinned = True

    def get_task(self, task_id: str) -> TaskInfo | None:
        if self.info is not None and self.info.task_id == task_id:
            return self.info
        return None

    def list_tasks(self) -> list[TaskInfo]:
        return [] if self.info is None else [self.info]


def test_list_tasks_empty(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    body = resp.json()
    TaskListResponse.model_validate(body)
    assert body["tasks"] == []


def test_get_task_not_found(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.get("/api/tasks/nonexistent")
    assert resp.status_code == 404


def test_cancel_requires_auth(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/tasks/nonexistent/cancel")
    assert resp.status_code == 403


def test_cancel_with_auth_nonexistent(tmp_path: Path) -> None:
    client = _client(tmp_path, token="tok")
    resp = client.post(
        "/api/tasks/nonexistent/cancel",
        headers={
            "X-AhaDiff-Token": "tok",
            "origin": "http://localhost:8765",
        },
    )
    assert resp.status_code == 404


def test_progress_sse_not_found(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.get("/api/tasks/nonexistent/progress")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    payload = _parse_sse_data(body)
    evt = TaskProgressEvent.model_validate(payload)
    assert evt.event == "error"
    assert evt.data == {"error": "task not found"}


def test_progress_sse_emits_contract_envelope_for_terminal_task(tmp_path: Path) -> None:
    info = TaskInfo(
        task_id="task-1",
        task_type="learn",
        status=TaskStatus.COMPLETED,
        progress=TaskProgress(current=10, total=10, message="done"),
        result={"run_id": "run-1", "status": "keep", "overall": 88.0, "verdict": "PASS"},
        created_at="2026-05-01T00:00:00+00:00",
        started_at="2026-05-01T00:00:01+00:00",
        completed_at="2026-05-01T00:00:02+00:00",
    )
    runner = _StaticTaskRunner(info)
    app = create_app(ServeState(state_dir=tmp_path, token="tok", task_runner=cast("Any", runner)))
    client = TestClient(app, base_url="http://localhost:8765")

    resp = client.get("/api/tasks/task-1/progress")

    assert resp.status_code == 200
    payload = _parse_sse_data(resp.text)
    evt = TaskProgressEvent.model_validate(payload)
    assert evt.event == "progress"
    assert isinstance(evt.data, TaskInfoResponse)
    assert evt.data.status == "completed"
    assert evt.data.result_summary is not None
    assert evt.data.result_summary.run_id == "run-1"
    assert runner.unpinned is True


def test_get_task_omits_raw_result_and_exposes_result_summary(tmp_path: Path) -> None:
    info = TaskInfo(
        task_id="task-1",
        task_type="learn",
        status=TaskStatus.COMPLETED,
        progress=TaskProgress(current=10, total=10, message="done"),
        result={
            "run_id": "run-1",
            "status": "keep",
            "overall": 88.0,
            "verdict": "PASS",
            "internal_thread_ref": "do-not-expose",
        },
        created_at="2026-05-01T00:00:00+00:00",
    )
    runner = _StaticTaskRunner(info)
    app = create_app(ServeState(state_dir=tmp_path, token="tok", task_runner=cast("Any", runner)))
    client = TestClient(app, base_url="http://localhost:8765")

    resp = client.get("/api/tasks/task-1")

    assert resp.status_code == 200
    body = resp.json()
    TaskInfoResponse.model_validate(body)
    assert "result" not in body
    assert body["result_summary"] == {
        "run_id": "run-1",
        "status": "keep",
        "overall": 88.0,
        "verdict": "PASS",
        "warnings": [],
    }


def test_get_task_exposes_timeout_and_deadline_metadata(tmp_path: Path) -> None:
    info = TaskInfo(
        task_id="task-1",
        task_type="learn",
        status=TaskStatus.PENDING,
        progress=TaskProgress(current=0, total=10, message="queued"),
        created_at="2026-05-01T00:00:00+00:00",
        timeout_seconds=12.5,
        deadline_at="2026-05-01T00:00:12.500000+00:00",
    )
    runner = _StaticTaskRunner(info)
    app = create_app(ServeState(state_dir=tmp_path, token="tok", task_runner=cast("Any", runner)))
    client = TestClient(app, base_url="http://localhost:8765")

    resp = client.get("/api/tasks/task-1")

    assert resp.status_code == 200
    body = resp.json()
    TaskInfoResponse.model_validate(body)
    timeout_seconds = body["timeout_seconds"]
    assert isinstance(timeout_seconds, int | float)
    assert float(timeout_seconds) == 12.5
    assert isinstance(body["deadline_at"], str)
    created_at = _parse_utc_datetime(body["created_at"])
    deadline_at = _parse_utc_datetime(body["deadline_at"])
    assert abs((deadline_at - created_at).total_seconds() - float(timeout_seconds)) <= 0.5


def test_get_task_maps_error_code_to_user_facing_error(tmp_path: Path) -> None:
    info = TaskInfo(
        task_id="task-1",
        task_type="learn",
        status=TaskStatus.FAILED,
        progress=TaskProgress(current=1, total=10, message="failed"),
        error="connection refused: provider.internal.example",
        error_code="network_error",
        created_at="2026-05-01T00:00:00+00:00",
        started_at="2026-05-01T00:00:01+00:00",
        completed_at="2026-05-01T00:00:03+00:00",
    )
    runner = _StaticTaskRunner(info)
    app = create_app(ServeState(state_dir=tmp_path, token="tok", task_runner=cast("Any", runner)))
    client = TestClient(app, base_url="http://localhost:8765")

    resp = client.get("/api/tasks/task-1")

    assert resp.status_code == 200
    body = resp.json()
    TaskInfoResponse.model_validate(body)
    assert body["error"] == "Network connection failed. Check your internet and try again."
    assert body["error_code"] == "network_error"
    assert body["elapsed_seconds"] == 2.0


@pytest.mark.parametrize(
    ("error_code", "expected"),
    [
        ("network_error", "Network connection failed. Check your internet and try again."),
        ("timeout", "Task timed out. Try again or increase the timeout."),
        ("config_error", "raw internal detail"),
        ("permission_error", "Permission denied. Check file or directory permissions."),
        ("claim_error", "raw internal detail"),
        ("lesson_error", "raw internal detail"),
        ("quiz_error", "raw internal detail"),
        ("learnability_error", "Diff was not suitable for learning."),
        ("cancelled", "Task was cancelled."),
        ("internal_error", "raw internal detail"),
        ("unknown_future_code", "An unexpected error occurred."),
    ],
)
def test_user_facing_message_mapping(error_code: str, expected: str) -> None:
    assert _user_facing_message(error_code, "raw internal detail") == expected


@pytest.mark.parametrize(
    ("raw", "should_not_contain"),
    [
        ("/etc/passwd", "/etc/passwd"),
        ("/home/admin/secret/file.txt", "/home/admin"),
        ("C:\\Users\\admin\\Desktop", "C:\\Users\\admin"),
        ("../../secret/data.json", "../../secret"),
        ("\\\\server\\share\\file", "\\\\server"),
        ("http://internal:8080/admin", "internal:8080"),
        ("https://10.0.0.5/api/key", "10.0.0.5"),
    ],
)
def test_sanitize_warning_scrubs_paths(raw: str, should_not_contain: str) -> None:
    sanitized = _sanitize_warning(raw)
    assert should_not_contain not in sanitized


def test_sanitize_warning_truncates_long_input() -> None:
    long_warning = "x" * 300
    sanitized = _sanitize_warning(long_warning)
    assert len(sanitized) <= 201  # 200 + "…"


def test_sanitize_warning_empty_string() -> None:
    assert _sanitize_warning("") == ""


def test_sanitize_warning_no_path() -> None:
    msg = "something went wrong"
    assert _sanitize_warning(msg) == msg


# --- Stable contract tests ---


class TestTaskResultSummary:
    def test_from_learn_result(self) -> None:
        summary = TaskResultSummary(
            run_id="abc123",
            status="keep",
            overall=88.5,
            verdict="PASS",
            warnings=["low coverage"],
        )
        d = summary.model_dump(mode="json")
        assert d["run_id"] == "abc123"
        assert d["overall"] == 88.5
        assert d["warnings"] == ["low coverage"]

    def test_empty_defaults(self) -> None:
        summary = TaskResultSummary()
        d = summary.model_dump(mode="json")
        assert d["run_id"] is None
        assert d["status"] is None
        assert d["overall"] is None
        assert d["verdict"] is None
        assert d["warnings"] == []

    def test_rejects_extra_fields(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TaskResultSummary.model_validate({"run_id": "x", "secret_field": True})


class TestTaskInfoResponseStableFields:
    def test_stable_fields_present(self) -> None:
        info = TaskInfoResponse(
            task_id="abc",
            task_type="learn",
            status="completed",
            progress=TaskProgressResponse(current=10, total=10, message="done"),
            created_at="2026-05-01T00:00:00Z",
            timeout_seconds=600.0,
            deadline_at="2026-05-01T00:10:00Z",
            result_summary=TaskResultSummary(run_id="r1", verdict="PASS"),
        )
        d = info.model_dump(mode="json")
        stable_keys = {
            "task_id",
            "task_type",
            "status",
            "progress",
            "error",
            "error_code",
            "recovery_hint",
            "created_at",
            "started_at",
            "completed_at",
            "elapsed_seconds",
            "timeout_seconds",
            "deadline_at",
            "result_summary",
        }
        for key in stable_keys:
            assert key in d, f"stable field {key} missing"

    def test_result_summary_null_when_pending(self) -> None:
        info = TaskInfoResponse(
            task_id="abc",
            task_type="learn",
            status="pending",
            progress=TaskProgressResponse(current=0, total=0, message=""),
            created_at="2026-05-01T00:00:00Z",
        )
        d = info.model_dump(mode="json")
        assert d["result_summary"] is None


class TestTaskProgressEvent:
    def test_progress_event(self) -> None:
        evt = TaskProgressEvent(
            event="progress",
            data=TaskInfoResponse(
                task_id="abc",
                task_type="learn",
                status="running",
                progress=TaskProgressResponse(current=3, total=10, message="step 3"),
                created_at="2026-05-01T00:00:00Z",
            ),
        )
        assert evt.event == "progress"
        assert isinstance(evt.data, TaskInfoResponse)

    def test_error_event(self) -> None:
        evt = TaskProgressEvent(
            event="error",
            data={"error": "task not found"},
        )
        assert evt.event == "error"
        assert evt.data == {"error": "task not found"}


# --- Request timeout middleware tests ---


class TestRequestTimeoutRouting:
    def test_default_timeout_for_normal_endpoint(self) -> None:
        assert _request_timeout_for("/api/runs") == 30.0

    def test_long_timeout_for_learn(self) -> None:
        assert _request_timeout_for("/api/learn") == 600.0

    def test_long_timeout_for_task_progress(self) -> None:
        assert _request_timeout_for("/api/tasks/abc123/progress") == 600.0

    def test_long_timeout_for_task_get(self) -> None:
        assert _request_timeout_for("/api/tasks/abc123") == 600.0

    def test_default_timeout_for_healthz(self) -> None:
        assert _request_timeout_for("/healthz") == 30.0


# --- Rate limiting middleware tests ---


class TestRateLimitPathMatching:
    def test_learn_endpoint_is_rate_limited(self) -> None:
        result = _rate_limit_for_path("/api/learn")
        assert result is not None
        limit, key = result
        assert limit == 10
        assert key == "/api/learn"

    def test_learn_trailing_slash_is_not_matched(self) -> None:
        assert _rate_limit_for_path("/api/learn/") is None

    def test_learn_subpath_is_not_matched(self) -> None:
        assert _rate_limit_for_path("/api/learning") is None

    def test_learn_nested_subpath_is_not_matched(self) -> None:
        assert _rate_limit_for_path("/api/learn/not-a-route") is None

    def test_tasks_endpoint_is_not_rate_limited(self) -> None:
        assert _rate_limit_for_path("/api/tasks") is None

    def test_read_endpoint_is_not_rate_limited(self) -> None:
        assert _rate_limit_for_path("/api/runs") is None

    def test_healthz_is_not_rate_limited(self) -> None:
        assert _rate_limit_for_path("/healthz") is None


class TestRateLimitIntegration:
    def test_learn_rate_limit_returns_429(self, tmp_path: Path) -> None:
        app = create_app(ServeState(state_dir=tmp_path, token="tok"))
        client = TestClient(app, base_url="http://localhost:8765")
        headers = {"X-AhaDiff-Token": "tok", "origin": "http://localhost:8765"}
        for _ in range(10):
            client.post("/api/learn", json={}, headers=headers)
        resp = client.post("/api/learn", json={}, headers=headers)
        assert resp.status_code == 429
        body = resp.json()
        assert body["error"] == "rate_limited"
        assert "retry_after" in body
        assert "Retry-After" in resp.headers
        assert resp.headers["Retry-After"] == str(body["retry_after"])

    def test_rate_limit_window_expires(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        current_time = 100.0
        monkeypatch.setattr(middleware_mod.time, "monotonic", lambda: current_time)
        app = create_app(ServeState(state_dir=tmp_path, token="tok"))
        client = TestClient(app, base_url="http://localhost:8765")
        headers = {"X-AhaDiff-Token": "tok", "origin": "http://localhost:8765"}
        for _ in range(10):
            client.post("/api/learn", json={}, headers=headers)
        resp = client.post("/api/learn", json={}, headers=headers)
        assert resp.status_code == 429
        assert resp.json()["retry_after"] == 60

        current_time = 161.0
        resp = client.post("/api/learn", json={}, headers=headers)
        assert resp.status_code != 429

    def test_invalid_token_does_not_consume_learn_quota(self, tmp_path: Path) -> None:
        app = create_app(ServeState(state_dir=tmp_path, token="tok"))
        client = TestClient(app, base_url="http://localhost:8765")
        bad_headers = {"X-AhaDiff-Token": "bad", "origin": "http://localhost:8765"}
        good_headers = {"X-AhaDiff-Token": "tok", "origin": "http://localhost:8765"}
        for _ in range(10):
            assert client.post("/api/learn", json={}, headers=bad_headers).status_code == 403

        resp = client.post("/api/learn", json={}, headers=good_headers)
        assert resp.status_code != 429

    def test_unknown_learn_subpath_does_not_consume_learn_quota(self, tmp_path: Path) -> None:
        app = create_app(ServeState(state_dir=tmp_path, token="tok"))
        client = TestClient(app, base_url="http://localhost:8765")
        headers = {"X-AhaDiff-Token": "tok", "origin": "http://localhost:8765"}
        for _ in range(10):
            resp = client.post("/api/learn/not-a-route", json={}, headers=headers)
            assert resp.status_code == 404

        resp = client.post("/api/learn", json={}, headers=headers)
        assert resp.status_code != 429

    def test_get_requests_not_rate_limited(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        for _ in range(20):
            resp = client.get("/api/tasks")
            assert resp.status_code == 200


# --- Recovery hint tests ---


class TestRecoveryHints:
    def test_network_error_suggests_retry(self, tmp_path: Path) -> None:
        info = TaskInfo(
            task_id="task-1",
            task_type="learn",
            status=TaskStatus.FAILED,
            progress=TaskProgress(current=1, total=10, message="failed"),
            error="connection refused",
            error_code="network_error",
            created_at="2026-05-01T00:00:00+00:00",
        )
        runner = _StaticTaskRunner(info)
        app = create_app(
            ServeState(state_dir=tmp_path, token="tok", task_runner=cast("Any", runner))
        )
        client = TestClient(app, base_url="http://localhost:8765")
        resp = client.get("/api/tasks/task-1")
        body = resp.json()
        assert body["recovery_hint"] == "retry"

    def test_config_error_suggests_check_config(self, tmp_path: Path) -> None:
        info = TaskInfo(
            task_id="task-1",
            task_type="learn",
            status=TaskStatus.FAILED,
            progress=TaskProgress(current=0, total=0, message=""),
            error="missing api key",
            error_code="config_error",
            created_at="2026-05-01T00:00:00+00:00",
        )
        runner = _StaticTaskRunner(info)
        app = create_app(
            ServeState(state_dir=tmp_path, token="tok", task_runner=cast("Any", runner))
        )
        client = TestClient(app, base_url="http://localhost:8765")
        resp = client.get("/api/tasks/task-1")
        body = resp.json()
        assert body["recovery_hint"] == "check_config"

    def test_learnability_error_suggests_dismiss(self, tmp_path: Path) -> None:
        info = TaskInfo(
            task_id="task-1",
            task_type="learn",
            status=TaskStatus.FAILED,
            progress=TaskProgress(current=0, total=0, message=""),
            error="diff too small",
            error_code="learnability_error",
            created_at="2026-05-01T00:00:00+00:00",
        )
        runner = _StaticTaskRunner(info)
        app = create_app(
            ServeState(state_dir=tmp_path, token="tok", task_runner=cast("Any", runner))
        )
        client = TestClient(app, base_url="http://localhost:8765")
        resp = client.get("/api/tasks/task-1")
        body = resp.json()
        assert body["recovery_hint"] == "dismiss"

    def test_no_recovery_hint_for_completed_tasks(self, tmp_path: Path) -> None:
        info = TaskInfo(
            task_id="task-1",
            task_type="learn",
            status=TaskStatus.COMPLETED,
            progress=TaskProgress(current=10, total=10, message="done"),
            result={"run_id": "r1", "overall": 90.0},
            created_at="2026-05-01T00:00:00+00:00",
        )
        runner = _StaticTaskRunner(info)
        app = create_app(
            ServeState(state_dir=tmp_path, token="tok", task_runner=cast("Any", runner))
        )
        client = TestClient(app, base_url="http://localhost:8765")
        resp = client.get("/api/tasks/task-1")
        body = resp.json()
        assert body["recovery_hint"] is None

    def test_recovery_hint_in_stable_contract(self) -> None:
        info = TaskInfoResponse(
            task_id="abc",
            task_type="learn",
            status="failed",
            progress=TaskProgressResponse(current=0, total=0, message=""),
            error="timeout",
            error_code="timeout",
            recovery_hint="retry",
            created_at="2026-05-01T00:00:00Z",
        )
        d = info.model_dump(mode="json")
        assert d["recovery_hint"] == "retry"

    def test_unknown_error_code_falls_back_to_internal_error(self, tmp_path: Path) -> None:
        info = TaskInfo(
            task_id="task-1",
            task_type="learn",
            status=TaskStatus.FAILED,
            progress=TaskProgress(current=0, total=0, message=""),
            error="future failure",
            error_code="future_error_code",
            created_at="2026-05-01T00:00:00+00:00",
        )
        runner = _StaticTaskRunner(info)
        app = create_app(
            ServeState(state_dir=tmp_path, token="tok", task_runner=cast("Any", runner))
        )
        client = TestClient(app, base_url="http://localhost:8765")

        resp = client.get("/api/tasks/task-1")

        body = resp.json()
        assert body["error_code"] == "internal_error"
        assert body["recovery_hint"] == "none"
