from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ahadiff.core.errors import InputError, StorageError
from ahadiff.review.database import (
    CURRENT_SCHEMA_VERSION,
    connect_review_db,
    initialize_review_db,
    upsert_concept,
)
from ahadiff.review.search import search_all, search_all_with_graph


def test_schema_version_is_8() -> None:
    assert CURRENT_SCHEMA_VERSION == 8


def test_fts_tables_created(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    with connect_review_db(db) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert "fts_concepts" in tables
    assert "fts_result_events" in tables
    assert "fts_cards" in tables


def test_search_empty_db(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    results = search_all(db, "closure")
    assert results == ()


def test_search_nonexistent_db(tmp_path: Path) -> None:
    results = search_all(tmp_path / "nope.sqlite", "test")
    assert results == ()


def test_search_empty_query(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    assert search_all(db, "") == ()
    assert search_all(db, "   ") == ()


def test_search_concepts_by_name(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="closure",
        concept="JavaScript Closure",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    upsert_concept(
        db,
        term_key="hoisting",
        concept="Variable Hoisting",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    results = search_all(db, "closure")
    assert len(results) >= 1
    assert any(r.source_table == "concepts" and r.primary_key == "closure" for r in results)


def test_search_concepts_partial_match(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="async-await",
        concept="Async Await Pattern",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    results = search_all(db, "async")
    assert len(results) >= 1


def test_search_respects_limit(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    for i in range(10):
        upsert_concept(
            db,
            term_key=f"concept-{i}",
            concept=f"Test Concept {i}",
            run_id="r1",
            source_ref="abc",
            branch_hint=None,
            related_claims=(),
            file_refs=(),
        )
    results = search_all(db, "concept", limit=3)
    assert len(results) <= 3


def test_search_respects_table_filter(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="pattern",
        concept="Design Pattern",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    results = search_all(db, "pattern", tables=("result_events",))
    # Should not find concepts since we filtered to result_events only
    assert not any(r.source_table == "concepts" for r in results)


def test_search_empty_table_filter_returns_empty(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="pattern",
        concept="Design Pattern",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )

    assert search_all(db, "pattern", tables=()) == ()


def test_search_query_too_long(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    with pytest.raises(InputError):
        search_all(db, "x" * 600)


def test_search_sanitizes_special_chars(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="test",
        concept="Test Concept",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    # These should not crash even with FTS5 special characters
    results = search_all(db, '"test"')
    assert isinstance(results, tuple)
    results = search_all(db, "test AND concept")
    assert isinstance(results, tuple)


def test_search_tokenizes_illegal_punctuation_without_empty_results(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="closure",
        concept="Closure Capture",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )

    results = search_all(db, "closure|missing", tables=("concepts",))

    assert any(r.source_table == "concepts" and r.primary_key == "closure" for r in results)


def test_search_treats_fts_operators_as_literal_tokens(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="closure",
        concept="Closure Capture",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    upsert_concept(
        db,
        term_key="missing",
        concept="Missing Evidence",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    upsert_concept(
        db,
        term_key="operator-or",
        concept="Logical OR Token",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )

    not_results = search_all(db, "closure NOT missing", tables=("concepts",))
    or_results = search_all(db, "OR", tables=("concepts",))

    not_keys = {result.primary_key for result in not_results}
    assert {"closure", "missing"}.issubset(not_keys)
    assert any(result.primary_key == "operator-or" for result in or_results)


def test_search_snippet_comes_from_indexed_body_column(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="primary-key-only",
        concept="Closure body explains lexical capture",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )

    results = search_all(db, "closure", tables=("concepts",))

    result = next(r for r in results if r.primary_key == "primary-key-only")
    assert result.snippet != "primary-key-only"
    assert "<b>closure</b>" in result.snippet.lower()


def test_search_raises_storage_error_for_broken_fts_schema(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    with connect_review_db(db) as conn:
        conn.execute("DROP TABLE fts_concepts")
        conn.execute("CREATE TABLE fts_concepts (term_key TEXT)")

    with pytest.raises(StorageError, match="FTS search failed for fts_concepts"):
        search_all(db, "closure", tables=("concepts",))


def test_migration_v3_to_v4(tmp_path: Path) -> None:
    """A v3 database gets upgraded to v4 with FTS tables."""
    from ahadiff.core.sqlite_util import safe_sqlite_connect

    db = tmp_path / "review.sqlite"
    conn = safe_sqlite_connect(db, journal_mode="WAL", foreign_keys=True, defensive=True)
    conn.execute("PRAGMA user_version=3")
    # Create minimal v3 tables (concepts + existing)
    conn.execute(
        "CREATE TABLE scheduler_presets (preset_id TEXT PRIMARY KEY, weights TEXT NOT NULL,"
        " desired_retention REAL NOT NULL DEFAULT 0.9, scheduler_version TEXT NOT NULL,"
        " total_reviews INTEGER NOT NULL DEFAULT 0, last_optimized_utc TEXT,"
        " created_at_utc TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO scheduler_presets VALUES"
        " ('default', '[]', 0.9, 'test', 0, NULL, '2024-01-01T00:00:00Z')"
    )
    conn.execute(
        "CREATE TABLE cards (id TEXT PRIMARY KEY, concept TEXT NOT NULL,"
        " run_id TEXT NOT NULL, fsrs_state TEXT NOT NULL,"
        " card_state TEXT NOT NULL DEFAULT 'active',"
        " scheduler_preset_id TEXT NOT NULL DEFAULT 'default',"
        " scheduler_version TEXT NOT NULL, desired_retention REAL NOT NULL DEFAULT 0.9,"
        " due_date TEXT NOT NULL, stability REAL NOT NULL, difficulty REAL NOT NULL,"
        " reps INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0,"
        " scaffolding_level TEXT NOT NULL DEFAULT 'full', last_rating INTEGER,"
        " last_review_utc TEXT, source_ref TEXT NOT NULL, file_id TEXT NOT NULL,"
        " display_path TEXT NOT NULL, hunk_id TEXT NOT NULL, hunk_hash TEXT NOT NULL,"
        " symbol TEXT, change_kind TEXT, stale_reason TEXT, created_at_utc TEXT NOT NULL,"
        " archived_at_utc TEXT, suspended_at_utc TEXT)"
    )
    conn.execute(
        "CREATE TABLE review_logs (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " card_id TEXT NOT NULL, rating INTEGER NOT NULL,"
        " reviewed_at_utc TEXT NOT NULL, elapsed_days REAL NOT NULL,"
        " scheduled_days REAL NOT NULL, state TEXT NOT NULL, review_duration INTEGER)"
    )
    conn.execute(
        "CREATE TABLE result_events (event_id TEXT PRIMARY KEY,"
        " run_id TEXT NOT NULL, event_type TEXT NOT NULL,"
        " timestamp TEXT NOT NULL, source_ref TEXT NOT NULL, base_ref TEXT,"
        " prompt_version TEXT NOT NULL, eval_bundle_version TEXT NOT NULL,"
        " rubric_version TEXT, overall REAL NOT NULL, verdict TEXT NOT NULL,"
        " status TEXT NOT NULL, weakest_dim TEXT NOT NULL, note_json TEXT)"
    )
    conn.execute(
        "CREATE TABLE learning_signals (event_id TEXT PRIMARY KEY,"
        " idempotency_key TEXT NOT NULL UNIQUE, signal_type TEXT NOT NULL,"
        " payload_json TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE concepts (term_key TEXT PRIMARY KEY, concept TEXT NOT NULL,"
        " term TEXT NOT NULL, display_name TEXT NOT NULL,"
        " lang TEXT NOT NULL DEFAULT 'en', aliases TEXT NOT NULL DEFAULT '[]',"
        " source_refs TEXT NOT NULL DEFAULT '[]', branch_hint TEXT,"
        " introduced_by_run TEXT NOT NULL, updated_by_runs TEXT NOT NULL DEFAULT '[]',"
        " related_claims TEXT NOT NULL DEFAULT '[]',"
        " file_refs TEXT NOT NULL DEFAULT '[]',"
        " created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL)"
    )
    # Insert a concept to test FTS rebuild
    conn.execute(
        "INSERT INTO concepts VALUES"
        " ('closure', 'Closure', 'closure', 'Closure', 'en', '[]', '[]',"
        " NULL, 'r1', '[]', '[]', '[]', '2024-01-01', '2024-01-01')"
    )
    conn.commit()
    conn.close()

    # Trigger migration
    initialize_review_db(db)

    with connect_review_db(db) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "fts_concepts" in tables
        assert "fts_result_events" in tables
        assert "fts_cards" in tables

    # The pre-existing concept should be searchable after rebuild
    results = search_all(db, "closure")
    assert len(results) >= 1


def test_search_unicode_cjk(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="u-95ed-5305-6355-83b7",
        concept="闭包捕获",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    # FTS5 unicode61 tokenizer treats continuous CJK as a single token,
    # so full-word match is required (partial CJK needs trigram tokenizer).
    results = search_all(db, "闭包捕获", tables=("concepts",))
    assert any(r.primary_key == "u-95ed-5305-6355-83b7" for r in results)


def test_search_unicode_accented(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="u-e9-u-e8",
        concept="résumé è",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    results = search_all(db, "résumé", tables=("concepts",))
    assert len(results) >= 1


def test_search_limit_zero_returns_empty(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="test",
        concept="Test",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    assert search_all(db, "test", limit=0) == ()


def test_search_limit_negative_returns_empty(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    assert search_all(db, "test", limit=-5) == ()


def test_search_limit_capped_at_max(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    results = search_all(db, "anything", limit=9999)
    assert isinstance(results, tuple)


def test_search_unknown_table_silently_skipped(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="test",
        concept="Test Concept",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    results = search_all(db, "test", tables=("evil_table", "concepts"))
    assert any(r.source_table == "concepts" for r in results)


def test_search_all_with_graph_returns_graph_nodes_without_db(tmp_path: Path) -> None:
    from ahadiff.graphify import parse_graph_json_text

    graph = parse_graph_json_text(
        """
        {
          "nodes": [
            {"id": "n1", "label": "task_runner", "source_file": "src/task_runner.py"}
          ],
          "links": []
        }
        """
    )

    results = search_all_with_graph(
        tmp_path / "missing.sqlite",
        "TaskRunner",
        tables=("graph_nodes",),
        graph=graph,
    )

    assert len(results) == 1
    assert results[0].source_table == "graph_nodes"
    assert results[0].primary_key == "n1"


def test_search_all_with_graph_respects_table_filter(tmp_path: Path) -> None:
    from ahadiff.graphify import parse_graph_json_text

    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    graph = parse_graph_json_text(
        """
        {
          "nodes": [{"id": "n1", "label": "task_runner"}],
          "links": []
        }
        """
    )

    results = search_all_with_graph(db, "task_runner", tables=("concepts",), graph=graph)

    assert not any(r.source_table == "graph_nodes" for r in results)


def test_search_all_with_graph_uses_stable_descending_rank_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.graphify.search import GraphSearchResult

    def fake_search_graph_nodes(
        graph: object,
        query: str,
        *,
        limit: int = 20,
    ) -> tuple[GraphSearchResult, ...]:
        del graph, query, limit
        return (
            GraphSearchResult("node-b", "same score b", None, None, 0.5),
            GraphSearchResult("node-a", "same score a", None, None, 0.5),
        )

    monkeypatch.setattr("ahadiff.graphify.search.search_graph_nodes", fake_search_graph_nodes)

    results = search_all_with_graph(
        tmp_path / "missing.sqlite",
        "same score",
        tables=("graph_nodes",),
        graph=object(),
    )

    assert [r.primary_key for r in results] == ["node-a", "node-b"]
    assert [r.rank for r in results] == sorted((r.rank for r in results), reverse=True)


def test_route_search_returns_public_rank_descending_order(tmp_path: Path) -> None:
    from starlette.testclient import TestClient

    from ahadiff.serve import ServeState, create_app

    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db = state_dir / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="task-timeout",
        concept="Task timeout handling",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    upsert_concept(
        db,
        term_key="task-runner",
        concept="Task runner",
        run_id="r1",
        source_ref="abc",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    app = create_app(ServeState(state_dir=state_dir, token="test-token", locale="en"))
    client = TestClient(app, base_url="http://localhost:8765")

    response = client.get(
        "/api/search?q=task timeout&tables=concepts",
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) >= 2
    ranks = [item["rank"] for item in results]
    assert ranks == sorted(ranks, reverse=True)
    assert results[0]["primary_key"] == "task-timeout"


def test_route_search_result_events_expose_run_href(tmp_path: Path) -> None:
    from starlette.testclient import TestClient

    from ahadiff.serve import ServeState, create_app

    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db = state_dir / "review.sqlite"
    initialize_review_db(db)
    with connect_review_db(db) as conn:
        conn.execute(
            """
            INSERT INTO result_events (
                event_id,
                run_id,
                event_type,
                timestamp,
                source_ref,
                base_ref,
                prompt_version,
                eval_bundle_version,
                rubric_version,
                overall,
                verdict,
                status,
                weakest_dim,
                note_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "event-123",
                "run-real",
                "score_finalized",
                "2026-04-30T00:00:00Z",
                "src/task_timeout.py",
                None,
                "prompt-v1",
                "eval-v1",
                None,
                90.0,
                "PASS",
                "completed",
                "task_timeout",
                '{"summary":"task timeout result"}',
            ),
        )

    app = create_app(ServeState(state_dir=state_dir, token="test-token", locale="en"))
    client = TestClient(app, base_url="http://localhost:8765")

    response = client.get(
        "/api/search?q=timeout&tables=result_events",
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["source_table"] == "result_events"
    assert results[0]["primary_key"] == "event-123"
    assert results[0]["href"] == "#/run/run-real/lesson"
    assert "<b>timeout</b>" in results[0]["snippet"]


def test_route_search_corrupt_db_error_does_not_expose_local_path(tmp_path: Path) -> None:
    from starlette.testclient import TestClient

    from ahadiff.serve import ServeState, create_app

    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db = state_dir / "review.sqlite"
    db.write_bytes(b"not a valid sqlite database")

    app = create_app(ServeState(state_dir=state_dir, token="test-token", locale="en"))
    client = TestClient(app, base_url="http://localhost:8765")

    response = client.get(
        "/api/search?q=timeout",
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "review.sqlite is not a valid database"
    assert str(db) not in json.dumps(payload)


def test_route_search_loads_imported_graph_artifact(tmp_path: Path) -> None:
    from starlette.testclient import TestClient

    from ahadiff.serve import ServeState, create_app

    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    raw_graph_dir = tmp_path / "graphify-out"
    raw_graph_dir.mkdir()
    (raw_graph_dir / "graph.json").write_text(
        json.dumps({"nodes": [{"id": "raw", "label": "rawzzztoken"}], "links": []}),
        encoding="utf-8",
    )
    imported_graph_dir = state_dir / "graphify"
    imported_graph_dir.mkdir()
    (imported_graph_dir / "graph.json").write_text(
        json.dumps({"nodes": [{"id": "safe", "label": "safeaaatoken"}], "links": []}),
        encoding="utf-8",
    )

    app = create_app(ServeState(state_dir=state_dir, token="test-token", locale="en"))
    client = TestClient(app, base_url="http://localhost:8765")
    headers = {
        "X-AhaDiff-Token": "test-token",
        "origin": "http://localhost:8765",
    }

    raw_resp = client.get(
        "/api/search?q=rawzzztoken&tables=graph_nodes",
        headers=headers,
    )
    safe_resp = client.get(
        "/api/search?q=safeaaatoken&tables=graph_nodes",
        headers=headers,
    )

    assert raw_resp.status_code == 200
    assert safe_resp.status_code == 200
    assert raw_resp.json()["results"] == []
    assert safe_resp.json()["results"][0]["primary_key"] == "safe"


def test_search_query_at_exact_boundary(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    results = search_all(db, "x" * 500)
    assert isinstance(results, tuple)
    with pytest.raises(InputError):
        search_all(db, "x" * 501)


# ---------------------------------------------------------------------------
# Graph node FTS tests
# ---------------------------------------------------------------------------


def test_fts_graph_nodes_table_created(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    with connect_review_db(db) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert "graph_nodes" in tables
    assert "fts_graph_nodes" in tables


def test_import_graph_nodes_and_fts_search(tmp_path: Path) -> None:
    from ahadiff.review.database import import_graph_nodes
    from ahadiff.review.search import search_graph_nodes_fts

    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    nodes = [
        {"id": "n1", "label": "TaskRunner", "kind": "class", "file_path": "src/task_runner.py"},
        {"id": "n2", "label": "FileWatcher", "kind": "class", "file_path": "src/watcher.py"},
        {"id": "n3", "label": "config_loader", "kind": "function", "file_path": "src/config.py"},
    ]
    count = import_graph_nodes(db, nodes)
    assert count == 3

    results = search_graph_nodes_fts(db, "TaskRunner")
    assert len(results) >= 1
    assert results[0].source_table == "graph_nodes"
    assert results[0].primary_key == "n1"


def test_import_graph_nodes_replaces_on_reimport(tmp_path: Path) -> None:
    from ahadiff.review.database import count_graph_nodes, import_graph_nodes

    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    import_graph_nodes(db, [{"id": "n1", "label": "OldLabel"}])
    assert count_graph_nodes(db) == 1

    import_graph_nodes(
        db,
        [
            {"id": "n2", "label": "NewLabel"},
            {"id": "n3", "label": "AnotherLabel"},
        ],
    )
    assert count_graph_nodes(db) == 2


def test_import_graph_nodes_empty(tmp_path: Path) -> None:
    from ahadiff.review.database import import_graph_nodes

    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    assert import_graph_nodes(db, []) == 0


def test_import_graph_nodes_skips_invalid(tmp_path: Path) -> None:
    from ahadiff.review.database import import_graph_nodes

    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    nodes = [
        {"id": "", "label": "NoId"},
        {"id": "n1", "label": ""},
        {"id": "n2", "label": "Valid"},
    ]
    assert import_graph_nodes(db, nodes) == 1


def test_import_graph_nodes_rejects_over_cap_without_truncation(tmp_path: Path) -> None:
    from ahadiff.review.database import count_graph_nodes, import_graph_nodes

    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    import_graph_nodes(db, [{"id": "keep", "label": "Existing"}])
    nodes = [{"id": f"n{i}", "label": f"Node {i}"} for i in range(10_001)]

    with pytest.raises(InputError, match="graph node import exceeds 10000"):
        import_graph_nodes(db, nodes)

    assert count_graph_nodes(db) == 1


def test_search_graph_nodes_fts_empty_db(tmp_path: Path) -> None:
    from ahadiff.review.search import search_graph_nodes_fts

    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    assert search_graph_nodes_fts(db, "anything") == ()


def test_search_graph_nodes_fts_nonexistent_db(tmp_path: Path) -> None:
    from ahadiff.review.search import search_graph_nodes_fts

    assert search_graph_nodes_fts(tmp_path / "nope.sqlite", "test") == ()


def test_search_graph_nodes_fts_empty_query(tmp_path: Path) -> None:
    from ahadiff.review.search import search_graph_nodes_fts

    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    assert search_graph_nodes_fts(db, "") == ()
    assert search_graph_nodes_fts(db, "   ") == ()


def test_search_all_with_graph_prefers_fts_over_inmemory(tmp_path: Path) -> None:
    from ahadiff.graphify import parse_graph_json_text
    from ahadiff.review.database import import_graph_nodes

    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    import_graph_nodes(
        db,
        [
            {"id": "n1", "label": "task_runner", "kind": "class", "file_path": "src/runner.py"},
        ],
    )

    graph = parse_graph_json_text('{"nodes": [{"id": "n1", "label": "task_runner"}], "links": []}')

    results = search_all_with_graph(
        db,
        "task_runner",
        tables=("graph_nodes",),
        graph=graph,
    )
    node_ids = [r.primary_key for r in results if r.source_table == "graph_nodes"]
    assert "n1" in node_ids
    assert node_ids.count("n1") == 1


def test_search_all_with_graph_falls_back_to_inmemory(tmp_path: Path) -> None:
    from ahadiff.graphify import parse_graph_json_text

    db = tmp_path / "review.sqlite"
    initialize_review_db(db)

    graph = parse_graph_json_text('{"nodes": [{"id": "n1", "label": "task_runner"}], "links": []}')

    results = search_all_with_graph(
        db,
        "task_runner",
        tables=("graph_nodes",),
        graph=graph,
    )
    assert len(results) >= 1
    assert results[0].primary_key == "n1"


def test_large_graph_import_and_search(tmp_path: Path) -> None:
    from ahadiff.review.database import count_graph_nodes, import_graph_nodes
    from ahadiff.review.search import search_graph_nodes_fts

    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    nodes = [{"id": f"node-{i}", "label": f"Component_{i}", "kind": "class"} for i in range(200)]
    nodes.append({"id": "special", "label": "UniqueSearchTarget", "kind": "function"})
    count = import_graph_nodes(db, nodes)
    assert count == 201
    assert count_graph_nodes(db) == 201

    results = search_graph_nodes_fts(db, "UniqueSearchTarget")
    assert len(results) == 1
    assert results[0].primary_key == "special"


def test_migration_v5_to_v6(tmp_path: Path) -> None:
    from ahadiff.core.sqlite_util import safe_sqlite_connect
    from ahadiff.review.database import import_graph_nodes
    from ahadiff.review.search import search_graph_nodes_fts

    db = tmp_path / "review.sqlite"
    conn = safe_sqlite_connect(db, journal_mode="WAL", foreign_keys=True, defensive=True)
    conn.execute("PRAGMA user_version=5")
    conn.execute(
        "CREATE TABLE scheduler_presets (preset_id TEXT PRIMARY KEY, weights TEXT NOT NULL,"
        " desired_retention REAL NOT NULL DEFAULT 0.9, scheduler_version TEXT NOT NULL,"
        " total_reviews INTEGER NOT NULL DEFAULT 0, last_optimized_utc TEXT,"
        " created_at_utc TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO scheduler_presets VALUES"
        " ('default', '[]', 0.9, 'test', 0, NULL, '2024-01-01T00:00:00Z')"
    )
    conn.execute(
        "CREATE TABLE cards (id TEXT PRIMARY KEY, concept TEXT NOT NULL,"
        " run_id TEXT NOT NULL, fsrs_state TEXT NOT NULL,"
        " card_state TEXT NOT NULL DEFAULT 'active',"
        " scheduler_preset_id TEXT NOT NULL DEFAULT 'default',"
        " scheduler_version TEXT NOT NULL, desired_retention REAL NOT NULL DEFAULT 0.9,"
        " due_date TEXT NOT NULL, stability REAL NOT NULL, difficulty REAL NOT NULL,"
        " reps INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0,"
        " scaffolding_level TEXT NOT NULL DEFAULT 'full', last_rating INTEGER,"
        " last_review_utc TEXT, source_ref TEXT NOT NULL, file_id TEXT NOT NULL,"
        " display_path TEXT NOT NULL, hunk_id TEXT NOT NULL, hunk_hash TEXT NOT NULL,"
        " symbol TEXT, change_kind TEXT, stale_reason TEXT, created_at_utc TEXT NOT NULL,"
        " archived_at_utc TEXT, suspended_at_utc TEXT)"
    )
    conn.execute(
        "CREATE TABLE review_logs (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " card_id TEXT NOT NULL, rating INTEGER NOT NULL,"
        " reviewed_at_utc TEXT NOT NULL, elapsed_days REAL NOT NULL,"
        " scheduled_days REAL NOT NULL, state TEXT NOT NULL, review_duration INTEGER)"
    )
    conn.execute(
        "CREATE TABLE result_events (event_id TEXT PRIMARY KEY,"
        " run_id TEXT NOT NULL, event_type TEXT NOT NULL,"
        " timestamp TEXT NOT NULL, source_ref TEXT NOT NULL, base_ref TEXT,"
        " prompt_version TEXT NOT NULL, eval_bundle_version TEXT NOT NULL,"
        " rubric_version TEXT, overall REAL NOT NULL, verdict TEXT NOT NULL,"
        " status TEXT NOT NULL, weakest_dim TEXT NOT NULL, note_json TEXT)"
    )
    conn.execute(
        "CREATE TABLE learning_signals (event_id TEXT PRIMARY KEY,"
        " idempotency_key TEXT NOT NULL UNIQUE, signal_type TEXT NOT NULL,"
        " payload_json TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE concepts (term_key TEXT PRIMARY KEY, concept TEXT NOT NULL,"
        " term TEXT NOT NULL, display_name TEXT NOT NULL,"
        " lang TEXT NOT NULL DEFAULT 'en', aliases TEXT NOT NULL DEFAULT '[]',"
        " source_refs TEXT NOT NULL DEFAULT '[]', branch_hint TEXT,"
        " introduced_by_run TEXT NOT NULL, updated_by_runs TEXT NOT NULL DEFAULT '[]',"
        " related_claims TEXT NOT NULL DEFAULT '[]',"
        " file_refs TEXT NOT NULL DEFAULT '[]',"
        " graphify_node_id TEXT,"
        " created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE fts_concepts USING fts5("
        " term_key UNINDEXED, concept, display_name, aliases,"
        " content='concepts', content_rowid='rowid')"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE fts_result_events USING fts5("
        " event_id UNINDEXED, source_ref, weakest_dim, note_json,"
        " content='result_events', content_rowid='rowid')"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE fts_cards USING fts5("
        " id UNINDEXED, concept, display_path, symbol,"
        " content='cards', content_rowid='rowid')"
    )
    conn.commit()
    conn.close()

    initialize_review_db(db)

    with connect_review_db(db) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "graph_nodes" in tables
        assert "fts_graph_nodes" in tables

    import_graph_nodes(db, [{"id": "n1", "label": "TaskRunner", "kind": "class"}])
    results = search_graph_nodes_fts(db, "TaskRunner")
    assert len(results) == 1
    assert results[0].primary_key == "n1"
