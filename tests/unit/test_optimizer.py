from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol, cast

import fsrs
import pytest

from ahadiff.core.errors import InputError
from ahadiff.review import optimizer as optimizer_module
from ahadiff.review.optimizer import adapt_review_logs, optimize_weights
from ahadiff.review.scheduler import default_scheduler_parameters

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path


class _ReviewDatabaseModule(Protocol):
    def initialize_review_db(self, db_path: Path) -> None: ...

    def connect_review_db(self, db_path: Path) -> sqlite3.Connection: ...


def _review_database_module() -> _ReviewDatabaseModule:
    return cast(
        "_ReviewDatabaseModule",
        optimizer_module._load_review_database_module(),  # pyright: ignore[reportPrivateUsage]
    )


def _optimizer_weights(value: float) -> list[float]:
    return [value] * len(default_scheduler_parameters())


def _insert_review_log_rows(
    db_path: Path,
    *,
    card_id: str,
    count: int,
    start_at: datetime | None = None,
    rating: int = 3,
    step: timedelta = timedelta(days=1),
) -> None:
    base = start_at or datetime(2026, 4, 28, tzinfo=UTC)
    review_database = _review_database_module()
    with review_database.connect_review_db(db_path) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO cards (
                id,
                concept,
                run_id,
                fsrs_state,
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card_id,
                "optimizer test",
                "run-optimizer",
                "{}",
                "fsrs-test",
                base.isoformat().replace("+00:00", "Z"),
                1.0,
                1.0,
                "abc1234",
                "file-1",
                "src/app.py",
                "hunk-1",
                "deadbeef",
                base.isoformat().replace("+00:00", "Z"),
            ),
        )
        for index in range(count):
            reviewed_at = base + (step * index)
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
                    rating,
                    reviewed_at.isoformat().replace("+00:00", "Z"),
                    float(index),
                    float(index + 1),
                    "Review",
                ),
            )


