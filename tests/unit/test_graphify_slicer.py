"""Tests for graphify subgraph slicing (Phase 5A)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ahadiff.graphify import (
    GraphifyGraph,
    Subgraph,
    extract_subgraph,
    parse_graph_json_text,
    slice_by_files,
)


def _make_graph() -> GraphifyGraph:
    data: dict[str, Any] = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [
            {"id": "n1", "label": "foo", "file_path": "src/foo.py", "kind": "function"},
            {"id": "n2", "label": "bar", "file_path": "src/bar.py", "kind": "class"},
            {"id": "n3", "label": "baz", "file_path": "src/baz.py", "kind": "function"},
            {"id": "n4", "label": "qux", "file_path": "src/qux.py", "kind": "module"},
            {"id": "n5", "label": "isolated", "file_path": "src/isolated.py"},
        ],
        "links": [
            {"source": "n1", "target": "n2", "relation": "calls"},
            {"source": "n2", "target": "n3", "relation": "imports"},
            {"source": "n3", "target": "n4", "relation": "uses"},
        ],
        "hyperedges": [
            {"id": "he1", "nodes": ["n1", "n2"], "relation": "co-change"},
            {"id": "he2", "nodes": ["n3", "n4"], "relation": "co-change"},
        ],
    }
    return parse_graph_json_text(json.dumps(data))


class TestSliceByFiles:
    def test_empty_files(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, [])
        assert sub.node_ids == frozenset()
        assert sub.edge_indices == ()

    def test_empty_graph(self) -> None:
        g = parse_graph_json_text(json.dumps({"nodes": [], "links": []}))
        sub = slice_by_files(g, ["src/foo.py"])
        assert sub.node_ids == frozenset()

    def test_no_matching_files(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["nonexistent.py"])
        assert sub.node_ids == frozenset()

    def test_single_file_hop_0(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["src/foo.py"], hop_depth=0)
        assert sub.node_ids == frozenset({"n1"})
        assert sub.edge_indices == ()

    def test_single_file_hop_1(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["src/foo.py"], hop_depth=1)
        assert "n1" in sub.node_ids
        assert "n2" in sub.node_ids
        assert "n3" not in sub.node_ids

    def test_multi_file(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["src/foo.py", "src/baz.py"], hop_depth=1)
        assert {"n1", "n2", "n3", "n4"}.issubset(sub.node_ids)

    def test_hop_2_reaches_further(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["src/foo.py"], hop_depth=2)
        assert "n1" in sub.node_ids
        assert "n2" in sub.node_ids
        assert "n3" in sub.node_ids

    def test_isolated_node_stays_isolated(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["src/isolated.py"], hop_depth=1)
        assert sub.node_ids == frozenset({"n5"})
        assert sub.edge_indices == ()
        assert sub.hyperedge_indices == ()

    def test_edges_only_between_reachable(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["src/foo.py"], hop_depth=1)
        for idx in sub.edge_indices:
            edge = g.links[idx]
            assert edge.source in sub.node_ids
            assert edge.target in sub.node_ids

    def test_hyperedges_only_when_all_nodes_reachable(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["src/foo.py"], hop_depth=1)
        for he_idx in sub.hyperedge_indices:
            he = g.hyperedges[he_idx]
            assert all(nid in sub.node_ids for nid in he.nodes)

    def test_hyperedge_excluded_when_partial_nodes(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["src/foo.py"], hop_depth=0)
        assert sub.node_ids == frozenset({"n1"})
        assert sub.hyperedge_indices == ()


class TestExtractSubgraph:
    def test_extract_produces_valid_graph(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["src/foo.py"], hop_depth=1)
        extracted = extract_subgraph(g, sub)
        assert isinstance(extracted, GraphifyGraph)
        node_ids = {n.id for n in extracted.nodes}
        assert node_ids == sub.node_ids
        for edge in extracted.links:
            assert edge.source in node_ids
            assert edge.target in node_ids

    def test_extract_empty_subgraph(self) -> None:
        g = _make_graph()
        sub = Subgraph(node_ids=frozenset(), edge_indices=(), hyperedge_indices=())
        extracted = extract_subgraph(g, sub)
        assert extracted.nodes == []
        assert extracted.links == []

    def test_extract_preserves_metadata(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["src/foo.py"], hop_depth=0)
        extracted = extract_subgraph(g, sub)
        assert extracted.directed == g.directed
        assert extracted.graph == g.graph

    def test_extract_deep_copies_graph_metadata(self) -> None:
        g = _make_graph()
        g.graph["nested"] = {"values": ["original"]}
        sub = slice_by_files(g, ["src/foo.py"], hop_depth=0)

        extracted = extract_subgraph(g, sub)
        extracted.graph["nested"]["values"].append("mutated")

        assert g.graph["nested"]["values"] == ["original"]

    def test_extract_ignores_out_of_range_indices(self) -> None:
        g = _make_graph()
        sub = Subgraph(
            node_ids=frozenset({"n1"}),
            edge_indices=(0, 999),
            hyperedge_indices=(0, 999),
        )
        extracted = extract_subgraph(g, sub)
        assert len(extracted.links) == 1
        assert len(extracted.hyperedges) == 1


class TestSliceSelfLoop:
    def test_self_loop_terminates(self) -> None:
        data = {
            "nodes": [
                {"id": "n1", "label": "a", "file_path": "a.py"},
                {"id": "n2", "label": "b", "file_path": "b.py"},
            ],
            "links": [
                {"source": "n1", "target": "n1", "relation": "recursive"},
                {"source": "n1", "target": "n2"},
            ],
        }
        g = parse_graph_json_text(json.dumps(data))
        sub = slice_by_files(g, ["a.py"], hop_depth=1)
        assert "n1" in sub.node_ids
        assert "n2" in sub.node_ids


class TestSliceCycle:
    def test_cycle_terminates(self) -> None:
        data = {
            "nodes": [
                {"id": "n1", "label": "a", "file_path": "a.py"},
                {"id": "n2", "label": "b"},
                {"id": "n3", "label": "c"},
            ],
            "links": [
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n3"},
                {"source": "n3", "target": "n1"},
            ],
        }
        g = parse_graph_json_text(json.dumps(data))
        sub = slice_by_files(g, ["a.py"], hop_depth=1)
        assert sub.node_ids == frozenset({"n1", "n2", "n3"})

    def test_cycle_hop_0_only_seed(self) -> None:
        data = {
            "nodes": [
                {"id": "n1", "label": "a", "file_path": "a.py"},
                {"id": "n2", "label": "b"},
            ],
            "links": [
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n1"},
            ],
        }
        g = parse_graph_json_text(json.dumps(data))
        sub = slice_by_files(g, ["a.py"], hop_depth=0)
        assert sub.node_ids == frozenset({"n1"})


class TestExtractHyperedgeIntegrity:
    def test_extracted_hyperedge_nodes_are_subset_of_graph_nodes(self) -> None:
        g = _make_graph()
        sub = slice_by_files(g, ["src/foo.py", "src/bar.py"], hop_depth=1)
        extracted = extract_subgraph(g, sub)
        node_ids = {n.id for n in extracted.nodes}
        for he in extracted.hyperedges:
            for nid in he.nodes:
                assert nid in node_ids


class TestSubgraphDataclass:
    def test_frozen(self) -> None:
        sub = Subgraph(node_ids=frozenset({"a"}), edge_indices=(0,), hyperedge_indices=())
        with pytest.raises(AttributeError):
            sub.node_ids = frozenset()  # type: ignore[misc]

    def test_equality(self) -> None:
        a = Subgraph(node_ids=frozenset({"x"}), edge_indices=(1,), hyperedge_indices=())
        b = Subgraph(node_ids=frozenset({"x"}), edge_indices=(1,), hyperedge_indices=())
        assert a == b
