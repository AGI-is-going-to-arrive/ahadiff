"""Tests for graphify concept linker (Phase 5B)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ahadiff.graphify import ConceptLink, link_concepts, parse_graph_json_text

if TYPE_CHECKING:
    from ahadiff.graphify.models import GraphifyGraph


def _make_graph() -> GraphifyGraph:
    data: dict[str, object] = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [
            {"id": "n1", "label": "task_runner", "file_path": "src/task_runner.py"},
            {"id": "n2", "label": "asyncio", "file_path": "lib/asyncio.py"},
            {"id": "n3", "label": "freshness_state", "file_path": "src/freshness.py"},
            {"id": "n4", "label": "unrelated_thing", "file_path": "src/other.py"},
        ],
        "links": [
            {"source": "n1", "target": "n2", "relation": "imports"},
        ],
    }
    return parse_graph_json_text(json.dumps(data))


class TestLinkConcepts:
    def test_exact_match_links(self) -> None:
        g = _make_graph()
        links = link_concepts(g, ["asyncio"])
        assert len(links) >= 1
        assert any(lnk.concept == "asyncio" and lnk.node_id == "n2" for lnk in links)

    def test_fuzzy_match_links(self) -> None:
        g = _make_graph()
        links = link_concepts(g, ["TaskRunner"], threshold=0.4)
        assert any(lnk.node_id == "n1" for lnk in links)

    def test_no_match_below_threshold(self) -> None:
        g = _make_graph()
        links = link_concepts(g, ["completely_alien_concept"], threshold=0.9)
        assert links == ()

    def test_empty_concepts(self) -> None:
        g = _make_graph()
        assert link_concepts(g, []) == ()

    def test_empty_graph(self) -> None:
        g = parse_graph_json_text(json.dumps({"nodes": [], "links": []}))
        assert link_concepts(g, ["foo"]) == ()

    def test_link_has_correct_fields(self) -> None:
        g = _make_graph()
        links = link_concepts(g, ["asyncio"])
        lnk = next(item for item in links if item.node_id == "n2")
        assert isinstance(lnk, ConceptLink)
        assert lnk.concept == "asyncio"
        assert lnk.node_label == "asyncio"
        assert lnk.file_path == "lib/asyncio.py"
        assert lnk.score == 1.0

    def test_multiple_concepts(self) -> None:
        g = _make_graph()
        links = link_concepts(g, ["asyncio", "FreshnessState"], threshold=0.4)
        linked_concepts = {lnk.concept for lnk in links}
        assert "asyncio" in linked_concepts
        assert "FreshnessState" in linked_concepts

    def test_deduplication(self) -> None:
        g = _make_graph()
        links = link_concepts(g, ["asyncio", "asyncio"])
        asyncio_links = [lnk for lnk in links if lnk.concept == "asyncio" and lnk.node_id == "n2"]
        assert len(asyncio_links) == 1

    def test_threshold_parameter(self) -> None:
        g = _make_graph()
        strict = link_concepts(g, ["task"], threshold=0.9)
        lenient = link_concepts(g, ["task"], threshold=0.1)
        assert len(lenient) >= len(strict)

    def test_duplicate_labels_link_all_nodes(self) -> None:
        data = {
            "nodes": [
                {"id": "n1", "label": "utils", "file_path": "src/utils.py"},
                {"id": "n2", "label": "utils", "file_path": "lib/utils.py"},
                {"id": "n3", "label": "other", "file_path": "src/other.py"},
            ],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        links = link_concepts(g, ["utils"])
        node_ids = {lnk.node_id for lnk in links}
        assert node_ids == {"n1", "n2"}
        file_paths = {lnk.file_path for lnk in links}
        assert file_paths == {"src/utils.py", "lib/utils.py"}
