from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module, util
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import fsrs

from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.json_util import safe_json_loads

from .scheduler import default_scheduler_parameters, scheduler_version

if TYPE_CHECKING:
    import sqlite3
    from types import ModuleType

_OPTIMIZER_INSTALL_HINT = (
    "FSRS optimizer requires optional dependencies; install with pip install 'ahadiff[optimizer]'"
)
_DATABASE_MODULE_NAME = "ahadiff.review.database"
_FSRS_OPTIMIZER_MAX_SEQ_LEN = 64


@dataclass(frozen=True)
class OptimizeResult:
    weights: list[float]
    review_count: int
    effective_review_count: int
    stage: str
    message: str


def adapt_review_logs(connection: sqlite3.Connection) -> list[fsrs.ReviewLog]:
    rows = connection.execute(
        """
        SELECT card_id, rating, reviewed_at_utc
        FROM review_logs
        ORDER BY reviewed_at_utc ASC, id ASC
        """
    ).fetchall()
    card_id_map = {
        card_id: index + 1
        for index, card_id in enumerate(sorted({str(row["card_id"]) for row in rows}))
    }
    review_logs: list[fsrs.ReviewLog] = []
    for row in rows:
        card_id = str(row["card_id"])
        rating_value = int(row["rating"])
        reviewed_at_raw = str(row["reviewed_at_utc"])
        try:
            rating = fsrs.Rating(rating_value)
        except ValueError as exc:
            raise InputError(
                f"invalid review_logs.rating for card {card_id}: {rating_value}"
            ) from exc
        try:
            review_datetime = _parse_reviewed_at_utc(reviewed_at_raw)
        except ValueError as exc:
            raise InputError(
                f"invalid review_logs.reviewed_at_utc for card {card_id}: {reviewed_at_raw}"
            ) from exc
        review_logs.append(
            fsrs.ReviewLog(
                card_id=card_id_map[card_id],
                rating=rating,
                review_datetime=review_datetime,
                review_duration=None,
            )
        )
    return review_logs


def optimize_weights(db_path: Path, *, min_reviews: int = 512) -> OptimizeResult:
    if min_reviews < 1:
        raise InputError("min_reviews must be >= 1")
    database_module = _load_review_database_module()
    connect_review_db = database_module.connect_review_db
    with connect_review_db(db_path) as connection:
        review_logs = adapt_review_logs(connection)
        review_count = len(review_logs)
        effective_review_count = _count_effective_optimizer_reviews(review_logs)
        current_weights = _load_current_weights(connection)
        if effective_review_count < min_reviews:
            return OptimizeResult(
                weights=current_weights,
                review_count=review_count,
                effective_review_count=effective_review_count,
                stage="cold",
                message=(
                    f"Cold-start mode: {effective_review_count} effective reviews "
                    f"({review_count} raw logs) available; requires at least "
                    f"{min_reviews} effective reviews before optimization."
                ),
            )

        stage = "hot" if effective_review_count > 2000 else "warm"
        optimized_weights = _compute_optimized_weights(review_logs, verbose=stage == "hot")
        _write_optimized_weights(connection, optimized_weights, scheduler_version())
        message = (
            f"Hot optimization applied from {effective_review_count} effective reviews "
            f"({review_count} raw logs) with verbose tracing and higher confidence."
            if stage == "hot"
            else (
                f"Warm optimization applied from {effective_review_count} effective reviews "
                f"({review_count} raw logs)."
            )
        )
        return OptimizeResult(
            weights=optimized_weights,
            review_count=review_count,
            effective_review_count=effective_review_count,
            stage=stage,
            message=message,
        )


def _write_optimized_weights(
    connection: sqlite3.Connection,
    weights: list[float],
    scheduler_version: str,
) -> None:
    if not scheduler_version:
        raise InputError("scheduler_version must not be empty")
    validated_weights = _validate_optimizer_weights(weights)
    payload = json.dumps(validated_weights, allow_nan=False, separators=(",", ":"))
    cursor = connection.execute(
        """
        UPDATE scheduler_presets
        SET weights = ?, last_optimized_utc = ?
        WHERE preset_id = 'default'
        """,
        (payload, _utc_now_text()),
    )
    if cursor.rowcount == 0:
        raise StorageError("default scheduler preset does not exist")


