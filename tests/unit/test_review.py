from __future__ import annotations

import json
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from typer.testing import CliRunner

from ahadiff import cli as cli_module
from ahadiff.cli import app
from ahadiff.contracts import ResultEvent, ReviewCard
from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.paths import is_wsl2_mnt, lock_file_path, review_db_path
from ahadiff.quiz import QuizArtifactPaths
from ahadiff.review import database as review_database_module
from ahadiff.review.database import (
    CURRENT_SCHEMA_VERSION,
    check_review_db,
    checkpoint_review_db,
    connect_review_db,
    finalize_targeted_verify_event,
    import_cards_from_jsonl,
    import_results_tsv_lossy,
    initialize_review_db,
    list_due_cards,
    load_result_events_from_db,
    record_card_review,
    resolve_sqlite_journal_mode,
    set_card_queue_state,
    sync_result_event,
    upgrade_review_db,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_RUNNER = CliRunner()


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _review_card(card_id: str = "card-1") -> ReviewCard:
    return ReviewCard(
        card_id=card_id,
        concept="retry loop",
        run_id="run-1",
        source_ref="abc1234",
        fsrs_state="{}",
        file_id="file-app",
        display_path="src/app.py",
        hunk_id="hunk-1",
        hunk_hash="deadbeefcafe",
        symbol="retry_once",
    )


def _write_cards_jsonl(path: Path, cards: tuple[ReviewCard, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(card.model_dump(mode="json")) + "\n" for card in cards),
        encoding="utf-8",
    )


def _create_v1_review_db_without_stale_reason(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_version (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL
            );
            INSERT INTO schema_version (id, version) VALUES (1, 1);

            CREATE TABLE scheduler_presets (
                preset_id TEXT PRIMARY KEY,
                weights TEXT NOT NULL,
                desired_retention REAL NOT NULL DEFAULT 0.9,
                scheduler_version TEXT NOT NULL,
                total_reviews INTEGER NOT NULL DEFAULT 0,
                last_optimized_utc TEXT,
                created_at_utc TEXT NOT NULL
            );

            CREATE TABLE cards (
                id TEXT PRIMARY KEY,
                concept TEXT NOT NULL,
                run_id TEXT NOT NULL,
                fsrs_state TEXT NOT NULL,
                card_state TEXT NOT NULL DEFAULT 'active',
                scheduler_preset_id TEXT NOT NULL DEFAULT 'default'
                    REFERENCES scheduler_presets(preset_id),
                scheduler_version TEXT NOT NULL,
                desired_retention REAL NOT NULL DEFAULT 0.9,
                due_date TEXT NOT NULL,
                stability REAL NOT NULL,
                difficulty REAL NOT NULL,
                reps INTEGER NOT NULL DEFAULT 0,
                lapses INTEGER NOT NULL DEFAULT 0,
                scaffolding_level TEXT NOT NULL DEFAULT 'full',
                last_rating INTEGER,
                last_review_utc TEXT,
                source_ref TEXT,
                file_id TEXT,
                display_path TEXT,
                hunk_id TEXT,
                hunk_hash TEXT,
                symbol TEXT,
                change_kind TEXT,
                created_at_utc TEXT NOT NULL,
                archived_at_utc TEXT,
                suspended_at_utc TEXT
            );

            CREATE TABLE review_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT NOT NULL REFERENCES cards(id),
                rating INTEGER NOT NULL,
                reviewed_at_utc TEXT NOT NULL,
                elapsed_days REAL NOT NULL,
                scheduled_days REAL NOT NULL,
                state TEXT NOT NULL
            );

            CREATE TABLE result_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                base_ref TEXT,
                prompt_version TEXT NOT NULL,
                eval_bundle_version TEXT NOT NULL,
                rubric_version TEXT,
                overall REAL NOT NULL,
                verdict TEXT NOT NULL,
                status TEXT NOT NULL,
                weakest_dim TEXT NOT NULL,
                note_json TEXT
            );

            CREATE TABLE learning_signals (
                event_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                signal_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def _result_event(
    event_id: str = "018f0f52-91c0-7abc-8123-000000000101",
    *,
    status: str = "baseline",
    event_type: str = "learn",
    timestamp: str = "2026-04-24T00:00:00Z",
) -> ResultEvent:
    return ResultEvent(
        event_id=event_id,
        run_id="run-1",
        event_type=event_type,
        timestamp=timestamp,
        source_ref="abc1234",
        base_ref=None,
        prompt_version="prompt123",
        eval_bundle_version="eval123",
        rubric_version="rubric-v1",
        overall=88.0,
        verdict="PASS",
        status=cast("Any", status),
        weakest_dim="evidence",
        note_json=None,
    )


def test_initialize_review_db_creates_full_schema_and_pragmas(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    db_path = review_db_path(repo_root)

    initialize_review_db(db_path)

    with connect_review_db(db_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        index_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        schema_version = connection.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        ).fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]

    assert schema_version == CURRENT_SCHEMA_VERSION
    assert {"cards", "scheduler_presets", "review_logs", "result_events", "learning_signals"} <= (
        table_names
    )
    assert "ux_result_events_run_type_ts" in index_names
    assert busy_timeout == 5000
    assert journal_mode == "wal"
    assert quick_check == "ok"

    with connect_review_db(db_path) as connection:
        card_info = {
            str(row["name"]): row
            for row in connection.execute("PRAGMA table_info(cards)").fetchall()
        }
        cards_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'cards'"
        ).fetchone()[0]
    assert "stale_reason" in card_info
    assert "CHECK (card_state IN ('active', 'stale', 'archived', 'suspended'))" in str(cards_sql)
    for column in ("source_ref", "file_id", "display_path", "hunk_id", "hunk_hash"):
        assert int(card_info[column]["notnull"]) == 1


