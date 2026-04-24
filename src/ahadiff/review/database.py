from __future__ import annotations

import csv
import json
import os
import sqlite3
import tempfile
import threading
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from ahadiff.contracts import ResultEvent, ReviewCard
from ahadiff.core.errors import InputError, MigrationError, StorageError

from .scheduler import (
    DEFAULT_DESIRED_RETENTION,
    default_weights_json,
    normalize_fsrs_state,
    review_fsrs_card,
    scheduler_version,
    snapshot_card_state,
)
from .schemas import DueReviewCard, ReviewAnswer, ReviewDbCheck, ReviewUpdate

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

CURRENT_SCHEMA_VERSION = 2
_SQLITE_MIN_VERSION = (3, 51, 3)
_SQLITE_ALLOWED_BACKPORTS = {(3, 50, 7), (3, 44, 6)}
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


@dataclass(frozen=True)
class UpgradeOutcome:
    db_path: Path
    backup_path: Path
    schema_version: int


@dataclass(frozen=True)
class LossyImportOutcome:
    imported: int
    skipped: int


def connect_review_db(db_path: Path, *, create_parent: bool = False) -> sqlite3.Connection:
    _assert_sqlite_runtime_supported()
    if create_parent:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    elif not db_path.parent.exists():
        raise InputError(f"review DB parent directory does not exist: {db_path.parent}")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA foreign_keys=ON")
        defensive_flag = getattr(sqlite3, "SQLITE_DBCONFIG_DEFENSIVE", None)
        setconfig = getattr(connection, "setconfig", None)
        if defensive_flag is not None and callable(setconfig):
            cast("Any", setconfig)(defensive_flag, True)
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or quick_check[0] != "ok":
            value = "unknown" if quick_check is None else str(quick_check[0])
            raise StorageError(f"SQLite quick_check failed for {db_path}: {value}")
        return connection
    except Exception:
        connection.close()
        raise


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
        connection.execute("BEGIN EXCLUSIVE")
        _ensure_schema(connection)
        if migration_hook is not None:
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
    if not db_path.exists():
        raise InputError(f"review.sqlite does not exist: {db_path}")
    target = backup_path or _default_backup_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as source, sqlite3.connect(target) as backup:
        source.backup(backup)
    return target


