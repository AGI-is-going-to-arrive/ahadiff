from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

_EVIDENCE_COVERAGE_GATE_RATIO = 0.55
_SHA256_HEX_LENGTH = 64
_REDACTION_SOURCE_KINDS = frozenset(
    {"raw_patch", "resolved_file", "branch_name", "tag_name", "markdown", "string"}
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ahadiff.contracts import ClaimRecord

    from .rubric import RubricDefinition


@dataclass(frozen=True)
class HardGatePolicy:
    kind: str
    ratio: float
    regime: str
    basis: Mapping[str, int]

    def as_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "ratio": round(self.ratio, 2),
            "regime": self.regime,
            "basis": dict(self.basis),
        }


@dataclass(frozen=True)
class HardGateResult:
    name: str
    passed: bool
    detail: str
    score: float | None = None
    threshold: float | None = None
    policy: HardGatePolicy | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "passed": self.passed,
            "detail": self.detail,
        }
        if self.score is not None:
            payload["score"] = round(self.score, 2)
        if self.threshold is not None:
            payload["threshold"] = round(self.threshold, 2)
        if self.policy is not None:
            payload["policy"] = self.policy.as_payload()
        return payload


@dataclass(frozen=True)
class HardGateSummary:
    results: tuple[HardGateResult, ...]

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.results)

    def failed_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.results if not item.passed)

    def as_payload(self) -> dict[str, dict[str, object]]:
        return {item.name: item.as_payload() for item in self.results}


def evaluate_hard_gates(
    *,
    rubric: RubricDefinition,
    dimension_scores: Mapping[str, float],
    claims: Sequence[ClaimRecord],
    secret_leak_detected: bool,
    injection_unresolved: bool,
    safety_findings: Sequence[Mapping[str, object]] = (),
    diff_coverage_basis: Mapping[str, int] | None = None,
) -> HardGateSummary:
    contradicted_count = sum(1 for claim in claims if claim.status == "contradicted")
    accuracy_dimension = rubric.dimension("accuracy")
    evidence_dimension = rubric.dimension("evidence")
    diff_coverage_dimension = rubric.dimension("diff_coverage")
    accuracy_score = _dimension_score(dimension_scores, "accuracy")
    evidence_score = _dimension_score(dimension_scores, "evidence")
    diff_coverage_score = _dimension_score(dimension_scores, "diff_coverage")
    evidence_coverage_ratio, evidence_coverage_regime, evidence_coverage_basis_detail = (
        _evidence_coverage_threshold_policy(diff_coverage_basis)
    )
    evidence_coverage_threshold = round(
        float(diff_coverage_dimension.max_score) * evidence_coverage_ratio,
        2,
    )
    critical_safety_count = _critical_safety_finding_count(safety_findings)
    mitigated_critical_safety_count = _mitigated_critical_safety_finding_count(safety_findings)
    adaptive_policy = _adaptive_accuracy_evidence_policy(diff_coverage_basis)
    rejected_quality = _rejected_quality_constraint(claims)
    accuracy_base_threshold = float(accuracy_dimension.hard_gate or 0.0)
    evidence_base_threshold = float(evidence_dimension.hard_gate or 0.0)
    accuracy_threshold = _adaptive_gate_threshold(accuracy_base_threshold, adaptive_policy)
    evidence_threshold = _adaptive_gate_threshold(evidence_base_threshold, adaptive_policy)
    accuracy_quality_blocked = _adaptive_quality_blocks_pass(
        score=accuracy_score,
        base_threshold=accuracy_base_threshold,
        adjusted_threshold=accuracy_threshold,
        rejected_quality=rejected_quality,
    )
    evidence_quality_blocked = _adaptive_quality_blocks_pass(
        score=evidence_score,
        base_threshold=evidence_base_threshold,
        adjusted_threshold=evidence_threshold,
        rejected_quality=rejected_quality,
    )
    results = (
        HardGateResult(
            name="accuracy",
            passed=accuracy_score is not None
            and accuracy_score >= accuracy_threshold
            and not accuracy_quality_blocked,
            detail=_adaptive_threshold_detail(
                "accuracy",
                score=accuracy_score,
                threshold=accuracy_threshold,
                policy=adaptive_policy,
                rejected_quality=rejected_quality,
                quality_blocked=accuracy_quality_blocked,
            ),
            score=accuracy_score,
            threshold=accuracy_threshold,
            policy=adaptive_policy,
        ),
        HardGateResult(
            name="evidence",
            passed=evidence_score is not None
            and evidence_score >= evidence_threshold
            and not evidence_quality_blocked,
            detail=_adaptive_threshold_detail(
                "evidence",
                score=evidence_score,
                threshold=evidence_threshold,
                policy=adaptive_policy,
                rejected_quality=rejected_quality,
                quality_blocked=evidence_quality_blocked,
            ),
            score=evidence_score,
            threshold=evidence_threshold,
            policy=adaptive_policy,
        ),
        HardGateResult(
            name="contradicted_claims",
            passed=contradicted_count == 0,
            detail=(
                "no contradicted claims"
                if contradicted_count == 0
                else f"{contradicted_count} contradicted claim(s); requires 0"
            ),
        ),
        HardGateResult(
            name="evidence_coverage",
            passed=diff_coverage_score is not None
            and diff_coverage_score >= evidence_coverage_threshold,
            detail=_minimum_threshold_detail(
                "claim anchor coverage",
                score=diff_coverage_score,
                threshold=evidence_coverage_threshold,
                adaptive_ratio=evidence_coverage_ratio,
                regime=evidence_coverage_regime,
                basis=evidence_coverage_basis_detail,
            ),
            score=diff_coverage_score,
            threshold=evidence_coverage_threshold,
        ),
        HardGateResult(
            name="secret_leak",
            passed=not secret_leak_detected,
            detail=(
                "no leaked secrets detected in persisted patch"
                if not secret_leak_detected
                else "leaked secrets detected in persisted patch"
            ),
        ),
        HardGateResult(
            name="injection_unresolved",
            passed=not injection_unresolved,
            detail=(
                "no unresolved prompt-injection markers detected in persisted patch"
                if not injection_unresolved
                else "unresolved prompt-injection markers detected in persisted patch"
            ),
        ),
        HardGateResult(
            name="critical_safety_findings",
            passed=critical_safety_count == 0,
            detail=_critical_safety_finding_detail(
                critical_safety_count,
                mitigated_critical_safety_count,
            ),
        ),
    )
    return HardGateSummary(results=results)


