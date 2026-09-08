"""Read-only, self-reported practice metrics from persisted bounded signals."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast

from ahadiff.contracts.serve_stats import (
    ActivePracticeSummary,
    PracticeAttemptSummary,
    PracticeErrorCounts,
)
from ahadiff.core.errors import StorageError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.sqlite_util import safe_sqlite_connect

if TYPE_CHECKING:
    from pathlib import Path

AttemptKind = Literal["initial", "delayed_recall", "unseen_variant"]
ErrorKind = Literal["none", "recall", "application", "reasoning", "boundary"]
_DELAYED_RECALL_SECONDS = 86_400
_MAX_SIGNAL_ROWS = 100_000
_MAX_SIGNAL_BYTES = 8192


@dataclass(frozen=True)
class _Attempt:
    identity: tuple[str, str]
    kind: AttemptKind
    error: ErrorKind
    independent: bool
    created_at: datetime
    elapsed_seconds: int | None
    new_variant: bool


def _attempt(raw: object, created_at: object, *, now: datetime) -> _Attempt | None:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_SIGNAL_BYTES:
        return None
    try:
        parsed = safe_json_loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    payload = cast("dict[str, object]", parsed)
    run_id, quiz_id = payload.get("run_id"), payload.get("quiz_id")
    kind, error, assessment = (
        payload.get("attempt_kind"),
        payload.get("error_type"),
        payload.get("self_assessment"),
    )
    if (
        not isinstance(run_id, str)
        or not run_id
        or len(run_id) > 64
        or not isinstance(quiz_id, str)
        or not quiz_id
        or len(quiz_id) > 200
        or payload.get("exercise_kind") not in ("prediction", "completion", "error_reason")
        or payload.get("feedback_kind") != "semantic_self_assessment"
        or "correct" not in payload
        or payload["correct"] is not None
        or "choice" in payload
        or payload.get("scenario_kind") not in (None, "new_variant")
        or kind not in ("initial", "delayed_recall", "unseen_variant")
        or error not in ("none", "recall", "application", "reasoning", "boundary")
        or assessment not in ("independent", "assisted", "not_yet")
        or ((assessment == "independent") != (error == "none"))
        or not isinstance(created_at, str)
    ):
        return None
    try:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp > now:
            return None
        timestamp = timestamp.astimezone(UTC)
    except (ValueError, OverflowError):
        return None
    raw_elapsed = payload.get("elapsed_seconds")
    if raw_elapsed is not None and (type(raw_elapsed) is not int or raw_elapsed < 0):
        return None
    return _Attempt(
        identity=(run_id, quiz_id),
        kind=kind,
        error=error,
        independent=assessment == "independent",
        created_at=timestamp,
        elapsed_seconds=raw_elapsed,
        new_variant=payload.get("scenario_kind") == "new_variant",
    )


def aggregate_active_practice(db_path: Path) -> ActivePracticeSummary:
    """Never initialize/migrate the DB; absent old signal tables mean unmeasured."""
    if not db_path.is_file():
        return ActivePracticeSummary()
    try:
        with closing(
            safe_sqlite_connect(db_path, read_only=True, row_factory=sqlite3.Row, defensive=True)
        ) as conn:
            rows = conn.execute(
                """SELECT CASE WHEN length(CAST(payload_json AS BLOB)) <= ?
                         THEN payload_json ELSE NULL END AS payload_json, created_at
                   FROM learning_signals
                   WHERE signal_type = 'quiz_answer'
                   ORDER BY created_at ASC, event_id ASC LIMIT ?""",
                (_MAX_SIGNAL_BYTES, _MAX_SIGNAL_ROWS + 1),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc) or "no such column" in str(exc):
            return ActivePracticeSummary()
        raise StorageError("practice statistics are unavailable") from exc
    except (sqlite3.DatabaseError, OSError) as exc:
        raise StorageError("practice statistics are unavailable") from exc
    if len(rows) > _MAX_SIGNAL_ROWS:
        raise StorageError("practice signal count exceeds the supported statistics limit")
    now = datetime.now(UTC)
    totals: dict[AttemptKind, int] = {"initial": 0, "delayed_recall": 0, "unseen_variant": 0}
    independent: dict[AttemptKind, int] = dict.fromkeys(totals, 0)
    errors: dict[ErrorKind, int] = {
        "none": 0,
        "recall": 0,
        "application": 0,
        "reasoning": 0,
        "boundary": 0,
    }
    previous: dict[tuple[str, str], datetime] = {}
    valid_attempts = [
        attempt
        for row in rows
        if (attempt := _attempt(row["payload_json"], row["created_at"], now=now)) is not None
    ]
    for attempt in sorted(valid_attempts, key=lambda item: item.created_at):
        earlier = previous.get(attempt.identity)
        previous[attempt.identity] = attempt.created_at
        if earlier is None:
            # Only a recorded first attempt may enter either initial denominator.
            if attempt.kind == "delayed_recall":
                continue
            if attempt.kind == "unseen_variant" and not attempt.new_variant:
                continue
        else:
            elapsed = int((attempt.created_at - earlier).total_seconds())
            if (
                attempt.kind != "delayed_recall"
                or elapsed < _DELAYED_RECALL_SECONDS
                or attempt.elapsed_seconds is None
                or attempt.elapsed_seconds < _DELAYED_RECALL_SECONDS
                or abs(attempt.elapsed_seconds - elapsed) > 5
            ):
                continue
        totals[attempt.kind] += 1
        independent[attempt.kind] += int(attempt.independent)
        errors[attempt.error] += 1

    def bucket(kind: AttemptKind) -> PracticeAttemptSummary:
        count = totals[kind]
        return PracticeAttemptSummary(
            attempts=count, independent_rate=round(independent[kind] / count, 4) if count else None
        )

    return ActivePracticeSummary(
        initial=bucket("initial"),
        delayed_recall=bucket("delayed_recall"),
        unseen_variant=bucket("unseen_variant"),
        error_types=PracticeErrorCounts(**errors),
    )


__all__ = ["aggregate_active_practice"]
