"""Tests for GET /api/search endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from ahadiff.contracts.serve_runtime import SearchResponse
from ahadiff.review.database import initialize_review_db
from ahadiff.serve.app import create_app
from ahadiff.serve.state import ServeState

if TYPE_CHECKING:
    from pathlib import Path


_AUTH = {"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"}


def _client(state_dir: Path) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token="test-token", locale="en"))
    return TestClient(app, base_url="http://localhost:8765")


def test_search_without_token_returns_403(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/search")

    assert response.status_code == 401


def test_search_empty_query_returns_empty_results(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/search?q=", headers=_AUTH)

    assert response.status_code == 200
    data = response.json()
    SearchResponse.model_validate(data)
    assert data == {"results": [], "next_cursor": None}


def test_search_valid_query_with_empty_db_returns_empty_results(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    client = _client(state_dir)

    response = client.get("/api/search?q=timeout", headers=_AUTH)

    assert response.status_code == 200
    data = response.json()
    SearchResponse.model_validate(data)
    assert data == {"results": [], "next_cursor": None}


def test_search_response_schema_includes_expected_fields(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/search?q=missing", headers=_AUTH)

    assert response.status_code == 200
    data = response.json()
    SearchResponse.model_validate(data)
    assert set(data) == {"results", "next_cursor"}
    assert isinstance(data["results"], list)
    assert data["next_cursor"] is None
