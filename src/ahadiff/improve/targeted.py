from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from ahadiff.claims.extract import read_artifact_text_no_follow
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads

if TYPE_CHECKING:
    from pathlib import Path

    from ahadiff.eval.evaluator import ScoreReport

CORE_TARGETED_DIMENSIONS = ("accuracy", "evidence", "safety_privacy")
_MAX_SCORE_ARTIFACT_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ScoreSnapshot:
    overall: float
    dimensions: dict[str, float]
    verdict: str | None = None


@dataclass(frozen=True)
class TargetedVerification:
    target_dimension: str
    dimensions: tuple[str, ...]
    baseline_score: float
    candidate_score: float
    failed_gates: tuple[str, ...]
    passed: bool
    reason: str | None

    def note_payload(self) -> dict[str, object]:
        return {
            "targeted_dimensions": list(self.dimensions),
            "targeted_baseline_score": round(self.baseline_score, 2),
            "targeted_candidate_score": round(self.candidate_score, 2),
            "targeted_passed": self.passed,
            "targeted_reason": self.reason,
            "targeted_failed_gates": list(self.failed_gates),
        }


def targeted_dimensions(target_dimension: str | None) -> tuple[str, ...]:
    selected: list[str] = []
    if target_dimension:
        selected.append(target_dimension)
    for dimension in CORE_TARGETED_DIMENSIONS:
        if dimension not in selected:
            selected.append(dimension)
    return tuple(selected)


def snapshot_from_report(report: ScoreReport) -> ScoreSnapshot:
    dimensions = {item.name: float(item.score) for item in report.dimensions}
    if not dimensions:
        raise InputError("score report does not contain dimension scores")
    return ScoreSnapshot(
        overall=float(report.overall),
        dimensions=dimensions,
        verdict=report.verdict,
    )


def load_score_snapshot(
    run_path: Path,
    *,
    expected_run_id: str | None = None,
    expected_source_ref: str | None = None,
    expected_overall: float | None = None,
) -> ScoreSnapshot:
    target = run_path / "score.json"
    if not target.exists():
        raise InputError(f"baseline run is missing score.json: {run_path.name}")
    payload = _load_json_object(target)
    _validate_score_snapshot_identity(
        payload,
        target=target,
        expected_run_id=expected_run_id,
        expected_source_ref=expected_source_ref,
        expected_overall=expected_overall,
    )
    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, dict):
        raise InputError(f"score.json dimensions must be an object: {target}")
    dimension_map = cast("dict[object, object]", raw_dimensions)
    dimensions: dict[str, float] = {}
    for name, raw_value in dimension_map.items():
        if not isinstance(name, str):
            raise InputError(f"score.json dimension names must be strings: {target}")
        if isinstance(raw_value, dict):
            value_map = cast("dict[object, object]", raw_value)
            score_value = value_map.get("score")
        else:
            score_value = raw_value
        if not isinstance(score_value, int | float):
            raise InputError(f"score.json dimension {name!r} score must be numeric: {target}")
        dimensions[name] = float(score_value)
    overall = payload.get("overall")
    if not isinstance(overall, int | float):
        raise InputError(f"score.json overall must be numeric: {target}")
    verdict = payload.get("verdict")
    if verdict is not None and not isinstance(verdict, str):
        raise InputError(f"score.json verdict must be a string: {target}")
    return ScoreSnapshot(
        overall=float(overall),
        dimensions=dimensions,
        verdict=verdict,
    )


def _validate_score_snapshot_identity(
    payload: dict[str, Any],
    *,
    target: Path,
    expected_run_id: str | None,
    expected_source_ref: str | None,
    expected_overall: float | None,
) -> None:
    if expected_run_id is not None and payload.get("run_id") != expected_run_id:
        raise InputError(f"score.json run_id does not match selected baseline event: {target}")
    if expected_source_ref is not None and payload.get("source_ref") != expected_source_ref:
        raise InputError(f"score.json source_ref does not match selected baseline event: {target}")
    if expected_overall is not None:
        overall = payload.get("overall")
        if not isinstance(overall, int | float) or float(overall) != float(expected_overall):
            raise InputError(f"score.json overall does not match selected baseline event: {target}")


def verify_targeted_dimensions(
    *,
    baseline: ScoreSnapshot,
    candidate: ScoreSnapshot,
    target_dimension: str,
    failed_gates: tuple[str, ...] = (),
) -> TargetedVerification:
    dimensions = targeted_dimensions(target_dimension)
    baseline_score = _score_for_dimensions(baseline, dimensions)
    candidate_score = _score_for_dimensions(candidate, dimensions)
    reason: str | None = None
    if baseline.verdict not in {None, "PASS"}:
        reason = "baseline_verdict_not_pass"
    elif candidate.verdict not in {None, "PASS"}:
        reason = "candidate_verdict_not_pass"
    elif failed_gates:
        reason = "hard_gates_failed"
    elif candidate_score <= baseline_score:
        reason = "targeted_score_not_improved"
    return TargetedVerification(
        target_dimension=target_dimension,
        dimensions=dimensions,
        baseline_score=baseline_score,
        candidate_score=candidate_score,
        failed_gates=failed_gates,
        passed=reason is None,
        reason=reason,
    )


def _score_for_dimensions(snapshot: ScoreSnapshot, dimensions: tuple[str, ...]) -> float:
    missing = [name for name in dimensions if name not in snapshot.dimensions]
    if missing:
        joined = ", ".join(missing)
        raise InputError(f"score report is missing targeted dimensions: {joined}")
    return round(sum(snapshot.dimensions[name] for name in dimensions), 2)


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = safe_json_loads(
            read_artifact_text_no_follow(path, max_bytes=_MAX_SCORE_ARTIFACT_BYTES),
            max_input_bytes=_MAX_SCORE_ARTIFACT_BYTES,
        )
    except ValueError as exc:
        raise InputError(f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise InputError(f"expected a JSON object in {path}")
    return cast("dict[str, Any]", payload)


__all__ = [
    "CORE_TARGETED_DIMENSIONS",
    "ScoreSnapshot",
    "TargetedVerification",
    "load_score_snapshot",
    "snapshot_from_report",
    "targeted_dimensions",
    "verify_targeted_dimensions",
]
