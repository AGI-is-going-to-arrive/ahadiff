"""Tests for graphify graph node search (Phase 5C)."""

from __future__ import annotations

import json

from ahadiff.graphify import parse_graph_json_text, search_graph_nodes
from ahadiff.graphify.search import GraphSearchResult


def _make_graph():  # type: ignore[no-untyped-def]
    data = {
        "nodes": [
            {"id": "n1", "label": "task_runner", "file_path": "src/task_runner.py"},
            {"id": "n2", "label": "asyncio", "file_path": "lib/asyncio.py", "kind": "module"},
            {"id": "n3", "label": "freshness_state", "file_path": "src/freshness.py"},
            {"id": "n4", "label": "compute_hash", "file_path": "src/utils.py"},
            {"id": "n5", "label": "", "file_path": "src/empty.py"},
        ],
        "links": [],
    }
    return parse_graph_json_text(json.dumps(data))


class TestSearchGraphNodes:
    def test_exact_match(self) -> None:
        g = _make_graph()
        results = search_graph_nodes(g, "asyncio")
        assert len(results) >= 1
        assert results[0].node_id == "n2"
        assert results[0].score == 1.0

    def test_fuzzy_match(self) -> None:
        g = _make_graph()
        results = search_graph_nodes(g, "TaskRunner", threshold=0.3)
        assert any(r.node_id == "n1" for r in results)

    def test_no_match(self) -> None:
        g = _make_graph()
        results = search_graph_nodes(g, "zzz_nonexistent", threshold=0.9)
        assert results == ()

    def test_empty_query(self) -> None:
        g = _make_graph()
        assert search_graph_nodes(g, "") == ()

    def test_whitespace_query(self) -> None:
        g = _make_graph()
        assert search_graph_nodes(g, "   ") == ()

    def test_empty_graph(self) -> None:
        g = parse_graph_json_text(json.dumps({"nodes": [], "links": []}))
        assert search_graph_nodes(g, "test") == ()

    def test_limit(self) -> None:
        g = _make_graph()
        results = search_graph_nodes(g, "s", threshold=0.1, limit=2)
        assert len(results) <= 2

    def test_result_fields(self) -> None:
        g = _make_graph()
        results = search_graph_nodes(g, "asyncio")
        r = results[0]
        assert isinstance(r, GraphSearchResult)
        assert r.node_id == "n2"
        assert r.label == "asyncio"
        assert r.file_path == "lib/asyncio.py"
        assert r.kind == "module"
        assert r.score > 0.0

    def test_sorted_by_score_descending(self) -> None:
        g = _make_graph()
        results = search_graph_nodes(g, "compute", threshold=0.1)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_labels_excluded(self) -> None:
        g = _make_graph()
        results = search_graph_nodes(g, "", threshold=0.0)
        assert all(r.node_id != "n5" for r in results)

    def test_deduplication(self) -> None:
        data = {
            "nodes": [
                {"id": "n1", "label": "utils", "file_path": "a.py"},
                {"id": "n2", "label": "utils", "file_path": "b.py"},
            ],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        results = search_graph_nodes(g, "utils")
        node_ids = {r.node_id for r in results}
        assert node_ids == {"n1", "n2"}
