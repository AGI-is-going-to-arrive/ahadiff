from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ahadiff.claims import load_line_map_records
from ahadiff.contracts import ClaimRecord, compute_runtime_eval_bundle_version
from ahadiff.core.errors import InputError

from .deterministic import DimensionScore, build_deterministic_scores
from .gates import HardGateSummary, evaluate_hard_gates
from .rubric import load_rubric


@dataclass(frozen=True)
class ScoreReport:
    run_id: str
    source_ref: str
    source_kind: str
    capability_level: int
    degraded_flags: dict[str, bool]
    overall: float
    verdict: str
    weakest_dim: str
    eval_bundle_version: str
    rubric_version: str
    dimensions: tuple[DimensionScore, ...]
    hard_gates: HardGateSummary
    notes: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "source_ref": self.source_ref,
            "source_kind": self.source_kind,
            "capability_level": self.capability_level,
            "degraded_flags": self.degraded_flags,
            "overall": round(self.overall, 2),
            "verdict": self.verdict,
            "weakest_dim": self.weakest_dim,
            "eval_bundle_version": self.eval_bundle_version,
            "rubric_version": self.rubric_version,
            "dimensions": {item.name: item.as_payload() for item in self.dimensions},
            "hard_gates": self.hard_gates.as_payload(),
            "notes": list(self.notes),
        }


def evaluate_run(run_path: Path) -> ScoreReport:
    metadata = _load_json_object(run_path / "metadata.json")
    patch_text = _read_text(run_path / "patch.diff")
    line_maps = load_line_map_records(run_path / "line_map.json")
    claims = _load_claim_records(run_path / "claims.jsonl")
    lesson_artifacts = _load_lesson_artifacts(run_path / "lesson")
    quiz_entries = _load_jsonl_objects(run_path / "quiz" / "quiz.jsonl", required=False)
    rubric = load_rubric()
    deterministic = build_deterministic_scores(
        rubric=rubric,
        metadata=metadata,
        patch_text=patch_text,
        claims=claims,
        line_maps=line_maps,
        lesson_artifacts=lesson_artifacts,
        quiz_entries=quiz_entries,
    )
    dimension_scores = deterministic.score_lookup()
    hard_gates = evaluate_hard_gates(
        rubric=rubric,
        dimension_scores=dimension_scores,
        claims=claims,
        secret_leak_detected=deterministic.secret_leak_detected,
        injection_unresolved=deterministic.injection_unresolved,
    )
    overall = round(sum(dimension_scores.values()), 2)
    verdict = _resolve_verdict(
        overall=overall,
        hard_gates=hard_gates,
        pass_threshold=rubric.pass_threshold,
        caution_threshold=rubric.caution_threshold,
        artifacts_complete=_has_complete_stage3_artifacts(
            lesson_artifacts=lesson_artifacts,
            quiz_entries=quiz_entries,
        ),
    )
    weakest_dim = _resolve_weakest_dimension(deterministic.dimensions)
    return ScoreReport(
        run_id=str(metadata["run_id"]),
        source_ref=str(metadata["source_ref"]),
        source_kind=str(metadata["source_kind"]),
        capability_level=int(metadata["capability_level"]),
        degraded_flags=_normalize_degraded_flags(metadata.get("degraded_flags")),
        overall=overall,
        verdict=verdict,
        weakest_dim=weakest_dim,
        eval_bundle_version=compute_runtime_eval_bundle_version(),
        rubric_version=rubric.rubric_version,
        dimensions=deterministic.dimensions,
        hard_gates=hard_gates,
        notes=deterministic.notes,
    )


def write_score_report(path: Path, report: ScoreReport, *, overwrite: bool = False) -> Path:
    if path.exists() and not overwrite:
        raise InputError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling_path(path)
    try:
        temp_path.write_text(
            json.dumps(report.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)
    return path


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(_read_text(path))
    if not isinstance(payload, dict):
        raise InputError(f"expected a JSON object in {path}")
    return cast("dict[str, Any]", payload)


def _read_text(path: Path) -> str:
    if not path.exists():
        raise InputError(f"required run artifact is missing: {path}")
    return path.read_text(encoding="utf-8")


def _load_claim_records(path: Path) -> tuple[ClaimRecord, ...]:
    claims: list[ClaimRecord] = []
    for index, line in enumerate(_read_text(path).splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            claims.append(ClaimRecord.model_validate_json(stripped))
        except Exception as exc:  # pragma: no cover - pydantic message already exercised
            raise InputError(f"invalid claims.jsonl line {index}: {path}") from exc
    if not claims:
        raise InputError(f"claims.jsonl did not contain any records: {path}")
    return tuple(claims)


def _load_lesson_artifacts(lesson_dir: Path) -> dict[str, str]:
    lesson_files = {
        "full": lesson_dir / "lesson.full.md",
        "hint": lesson_dir / "lesson.hint.md",
        "compact": lesson_dir / "lesson.compact.md",
    }
    return {
        key: target.read_text(encoding="utf-8")
        for key, target in lesson_files.items()
        if target.exists()
    }


def _load_jsonl_objects(path: Path, *, required: bool) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        if required:
            raise InputError(f"required run artifact is missing: {path}")
        return ()
    payloads: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise InputError(f"expected a JSON object on line {index}: {path}")
        payloads.append(cast("dict[str, Any]", payload))
    return tuple(payloads)


def _resolve_verdict(
    *,
    overall: float,
    hard_gates: HardGateSummary,
    pass_threshold: float,
    caution_threshold: float,
    artifacts_complete: bool,
) -> str:
    if not hard_gates.passed:
        return "FAIL"
    if overall >= pass_threshold:
        if not artifacts_complete:
            return "CAUTION"
        return "PASS"
    if overall >= caution_threshold:
        return "CAUTION"
    return "FAIL"


def _has_complete_stage3_artifacts(
    *,
    lesson_artifacts: dict[str, str],
    quiz_entries: tuple[dict[str, Any], ...],
) -> bool:
    required_lesson_variants = {"full", "hint", "compact"}
    return required_lesson_variants.issubset(lesson_artifacts) and bool(quiz_entries)


def _resolve_weakest_dimension(dimensions: tuple[DimensionScore, ...]) -> str:
    weakest = min(
        dimensions,
        key=lambda item: (
            item.score / item.max_score if item.max_score else 0.0,
            item.score,
            item.name,
        ),
    )
    return weakest.name


def _normalize_degraded_flags(raw_value: object) -> dict[str, bool]:
    if not isinstance(raw_value, dict):
        return {}
    raw_mapping = cast("dict[object, object]", raw_value)
    return {str(key): bool(value) for key, value in raw_mapping.items()}


def _temporary_sibling_path(path: Path) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".score.tmp",
        dir=path.parent,
    )
    os.close(fd)
    temp_path = Path(raw_path)
    temp_path.unlink()
    return temp_path


__all__ = ["ScoreReport", "evaluate_run", "write_score_report"]