def _dimension_score(dimension_scores: Mapping[str, float], name: str) -> float | None:
    value = dimension_scores.get(name)
    if value is None:
        return None
    return float(value)


def _threshold_detail(name: str, *, score: float | None, threshold: float) -> str:
    if score is None:
        return f"{name} score is missing; requires >= {threshold:.2f}"
    if score >= threshold:
        return f"{name} score {score:.2f} >= {threshold:.2f}"
    return f"{name} score {score:.2f} < {threshold:.2f}; requires >= {threshold:.2f}"


@dataclass(frozen=True)
class RejectedQualityConstraint:
    ratio: float
    blocked: bool


def _adaptive_threshold_detail(
    name: str,
    *,
    score: float | None,
    threshold: float,
    policy: HardGatePolicy | None,
    rejected_quality: RejectedQualityConstraint,
    quality_blocked: bool,
) -> str:
    detail = _threshold_detail(name, score=score, threshold=threshold)
    if policy is not None:
        detail += f"; adaptive_ratio={policy.ratio:.2f}; regime={policy.regime}"
    if quality_blocked:
        detail += (
            f"; blocked_by_rejected_ratio={rejected_quality.ratio:.2f}; "
            "unsafe_rejected_claims_exceed_25_percent"
        )
    return detail


def _minimum_threshold_detail(
    name: str,
    *,
    score: float | None,
    threshold: float,
    adaptive_ratio: float,
    regime: str,
    basis: str,
) -> str:
    if basis == "unavailable":
        policy_detail = f"fixed_ratio={adaptive_ratio:.2f}; basis=unavailable"
    else:
        policy_detail = f"adaptive_ratio={adaptive_ratio:.2f}; regime={regime}; basis={basis}"
    if score is None:
        return f"{name} score is missing; requires >= {threshold:.2f}; {policy_detail}"
    if score >= threshold:
        return f"{name} score {score:.2f} >= {threshold:.2f}; {policy_detail}"
    return (
        f"{name} score {score:.2f} < {threshold:.2f}; requires >= {threshold:.2f}; {policy_detail}"
    )


def _evidence_coverage_threshold_policy(
    basis: Mapping[str, int] | None,
) -> tuple[float, str, str]:
    if basis is None:
        return _EVIDENCE_COVERAGE_GATE_RATIO, "normal", "unavailable"
    visible_files = _non_negative_int(basis.get("visible_files"))
    visible_hunks = _non_negative_int(basis.get("visible_hunks"))
    visible_changed_lines = _non_negative_int(basis.get("visible_changed_lines"))
    if visible_files <= 2 and visible_hunks > 80:
        basis_detail = (
            f"visible_files={visible_files}, visible_hunks={visible_hunks}, "
            f"visible_changed_lines={visible_changed_lines}"
        )
        return 0.64, "single_file_many_hunks", basis_detail
    ratio, regime = _adaptive_evidence_coverage_ratio(
        visible_hunks=visible_hunks,
        visible_changed_lines=visible_changed_lines,
    )
    basis_detail = (
        f"visible_files={visible_files}, visible_hunks={visible_hunks}, "
        f"visible_changed_lines={visible_changed_lines}"
    )
    return ratio, regime, basis_detail


def _adaptive_accuracy_evidence_policy(
    basis: Mapping[str, int] | None,
) -> HardGatePolicy | None:
    if basis is None:
        return None
    visible_files = _non_negative_int(basis.get("visible_files"))
    visible_hunks = _non_negative_int(basis.get("visible_hunks"))
    visible_changed_lines = _non_negative_int(basis.get("visible_changed_lines"))
    ratio, regime = _adaptive_accuracy_evidence_ratio(
        visible_hunks=visible_hunks,
        visible_changed_lines=visible_changed_lines,
    )
    return HardGatePolicy(
        kind="adaptive_threshold",
        ratio=ratio,
        regime=regime,
        basis={
            "visible_files": visible_files,
            "visible_hunks": visible_hunks,
            "visible_changed_lines": visible_changed_lines,
        },
    )


