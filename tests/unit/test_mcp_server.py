from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any, cast

import pytest

from ahadiff.contracts import ResultEvent
from ahadiff.core.errors import StorageError
from ahadiff.core.sqlite_util import mcp_readonly_connect
from ahadiff.graphify import GraphifyGraph
from ahadiff.mcp.server import (
    _count_table_rows,  # pyright: ignore[reportPrivateUsage]
    _get_stats,  # pyright: ignore[reportPrivateUsage]
    _list_due_cards,  # pyright: ignore[reportPrivateUsage]
    _list_runs,  # pyright: ignore[reportPrivateUsage]
    _load_graph,  # pyright: ignore[reportPrivateUsage]
    _load_latest_result_event_for_run,  # pyright: ignore[reportPrivateUsage]
    _search,  # pyright: ignore[reportPrivateUsage]
    _tool_handlers,  # pyright: ignore[reportPrivateUsage]
)
from ahadiff.review.database import initialize_review_db, sync_result_event

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


def _seed_review_db(db_path: Path) -> None:
    initialize_review_db(db_path)
    sync_result_event(
        db_path,
        ResultEvent(
            event_id="018f0f52-91c0-7abc-8123-000000000101",
            run_id="run-mcp-1",
            event_type="learn",
            timestamp="2026-05-01T00:00:00Z",
            source_ref="abc1234",
            base_ref=None,
            prompt_version="prompt123",
            eval_bundle_version="eval123",
            rubric_version="rubric-v1",
            overall=88.0,
            verdict="PASS",
            status=cast("Any", "baseline"),
            weakest_dim="evidence",
            note_json=None,
        ),
    )


def _insert_due_card(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO cards (
                id, concept, run_id, fsrs_state, card_state, scheduler_version,
                due_date, stability, difficulty, source_ref, file_id,
                display_path, hunk_id, hunk_hash, answer_mode, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "card-mcp-1",
                "retry loop",
                "run-mcp-1",
                "{}",
                "active",
                "fsrs-test",
                "2020-01-01T00:00:00Z",
                0.0,
                0.0,
                "abc1234",
                "file-app",
                "src/app.py",
                "hunk-1",
                "deadbeef",
                "open",
                "2026-04-24T00:00:00Z",
            ),
        )
        connection.commit()


class TestMCPReadOnly:
    def test_query_only_pragma_set(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        _seed_review_db(db_path)

        connection = mcp_readonly_connect(db_path)
        try:
            row = connection.execute("PRAGMA query_only").fetchone()
            assert row is not None
            assert int(row[0]) == 1
            ts_row = connection.execute("PRAGMA trusted_schema").fetchone()
            assert ts_row is not None
            assert int(ts_row[0]) == 0
        finally:
            connection.close()

    def test_write_operations_blocked(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        _seed_review_db(db_path)

        connection = mcp_readonly_connect(db_path)
        try:
            with pytest.raises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE evil (x TEXT)")
            with pytest.raises(sqlite3.OperationalError):
                connection.execute(
                    "INSERT INTO result_events (event_id, run_id, event_type, timestamp) "
                    "VALUES ('x', 'y', 'learn', '2026-01-01T00:00:00Z')"
                )
            with pytest.raises(sqlite3.OperationalError):
                connection.execute("UPDATE result_events SET overall = 0")
            with pytest.raises(sqlite3.OperationalError):
                connection.execute("DELETE FROM result_events")
        finally:
            connection.close()

    def test_attach_writable_db_blocked(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        _seed_review_db(db_path)
        side_path = tmp_path / "side.sqlite"
        side = sqlite3.connect(side_path)
        try:
            side.execute("CREATE TABLE t (x TEXT)")
            side.commit()
        finally:
            side.close()

        connection = mcp_readonly_connect(db_path)
        try:
            attach_blocked = False
            write_blocked = False
            try:
                connection.execute("ATTACH DATABASE ? AS side", (str(side_path),))
            except sqlite3.OperationalError:
                attach_blocked = True
            else:
                try:
                    connection.execute("INSERT INTO side.t (x) VALUES ('hack')")
                except sqlite3.OperationalError:
                    write_blocked = True
            assert attach_blocked or write_blocked, (
                "ATTACH or writes on attached DB must be blocked under MCP read-only mode"
            )
        finally:
            connection.close()

    def test_existing_tools_output_unchanged(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        _seed_review_db(db_path)
        _insert_due_card(db_path)

        runs_payload = _list_runs(db_path, {"limit": 5})
        runs = cast("list[dict[str, Any]]", runs_payload["runs"])
        assert len(runs) == 1
        run_entry = runs[0]
        assert run_entry["run_id"] == "run-mcp-1"
        assert run_entry["overall"] == 88.0

        latest = _load_latest_result_event_for_run(db_path, "run-mcp-1")
        assert latest is not None
        assert latest["event_id"] == "018f0f52-91c0-7abc-8123-000000000101"

        due_payload = _list_due_cards(db_path, {"limit": 5})
        cards = cast("list[dict[str, Any]]", due_payload["cards"])
        assert len(cards) == 1
        assert cards[0]["card_id"] == "card-mcp-1"
        assert cards[0]["answer_mode"] == "open"

        search_payload = _search(tmp_path, db_path, {"query": "retry", "limit": 5})
        assert "results" in search_payload

        stats = _get_stats(tmp_path, db_path)
        assert stats["total_runs"] == 1
        assert stats["total_result_events"] == 1
        assert stats["total_cards"] == 1
        avg = cast("float | None", stats["avg_overall_score"])
        assert avg is not None
        assert abs(avg - 88.0) < 1e-9
        assert stats["last_run_at"] == "2026-05-01T00:00:00Z"

    def test_missing_db_raises_storage_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "absent.sqlite"
        with pytest.raises(StorageError, match="MCP read-only DB does not exist"):
            mcp_readonly_connect(missing)

    def test_no_wal_shm_created(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        _seed_review_db(db_path)

        from ahadiff.review.database import checkpoint_review_db

        checkpoint_review_db(db_path)
        pre_existing = {
            suffix
            for suffix in ("-wal", "-shm", "-journal")
            if db_path.with_name(f"{db_path.name}{suffix}").exists()
        }

        connection = mcp_readonly_connect(db_path)
        try:
            connection.execute("SELECT 1").fetchone()
            connection.execute("SELECT COUNT(*) FROM result_events").fetchone()
        finally:
            connection.close()

        for suffix in ("-wal", "-shm", "-journal"):
            if suffix in pre_existing:
                continue
            sidecar = db_path.with_name(f"{db_path.name}{suffix}")
            assert not sidecar.exists(), (
                f"MCP read-only connection must not create sidecar {sidecar.name}"
            )


def test_mcp_server_registers_seven_tools(tmp_path: Path) -> None:
    handlers = _tool_handlers(tmp_path, tmp_path / "review.sqlite")
    assert set(handlers) == {
        "list_runs",
        "get_run_summary",
        "list_due_cards",
        "search",
        "get_concepts",
        "get_stats",
        "ask_lesson",
    }
    assert len(handlers) == 7
