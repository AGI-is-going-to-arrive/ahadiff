from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from starlette.testclient import TestClient

from ahadiff.contracts.serve_runtime import TaskListResponse
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
    assert '"error"' in body
    assert "task not found" in body
