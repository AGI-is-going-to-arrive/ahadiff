from __future__ import annotations

import pytest

from ahadiff.contracts import ClaimRecord, ClaimStatus, RejectReasonCode, SourceHunk
from ahadiff.eval.gates import evaluate_hard_gates
from ahadiff.eval.rubric import load_rubric


def _claim(
    *,
    status: ClaimStatus,
    reason_code: RejectReasonCode | None = None,
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=f"claim-{status}-{reason_code or 'none'}",
        run_id="run_test",
        text="Example claim",
        status=status,
        reason_code=(reason_code or "evidence_missing") if status == "rejected" else None,
        confidence="medium",
        source_hunks=[
            SourceHunk(file="src/app.py", start=1, end=2, side="new"),
        ],
    )


def _mitigated_secret_finding(**overrides: object) -> dict[str, object]:
    finding: dict[str, object] = {
        "severity": "Critical",
        "action": "redact",
        "allowlisted": False,
        "blocked_remote": True,
        "column": 1,
        "line": 1,
        "rule_id": "OPENAI_API_KEY",
        "secret_type": "openai_api_key",
        "source_kind": "raw_patch",
        "source_name": "raw_patch",
        "value_sha256": "a" * 64,
    }
    finding.update(overrides)
    for key, value in list(finding.items()):
        if value is None:
            finding.pop(key)
    return finding


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
    payload = summary.as_payload()
    assert payload["accuracy"]["detail"] == "accuracy score 14.00 >= 14.00"
    assert payload["accuracy"]["threshold"] == 14.00
    assert "policy" not in payload["accuracy"]
    assert payload["evidence"]["detail"] == "evidence score 12.00 >= 12.00"
    assert payload["evidence"]["threshold"] == 12.00
    assert "policy" not in payload["evidence"]


@pytest.mark.parametrize(
    ("basis", "expected_regime", "expected_accuracy", "expected_evidence"),
    [
        (
            {"visible_files": 2, "visible_hunks": 20, "visible_changed_lines": 400},
            "normal",
            14.00,
            12.00,
        ),
        (
            {"visible_files": 8, "visible_hunks": 80, "visible_changed_lines": 1200},
            "medium",
            13.30,
            11.40,
        ),
        (
            {"visible_files": 24, "visible_hunks": 160, "visible_changed_lines": 3000},
            "large",
            12.60,
            10.80,
        ),
        (
            {"visible_files": 44, "visible_hunks": 164, "visible_changed_lines": 2756},
            "very_large",
            11.90,
            10.20,
        ),
    ],
)
def test_accuracy_and_evidence_gates_use_adaptive_threshold_policy(
    basis: dict[str, int],
    expected_regime: str,
    expected_accuracy: float,
    expected_evidence: float,
) -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={
            "accuracy": expected_accuracy,
            "evidence": expected_evidence,
            "diff_coverage": 14.0,
        },
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=False,
        diff_coverage_basis=basis,
    )

    payload = summary.as_payload()
    accuracy = payload["accuracy"]
    evidence = payload["evidence"]

    assert summary.failed_names() == ()
    assert accuracy["threshold"] == expected_accuracy
    assert evidence["threshold"] == expected_evidence
    assert accuracy["passed"] is True
    assert evidence["passed"] is True
    assert accuracy["policy"] == {
        "kind": "adaptive_threshold",
        "ratio": round(expected_accuracy / 14.0, 2),
        "regime": expected_regime,
        "basis": basis,
    }
    assert evidence["policy"] == {
        "kind": "adaptive_threshold",
        "ratio": round(expected_evidence / 12.0, 2),
        "regime": expected_regime,
        "basis": basis,
    }
    assert "policy" not in payload["contradicted_claims"]
    assert "policy" not in payload["evidence_coverage"]
    assert "policy" not in payload["secret_leak"]
    assert "policy" not in payload["injection_unresolved"]
    assert "policy" not in payload["critical_safety_findings"]


def test_adaptive_accuracy_and_evidence_gate_rejected_ratio_quality_constraint() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 11.90, "evidence": 10.20, "diff_coverage": 14.0},
        claims=(
            _claim(status="verified"),
            _claim(status="verified"),
            _claim(status="rejected", reason_code="evidence_missing"),
        ),
        secret_leak_detected=False,
        injection_unresolved=False,
        diff_coverage_basis={
            "visible_files": 44,
            "visible_hunks": 164,
            "visible_changed_lines": 2756,
        },
    )

    payload = summary.as_payload()

    assert summary.failed_names() == ("accuracy", "evidence")
    assert payload["accuracy"]["threshold"] == 11.90
    assert payload["evidence"]["threshold"] == 10.20
    assert "blocked_by_rejected_ratio=0.33" in str(payload["accuracy"]["detail"])
    assert "blocked_by_rejected_ratio=0.33" in str(payload["evidence"]["detail"])


