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
class HardGateResult:
    name: str
    passed: bool
    detail: str
    score: float | None = None
    threshold: float | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "passed": self.passed,
            "detail": self.detail,
        }
        if self.score is not None:
            payload["score"] = round(self.score, 2)
        if self.threshold is not None:
            payload["threshold"] = round(self.threshold, 2)
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
    results = (
        HardGateResult(
            name="accuracy",
            passed=(
                accuracy_score is not None
                and accuracy_score >= float(accuracy_dimension.hard_gate or 0.0)
            ),
            detail=_threshold_detail(
                "accuracy",
                score=accuracy_score,
                threshold=float(accuracy_dimension.hard_gate or 0.0),
            ),
            score=accuracy_score,
            threshold=accuracy_dimension.hard_gate,
        ),
        HardGateResult(
            name="evidence",
            passed=(
                evidence_score is not None
                and evidence_score >= float(evidence_dimension.hard_gate or 0.0)
            ),
            detail=_threshold_detail(
                "evidence",
                score=evidence_score,
                threshold=float(evidence_dimension.hard_gate or 0.0),
            ),
            score=evidence_score,
            threshold=evidence_dimension.hard_gate,
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


def _minimum_threshold_detail(
    name: str,
    *,
    score: float | None,
    threshold: float,
    adaptive_ratio: float,
    regime: str,
    basis: str,
) -> str:
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
    return value if isinstance(value, int) and value >= 0 else 0


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


__all__ = ["HardGateResult", "HardGateSummary", "evaluate_hard_gates"]