def _adaptive_gate_threshold(base_threshold: float, policy: HardGatePolicy | None) -> float:
    if policy is None:
        return base_threshold
    return round(base_threshold * policy.ratio, 2)


def _adaptive_quality_blocks_pass(
    *,
    score: float | None,
    base_threshold: float,
    adjusted_threshold: float,
    rejected_quality: RejectedQualityConstraint,
) -> bool:
    if score is None or not rejected_quality.blocked:
        return False
    return adjusted_threshold < base_threshold and adjusted_threshold <= score < base_threshold


def _rejected_quality_constraint(claims: Sequence[ClaimRecord]) -> RejectedQualityConstraint:
    if not claims:
        return RejectedQualityConstraint(ratio=0.0, blocked=False)
    rejected_claims = tuple(claim for claim in claims if claim.status == "rejected")
    rejected_ratio = len(rejected_claims) / len(claims)
    if rejected_ratio <= 0.25:
        return RejectedQualityConstraint(ratio=rejected_ratio, blocked=False)
    unsafe_rejected = any(
        not _is_safe_phase2_diagnostic_rejection(claim) for claim in rejected_claims
    )
    return RejectedQualityConstraint(ratio=rejected_ratio, blocked=unsafe_rejected)


def _is_safe_phase2_diagnostic_rejection(_claim: ClaimRecord) -> bool:
    # ClaimRecord currently has no narrow Phase 2 safe-diagnostic marker.
    return False


def _adaptive_accuracy_evidence_ratio(
    *,
    visible_hunks: int,
    visible_changed_lines: int,
) -> tuple[float, str]:
    if visible_hunks <= 20 and visible_changed_lines <= 400:
        return 1.0, "normal"
    if visible_hunks <= 80 and visible_changed_lines <= 1200:
        return 0.95, "medium"
    if visible_hunks <= 160 and visible_changed_lines <= 3000:
        return 0.90, "large"
    return 0.85, "very_large"


def _adaptive_evidence_coverage_ratio(
    *,
    visible_hunks: int,
    visible_changed_lines: int,
) -> tuple[float, str]:
    if visible_hunks <= 20 and visible_changed_lines <= 400:
        return 0.55, "normal"
    if visible_hunks <= 80 and visible_changed_lines <= 1200:
        return 0.52, "medium"
    if visible_hunks <= 160 and visible_changed_lines <= 3000:
        return 0.50, "large"
    return 0.48, "very_large"


def _non_negative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _critical_safety_finding_count(findings: Sequence[Mapping[str, object]]) -> int:
    count = 0
    for finding in findings:
        raw_severity = finding.get("severity", finding.get("level"))
        if not (isinstance(raw_severity, str) and raw_severity.casefold() == "critical"):
            continue
        # Skip only capture-shaped findings that were actually redacted locally.
        if _is_mitigated_critical_redaction_finding(finding):
            continue
        count += 1
    return count


def _mitigated_critical_safety_finding_count(
    findings: Sequence[Mapping[str, object]],
) -> int:
    count = 0
    for finding in findings:
        raw_severity = finding.get("severity", finding.get("level"))
        if not (isinstance(raw_severity, str) and raw_severity.casefold() == "critical"):
            continue
        if _is_mitigated_critical_redaction_finding(finding):
            count += 1
    return count


def _is_mitigated_critical_redaction_finding(finding: Mapping[str, object]) -> bool:
    if finding.get("action") != "redact" or finding.get("blocked_remote") is not True:
        return False
    if finding.get("allowlisted") is not False:
        return False
    if not _non_empty_string(finding.get("rule_id")):
        return False
    if not _non_empty_string(finding.get("secret_type")):
        return False
    if not _sha256_hex(finding.get("value_sha256")):
        return False
    source_kind = finding.get("source_kind")
    if not isinstance(source_kind, str) or source_kind not in _REDACTION_SOURCE_KINDS:
        return False
    if not _non_empty_string(finding.get("source_name")):
        return False
    return _positive_int(finding.get("line")) and _positive_int(finding.get("column"))


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_HEX_LENGTH
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _critical_safety_finding_detail(
    unmitigated_count: int,
    mitigated_count: int,
) -> str:
    if mitigated_count > 0:
        base = f"{unmitigated_count} unmitigated Critical safety finding(s)"
        if unmitigated_count > 0:
            base += " detected"
        return f"{base} ({mitigated_count} mitigated by redaction)"
    if unmitigated_count == 0:
        return "no Critical safety findings"
    return f"{unmitigated_count} unmitigated Critical safety finding(s) detected"


__all__ = ["HardGatePolicy", "HardGateResult", "HardGateSummary", "evaluate_hard_gates"]
