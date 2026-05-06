from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from ahadiff.contracts.quiz_choice import (  # noqa: TC001
    AnswerMode,
    QuizChoice,
    validate_quiz_choices,
)
from ahadiff.core.json_util import safe_json_loads

ClaimStatus = Literal["verified", "weak", "not_proven", "contradicted", "rejected"]
SourceHunkSide = Literal["old", "new", "either"]
RejectReasonCode = Literal[
    "file_not_in_patch",
    "line_outside_hunk",
    "symbol_not_found",
    "hunk_id_mismatch",
    "evidence_missing",
]
CardState = Literal["active", "stale", "archived", "suspended"]
StaleReason = Literal["file_deleted", "symbol_removed", "line_drifted", "staleness_unknown"]
ScaffoldingLevel = Literal["full", "hint", "compact"]
ClaimConfidence = Literal["high", "medium", "low"]
ClaimExtractor = Literal["python_ast", "tree_sitter", "regex", "section_header"]
ChangeKind = Literal["deleted", "renamed"]


class SourceHunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    start: StrictInt
    end: StrictInt
    side: SourceHunkSide = "either"
    file_id: str | None = None
    display_path: str | None = None
    hunk_id: str | None = None
    hunk_hash: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> SourceHunk:
        if self.start < 1 or self.end < 1:
            raise ValueError("source hunk start and end must be positive")
        if self.end < self.start:
            raise ValueError("source hunk end must be >= start")
        return self


class ReviewCard(BaseModel):
    """Task 10 card contract frozen in Stage 0."""

    model_config = ConfigDict(extra="forbid")

    card_id: str = Field(min_length=1)
    concept: str
    run_id: str = Field(min_length=1)
    source_ref: str
    fsrs_state: str
    scaffolding_level: ScaffoldingLevel = "full"
    last_rating: int | None = None
    card_state: CardState = "active"
    stale_reason: StaleReason | None = None
    peeked_this_session: bool = Field(default=False, exclude=True)
    file_id: str
    display_path: str
    hunk_id: str
    hunk_hash: str
    symbol: str | None = None
    change_kind: ChangeKind | None = None
    question: str | None = None
    answer: str | None = None
    answer_mode: AnswerMode = "open"
    choices: list[QuizChoice] | None = None

    @field_validator("fsrs_state")
    @classmethod
    def validate_fsrs_state_json(cls, value: str) -> str:
        parsed = safe_json_loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("fsrs_state must be a JSON object string")
        return value

    @field_validator("last_rating")
    @classmethod
    def validate_last_rating(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 1 or value > 4:
            raise ValueError("last_rating must be between 1 and 4")
        return value

    @model_validator(mode="after")
    def validate_stale_contract(self) -> ReviewCard:
        if self.card_state == "stale" and self.stale_reason is None:
            raise ValueError("stale cards require stale_reason")
        if self.card_state != "stale" and self.stale_reason is not None:
            raise ValueError("stale_reason is only allowed when card_state is stale")
        return self

    @model_validator(mode="after")
    def validate_choice_contract(self) -> ReviewCard:
        if self.answer_mode == "open":
            if self.choices is not None:
                raise ValueError("open review cards must not include choices")
            return self
        if self.answer is None or not self.answer.strip():
            raise ValueError("multiple_choice review cards require a non-empty answer")
        if self.choices is None:
            raise ValueError("multiple_choice review cards must include choices")
        self.choices = list(validate_quiz_choices(self.choices, expected_answer=self.answer))
        return self


class ClaimRecord(BaseModel):
    """Stage 0 minimal importable claim schema."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    text: str
    status: ClaimStatus
    reason_code: RejectReasonCode | None = None
    confidence: ClaimConfidence = "medium"
    source_hunks: list[SourceHunk]
    symbols: list[str] = Field(default_factory=list)
    negative_evidence: list[str] = Field(default_factory=list)
    extractor: ClaimExtractor | None = None

    @model_validator(mode="after")
    def validate_reason_code_contract(self) -> ClaimRecord:
        if self.status == "rejected" and self.reason_code is None:
            raise ValueError("rejected claims require reason_code")
        if self.status != "rejected" and self.reason_code is not None:
            raise ValueError("reason_code is only allowed for rejected claims")
        return self


__all__ = [
    "ClaimStatus",
    "SourceHunkSide",
    "RejectReasonCode",
    "CardState",
    "StaleReason",
    "ScaffoldingLevel",
    "ClaimConfidence",
    "ClaimExtractor",
    "ChangeKind",
    "SourceHunk",
    "ReviewCard",
    "ClaimRecord",
]