def test_adapt_review_logs_maps_database_rows_to_fsrs_review_logs(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    review_database = _review_database_module()
    review_database.initialize_review_db(db_path)
    _insert_review_log_rows(
        db_path,
        card_id="card-alpha",
        count=2,
        start_at=datetime(2026, 4, 28, 9, 30, tzinfo=UTC),
    )

    with review_database.connect_review_db(db_path) as connection:
        logs = adapt_review_logs(connection)

    assert len(logs) == 2
    assert logs[0].card_id == 1
    assert logs[0].rating is fsrs.Rating.Good
    assert logs[0].review_datetime == datetime(2026, 4, 28, 9, 30, tzinfo=UTC)
    assert logs[0].review_duration is None
    assert logs[1].review_datetime == datetime(2026, 4, 29, 9, 30, tzinfo=UTC)


def test_adapt_review_logs_uses_stable_sorted_card_id_mapping(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    review_database = _review_database_module()
    review_database.initialize_review_db(db_path)
    _insert_review_log_rows(
        db_path,
        card_id="card-zulu",
        count=1,
        start_at=datetime(2026, 4, 28, 9, 30, tzinfo=UTC),
    )
    _insert_review_log_rows(
        db_path,
        card_id="card-alpha",
        count=1,
        start_at=datetime(2026, 4, 28, 10, 30, tzinfo=UTC),
    )

    with review_database.connect_review_db(db_path) as connection:
        logs = adapt_review_logs(connection)

    assert [log.card_id for log in logs] == [2, 1]


def test_optimize_weights_returns_current_default_weights_in_cold_stage(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    review_database = _review_database_module()
    review_database.initialize_review_db(db_path)
    _insert_review_log_rows(db_path, card_id="card-cold", count=3)
    with review_database.connect_review_db(db_path) as connection:
        connection.execute(
            """
            UPDATE scheduler_presets
            SET weights = ?
            WHERE preset_id = 'default'
            """,
            (json.dumps([0.25, 0.5, 0.75]),),
        )

    result = optimize_weights(db_path, min_reviews=512)

    assert result.stage == "cold"
    assert result.review_count == 3
    assert result.effective_review_count == 2
    assert result.weights == [0.25, 0.5, 0.75]
    assert "512" in result.message


def test_optimize_weights_stays_cold_when_raw_logs_meet_threshold_but_effective_samples_do_not(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review.sqlite"
    review_database = _review_database_module()
    review_database.initialize_review_db(db_path)
    _insert_review_log_rows(
        db_path,
        card_id="card-same-day",
        count=3,
        step=timedelta(hours=1),
    )

    result = optimize_weights(db_path, min_reviews=2)

    assert result.stage == "cold"
    assert result.review_count == 3
    assert result.effective_review_count == 0
    assert "0 effective reviews" in result.message


def test_optimize_weights_wraps_missing_optimizer_extras_as_input_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    _review_database_module().initialize_review_db(db_path)
    _insert_review_log_rows(db_path, card_id="card-import", count=3)

    def fail_optimizer_import() -> type[object]:
        raise ImportError("torch is not installed")

    monkeypatch.setattr(optimizer_module, "_resolve_optimizer_class", fail_optimizer_import)

    with pytest.raises(
        InputError,
        match=(
            r"FSRS optimizer requires optional dependencies; install with "
            r"pip install 'ahadiff\[optimizer\]'"
        ),
    ):
        optimize_weights(db_path, min_reviews=2)


def test_optimize_weights_writes_optimized_weights_in_warm_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    review_database = _review_database_module()
    review_database.initialize_review_db(db_path)
    _insert_review_log_rows(db_path, card_id="card-warm", count=3)
    seen: dict[str, object] = {}

    class FakeOptimizer:
        def __init__(self, review_logs: list[fsrs.ReviewLog]) -> None:
            seen["review_logs"] = review_logs

        def compute_optimal_parameters(self, verbose: bool = False) -> list[float]:
            seen["verbose"] = verbose
            return _optimizer_weights(0.11)

    monkeypatch.setattr(optimizer_module, "_load_optimizer_class", lambda: FakeOptimizer)

    result = optimize_weights(db_path, min_reviews=2)

    assert result.stage == "warm"
    assert result.review_count == 3
    assert result.effective_review_count == 2
    assert result.weights == _optimizer_weights(0.11)
    assert seen["verbose"] is False
    assert len(cast("list[fsrs.ReviewLog]", seen["review_logs"])) == 3
    with review_database.connect_review_db(db_path) as connection:
        row = connection.execute(
            """
            SELECT weights, last_optimized_utc
            FROM scheduler_presets
            WHERE preset_id = 'default'
            """
        ).fetchone()
    assert row is not None
    assert json.loads(str(row["weights"])) == _optimizer_weights(0.11)
    assert row["last_optimized_utc"] is not None


def test_optimize_weights_rejects_bad_optimizer_weight_shape_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    review_database = _review_database_module()
    review_database.initialize_review_db(db_path)
    _insert_review_log_rows(db_path, card_id="card-bad-shape", count=3)

    class FakeOptimizer:
        def __init__(self, review_logs: list[fsrs.ReviewLog]) -> None:
            del review_logs

        def compute_optimal_parameters(self, verbose: bool = False) -> list[float]:
            del verbose
            return [0.11]

    monkeypatch.setattr(optimizer_module, "_load_optimizer_class", lambda: FakeOptimizer)

    with pytest.raises(InputError, match="weights length mismatch"):
        optimize_weights(db_path, min_reviews=2)

    with review_database.connect_review_db(db_path) as connection:
        row = connection.execute(
            """
            SELECT last_optimized_utc
            FROM scheduler_presets
            WHERE preset_id = 'default'
            """
        ).fetchone()
    assert row is not None
    assert row["last_optimized_utc"] is None


def test_optimize_weights_rejects_non_finite_optimizer_weights_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    review_database = _review_database_module()
    review_database.initialize_review_db(db_path)
    _insert_review_log_rows(db_path, card_id="card-bad-finite", count=3)

    class FakeOptimizer:
        def __init__(self, review_logs: list[fsrs.ReviewLog]) -> None:
            del review_logs

        def compute_optimal_parameters(self, verbose: bool = False) -> list[float]:
            del verbose
            weights = _optimizer_weights(0.11)
            weights[0] = float("inf")
            return weights

    monkeypatch.setattr(optimizer_module, "_load_optimizer_class", lambda: FakeOptimizer)

    with pytest.raises(InputError, match="weights must be finite"):
        optimize_weights(db_path, min_reviews=2)

    with review_database.connect_review_db(db_path) as connection:
        row = connection.execute(
            """
            SELECT last_optimized_utc
            FROM scheduler_presets
            WHERE preset_id = 'default'
            """
        ).fetchone()
    assert row is not None
    assert row["last_optimized_utc"] is None


def test_optimize_weights_uses_verbose_optimizer_in_hot_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    _review_database_module().initialize_review_db(db_path)
    seen: dict[str, object] = {}

    review_logs = [
        fsrs.ReviewLog(
            card_id=index,
            rating=fsrs.Rating.Good,
            review_datetime=datetime(2026, 4, 28, tzinfo=UTC) + timedelta(days=offset),
            review_duration=None,
        )
        for index in range(2001)
        for offset in (0, 1)
    ]

    class FakeOptimizer:
        def __init__(self, logs: list[fsrs.ReviewLog]) -> None:
            seen["review_logs"] = logs

        def compute_optimal_parameters(self, verbose: bool = False) -> list[float]:
            seen["verbose"] = verbose
            return _optimizer_weights(1.0)

    def fake_adapt_review_logs(_connection: sqlite3.Connection) -> list[fsrs.ReviewLog]:
        return review_logs

    monkeypatch.setattr(optimizer_module, "adapt_review_logs", fake_adapt_review_logs)
    monkeypatch.setattr(optimizer_module, "_load_optimizer_class", lambda: FakeOptimizer)

    result = optimize_weights(db_path, min_reviews=2)

    assert result.stage == "hot"
    assert result.review_count == 4002
    assert result.effective_review_count == 2001
    assert result.weights == _optimizer_weights(1.0)
    assert seen["verbose"] is True
    assert len(cast("list[fsrs.ReviewLog]", seen["review_logs"])) == 4002
    assert "confidence" in result.message
