from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from ahadiff.contracts import ResultEvent, ReviewCard
from ahadiff.contracts.quiz_choice import (
    AnswerMode,
    QuizChoice,
    QuizChoiceLabel,
    validate_quiz_choices,
)
from ahadiff.core.errors import InputError, MigrationError, StorageError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import is_wsl2_mnt
from ahadiff.core.sqlite_util import safe_sqlite_connect

from .scheduler import (
    DEFAULT_DESIRED_RETENTION,
    default_scheduler_parameters,
    default_weights_json,
    normalize_fsrs_state,
    review_fsrs_card,
    scheduler_version,
    snapshot_card_state,
)
from .schemas import DueReviewCard, ReviewAnswer, ReviewDbCheck, ReviewUpdate

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

CURRENT_SCHEMA_VERSION = 9
_SQLITE_MIN_VERSION = (3, 51, 3)
_SQLITE_ALLOWED_BACKPORTS = {(3, 50, 7), (3, 44, 6)}
_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_SQLITE_SIDECAR_REMOVE_ATTEMPTS = 5
_SQLITE_SIDECAR_REMOVE_DELAY_SECONDS = 0.05
_VALID_ANSWER_MODES: tuple[AnswerMode, ...] = ("open", "multiple_choice")
_RESULT_EVENT_COLUMNS = (
    "event_id",
    "run_id",
    "event_type",
    "timestamp",
    "source_ref",
    "base_ref",
    "prompt_version",
    "eval_bundle_version",
    "rubric_version",
    "overall",
    "verdict",
    "status",
    "weakest_dim",
    "note_json",
)
_UUID7_LOCK = threading.Lock()
_uuid7_last_timestamp_ms = -1
_uuid7_last_tail = -1
_UUID7_TIMESTAMP_MASK = (1 << 48) - 1
_UUID7_TAIL_MASK = (1 << 74) - 1
_UUID7_RANDOM_B_MASK = (1 << 62) - 1


MigrationStep = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class UpgradeOutcome:
    db_path: Path
    backup_path: Path
    schema_version: int


@dataclass(frozen=True)
class LossyImportOutcome:
    imported: int
    skipped: int


def resolve_sqlite_journal_mode(db_path: Path) -> str:
    return "DELETE" if is_wsl2_mnt(db_path) else "WAL"


def connect_review_db(db_path: Path, *, create_parent: bool = False) -> sqlite3.Connection:
    _assert_sqlite_runtime_supported()
    try:
        if create_parent:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        elif not db_path.parent.exists():
            raise InputError(f"review DB parent directory does not exist: {db_path.parent}")
        connection = safe_sqlite_connect(
            db_path,
            journal_mode=resolve_sqlite_journal_mode(db_path),
            row_factory=sqlite3.Row,
            foreign_keys=True,
            defensive=True,
        )
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"review.sqlite is not a valid database: {db_path} ({exc})") from exc
    except OSError as exc:
        raise StorageError(f"failed to open review.sqlite safely: {db_path} ({exc})") from exc
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or quick_check[0] != "ok":
            value = "unknown" if quick_check is None else str(quick_check[0])
            raise StorageError(f"SQLite quick_check failed for {db_path}: {value}")
        return connection
    except Exception:
        connection.close()
        raise


def _connect_review_db_maintenance(
    db_path: Path,
    *,
    create_parent: bool = False,
) -> sqlite3.Connection:
    _assert_sqlite_runtime_supported()
    try:
        if create_parent:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        elif not db_path.parent.exists():
            raise InputError(f"review DB parent directory does not exist: {db_path.parent}")
        return safe_sqlite_connect(
            db_path,
            journal_mode=resolve_sqlite_journal_mode(db_path),
            foreign_keys=True,
            defensive=True,
        )
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"review.sqlite is not a valid database: {db_path} ({exc})") from exc
    except OSError as exc:
        raise StorageError(f"failed to open review.sqlite safely: {db_path} ({exc})") from exc


def initialize_review_db(db_path: Path) -> None:
    with connect_review_db(db_path, create_parent=True) as connection:
        _ensure_schema(connection)


def upgrade_review_db(
    db_path: Path,
    *,
    migration_hook: Callable[[sqlite3.Connection], None] | None = None,
) -> UpgradeOutcome:
    backup_path = backup_review_db(db_path)
    connection: sqlite3.Connection | None = None
    try:
        connection = connect_review_db(db_path)
        _ensure_schema(connection)
        if migration_hook is not None:
            connection.execute("BEGIN EXCLUSIVE")
            migration_hook(connection)
            connection.execute("COMMIT")
    except Exception as exc:
        if connection is not None:
            with suppress(sqlite3.DatabaseError):
                connection.execute("ROLLBACK")
            connection.close()
            connection = None
        restore_review_db(db_path=db_path, backup_path=backup_path)
        raise MigrationError(f"review.sqlite migration failed and was rolled back: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
    return UpgradeOutcome(
        db_path=db_path,
        backup_path=backup_path,
        schema_version=CURRENT_SCHEMA_VERSION,
    )


def backup_review_db(db_path: Path, backup_path: Path | None = None) -> Path:
    if not (db_path.exists() or db_path.is_symlink()):
        raise InputError(f"review.sqlite does not exist: {db_path}")
    target = backup_path or _default_backup_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (
            _connect_review_db_maintenance(db_path) as source,
            _connect_review_db_maintenance(
                target,
                create_parent=True,
            ) as backup,
        ):
            source.backup(backup)
            backup.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except (sqlite3.DatabaseError, OSError, StorageError) as exc:
        raise StorageError(
            f"failed to back up review.sqlite from {db_path} to {target}: {exc}"
        ) from exc
    _remove_sqlite_sidecars_with_retry(target)
    return target


def checkpoint_review_db(db_path: Path) -> None:
    if not (db_path.exists() or db_path.is_symlink()):
        return
    with connect_review_db(db_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def restore_review_db(*, db_path: Path, backup_path: Path) -> None:
    if not (backup_path.exists() or backup_path.is_symlink()):
        raise InputError(f"review DB backup does not exist: {backup_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling_path(db_path, suffix=".restore.tmp")
    try:
        try:
            with (
                _connect_review_db_maintenance(backup_path) as source,
                _connect_review_db_maintenance(temp_path, create_parent=True) as target,
            ):
                source.backup(target)
                target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except (sqlite3.DatabaseError, OSError, StorageError) as exc:
            raise StorageError(
                f"failed to restore review.sqlite from backup {backup_path}: {exc}"
            ) from exc
        _remove_sqlite_sidecars_with_retry(temp_path)
        checkpoint_review_db(backup_path)
        _remove_sqlite_sidecars_with_retry(backup_path)
        with suppress(sqlite3.DatabaseError, StorageError):
            checkpoint_review_db(db_path)
        _remove_sqlite_sidecars_with_retry(db_path)
        temp_path.replace(db_path)
        checkpoint_review_db(db_path)
        _remove_sqlite_sidecars_with_retry(db_path)
    finally:
        temp_path.unlink(missing_ok=True)


def check_review_db(db_path: Path) -> ReviewDbCheck:
    if not db_path.exists():
        raise InputError(f"review.sqlite does not exist: {db_path}")
    with connect_review_db(db_path) as connection:
        _ensure_schema(connection)
        quick_check_row = connection.execute("PRAGMA quick_check").fetchone()
        quick_check = "unknown" if quick_check_row is None else str(quick_check_row[0])
        foreign_key_issues = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        event_count = int(connection.execute("SELECT COUNT(*) FROM result_events").fetchone()[0])
        distinct_event_count = int(
            connection.execute("SELECT COUNT(DISTINCT event_id) FROM result_events").fetchone()[0]
        )
        return ReviewDbCheck(
            schema_version=_schema_version(connection),
            quick_check=quick_check,
            foreign_key_issues=foreign_key_issues,
            event_count=event_count,
            event_id_unique=event_count == distinct_event_count,
        )


def sync_result_event(db_path: Path, event: ResultEvent) -> bool:
    try:
        with connect_review_db(db_path, create_parent=True) as connection:
            _ensure_schema(connection)
            return _sync_result_event(connection, event).rowcount > 0
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"failed to append result event to {db_path}: {exc}") from exc


def load_result_events_from_db(db_path: Path) -> tuple[ResultEvent, ...]:
    if not db_path.exists():
        return ()
    try:
        with connect_review_db(db_path) as connection:
            if not _result_events_table_exists(connection):
                return ()
            rows = connection.execute(
                f"""
                SELECT {", ".join(_RESULT_EVENT_COLUMNS)}
                FROM result_events
                ORDER BY timestamp DESC, event_id DESC
                """
            ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"failed to read result_events from {db_path}: {exc}") from exc
    return tuple(ResultEvent.model_validate(dict(row)) for row in rows)


def load_result_events_page(
    db_path: Path,
    *,
    limit: int,
    before: tuple[str, str] | None = None,
    event_ids: Iterable[str] | None = None,
    statuses: Iterable[str] | None = None,
) -> tuple[ResultEvent, ...]:
    if limit <= 0 or not db_path.exists():
        return ()
    event_id_values = _dedupe_filter_values(event_ids)
    if event_ids is not None and not event_id_values:
        return ()
    status_values = _dedupe_filter_values(statuses)
    if statuses is not None and not status_values:
        return ()
    try:
        with connect_review_db(db_path) as connection:
            if not _result_events_table_exists(connection):
                return ()
            rows: list[sqlite3.Row] = []
            if event_id_values is None:
                rows.extend(
                    _select_result_events_page(
                        connection,
                        limit=limit,
                        before=before,
                        event_ids=None,
                        statuses=status_values,
                    )
                )
            else:
                for chunk in _chunks(event_id_values, 700):
                    rows.extend(
                        _select_result_events_page(
                            connection,
                            limit=limit,
                            before=before,
                            event_ids=chunk,
                            statuses=status_values,
                        )
                    )
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"failed to read result_events page from {db_path}: {exc}") from exc
    events = tuple(ResultEvent.model_validate(dict(row)) for row in rows)
    return tuple(
        sorted(events, key=lambda item: (item.timestamp, item.event_id), reverse=True)[:limit]
    )


def load_finalized_ratchet_history_page(
    db_path: Path,
    *,
    finalized_event_ids: Iterable[str],
    statuses: Iterable[str],
    limit: int,
    before: tuple[str, str] | None = None,
) -> tuple[ResultEvent, ...]:
    event_ids = tuple(finalized_event_ids)
    return load_result_events_page(
        db_path,
        limit=limit,
        before=before,
        event_ids=event_ids if event_ids else None,
        statuses=statuses,
    )


def load_result_event_by_run_and_id(
    db_path: Path,
    *,
    run_id: str,
    event_id: str,
) -> ResultEvent | None:
    if not db_path.exists():
        return None
    try:
        with connect_review_db(db_path) as connection:
            if not _result_events_table_exists(connection):
                return None
            row = connection.execute(
                f"""
                SELECT {", ".join(_RESULT_EVENT_COLUMNS)}
                FROM result_events
                WHERE run_id = ? AND event_id = ?
                LIMIT 1
                """,
                (run_id, event_id),
            ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"failed to read result_event from {db_path}: {exc}") from exc
    return None if row is None else ResultEvent.model_validate(dict(row))


def load_result_events_for_improve_chain(
    db_path: Path,
    *,
    source_ref: str,
    base_ref: str | None,
    anchor_run_id: str,
) -> tuple[ResultEvent, ...]:
    if not db_path.exists():
        return ()
    try:
        with connect_review_db(db_path) as connection:
            if not _result_events_table_exists(connection):
                return ()
            rows = connection.execute(
                f"""
                SELECT {", ".join(_RESULT_EVENT_COLUMNS)}
                FROM result_events
                WHERE source_ref = ?
                  AND ((base_ref IS NULL AND ? IS NULL) OR base_ref = ?)
                  AND (
                      run_id = ?
                      OR (
                          note_json IS NOT NULL
                          AND json_valid(note_json)
                          AND json_extract(note_json, '$.anchor_run_id') = ?
                      )
                  )
                ORDER BY timestamp DESC, event_id DESC
                """,
                (source_ref, base_ref, base_ref, anchor_run_id, anchor_run_id),
            ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"failed to read result_events from {db_path}: {exc}") from exc
    return tuple(ResultEvent.model_validate(dict(row)) for row in rows)


def select_result_tsv_rows(db_path: Path) -> tuple[dict[str, object], ...]:
    if not db_path.exists():
        raise InputError(f"review.sqlite does not exist: {db_path}")
    with connect_review_db(db_path) as connection:
        if not _result_events_table_exists(connection):
            raise InputError("result_events table does not exist yet")
        rows = connection.execute(
            """
            SELECT
                timestamp,
                run_id,
                source_ref,
                base_ref,
                prompt_version,
                rubric_version,
                overall,
                verdict,
                status,
                weakest_dim,
                note_json
            FROM result_events
            ORDER BY timestamp ASC, event_id ASC
            """
        ).fetchall()
    return tuple(dict(row) for row in rows)


def delete_result_event(db_path: Path, event_id: str) -> None:
    try:
        with connect_review_db(db_path) as connection:
            if not _result_events_table_exists(connection):
                return
            connection.execute("DELETE FROM result_events WHERE event_id = ?", (event_id,))
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"failed to roll back result event in {db_path}: {exc}") from exc