def test_hard_gates_fail_when_evidence_coverage_below_threshold() -> None:
    failed_summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 7.69},
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=False,
    )
    passed_summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 7.70},
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=False,
    )

    assert failed_summary.passed is False
    assert failed_summary.failed_names() == ("evidence_coverage",)
    assert failed_summary.as_payload()["evidence_coverage"]["threshold"] == 7.7
    assert passed_summary.passed is True
    assert passed_summary.failed_names() == ()


def test_evidence_coverage_gate_keeps_fixed_threshold_when_basis_unavailable() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 7.70},
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=False,
    )

    payload = summary.as_payload()["evidence_coverage"]
    detail = str(payload["detail"])
    assert payload["threshold"] == 7.70
    assert "basis=unavailable" in detail
    assert "regime=" not in detail


def test_evidence_coverage_gate_uses_adaptive_threshold_for_large_visible_diff() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 7.0},
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=False,
        diff_coverage_basis={
            "visible_files": 30,
            "visible_hunks": 109,
            "visible_changed_lines": 1841,
        },
    )

    payload = summary.as_payload()["evidence_coverage"]
    assert summary.failed_names() == ()
    assert payload["threshold"] == 7.0
    assert "adaptive_ratio=0.50" in str(payload["detail"])
    assert "regime=large" in str(payload["detail"])
    assert "visible_hunks=109" in str(payload["detail"])


def test_adaptive_threshold_does_not_modify_safety_gates() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 14.0},
        claims=(_claim(status="verified"),),
        secret_leak_detected=True,
        injection_unresolved=True,
        diff_coverage_basis={
            "visible_files": 50,
            "visible_hunks": 200,
            "visible_changed_lines": 4000,
        },
    )

    assert summary.failed_names() == ("secret_leak", "injection_unresolved")


def test_evidence_coverage_gate_rejects_single_file_many_hunks_with_tiny_anchor() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 8.46},
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=False,
        diff_coverage_basis={
            "visible_files": 1,
            "visible_hunks": 100,
            "visible_changed_lines": 200,
        },
    )

    payload = summary.as_payload()["evidence_coverage"]
    assert summary.failed_names() == ("evidence_coverage",)
    assert payload["threshold"] == 8.96
    assert "regime=single_file_many_hunks" in str(payload["detail"])


def test_critical_safety_findings_skips_mitigated_redactions() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 10.0},
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=False,
        safety_findings=[
            _mitigated_secret_finding(),
            _mitigated_secret_finding(level="critical", severity=None, value_sha256="b" * 64),
        ],
    )

    detail = str(summary.as_payload()["critical_safety_findings"]["detail"])
    assert summary.passed is True
    assert summary.failed_names() == ()
    assert "0 unmitigated" in detail
    assert "(2 mitigated by redaction)" in detail


def test_critical_safety_findings_counts_unmitigated_only() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 10.0},
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=False,
        safety_findings=[
            {"severity": "Critical"},
            {"level": "critical", "action": "redact", "blocked_remote": False},
            *[_mitigated_secret_finding(value_sha256=f"{index:064x}") for index in range(13)],
        ],
    )

    detail = str(summary.as_payload()["critical_safety_findings"]["detail"])
    assert summary.passed is False
    assert summary.failed_names() == ("critical_safety_findings",)
    assert "2 unmitigated" in detail
    assert "13 mitigated" in detail


def test_critical_safety_findings_do_not_trust_forged_mitigation_fields() -> None:
    summary = evaluate_hard_gates(
        rubric=load_rubric(),
        dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 10.0},
        claims=(_claim(status="verified"),),
        secret_leak_detected=False,
        injection_unresolved=False,
        safety_findings=[
            {"severity": "Critical", "action": "redact", "blocked_remote": True},
            _mitigated_secret_finding(value_sha256="not-a-sha256"),
        ],
    )

    detail = str(summary.as_payload()["critical_safety_findings"]["detail"])
    assert summary.passed is False
    assert summary.failed_names() == ("critical_safety_findings",)
    assert detail == "2 unmitigated Critical safety finding(s) detected"


def test_critical_safety_finding_detail_covers_all_redaction_count_combinations() -> None:
    cases: list[tuple[list[dict[str, object]], str, bool]] = [
        ([], "no Critical safety findings", True),
        (
            [_mitigated_secret_finding()],
            "0 unmitigated Critical safety finding(s) (1 mitigated by redaction)",
            True,
        ),
        (
            [{"severity": "Critical"}],
            "1 unmitigated Critical safety finding(s) detected",
            False,
        ),
        (
            [{"severity": "Critical"}, _mitigated_secret_finding()],
            "1 unmitigated Critical safety finding(s) detected (1 mitigated by redaction)",
            False,
        ),
    ]

    for findings, expected_detail, expected_passed in cases:
        summary = evaluate_hard_gates(
            rubric=load_rubric(),
            dimension_scores={"accuracy": 19.0, "evidence": 16.0, "diff_coverage": 10.0},
            claims=(_claim(status="verified"),),
            secret_leak_detected=False,
            injection_unresolved=False,
            safety_findings=findings,
        )
        payload = summary.as_payload()["critical_safety_findings"]
        assert summary.passed is expected_passed
        assert payload["detail"] == expected_detail
