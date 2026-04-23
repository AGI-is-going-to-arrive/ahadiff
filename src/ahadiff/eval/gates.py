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
) -> HardGateSummary:
    contradicted_count = sum(1 for claim in claims if claim.status == "contradicted")
    accuracy_dimension = rubric.dimension("accuracy")
    evidence_dimension = rubric.dimension("evidence")
    results = (
        HardGateResult(
            name="accuracy",
            passed=dimension_scores["accuracy"] >= float(accuracy_dimension.hard_gate or 0.0),
            detail=(
                f"accuracy score {dimension_scores['accuracy']:.2f} "
                f">= {float(accuracy_dimension.hard_gate or 0.0):.2f}"
            ),
            score=dimension_scores["accuracy"],
            threshold=accuracy_dimension.hard_gate,
        ),
        HardGateResult(
            name="evidence",
            passed=dimension_scores["evidence"] >= float(evidence_dimension.hard_gate or 0.0),
            detail=(
                f"evidence score {dimension_scores['evidence']:.2f} "
                f">= {float(evidence_dimension.hard_gate or 0.0):.2f}"
            ),
            score=dimension_scores["evidence"],
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
    )
    return HardGateSummary(results=results)


__all__ = ["HardGateResult", "HardGateSummary", "evaluate_hard_gates"]