def delete_result_event_and_select_tsv_rows(
    db_path: Path,
    event_id: str,
) -> tuple[dict[str, object], ...]:
    try:
        with connect_review_db(db_path) as connection:
            if not _result_events_table_exists(connection):
                return ()
            connection.execute("DELETE FROM result_events WHERE event_id = ?", (event_id,))
            rows = connection.execute(
                """
                SELECT
                    timestamp,
                    run_id,
                    source_ref,
                    base_ref,
                    prompt_version,
                    rubric_version,
                    overall,
                    verdict,
                    status,
                    weakest_dim,
                    note_json
                FROM result_events
                ORDER BY timestamp ASC, event_id ASC
                """
            ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise StorageError(
            f"failed to delete result event and select export rows from {db_path}: {exc}"
        ) from exc
    return tuple(dict(row) for row in rows)


def finalize_targeted_verify_event(
    db_path: Path,
    *,
    run_id: str,
    event_id: str | None = None,
    timestamp: datetime | None = None,
) -> ResultEvent:
    with connect_review_db(db_path) as connection:
        _ensure_schema(connection)
        source_row = connection.execute(
            f"""
            SELECT {", ".join(_RESULT_EVENT_COLUMNS)}
            FROM result_events
            WHERE run_id = ? AND status = 'targeted_verify'
            ORDER BY timestamp DESC, event_id DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        if source_row is None:
            raise InputError(f"targeted_verify result event does not exist for run_id: {run_id}")
        source_event = ResultEvent.model_validate(dict(source_row))
        note_payload = _merge_event_note(
            source_event.note_json,
            {"finalized_from_event_id": source_event.event_id},
        )
        finalized_event = source_event.model_copy(
            update={
                "event_id": event_id or make_uuid7(),
                "timestamp": _datetime_to_utc_text(timestamp or datetime.now(UTC)),
                "status": "keep_final",
                "note_json": note_payload,
            }
        )
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO result_events (
                event_id, run_id, event_type, timestamp, source_ref, base_ref,
                prompt_version, eval_bundle_version, rubric_version, overall,
                verdict, status, weakest_dim, note_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                finalized_event.event_id,
                finalized_event.run_id,
                finalized_event.event_type,
                finalized_event.timestamp,
                finalized_event.source_ref,
                finalized_event.base_ref,
                finalized_event.prompt_version,
                finalized_event.eval_bundle_version,
                finalized_event.rubric_version,
                finalized_event.overall,
                finalized_event.verdict,
                finalized_event.status,
                finalized_event.weakest_dim,
                finalized_event.note_json,
            ),
        )
        if cursor.rowcount == 0:
            raise StorageError(
                f"keep_final result event was not inserted: {finalized_event.event_id}"
            )
    return finalized_event


def import_results_tsv_lossy(db_path: Path, tsv_path: Path) -> LossyImportOutcome:
    if not tsv_path.exists():
        raise InputError(f"results TSV does not exist: {tsv_path}")
    imported = 0
    skipped = 0
    seen_identity_keys: set[tuple[str, str, str]] = set()
    try:
        with connect_review_db(db_path, create_parent=True) as connection:
            _ensure_schema(connection)
            with tsv_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                for row in reader:
                    if not row:
                        skipped += 1
                        continue
                    event = _lossy_event_from_tsv_row(row)
                    identity_key = (event.run_id, event.event_type, event.timestamp)
                    if identity_key in seen_identity_keys:
                        raise InputError(
                            "results TSV contains duplicate lossy identity for "
                            f"run_id={event.run_id!r} timestamp={event.timestamp!r}"
                        )
                    seen_identity_keys.add(identity_key)
                    if _sync_result_event(connection, event).rowcount > 0:
                        imported += 1
                    else:
                        skipped += 1
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"failed to import lossy results TSV into {db_path}: {exc}") from exc
    return LossyImportOutcome(imported=imported, skipped=skipped)


def import_cards_from_jsonl(db_path: Path, cards_path: Path) -> int:
    if not cards_path.exists():
        return 0
    cards = _load_review_cards(cards_path)
    if not cards:
        return 0
    card_choice_payloads = tuple(_serialize_card_choices(card) for card in cards)
    now = _utc_now()
    inserted = 0
    with connect_review_db(db_path) as connection:
        _ensure_schema(connection)
        _ensure_default_scheduler_preset(connection, created_at_utc=now)
        run_ids = tuple(sorted({card.run_id for card in cards}))
        card_ids = {card.card_id for card in cards}
        for card, (answer_mode, choices_json) in zip(cards, card_choice_payloads, strict=True):
            normalized_state = normalize_fsrs_state(card.fsrs_state)
            fsrs_state, due_date, stability, difficulty, scaffolding = snapshot_card_state(
                normalized_state
            )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO cards (
                    id,
                    concept,
                    run_id,
                    fsrs_state,
                    card_state,
                    scheduler_preset_id,
                    scheduler_version,
                    desired_retention,
                    due_date,
                    stability,
                    difficulty,
                    reps,
                    lapses,
                    scaffolding_level,
                    last_rating,
                    last_review_utc,
                    source_ref,
                    file_id,
                    display_path,
                    hunk_id,
                    hunk_hash,
                    symbol,
                    change_kind,
                    question,
                    answer,
                    answer_mode,
                    choices_json,
                    stale_reason,
                    created_at_utc,
                    archived_at_utc,
                    suspended_at_utc
                ) VALUES (?, ?, ?, ?, ?, 'default', ?, ?, ?, ?, ?, 0, 0, ?, ?, NULL,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    card.card_id,
                    card.concept,
                    card.run_id,
                    fsrs_state,
                    card.card_state,
                    scheduler_version(),
                    DEFAULT_DESIRED_RETENTION,
                    due_date,
                    stability,
                    difficulty,
                    scaffolding,
                    card.last_rating,
                    card.source_ref,
                    card.file_id,
                    card.display_path,
                    card.hunk_id,
                    card.hunk_hash,
                    card.symbol,
                    card.change_kind,
                    card.question,
                    card.answer,
                    answer_mode,
                    choices_json,
                    card.stale_reason,
                    now,
                ),
            )
            inserted += cursor.rowcount
            if cursor.rowcount == 0:
                connection.execute(
                    """
                    UPDATE cards
                    SET
                        concept = ?,
                        run_id = ?,
                        source_ref = ?,
                        file_id = ?,
                        display_path = ?,
                        hunk_id = ?,
                        hunk_hash = ?,
                        symbol = ?,
                        change_kind = ?,
                        question = ?,
                        answer = ?,
                        answer_mode = ?,
                        choices_json = ?,
                        card_state = CASE
                            WHEN card_state IN ('archived', 'suspended') THEN card_state
                            ELSE ?
                        END,
                        stale_reason = CASE
                            WHEN card_state IN ('archived', 'suspended') THEN stale_reason
                            ELSE ?
                        END
                    WHERE id = ?
                    """,
                    (
                        card.concept,
                        card.run_id,
                        card.source_ref,
                        card.file_id,
                        card.display_path,
                        card.hunk_id,
                        card.hunk_hash,
                        card.symbol,
                        card.change_kind,
                        card.question,
                        card.answer,
                        answer_mode,
                        choices_json,
                        card.card_state,
                        card.stale_reason,
                        card.card_id,
                    ),
                )
        if run_ids:
            placeholders = ", ".join("?" for _ in run_ids)
            rows = connection.execute(
                f"""
                SELECT id
                FROM cards
                WHERE run_id IN ({placeholders}) AND card_state = 'active'
                """,
                run_ids,
            ).fetchall()
            stale_ids = [str(row["id"]) for row in rows if str(row["id"]) not in card_ids]
            if stale_ids:
                stale_placeholders = ", ".join("?" for _ in stale_ids)
                connection.execute(
                    f"""
                    UPDATE cards
                    SET card_state = ?, stale_reason = ?
                    WHERE id IN ({stale_placeholders})
                    """,
                    ("stale", "staleness_unknown", *stale_ids),
                )
    return inserted


def import_cards_from_runs(
    db_path: Path,
    state_dir: Path,
    *,
    on_error: Callable[[Path, Exception], None] | None = None,
) -> int:
    runs_dir = state_dir / "runs"
    if not runs_dir.exists():
        initialize_review_db(db_path)
        return 0
    inserted = 0
    for cards_path in sorted(runs_dir.glob("*/quiz/cards.jsonl")):
        try:
            inserted += import_cards_from_jsonl(db_path, cards_path)
        except (InputError, StorageError) as exc:
            if on_error is not None:
                on_error(cards_path, exc)
            else:
                raise
    return inserted


def mark_run_cards_stale(
    db_path: Path,
    *,
    run_id: str,
    stale_reason: str = "staleness_unknown",
) -> int:
    with connect_review_db(db_path) as connection:
        _ensure_schema(connection)
        cursor = connection.execute(
            """
            UPDATE cards
            SET card_state = ?, stale_reason = ?
            WHERE run_id = ? AND card_state = 'active'
            """,
            ("stale", stale_reason, run_id),
        )
    return cursor.rowcount


def list_due_cards(
    db_path: Path,
    *,
    now_utc: datetime | None = None,
    limit: int = 20,
) -> tuple[DueReviewCard, ...]:
    now_text = _datetime_to_utc_text(now_utc or datetime.now(UTC))
    with connect_review_db(db_path) as connection:
        if _get_schema_version(connection) != CURRENT_SCHEMA_VERSION:
            return ()
        rows = connection.execute(
            """
            SELECT
                id,
                concept,
                run_id,
                due_date,
                scaffolding_level,
                display_path,
                source_ref,
                symbol,
                question,
                answer,
                answer_mode,
                choices_json
            FROM cards
            WHERE card_state = 'active' AND due_date <= ?
            ORDER BY due_date ASC, id ASC
            LIMIT ?
            """,
            (now_text, limit),
        ).fetchall()
    return tuple(_row_to_due_review_card(row) for row in rows)


def get_card(db_path: Path, card_id: str) -> DueReviewCard | None:
    if not db_path.exists():
        return None
    with connect_review_db(db_path) as connection:
        if _get_schema_version(connection) != CURRENT_SCHEMA_VERSION:
            return None
        row = connection.execute(
            """
            SELECT
                id,
                concept,
                run_id,
                due_date,
                scaffolding_level,
                display_path,
                source_ref,
                symbol,
                question,
                answer,
                answer_mode,
                choices_json
            FROM cards
            WHERE id = ?
            LIMIT 1
            """,
            (card_id,),
        ).fetchone()
    return None if row is None else _row_to_due_review_card(row)


def record_card_review(
    db_path: Path,
    *,
    card_id: str,
    answer: ReviewAnswer,
    peeked_this_session: bool = False,
    reviewed_at_utc: datetime | None = None,
) -> ReviewUpdate:
    reviewed_at = reviewed_at_utc or datetime.now(UTC)
    with connect_review_db(db_path) as connection:
        _ensure_schema(connection)
        return _record_card_review(
            connection,
            card_id=card_id,
            answer=answer,
            peeked_this_session=peeked_this_session,
            reviewed_at=reviewed_at,
        )


def record_card_review_once(
    db_path: Path,
    *,
    card_id: str,
    answer: ReviewAnswer,
    idempotency_key: str,
    peeked_this_session: bool = False,
    selected_choice_label: QuizChoiceLabel | None = None,
    reviewed_at_utc: datetime | None = None,
) -> ReviewUpdate | None:
    reviewed_at = reviewed_at_utc or datetime.now(UTC)
    with connect_review_db(db_path) as connection:
        _ensure_schema(connection)
        choice_payload = _review_choice_signal_payload(
            connection,
            card_id=card_id,
            selected_choice_label=selected_choice_label,
        )
        inserted = _insert_learning_signal(
            connection,
            event_id=make_uuid7(),
            idempotency_key=idempotency_key,
            signal_type="srs_review",
            payload={
                "card_id": card_id,
                "answer": answer,
                "peeked_this_session": peeked_this_session,
                **choice_payload,
            },
            created_at_utc=reviewed_at,
        )
        if not inserted:
            return None
        return _record_card_review(
            connection,
            card_id=card_id,
            answer=answer,
            peeked_this_session=peeked_this_session,
            reviewed_at=reviewed_at,
        )


def _review_choice_signal_payload(
    connection: sqlite3.Connection,
    *,
    card_id: str,
    selected_choice_label: QuizChoiceLabel | None,
) -> dict[str, object]:
    if selected_choice_label is None:
        return {}

    row = connection.execute(
        """
        SELECT answer, answer_mode, choices_json
        FROM cards
        WHERE id = ? AND card_state = 'active'
        """,
        (card_id,),
    ).fetchone()
    if row is None:
        raise InputError(f"active review card does not exist: {card_id}")

    answer_mode, choices = _deserialize_card_choices(
        row["answer_mode"],
        row["choices_json"],
        expected_answer=cast("str | None", row["answer"]),
    )
    if answer_mode != "multiple_choice" or choices is None:
        raise InputError("selected_choice_label is only valid for multiple_choice review cards")

    for choice in choices:
        if choice.label == selected_choice_label:
            return {
                "selected_choice_label": selected_choice_label,
                "choice_correct": choice.is_correct,
            }

    raise InputError(f"selected_choice_label is not valid for review card choices: {card_id}")


def set_card_queue_state(
    db_path: Path,
    *,
    card_id: str,
    state: str,
    changed_at_utc: datetime | None = None,
) -> None:
    if state not in {"archived", "suspended"}:
        raise InputError("card queue state must be archived or suspended")
    timestamp = _datetime_to_utc_text(changed_at_utc or datetime.now(UTC))
    column = "archived_at_utc" if state == "archived" else "suspended_at_utc"
    with connect_review_db(db_path) as connection:
        _ensure_schema(connection)
        # Clear stale_reason whenever the card leaves the stale queue: ReviewCard
        # contract requires stale_reason to be set only when card_state == 'stale'.
        cursor = connection.execute(
            f"UPDATE cards SET card_state = ?, {column} = ?, stale_reason = NULL WHERE id = ?",
            (state, timestamp, card_id),
        )
        if cursor.rowcount == 0:
            raise InputError(f"review card does not exist: {card_id}")


def _record_card_review(
    connection: sqlite3.Connection,
    *,
    card_id: str,
    answer: ReviewAnswer,
    peeked_this_session: bool,
    reviewed_at: datetime,
) -> ReviewUpdate:
    reviewed_at_text = _datetime_to_utc_text(reviewed_at)
    row = connection.execute(
        """
        SELECT
            id,
            fsrs_state,
            desired_retention,
            scheduler_preset_id,
            due_date,
            created_at_utc,
            last_review_utc,
            reps,
            lapses
        FROM cards
        WHERE id = ? AND card_state = 'active'
        """,
        (card_id,),
    ).fetchone()
    if row is None:
        raise InputError(f"active review card does not exist: {card_id}")
    weights = _scheduler_weights_for_card(connection, str(row["scheduler_preset_id"]))
    recent_successes = _recent_success_count(connection, card_id)
    scheduled = review_fsrs_card(
        fsrs_state=str(row["fsrs_state"]),
        answer=answer,
        peeked_this_session=peeked_this_session,
        reviewed_at=reviewed_at,
        desired_retention=float(row["desired_retention"]),
        weights=weights,
        recent_successes=recent_successes,
    )
    elapsed_days, scheduled_days = _review_day_deltas(
        created_at=str(row["created_at_utc"]),
        last_review=cast("str | None", row["last_review_utc"]),
        due_date=str(row["due_date"]),
        reviewed_at=reviewed_at,
    )
    lapses_increment = 1 if answer == "wrong" else 0
    connection.execute(
        """
        UPDATE cards
        SET
            fsrs_state = ?,
            scheduler_version = ?,
            due_date = ?,
            stability = ?,
            difficulty = ?,
            reps = reps + 1,
            lapses = lapses + ?,
            scaffolding_level = ?,
            last_rating = ?,
            last_review_utc = ?
        WHERE id = ?
        """,
        (
            scheduled.fsrs_state,
            scheduler_version(),
            scheduled.due_date,
            scheduled.stability,
            scheduled.difficulty,
            lapses_increment,
            scheduled.scaffolding_level,
            scheduled.rating,
            reviewed_at_text,
            card_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO review_logs (
            card_id,
            rating,
            reviewed_at_utc,
            elapsed_days,
            scheduled_days,
            state
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            card_id,
            scheduled.rating,
            reviewed_at_text,
            elapsed_days,
            scheduled_days,
            scheduled.state_name,
        ),
    )
    connection.execute(
        """
        UPDATE scheduler_presets
        SET total_reviews = total_reviews + 1
        WHERE preset_id = ?
        """,
        (str(row["scheduler_preset_id"]),),
    )
    return ReviewUpdate(
        card_id=card_id,
        rating=scheduled.rating,
        due_date=scheduled.due_date,
        fsrs_state=scheduled.fsrs_state,
        stability=scheduled.stability,
        difficulty=scheduled.difficulty,
        card_state="active",
        scaffolding_level=scheduled.scaffolding_level,
    )


def insert_learning_signal(
    db_path: Path,
    *,
    event_id: str,
    idempotency_key: str,
    signal_type: str,
    payload: dict[str, object],
    created_at_utc: datetime | None = None,
) -> bool:
    with connect_review_db(db_path) as connection:
        _ensure_schema(connection)
        return _insert_learning_signal(
            connection,
            event_id=event_id,
            idempotency_key=idempotency_key,
            signal_type=signal_type,
            payload=payload,
            created_at_utc=created_at_utc,
        )


def _insert_learning_signal(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    idempotency_key: str,
    signal_type: str,
    payload: dict[str, object],
    created_at_utc: datetime | None = None,
) -> bool:
    timestamp = _datetime_to_utc_text(created_at_utc or datetime.now(UTC))
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO learning_signals (
            event_id,
            idempotency_key,
            signal_type,
            payload_json,
            created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            event_id,
            idempotency_key,
            signal_type,
            payload_json,
            timestamp,
        ),
    )
    if cursor.rowcount > 0:
        return True

    existing = connection.execute(
        """
        SELECT signal_type, payload_json
        FROM learning_signals
        WHERE idempotency_key = ?
        """,
        (idempotency_key,),
    ).fetchone()
    if existing is not None:
        if (
            str(existing["signal_type"]) == signal_type
            and str(existing["payload_json"]) == payload_json
        ):
            return False
        raise InputError("idempotency key already used with different learning signal payload")

    raise InputError("learning signal event_id already exists")


def _ensure_schema(connection: sqlite3.Connection) -> None:
    actual = _get_schema_version(connection)
    has_tables = _has_user_tables(connection)
    if actual == 0 and not has_tables:
        _initialize_schema(connection)
        return
    if actual == 0 and has_tables:
        legacy_version = _get_legacy_schema_version(connection)
        if legacy_version is not None:
            if legacy_version < 1:
                raise MigrationError(
                    f"review.sqlite legacy schema version {legacy_version} is not supported"
                )
            if legacy_version > CURRENT_SCHEMA_VERSION:
                raise MigrationError(
                    f"review.sqlite legacy schema version {legacy_version} is newer than supported "
                    f"{CURRENT_SCHEMA_VERSION}; upgrade AhaDiff before opening this database"
                )
        _run_migrations(connection, legacy_version or 1)
        _ensure_cards_query_indexes(connection)
        return
    if actual == CURRENT_SCHEMA_VERSION:
        _ensure_cards_query_indexes(connection)
        return
    if actual > CURRENT_SCHEMA_VERSION:
        raise MigrationError(
            f"review.sqlite schema version {actual} is newer than supported "
            f"{CURRENT_SCHEMA_VERSION}; upgrade AhaDiff before opening this database"
        )
    _run_migrations(connection, actual)
    _ensure_cards_query_indexes(connection)


def _get_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    if row is None:
        return 0
    return int(row[0])


def _get_legacy_schema_version(connection: sqlite3.Connection) -> int | None:
    legacy_table = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_version'
        LIMIT 1
        """
    ).fetchone()
    if legacy_table is None:
        return None
    try:
        row = connection.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    except sqlite3.DatabaseError as exc:
        raise MigrationError("review.sqlite legacy schema_version table is invalid") from exc
    if row is None:
        raise MigrationError("review.sqlite legacy schema_version table is missing version row")
    try:
        return int(row[0])
    except (TypeError, ValueError) as exc:
        raise MigrationError("review.sqlite legacy schema_version value is invalid") from exc


def _set_schema_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(f"PRAGMA user_version={version}")


def _has_user_tables(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def _initialize_schema(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("BEGIN EXCLUSIVE")
        _ensure_scheduler_presets_schema(connection)
        _ensure_cards_schema(connection)
        _ensure_review_logs_schema(connection)
        _ensure_result_events_schema(connection)
        _ensure_learning_signals_schema(connection)
        _ensure_concepts_schema(connection)
        _ensure_review_logs_review_duration(connection)
        _ensure_fts_concepts_schema(connection)
        _ensure_fts_result_events_schema(connection)
        _ensure_fts_cards_schema(connection)
        _ensure_concepts_graphify_node_id(connection)
        _ensure_graph_nodes_schema(connection)
        _ensure_fts_graph_nodes_schema(connection)
        _ensure_commit_ancestry_schema(connection)
        _ensure_default_scheduler_preset(connection, created_at_utc=_utc_now())
        _set_schema_version(connection, CURRENT_SCHEMA_VERSION)
        connection.execute("COMMIT")
    except Exception:
        with suppress(sqlite3.DatabaseError):
            connection.execute("ROLLBACK")
        raise


def _run_migrations(connection: sqlite3.Connection, from_version: int) -> None:
    if from_version < 1:
        raise MigrationError(f"review.sqlite schema version {from_version} is not supported")
    for version in range(from_version, CURRENT_SCHEMA_VERSION):
        migration = _MIGRATIONS.get(version)
        if migration is None:
            raise MigrationError(
                f"review.sqlite migration path is missing for schema version {version}"
            )
        try:
            connection.execute("BEGIN EXCLUSIVE")
            migration(connection)
            _set_schema_version(connection, version + 1)
            connection.execute("COMMIT")
        except Exception:
            with suppress(sqlite3.DatabaseError):
                connection.execute("ROLLBACK")
            raise


def _ensure_scheduler_presets_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduler_presets (
            preset_id TEXT PRIMARY KEY,
            weights TEXT NOT NULL,
            desired_retention REAL NOT NULL DEFAULT 0.9,
            scheduler_version TEXT NOT NULL,
            total_reviews INTEGER NOT NULL DEFAULT 0,
            last_optimized_utc TEXT,
            created_at_utc TEXT NOT NULL
        )
        """
    )


def _ensure_cards_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id TEXT PRIMARY KEY,
            concept TEXT NOT NULL,
            run_id TEXT NOT NULL,
            fsrs_state TEXT NOT NULL,
            card_state TEXT NOT NULL DEFAULT 'active'
                CHECK (card_state IN ('active', 'stale', 'archived', 'suspended')),
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
            source_ref TEXT NOT NULL,
            file_id TEXT NOT NULL,
            display_path TEXT NOT NULL,
            hunk_id TEXT NOT NULL,
            hunk_hash TEXT NOT NULL,
            symbol TEXT,
            change_kind TEXT,
            question TEXT,
            answer TEXT,
            answer_mode TEXT NOT NULL DEFAULT 'open'
                CHECK (answer_mode IN ('open', 'multiple_choice')),
            choices_json TEXT,
            stale_reason TEXT,
            created_at_utc TEXT NOT NULL,
            archived_at_utc TEXT,
            suspended_at_utc TEXT
        )
        """
    )
    _ensure_cards_query_indexes(connection)
    _ensure_cards_contract_triggers(connection)


def _ensure_cards_query_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_cards_due_active
            ON cards (card_state, due_date)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_cards_run
            ON cards (run_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_cards_weak_active_stability
            ON cards (card_state, stability ASC, difficulty DESC)
            WHERE card_state = 'active' AND reps > 0
        """
    )


def _ensure_cards_contract_triggers(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_cards_validate_state_insert
        BEFORE INSERT ON cards
        WHEN NEW.card_state NOT IN ('active', 'stale', 'archived', 'suspended')
        BEGIN
            SELECT RAISE(ABORT, 'invalid cards.card_state');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_cards_validate_state_update
        BEFORE UPDATE ON cards
        WHEN NEW.card_state NOT IN ('active', 'stale', 'archived', 'suspended')
        BEGIN
            SELECT RAISE(ABORT, 'invalid cards.card_state');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_cards_validate_core_fields_insert
        BEFORE INSERT ON cards
        WHEN NEW.source_ref IS NULL
             OR NEW.file_id IS NULL
             OR NEW.display_path IS NULL
             OR NEW.hunk_id IS NULL
             OR NEW.hunk_hash IS NULL
        BEGIN
            SELECT RAISE(ABORT, 'cards core anchor fields must not be NULL');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_cards_validate_core_fields_update
        BEFORE UPDATE ON cards
        WHEN NEW.source_ref IS NULL
             OR NEW.file_id IS NULL
             OR NEW.display_path IS NULL
             OR NEW.hunk_id IS NULL
             OR NEW.hunk_hash IS NULL
        BEGIN
            SELECT RAISE(ABORT, 'cards core anchor fields must not be NULL');
        END
        """
    )


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    _ensure_scheduler_presets_schema(connection)
    _ensure_cards_schema(connection)
    _ensure_cards_column(connection, "stale_reason", "TEXT")
    _ensure_review_logs_schema(connection)
    _ensure_result_events_schema(connection)
    _ensure_learning_signals_schema(connection)
    _ensure_learning_signals_columns(connection)
    _ensure_default_scheduler_preset(connection, created_at_utc=_utc_now())
    connection.execute("DROP TABLE IF EXISTS schema_version")


def _ensure_review_logs_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS review_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL REFERENCES cards(id),
            rating INTEGER NOT NULL,
            reviewed_at_utc TEXT NOT NULL,
            elapsed_days REAL NOT NULL,
            scheduled_days REAL NOT NULL,
            state TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_review_logs_card_reviewed
            ON review_logs (card_id, reviewed_at_utc DESC)
        """
    )


def _ensure_result_events_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS result_events (
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
        CREATE UNIQUE INDEX IF NOT EXISTS ux_result_events_run_type_ts
            ON result_events (run_id, event_type, timestamp)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_result_events_source_ts
            ON result_events (source_ref, timestamp DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_result_events_prompt_eval
            ON result_events (prompt_version, eval_bundle_version)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_result_events_verdict_status
            ON result_events (verdict, status)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_result_events_weakest_dim_ts
            ON result_events (weakest_dim, timestamp DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_result_events_timestamp_id
            ON result_events (timestamp DESC, event_id DESC)
        """
    )


def _ensure_learning_signals_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_signals (
            event_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            signal_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_learning_signals_type_created
            ON learning_signals (signal_type, created_at DESC)
        """
    )


def _ensure_concepts_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS concepts (
            term_key TEXT PRIMARY KEY,
            concept TEXT NOT NULL,
            term TEXT NOT NULL,
            display_name TEXT NOT NULL,
            lang TEXT NOT NULL DEFAULT 'en',
            aliases TEXT NOT NULL DEFAULT '[]',
            source_refs TEXT NOT NULL DEFAULT '[]',
            branch_hint TEXT,
            introduced_by_run TEXT NOT NULL,
            updated_by_runs TEXT NOT NULL DEFAULT '[]',
            related_claims TEXT NOT NULL DEFAULT '[]',
            file_refs TEXT NOT NULL DEFAULT '[]',
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_concepts_run
            ON concepts (introduced_by_run)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_concepts_lang
            ON concepts (lang)
        """
    )


def _ensure_review_logs_review_duration(connection: sqlite3.Connection) -> None:
    _ensure_table_column(connection, "review_logs", "review_duration", "INTEGER")


def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    _ensure_concepts_schema(connection)
    _ensure_review_logs_review_duration(connection)


# ---------------------------------------------------------------------------
# FTS5 full-text search schema
# ---------------------------------------------------------------------------


def _ensure_fts_concepts_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_concepts USING fts5(
            term_key UNINDEXED,
            concept,
            display_name,
            aliases,
            content='concepts',
            content_rowid='rowid'
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_concepts_ai
        AFTER INSERT ON concepts BEGIN
            INSERT INTO fts_concepts(rowid, term_key, concept, display_name, aliases)
            VALUES (NEW.rowid, NEW.term_key, NEW.concept, NEW.display_name, NEW.aliases);
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_concepts_ad
        AFTER DELETE ON concepts BEGIN
            INSERT INTO fts_concepts(fts_concepts, rowid, term_key, concept, display_name, aliases)
            VALUES ('delete', OLD.rowid, OLD.term_key, OLD.concept, OLD.display_name, OLD.aliases);
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_concepts_au
        AFTER UPDATE ON concepts BEGIN
            INSERT INTO fts_concepts(fts_concepts, rowid, term_key, concept, display_name, aliases)
            VALUES ('delete', OLD.rowid, OLD.term_key, OLD.concept, OLD.display_name, OLD.aliases);
            INSERT INTO fts_concepts(rowid, term_key, concept, display_name, aliases)
            VALUES (NEW.rowid, NEW.term_key, NEW.concept, NEW.display_name, NEW.aliases);
        END
        """
    )


def _ensure_fts_result_events_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_result_events USING fts5(
            event_id UNINDEXED,
            source_ref,
            weakest_dim,
            note_json,
            content='result_events',
            content_rowid='rowid'
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_result_events_ai
        AFTER INSERT ON result_events BEGIN
            INSERT INTO fts_result_events(rowid, event_id, source_ref, weakest_dim, note_json)
            VALUES (NEW.rowid, NEW.event_id, NEW.source_ref, NEW.weakest_dim, NEW.note_json);
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_result_events_ad
        AFTER DELETE ON result_events BEGIN
            INSERT INTO fts_result_events(
                fts_result_events, rowid, event_id,
                source_ref, weakest_dim, note_json)
            VALUES (
                'delete', OLD.rowid, OLD.event_id,
                OLD.source_ref, OLD.weakest_dim, OLD.note_json);
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_result_events_au
        AFTER UPDATE ON result_events BEGIN
            INSERT INTO fts_result_events(
                fts_result_events, rowid, event_id,
                source_ref, weakest_dim, note_json)
            VALUES (
                'delete', OLD.rowid, OLD.event_id,
                OLD.source_ref, OLD.weakest_dim, OLD.note_json);
            INSERT INTO fts_result_events(rowid, event_id, source_ref, weakest_dim, note_json)
            VALUES (NEW.rowid, NEW.event_id, NEW.source_ref, NEW.weakest_dim, NEW.note_json);
        END
        """
    )


def _ensure_fts_cards_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_cards USING fts5(
            id UNINDEXED,
            concept,
            display_path,
            symbol,
            content='cards',
            content_rowid='rowid'
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_cards_ai
        AFTER INSERT ON cards BEGIN
            INSERT INTO fts_cards(rowid, id, concept, display_path, symbol)
            VALUES (NEW.rowid, NEW.id, NEW.concept, NEW.display_path, NEW.symbol);
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_cards_ad
        AFTER DELETE ON cards BEGIN
            INSERT INTO fts_cards(fts_cards, rowid, id, concept, display_path, symbol)
            VALUES ('delete', OLD.rowid, OLD.id, OLD.concept, OLD.display_path, OLD.symbol);
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_cards_au
        AFTER UPDATE ON cards BEGIN
            INSERT INTO fts_cards(fts_cards, rowid, id, concept, display_path, symbol)
            VALUES ('delete', OLD.rowid, OLD.id, OLD.concept, OLD.display_path, OLD.symbol);
            INSERT INTO fts_cards(rowid, id, concept, display_path, symbol)
            VALUES (NEW.rowid, NEW.id, NEW.concept, NEW.display_path, NEW.symbol);
        END
        """
    )


_ALLOWED_FTS_TABLES = frozenset(
    {"fts_concepts", "fts_result_events", "fts_cards", "fts_graph_nodes"}
)


def _rebuild_fts_index(connection: sqlite3.Connection, fts_table: str) -> None:
    """Rebuild FTS index from content table. Use during migration."""
    if fts_table not in _ALLOWED_FTS_TABLES:
        raise StorageError(f"unknown FTS table: {fts_table}")
    connection.execute(f"INSERT INTO {fts_table}({fts_table}) VALUES ('rebuild')")


def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    _ensure_fts_concepts_schema(connection)
    _ensure_fts_result_events_schema(connection)
    _ensure_fts_cards_schema(connection)
    # Rebuild FTS indexes from existing data
    _rebuild_fts_index(connection, "fts_concepts")
    _rebuild_fts_index(connection, "fts_result_events")
    _rebuild_fts_index(connection, "fts_cards")


def _migrate_v4_to_v5(connection: sqlite3.Connection) -> None:
    _ensure_concepts_graphify_node_id(connection)


def _ensure_concepts_graphify_node_id(connection: sqlite3.Connection) -> None:
    _ensure_table_column(connection, "concepts", "graphify_node_id", "TEXT")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_concepts_graphify_node
            ON concepts (graphify_node_id)
            WHERE graphify_node_id IS NOT NULL
        """
    )


def _ensure_graph_nodes_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_nodes (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            kind TEXT,
            file_path TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_graph_nodes_kind
            ON graph_nodes (kind) WHERE kind IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_graph_nodes_file_path
            ON graph_nodes (file_path) WHERE file_path IS NOT NULL
        """
    )


def _ensure_fts_graph_nodes_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_graph_nodes USING fts5(
            id UNINDEXED,
            label,
            kind,
            file_path,
            content='graph_nodes',
            content_rowid='rowid'
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_graph_nodes_ai
        AFTER INSERT ON graph_nodes BEGIN
            INSERT INTO fts_graph_nodes(rowid, id, label, kind, file_path)
            VALUES (NEW.rowid, NEW.id, NEW.label, NEW.kind, NEW.file_path);
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_graph_nodes_ad
        AFTER DELETE ON graph_nodes BEGIN
            INSERT INTO fts_graph_nodes(fts_graph_nodes, rowid, id, label, kind, file_path)
            VALUES ('delete', OLD.rowid, OLD.id, OLD.label, OLD.kind, OLD.file_path);
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_fts_graph_nodes_au
        AFTER UPDATE ON graph_nodes BEGIN
            INSERT INTO fts_graph_nodes(fts_graph_nodes, rowid, id, label, kind, file_path)
            VALUES ('delete', OLD.rowid, OLD.id, OLD.label, OLD.kind, OLD.file_path);
            INSERT INTO fts_graph_nodes(rowid, id, label, kind, file_path)
            VALUES (NEW.rowid, NEW.id, NEW.label, NEW.kind, NEW.file_path);
        END
        """
    )


def _migrate_v5_to_v6(connection: sqlite3.Connection) -> None:
    _ensure_graph_nodes_schema(connection)
    _ensure_fts_graph_nodes_schema(connection)


def _ensure_commit_ancestry_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS commit_ancestry (
            head_sha TEXT NOT NULL,
            ancestor_sha TEXT NOT NULL,
            depth INTEGER NOT NULL CHECK(depth >= 0),
            created_at_utc TEXT NOT NULL,
            PRIMARY KEY (head_sha, ancestor_sha)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_commit_ancestry_ancestor
            ON commit_ancestry (ancestor_sha)
        """
    )


def _migrate_v6_to_v7(connection: sqlite3.Connection) -> None:
    _ensure_commit_ancestry_schema(connection)


def _migrate_v7_to_v8(connection: sqlite3.Connection) -> None:
    _ensure_cards_column(connection, "question", "TEXT")
    _ensure_cards_column(connection, "answer", "TEXT")


def _migrate_v8_to_v9(connection: sqlite3.Connection) -> None:
    _ensure_cards_column(
        connection,
        "answer_mode",
        "TEXT NOT NULL DEFAULT 'open' CHECK (answer_mode IN ('open', 'multiple_choice'))",
    )
    _ensure_cards_column(connection, "choices_json", "TEXT")


_MIGRATIONS: dict[int, MigrationStep] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
    3: _migrate_v3_to_v4,
    4: _migrate_v4_to_v5,
    5: _migrate_v5_to_v6,
    6: _migrate_v6_to_v7,
    7: _migrate_v7_to_v8,
    8: _migrate_v8_to_v9,
}


def _ensure_default_scheduler_preset(
    connection: sqlite3.Connection,
    *,
    created_at_utc: str,
) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO scheduler_presets (
            preset_id,
            weights,
            desired_retention,
            scheduler_version,
            total_reviews,
            created_at_utc
        ) VALUES ('default', ?, ?, ?, 0, ?)
        """,
        (
            default_weights_json(),
            DEFAULT_DESIRED_RETENTION,
            scheduler_version(),
            created_at_utc,
        ),
    )


def _schema_version(connection: sqlite3.Connection) -> int:
    return _get_schema_version(connection)


def _result_events_table_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'result_events'"
    ).fetchone()
    return row is not None


