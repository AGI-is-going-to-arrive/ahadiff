from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ahadiff.core.errors import InputError
from ahadiff.improve.targeted import (
    ScoreSnapshot,
    load_score_snapshot,
    targeted_dimensions,
    verify_targeted_dimensions,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_targeted_dimensions_include_goal_and_core_gates_once() -> None:
    assert targeted_dimensions("evidence") == ("evidence", "accuracy", "safety_privacy")
    assert targeted_dimensions("learnability") == (
        "learnability",
        "accuracy",
        "evidence",
        "safety_privacy",
    )


def test_verify_targeted_dimensions_passes_only_when_targeted_score_improves() -> None:
    baseline = ScoreSnapshot(
        overall=70.0,
        dimensions={
            "learnability": 10.0,
            "accuracy": 18.0,
            "evidence": 16.0,
            "safety_privacy": 6.0,
        },
    )
    candidate = ScoreSnapshot(
        overall=71.0,
        dimensions={
            "learnability": 12.0,
            "accuracy": 18.0,
            "evidence": 16.0,
            "safety_privacy": 6.0,
        },
    )

    result = verify_targeted_dimensions(
        baseline=baseline,
        candidate=candidate,
        target_dimension="learnability",
    )

    assert result.passed is True
    assert result.dimensions == ("learnability", "accuracy", "evidence", "safety_privacy")
    assert result.note_payload()["targeted_candidate_score"] == 52.0


def test_verify_targeted_dimensions_fails_on_hard_gate_failures() -> None:
    baseline = ScoreSnapshot(
        overall=70.0,
        dimensions={
            "learnability": 10.0,
            "accuracy": 18.0,
            "evidence": 16.0,
            "safety_privacy": 6.0,
        },
    )
    candidate = ScoreSnapshot(
        overall=80.0,
        dimensions={
            "learnability": 20.0,
            "accuracy": 18.0,
            "evidence": 16.0,
            "safety_privacy": 6.0,
        },
    )

    result = verify_targeted_dimensions(
        baseline=baseline,
        candidate=candidate,
        target_dimension="learnability",
        failed_gates=("secret_leak",),
    )

    assert result.passed is False
    assert result.reason == "hard_gates_failed"
    assert result.note_payload()["targeted_failed_gates"] == ["secret_leak"]


def test_load_score_snapshot_reads_score_json_dimensions(tmp_path: Path) -> None:
    run_path = tmp_path / "run"
    run_path.mkdir()
    (run_path / "score.json").write_text(
        json.dumps(
            {
                "overall": 72.5,
                "dimensions": {
                    "accuracy": {"score": 18.0, "max_score": 20.0},
                    "evidence": {"score": 16.0, "max_score": 18.0},
                    "safety_privacy": 6.0,
                    "learnability": {"score": 11.0},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = load_score_snapshot(run_path)

    assert snapshot.overall == 72.5
    assert snapshot.dimensions["learnability"] == 11.0


def test_verify_targeted_dimensions_rejects_missing_dimension() -> None:
    baseline = ScoreSnapshot(overall=70.0, dimensions={"accuracy": 18.0})
    candidate = ScoreSnapshot(overall=71.0, dimensions={"accuracy": 18.0})

    with pytest.raises(InputError, match="missing targeted dimensions"):
        verify_targeted_dimensions(
            baseline=baseline,
            candidate=candidate,
            target_dimension="learnability",
        )
