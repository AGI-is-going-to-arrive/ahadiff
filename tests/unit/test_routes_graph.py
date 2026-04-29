"""Tests for GET /api/graph/status endpoint (Phase 5F)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from ahadiff.contracts.serve_runtime import GraphStatusResponse
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from pathlib import Path


def _client(state_dir: Path, *, token: str = "test-token") -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token=token, locale="en"))
    return TestClient(app, base_url="http://localhost:8765")


class TestGraphStatus:
    def test_no_graph_returns_disabled(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)
        resp = client.get("/api/graph/status")
        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["has_graph"] is False
        assert data["source_exists"] is False
        assert data["node_count"] == 0
        assert data["edge_count"] == 0

    def test_with_graph_file(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        graph_dir = tmp_path / "graphify-out"
        graph_dir.mkdir()
        graph_data = {
            "nodes": [
                {"id": "n1", "label": "foo", "file_path": "a.py"},
                {"id": "n2", "label": "bar", "file_path": "b.py"},
            ],
            "links": [
                {"source": "n1", "target": "n2"},
            ],
        }
        (graph_dir / "graph.json").write_text(
            json.dumps(graph_data),
            encoding="utf-8",
        )

        client = _client(state_dir)
        resp = client.get("/api/graph/status")
        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["source_exists"] is True
        assert data["has_graph"] is True
        assert data["node_count"] == 2
        assert data["edge_count"] == 1
        assert data["source_path"] == "graphify-out/graph.json"

    def test_malformed_graph_returns_zero_counts(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        graph_dir = tmp_path / "graphify-out"
        graph_dir.mkdir()
        (graph_dir / "graph.json").write_text("not json", encoding="utf-8")

        client = _client(state_dir)
        resp = client.get("/api/graph/status")
        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["source_exists"] is True
        assert data["node_count"] == 0
        assert data["edge_count"] == 0

    def test_empty_graph(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        graph_dir = tmp_path / "graphify-out"
        graph_dir.mkdir()
        (graph_dir / "graph.json").write_text(
            json.dumps({"nodes": [], "links": []}),
            encoding="utf-8",
        )

        client = _client(state_dir)
        resp = client.get("/api/graph/status")
        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["has_graph"] is True
        assert data["node_count"] == 0
        assert data["edge_count"] == 0

    def test_response_fields(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)
        resp = client.get("/api/graph/status")
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        expected_keys = {
            "enabled",
            "source_exists",
            "has_graph",
            "freshness",
            "node_count",
            "edge_count",
            "source_path",
        }
        assert set(data.keys()) == expected_keys