_MAX_CARDS_FILE_BYTES = 16 * 1024 * 1024


def _load_review_cards(cards_path: Path) -> tuple[ReviewCard, ...]:
    from ahadiff.core.paths import reject_leaf_symlink_or_reparse

    leaf_stat = reject_leaf_symlink_or_reparse(cards_path, label="cards file")
    file_size = leaf_stat.st_size
    if file_size > _MAX_CARDS_FILE_BYTES:
        raise InputError(f"cards file exceeds 16 MiB limit: {cards_path}")
    cards: list[ReviewCard] = []
    for index, line in enumerate(cards_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            cards.append(ReviewCard.model_validate_json(stripped))
        except ValidationError as exc:
            message = exc.errors(include_context=False, include_input=False)[0]["msg"]
            raise InputError(f"invalid cards JSONL line {index}: {cards_path} ({message})") from exc
    return tuple(cards)


def _serialize_card_choices(card: ReviewCard) -> tuple[AnswerMode, str | None]:
    answer_mode = _coerce_answer_mode(card.answer_mode, error_type=InputError)
    raw_choices = card.choices
    if answer_mode == "open":
        if raw_choices is not None:
            raise InputError("open review cards must not include choices")
        return answer_mode, None
    expected_answer = _coerce_choice_expected_answer(card.answer, error_type=InputError)
    choices = _coerce_quiz_choices(
        raw_choices,
        expected_answer=expected_answer,
        error_type=InputError,
    )
    payload = [choice.model_dump(mode="json") for choice in choices]
    return answer_mode, json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _deserialize_card_choices(
    answer_mode: object,
    choices_json: object,
    *,
    expected_answer: str | None,
) -> tuple[AnswerMode, tuple[QuizChoice, ...] | None]:
    mode = _coerce_answer_mode(answer_mode, error_type=StorageError)
    if mode == "open":
        if choices_json not in (None, ""):
            raise StorageError("open review card unexpectedly stores choices_json")
        return mode, None
    if not isinstance(choices_json, str) or not choices_json.strip():
        raise StorageError("multiple_choice review card is missing choices_json")
    expected_answer_text = _coerce_choice_expected_answer(
        expected_answer,
        error_type=StorageError,
    )
    try:
        payload = safe_json_loads(choices_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise StorageError("review card choices_json is not valid JSON") from exc
    choices = _coerce_quiz_choices(
        payload,
        expected_answer=expected_answer_text,
        error_type=StorageError,
    )
    return mode, choices


def _coerce_answer_mode(
    raw_mode: object,
    *,
    error_type: type[InputError] | type[StorageError],
) -> AnswerMode:
    if isinstance(raw_mode, str) and raw_mode in _VALID_ANSWER_MODES:
        return raw_mode
    raise error_type(f"invalid review card answer_mode: {raw_mode!r}")


def _coerce_choice_expected_answer(
    raw_answer: object,
    *,
    error_type: type[InputError] | type[StorageError],
) -> str:
    if isinstance(raw_answer, str) and raw_answer.strip():
        return raw_answer
    raise error_type("multiple_choice review cards require a non-empty answer")


def _coerce_quiz_choices(
    raw_choices: object,
    *,
    expected_answer: str | None,
    error_type: type[InputError] | type[StorageError],
) -> tuple[QuizChoice, ...]:
    if not isinstance(raw_choices, list | tuple):
        raise error_type("multiple_choice review cards require a choices array")
    choice_items = cast("Iterable[object]", raw_choices)
    try:
        choices = tuple(
            item if isinstance(item, QuizChoice) else QuizChoice.model_validate(item)
            for item in choice_items
        )
        return validate_quiz_choices(choices, expected_answer=expected_answer)
    except (TypeError, ValueError, ValidationError) as exc:
        raise error_type("invalid review card choices") from exc


def _row_to_due_review_card(row: sqlite3.Row) -> DueReviewCard:
    answer = cast("str | None", row["answer"])
    answer_mode, choices = _deserialize_card_choices(
        row["answer_mode"],
        row["choices_json"],
        expected_answer=answer,
    )
    return DueReviewCard(
        card_id=str(row["id"]),
        concept=str(row["concept"]),
        run_id=str(row["run_id"]),
        due_date=str(row["due_date"]),
        scaffolding_level=str(row["scaffolding_level"]),
        display_path=str(row["display_path"]),
        source_ref=cast("str | None", row["source_ref"]),
        symbol=cast("str | None", row["symbol"]),
        question=cast("str | None", row["question"]),
        answer=answer,
        answer_mode=answer_mode,
        choices=choices,
    )


def _ensure_cards_column(connection: sqlite3.Connection, column_name: str, ddl: str) -> None:
    column_names = _table_column_names(connection, "cards")
    if column_name in column_names:
        return
    connection.execute(f"ALTER TABLE cards ADD COLUMN {column_name} {ddl}")


def _ensure_learning_signals_columns(connection: sqlite3.Connection) -> None:
    for column_name in ("event_id", "idempotency_key", "signal_type", "payload_json", "created_at"):
        _ensure_table_column(connection, "learning_signals", column_name, "TEXT")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_learning_signals_event_id
            ON learning_signals (event_id)
            WHERE event_id IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_learning_signals_idempotency_key
            ON learning_signals (idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """
    )


def _ensure_table_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    ddl: str,
) -> None:
    column_names = _table_column_names(connection, table_name)
    if column_name in column_names:
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def _table_column_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _lossy_event_from_tsv_row(row: dict[str, str]) -> ResultEvent:
    note_json = (row.get("note_json") or "").strip() or None
    note_json = _merge_event_note(
        note_json,
        {"lossy_import": True, "event_type": "imported_from_tsv"},
    )
    try:
        overall = float(row["overall"])
    except (KeyError, ValueError) as exc:
        raise InputError("results TSV row has invalid overall score") from exc
    try:
        return ResultEvent(
            event_id=make_uuid7(),
            run_id=row["run_id"],
            event_type="imported_from_tsv",
            timestamp=row["timestamp"],
            source_ref=row["source_ref"],
            base_ref=(row.get("base_ref") or None),
            prompt_version=row["prompt_version"],
            eval_bundle_version="imported_from_tsv",
            rubric_version=(row.get("rubric_version") or None),
            overall=overall,
            verdict=cast("Any", row["verdict"]),
            status=cast("Any", row["status"]),
            weakest_dim=row["weakest_dim"],
            note_json=note_json,
        )
    except KeyError as exc:
        raise InputError(f"results TSV row is missing required column: {exc.args[0]}") from exc


def _sync_result_event(connection: sqlite3.Connection, event: ResultEvent) -> sqlite3.Cursor:
    return connection.execute(
        """
        INSERT OR IGNORE INTO result_events (
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


def _select_result_events_page(
    connection: sqlite3.Connection,
    *,
    limit: int,
    before: tuple[str, str] | None,
    event_ids: tuple[str, ...] | None,
    statuses: tuple[str, ...] | None,
) -> list[sqlite3.Row]:
    filters: list[str] = []
    params: list[object] = []
    if event_ids is not None:
        filters.append(f"event_id IN ({', '.join('?' for _ in event_ids)})")
        params.extend(event_ids)
    if statuses is not None:
        filters.append(f"status IN ({', '.join('?' for _ in statuses)})")
        params.extend(statuses)
    if before is not None:
        before_timestamp, before_event_id = before
        filters.append("(timestamp < ? OR (timestamp = ? AND event_id < ?))")
        params.extend((before_timestamp, before_timestamp, before_event_id))
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(limit)
    return list(
        connection.execute(
            f"""
            SELECT {", ".join(_RESULT_EVENT_COLUMNS)}
            FROM result_events
            {where_clause}
            ORDER BY timestamp DESC, event_id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    )


def _dedupe_filter_values(values: Iterable[str] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    return tuple(sorted({value for value in values if value}))


def _chunks(values: tuple[str, ...], size: int) -> Iterable[tuple[str, ...]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _merge_event_note(note_json: str | None, extra: dict[str, object]) -> str:
    payload: dict[str, object] = {}
    if note_json:
        try:
            parsed = safe_json_loads(note_json)
        except (json.JSONDecodeError, ValueError):
            parsed = {"original_note_json": note_json}
        if isinstance(parsed, dict):
            payload.update(cast("dict[str, object]", parsed))
        else:
            payload["original_note_json"] = note_json
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _scheduler_weights_for_card(
    connection: sqlite3.Connection,
    scheduler_preset_id: str,
) -> tuple[float, ...]:
    row = connection.execute(
        "SELECT weights FROM scheduler_presets WHERE preset_id = ?",
        (scheduler_preset_id,),
    ).fetchone()
    if row is None:
        raise InputError(f"scheduler preset does not exist: {scheduler_preset_id}")
    payload = safe_json_loads(str(row["weights"]))
    if not isinstance(payload, list):
        raise StorageError(f"scheduler preset weights are not a JSON array: {scheduler_preset_id}")
    weights = tuple(_coerce_float(item) for item in cast("Iterable[object]", payload))
    expected_count = len(default_scheduler_parameters())
    if len(weights) != expected_count:
        raise StorageError(
            "scheduler preset weights length mismatch: "
            f"{scheduler_preset_id} expected {expected_count}, got {len(weights)}"
        )
    if not all(math.isfinite(weight) for weight in weights):
        raise StorageError(f"scheduler preset weights must be finite: {scheduler_preset_id}")
    return weights


def _recent_success_count(connection: sqlite3.Connection, card_id: str) -> int:
    rows = connection.execute(
        """
        SELECT rating
        FROM review_logs
        WHERE card_id = ?
        ORDER BY id DESC
        LIMIT 2
        """,
        (card_id,),
    ).fetchall()
    count = 0
    for row in rows:
        if int(row["rating"]) in {2, 3, 4}:
            count += 1
            continue
        break
    return count


def _review_day_deltas(
    *,
    created_at: str,
    last_review: str | None,
    due_date: str,
    reviewed_at: datetime,
) -> tuple[float, float]:
    anchor = _parse_utc_text(last_review or created_at)
    due = _parse_utc_text(due_date)
    elapsed_days = max((reviewed_at - anchor).total_seconds() / 86400.0, 0.0)
    scheduled_days = max((due - anchor).total_seconds() / 86400.0, 0.0)
    return elapsed_days, scheduled_days


def _parse_utc_text(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_now() -> str:
    return _datetime_to_utc_text(datetime.now(UTC))


def _datetime_to_utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _temporary_sibling_path(path: Path, *, suffix: str) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=suffix,
        dir=path.parent,
    )
    os.close(fd)
    temp_path = Path(raw_path)
    temp_path.unlink()
    return temp_path


def _default_backup_path(db_path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return db_path.with_name(f"{db_path.name}.{timestamp}.bak")


def make_uuid7() -> str:
    global _uuid7_last_tail, _uuid7_last_timestamp_ms

    timestamp_ms = int(datetime.now(UTC).timestamp() * 1000) & _UUID7_TIMESTAMP_MASK
    with _UUID7_LOCK:
        if timestamp_ms > _uuid7_last_timestamp_ms:
            _uuid7_last_timestamp_ms = timestamp_ms
            _uuid7_last_tail = uuid.uuid4().int & _UUID7_TAIL_MASK
        else:
            _uuid7_last_tail = (_uuid7_last_tail + 1) & _UUID7_TAIL_MASK
            if _uuid7_last_tail == 0:
                _uuid7_last_timestamp_ms += 1
            timestamp_ms = _uuid7_last_timestamp_ms
        tail = _uuid7_last_tail
    rand_a = tail >> 62
    rand_b = tail & _UUID7_RANDOM_B_MASK
    versioned = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=versioned))


def _remove_sqlite_sidecars_with_retry(
    db_path: Path,
    *,
    attempts: int = _SQLITE_SIDECAR_REMOVE_ATTEMPTS,
    delay_seconds: float = _SQLITE_SIDECAR_REMOVE_DELAY_SECONDS,
) -> None:
    for suffix in _SQLITE_SIDECAR_SUFFIXES:
        sidecar_path = db_path.with_name(f"{db_path.name}{suffix}")
        for attempt in range(attempts):
            try:
                sidecar_path.unlink()
                break
            except FileNotFoundError:
                break
            except OSError as exc:
                if attempt + 1 >= attempts:
                    raise StorageError(
                        f"failed to remove SQLite sidecar {sidecar_path}: {exc}"
                    ) from exc
                time.sleep(delay_seconds)


def _coerce_float(value: object) -> float:
    if isinstance(value, int | float | str):
        return float(value)
    raise StorageError("scheduler preset weights must contain only numbers")


def _assert_sqlite_runtime_supported() -> None:
    version = _sqlite_version_tuple()
    if _sqlite_gate_ok(version):
        return
    minimum = ".".join(str(part) for part in _SQLITE_MIN_VERSION)
    backports = ", ".join(
        ".".join(str(part) for part in item) for item in sorted(_SQLITE_ALLOWED_BACKPORTS)
    )
    raise StorageError(
        f"SQLite runtime {sqlite3.sqlite_version} is below {minimum}; "
        f"allowed backports are {backports}"
    )


def _sqlite_version_tuple() -> tuple[int, int, int]:
    parts = sqlite3.sqlite_version.split(".")
    major, minor, patch = (int(part) for part in parts[:3])
    return major, minor, patch


def _sqlite_gate_ok(version: tuple[int, int, int]) -> bool:
    return version >= _SQLITE_MIN_VERSION or version in _SQLITE_ALLOWED_BACKPORTS


# ---------------------------------------------------------------------------
# Concepts helpers
# ---------------------------------------------------------------------------


def _merge_json_list(existing_json: str, new_values: list[object]) -> str:
    """Merge new values into a JSON array string, deduplicating."""
    try:
        existing_raw = safe_json_loads(existing_json)
    except (json.JSONDecodeError, ValueError):
        existing_raw = []
    existing_list: list[object] = (
        list(cast("list[object]", existing_raw)) if isinstance(existing_raw, list) else []
    )
    merged: list[object] = []
    seen: set[str] = set()
    for item in (*existing_list, *new_values):
        key = str(item).strip()
        if key and key not in seen:
            seen.add(key)
            merged.append(item)
    return json.dumps(merged, ensure_ascii=False)


def _merge_json_array_payloads(existing_json: str | None, incoming_json: str | None) -> str:
    """Merge two JSON array payloads for atomic SQLite UPSERT expressions."""
    try:
        incoming_raw = safe_json_loads(incoming_json or "[]")
    except (json.JSONDecodeError, ValueError):
        incoming_raw = []
    incoming_values = (
        list(cast("list[object]", incoming_raw)) if isinstance(incoming_raw, list) else []
    )
    return _merge_json_list(existing_json or "[]", incoming_values)


def _register_concepts_sql_functions(connection: sqlite3.Connection) -> None:
    connection.create_function("ahadiff_merge_json_arrays", 2, _merge_json_array_payloads)


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Concepts public API
# ---------------------------------------------------------------------------


def upsert_concept(
    db_path: Path,
    *,
    term_key: str,
    concept: str,
    run_id: str,
    source_ref: str,
    branch_hint: str | None,
    related_claims: tuple[str, ...],
    file_refs: tuple[str, ...],
) -> None:
    """Insert or merge a single concept entry."""
    now = _utc_now()
    with connect_review_db(db_path, create_parent=True) as connection:
        _ensure_schema(connection)
        _register_concepts_sql_functions(connection)
        connection.execute(
            """
            INSERT INTO concepts (
                term_key, concept, term, display_name,
                lang, aliases,
                source_refs, branch_hint,
                introduced_by_run, updated_by_runs,
                related_claims, file_refs,
                created_at_utc, updated_at_utc
            ) VALUES (
                ?, ?, ?, ?,
                'en', '[]',
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?
            )
            ON CONFLICT(term_key) DO UPDATE SET
                source_refs = ahadiff_merge_json_arrays(concepts.source_refs, excluded.source_refs),
                updated_by_runs = ahadiff_merge_json_arrays(
                    concepts.updated_by_runs,
                    excluded.updated_by_runs
                ),
                related_claims = ahadiff_merge_json_arrays(
                    concepts.related_claims,
                    excluded.related_claims
                ),
                file_refs = ahadiff_merge_json_arrays(concepts.file_refs, excluded.file_refs),
                branch_hint = COALESCE(concepts.branch_hint, excluded.branch_hint),
                updated_at_utc = excluded.updated_at_utc
            """,
            (
                term_key,
                concept,
                concept,
                concept,
                json.dumps([source_ref], ensure_ascii=False),
                branch_hint,
                run_id,
                json.dumps([run_id], ensure_ascii=False),
                json.dumps(list(related_claims), ensure_ascii=False),
                json.dumps(list(file_refs), ensure_ascii=False),
                now,
                now,
            ),
        )


def upsert_concepts_batch(
    db_path: Path,
    entries: Iterable[dict[str, object]],
) -> int:
    """Batch upsert concept entries. Returns count of rows affected."""
    now = _utc_now()
    count = 0
    with connect_review_db(db_path, create_parent=True) as connection:
        _ensure_schema(connection)
        _register_concepts_sql_functions(connection)
        for entry in entries:
            term_key = str(entry.get("term_key", ""))
            if not term_key:
                continue
            concept = str(entry.get("concept", ""))
            source_refs_raw = entry.get("source_refs", [])
            source_refs_list: list[object] = (
                list(cast("list[object]", source_refs_raw))
                if isinstance(source_refs_raw, list)
                else []
            )
            updated_by_runs_raw = entry.get("updated_by_runs", [])
            updated_by_runs_list: list[object] = (
                list(cast("list[object]", updated_by_runs_raw))
                if isinstance(updated_by_runs_raw, list)
                else []
            )
            related_claims_raw = entry.get("related_claims", [])
            related_claims_list: list[object] = (
                list(cast("list[object]", related_claims_raw))
                if isinstance(related_claims_raw, list)
                else []
            )
            file_refs_raw = entry.get("file_refs", [])
            file_refs_list: list[object] = (
                list(cast("list[object]", file_refs_raw)) if isinstance(file_refs_raw, list) else []
            )
            aliases_raw = entry.get("aliases", [])
            aliases_list: list[object] = (
                list(aliases_raw)  # type: ignore[arg-type]
                if isinstance(aliases_raw, list)
                else []
            )
            graphify_node_id_raw = entry.get("graphify_node_id")
            graphify_node_id = (
                str(graphify_node_id_raw) if graphify_node_id_raw is not None else None
            )
            connection.execute(
                """
                INSERT INTO concepts (
                    term_key, concept, term,
                    display_name, lang, aliases,
                    source_refs, branch_hint,
                    introduced_by_run, updated_by_runs,
                    related_claims, file_refs,
                    graphify_node_id,
                    created_at_utc, updated_at_utc
                ) VALUES (
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?,
                    ?, ?
                )
                ON CONFLICT(term_key) DO UPDATE SET
                    concept = COALESCE(NULLIF(excluded.concept, ''), concepts.concept),
                    term = COALESCE(NULLIF(excluded.term, ''), concepts.term),
                    display_name = COALESCE(
                        NULLIF(excluded.display_name, ''),
                        concepts.display_name
                    ),
                    lang = COALESCE(NULLIF(excluded.lang, ''), concepts.lang),
                    aliases = ahadiff_merge_json_arrays(
                        concepts.aliases, excluded.aliases
                    ),
                    source_refs = ahadiff_merge_json_arrays(
                        concepts.source_refs, excluded.source_refs
                    ),
                    updated_by_runs = ahadiff_merge_json_arrays(
                        concepts.updated_by_runs,
                        excluded.updated_by_runs
                    ),
                    related_claims = ahadiff_merge_json_arrays(
                        concepts.related_claims,
                        excluded.related_claims
                    ),
                    file_refs = ahadiff_merge_json_arrays(concepts.file_refs, excluded.file_refs),
                    introduced_by_run = COALESCE(
                        NULLIF(concepts.introduced_by_run, ''),
                        excluded.introduced_by_run
                    ),
                    branch_hint = COALESCE(concepts.branch_hint, excluded.branch_hint),
                    graphify_node_id = COALESCE(
                        excluded.graphify_node_id, concepts.graphify_node_id
                    ),
                    updated_at_utc = excluded.updated_at_utc
                """,
                (
                    term_key,
                    concept,
                    str(entry.get("term", concept)),
                    str(entry.get("display_name", concept)),
                    str(entry.get("lang", "en")),
                    json.dumps(aliases_list, ensure_ascii=False),
                    json.dumps(source_refs_list, ensure_ascii=False),
                    entry.get("branch_hint"),
                    str(entry.get("introduced_by_run", "")),
                    json.dumps(updated_by_runs_list, ensure_ascii=False),
                    json.dumps(related_claims_list, ensure_ascii=False),
                    json.dumps(file_refs_list, ensure_ascii=False),
                    graphify_node_id,
                    now,
                    now,
                ),
            )
            count += 1
    return count


def load_concepts_from_db(
    db_path: Path,
    *,
    limit: int = 100,
    after_term_key: str | None = None,
) -> tuple[dict[str, object], ...]:
    """Load concepts from SQLite with keyset pagination."""
    if not db_path.exists():
        return ()
    with connect_review_db(db_path) as connection:
        if not _table_exists(connection, "concepts"):
            return ()
        clauses: list[str] = []
        params: list[object] = []
        if after_term_key is not None:
            clauses.append("term_key > ?")
            params.append(after_term_key)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = connection.execute(
            f"""
            SELECT term_key, concept, term, display_name, lang, aliases,
                   source_refs, branch_hint, introduced_by_run, updated_by_runs,
                   related_claims, file_refs, graphify_node_id,
                   created_at_utc, updated_at_utc
            FROM concepts{where}
            ORDER BY term_key ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        entry: dict[str, object] = {}
        for key in (
            "term_key",
            "concept",
            "term",
            "display_name",
            "lang",
            "branch_hint",
            "introduced_by_run",
            "graphify_node_id",
            "created_at_utc",
            "updated_at_utc",
        ):
            entry[key] = row[key]
        for key in ("aliases", "source_refs", "updated_by_runs", "related_claims", "file_refs"):
            raw = row[key]
            try:
                entry[key] = safe_json_loads(str(raw)) if raw else []
            except (json.JSONDecodeError, ValueError):
                entry[key] = []
        result.append(entry)
    return tuple(result)


def count_concepts(db_path: Path) -> int:
    """Count total concepts in the database."""
    if not db_path.exists():
        return 0
    with connect_review_db(db_path) as connection:
        if not _table_exists(connection, "concepts"):
            return 0
        row = connection.execute("SELECT COUNT(*) FROM concepts").fetchone()
        return int(row[0]) if row else 0


_MAX_CONCEPTS_JSONL_BYTES = 16 * 1024 * 1024


def import_concepts_from_jsonl(db_path: Path, jsonl_path: Path) -> int:
    """Import concepts from a JSONL file into SQLite. Returns count imported."""
    if not jsonl_path.exists():
        return 0
    from ahadiff.core.paths import reject_leaf_symlink_or_reparse

    leaf_stat = reject_leaf_symlink_or_reparse(jsonl_path, label="concepts JSONL")
    file_size = leaf_stat.st_size
    if file_size > _MAX_CONCEPTS_JSONL_BYTES:
        raise InputError(f"concepts JSONL exceeds 16 MiB limit: {jsonl_path}")
    entries: list[dict[str, object]] = []
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = safe_json_loads(stripped)
            except (json.JSONDecodeError, ValueError) as exc:
                raise InputError(f"invalid concepts JSONL line {index}: {jsonl_path}") from exc
            if not isinstance(payload, dict):
                raise InputError(f"concepts JSONL line {index} must be an object: {jsonl_path}")
            row = cast("dict[str, object]", payload)
            if not row.get("term_key") or not row.get("concept"):
                raise InputError(
                    f"concepts JSONL line {index} missing term_key or concept: {jsonl_path}"
                )
            entries.append(row)
    if not entries:
        return 0
    return upsert_concepts_batch(db_path, entries)


_MAX_GRAPH_NODES_IMPORT = 10_000


def import_graph_nodes(
    db_path: Path,
    nodes: Sequence[Mapping[str, object]],
) -> int:
    if not nodes:
        return 0
    if len(nodes) > _MAX_GRAPH_NODES_IMPORT:
        raise InputError(f"graph node import exceeds {_MAX_GRAPH_NODES_IMPORT} nodes")
    with connect_review_db(db_path, create_parent=True) as connection:
        _ensure_schema(connection)
        connection.execute("DELETE FROM graph_nodes")
        inserted = 0
        for node in nodes:
            node_id = str(node.get("id", ""))
            label = str(node.get("label", ""))
            if not node_id or not label:
                continue
            metadata = node.get("metadata", {})
            metadata_json = json.dumps(
                metadata if isinstance(metadata, dict) else {},
                ensure_ascii=False,
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO graph_nodes (id, label, kind, file_path, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    node_id,
                    label,
                    node.get("kind"),
                    node.get("file_path"),
                    metadata_json,
                ),
            )
            inserted += 1
    return inserted


def replace_commit_ancestry(
    db_path: Path,
    *,
    head_sha: str,
    ancestors: Sequence[str],
) -> int:
    if not head_sha:
        return 0
    now = _utc_now()
    with connect_review_db(db_path, create_parent=True) as connection:
        _ensure_schema(connection)
        connection.execute("DELETE FROM commit_ancestry WHERE head_sha = ?", (head_sha,))
        inserted = 0
        for depth, ancestor_sha in enumerate(ancestors):
            if not ancestor_sha:
                continue
            connection.execute(
                """
                INSERT OR REPLACE INTO commit_ancestry (
                    head_sha, ancestor_sha, depth, created_at_utc
                ) VALUES (?, ?, ?, ?)
                """,
                (head_sha, ancestor_sha, depth, now),
            )
            inserted += 1
    return inserted


def load_commit_ancestry(db_path: Path, *, head_sha: str) -> tuple[str, ...]:
    if not head_sha or not db_path.exists():
        return ()
    with connect_review_db(db_path) as connection:
        if not _table_exists(connection, "commit_ancestry"):
            return ()
        rows = connection.execute(
            """
            SELECT ancestor_sha
            FROM commit_ancestry
            WHERE head_sha = ?
            ORDER BY depth ASC
            """,
            (head_sha,),
        ).fetchall()
    return tuple(str(row["ancestor_sha"]) for row in rows)


def count_commit_ancestry(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    with connect_review_db(db_path) as connection:
        if not _table_exists(connection, "commit_ancestry"):
            return 0
        row = connection.execute("SELECT COUNT(*) FROM commit_ancestry").fetchone()
        return int(row[0]) if row else 0


def count_graph_nodes(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    with connect_review_db(db_path) as connection:
        if not _table_exists(connection, "graph_nodes"):
            return 0
        row = connection.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()
        return int(row[0]) if row else 0


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "LossyImportOutcome",
    "UpgradeOutcome",
    "backup_review_db",
    "check_review_db",
    "checkpoint_review_db",
    "connect_review_db",
    "count_commit_ancestry",
    "count_concepts",
    "count_graph_nodes",
    "delete_result_event",
    "delete_result_event_and_select_tsv_rows",
    "finalize_targeted_verify_event",
    "get_card",
    "import_cards_from_jsonl",
    "import_cards_from_runs",
    "import_concepts_from_jsonl",
    "import_graph_nodes",
    "import_results_tsv_lossy",
    "initialize_review_db",
    "insert_learning_signal",
    "list_due_cards",
    "load_commit_ancestry",
    "load_concepts_from_db",
    "load_finalized_ratchet_history_page",
    "load_result_event_by_run_and_id",
    "load_result_events_for_improve_chain",
    "load_result_events_from_db",
    "load_result_events_page",
    "make_uuid7",
    "mark_run_cards_stale",
    "record_card_review",
    "record_card_review_once",
    "replace_commit_ancestry",
    "resolve_sqlite_journal_mode",
    "restore_review_db",
    "select_result_tsv_rows",
    "set_card_queue_state",
    "sync_result_event",
    "upgrade_review_db",
    "upsert_concept",
    "upsert_concepts_batch",
]
