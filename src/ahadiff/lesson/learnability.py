from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ahadiff.contracts import LearnabilityWeights
from ahadiff.git.parser import ChangedFileRecord, parse_unified_diff

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


_HIGH_SIGNAL_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".go",
        ".h",
        ".hpp",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".mjs",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".scala",
        ".sh",
        ".sql",
        ".swift",
        ".ts",
        ".tsx",
        ".zsh",
    }
)
_LOW_SIGNAL_FILENAMES = frozenset(
    {
        "bun.lockb",
        "cargo.lock",
        "go.sum",
        "package-lock.json",
        "pnpm-lock.yaml",
        "poetry.lock",
        "uv.lock",
        "yarn.lock",
    }
)
_LOW_SIGNAL_SUFFIXES = (
    ".d.ts",
    ".min.css",
    ".min.js",
    ".pb.go",
)
_STRUCTURAL_TOKENS = (
    "class ",
    "const ",
    "def ",
    "enum ",
    "except ",
    "finally:",
    "for ",
    "function ",
    "if ",
    "import ",
    "interface ",
    "match ",
    "return ",
    "switch ",
    "try:",
    "type ",
    "while ",
)
_VERSION_BUMP_TOKENS = ("version", "dependencies", "lockfileVersion", "resolved", "integrity")


@dataclass(frozen=True)
class LearnabilityFactors:
    complexity: float
    novelty: float
    pattern: float

    def as_dict(self) -> dict[str, float]:
        return {
            "complexity": round(self.complexity, 4),
            "novelty": round(self.novelty, 4),
            "pattern": round(self.pattern, 4),
        }


@dataclass(frozen=True)
class LearnabilityAssessment:
    score: float
    threshold: float
    skip_lesson_quiz: bool
    forced: bool
    factors: LearnabilityFactors
    reasons: tuple[str, ...]
    weights: LearnabilityWeights

    def as_metadata(self) -> dict[str, object]:
        return {
            "score": round(self.score, 4),
            "threshold": round(self.threshold, 4),
            "skip_lesson_quiz": self.skip_lesson_quiz,
            "forced": self.forced,
            "factors": self.factors.as_dict(),
            "weights": self.weights.model_dump(mode="json"),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class _FileSignal:
    path: str
    learning_weight: float
    changed_nonblank_lines: int
    structural_hits: int


def compute_learnability_score(
    parsed_diff: str | Iterable[ChangedFileRecord],
    *,
    weights: LearnabilityWeights | None = None,
) -> float:
    return assess_learnability(parsed_diff, weights=weights).score


def assess_learnability(
    parsed_diff: str | Iterable[ChangedFileRecord],
    *,
    threshold: float = 0.3,
    weights: LearnabilityWeights | None = None,
    force_learn: bool = False,
) -> LearnabilityAssessment:
    records = (
        parse_unified_diff(parsed_diff) if isinstance(parsed_diff, str) else tuple(parsed_diff)
    )
    resolved_weights = weights or LearnabilityWeights()
    signals = tuple(_file_signal(record) for record in records)
    factors = _compute_factors(signals)
    score = (
        factors.complexity * resolved_weights.complexity
        + factors.novelty * resolved_weights.novelty
        + factors.pattern * resolved_weights.pattern
    )
    reasons = _build_reasons(signals, factors)
    skip_lesson_quiz = score < threshold and not force_learn
    return LearnabilityAssessment(
        score=round(min(max(score, 0.0), 1.0), 4),
        threshold=threshold,
        skip_lesson_quiz=skip_lesson_quiz,
        forced=force_learn,
        factors=factors,
        reasons=reasons,
        weights=resolved_weights,
    )


def _compute_factors(signals: Sequence[_FileSignal]) -> LearnabilityFactors:
    complexity = _complexity_factor(signals)
    novelty = _novelty_factor(signals)
    pattern = _pattern_factor(signals)
    return LearnabilityFactors(
        complexity=round(complexity, 4),
        novelty=round(novelty, 4),
        pattern=round(pattern, 4),
    )


def _complexity_factor(signals: Sequence[_FileSignal]) -> float:
    weighted_lines = sum(
        signal.learning_weight * signal.changed_nonblank_lines for signal in signals
    )
    weighted_hunks = sum(
        signal.learning_weight for signal in signals if signal.changed_nonblank_lines
    )
    structural_bonus = 0.25 if any(signal.structural_hits for signal in signals) else 0.0
    return min(
        1.0,
        0.55 * min(weighted_lines / 16.0, 1.0)
        + 0.2 * min(weighted_hunks / 3.0, 1.0)
        + structural_bonus,
    )


def _novelty_factor(signals: Sequence[_FileSignal]) -> float:
    if not signals:
        return 0.0
    if all(signal.learning_weight <= 0.1 for signal in signals):
        return 0.05
    if sum(1 for signal in signals if signal.learning_weight >= 0.8) >= 2:
        return 0.65
    if any(signal.structural_hits >= 2 for signal in signals):
        return 0.55
    if any(signal.learning_weight >= 0.8 for signal in signals):
        return 0.25
    return 0.2


def _pattern_factor(signals: Sequence[_FileSignal]) -> float:
    if not signals:
        return 0.0
    if all(signal.changed_nonblank_lines == 0 for signal in signals):
        return 0.0
    if all(signal.learning_weight <= 0.1 for signal in signals):
        return 0.05
    if any(signal.structural_hits for signal in signals):
        return 0.85
    if sum(signal.changed_nonblank_lines for signal in signals) <= 2:
        return 0.15
    return 0.22


def _build_reasons(
    signals: Sequence[_FileSignal],
    factors: LearnabilityFactors,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not signals:
        return ("empty_diff",)
    if all(signal.learning_weight <= 0.1 for signal in signals):
        reasons.append("low_signal_file_types")
    if sum(signal.changed_nonblank_lines for signal in signals) <= 2 and factors.pattern < 0.2:
        reasons.append("small_non_structural_change")
    if any(signal.structural_hits for signal in signals):
        reasons.append("logic_structure_detected")
    if not reasons:
        reasons.append("mixed_change_pattern")
    return tuple(reasons)


def _file_signal(record: ChangedFileRecord) -> _FileSignal:
    path = record.display_path
    learning_weight = _file_learning_weight(path)
    changed_nonblank_lines = 0
    structural_hits = 0
    for hunk in record.hunks:
        if hunk.section_header:
            structural_hits += 1
        for line in hunk.lines:
            if line.kind not in {"add", "delete"}:
                continue
            content = line.content.strip()
            if not content:
                continue
            changed_nonblank_lines += 1
            lowered = content.casefold()
            if any(token in lowered for token in _STRUCTURAL_TOKENS):
                structural_hits += 1
            elif _looks_like_version_or_lock_entry(lowered) and learning_weight <= 0.1:
                continue
    return _FileSignal(
        path=path,
        learning_weight=learning_weight,
        changed_nonblank_lines=changed_nonblank_lines,
        structural_hits=structural_hits,
    )


def _file_learning_weight(path: str) -> float:
    name = Path(path).name
    if name in _LOW_SIGNAL_FILENAMES or any(
        name.endswith(suffix) for suffix in _LOW_SIGNAL_SUFFIXES
    ):
        return 0.05
    extension = Path(path).suffix.casefold()
    if extension in _HIGH_SIGNAL_EXTENSIONS:
        return 1.0
    if extension in {".json", ".md", ".toml", ".yaml", ".yml"}:
        return 0.35
    return 0.25


def _looks_like_version_or_lock_entry(content: str) -> bool:
    return any(token.casefold() in content for token in _VERSION_BUMP_TOKENS)
