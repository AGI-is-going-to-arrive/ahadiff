from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ahadiff.core.errors import InputError
from ahadiff.graphify import (
    FreshnessState,
    compute_freshness,
    parse_graph_json,
    parse_graph_json_text,
    project_freshness,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MINIMAL_GRAPH: dict[str, Any] = {
    "directed": True,
    "multigraph": False,
    "graph": {},
    "nodes": [
        {"id": "n1", "label": "foo", "file_path": "src/foo.py", "kind": "function"},
        {"id": "n2", "label": "bar"},
    ],
    "links": [
        {"source": "n1", "target": "n2", "relation": "calls"},
    ],
}

_FULL_GRAPH: dict[str, Any] = {
    **_MINIMAL_GRAPH,
    "hyperedges": [
        {"id": "he1", "nodes": ["n1", "n2"], "relation": "co-change"},
    ],
}


# ---------------------------------------------------------------------------
# Parser — valid graphs
# ---------------------------------------------------------------------------


class TestParseValid:
    def test_minimal(self) -> None:
        g = parse_graph_json_text(json.dumps(_MINIMAL_GRAPH))
        assert len(g.nodes) == 2
        assert len(g.links) == 1
        assert g.nodes[0].id == "n1"
        assert g.nodes[0].file_path == "src/foo.py"
        assert g.links[0].relation == "calls"

    def test_full_with_hyperedges(self) -> None:
        g = parse_graph_json_text(json.dumps(_FULL_GRAPH))
        assert len(g.hyperedges) == 1
        assert g.hyperedges[0].nodes == ["n1", "n2"]

    def test_missing_optional_keys(self) -> None:
        data: dict[str, Any] = {"nodes": [{"id": "a", "label": "A"}], "links": []}
        g = parse_graph_json_text(json.dumps(data))
        assert g.directed is True
        assert g.multigraph is False
        assert g.hyperedges == []
        assert g.nodes[0].kind is None
        assert g.nodes[0].metadata == {}

    def test_empty_graph(self) -> None:
        g = parse_graph_json_text(json.dumps({"nodes": [], "links": []}))
        assert g.nodes == []
        assert g.links == []

    def test_from_file(self, tmp_path: Path) -> None:
        p = tmp_path / "graph.json"
        p.write_text(json.dumps(_MINIMAL_GRAPH), encoding="utf-8")
        g = parse_graph_json(p)
        assert len(g.nodes) == 2

    def test_node_metadata_preserved(self) -> None:
        data = {
            "nodes": [{"id": "x", "label": "X", "metadata": {"loc": 42}}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes[0].metadata == {"loc": 42}

    def test_edge_metadata_preserved(self) -> None:
        data = {
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "links": [{"source": "a", "target": "b", "metadata": {"weight": 3}}],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert g.links[0].metadata == {"weight": 3}


# ---------------------------------------------------------------------------
# Parser — invalid inputs
# ---------------------------------------------------------------------------


class TestParseInvalid:
    def test_invalid_json(self) -> None:
        with pytest.raises(InputError, match="Invalid graph JSON"):
            parse_graph_json_text("{bad json")

    def test_top_level_array(self) -> None:
        with pytest.raises(InputError, match="must be an object"):
            parse_graph_json_text("[]")

    def test_extra_field_forbidden(self) -> None:
        data = {**_MINIMAL_GRAPH, "extra_key": True}
        with pytest.raises(InputError, match="validation failed"):
            parse_graph_json_text(json.dumps(data))

    def test_missing_required_node_field(self) -> None:
        data = {"nodes": [{"id": "n1"}], "links": []}
        with pytest.raises(InputError, match="validation failed"):
            parse_graph_json_text(json.dumps(data))

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(InputError, match="Cannot read graph file"):
            parse_graph_json(tmp_path / "nonexistent.json")

    def test_nan_rejected(self) -> None:
        raw = '{"nodes": [], "links": [], "graph": {"val": NaN}}'
        with pytest.raises(InputError, match="Invalid graph JSON"):
            parse_graph_json_text(raw)


# ---------------------------------------------------------------------------
# Label sanitization
# ---------------------------------------------------------------------------


class TestLabelSanitization:
    def test_non_dict_nodes_are_ignored_during_prevalidation(self) -> None:
        data = {"nodes": [{"id": "n", "label": "ok"}, "bad-node", 42], "links": []}
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.nodes) == 1
        assert g.nodes[0].id == "n"

    def test_html_tags_stripped(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "<b>bold</b> <script>xss</script>text"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes[0].label == "bold text"

    def test_unclosed_script_tag_is_removed(self) -> None:
        data = {"nodes": [{"id": "n", "label": "safe <script>alert(1)"}], "links": []}
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes[0].label == "safe "

    def test_metadata_strings_are_sanitized(self) -> None:
        data = {
            "nodes": [
                {
                    "id": "n",
                    "label": "label",
                    "metadata": {"summary": "<style>bad</style><b>kept</b>"},
                }
            ],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes[0].metadata["summary"] == "kept"

    def test_metadata_keys_are_sanitized(self) -> None:
        data = {
            "nodes": [
                {
                    "id": "n",
                    "label": "label",
                    "metadata": {"<script>bad</script><b>summary</b>": "kept"},
                }
            ],
            "links": [],
        }

        g = parse_graph_json_text(json.dumps(data))

        assert g.nodes[0].metadata == {"summary": "kept"}

    def test_long_label_truncated(self) -> None:
        long_label = "A" * 1000
        data = {"nodes": [{"id": "n", "label": long_label}], "links": []}
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.nodes[0].label) == 500

    def test_normal_label_unchanged(self) -> None:
        data = {"nodes": [{"id": "n", "label": "my_function"}], "links": []}
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes[0].label == "my_function"

    def test_empty_label_ok(self) -> None:
        data = {"nodes": [{"id": "n", "label": ""}], "links": []}
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes[0].label == ""


# ---------------------------------------------------------------------------
# Freshness — compute
# ---------------------------------------------------------------------------


class TestComputeFreshness:
    def test_current(self) -> None:
        assert compute_freshness("abc", "abc", 0) == FreshnessState.CURRENT

    def test_recent_at_threshold(self) -> None:
        assert compute_freshness("old", "new", 5) == FreshnessState.RECENT

    def test_recent_below_threshold(self) -> None:
        assert compute_freshness("old", "new", 3) == FreshnessState.RECENT

    def test_stale(self) -> None:
        assert compute_freshness("old", "new", 20) == FreshnessState.STALE

    def test_stale_at_boundary(self) -> None:
        assert compute_freshness("old", "new", 50) == FreshnessState.STALE

    def test_outdated(self) -> None:
        assert compute_freshness("old", "new", 51) == FreshnessState.OUTDATED

    def test_outdated_large(self) -> None:
        assert compute_freshness("old", "new", 500) == FreshnessState.OUTDATED

    def test_unknown_no_graph_commit(self) -> None:
        assert compute_freshness(None, "head", 0) == FreshnessState.UNKNOWN

    def test_unknown_no_count(self) -> None:
        assert compute_freshness("old", "new", None) == FreshnessState.UNKNOWN

    def test_unknown_negative_count(self) -> None:
        assert compute_freshness("old", "new", -1) == FreshnessState.UNKNOWN


# ---------------------------------------------------------------------------
# Freshness — projection
# ---------------------------------------------------------------------------


class TestProjectFreshness:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (FreshnessState.CURRENT, "fresh"),
            (FreshnessState.RECENT, "fresh"),
            (FreshnessState.STALE, "stale"),
            (FreshnessState.OUTDATED, "stale"),
            (FreshnessState.UNKNOWN, "stale"),
            (FreshnessState.UNAVAILABLE, "unavailable"),
            (FreshnessState.DISABLED, "disabled"),
        ],
    )
    def test_projection(self, state: FreshnessState, expected: str) -> None:
        assert project_freshness(state) == expected

    def test_all_states_covered(self) -> None:
        for state in FreshnessState:
            result = project_freshness(state)
            assert result in ("fresh", "stale", "unavailable", "disabled")
