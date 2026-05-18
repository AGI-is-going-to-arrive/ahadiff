from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from ahadiff.contracts.quiz_choice import AnswerMode, QuizChoice  # noqa: TC001

ReviewAnswer = Literal["easy", "good", "hard", "wrong"]
CardQueueAction = Literal["archive", "suspend"]


@dataclass(frozen=True)
class DueReviewCard:
    card_id: str
    concept: str
    run_id: str
    due_date: str
    scaffolding_level: str
    display_path: str
    stability: float | None = None
    difficulty: float | None = None
    reps: int = 0
    lapses: int = 0
    last_rating: int | None = None
    source_ref: str | None = None
    symbol: str | None = None
    question: str | None = None
    answer: str | None = None
    answer_mode: AnswerMode = "open"
    choices: tuple[QuizChoice, ...] | None = None


@dataclass(frozen=True)
class ReviewUpdate:
    card_id: str
    rating: int
    due_date: str
    fsrs_state: str
    stability: float
    difficulty: float
    card_state: str
    scaffolding_level: str


@dataclass(frozen=True)
class ReviewDbCheck:
    schema_version: int
    quick_check: str
    foreign_key_issues: int
    event_count: int
    card_count: int
    event_id_unique: bool


def normalize_due_card_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return normalized if math.isfinite(normalized) and normalized >= 0 else None


def normalize_due_card_count(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(normalized) or normalized < 0 or not normalized.is_integer():
        return 0
    return int(normalized)


def normalize_due_card_last_rating(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(normalized) or not normalized.is_integer():
        return None
    rating = int(normalized)
    return rating if 1 <= rating <= 4 else None


__all__ = [
    "CardQueueAction",
    "DueReviewCard",
    "normalize_due_card_count",
    "normalize_due_card_float",
    "normalize_due_card_last_rating",
    "ReviewAnswer",
    "ReviewDbCheck",
    "ReviewUpdate",
]
