from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

from ahadiff.graphify import GraphifyGraph
from ahadiff.mcp.server import _count_table_rows, _load_graph  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from pathlib import Path


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


def _write_graph(state_dir: Path, content: str) -> None:
    graph_dir = state_dir / "graphify"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text(content, encoding="utf-8")


def test_load_graph_logs_warning_for_invalid_graph(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_graph(tmp_path, "not json")

    with caplog.at_level(logging.WARNING, logger="ahadiff.mcp.server"):
        graph = _load_graph(tmp_path)

    assert graph is None
    assert "failed to load graph:" in caplog.text


def test_load_graph_returns_valid_graph_without_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_graph(tmp_path, json.dumps(_MINIMAL_GRAPH))

    with caplog.at_level(logging.WARNING, logger="ahadiff.mcp.server"):
        graph = _load_graph(tmp_path)

    assert isinstance(graph, GraphifyGraph)
    assert [node.id for node in graph.nodes] == ["n1", "n2"]
    assert not [
        record
        for record in caplog.records
        if record.name == "ahadiff.mcp.server" and record.levelno >= logging.WARNING
    ]


def test_load_graph_returns_none_when_graph_file_is_missing(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="ahadiff.mcp.server"):
        graph = _load_graph(tmp_path)

    assert graph is None
    assert "failed to load graph:" not in caplog.text


def test_count_table_rows_returns_count_for_allowlisted_table() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE cards (card_id TEXT)")
        connection.executemany("INSERT INTO cards (card_id) VALUES (?)", [("a",), ("b",)])

        assert _count_table_rows(connection, "cards") == 2
    finally:
        connection.close()


def test_count_table_rows_rejects_non_allowlisted_table() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="table not in allowlist"):
            _count_table_rows(connection, "evil; DROP TABLE")
    finally:
        connection.close()


def test_count_table_rows_rejects_empty_table_name() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="table not in allowlist"):
            _count_table_rows(connection, "")
    finally:
        connection.close()
