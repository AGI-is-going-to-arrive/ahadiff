"""Tests for /api/tasks route endpoints."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from starlette.testclient import TestClient

from ahadiff.contracts.serve_runtime import TaskListResponse, TaskProgressEvent
from ahadiff.serve.app import create_app
from ahadiff.serve.state import ServeState

if TYPE_CHECKING:
    from pathlib import Path


_AUTH = {"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"}
_ORIGIN = {"origin": "http://localhost:8765"}


def _client(state_dir: Path) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token="test-token", locale="en"))
    return TestClient(app, base_url="http://localhost:8765")


def _parse_sse_data(body: str) -> dict[str, object]:
    for line in body.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line.removeprefix("data: "))
            assert isinstance(payload, dict)
            return cast("dict[str, object]", payload)
    raise AssertionError(f"SSE body has no data line: {body}")


def test_tasks_list_empty(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/tasks")

    assert response.status_code == 200
    data = response.json()
    TaskListResponse.model_validate(data)
    assert data == {"tasks": []}


def test_task_detail_not_found(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/tasks/missing-task")

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "status": 404}


def test_task_cancel_without_token_returns_403(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.post("/api/tasks/missing-task/cancel", headers=_ORIGIN)

    assert response.status_code == 403
    assert response.json()["error"] == "write route requires a valid X-AhaDiff-Token header"


def test_task_cancel_with_token_returns_not_found_for_missing_task(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.post("/api/tasks/missing-task/cancel", headers=_AUTH)

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "status": 404}


def test_task_progress_sse_not_found(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/tasks/missing-task/progress")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    data = _parse_sse_data(response.text)
    event = TaskProgressEvent.model_validate(data)
    assert event.event == "error"
    assert event.data == {"error": "task not found"}
