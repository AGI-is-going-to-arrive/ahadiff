from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from ahadiff.contracts.serve_stats import ActivePracticeSummary, PracticeAttemptSummary
from ahadiff.lesson.practice_metrics import aggregate_active_practice
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from pathlib import Path


def _payload(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "run_id": "run-1",
        "quiz_id": "quiz_exercise_one",
        "exercise_kind": "prediction",
        "feedback_kind": "semantic_self_assessment",
        "correct": None,
        "self_assessment": "independent",
        "error_type": "none",
        "attempt_kind": "initial",
    }
    result.update(changes)
    return result


def _write_rows(db: Path, rows: list[tuple[dict[str, object], str]]) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as connection:
        connection.execute("""CREATE TABLE learning_signals (
            event_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE, signal_type TEXT,
            payload_json TEXT, created_at TEXT
        )""")
        for index, (payload, timestamp) in enumerate(rows):
            connection.execute(
                "INSERT INTO learning_signals VALUES (?, ?, ?, ?, ?)",
                (
                    str(index),
                    str(index),
                    "quiz_answer",
                    json.dumps(payload),
                    timestamp,
                ),
            )


def test_missing_or_old_db_has_null_rates_without_creating_or_upgrading_it(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "review.sqlite"
    assert aggregate_active_practice(missing) == ActivePracticeSummary()
    assert not missing.parent.exists()
    old = tmp_path / "old.sqlite"
    with sqlite3.connect(old) as connection:
        connection.execute("CREATE TABLE old_data(value TEXT)")
    before = old.read_bytes()
    result = aggregate_active_practice(old)
    assert result.initial.independent_rate is None
    assert result.delayed_recall.attempts == 0
    assert result.unseen_variant.independent_rate is None
    assert old.read_bytes() == before


def test_initial_and_unseen_denominators_do_not_grow_when_the_same_question_is_repeated(
    tmp_path: Path,
) -> None:
    start = datetime.now(UTC) - timedelta(hours=100)

    def at(hours: int) -> str:
        return (start + timedelta(hours=hours)).isoformat()

    db = tmp_path / "review.sqlite"
    _write_rows(
        db,
        [
            (_payload(self_assessment="assisted", error_type="reasoning"), at(0)),
            (_payload(), at(1)),
            (_payload(attempt_kind="delayed_recall", elapsed_seconds=25 * 3600), at(26)),
            (_payload(attempt_kind="delayed_recall", elapsed_seconds=25 * 3600), at(26)),
            (
                _payload(
                    quiz_id="quiz_exercise_variant",
                    attempt_kind="unseen_variant",
                    scenario_kind="new_variant",
                ),
                at(2),
            ),
            (
                _payload(
                    quiz_id="quiz_exercise_variant",
                    attempt_kind="unseen_variant",
                    scenario_kind="new_variant",
                    self_assessment="not_yet",
                    error_type="application",
                ),
                at(3),
            ),
        ],
    )
    summary = aggregate_active_practice(db)
    assert summary.initial.model_dump() == {"attempts": 1, "independent_rate": 0.0}
    assert summary.delayed_recall.model_dump() == {"attempts": 1, "independent_rate": 1.0}
    assert summary.unseen_variant.model_dump() == {"attempts": 1, "independent_rate": 1.0}
    assert summary.error_types.model_dump() == {
        "none": 2,
        "recall": 0,
        "application": 0,
        "reasoning": 1,
        "boundary": 0,
    }
    assert summary.feedback_kind == "self_reported"


@pytest.mark.parametrize(
    "changes",
    [
        {"correct": True},
        {"correct": "null"},
        {"feedback_kind": "choice_check"},
        {"exercise_kind": ["prediction"]},
        {"attempt_kind": {"initial": True}},
        {"self_assessment": "machine_pass"},
        {"error_type": ["none"]},
        {"self_assessment": "assisted", "error_type": "none"},
        {"elapsed_seconds": float("nan")},
        {"elapsed_seconds": float("inf")},
        {"elapsed_seconds": True},
        {"elapsed_seconds": -1},
        {"run_id": ""},
        {"quiz_id": None},
        {"choice": "untrusted free-form answer"},
        {"scenario_kind": "source_example"},
    ],
)
def test_invalid_signal_metadata_does_not_become_a_sample(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    db = tmp_path / "review.sqlite"
    _write_rows(db, [(_payload(**changes), (datetime.now(UTC) - timedelta(hours=1)).isoformat())])
    assert aggregate_active_practice(db) == ActivePracticeSummary()


@pytest.mark.parametrize("timestamp", ["invalid", "2020-01-01T00:00:00", "9999-01-01T00:00:00Z"])
def test_invalid_naive_or_future_timestamps_are_not_learning_samples(
    tmp_path: Path, timestamp: str
) -> None:
    db = tmp_path / "review.sqlite"
    _write_rows(db, [(_payload(), timestamp)])
    assert aggregate_active_practice(db) == ActivePracticeSummary()


def test_delayed_recall_needs_a_real_prior_time_and_consistent_recorded_delay(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    db = tmp_path / "review.sqlite"
    _write_rows(
        db,
        [
            (
                _payload(attempt_kind="delayed_recall", elapsed_seconds=100000),
                (now - timedelta(hours=100)).isoformat(),
            ),
            (
                _payload(attempt_kind="delayed_recall", elapsed_seconds=100000),
                (now - timedelta(hours=99)).isoformat(),
            ),
            (
                _payload(attempt_kind="delayed_recall", elapsed_seconds=86400),
                (now - timedelta(hours=40)).isoformat(),
            ),
        ],
    )
    assert aggregate_active_practice(db).delayed_recall.attempts == 0


def test_unseen_variant_requires_a_recorded_new_scenario_and_is_unique_per_run_question(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC) - timedelta(hours=2)
    db = tmp_path / "review.sqlite"
    _write_rows(
        db,
        [
            (_payload(attempt_kind="unseen_variant"), now.isoformat()),
            (
                _payload(attempt_kind="unseen_variant", scenario_kind="new_variant"),
                (now + timedelta(minutes=1)).isoformat(),
            ),
            (
                _payload(
                    run_id="run-2", attempt_kind="unseen_variant", scenario_kind="new_variant"
                ),
                now.isoformat(),
            ),
        ],
    )
    summary = aggregate_active_practice(db)
    assert summary.initial.attempts == 0
    assert summary.unseen_variant.attempts == 1


def test_time_order_is_normalized_across_offsets(tmp_path: Path) -> None:
    earlier = datetime.now(UTC) - timedelta(hours=60)
    later = earlier + timedelta(hours=25)
    db = tmp_path / "review.sqlite"
    _write_rows(
        db,
        [
            (_payload(), earlier.astimezone(timezone(timedelta(hours=14))).isoformat()),
            (
                _payload(attempt_kind="delayed_recall", elapsed_seconds=25 * 3600),
                later.astimezone(timezone(timedelta(hours=-12))).isoformat(),
            ),
        ],
    )
    assert aggregate_active_practice(db).delayed_recall.attempts == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"attempts": 0, "independent_rate": 0.0},
        {"attempts": 1, "independent_rate": None},
        {"attempts": True, "independent_rate": 1.0},
        {"attempts": 1, "independent_rate": float("nan")},
        {"attempts": 1, "independent_rate": 1.1},
    ],
)
def test_rate_contract_rejects_unmeasured_numeric_and_nonfinite_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        PracticeAttemptSummary.model_validate(payload)


