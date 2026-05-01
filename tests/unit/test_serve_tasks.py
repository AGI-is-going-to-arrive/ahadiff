from __future__ import annotations

import json
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
from ahadiff.serve.middleware import _request_timeout_for  # pyright: ignore[reportPrivateUsage]
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
        ("config_error", "Configuration error. Check your provider settings."),
        ("permission_error", "Permission denied. Check file or directory permissions."),
        ("claim_error", "Failed to extract or verify claims from the diff."),
        ("lesson_error", "Failed to generate lesson content."),
        ("quiz_error", "Failed to generate quiz content."),
        ("learnability_error", "Diff was not suitable for learning."),
        ("cancelled", "Task was cancelled."),
        ("internal_error", "Internal error occurred."),
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
            "created_at",
            "started_at",
            "completed_at",
            "elapsed_seconds",
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
