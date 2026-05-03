from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
    source_ref: str | None = None
    symbol: str | None = None
    question: str | None = None
    answer: str | None = None


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
    event_id_unique: bool


__all__ = [
    "CardQueueAction",
    "DueReviewCard",
    "ReviewAnswer",
    "ReviewDbCheck",
    "ReviewUpdate",
]