def test_is_wsl2_mnt_detects_only_linux_wsl_mount_paths() -> None:
    wsl_env = {"WSL_DISTRO_NAME": "Ubuntu", "WSL_INTEROP": "/run/WSL/1_interop"}

    assert is_wsl2_mnt(Path("/mnt/c/project"), platform="linux", env=wsl_env) is True
    assert is_wsl2_mnt(Path("/mnt/c/project"), platform="darwin", env=wsl_env) is False
    assert is_wsl2_mnt(Path("/home/user/project"), platform="linux", env=wsl_env) is False
    assert is_wsl2_mnt(Path("/mnt"), platform="linux", env=wsl_env) is False
    assert is_wsl2_mnt(Path("/mnt/c/project"), platform="linux", env={}) is False


@pytest.mark.parametrize(
    ("is_wsl2_mount", "expected_mode"),
    ((False, "WAL"), (True, "DELETE")),
)
def test_connect_review_db_applies_resolved_journal_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    is_wsl2_mount: bool,
    expected_mode: str,
) -> None:
    db_path = tmp_path / "review.sqlite"

    def fake_is_wsl2_mnt(_path: Path) -> bool:
        return is_wsl2_mount

    monkeypatch.setattr(review_database_module, "is_wsl2_mnt", fake_is_wsl2_mnt)

    assert resolve_sqlite_journal_mode(db_path) == expected_mode
    initialize_review_db(db_path)

    with connect_review_db(db_path) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert journal_mode == expected_mode.lower()


def test_restore_review_db_checkpoints_before_after_and_removes_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    backup_path = tmp_path / "manual.bak"
    initialize_review_db(db_path)
    sync_result_event(db_path, _result_event())
    review_database_module.backup_review_db(db_path, backup_path)
    sync_result_event(
        db_path,
        _result_event(event_id="018f0f52-91c0-7abc-8123-000000000102"),
    )
    for suffix in ("-wal", "-shm", "-journal"):
        db_path.with_name(f"{db_path.name}{suffix}").write_text("stale sidecar", encoding="utf-8")
    checkpointed_paths: list[Path] = []

    def recording_checkpoint(path: Path) -> None:
        checkpointed_paths.append(path)

    monkeypatch.setattr(review_database_module, "checkpoint_review_db", recording_checkpoint)

    review_database_module.restore_review_db(db_path=db_path, backup_path=backup_path)

    assert checkpointed_paths == [backup_path, db_path, db_path]
    for suffix in ("-wal", "-shm", "-journal"):
        assert not db_path.with_name(f"{db_path.name}{suffix}").exists()
    assert [event.event_id for event in load_result_events_from_db(db_path)] == [
        "018f0f52-91c0-7abc-8123-000000000101"
    ]


def test_restore_review_db_removes_real_stale_sidecars_without_mocked_checkpoint(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review.sqlite"
    backup_path = tmp_path / "manual.bak"
    initialize_review_db(db_path)
    sync_result_event(db_path, _result_event())
    review_database_module.backup_review_db(db_path, backup_path)
    sync_result_event(
        db_path,
        _result_event(event_id="018f0f52-91c0-7abc-8123-000000000102"),
    )
    for suffix in ("-wal", "-shm", "-journal"):
        db_path.with_name(f"{db_path.name}{suffix}").write_text("stale sidecar", encoding="utf-8")

    review_database_module.restore_review_db(db_path=db_path, backup_path=backup_path)

    for base_path in (db_path, backup_path):
        for suffix in ("-wal", "-shm", "-journal"):
            assert not base_path.with_name(f"{base_path.name}{suffix}").exists()
    assert [event.event_id for event in load_result_events_from_db(db_path)] == [
        "018f0f52-91c0-7abc-8123-000000000101"
    ]


def test_checkpoint_review_db_ignores_missing_database(tmp_path: Path) -> None:
    checkpoint_review_db(tmp_path / "missing.sqlite")


def test_connect_review_db_does_not_create_missing_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "missing-parent" / "review.sqlite"

    with pytest.raises(InputError, match="review DB parent directory does not exist"):
        connect_review_db(db_path)

    assert not db_path.parent.exists()


def test_initialize_review_db_creates_missing_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "missing-parent" / "review.sqlite"

    initialize_review_db(db_path)

    assert db_path.exists()
    assert db_path.parent.exists()


def test_initialize_review_db_migrates_legacy_result_events_only_db(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    event = _result_event()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE result_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                base_ref TEXT,
                prompt_version TEXT NOT NULL,
                eval_bundle_version TEXT NOT NULL,
                rubric_version TEXT,
                overall REAL NOT NULL,
                verdict TEXT NOT NULL,
                status TEXT NOT NULL,
                weakest_dim TEXT NOT NULL,
                note_json TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO result_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.run_id,
                event.event_type,
                event.timestamp,
                event.source_ref,
                event.base_ref,
                event.prompt_version,
                event.eval_bundle_version,
                event.rubric_version,
                event.overall,
                event.verdict,
                event.status,
                event.weakest_dim,
                event.note_json,
            ),
        )

    initialize_review_db(db_path)

    rows = load_result_events_from_db(db_path)
    check = check_review_db(db_path)
    assert len(rows) == 1
    assert rows[0].event_id == event.event_id
    assert check.schema_version == CURRENT_SCHEMA_VERSION


