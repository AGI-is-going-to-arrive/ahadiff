from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.core.paths import path_identity_key
from ahadiff.safety.injection import protect_untrusted_text
from ahadiff.safety.redact import redaction_pipeline

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ahadiff.contracts import ClaimRecord
    from ahadiff.git.line_map import FileLineMap, HunkLineMap

    from .rubric import RubricDefinition


@dataclass(frozen=True)
class DimensionScore:
    name: str
    score: float
    max_score: float
    reason: str

    def as_payload(self) -> dict[str, object]:
        return {
            "score": round(self.score, 2),
            "max_score": round(self.max_score, 2),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DeterministicScoreResult:
    dimensions: tuple[DimensionScore, ...]
    notes: tuple[str, ...]
    secret_leak_detected: bool
    injection_unresolved: bool

    def as_payload(self) -> dict[str, dict[str, object]]:
        return {item.name: item.as_payload() for item in self.dimensions}

    def score_lookup(self) -> dict[str, float]:
        return {item.name: item.score for item in self.dimensions}


def build_deterministic_scores(
    *,
    rubric: RubricDefinition,
    metadata: Mapping[str, Any],
    patch_text: str,
    claims: Sequence[ClaimRecord],
    line_maps: Sequence[FileLineMap],
    lesson_artifacts: Mapping[str, str],
    quiz_entries: Sequence[Mapping[str, Any]],
) -> DeterministicScoreResult:
    notes: list[str] = []
    learnability_score = _metadata_learnability_score(metadata, notes)
    quiz_score, quiz_reason = _quiz_transfer_score(quiz_entries)
    conciseness_score, conciseness_reason = _conciseness_score(lesson_artifacts)
    spec_score, spec_reason = _spec_alignment_score(metadata)
    coverage_score, coverage_reason = _diff_coverage_score(claims, line_maps)
    accuracy_score, accuracy_reason = _claim_weighted_score(
        claims,
        weights={
            "verified": 1.0,
            "weak": 0.75,
            "not_proven": 0.45,
            "contradicted": 0.0,
            "rejected": 0.0,
        },
        dimension_max=rubric.dimension("accuracy").max_score,
        empty_reason="no verified claims artifact",
        success_reason="claim status mix",
    )
    evidence_score, evidence_reason = _claim_weighted_score(
        claims,
        weights={
            "verified": 1.0,
            "weak": 0.8,
            "not_proven": 0.5,
            "contradicted": 0.25,
            "rejected": 0.0,
        },
        dimension_max=rubric.dimension("evidence").max_score,
        empty_reason="no verified claims artifact",
        success_reason="claim evidence coverage",
        hunk_bonus=_source_hunk_bonus(claims),
    )
    safety_score, secret_leak_detected, injection_unresolved = _safety_privacy_score(
        patch_text,
        rubric.dimension("safety_privacy").max_score,
    )
    if not lesson_artifacts:
        notes.append("lesson artifacts are missing; conciseness scored as zero")
    if not quiz_entries:
        notes.append("quiz artifacts are missing; quiz_transfer scored as zero")

    dimensions = (
        DimensionScore(
            name="accuracy",
            score=accuracy_score,
            max_score=rubric.dimension("accuracy").max_score,
            reason=accuracy_reason,
        ),
        DimensionScore(
            name="evidence",
            score=evidence_score,
            max_score=rubric.dimension("evidence").max_score,
            reason=evidence_reason,
        ),
        DimensionScore(
            name="diff_coverage",
            score=coverage_score,
            max_score=rubric.dimension("diff_coverage").max_score,
            reason=coverage_reason,
        ),
        DimensionScore(
            name="learnability",
            score=learnability_score * rubric.dimension("learnability").max_score,
            max_score=rubric.dimension("learnability").max_score,
            reason="capture metadata learnability score",
        ),
        DimensionScore(
            name="quiz_transfer",
            score=quiz_score,
            max_score=rubric.dimension("quiz_transfer").max_score,
            reason=quiz_reason,
        ),
        DimensionScore(
            name="spec_alignment",
            score=spec_score,
            max_score=rubric.dimension("spec_alignment").max_score,
            reason=spec_reason,
        ),
        DimensionScore(
            name="conciseness",
            score=conciseness_score,
            max_score=rubric.dimension("conciseness").max_score,
            reason=conciseness_reason,
        ),
        DimensionScore(
            name="safety_privacy",
            score=safety_score,
            max_score=rubric.dimension("safety_privacy").max_score,
            reason="persisted patch passes secret and injection re-checks",
        ),
    )
    return DeterministicScoreResult(
        dimensions=dimensions,
        notes=tuple(notes),
        secret_leak_detected=secret_leak_detected,
        injection_unresolved=injection_unresolved,
    )


def _metadata_learnability_score(metadata: Mapping[str, Any], notes: list[str]) -> float:
    learnability = metadata.get("learnability")
    if not isinstance(learnability, dict):
        notes.append("metadata.learnability is missing; learnability dimension scored as zero")
        return 0.0
    learnability_map = cast("dict[str, object]", learnability)
    raw_score = learnability_map.get("score")
    if not isinstance(raw_score, int | float):
        notes.append(
            "metadata.learnability.score is missing; learnability dimension scored as zero"
        )
        return 0.0
    return max(0.0, min(float(raw_score), 1.0))


def _quiz_transfer_score(
    quiz_entries: Sequence[Mapping[str, Any]],
) -> tuple[float, str]:
    if not quiz_entries:
        return 0.0, "quiz.jsonl is missing"
    count_ratio = min(len(quiz_entries) / 3.0, 1.0)
    claim_ratio = _field_presence_ratio(quiz_entries, ("source_claims", "claim_ids", "claims"))
    evidence_ratio = _field_presence_ratio(
        quiz_entries,
        ("evidence", "file_line_evidence", "source_hunks"),
    )
    concept_ratio = _field_presence_ratio(quiz_entries, ("concepts", "concept_ids"))
    composite_ratio = (
        0.5 * count_ratio
        + 0.25 * claim_ratio
        + 0.25
        * max(
            evidence_ratio,
            concept_ratio,
        )
    )
    return round(10.0 * composite_ratio, 2), "quiz artifact count and anchor richness"


def _conciseness_score(
    lesson_artifacts: Mapping[str, str],
) -> tuple[float, str]:
    if not lesson_artifacts:
        return 0.0, "lesson artifacts are missing"
    presence_ratio = len(lesson_artifacts) / 3.0
    compact_words = _word_count(lesson_artifacts.get("compact", ""))
    full_words = _word_count(lesson_artifacts.get("full", ""))
    compact_ratio = 0.0
    if compact_words:
        compact_ratio = 1.0 if compact_words <= 500 else max(0.2, 500.0 / compact_words)
    full_ratio = 0.0
    if full_words:
        full_ratio = 1.0 if full_words <= 1400 else max(0.25, 1400.0 / full_words)
    combined = min(1.0, 0.4 * presence_ratio + 0.35 * compact_ratio + 0.25 * full_ratio)
    return round(8.0 * combined, 2), "lesson artifact presence and length budgets"


def _spec_alignment_score(
    metadata: Mapping[str, Any],
) -> tuple[float, str]:
    source_detail = metadata.get("source_detail")
    if isinstance(source_detail, dict) and any(
        key in source_detail for key in ("against_spec", "spec_path", "spec_ref")
    ):
        return 6.0, "spec reference present but deterministic scorer is neutral"
    return 10.0, "no spec constraint attached to this run"


def _diff_coverage_score(
    claims: Sequence[ClaimRecord],
    line_maps: Sequence[FileLineMap],
) -> tuple[float, str]:
    total_files = len(line_maps)
    total_hunks = sum(len(item.hunks) for item in line_maps)
    if total_files == 0:
        return 0.0, "line_map.json contains no files"
    covered_files: set[str] = set()
    covered_hunks: set[str] = set()
    file_lookup = {path_identity_key(Path(item.display_path)): item for item in line_maps}
    for claim in claims:
        for source_hunk in claim.source_hunks:
            file_map = file_lookup.get(path_identity_key(Path(source_hunk.file)))
            if file_map is None:
                continue
            covered_files.add(file_map.file_id)
            for hunk in file_map.hunks:
                if _hunk_matches_source_hunk(
                    hunk,
                    source_hunk.start,
                    source_hunk.end,
                    source_hunk.side,
                ):
                    covered_hunks.add(hunk.hunk_id)
    file_ratio = len(covered_files) / total_files
    hunk_ratio = 0.0 if total_hunks == 0 else len(covered_hunks) / total_hunks
    combined = 0.6 * file_ratio + 0.4 * hunk_ratio
    return round(14.0 * combined, 2), "claim anchors cover files and hunks from line_map.json"


def _claim_weighted_score(
    claims: Sequence[ClaimRecord],
    *,
    weights: Mapping[str, float],
    dimension_max: float,
    empty_reason: str,
    success_reason: str,
    hunk_bonus: float = 1.0,
) -> tuple[float, str]:
    if not claims:
        return 0.0, empty_reason
    weighted_total = sum(weights[claim.status] for claim in claims)
    ratio = weighted_total / len(claims)
    ratio = min(1.0, ratio * hunk_bonus)
    return round(dimension_max * ratio, 2), success_reason


def _source_hunk_bonus(claims: Sequence[ClaimRecord]) -> float:
    if not claims:
        return 1.0
    total_source_hunks = sum(len(claim.source_hunks) for claim in claims)
    return min(1.0, 0.8 + min(total_source_hunks / max(len(claims), 1), 2.0) * 0.1)


def _safety_privacy_score(
    patch_text: str,
    max_score: float,
) -> tuple[float, bool, bool]:
    secret_recheck = redaction_pipeline(patch_text)
    injection_recheck = protect_untrusted_text(patch_text)
    secret_leak_detected = bool(secret_recheck.findings)
    injection_unresolved = bool(injection_recheck.findings)
    if secret_leak_detected or injection_unresolved:
        return 0.0, secret_leak_detected, injection_unresolved
    return max_score, False, False


def _field_presence_ratio(
    entries: Sequence[Mapping[str, Any]],
    field_names: tuple[str, ...],
) -> float:
    if not entries:
        return 0.0
    hits = 0
    for entry in entries:
        if any(_has_non_empty_field(entry, field_name) for field_name in field_names):
            hits += 1
    return hits / len(entries)


def _has_non_empty_field(entry: Mapping[str, Any], field_name: str) -> bool:
    value = entry.get(field_name)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return len(cast("list[object]", value)) > 0
    if isinstance(value, tuple):
        return len(cast("tuple[object, ...]", value)) > 0
    if isinstance(value, dict):
        return len(cast("dict[object, object]", value)) > 0
    return value is not None


def _word_count(text: str) -> int:
    return len([token for token in text.split() if token])


def _hunk_matches_source_hunk(
    hunk: HunkLineMap,
    start: int,
    end: int,
    side: str,
) -> bool:
    if side in {"new", "either"} and _ranges_overlap(start, end, hunk.new_start, hunk.new_end):
        return True
    return side in {"old", "either"} and _ranges_overlap(start, end, hunk.old_start, hunk.old_end)


def _ranges_overlap(start: int, end: int, other_start: int, other_end: int) -> bool:
    return max(start, other_start) <= min(end, other_end)


__all__ = ["DeterministicScoreResult", "DimensionScore", "build_deterministic_scores"]
