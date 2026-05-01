from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, Any

import pytest

import ahadiff.review.database as review_database_module
from ahadiff.core.errors import InputError
from ahadiff.review.database import (
    CURRENT_SCHEMA_VERSION,
    connect_review_db,
    count_commit_ancestry,
    count_concepts,
    import_concepts_from_jsonl,
    initialize_review_db,
    load_commit_ancestry,
    load_concepts_from_db,
    replace_commit_ancestry,
    upsert_concept,
    upsert_concepts_batch,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path


class _BarrierConnectionProxy:
    def __init__(
        self,
        connection: sqlite3.Connection,
        barrier: threading.Barrier,
        *,
        select_fragment: str,
    ) -> None:
        self._connection = connection
        self._barrier = barrier
        self._select_fragment = select_fragment

    def __enter__(self) -> _BarrierConnectionProxy:
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        return self._connection.__exit__(exc_type, exc, tb)

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        normalized = " ".join(sql.split())
        if self._select_fragment in normalized:
            self._barrier.wait(timeout=5)
        return self._connection.execute(sql, parameters)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def test_schema_version_is_7() -> None:
    assert CURRENT_SCHEMA_VERSION == 7


def test_concepts_table_created_on_init(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    with connect_review_db(db) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert "concepts" in tables
    assert "commit_ancestry" in tables


def test_review_logs_has_review_duration(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    with connect_review_db(db) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(review_logs)").fetchall()}
    assert "review_duration" in columns


def test_commit_ancestry_helpers_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    head_sha = "a" * 40
    ancestors = ("a" * 40, "b" * 40, "c" * 40)

    inserted = replace_commit_ancestry(db, head_sha=head_sha, ancestors=ancestors)

    assert inserted == 3
    assert load_commit_ancestry(db, head_sha=head_sha) == ancestors
    assert count_commit_ancestry(db) == 3

    replace_commit_ancestry(db, head_sha=head_sha, ancestors=("d" * 40,))
    assert load_commit_ancestry(db, head_sha=head_sha) == ("d" * 40,)
    assert count_commit_ancestry(db) == 1


def test_upsert_concept_insert(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="closure",
        concept="Closure",
        run_id="run1",
        source_ref="abc123",
        branch_hint="main",
        related_claims=("c1", "c2"),
        file_refs=("src/foo.py",),
    )
    rows = load_concepts_from_db(db, limit=10)
    assert len(rows) == 1
    assert rows[0]["term_key"] == "closure"
    assert rows[0]["concept"] == "Closure"


def test_upsert_concept_merge(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concept(
        db,
        term_key="closure",
        concept="Closure",
        run_id="run1",
        source_ref="abc",
        branch_hint=None,
        related_claims=("c1",),
        file_refs=("f1.py",),
    )
    upsert_concept(
        db,
        term_key="closure",
        concept="Closure",
        run_id="run2",
        source_ref="def",
        branch_hint="main",
        related_claims=("c2",),
        file_refs=("f2.py",),
    )
    rows = load_concepts_from_db(db, limit=10)
    assert len(rows) == 1
    assert "abc" in str(rows[0]["source_refs"])
    assert "def" in str(rows[0]["source_refs"])
    assert rows[0]["branch_hint"] == "main"


def test_upsert_concept_concurrent_writers_merge_without_primary_key_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    barrier = threading.Barrier(2)
    original_connect = review_database_module.connect_review_db

    def wrapped_connect(*args: Any, **kwargs: Any) -> _BarrierConnectionProxy:
        return _BarrierConnectionProxy(
            original_connect(*args, **kwargs),
            barrier,
            select_fragment="FROM concepts WHERE term_key = ?",
        )

    monkeypatch.setattr(review_database_module, "connect_review_db", wrapped_connect)
    errors: list[Exception] = []

    def worker(run_id: str, source_ref: str, claim_id: str, file_ref: str) -> None:
        try:
            upsert_concept(
                db,
                term_key="closure",
                concept="Closure",
                run_id=run_id,
                source_ref=source_ref,
                branch_hint="main",
                related_claims=(claim_id,),
                file_refs=(file_ref,),
            )
        except Exception as exc:  # pragma: no cover - regression guard
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("run-a", "ref-a", "claim-a", "a.py")),
        threading.Thread(target=worker, args=("run-b", "ref-b", "claim-b", "b.py")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    [row] = load_concepts_from_db(db, limit=10)
    refs: Any = row["source_refs"]
    assert set(refs) == {"ref-a", "ref-b"}
    runs: Any = row["updated_by_runs"]
    assert set(runs) == {"run-a", "run-b"}
    claims: Any = row["related_claims"]
    assert set(claims) == {"claim-a", "claim-b"}
    files: Any = row["file_refs"]
    assert set(files) == {"a.py", "b.py"}


def test_load_concepts_pagination(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    for i in range(5):
        upsert_concept(
            db,
            term_key=f"concept-{i:02d}",
            concept=f"Concept {i}",
            run_id="r1",
            source_ref="ref",
            branch_hint=None,
            related_claims=(),
            file_refs=(),
        )
    page1 = load_concepts_from_db(db, limit=2)
    assert len(page1) == 2
    assert page1[0]["term_key"] == "concept-00"
    page2 = load_concepts_from_db(db, limit=2, after_term_key=str(page1[-1]["term_key"]))
    assert len(page2) == 2
    assert page2[0]["term_key"] == "concept-02"


def test_count_concepts(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    assert count_concepts(db) == 0
    initialize_review_db(db)
    assert count_concepts(db) == 0
    upsert_concept(
        db,
        term_key="a",
        concept="A",
        run_id="r1",
        source_ref="ref",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    assert count_concepts(db) == 1


def test_upsert_concepts_batch(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    entries: list[dict[str, object]] = [
        {
            "term_key": "a",
            "concept": "A",
            "introduced_by_run": "r1",
            "source_refs": ["ref1"],
            "related_claims": [],
            "file_refs": [],
        },
        {
            "term_key": "b",
            "concept": "B",
            "introduced_by_run": "r1",
            "source_refs": ["ref1"],
            "related_claims": [],
            "file_refs": [],
        },
    ]
    count = upsert_concepts_batch(db, entries)
    assert count == 2
    assert count_concepts(db) == 2


def test_upsert_concepts_batch_refreshes_display_fields_for_existing_term_key(
    tmp_path: Path,
) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    initial_entries: list[dict[str, object]] = [
        {
            "term_key": "closure",
            "concept": "Closure",
            "term": "closure",
            "display_name": "Closure",
            "lang": "en",
            "aliases": [],
            "introduced_by_run": "r1",
            "source_refs": ["ref1"],
            "updated_by_runs": ["r1"],
            "related_claims": [],
            "file_refs": [],
        }
    ]
    upsert_concepts_batch(
        db,
        initial_entries,
    )

    updated_entries: list[dict[str, object]] = [
        {
            "term_key": "closure",
            "concept": "Closure Refined",
            "term": "closure refined",
            "display_name": "Closure Refined",
            "lang": "zh-CN",
            "aliases": ["fn closure"],
            "introduced_by_run": "r2",
            "source_refs": ["ref2"],
            "updated_by_runs": ["r2"],
            "related_claims": ["claim-2"],
            "file_refs": ["src/app.py"],
        }
    ]
    count = upsert_concepts_batch(
        db,
        updated_entries,
    )

    assert count == 1
    [row] = load_concepts_from_db(db, limit=10)
    assert row["concept"] == "Closure Refined"
    assert row["term"] == "closure refined"
    assert row["display_name"] == "Closure Refined"
    assert row["lang"] == "zh-CN"
    assert row["aliases"] == ["fn closure"]
    assert row["introduced_by_run"] == "r1"
    assert row["source_refs"] == ["ref1", "ref2"]
    assert row["updated_by_runs"] == ["r1", "r2"]
    assert row["related_claims"] == ["claim-2"]
    assert row["file_refs"] == ["src/app.py"]


def test_upsert_concepts_batch_concurrent_writers_merge_without_primary_key_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    barrier = threading.Barrier(2)
    original_connect = review_database_module.connect_review_db

    def wrapped_connect(*args: Any, **kwargs: Any) -> _BarrierConnectionProxy:
        return _BarrierConnectionProxy(
            original_connect(*args, **kwargs),
            barrier,
            select_fragment="FROM concepts WHERE term_key = ?",
        )

    monkeypatch.setattr(review_database_module, "connect_review_db", wrapped_connect)
    errors: list[Exception] = []

    def worker(run_id: str, alias: str, source_ref: str, claim_id: str, file_ref: str) -> None:
        try:
            upsert_concepts_batch(
                db,
                [
                    {
                        "term_key": "closure",
                        "concept": "Closure",
                        "term": "closure",
                        "display_name": "Closure",
                        "lang": "en",
                        "aliases": [alias],
                        "introduced_by_run": run_id,
                        "source_refs": [source_ref],
                        "updated_by_runs": [run_id],
                        "related_claims": [claim_id],
                        "file_refs": [file_ref],
                    }
                ],
            )
        except Exception as exc:  # pragma: no cover - regression guard
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("run-a", "alias-a", "ref-a", "claim-a", "a.py")),
        threading.Thread(target=worker, args=("run-b", "alias-b", "ref-b", "claim-b", "b.py")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    [row] = load_concepts_from_db(db, limit=10)
    a: Any = row["aliases"]
    assert set(a) == {"alias-a", "alias-b"}
    sr: Any = row["source_refs"]
    assert set(sr) == {"ref-a", "ref-b"}
    ur: Any = row["updated_by_runs"]
    assert set(ur) == {"run-a", "run-b"}
    rc: Any = row["related_claims"]
    assert set(rc) == {"claim-a", "claim-b"}
    fr: Any = row["file_refs"]
    assert set(fr) == {"a.py", "b.py"}


def test_import_concepts_from_jsonl(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    jsonl = tmp_path / "concepts.jsonl"
    lines = [
        json.dumps(
            {
                "term_key": "x",
                "concept": "X",
                "introduced_by_run": "r1",
                "source_refs": ["ref"],
                "related_claims": [],
                "file_refs": [],
            }
        ),
        json.dumps(
            {
                "term_key": "y",
                "concept": "Y",
                "introduced_by_run": "r1",
                "source_refs": ["ref"],
                "related_claims": [],
                "file_refs": [],
            }
        ),
    ]
    jsonl.write_text("\n".join(lines) + "\n")
    count = import_concepts_from_jsonl(db, jsonl)
    assert count == 2
    assert count_concepts(db) == 2


def test_import_nonexistent_jsonl(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    assert import_concepts_from_jsonl(db, tmp_path / "nope.jsonl") == 0


def test_import_concepts_rejects_row_missing_required_fields(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    bad = tmp_path / "missing.jsonl"
    bad.write_text('{"term_key":"closure"}\n')
    with pytest.raises(InputError, match="missing term_key or concept"):
        import_concepts_from_jsonl(db, bad)


def test_migration_v2_to_v3(tmp_path: Path) -> None:
    """Verify that a v2 database gets upgraded to v3."""
    db = tmp_path / "review.sqlite"
    # Create a v2 database manually
    from ahadiff.core.sqlite_util import safe_sqlite_connect

    conn = safe_sqlite_connect(db, journal_mode="WAL", foreign_keys=True, defensive=True)
    conn.execute("PRAGMA user_version=2")
    # Create minimal v2 tables
    conn.execute(
        "CREATE TABLE scheduler_presets ("
        "preset_id TEXT PRIMARY KEY, weights TEXT NOT NULL, "
        "desired_retention REAL NOT NULL DEFAULT 0.9, "
        "scheduler_version TEXT NOT NULL, "
        "total_reviews INTEGER NOT NULL DEFAULT 0, "
        "last_optimized_utc TEXT, created_at_utc TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO scheduler_presets VALUES "
        "('default', '[]', 0.9, 'test', 0, NULL, '2024-01-01T00:00:00Z')"
    )
    conn.execute(
        "CREATE TABLE cards ("
        "id TEXT PRIMARY KEY, concept TEXT NOT NULL, run_id TEXT NOT NULL, "
        "fsrs_state TEXT NOT NULL, "
        "card_state TEXT NOT NULL DEFAULT 'active', "
        "scheduler_preset_id TEXT NOT NULL DEFAULT 'default', "
        "scheduler_version TEXT NOT NULL, "
        "desired_retention REAL NOT NULL DEFAULT 0.9, "
        "due_date TEXT NOT NULL, stability REAL NOT NULL, "
        "difficulty REAL NOT NULL, reps INTEGER NOT NULL DEFAULT 0, "
        "lapses INTEGER NOT NULL DEFAULT 0, "
        "scaffolding_level TEXT NOT NULL DEFAULT 'full', "
        "last_rating INTEGER, last_review_utc TEXT, "
        "source_ref TEXT NOT NULL, file_id TEXT NOT NULL, "
        "display_path TEXT NOT NULL, hunk_id TEXT NOT NULL, "
        "hunk_hash TEXT NOT NULL, symbol TEXT, change_kind TEXT, "
        "stale_reason TEXT, created_at_utc TEXT NOT NULL, "
        "archived_at_utc TEXT, suspended_at_utc TEXT)"
    )
    conn.execute(
        "CREATE TABLE review_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "card_id TEXT NOT NULL, rating INTEGER NOT NULL, "
        "reviewed_at_utc TEXT NOT NULL, elapsed_days REAL NOT NULL, "
        "scheduled_days REAL NOT NULL, state TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE result_events ("
        "event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, "
        "event_type TEXT NOT NULL, timestamp TEXT NOT NULL, "
        "source_ref TEXT NOT NULL, base_ref TEXT, "
        "prompt_version TEXT NOT NULL, "
        "eval_bundle_version TEXT NOT NULL, "
        "rubric_version TEXT, overall REAL NOT NULL, "
        "verdict TEXT NOT NULL, status TEXT NOT NULL, "
        "weakest_dim TEXT NOT NULL, note_json TEXT)"
    )
    conn.execute(
        "CREATE TABLE learning_signals ("
        "event_id TEXT PRIMARY KEY, "
        "idempotency_key TEXT NOT NULL UNIQUE, "
        "signal_type TEXT NOT NULL, "
        "payload_json TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    # Now open with the new code which should trigger migration
    initialize_review_db(db)

    with connect_review_db(db) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION
        # concepts table should exist
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "concepts" in tables
        # review_logs should have review_duration
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(review_logs)").fetchall()}
        assert "review_duration" in columns


def test_load_concepts_from_nonexistent_db(tmp_path: Path) -> None:
    assert load_concepts_from_db(tmp_path / "nope.sqlite", limit=10) == ()


def test_count_concepts_nonexistent_db(tmp_path: Path) -> None:
    assert count_concepts(tmp_path / "nope.sqlite") == 0


def test_import_concepts_from_jsonl_rejects_symlink(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    real_file = tmp_path / "real.jsonl"
    real_file.write_text('{"term_key":"a","concept":"A"}\n')
    link = tmp_path / "concepts.jsonl"
    link.symlink_to(real_file)

    with pytest.raises(InputError, match="symlink"):
        import_concepts_from_jsonl(db, link)


def test_import_concepts_from_jsonl_rejects_oversized(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    huge = tmp_path / "huge.jsonl"
    huge.write_text("x" * (17 * 1024 * 1024))

    with pytest.raises(InputError, match="16 MiB"):
        import_concepts_from_jsonl(db, huge)


def test_import_concepts_from_jsonl_fails_fast_on_malformed(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"term_key":"ok","concept":"OK"}\nnot-json\n')

    with pytest.raises(InputError, match="invalid concepts JSONL line"):
        import_concepts_from_jsonl(db, bad)


def test_graphify_node_id_column_exists_on_fresh_db(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    with connect_review_db(db) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(concepts)").fetchall()}
    assert "graphify_node_id" in columns


def test_upsert_concepts_batch_stores_graphify_node_id(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    entries: list[dict[str, object]] = [
        {
            "term_key": "closure",
            "concept": "Closure",
            "introduced_by_run": "r1",
            "source_refs": ["ref1"],
            "related_claims": [],
            "file_refs": [],
            "graphify_node_id": "node-42",
        },
    ]
    upsert_concepts_batch(db, entries)
    [row] = load_concepts_from_db(db, limit=10)
    assert row["graphify_node_id"] == "node-42"


def test_upsert_concepts_batch_graphify_node_id_defaults_to_none(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    entries: list[dict[str, object]] = [
        {
            "term_key": "closure",
            "concept": "Closure",
            "introduced_by_run": "r1",
            "source_refs": [],
            "related_claims": [],
            "file_refs": [],
        },
    ]
    upsert_concepts_batch(db, entries)
    [row] = load_concepts_from_db(db, limit=10)
    assert row["graphify_node_id"] is None


def test_upsert_preserves_existing_graphify_node_id_when_new_is_none(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concepts_batch(
        db,
        [
            {
                "term_key": "x",
                "concept": "X",
                "introduced_by_run": "r1",
                "source_refs": [],
                "related_claims": [],
                "file_refs": [],
                "graphify_node_id": "node-1",
            }
        ],
    )
    upsert_concepts_batch(
        db,
        [
            {
                "term_key": "x",
                "concept": "X updated",
                "introduced_by_run": "r2",
                "source_refs": [],
                "related_claims": [],
                "file_refs": [],
            }
        ],
    )
    [row] = load_concepts_from_db(db, limit=10)
    assert row["graphify_node_id"] == "node-1"
    assert row["concept"] == "X updated"


def test_upsert_overwrites_graphify_node_id_when_new_is_provided(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    upsert_concepts_batch(
        db,
        [
            {
                "term_key": "x",
                "concept": "X",
                "introduced_by_run": "r1",
                "source_refs": [],
                "related_claims": [],
                "file_refs": [],
                "graphify_node_id": "old-node",
            }
        ],
    )
    upsert_concepts_batch(
        db,
        [
            {
                "term_key": "x",
                "concept": "X",
                "introduced_by_run": "r2",
                "source_refs": [],
                "related_claims": [],
                "file_refs": [],
                "graphify_node_id": "new-node",
            }
        ],
    )
    [row] = load_concepts_from_db(db, limit=10)
    assert row["graphify_node_id"] == "new-node"


def test_migration_v4_to_v5_adds_graphify_node_id(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    from ahadiff.core.sqlite_util import safe_sqlite_connect

    conn = safe_sqlite_connect(db, journal_mode="WAL", foreign_keys=True, defensive=True)
    conn.execute("PRAGMA user_version=4")
    conn.execute(
        "CREATE TABLE scheduler_presets ("
        "preset_id TEXT PRIMARY KEY, weights TEXT NOT NULL, "
        "desired_retention REAL NOT NULL DEFAULT 0.9, "
        "scheduler_version TEXT NOT NULL, "
        "total_reviews INTEGER NOT NULL DEFAULT 0, "
        "last_optimized_utc TEXT, created_at_utc TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO scheduler_presets VALUES "
        "('default', '[]', 0.9, 'test', 0, NULL, '2024-01-01T00:00:00Z')"
    )
    conn.execute(
        "CREATE TABLE cards ("
        "id TEXT PRIMARY KEY, concept TEXT NOT NULL, run_id TEXT NOT NULL, "
        "fsrs_state TEXT NOT NULL, "
        "card_state TEXT NOT NULL DEFAULT 'active', "
        "scheduler_preset_id TEXT NOT NULL DEFAULT 'default', "
        "scheduler_version TEXT NOT NULL, "
        "desired_retention REAL NOT NULL DEFAULT 0.9, "
        "due_date TEXT NOT NULL, stability REAL NOT NULL, "
        "difficulty REAL NOT NULL, reps INTEGER NOT NULL DEFAULT 0, "
        "lapses INTEGER NOT NULL DEFAULT 0, "
        "scaffolding_level TEXT NOT NULL DEFAULT 'full', "
        "last_rating INTEGER, last_review_utc TEXT, "
        "source_ref TEXT NOT NULL, file_id TEXT NOT NULL, "
        "display_path TEXT NOT NULL, hunk_id TEXT NOT NULL, "
        "hunk_hash TEXT NOT NULL, symbol TEXT, change_kind TEXT, "
        "stale_reason TEXT, created_at_utc TEXT NOT NULL, "
        "archived_at_utc TEXT, suspended_at_utc TEXT)"
    )
    conn.execute(
        "CREATE TABLE review_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "card_id TEXT NOT NULL, rating INTEGER NOT NULL, "
        "reviewed_at_utc TEXT NOT NULL, elapsed_days REAL NOT NULL, "
        "scheduled_days REAL NOT NULL, state TEXT NOT NULL, "
        "review_duration INTEGER)"
    )
    conn.execute(
        "CREATE TABLE result_events ("
        "event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, "
        "event_type TEXT NOT NULL, timestamp TEXT NOT NULL, "
        "source_ref TEXT NOT NULL, base_ref TEXT, "
        "prompt_version TEXT NOT NULL, "
        "eval_bundle_version TEXT NOT NULL, "
        "rubric_version TEXT, overall REAL NOT NULL, "
        "verdict TEXT NOT NULL, status TEXT NOT NULL, "
        "weakest_dim TEXT NOT NULL, note_json TEXT)"
    )
    conn.execute(
        "CREATE TABLE learning_signals ("
        "event_id TEXT PRIMARY KEY, "
        "idempotency_key TEXT NOT NULL UNIQUE, "
        "signal_type TEXT NOT NULL, "
        "payload_json TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE concepts ("
        "term_key TEXT PRIMARY KEY, concept TEXT NOT NULL, "
        "term TEXT NOT NULL, display_name TEXT NOT NULL, "
        "lang TEXT NOT NULL DEFAULT 'en', aliases TEXT NOT NULL DEFAULT '[]', "
        "source_refs TEXT NOT NULL DEFAULT '[]', branch_hint TEXT, "
        "introduced_by_run TEXT NOT NULL, "
        "updated_by_runs TEXT NOT NULL DEFAULT '[]', "
        "related_claims TEXT NOT NULL DEFAULT '[]', "
        "file_refs TEXT NOT NULL DEFAULT '[]', "
        "created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO concepts VALUES "
        "('closure', 'Closure', 'closure', 'Closure', 'en', '[]', "
        "'[]', NULL, 'r1', '[]', '[]', '[]', "
        "'2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE fts_concepts USING fts5("
        "term_key UNINDEXED, concept, display_name, aliases, "
        "content='concepts', content_rowid='rowid')"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE fts_result_events USING fts5("
        "event_id UNINDEXED, source_ref, weakest_dim, note_json, "
        "content='result_events', content_rowid='rowid')"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE fts_cards USING fts5("
        "id UNINDEXED, concept, display_path, symbol, "
        "content='cards', content_rowid='rowid')"
    )
    conn.commit()
    conn.close()

    initialize_review_db(db)

    with connect_review_db(db) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(concepts)").fetchall()}
        assert "graphify_node_id" in columns
        row = conn.execute(
            "SELECT graphify_node_id FROM concepts WHERE term_key = 'closure'"
        ).fetchone()
        assert row["graphify_node_id"] is None
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "commit_ancestry" in tables
