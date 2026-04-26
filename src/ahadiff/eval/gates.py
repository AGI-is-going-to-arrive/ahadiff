from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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
) -> HardGateSummary:
    contradicted_count = sum(1 for claim in claims if claim.status == "contradicted")
    accuracy_dimension = rubric.dimension("accuracy")
    evidence_dimension = rubric.dimension("evidence")
    accuracy_score = _dimension_score(dimension_scores, "accuracy")
    evidence_score = _dimension_score(dimension_scores, "evidence")
    critical_safety_count = _critical_safety_finding_count(safety_findings)
    results = (
        HardGateResult(
            name="accuracy",
            passed=(
                accuracy_score is not None
                and accuracy_score > float(accuracy_dimension.hard_gate or 0.0)
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
                and evidence_score > float(evidence_dimension.hard_gate or 0.0)
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
                else f"{contradicted_count} contradicted claim(s) detected"
            ),
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
            detail=(
                "no Critical safety findings"
                if critical_safety_count == 0
                else f"{critical_safety_count} Critical safety finding(s) detected"
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
        return f"{name} score is missing; requires > {threshold:.2f}"
    if score > threshold:
        return f"{name} score {score:.2f} > {threshold:.2f}"
    return f"{name} score {score:.2f} <= {threshold:.2f}; requires > {threshold:.2f}"


def _critical_safety_finding_count(findings: Sequence[Mapping[str, object]]) -> int:
    count = 0
    for finding in findings:
        raw_severity = finding.get("severity", finding.get("level"))
        if isinstance(raw_severity, str) and raw_severity.casefold() == "critical":
            count += 1
    return count


__all__ = ["HardGateResult", "HardGateSummary", "evaluate_hard_gates"]