def test_cards_schema_rejects_invalid_state_and_null_core_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    initialize_review_db(db_path)

    insert_sql = """
        INSERT INTO cards (
            id,
            concept,
            run_id,
            fsrs_state,
            card_state,
            scheduler_version,
            due_date,
            stability,
            difficulty,
            source_ref,
            file_id,
            display_path,
            hunk_id,
            hunk_hash,
            created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    base_params = (
        "card-raw",
        "retry loop",
        "run-raw",
        "{}",
        "active",
        "fsrs-test",
        "2026-04-24T00:00:00Z",
        0.0,
        0.0,
        "abc1234",
        "file-app",
        "src/app.py",
        "hunk-1",
        "deadbeef",
        "2026-04-24T00:00:00Z",
    )

    with connect_review_db(db_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="cards\\.card_state|CHECK constraint"):
            connection.execute(insert_sql, (*base_params[:4], "broken", *base_params[5:]))
        with pytest.raises(
            sqlite3.IntegrityError,
            match="core anchor fields must not be NULL|NOT NULL constraint failed",
        ):
            connection.execute(insert_sql, (*base_params[:9], None, *base_params[10:]))


def test_backup_review_db_rejects_missing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "missing" / "review.sqlite"

    with pytest.raises(InputError, match="review\\.sqlite does not exist"):
        review_database_module.backup_review_db(db_path)

    assert not db_path.parent.exists()


def test_sync_result_event_is_idempotent_under_review_db_owner(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    event = _result_event()

    assert sync_result_event(db_path, event) is True
    assert sync_result_event(db_path, event) is False

    rows = load_result_events_from_db(db_path)
    assert len(rows) == 1
    assert rows[0].event_id == event.event_id


def test_import_cards_and_record_fsrs_review(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    cards_path = tmp_path / "cards.jsonl"
    _write_cards_jsonl(cards_path, (_review_card(),))

    inserted = import_cards_from_jsonl(db_path, cards_path)
    due_cards = list_due_cards(db_path)

    assert inserted == 1
    assert [card.card_id for card in due_cards] == ["card-1"]

    update = record_card_review(
        db_path,
        card_id="card-1",
        answer="good",
        reviewed_at_utc=datetime(2026, 4, 24, tzinfo=UTC),
    )

    assert update.rating == 3
    assert update.stability > 0
    assert update.difficulty > 0
    assert json.loads(update.fsrs_state)["last_review"] == "2026-04-24T00:00:00+00:00"
    with connect_review_db(db_path) as connection:
        card_row = connection.execute("SELECT reps, last_rating FROM cards").fetchone()
        log_row = connection.execute("SELECT rating, state FROM review_logs").fetchone()
        preset_row = connection.execute(
            "SELECT total_reviews FROM scheduler_presets WHERE preset_id = 'default'"
        ).fetchone()
    assert tuple(card_row) == (1, 3)
    assert log_row["rating"] == 3
    assert preset_row["total_reviews"] == 1


def test_record_card_review_rejects_missing_or_archived_card(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    cards_path = tmp_path / "cards.jsonl"
    _write_cards_jsonl(cards_path, (_review_card(),))
    import_cards_from_jsonl(db_path, cards_path)
    set_card_queue_state(db_path, card_id="card-1", state="archived")

    with pytest.raises(InputError, match="active review card does not exist: missing-card"):
        record_card_review(db_path, card_id="missing-card", answer="good")
    with pytest.raises(InputError, match="active review card does not exist: card-1"):
        record_card_review(db_path, card_id="card-1", answer="good")


def test_import_cards_migrates_v1_cards_table_before_writing_stale_reason(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    cards_path = tmp_path / "cards.jsonl"
    _create_v1_review_db_without_stale_reason(db_path)
    _write_cards_jsonl(cards_path, (_review_card(),))

    inserted = import_cards_from_jsonl(db_path, cards_path)
    check = check_review_db(db_path)

    assert inserted == 1
    assert check.schema_version == CURRENT_SCHEMA_VERSION
    with connect_review_db(db_path) as connection:
        card_columns = {row[1] for row in connection.execute("PRAGMA table_info(cards)").fetchall()}
        stored = connection.execute(
            "SELECT id, stale_reason FROM cards WHERE id = 'card-1'"
        ).fetchone()
    assert "stale_reason" in card_columns
    assert tuple(stored) == ("card-1", None)


def test_import_cards_marks_missing_run_cards_stale_instead_of_leaving_duplicates(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review.sqlite"
    initial_cards = tmp_path / "cards-initial.jsonl"
    replacement_cards = tmp_path / "cards-replacement.jsonl"
    _write_cards_jsonl(initial_cards, (_review_card("card-1"),))
    _write_cards_jsonl(replacement_cards, (_review_card("card-2"),))

    assert import_cards_from_jsonl(db_path, initial_cards) == 1
    assert import_cards_from_jsonl(db_path, replacement_cards) == 1

    due_cards = list_due_cards(db_path)
    assert [card.card_id for card in due_cards] == ["card-2"]
    with connect_review_db(db_path) as connection:
        rows = connection.execute(
            "SELECT id, card_state, stale_reason FROM cards ORDER BY id"
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("card-1", "stale", "staleness_unknown"),
        ("card-2", "active", None),
    ]


def test_peek_guard_rejects_good_review(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    cards_path = tmp_path / "cards.jsonl"
    _write_cards_jsonl(cards_path, (_review_card(),))
    import_cards_from_jsonl(db_path, cards_path)

    with pytest.raises(Exception, match="peeked cards cannot be reviewed as good"):
        record_card_review(
            db_path,
            card_id="card-1",
            answer="good",
            peeked_this_session=True,
        )

    update = record_card_review(
        db_path,
        card_id="card-1",
        answer="hard",
        peeked_this_session=True,
    )
    assert update.rating == 2


def test_card_queue_archive_suspend_do_not_write_review_log(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    cards_path = tmp_path / "cards.jsonl"
    _write_cards_jsonl(cards_path, (_review_card(), _review_card("card-2")))
    import_cards_from_jsonl(db_path, cards_path)

    set_card_queue_state(db_path, card_id="card-1", state="archived")
    set_card_queue_state(db_path, card_id="card-2", state="suspended")

    assert list_due_cards(db_path) == ()
    with connect_review_db(db_path) as connection:
        rows = connection.execute(
            "SELECT id, card_state, archived_at_utc, suspended_at_utc FROM cards ORDER BY id"
        ).fetchall()
        log_count = connection.execute("SELECT COUNT(*) FROM review_logs").fetchone()[0]
    assert rows[0]["card_state"] == "archived"
    assert rows[0]["archived_at_utc"] is not None
    assert rows[1]["card_state"] == "suspended"
    assert rows[1]["suspended_at_utc"] is not None
    assert log_count == 0


def test_set_card_queue_state_rejects_missing_card_and_allows_double_archive(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review.sqlite"
    cards_path = tmp_path / "cards.jsonl"
    _write_cards_jsonl(cards_path, (_review_card(),))
    import_cards_from_jsonl(db_path, cards_path)

    with pytest.raises(InputError, match="review card does not exist: missing-card"):
        set_card_queue_state(db_path, card_id="missing-card", state="archived")

    set_card_queue_state(
        db_path,
        card_id="card-1",
        state="archived",
        changed_at_utc=datetime(2026, 4, 24, tzinfo=UTC),
    )
    set_card_queue_state(
        db_path,
        card_id="card-1",
        state="archived",
        changed_at_utc=datetime(2026, 4, 25, tzinfo=UTC),
    )

    with connect_review_db(db_path) as connection:
        row = connection.execute(
            "SELECT card_state, archived_at_utc FROM cards WHERE id = 'card-1'"
        ).fetchone()
    assert tuple(row) == ("archived", "2026-04-25T00:00:00Z")


def test_review_cli_imports_cards_and_records_answer(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    cards_path = repo_root / ".ahadiff" / "runs" / "run-1" / "quiz" / "cards.jsonl"
    _write_cards_jsonl(cards_path, (_review_card(),))

    list_result = _RUNNER.invoke(
        app(),
        ["review", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )
    assert list_result.exit_code == 0
    assert "card-1" in list_result.stdout

    review_result = _RUNNER.invoke(
        app(),
        [
            "review",
            "--repo-root",
            str(repo_root),
            "--card-id",
            "card-1",
            "--answer",
            "wrong",
        ],
        catch_exceptions=False,
    )

    assert review_result.exit_code == 0
    assert "Rating" in review_result.stdout
    with connect_review_db(review_db_path(repo_root)) as connection:
        row = connection.execute("SELECT reps, lapses, last_rating FROM cards").fetchone()
    assert tuple(row) == (1, 1, 1)


def test_review_cli_warns_and_skips_schema_invalid_cards_jsonl(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    bad_cards_path = repo_root / ".ahadiff" / "runs" / "run-bad" / "quiz" / "cards.jsonl"
    good_cards_path = repo_root / ".ahadiff" / "runs" / "run-good" / "quiz" / "cards.jsonl"
    bad_cards_path.parent.mkdir(parents=True, exist_ok=True)
    bad_cards_path.write_text(json.dumps({"card_id": "broken"}) + "\n", encoding="utf-8")
    _write_cards_jsonl(good_cards_path, (_review_card("card-good"),))

    result = _RUNNER.invoke(
        app(),
        ["review", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "card-good" in result.stdout
    assert "Warning" in result.stderr
    assert "run-bad" in result.stderr.replace("\n", "")


def test_review_cli_archive_card_without_rating(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    cards_path = repo_root / ".ahadiff" / "runs" / "run-1" / "quiz" / "cards.jsonl"
    _write_cards_jsonl(cards_path, (_review_card(),))

    result = _RUNNER.invoke(
        app(),
        [
            "review",
            "--repo-root",
            str(repo_root),
            "--card-id",
            "card-1",
            "--action",
            "archive",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "Archived" in result.stdout
    with connect_review_db(review_db_path(repo_root)) as connection:
        row = connection.execute(
            "SELECT card_state, reps FROM cards WHERE id = 'card-1'"
        ).fetchone()
        log_count = connection.execute("SELECT COUNT(*) FROM review_logs").fetchone()[0]
    assert tuple(row) == ("archived", 0)
    assert log_count == 0


def test_regenerate_only_quiz_rewrites_quiz_without_touching_lesson(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    run_path = repo_root / ".ahadiff" / "runs" / "run-reg"
    lesson_path = run_path / "lesson" / "lesson.full.md"
    quiz_path = run_path / "quiz" / "quiz.jsonl"
    lesson_path.parent.mkdir(parents=True)
    quiz_path.parent.mkdir(parents=True)
    lesson_path.write_text("keep this lesson\n", encoding="utf-8")
    quiz_path.write_text('{"old": true}\n', encoding="utf-8")
    calls: list[str] = []

    class _FakeReport:
        verdict = "PASS"

    def fake_generate_quiz_from_run(
        **kwargs: object,
    ) -> tuple[QuizArtifactPaths, tuple[object, ...]]:
        calls.append("quiz")
        assert kwargs["overwrite"] is True
        quiz_path.write_text('{"new": true}\n', encoding="utf-8")
        return QuizArtifactPaths(quiz_dir=quiz_path.parent, quiz_path=quiz_path), ()

    def fake_generate_cards_for_run(**kwargs: object) -> Path:
        calls.append("cards")
        cards_path = run_path / "quiz" / "cards.jsonl"
        _write_cards_jsonl(cards_path, (_review_card(),))
        return cards_path

    def fake_evaluate_run(_run_path: Path) -> _FakeReport:
        return _FakeReport()

    monkeypatch.setattr(cli_module, "generate_quiz_from_run", fake_generate_quiz_from_run)
    monkeypatch.setattr(cli_module, "generate_cards_for_run", fake_generate_cards_for_run)
    monkeypatch.setattr(cli_module, "evaluate_run", fake_evaluate_run)

    result = _RUNNER.invoke(
        app(),
        [
            "regenerate",
            "run-reg",
            "--only",
            "quiz",
            "--repo-root",
            str(repo_root),
            "--base-url",
            "http://127.0.0.1:8318",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert calls == ["quiz", "cards"]
    assert lesson_path.read_text(encoding="utf-8") == "keep this lesson\n"
    assert quiz_path.read_text(encoding="utf-8") == '{"new": true}\n'


def test_regenerate_only_quiz_uses_run_content_lang(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    run_path = repo_root / ".ahadiff" / "runs" / "run-reg"
    quiz_path = run_path / "quiz" / "quiz.jsonl"
    quiz_path.parent.mkdir(parents=True)
    quiz_path.write_text('{"old": true}\n', encoding="utf-8")
    (run_path / "metadata.json").write_text(
        json.dumps({"content_lang": "zh-CN"}) + "\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class _FakeReport:
        verdict = "PASS"

    def fake_generate_quiz_from_run(
        **kwargs: object,
    ) -> tuple[QuizArtifactPaths, tuple[object, ...]]:
        captured.update(kwargs)
        quiz_path.write_text('{"new": true}\n', encoding="utf-8")
        return QuizArtifactPaths(quiz_dir=quiz_path.parent, quiz_path=quiz_path), ()

    def fake_generate_cards_for_run(**kwargs: object) -> Path:
        del kwargs
        cards_path = run_path / "quiz" / "cards.jsonl"
        _write_cards_jsonl(cards_path, (_review_card(),))
        return cards_path

    def fake_evaluate_run(_run_path: Path) -> _FakeReport:
        return _FakeReport()

    monkeypatch.setattr(cli_module, "generate_quiz_from_run", fake_generate_quiz_from_run)
    monkeypatch.setattr(cli_module, "generate_cards_for_run", fake_generate_cards_for_run)
    monkeypatch.setattr(cli_module, "evaluate_run", fake_evaluate_run)

    result = _RUNNER.invoke(
        app(),
        [
            "regenerate",
            "run-reg",
            "--only",
            "quiz",
            "--repo-root",
            str(repo_root),
            "--base-url",
            "http://127.0.0.1:8318",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["output_lang"] == "zh-CN"


def test_regenerate_only_quiz_rejects_concurrent_session_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    run_path = repo_root / ".ahadiff" / "runs" / "run-reg"
    (run_path / "quiz").mkdir(parents=True)
    observed_locks: list[tuple[Path, str]] = []
    generated = False

    @contextmanager
    def fake_repo_write_lock(lock_path: Path, *, command: str) -> Iterator[Path]:
        observed_locks.append((lock_path, command))
        if command:
            raise StorageError("另一个 ahadiff 进程正在运行(PID=123)")
        yield lock_path

    def fake_generate_quiz_from_run(
        **kwargs: object,
    ) -> tuple[QuizArtifactPaths, tuple[object, ...]]:
        nonlocal generated
        del kwargs
        generated = True
        raise AssertionError("quiz generation should not start while the repo lock is held")

    monkeypatch.setattr(cli_module, "repo_write_lock", fake_repo_write_lock)
    monkeypatch.setattr(cli_module, "generate_quiz_from_run", fake_generate_quiz_from_run)

    result = _RUNNER.invoke(
        app(),
        [
            "regenerate",
            "run-reg",
            "--only",
            "quiz",
            "--repo-root",
            str(repo_root),
            "--base-url",
            "http://127.0.0.1:8318",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "another ahadiff session is already running" in result.stderr
    assert observed_locks == [(lock_file_path(repo_root), "regenerate quiz")]
    assert generated is False


def test_regenerate_only_quiz_restores_previous_artifacts_when_evaluate_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    run_path = repo_root / ".ahadiff" / "runs" / "run-reg"
    lesson_path = run_path / "lesson" / "lesson.full.md"
    quiz_path = run_path / "quiz" / "quiz.jsonl"
    cards_path = run_path / "quiz" / "cards.jsonl"
    lesson_path.parent.mkdir(parents=True)
    quiz_path.parent.mkdir(parents=True)
    lesson_path.write_text("keep this lesson\n", encoding="utf-8")
    quiz_path.write_text('{"old": true}\n', encoding="utf-8")
    cards_path.write_text('{"old-card": true}\n', encoding="utf-8")

    def fake_generate_quiz_from_run(
        **kwargs: object,
    ) -> tuple[QuizArtifactPaths, tuple[object, ...]]:
        del kwargs
        quiz_path.write_text('{"new": true}\n', encoding="utf-8")
        return QuizArtifactPaths(quiz_dir=quiz_path.parent, quiz_path=quiz_path), ()

    def fail_evaluate_run(_run_path: Path) -> object:
        raise RuntimeError("simulated evaluate failure")

    monkeypatch.setattr(cli_module, "generate_quiz_from_run", fake_generate_quiz_from_run)
    monkeypatch.setattr(cli_module, "evaluate_run", fail_evaluate_run)

    result = _RUNNER.invoke(
        app(),
        [
            "regenerate",
            "run-reg",
            "--only",
            "quiz",
            "--repo-root",
            str(repo_root),
            "--base-url",
            "http://127.0.0.1:8318",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 2
    assert "simulated evaluate failure" in result.stderr
    assert lesson_path.read_text(encoding="utf-8") == "keep this lesson\n"
    assert quiz_path.read_text(encoding="utf-8") == '{"old": true}\n'
    assert cards_path.read_text(encoding="utf-8") == '{"old-card": true}\n'


def test_regenerate_only_quiz_marks_existing_run_cards_stale_when_verdict_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    run_path = repo_root / ".ahadiff" / "runs" / "run-reg"
    lesson_path = run_path / "lesson" / "lesson.full.md"
    quiz_path = run_path / "quiz" / "quiz.jsonl"
    cards_path = run_path / "quiz" / "cards.jsonl"
    lesson_path.parent.mkdir(parents=True)
    quiz_path.parent.mkdir(parents=True)
    lesson_path.write_text("keep this lesson\n", encoding="utf-8")
    quiz_path.write_text('{"old": true}\n', encoding="utf-8")
    _write_cards_jsonl(cards_path, (_review_card().model_copy(update={"run_id": "run-reg"}),))
    import_cards_from_jsonl(review_db_path(repo_root), cards_path)

    class _FailReport:
        verdict = "FAIL"

    def fake_generate_quiz_from_run(
        **kwargs: object,
    ) -> tuple[QuizArtifactPaths, tuple[object, ...]]:
        del kwargs
        quiz_path.write_text('{"new": true}\n', encoding="utf-8")
        return QuizArtifactPaths(quiz_dir=quiz_path.parent, quiz_path=quiz_path), ()

    def fake_evaluate_run(_run_path: Path) -> _FailReport:
        return _FailReport()

    monkeypatch.setattr(cli_module, "generate_quiz_from_run", fake_generate_quiz_from_run)
    monkeypatch.setattr(cli_module, "evaluate_run", fake_evaluate_run)

    result = _RUNNER.invoke(
        app(),
        [
            "regenerate",
            "run-reg",
            "--only",
            "quiz",
            "--repo-root",
            str(repo_root),
            "--base-url",
            "http://127.0.0.1:8318",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert quiz_path.read_text(encoding="utf-8") == '{"new": true}\n'
    assert not cards_path.exists()
    with connect_review_db(review_db_path(repo_root)) as connection:
        row = connection.execute(
            "SELECT card_state, stale_reason FROM cards WHERE id = 'card-1'"
        ).fetchone()
    assert tuple(row) == ("stale", "staleness_unknown")


def test_mark_wrong_cli_writes_idempotent_learning_signal(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    first = _RUNNER.invoke(
        app(),
        ["mark", "claim-1", "wrong", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )
    second = _RUNNER.invoke(
        app(),
        ["mark", "claim-1", "wrong", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "Already marked wrong" in second.stdout
    with connect_review_db(review_db_path(repo_root)) as connection:
        rows = connection.execute(
            "SELECT signal_type, payload_json FROM learning_signals"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["signal_type"] == "mark_wrong"
    assert json.loads(rows[0]["payload_json"]) == {"claim_id": "claim-1"}


def test_finalize_targeted_verify_clones_new_keep_final_event(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    targeted = _result_event(
        event_id="018f0f52-91c0-7abc-8123-000000000201",
        status="targeted_verify",
        event_type="improve",
        timestamp="2026-04-24T00:00:00Z",
    )
    sync_result_event(db_path, targeted)

    finalized = finalize_targeted_verify_event(
        db_path,
        run_id="run-1",
        event_id="018f0f52-91c0-7abc-8123-000000000202",
        timestamp=datetime(2026, 4, 25, tzinfo=UTC),
    )

    rows = load_result_events_from_db(db_path)
    assert finalized.status == "keep_final"
    assert finalized.event_type == "improve"
    assert len(rows) == 2
    assert {row.status for row in rows} == {"targeted_verify", "keep_final"}
    assert json.loads(finalized.note_json or "{}")["finalized_from_event_id"] == targeted.event_id


def test_finalize_targeted_verify_requires_source_event(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"

    with pytest.raises(InputError, match="targeted_verify result event does not exist"):
        finalize_targeted_verify_event(db_path, run_id="run-missing")


def test_db_cli_finalize_targeted_verify(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    sync_result_event(
        review_db_path(repo_root),
        _result_event(status="targeted_verify", event_type="improve"),
    )

    result = _RUNNER.invoke(
        app(),
        ["db", "finalize-targeted", "run-1", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    rows = load_result_events_from_db(review_db_path(repo_root))
    assert {row.status for row in rows} == {"targeted_verify", "keep_final"}


def test_import_results_tsv_lossy_synthesizes_missing_event_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    tsv_path = tmp_path / "results.tsv"
    tsv_path.write_text(
        "\t".join(
            (
                "timestamp",
                "run_id",
                "source_ref",
                "base_ref",
                "prompt_version",
                "rubric_version",
                "overall",
                "verdict",
                "status",
                "weakest_dim",
                "note_json",
            )
        )
        + "\n"
        + "\t".join(
            (
                "2026-04-24T00:00:00Z",
                "run-1",
                "abc1234",
                "",
                "prompt123",
                "rubric-v1",
                "91.50",
                "PASS",
                "baseline",
                "evidence",
                "",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    outcome = import_results_tsv_lossy(db_path, tsv_path)
    rows = load_result_events_from_db(db_path)

    assert outcome.imported == 1
    assert outcome.skipped == 0
    assert rows[0].event_type == "imported_from_tsv"
    assert rows[0].eval_bundle_version == "imported_from_tsv"
    assert json.loads(rows[0].note_json or "{}")["lossy_import"] is True


def test_import_results_tsv_lossy_uses_single_connection_for_multiple_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    tsv_path = tmp_path / "results.tsv"
    tsv_path.write_text(
        "timestamp\trun_id\tsource_ref\tbase_ref\tprompt_version\trubric_version\t"
        "overall\tverdict\tstatus\tweakest_dim\tnote_json\n"
        "2026-04-24T00:00:00Z\trun-1\tabc1234\t\tprompt123\trubric-v1\t"
        "91.50\tPASS\tbaseline\tevidence\t\n"
        "2026-04-24T00:00:01Z\trun-2\tdef5678\t\tprompt123\trubric-v1\t"
        "88.00\tPASS\tnon_ratcheted\tcoverage\t\n",
        encoding="utf-8",
    )
    connection_count = 0
    real_connect = review_database_module.connect_review_db

    def counting_connect(
        db_path_arg: Path,
        *,
        create_parent: bool = False,
    ) -> sqlite3.Connection:
        nonlocal connection_count
        connection_count += 1
        return real_connect(db_path_arg, create_parent=create_parent)

    monkeypatch.setattr(review_database_module, "connect_review_db", counting_connect)

    outcome = import_results_tsv_lossy(db_path, tsv_path)

    assert outcome == review_database_module.LossyImportOutcome(imported=2, skipped=0)
    assert connection_count == 1


def test_import_results_tsv_lossy_rolls_back_partial_batch_on_invalid_row(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    tsv_path = tmp_path / "results.tsv"
    tsv_path.write_text(
        "timestamp\trun_id\tsource_ref\tbase_ref\tprompt_version\trubric_version\t"
        "overall\tverdict\tstatus\tweakest_dim\tnote_json\n"
        "2026-04-24T00:00:00Z\trun-1\tabc1234\t\tprompt123\trubric-v1\t"
        "91.50\tPASS\tbaseline\tevidence\t\n"
        "2026-04-24T00:00:01Z\trun-2\tdef5678\t\tprompt123\trubric-v1\t"
        "not-a-number\tPASS\tnon_ratcheted\tcoverage\t\n",
        encoding="utf-8",
    )

    with pytest.raises(InputError, match="invalid overall score"):
        import_results_tsv_lossy(db_path, tsv_path)

    assert load_result_events_from_db(db_path) == ()


def test_import_results_tsv_lossy_rejects_duplicate_lossy_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    tsv_path = tmp_path / "results.tsv"
    tsv_path.write_text(
        "timestamp\trun_id\tsource_ref\tbase_ref\tprompt_version\trubric_version\t"
        "overall\tverdict\tstatus\tweakest_dim\tnote_json\n"
        "2026-04-24T00:00:00Z\trun-1\tabc1234\t\tprompt123\trubric-v1\t"
        "91.50\tPASS\tbaseline\tevidence\t\n"
        "2026-04-24T00:00:00Z\trun-1\tabc1234\t\tprompt123\trubric-v1\t"
        "88.00\tPASS\tnon_ratcheted\tcoverage\t\n",
        encoding="utf-8",
    )

    with pytest.raises(InputError, match="duplicate lossy identity"):
        import_results_tsv_lossy(db_path, tsv_path)

    assert load_result_events_from_db(db_path) == ()


def test_db_import_results_requires_lossy_confirmation(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    tsv_path = tmp_path / "results.tsv"
    tsv_path.write_text(
        "timestamp\trun_id\tsource_ref\tbase_ref\tprompt_version\trubric_version\t"
        "overall\tverdict\tstatus\tweakest_dim\tnote_json\n"
        "2026-04-24T00:00:00Z\trun-1\tabc1234\t\tprompt123\trubric-v1\t"
        "91.50\tPASS\tbaseline\tevidence\t\n",
        encoding="utf-8",
    )

    rejected = _RUNNER.invoke(
        app(),
        ["db", "import-results", str(tsv_path), "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )
    accepted = _RUNNER.invoke(
        app(),
        [
            "db",
            "import-results",
            str(tsv_path),
            "--repo-root",
            str(repo_root),
            "--i-understand-this-is-lossy",
        ],
        catch_exceptions=False,
    )

    assert rejected.exit_code == 1
    assert "is lossy" in rejected.stderr
    assert accepted.exit_code == 0
    rows = load_result_events_from_db(review_db_path(repo_root))
    assert len(rows) == 1


def test_make_uuid7_is_monotonic_within_same_millisecond(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 4, 24, 12, 0, 0, 123000, tzinfo=UTC)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            del tz
            return fixed_now

    monkeypatch.setattr(review_database_module, "datetime", _FrozenDatetime)
    monkeypatch.setattr(review_database_module, "_uuid7_last_timestamp_ms", -1)
    monkeypatch.setattr(review_database_module, "_uuid7_last_tail", -1)

    identifiers = [review_database_module.make_uuid7() for _ in range(1024)]

    assert identifiers == sorted(identifiers)
    assert len(set(identifiers)) == len(identifiers)


def test_upgrade_failure_restores_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    initialize_review_db(db_path)
    sync_result_event(db_path, _result_event())

    def failing_migration(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE should_not_survive (id INTEGER PRIMARY KEY)")
        raise RuntimeError("boom")

    with pytest.raises(Exception, match="rolled back"):
        upgrade_review_db(db_path, migration_hook=failing_migration)

    with connect_review_db(db_path) as connection:
        leftover = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'should_not_survive'"
        ).fetchone()
    assert leftover is None
    assert len(load_result_events_from_db(db_path)) == 1


def test_db_cli_upgrade_backup_check_and_restore(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    db_path = review_db_path(repo_root)
    initialize_review_db(db_path)

    backup_path = tmp_path / "manual.bak"
    backup_result = _RUNNER.invoke(
        app(),
        ["db", "backup", "--repo-root", str(repo_root), "--output", str(backup_path)],
        catch_exceptions=False,
    )
    assert backup_result.exit_code == 0
    assert backup_path.exists()

    check_result = _RUNNER.invoke(
        app(),
        ["db", "check", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )
    assert check_result.exit_code == 0
    assert "SQLite quick_check" in check_result.stdout
    assert "Event id unique" in check_result.stdout

    with connect_review_db(db_path) as connection:
        connection.execute(
            "INSERT INTO learning_signals VALUES (?, ?, ?, ?, ?)",
            ("event-1", "key-1", "mark_wrong", "{}", "2026-04-24T00:00:00Z"),
        )
    restore_result = _RUNNER.invoke(
        app(),
        ["db", "restore", str(backup_path), "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )
    assert restore_result.exit_code == 0
    with connect_review_db(db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM learning_signals").fetchone()[0]
    assert count == 0