def _count_effective_optimizer_reviews(review_logs: list[fsrs.ReviewLog]) -> int:
    histories: dict[int, list[datetime]] = {}
    for review_log in review_logs:
        histories.setdefault(review_log.card_id, []).append(review_log.review_datetime)

    effective_count = 0
    for reviewed_at_values in histories.values():
        previous_reviewed_at: datetime | None = None
        for reviewed_at in sorted(reviewed_at_values)[:_FSRS_OPTIMIZER_MAX_SEQ_LEN]:
            if previous_reviewed_at is not None and (reviewed_at - previous_reviewed_at).days > 0:
                effective_count += 1
            previous_reviewed_at = reviewed_at
    return effective_count


def _compute_optimized_weights(
    review_logs: list[fsrs.ReviewLog],
    *,
    verbose: bool,
) -> list[float]:
    optimizer_class = _load_optimizer_class()
    try:
        optimizer = optimizer_class(review_logs)
        raw_weights = optimizer.compute_optimal_parameters(verbose=verbose)
    except ImportError as exc:
        raise InputError(_OPTIMIZER_INSTALL_HINT) from exc
    return [_coerce_float(item) for item in cast("list[object]", raw_weights)]


def _load_optimizer_class() -> type[Any]:
    try:
        return _resolve_optimizer_class()
    except ImportError as exc:
        raise InputError(_OPTIMIZER_INSTALL_HINT) from exc


def _resolve_optimizer_class() -> type[Any]:
    return cast("type[Any]", fsrs.Optimizer)


def _load_current_weights(connection: sqlite3.Connection) -> list[float]:
    row = connection.execute(
        """
        SELECT weights
        FROM scheduler_presets
        WHERE preset_id = 'default'
        """
    ).fetchone()
    if row is None:
        return list(default_scheduler_parameters())
    payload = safe_json_loads(str(row["weights"]))
    if not isinstance(payload, list):
        raise StorageError("default scheduler preset weights are not a JSON array")
    return [_coerce_float(item) for item in cast("list[object]", payload)]


def _load_review_database_module() -> ModuleType:
    try:
        return import_module(_DATABASE_MODULE_NAME)
    except NameError as exc:
        if "_migrate_v2_to_v3" not in str(exc):
            raise
        return _load_review_database_module_with_forward_ref()


def _load_review_database_module_with_forward_ref() -> ModuleType:
    existing = sys.modules.get(_DATABASE_MODULE_NAME)
    if existing is not None:
        return existing
    module_path = Path(__file__).with_name("database.py")
    spec = util.spec_from_file_location(_DATABASE_MODULE_NAME, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load review database module from {module_path}")
    module = util.module_from_spec(spec)

    class _DeferredMigration:
        def __call__(self, connection: sqlite3.Connection) -> None:
            target = module.__dict__.get("_migrate_v2_to_v3")
            if target is None or target is self:
                raise NameError("_migrate_v2_to_v3")
            target(connection)

    # review.database currently references the v2->v3 migration before the function
    # definition appears; preload a callable proxy so the module can finish importing.
    module.__dict__["_migrate_v2_to_v3"] = _DeferredMigration()
    sys.modules[_DATABASE_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(_DATABASE_MODULE_NAME, None)
        raise
    return module


def _parse_reviewed_at_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _coerce_float(value: object) -> float:
    if isinstance(value, int | float | str):
        return float(value)
    raise InputError("FSRS optimizer weights must be numeric")


def _validate_optimizer_weights(weights: list[float]) -> list[float]:
    expected_count = len(default_scheduler_parameters())
    if len(weights) != expected_count:
        raise InputError(
            f"FSRS optimizer weights length mismatch: expected {expected_count}, got {len(weights)}"
        )
    validated = [_coerce_float(weight) for weight in weights]
    if not all(math.isfinite(weight) for weight in validated):
        raise InputError("FSRS optimizer weights must be finite")
    return validated


__all__ = ["OptimizeResult", "adapt_review_logs", "optimize_weights"]
