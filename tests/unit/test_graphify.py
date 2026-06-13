from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import ahadiff.graphify as graphify_package
import ahadiff.graphify.parser as graphify_parser_module
from ahadiff.core.errors import InputError
from ahadiff.git.repo import GitRepo
from ahadiff.graphify import (
    FreshnessState,
    GraphifyEdge,
    GraphifyGraph,
    GraphifyHyperedge,
    GraphifyNode,
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
# Model/export contracts
# ---------------------------------------------------------------------------


class TestGraphifyModelContracts:
    def test_models_forbid_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            GraphifyNode.model_validate({"id": "n1", "label": "Node", "unexpected": True})
        with pytest.raises(ValidationError):
            GraphifyEdge.model_validate({"source": "n1", "target": "n2", "unexpected": True})
        with pytest.raises(ValidationError):
            GraphifyHyperedge.model_validate({"id": "he1", "nodes": ["n1"], "unexpected": True})

    def test_graph_default_collections_are_isolated(self) -> None:
        first = GraphifyGraph()
        second = GraphifyGraph()

        first.nodes.append(GraphifyNode(id="n1", label="Node"))
        first.links.append(GraphifyEdge(source="n1", target="n1"))
        first.hyperedges.append(GraphifyHyperedge(id="he1", nodes=["n1"]))
        first.graph["source"] = "first"

        assert second.nodes == []
        assert second.links == []
        assert second.hyperedges == []
        assert second.graph == {}

    def test_public_exports_include_graphify_models(self) -> None:
        for name in ("GraphifyNode", "GraphifyEdge", "GraphifyHyperedge", "GraphifyGraph"):
            assert name in graphify_package.__all__
            assert getattr(graphify_package, name) is globals()[name]


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

    def test_loaded_graph_data_matches_text_parser(self) -> None:
        via_text = parse_graph_json_text(json.dumps(_MINIMAL_GRAPH))
        via_data = graphify_parser_module.parse_graph_json_data(_MINIMAL_GRAPH)

        assert via_data == via_text

    def test_from_file(self, tmp_path: Path) -> None:
        p = tmp_path / "graph.json"
        p.write_text(json.dumps(_MINIMAL_GRAPH), encoding="utf-8")
        g = parse_graph_json(p)
        assert len(g.nodes) == 2

    def test_node_metadata_preserved(self) -> None:
        data: dict[str, Any] = {
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

    def test_real_graphify_flat_fields_are_normalized(self) -> None:
        data: dict[str, Any] = {
            "directed": False,
            "multigraph": False,
            "graph": {},
            "nodes": [
                {
                    "id": "client",
                    "label": "Client",
                    "file_type": "code",
                    "source_file": "worked/httpx/raw/client.py",
                },
                {
                    "id": "client_timeout",
                    "label": "Timeout",
                    "file_type": "code",
                    "source_file": "worked/httpx/raw/client.py",
                    "source_location": "L16",
                    "community": 1,
                    "norm_label": "timeout",
                },
            ],
            "links": [
                {
                    "source": "client",
                    "target": "client_timeout",
                    "relation": "contains",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": "worked/httpx/raw/client.py",
                    "weight": 1.0,
                }
            ],
            "hyperedges": [
                {
                    "id": "auth_flow",
                    "label": "Auth Flow",
                    "nodes": ["client", "client_timeout"],
                    "confidence_score": 0.75,
                    "source_file": "worked/httpx/raw/client.py",
                }
            ],
        }

        g = parse_graph_json_text(json.dumps(data))

        timeout_node = next(n for n in g.nodes if n.id == "client_timeout")
        assert timeout_node.file_path == "worked/httpx/raw/client.py"
        assert timeout_node.kind == "code"
        assert timeout_node.metadata == {
            "source_location": "L16",
            "community": 1,
            "norm_label": "timeout",
        }
        assert g.links[0].relation == "contains"
        assert g.links[0].metadata["confidence"] == "EXTRACTED"
        assert g.links[0].metadata["confidence_score"] == 1.0
        assert g.hyperedges[0].metadata["label"] == "Auth Flow"

    def test_edges_alias_is_normalized_to_links(self) -> None:
        data = {
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"source": "a", "target": "b", "type": "imports"}],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.links) == 1
        assert g.links[0].relation == "imports"


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

    def test_loaded_graph_data_rejects_non_finite_numbers(self) -> None:
        data: dict[str, Any] = {
            "nodes": [
                {
                    "id": "n1",
                    "label": "Node",
                    "metadata": {"score": float("nan")},
                }
            ],
            "links": [],
        }

        with pytest.raises(InputError, match="non-finite"):
            graphify_parser_module.parse_graph_json_data(data)

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

    def test_symlink_file_rejected(self, tmp_path: Path) -> None:
        if not hasattr(os, "symlink"):
            pytest.skip("os.symlink is unavailable on this platform")
        target = tmp_path / "target.json"
        target.write_text(json.dumps(_MINIMAL_GRAPH), encoding="utf-8")
        link = tmp_path / "graph.json"
        os.symlink(target, link)

        with pytest.raises(InputError, match="must not be a symlink"):
            parse_graph_json(link)

    def test_lstat_open_symlink_swap_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if not hasattr(os, "symlink"):
            pytest.skip("os.symlink is unavailable on this platform")
        graph = tmp_path / "graph.json"
        graph.write_text(json.dumps(_MINIMAL_GRAPH), encoding="utf-8")
        replacement = tmp_path / "replacement.json"
        replacement.write_text(json.dumps(_MINIMAL_GRAPH), encoding="utf-8")

        original_open = graphify_parser_module.os.open
        swapped = False

        def swapping_open(
            path: str,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal swapped
            if not swapped and Path(path) == graph and dir_fd is None:
                graph.unlink()
                os.symlink(replacement, graph)
                swapped = True
            if dir_fd is None:
                return original_open(path, flags, mode)
            return original_open(path, flags, mode, dir_fd=dir_fd)

        monkeypatch.setattr(graphify_parser_module.os, "open", swapping_open)

        with pytest.raises(InputError, match="symlink|changed during validation"):
            parse_graph_json(graph)

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

    def test_html_entities_normalized_to_plain_text(self) -> None:
        data = {"nodes": [{"id": "n", "label": "a & b"}], "links": []}
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes[0].label == "a & b"

    def test_pre_escaped_entities_normalized_to_plain_text(self) -> None:
        data = {"nodes": [{"id": "n", "label": "Tom &amp; Jerry"}], "links": []}
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes[0].label == "Tom & Jerry"

    def test_javascript_uri_stripped(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "javascript:alert(1)"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "javascript:" not in g.nodes[0].label

    def test_entity_obfuscated_javascript_uri_stripped(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "java&#x73;cript:alert(1)"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "javascript:" not in g.nodes[0].label

    def test_nested_entity_obfuscated_javascript_uri_stripped(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "java&amp;#x73;cript:alert(1)"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "javascript:" not in g.nodes[0].label

    def test_data_uri_stripped(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "data:text/html,<script>xss</script>"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "data:" not in g.nodes[0].label

    def test_null_byte_in_label_stripped(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "java\x00script:alert(1)"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "\x00" not in g.nodes[0].label
        assert "javascript:" not in g.nodes[0].label

    def test_control_chars_stripped(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "hello\x08world\x0etest"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "\x08" not in g.nodes[0].label
        assert "\x0e" not in g.nodes[0].label

    def test_quotes_preserved_as_plain_text(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": 'x "quoted" y'}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes[0].label == 'x "quoted" y'

    def test_event_handler_stripped_from_label(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": 'onload="alert(1)"'}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "onload" not in g.nodes[0].label.lower()

    def test_onerror_handler_stripped(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "img onerror=alert(1)"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "onerror" not in g.nodes[0].label.lower()

    def test_onmouseover_handler_stripped(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "text onmouseover=steal()"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "onmouseover" not in g.nodes[0].label.lower()

    def test_dangerous_uri_mid_string_stripped(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "click here javascript:alert(1)"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "javascript:" not in g.nodes[0].label

    def test_event_handler_in_edge_relation(self) -> None:
        data = {
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "links": [{"source": "a", "target": "b", "relation": "onerror=alert(1)"}],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "onerror" not in (g.links[0].relation or "").lower()

    def test_event_handler_in_hyperedge_relation(self) -> None:
        data = {
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "links": [],
            "hyperedges": [{"id": "h", "nodes": ["a", "b"], "relation": "onclick=xss()"}],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "onclick" not in (g.hyperedges[0].relation or "").lower()

    def test_xss_svg_onload_payload(self) -> None:
        payload = '<svg onload="alert(document.cookie)">'
        data = {"nodes": [{"id": "n", "label": payload}], "links": []}
        g = parse_graph_json_text(json.dumps(data))
        assert "onload" not in g.nodes[0].label.lower()
        assert "<svg" not in g.nodes[0].label

    def test_data_uri_mid_string_stripped(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "see data:text/html,<script>xss</script>"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "data:" not in g.nodes[0].label

    def test_metadata_colon_preserved(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "metadata:value bigdata:analysis"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "metadata:value" in g.nodes[0].label
        assert "bigdata:analysis" in g.nodes[0].label

    def test_legitimate_on_prefix_preserved(self) -> None:
        data = {
            "nodes": [{"id": "n", "label": "only=true online=yes ongoing=work"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert "only=true" in g.nodes[0].label
        assert "online=yes" in g.nodes[0].label
        assert "ongoing=work" in g.nodes[0].label


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


def test_run_graphify_update_timeout_terminates_detached_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import ahadiff.graphify.cli as graphify_cli_module

    events: list[tuple[str, object]] = []

    class _FakeProcess:
        pid = 12345
        returncode: int | None = None

        def __init__(self, command: list[str], **kwargs: object) -> None:
            self.command = command
            events.append(("command", command))
            events.append(("kwargs", kwargs))

        def __enter__(self) -> _FakeProcess:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def communicate(self, *, timeout: int | float | None = None) -> tuple[str, str]:
            events.append(("communicate_timeout", timeout))
            expired_timeout = 0.0 if timeout is None else float(timeout)
            raise subprocess.TimeoutExpired(self.command, expired_timeout)

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            events.append(("kill", None))
            self.returncode = -9

        def terminate(self) -> None:
            events.append(("terminate", None))
            self.returncode = -15

    def _fake_popen(command: list[str], **kwargs: object) -> _FakeProcess:
        return _FakeProcess(command, **kwargs)

    monkeypatch.setattr(graphify_cli_module, "detect_graphify_cli", lambda: "/usr/bin/graphify")
    monkeypatch.setattr(graphify_cli_module.subprocess, "Popen", _fake_popen)
    if not sys.platform.startswith("win"):

        def _fake_killpg(pid: int, signum: int) -> None:
            events.append(("killpg", (pid, signum)))

        monkeypatch.setattr(
            os,
            "killpg",
            _fake_killpg,
        )

    assert graphify_cli_module.run_graphify_update(tmp_path, timeout=3) is False

    kwargs = next(value for key, value in events if key == "kwargs")
    assert isinstance(kwargs, dict)
    if sys.platform.startswith("win"):
        assert "creationflags" in kwargs
        assert ("kill", None) in events
    else:
        assert kwargs["start_new_session"] is True
        assert any(key == "killpg" for key, _value in events)
    assert ("communicate_timeout", 3) in events


# ---------------------------------------------------------------------------
# detect_graphify_status — freshness wiring
# ---------------------------------------------------------------------------


class TestDetectGraphifyStatusFreshness:
    @staticmethod
    def _repo(tmp_path: Path) -> GitRepo:
        return GitRepo(
            root=tmp_path,
            head_sha="head-sha",
            head_short_sha="head",
            head_detached=False,
            current_branch="main",
        )

    @staticmethod
    def _write_source(tmp_path: Path) -> None:
        graph_dir = tmp_path / "graphify-out"
        graph_dir.mkdir()
        (graph_dir / "graph.json").write_text("{}", encoding="utf-8")

    def test_no_source_returns_none(self, tmp_path: Path) -> None:
        from ahadiff.git.capture import detect_graphify_status

        status = detect_graphify_status(tmp_path, use_graphify=None)
        assert status.freshness is None
        assert status.source_exists is False

    def test_source_present_no_repo_returns_stale(self, tmp_path: Path) -> None:
        from ahadiff.git.capture import detect_graphify_status

        self._write_source(tmp_path)
        status = detect_graphify_status(tmp_path, use_graphify=None, repo=None)
        assert status.freshness == "stale"
        assert status.source_exists is True
        assert status.enabled is True

    def test_disabled_with_source_returns_disabled(self, tmp_path: Path) -> None:
        from ahadiff.git.capture import detect_graphify_status

        self._write_source(tmp_path)
        status = detect_graphify_status(tmp_path, use_graphify=False, repo=None)
        assert status.freshness == "disabled"
        assert status.enabled is False

    def test_freshness_is_projected_value(self, tmp_path: Path) -> None:
        from ahadiff.git.capture import detect_graphify_status

        self._write_source(tmp_path)
        status = detect_graphify_status(tmp_path, use_graphify=None, repo=None)
        assert status.freshness in {"fresh", "stale", "unavailable", "disabled"}

    def test_git_timeout_degrades_to_stale(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ahadiff.git import capture as capture_module

        def timeout_run_git(
            _repo_root: Path,
            *_args: str,
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            raise InputError("git command timed out after 1s: log")

        self._write_source(tmp_path)
        monkeypatch.setattr(capture_module, "run_git", timeout_run_git)

        status = capture_module.detect_graphify_status(
            tmp_path,
            use_graphify=None,
            repo=self._repo(tmp_path),
        )

        assert status.freshness == "stale"

    @pytest.mark.parametrize("count_stdout", ["not-an-int\n", ""])
    def test_invalid_commit_count_stdout_degrades_to_stale(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        count_stdout: str,
    ) -> None:
        from ahadiff.git import capture as capture_module

        calls: list[tuple[str, ...]] = []

        def fake_run_git(
            _repo_root: Path,
            *args: str,
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            if args[:3] == ("log", "-1", "--format=%H"):
                return subprocess.CompletedProcess(["git", *args], 0, stdout="graph-sha\n")
            if args[:2] == ("rev-list", "--count"):
                return subprocess.CompletedProcess(["git", *args], 0, stdout=count_stdout)
            raise AssertionError(f"unexpected git args: {args!r}")

        self._write_source(tmp_path)
        monkeypatch.setattr(capture_module, "run_git", fake_run_git)

        status = capture_module.detect_graphify_status(
            tmp_path,
            use_graphify=None,
            repo=self._repo(tmp_path),
        )

        assert status.freshness == "stale"
        assert any("--max-count=51" in call for call in calls)

    def test_graphify_log_pathspec_uses_forward_slashes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ahadiff.git import capture as capture_module

        calls: list[tuple[str, ...]] = []

        def fake_run_git(
            _repo_root: Path,
            *args: str,
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return subprocess.CompletedProcess(["git", *args], 0, stdout="")

        monkeypatch.setattr(capture_module, "run_git", fake_run_git)
        monkeypatch.setattr(
            capture_module,
            "_GRAPHIFY_RELATIVE_PATH",
            Path("graphify-out\\graph.json"),
        )

        freshness = capture_module._resolve_graphify_freshness(  # pyright: ignore[reportPrivateUsage]
            tmp_path,
            repo=self._repo(tmp_path),
            source_exists=True,
            imported_exists=False,
            enabled=True,
        )

        assert freshness == "stale"
        assert calls[0][-1] == "graphify-out/graph.json"


def test_project_graphify_maps_legacy_missing_to_canonical_unavailable() -> None:
    from ahadiff.serve import routes_runs as routes_runs_module

    projection = routes_runs_module._project_graphify(  # pyright: ignore[reportPrivateUsage]
        {"graphify": {"status": "missing"}}
    )

    assert projection[1] == "unavailable"


# ---------------------------------------------------------------------------
# Edge count cap (5C)
# ---------------------------------------------------------------------------


class TestEdgeCountCap:
    def test_within_limit_accepted(self) -> None:
        data: dict[str, Any] = {
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "links": [{"source": "a", "target": "b"}],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.links) == 1

    def test_exceeds_limit_rejected(self) -> None:
        max_edges = 50_000

        nodes = [{"id": f"n{i}", "label": f"N{i}"} for i in range(max_edges + 2)]
        links = [{"source": f"n{i}", "target": f"n{i + 1}"} for i in range(max_edges + 1)]
        data: dict[str, Any] = {"nodes": nodes, "links": links}
        with pytest.raises(InputError, match="edge limit"):
            parse_graph_json_text(json.dumps(data))


# ---------------------------------------------------------------------------
# Duplicate node ID detection (5C)
# ---------------------------------------------------------------------------


class TestDuplicateNodeId:
    def test_last_occurrence_wins(self) -> None:
        data: dict[str, Any] = {
            "nodes": [
                {"id": "dup", "label": "First"},
                {"id": "dup", "label": "Second"},
                {"id": "other", "label": "Other"},
            ],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.nodes) == 2
        dup_node = next(n for n in g.nodes if n.id == "dup")
        assert dup_node.label == "Second"

    def test_no_duplicates_unchanged(self) -> None:
        data: dict[str, Any] = {
            "nodes": [
                {"id": "a", "label": "A"},
                {"id": "b", "label": "B"},
            ],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.nodes) == 2

    def test_triple_duplicate_keeps_last(self) -> None:
        data: dict[str, Any] = {
            "nodes": [
                {"id": "x", "label": "V1"},
                {"id": "x", "label": "V2"},
                {"id": "x", "label": "V3"},
            ],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.nodes) == 1
        assert g.nodes[0].label == "V3"

    def test_empty_string_node_ids_are_dropped(self) -> None:
        data: dict[str, Any] = {
            "nodes": [
                {"id": "", "label": "Empty 1"},
                {"id": "", "label": "Empty 2"},
            ],
            "links": [{"source": "", "target": ""}],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes == []
        assert g.links == []

    def test_integer_node_id_is_dropped(self) -> None:
        data: dict[str, Any] = {
            "nodes": [{"id": 123, "label": "Integer ID"}],
            "links": [],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes == []


# ---------------------------------------------------------------------------
# Edge endpoint validation (5C)
# ---------------------------------------------------------------------------


class TestDanglingEdgeRemoval:
    def test_valid_edges_kept(self) -> None:
        data: dict[str, Any] = {
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "links": [{"source": "a", "target": "b"}],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.links) == 1

    def test_dangling_source_dropped(self) -> None:
        data: dict[str, Any] = {
            "nodes": [{"id": "a", "label": "A"}],
            "links": [{"source": "missing", "target": "a"}],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.links) == 0

    def test_dangling_target_dropped(self) -> None:
        data: dict[str, Any] = {
            "nodes": [{"id": "a", "label": "A"}],
            "links": [{"source": "a", "target": "missing"}],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.links) == 0

    def test_mixed_valid_and_dangling(self) -> None:
        data: dict[str, Any] = {
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "links": [
                {"source": "a", "target": "b"},
                {"source": "a", "target": "ghost"},
                {"source": "ghost", "target": "b"},
            ],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.links) == 1
        assert g.links[0].source == "a"
        assert g.links[0].target == "b"

    def test_duplicate_nodes_then_dangling_edges(self) -> None:
        """Edges referencing a deduplicated node still work if last-wins keeps the ID."""
        data: dict[str, Any] = {
            "nodes": [
                {"id": "dup", "label": "V1"},
                {"id": "dup", "label": "V2"},
                {"id": "other", "label": "O"},
            ],
            "links": [{"source": "dup", "target": "other"}],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.nodes) == 2
        assert len(g.links) == 1

    def test_null_edge_endpoints_are_dropped(self) -> None:
        data: dict[str, Any] = {
            "nodes": [{"id": "a", "label": "A"}],
            "links": [
                {"source": None, "target": "a"},
                {"source": "a", "target": None},
            ],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.links) == 0

    def test_all_dangling_edges_are_dropped(self) -> None:
        data: dict[str, Any] = {
            "nodes": [{"id": "a", "label": "A"}],
            "links": [{"source": "missing", "target": "ghost"}],
        }
        g = parse_graph_json_text(json.dumps(data))
        assert len(g.links) == 0

    @pytest.mark.parametrize("nodes", [None, {"id": "a", "label": "A"}])
    def test_non_list_nodes_parse_as_empty_graph(self, nodes: object) -> None:
        data: dict[str, Any] = {"nodes": nodes, "links": []}
        g = parse_graph_json_text(json.dumps(data))
        assert g.nodes == []
        assert g.links == []


# ---------------------------------------------------------------------------
# Graph SHA256 provenance (5B)
# ---------------------------------------------------------------------------


class TestGraphSha256Provenance:
    def test_sha256_present_in_provenance(self, tmp_path: Path) -> None:
        import hashlib

        from ahadiff.git.capture import import_graphify_artifact

        # import_graphify_artifact requires a git repository
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            env={
                **__import__("os").environ,
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )

        graph_data: dict[str, Any] = {
            "nodes": [{"id": "n1", "label": "Foo"}],
            "links": [],
        }
        source_dir = tmp_path / "graphify-out"
        source_dir.mkdir()
        graph_path = source_dir / "graph.json"
        graph_text = json.dumps(graph_data)
        graph_path.write_text(graph_text, encoding="utf-8")

        expected_sha = hashlib.sha256(graph_text.encode("utf-8")).hexdigest()

        status = import_graphify_artifact(tmp_path, force=True)

        assert "graph_sha256" in status.provenance
        assert status.provenance["graph_sha256"] == expected_sha
        assert len(expected_sha) == 64
