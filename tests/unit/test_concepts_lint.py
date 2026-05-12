"""Tests for v10 schema migration and deterministic concept lint engine."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

from ahadiff.core.errors import InputError
from ahadiff.review.database import (
    CURRENT_SCHEMA_VERSION,
    connect_review_db,
    initialize_review_db,
)
from ahadiff.wiki.lint import (
    LintFinding,
    canonical_term_key,
    detect_contradictions,
    detect_orphans,
    detect_stale_by_file_deletion,
    detect_stale_by_line_drift,
    run_deterministic_lint,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_current_schema_version_is_10() -> None:
    assert CURRENT_SCHEMA_VERSION == 10


def test_v10_migration_creates_concept_status_and_lint_run_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    initialize_review_db(db_path)
    with connect_review_db(db_path) as connection:
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        status_cols = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(concept_status)").fetchall()
        }
        lint_cols = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(concept_lint_runs)").fetchall()
        }
    assert user_version == 10
    assert "concept_status" in tables
    assert "concept_lint_runs" in tables
    assert {
        "term_key",
        "health_status",
        "stale_since",
        "contradicted_by_run",
        "refcount",
        "dismissed_reason",
        "dismissed_at_utc",
        "updated_at_utc",
    } <= status_cols
    assert {
        "lint_id",
        "started_at_utc",
        "finished_at_utc",
        "mode",
        "findings_count",
        "run_summary_json",
    } <= lint_cols


def test_v10_migration_check_constraints_reject_unknown_status(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    initialize_review_db(db_path)
    with connect_review_db(db_path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO concept_status (
                term_key, health_status, refcount, updated_at_utc
            ) VALUES (?, ?, ?, ?)
            """,
            ("term-x", "bogus", 0, "2026-05-12T00:00:00Z"),
        )


