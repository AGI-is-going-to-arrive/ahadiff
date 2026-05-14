from __future__ import annotations

from ahadiff.contracts import ClaimRecord, ClaimStatus, SourceHunk
from ahadiff.eval.gates import evaluate_hard_gates
from ahadiff.eval.rubric import load_rubric


def _claim(*, status: ClaimStatus) -> ClaimRecord:
    return ClaimRecord(
        claim_id=f"claim-{status}",
        run_id="run_test",
        text="Example claim",
        status=status,
        confidence="medium",
        source_hunks=[
            SourceHunk(file="src/app.py", start=1, end=2, side="new"),
        ],
    )


def test_hard_gates_pass_for_healthy_run() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 18.0, "evidence": 16.0, "diff_coverage": 10.0},
        claims=(_claim(status="verified"), _claim(status="weak")),
        secret_leak_detected=False,
        injection_unresolved=False,
    )

    assert summary.passed is True
    assert summary.failed_names() == ()


def test_hard_gates_fail_for_contradicted_claims_and_secret_leaks() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 10.0},
        claims=(_claim(status="contradicted"),),
        secret_leak_detected=True,
        injection_unresolved=False,
    )

    assert summary.passed is False
    assert summary.failed_names() == ("contradicted_claims", "secret_leak")
    assert (
        summary.as_payload()["secret_leak"]["detail"]
        == "leaked secrets detected in persisted patch"
    )


def test_hard_gates_fail_for_accuracy_and_evidence_thresholds() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 13.9, "evidence": 11.9, "diff_coverage": 10.0},
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=True,
    )

    assert summary.passed is False
    assert summary.failed_names() == ("accuracy", "evidence", "injection_unresolved")
    assert (
        summary.as_payload()["injection_unresolved"]["detail"]
        == "unresolved prompt-injection markers detected in persisted patch"
    )


def test_hard_gates_pass_at_accuracy_and_evidence_thresholds() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 14.0, "evidence": 12.0, "diff_coverage": 10.0},
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=False,
    )

    assert summary.passed is True
    assert summary.failed_names() == ()
    assert summary.as_payload()["accuracy"]["detail"] == "accuracy score 14.00 >= 14.00"
    assert summary.as_payload()["evidence"]["detail"] == "evidence score 12.00 >= 12.00"


def test_hard_gates_fail_when_evidence_coverage_below_sixty_percent() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 8.39},
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=False,
    )

    assert summary.passed is False
    assert summary.failed_names() == ("evidence_coverage",)
    assert summary.as_payload()["evidence_coverage"]["threshold"] == 8.4
