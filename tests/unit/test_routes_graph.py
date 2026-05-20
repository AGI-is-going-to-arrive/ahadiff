"""Tests for GET /api/graph/status endpoint (Phase 5F)."""

from __future__ import annotations

import json
import subprocess
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from ahadiff.contracts.serve_runtime import (
    ConceptGraphEdge,
    ConceptGraphResponse,
    GraphProvenance,
    GraphStatusResponse,
)
from ahadiff.serve import ServeState, create_app
from ahadiff.serve.routes_graph import api_relative_path

if TYPE_CHECKING:
    from pathlib import Path


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "core.quotePath=false", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )


def _client(state_dir: Path, *, token: str = "test-token") -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token=token, locale="en"))
    return TestClient(app, base_url="http://localhost:8765")


def _write_imported_graph_with_provenance(
    state_dir: Path,
    provenance: dict[str, str],
) -> None:
    imported_dir = state_dir / "graphify"
    imported_dir.mkdir()
    (imported_dir / "graph.json").write_text(
        json.dumps({"nodes": [{"id": "n1", "label": "foo"}], "links": []}),
        encoding="utf-8",
    )
    (imported_dir / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")


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
        (graph_dir / "graph.json").write_text(
            json.dumps({"nodes": [{"id": "raw", "label": "raw"}], "links": []}),
            encoding="utf-8",
        )
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        graph_data = {
            "nodes": [
                {"id": "n1", "label": "foo", "file_path": "a.py"},
                {"id": "n2", "label": "bar", "file_path": "b.py"},
            ],
            "links": [
                {"source": "n1", "target": "n2"},
            ],
        }
        (imported_dir / "graph.json").write_text(
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
        assert data["source_path"] == ".ahadiff/graphify/graph.json"

    def test_source_path_uses_posix_separators_for_api_stability(self) -> None:
        path = PureWindowsPath("C:/repo/.ahadiff/graphify/graph.json")
        root = PureWindowsPath("C:/repo")

        assert api_relative_path(path, root) == ".ahadiff/graphify/graph.json"

    def test_raw_graph_without_imported_artifact_is_not_served(self, tmp_path: Path) -> None:
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
        assert data["has_graph"] is False
        assert data["node_count"] == 0
        assert data["edge_count"] == 0
        assert data["source_path"] is None

    def test_malformed_imported_graph_returns_zero_counts(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        graph_dir = tmp_path / "graphify-out"
        graph_dir.mkdir()
        (graph_dir / "graph.json").write_text(
            json.dumps({"nodes": [], "links": []}),
            encoding="utf-8",
        )
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        (imported_dir / "graph.json").write_text("not json", encoding="utf-8")

        client = _client(state_dir)
        resp = client.get("/api/graph/status")
        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["source_exists"] is True
        assert data["has_graph"] is False
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
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        (imported_dir / "graph.json").write_text(
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

    def test_freshness_uses_repo_context(self, tmp_path: Path) -> None:
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.name", "AhaDiff Test")
        _git(tmp_path, "config", "user.email", "test@example.com")
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        graph_dir = tmp_path / "graphify-out"
        graph_dir.mkdir()
        graph_data = {"nodes": [{"id": "n1", "label": "foo"}], "links": []}
        (graph_dir / "graph.json").write_text(
            json.dumps(graph_data),
            encoding="utf-8",
        )
        _git(tmp_path, "add", "graphify-out/graph.json")
        _git(tmp_path, "commit", "-qm", "add graph", "--no-gpg-sign")
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        (imported_dir / "graph.json").write_text(
            json.dumps(graph_data),
            encoding="utf-8",
        )

        client = _client(state_dir)
        resp = client.get("/api/graph/status")

        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["freshness"] == "fresh"

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
            "provenance",
        }
        assert set(data.keys()) == expected_keys

    def test_graph_status_returns_valid_provenance(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        (imported_dir / "graph.json").write_text(
            json.dumps({"nodes": [{"id": "n1", "label": "foo"}], "links": []}),
            encoding="utf-8",
        )
        provenance = {
            "graph_sha256": "a" * 64,
            "import_time": "2026-05-02T00:00:00+00:00",
            "parser_version": "1.0",
        }
        (imported_dir / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")

        client = _client(state_dir)
        resp = client.get("/api/graph/status")

        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["has_graph"] is True
        assert data["provenance"] == provenance


class TestGraphRefresh:
    def test_graph_refresh_uses_configured_graph_node_limit(
        self,
        tmp_path: Path,
    ) -> None:
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.name", "AhaDiff Test")
        _git(tmp_path, "config", "user.email", "test@example.com")
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        (state_dir / "config.toml").write_text(
            "[graph]\nmax_nodes_import = 1000\n",
            encoding="utf-8",
        )
        graph_dir = tmp_path / "graphify-out"
        graph_dir.mkdir()
        (graph_dir / "graph.json").write_text(
            json.dumps(
                {
                    "nodes": [{"id": f"n{i}", "label": f"Node {i}"} for i in range(1001)],
                    "links": [],
                }
            ),
            encoding="utf-8",
        )
        _git(tmp_path, "add", "graphify-out/graph.json")
        _git(tmp_path, "commit", "-qm", "add graph", "--no-gpg-sign")

        resp = _client(state_dir).post(
            "/api/graph/refresh",
            headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        )

        assert resp.status_code == 413
        body = resp.json()
        assert body["error_code"] == "GRAPH_NODE_LIMIT"
        assert body["error"] == "graph node import exceeds limit: 1001 nodes > 1000 max"
        assert body["details"] == {"count": 1001, "limit": 1000}

    def test_graph_status_drops_malformed_provenance(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        (imported_dir / "graph.json").write_text(
            json.dumps({"nodes": [{"id": "n1", "label": "foo"}], "links": []}),
            encoding="utf-8",
        )
        (imported_dir / "provenance.json").write_text(
            json.dumps(
                {
                    "graph_sha256": "A" * 64,
                    "import_time": "2026-05-02T00:00:00+00:00",
                    "parser_version": "1.0",
                }
            ),
            encoding="utf-8",
        )

        client = _client(state_dir)
        resp = client.get("/api/graph/status")

        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["has_graph"] is True
        assert data["provenance"] is None

    def test_graph_status_round_trips_strong_graph_provenance(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        provenance = {
            "graph_sha256": "0123456789abcdef" * 4,
            "import_time": "2026-05-02T00:00:00+00:00",
            "parser_version": "1.0",
        }
        _write_imported_graph_with_provenance(state_dir, provenance)

        resp = _client(state_dir).get("/api/graph/status")

        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["provenance"] == provenance

    def test_graph_status_drops_provenance_with_short_sha(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        _write_imported_graph_with_provenance(
            state_dir,
            {
                "graph_sha256": "a" * 63,
                "import_time": "2026-05-02T00:00:00+00:00",
                "parser_version": "1.0",
            },
        )

        resp = _client(state_dir).get("/api/graph/status")

        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["provenance"] is None

    def test_graph_status_drops_provenance_with_non_hex_sha(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        _write_imported_graph_with_provenance(
            state_dir,
            {
                "graph_sha256": "z" * 64,
                "import_time": "2026-05-02T00:00:00+00:00",
                "parser_version": "1.0",
            },
        )

        resp = _client(state_dir).get("/api/graph/status")

        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["provenance"] is None

    def test_graph_status_drops_provenance_with_invalid_import_time(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        _write_imported_graph_with_provenance(
            state_dir,
            {
                "graph_sha256": "a" * 64,
                "import_time": "not-a-datetime",
                "parser_version": "1.0",
            },
        )

        resp = _client(state_dir).get("/api/graph/status")

        assert resp.status_code == 200
        data = resp.json()
        GraphStatusResponse.model_validate(data)
        assert data["provenance"] is None

    def test_graph_provenance_accepts_strong_values(self) -> None:
        provenance = GraphProvenance.model_validate(
            {
                "graph_sha256": "0123456789abcdef" * 4,
                "import_time": "2026-05-02T00:00:00+00:00",
                "parser_version": "1.0",
            }
        )

        assert provenance.graph_sha256 == "0123456789abcdef" * 4

    def test_graph_provenance_rejects_malformed_sha(self) -> None:
        with pytest.raises(ValidationError):
            GraphProvenance.model_validate(
                {
                    "graph_sha256": "g" * 64,
                    "import_time": "2026-05-02T00:00:00+00:00",
                    "parser_version": "1.0",
                }
            )

    def test_graph_provenance_rejects_invalid_import_time(self) -> None:
        with pytest.raises(ValidationError):
            GraphProvenance.model_validate(
                {
                    "graph_sha256": "a" * 64,
                    "import_time": "not-a-datetime",
                    "parser_version": "1.0",
                }
            )

    def test_graph_status_rejects_unknown_freshness_literal(self) -> None:
        with pytest.raises(ValidationError):
            GraphStatusResponse.model_validate(
                {
                    "enabled": True,
                    "source_exists": True,
                    "has_graph": True,
                    "freshness": "ok",
                    "node_count": 1,
                    "edge_count": 0,
                    "source_path": ".ahadiff/graphify/graph.json",
                }
            )

    def test_graph_status_rejects_negative_counts(self) -> None:
        for patch in (
            {"node_count": -1},
            {"edge_count": -1},
            {"node_count": True},
            {"edge_count": "1"},
        ):
            with pytest.raises(ValidationError):
                GraphStatusResponse.model_validate(
                    {
                        "enabled": True,
                        "source_exists": True,
                        "has_graph": True,
                        "freshness": "fresh",
                        "node_count": 1,
                        "edge_count": 0,
                        "source_path": ".ahadiff/graphify/graph.json",
                        **patch,
                    }
                )

    def test_concept_graph_edge_rejects_invalid_weight(self) -> None:
        for weight in [float("nan"), float("inf"), float("-inf"), -1, 0, 1e308, True, "1"]:
            with pytest.raises(ValidationError):
                ConceptGraphEdge.model_validate(
                    {
                        "id": "e1",
                        "source": "n1",
                        "target": "n2",
                        "weight": weight,
                    }
                )

    def test_concept_graph_edge_rejects_invalid_confidence(self) -> None:
        edge = ConceptGraphEdge.model_validate(
            {
                "id": "e1",
                "source": "n1",
                "target": "n2",
                "confidence": "EXTRACTED",
            }
        )
        assert edge.confidence == "EXTRACTED"

        for confidence in ["BROKEN", "", 1, True]:
            with pytest.raises(ValidationError):
                ConceptGraphEdge.model_validate(
                    {
                        "id": "e1",
                        "source": "n1",
                        "target": "n2",
                        "confidence": confidence,
                    }
                )

    def test_concept_graph_endpoint_returns_nodes_and_edges(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        graph_dir = tmp_path / "graphify-out"
        graph_dir.mkdir()
        (graph_dir / "graph.json").write_text(
            json.dumps({"nodes": [{"id": "n1", "label": "foo"}], "links": []}),
            encoding="utf-8",
        )
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        (imported_dir / "graph.json").write_text(
            json.dumps(
                {
                    "nodes": [
                        {
                            "id": "n1",
                            "label": "<script>alert(1)</script>Foo",
                            "file_path": "src/foo.py",
                            "kind": "symbol",
                            "metadata": {"weight": 2},
                        },
                        {"id": "n2", "label": "Bar", "file_path": "src/bar.py"},
                        {"id": "n3", "label": "Baz", "file_path": "src/baz.py"},
                    ],
                    "links": [
                        {
                            "source": "n1",
                            "target": "n2",
                            "relation": "calls",
                            "weight": 1.5,
                            "confidence": "EXTRACTED",
                        },
                        {
                            "source": "n2",
                            "target": "n3",
                            "relation": "imports",
                            "weight": False,
                            "confidence": "BROKEN",
                        },
                        {
                            "source": "n3",
                            "target": "n1",
                            "relation": "observes",
                            "weight": True,
                            "confidence": 1,
                        },
                        {"source": "n1", "target": "n3", "relation": "uses", "weight": 1e308},
                    ],
                }
            ),
            encoding="utf-8",
        )
        client = _client(state_dir)

        resp = client.get("/api/graph/concepts")

        assert resp.status_code == 200
        data = resp.json()
        ConceptGraphResponse.model_validate(data)
        assert data["status"]["has_graph"] is True
        assert [node["id"] for node in data["nodes"]] == ["n1", "n2", "n3"]
        assert data["nodes"][0]["name"] == "Foo"
        assert data["edges"] == [
            {
                "id": "n1->n2:0",
                "source": "n1",
                "target": "n2",
                "relation": "calls",
                "weight": 1.5,
                "confidence": "EXTRACTED",
            },
            {
                "id": "n2->n3:1",
                "source": "n2",
                "target": "n3",
                "relation": "imports",
                "weight": 1.0,
            },
            {
                "id": "n3->n1:2",
                "source": "n3",
                "target": "n1",
                "relation": "observes",
                "weight": 1.0,
            },
            {
                "id": "n1->n3:3",
                "source": "n1",
                "target": "n3",
                "relation": "uses",
                "weight": 3.0,
            },
        ]
        assert data["truncated"] is False

    def test_concept_graph_status_includes_valid_provenance(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        (imported_dir / "graph.json").write_text(
            json.dumps({"nodes": [{"id": "n1", "label": "foo"}], "links": []}),
            encoding="utf-8",
        )
        provenance = {
            "graph_sha256": "b" * 64,
            "import_time": "2026-05-02T00:00:00+00:00",
            "parser_version": "1.0",
        }
        (imported_dir / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
        client = _client(state_dir)

        resp = client.get("/api/graph/concepts")

        assert resp.status_code == 200
        data = resp.json()
        ConceptGraphResponse.model_validate(data)
        assert data["status"]["provenance"] == provenance

    def test_concept_graph_endpoint_caps_nodes(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        graph_dir = tmp_path / "graphify-out"
        graph_dir.mkdir()
        (graph_dir / "graph.json").write_text(
            json.dumps({"nodes": [{"id": "n1", "label": "foo"}], "links": []}),
            encoding="utf-8",
        )
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        (imported_dir / "graph.json").write_text(
            json.dumps(
                {
                    "nodes": [
                        {"id": "n1", "label": "One"},
                        {"id": "n2", "label": "Two"},
                    ],
                    "links": [{"source": "n1", "target": "n2"}],
                }
            ),
            encoding="utf-8",
        )
        client = _client(state_dir)

        resp = client.get("/api/graph/concepts?limit=1")

        assert resp.status_code == 200
        data = resp.json()
        ConceptGraphResponse.model_validate(data)
        assert [node["id"] for node in data["nodes"]] == ["n1"]
        assert data["edges"] == []
        assert data["truncated"] is True

    def test_concept_graph_endpoint_includes_focused_node_beyond_limit(
        self, tmp_path: Path
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        (imported_dir / "graph.json").write_text(
            json.dumps(
                {
                    "nodes": [
                        {"id": "n1", "label": "One"},
                        {"id": "n2", "label": "Two"},
                        {"id": "n3", "label": "Three"},
                    ],
                    "links": [
                        {"source": "n1", "target": "n2"},
                        {"source": "n2", "target": "n3"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        client = _client(state_dir)

        resp = client.get("/api/graph/concepts?limit=1&focus=n3")

        assert resp.status_code == 200
        data = resp.json()
        ConceptGraphResponse.model_validate(data)
        assert [node["id"] for node in data["nodes"]] == ["n3"]
        assert data["edges"] == []
        assert data["truncated"] is True

    def test_concept_graph_endpoint_falls_back_when_label_sanitizes_empty(
        self, tmp_path: Path
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        graph_dir = tmp_path / "graphify-out"
        graph_dir.mkdir()
        (graph_dir / "graph.json").write_text(
            json.dumps({"nodes": [{"id": "n1", "label": "foo"}], "links": []}),
            encoding="utf-8",
        )
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        (imported_dir / "graph.json").write_text(
            json.dumps({"nodes": [{"id": "n1", "label": "<script>x</script>"}], "links": []}),
            encoding="utf-8",
        )
        client = _client(state_dir)

        resp = client.get("/api/graph/concepts")

        assert resp.status_code == 200
        data = resp.json()
        ConceptGraphResponse.model_validate(data)
        assert data["nodes"][0]["name"] == "n1"

    def test_concept_graph_parse_failure_clears_provenance_and_source_path(
        self, tmp_path: Path
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        imported_dir = state_dir / "graphify"
        imported_dir.mkdir()
        (imported_dir / "graph.json").write_text("INVALID JSON", encoding="utf-8")
        client = _client(state_dir)

        resp = client.get("/api/graph/concepts")

        assert resp.status_code == 200
        data = resp.json()
        ConceptGraphResponse.model_validate(data)
        assert data["status"]["has_graph"] is False
        assert data["status"]["node_count"] == 0
        assert data["status"]["edge_count"] == 0
        assert data["status"]["source_path"] is None
        assert data["status"]["provenance"] is None
        assert data["nodes"] == []
        assert data["edges"] == []