def test_v10_migration_check_constraints_reject_unknown_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    initialize_review_db(db_path)
    with connect_review_db(db_path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO concept_lint_runs (
                lint_id, started_at_utc, mode, findings_count
            ) VALUES (?, ?, ?, ?)
            """,
            ("lint-1", "2026-05-12T00:00:00Z", "remote_sync", 0),
        )


def test_v9_to_v10_upgrade_preserves_existing_data(tmp_path: Path) -> None:
    """A pre-existing v9 DB with concept rows is upgraded without data loss."""

    db_path = tmp_path / "review.sqlite"
    initialize_review_db(db_path)
    with connect_review_db(db_path) as connection:
        connection.execute(
            """
            INSERT INTO concepts (
                term_key, concept, term, display_name, lang, aliases,
                source_refs, branch_hint, introduced_by_run, updated_by_runs,
                related_claims, file_refs, graphify_node_id,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "closure",
                "Closure",
                "Closure",
                "Closure",
                "en",
                "[]",
                '["sha1"]',
                "main",
                "run-1",
                '["run-1"]',
                "[]",
                '["src/foo.py"]',
                None,
                "2026-05-12T00:00:00Z",
                "2026-05-12T00:00:00Z",
            ),
        )
    _force_user_version(db_path, 9)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS concept_status")
        conn.execute("DROP TABLE IF EXISTS concept_lint_runs")
        conn.commit()

    initialize_review_db(db_path)
    with connect_review_db(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        concept = connection.execute(
            "SELECT term_key, concept FROM concepts WHERE term_key = 'closure'"
        ).fetchone()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert version == 10
    assert concept is not None
    assert tuple(concept) == ("closure", "Closure")
    assert "concept_status" in tables
    assert "concept_lint_runs" in tables


def test_canonical_term_key_nfc_casefold() -> None:
    decomposed = "Café"  # NFD form of "Café"
    composed = "Café"
    assert canonical_term_key(decomposed) == canonical_term_key(composed)
    assert canonical_term_key("Closure") == canonical_term_key("CLOSURE")


def test_canonical_term_key_empty_raises() -> None:
    with pytest.raises(InputError):
        canonical_term_key("   ")


def test_detect_orphans_when_no_recent_references() -> None:
    concepts = [
        {"term_key": "alpha", "updated_by_runs": ["run-1"]},
        {"term_key": "beta", "updated_by_runs": ["run-99"]},
    ]
    findings = detect_orphans(
        concepts,
        recent_runs=["run-90", "run-91", "run-92", "run-93", "run-94"],
        threshold=5,
    )
    keys = {finding.term_key for finding in findings}
    assert "alpha" in keys
    assert "beta" in keys


def test_detect_orphans_keeps_referenced_concepts() -> None:
    concepts: list[dict[str, object]] = [
        {"term_key": "alpha", "updated_by_runs": ["run-92"]},
        {"term_key": "beta", "updated_by_runs": []},
    ]
    findings = detect_orphans(
        concepts,  # type: ignore[arg-type]
        recent_runs=["run-90", "run-91", "run-92"],
        threshold=3,
    )
    assert {f.term_key for f in findings} == {"beta"}


def test_detect_orphans_invalid_threshold() -> None:
    with pytest.raises(InputError):
        detect_orphans([], recent_runs=[], threshold=-1)


def test_detect_stale_by_file_deletion_flags_missing_files(tmp_path: Path) -> None:
    concepts = [
        {
            "term_key": "gone",
            "file_refs": ["src/deleted.py", "src/also_gone.py"],
        },
        {
            "term_key": "present",
            "file_refs": ["src/keep.py"],
        },
    ]
    tracked = frozenset({"src/keep.py"})
    findings = detect_stale_by_file_deletion(
        concepts,
        repo_root=tmp_path,
        tracked_files=tracked,
    )
    assert {f.term_key for f in findings} == {"gone"}
    finding = next(f for f in findings if f.term_key == "gone")
    assert finding.new_status == "stale"
    assert finding.stale_reason == "file_deleted"


def test_detect_stale_by_file_deletion_skips_partial_loss(tmp_path: Path) -> None:
    """If at least one file_ref still exists, do not mark stale."""

    concepts = [
        {
            "term_key": "partial",
            "file_refs": ["src/keep.py", "src/gone.py"],
        }
    ]
    tracked = frozenset({"src/keep.py"})
    findings = detect_stale_by_file_deletion(
        concepts,
        repo_root=tmp_path,
        tracked_files=tracked,
    )
    assert findings == []


def test_detect_stale_by_line_drift_flags_drift(tmp_path: Path) -> None:
    concepts = [
        {
            "term_key": "drifted",
            "source_refs": ["src/foo.py:500"],
        }
    ]
    line_counts = {"src/foo.py": 12}
    findings = detect_stale_by_line_drift(
        concepts,
        repo_root=tmp_path,
        drift_threshold=50,
        file_line_counts=line_counts,
    )
    assert {f.term_key for f in findings} == {"drifted"}
    finding = findings[0]
    assert finding.stale_reason == "line_drifted"


def test_detect_stale_by_line_drift_ignores_small_drift(tmp_path: Path) -> None:
    concepts = [
        {
            "term_key": "ok",
            "source_refs": ["src/foo.py:100"],
        }
    ]
    line_counts = {"src/foo.py": 110}
    findings = detect_stale_by_line_drift(
        concepts,
        repo_root=tmp_path,
        drift_threshold=50,
        file_line_counts=line_counts,
    )
    assert findings == []


def test_detect_stale_by_line_drift_ignores_non_lineref(tmp_path: Path) -> None:
    """source_refs without ':<digits>' (e.g. commit SHAs) must not trigger drift."""

    concepts = [
        {
            "term_key": "sha-only",
            "source_refs": ["abcdef0123456789"],
        }
    ]
    findings = detect_stale_by_line_drift(
        concepts,
        repo_root=tmp_path,
        drift_threshold=10,
        file_line_counts={},
    )
    assert findings == []


def test_run_deterministic_lint_dry_run_skips_db_writes(tmp_path: Path) -> None:
    concepts = [
        {
            "term_key": "alpha",
            "updated_by_runs": ["run-old"],
            "file_refs": ["src/missing.py"],
        }
    ]
    summary = run_deterministic_lint(
        concepts=concepts,
        recent_runs=["run-new"],
        repo_root=tmp_path,
        db_path=None,
        dry_run=True,
        tracked_files=frozenset({"src/keep.py"}),
    )
    assert summary.findings
    db_path = tmp_path / "review.sqlite"
    assert not db_path.exists()


def test_run_deterministic_lint_requires_db_path_when_not_dry_run(tmp_path: Path) -> None:
    with pytest.raises(InputError):
        run_deterministic_lint(
            concepts=[],
            recent_runs=[],
            repo_root=tmp_path,
            db_path=None,
            dry_run=False,
        )


def test_run_deterministic_lint_persists_findings(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    initialize_review_db(db_path)
    concepts = [
        {
            "term_key": "orphaned",
            "updated_by_runs": ["run-archived"],
            "file_refs": [],
            "source_refs": [],
        },
        {
            "term_key": "deleted-file",
            "updated_by_runs": ["run-current"],
            "file_refs": ["src/gone.py"],
            "source_refs": [],
        },
    ]
    summary = run_deterministic_lint(
        concepts=concepts,
        recent_runs=["run-current"],
        repo_root=tmp_path,
        db_path=db_path,
        dry_run=False,
        tracked_files=frozenset({"src/exists.py"}),
    )
    assert len(summary.findings) == 2
    with connect_review_db(db_path) as connection:
        runs = connection.execute(
            "SELECT lint_id, mode, findings_count FROM concept_lint_runs"
        ).fetchall()
        statuses = {
            row["term_key"]: row["health_status"]
            for row in connection.execute(
                "SELECT term_key, health_status FROM concept_status"
            ).fetchall()
        }
    assert len(runs) == 1
    assert runs[0]["lint_id"] == summary.lint_id
    assert runs[0]["mode"] == "deterministic"
    assert runs[0]["findings_count"] == 2
    assert statuses == {"orphaned": "orphan", "deleted-file": "stale"}


def test_run_deterministic_lint_stale_wins_over_orphan(tmp_path: Path) -> None:
    """When a concept is both orphan and stale, stale (file_deleted) takes precedence."""

    concepts = [
        {
            "term_key": "both",
            "updated_by_runs": ["run-old"],
            "file_refs": ["src/gone.py"],
        }
    ]
    summary = run_deterministic_lint(
        concepts=concepts,
        recent_runs=["run-new"],
        repo_root=tmp_path,
        db_path=None,
        dry_run=True,
        tracked_files=frozenset(),
    )
    relevant = [f for f in summary.findings if f.term_key == "both"]
    assert len(relevant) == 1
    assert relevant[0].new_status == "stale"
    assert relevant[0].stale_reason == "file_deleted"


def test_detect_contradictions_flags_related_contradicted_claim() -> None:
    concepts = [
        {
            "term_key": "risky",
            "related_claims": ["claim-ok", "claim-bad"],
        },
        {
            "term_key": "safe",
            "related_claims": ["claim-ok"],
        },
    ]
    claims = [
        {"claim_id": "claim-ok", "status": "verified", "run_id": "run-a"},
        {"claim_id": "claim-bad", "status": "contradicted", "run_id": "run-b"},
    ]
    findings = detect_contradictions(concepts, claims)
    assert len(findings) == 1
    assert findings[0].term_key == "risky"
    assert findings[0].new_status == "contradicted"
    assert findings[0].contradicted_by_run == "run-b"


def test_run_deterministic_lint_preserves_dismissed_status(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    initialize_review_db(db_path)
    with connect_review_db(db_path) as connection:
        connection.execute(
            """
            INSERT INTO concept_status (
                term_key, health_status, refcount, dismissed_reason,
                dismissed_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "dismissed-concept",
                "dismissed",
                0,
                "user dismissed",
                "2026-05-12T00:00:00Z",
                "2026-05-12T00:00:00Z",
            ),
        )
    summary = run_deterministic_lint(
        concepts=[
            {
                "term_key": "dismissed-concept",
                "updated_by_runs": ["run-old"],
                "file_refs": ["src/gone.py"],
                "source_refs": ["src/gone.py:999"],
                "related_claims": ["claim-bad"],
            }
        ],
        recent_runs=["run-new"],
        repo_root=tmp_path,
        db_path=db_path,
        dry_run=False,
        tracked_files=frozenset({"src/exists.py"}),
        file_line_counts={"src/gone.py": 1},
        claims=[{"claim_id": "claim-bad", "status": "contradicted", "run_id": "run-b"}],
    )
    assert summary.findings == ()
    with connect_review_db(db_path) as connection:
        row = connection.execute(
            "SELECT health_status FROM concept_status WHERE term_key = ?",
            ("dismissed-concept",),
        ).fetchone()
    assert row is not None
    assert row["health_status"] == "dismissed"


def test_run_deterministic_lint_persists_contradicted_by_run(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    initialize_review_db(db_path)
    summary = run_deterministic_lint(
        concepts=[
            {
                "term_key": "risky",
                "updated_by_runs": ["run-current"],
                "related_claims": ["claim-bad"],
            }
        ],
        recent_runs=["run-current"],
        repo_root=tmp_path,
        db_path=db_path,
        dry_run=False,
        tracked_files=frozenset(),
        claims=[{"claim_id": "claim-bad", "status": "contradicted", "run_id": "run-b"}],
    )
    assert len(summary.findings) == 1
    with connect_review_db(db_path) as connection:
        row = connection.execute(
            """
            SELECT health_status, contradicted_by_run
            FROM concept_status WHERE term_key = ?
            """,
            ("risky",),
        ).fetchone()
    assert row is not None
    assert row["health_status"] == "contradicted"
    assert row["contradicted_by_run"] == "run-b"


def test_run_deterministic_lint_idempotent_lint_id_unique(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    initialize_review_db(db_path)
    concepts: list[dict[str, Any]] = [
        {
            "term_key": "alpha",
            "updated_by_runs": ["run-old"],
            "file_refs": [],
        }
    ]
    first = run_deterministic_lint(
        concepts=concepts,
        recent_runs=["run-new"],
        repo_root=tmp_path,
        db_path=db_path,
        dry_run=False,
    )
    second = run_deterministic_lint(
        concepts=concepts,
        recent_runs=["run-new"],
        repo_root=tmp_path,
        db_path=db_path,
        dry_run=False,
    )
    assert first.lint_id != second.lint_id
    with connect_review_db(db_path) as connection:
        rows = connection.execute("SELECT lint_id FROM concept_lint_runs").fetchall()
    assert len(rows) == 2


def test_lint_finding_dataclass_immutable() -> None:
    from dataclasses import FrozenInstanceError

    finding = LintFinding(
        term_key="x",
        current_status="healthy",
        new_status="orphan",
        reason="no refs",
    )
    with pytest.raises(FrozenInstanceError):
        finding.term_key = "y"  # type: ignore[misc]


def _force_user_version(db_path: Path, version: int) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"PRAGMA user_version={version}")
        connection.commit()