def test_learning_api_keeps_delete_journal_and_database_bytes_unchanged(tmp_path: Path) -> None:
    state = tmp_path / ".ahadiff"
    db = state / "review.sqlite"
    _write_rows(db, [(_payload(), (datetime.now(UTC) - timedelta(hours=1)).isoformat())])
    with sqlite3.connect(db) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    before = db.read_bytes()
    client = TestClient(
        create_app(ServeState(state_dir=state, token="test-token")),
        base_url="http://localhost:8765",
    )
    response = client.get("/api/stats/learning", headers={"X-AhaDiff-Token": "test-token"})
    assert response.status_code == 200
    assert response.json()["active_practice"]["initial"] == {"attempts": 1, "independent_rate": 1.0}
    assert response.json()["transfer_rate"] == 0.0
    assert db.read_bytes() == before
    with sqlite3.connect(db) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert not db.with_name("review.sqlite-wal").exists()


def test_learning_api_missing_db_does_not_create_it(tmp_path: Path) -> None:
    state = tmp_path / ".ahadiff"
    client = TestClient(
        create_app(ServeState(state_dir=state, token="test-token")),
        base_url="http://localhost:8765",
    )
    response = client.get("/api/stats/learning", headers={"X-AhaDiff-Token": "test-token"})
    assert response.status_code == 200
    assert response.json()["active_practice"]["delayed_recall"]["independent_rate"] is None
    assert not (state / "review.sqlite").exists()