def restore_review_db(*, db_path: Path, backup_path: Path) -> None:
    if not backup_path.exists():
        raise InputError(f"review DB backup does not exist: {backup_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling_path(db_path, suffix=".restore.tmp")
    try:
        with sqlite3.connect(backup_path) as source, sqlite3.connect(temp_path) as target:
            source.backup(target)
        temp_path.replace(db_path)
        _remove_sqlite_sidecars(db_path)
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
    now = _utc_now()
    inserted = 0
    with connect_review_db(db_path) as connection:
        _ensure_schema(connection)
        _ensure_default_scheduler_preset(connection, created_at_utc=now)
        run_ids = tuple(sorted({card.run_id for card in cards}))
        card_ids = {card.card_id for card in cards}
        for card in cards:
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
                    stale_reason,
                    created_at_utc,
                    archived_at_utc,
                    suspended_at_utc
                ) VALUES (?, ?, ?, ?, ?, 'default', ?, ?, ?, ?, ?, 0, 0, ?, ?, NULL,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
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
        _ensure_schema(connection)
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
                symbol
            FROM cards
            WHERE card_state = 'active' AND due_date <= ?
            ORDER BY due_date ASC, id ASC
            LIMIT ?
            """,
            (now_text, limit),
        ).fetchall()
    return tuple(
        DueReviewCard(
            card_id=str(row["id"]),
            concept=str(row["concept"]),
            run_id=str(row["run_id"]),
            due_date=str(row["due_date"]),
            scaffolding_level=str(row["scaffolding_level"]),
            display_path=str(row["display_path"]),
            source_ref=cast("str | None", row["source_ref"]),
            symbol=cast("str | None", row["symbol"]),
        )
        for row in rows
    )


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
    reviewed_at_utc: datetime | None = None,
) -> ReviewUpdate | None:
    reviewed_at = reviewed_at_utc or datetime.now(UTC)
    with connect_review_db(db_path) as connection:
        _ensure_schema(connection)
        inserted = _insert_learning_signal(
            connection,
            event_id=make_uuid7(),
            idempotency_key=idempotency_key,
            signal_type="srs_review",
            payload={"card_id": card_id, "answer": answer},
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
        cursor = connection.execute(
            f"UPDATE cards SET card_state = ?, {column} = ? WHERE id = ?",
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
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            timestamp,
        ),
    )
    return cursor.rowcount > 0


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL
        )
        """
    )
    _ensure_scheduler_presets_schema(connection)
    _ensure_cards_schema(connection)
    _ensure_review_logs_schema(connection)
    _ensure_result_events_schema(connection)
    _ensure_learning_signals_schema(connection)
    _ensure_default_scheduler_preset(connection, created_at_utc=_utc_now())
    row = connection.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO schema_version (id, version) VALUES (1, ?)",
            (CURRENT_SCHEMA_VERSION,),
        )
        return
    actual = int(row["version"])
    if actual > CURRENT_SCHEMA_VERSION:
        raise MigrationError(
            f"review.sqlite schema_version {actual} is newer than supported "
            f"{CURRENT_SCHEMA_VERSION}"
        )
    if actual < CURRENT_SCHEMA_VERSION:
        _migrate_schema(connection, from_version=actual)
        connection.execute(
            "UPDATE schema_version SET version = ? WHERE id = 1",
            (CURRENT_SCHEMA_VERSION,),
        )


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
            stale_reason TEXT,
            created_at_utc TEXT NOT NULL,
            archived_at_utc TEXT,
            suspended_at_utc TEXT
        )
        """
    )
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
    _ensure_cards_contract_triggers(connection)


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


def _migrate_schema(connection: sqlite3.Connection, *, from_version: int) -> None:
    if from_version < 2:
        _ensure_cards_column(connection, "stale_reason", "TEXT")


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
    row = connection.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    if row is None:
        raise MigrationError("schema_version row is missing")
    return int(row["version"])


def _result_events_table_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'result_events'"
    ).fetchone()
    return row is not None


def _load_review_cards(cards_path: Path) -> tuple[ReviewCard, ...]:
    cards: list[ReviewCard] = []
    for index, line in enumerate(cards_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise InputError(f"invalid cards JSONL line {index}: {cards_path}") from exc
        try:
            cards.append(ReviewCard.model_validate(payload))
        except ValidationError as exc:
            raise InputError(f"invalid cards JSONL line {index}: {cards_path}") from exc
    return tuple(cards)


def _ensure_cards_column(connection: sqlite3.Connection, column_name: str, ddl: str) -> None:
    column_names = {
        str(row["name"]) for row in connection.execute("PRAGMA table_info(cards)").fetchall()
    }
    if column_name in column_names:
        return
    connection.execute(f"ALTER TABLE cards ADD COLUMN {column_name} {ddl}")


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


def _merge_event_note(note_json: str | None, extra: dict[str, object]) -> str:
    payload: dict[str, object] = {}
    if note_json:
        try:
            parsed = json.loads(note_json)
        except json.JSONDecodeError:
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
    payload = json.loads(str(row["weights"]))
    if not isinstance(payload, list):
        raise StorageError(f"scheduler preset weights are not a JSON array: {scheduler_preset_id}")
    return tuple(_coerce_float(item) for item in cast("Iterable[object]", payload))


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


def _remove_sqlite_sidecars(db_path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        db_path.with_name(f"{db_path.name}{suffix}").unlink(missing_ok=True)


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


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "LossyImportOutcome",
    "UpgradeOutcome",
    "backup_review_db",
    "check_review_db",
    "connect_review_db",
    "delete_result_event",
    "delete_result_event_and_select_tsv_rows",
    "finalize_targeted_verify_event",
    "import_cards_from_jsonl",
    "import_cards_from_runs",
    "import_results_tsv_lossy",
    "initialize_review_db",
    "insert_learning_signal",
    "list_due_cards",
    "load_result_event_by_run_and_id",
    "load_result_events_from_db",
    "make_uuid7",
    "mark_run_cards_stale",
    "record_card_review",
    "record_card_review_once",
    "restore_review_db",
    "select_result_tsv_rows",
    "set_card_queue_state",
    "sync_result_event",
    "upgrade_review_db",
]
