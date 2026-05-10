"""Tests for POST /api/db/check endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from ahadiff.review.database import CURRENT_SCHEMA_VERSION, initialize_review_db
from ahadiff.serve.app import create_app
from ahadiff.serve.state import ServeState

if TYPE_CHECKING:
    from pathlib import Path


_AUTH = {"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"}
_ORIGIN = {"origin": "http://localhost:8765"}


def _client(state_dir: Path) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token="test-token", locale="en"))
    return TestClient(app, base_url="http://localhost:8765")


def test_db_check_without_token_returns_403(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.post("/api/db/check", headers=_ORIGIN)

    assert response.status_code == 403
    assert response.json()["error"] == "write route requires a valid X-AhaDiff-Token header"


def test_db_check_with_token_returns_valid_response(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    client = _client(state_dir)

    response = client.post("/api/db/check", headers=_AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "healthy": True,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "quick_check": "ok",
        "event_count": 0,
        "card_count": 0,
    }


def test_db_check_response_schema_includes_expected_fields(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    client = _client(state_dir)

    response = client.post("/api/db/check", headers=_AUTH)

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"healthy", "schema_version", "quick_check", "event_count", "card_count"}
    assert isinstance(data["healthy"], bool)
    assert isinstance(data["schema_version"], int)
    assert isinstance(data["quick_check"], str)
    assert isinstance(data["event_count"], int)
    assert isinstance(data["card_count"], int)
