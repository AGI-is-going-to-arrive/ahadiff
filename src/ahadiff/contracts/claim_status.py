from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

ClaimStatus = Literal["verified", "weak", "not_proven", "contradicted", "rejected"]
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
ClaimExtractor = Literal["python_ast", "regex", "section_header"]
ChangeKind = Literal["deleted", "renamed"]


class SourceHunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    start: StrictInt
    end: StrictInt

    @model_validator(mode="after")
    def validate_range(self) -> SourceHunk:
        if self.end < self.start:
            raise ValueError("source hunk end must be >= start")
        return self


class ReviewCard(BaseModel):
    """Task 10 card contract frozen in Stage 0."""

    model_config = ConfigDict(extra="forbid")

    card_id: str
    concept: str
    run_id: str
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

    @field_validator("fsrs_state")
    @classmethod
    def validate_fsrs_state_json(cls, value: str) -> str:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("fsrs_state must be a JSON object string")
        return value


class ClaimRecord(BaseModel):
    """Stage 0 minimal importable claim schema."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    run_id: str
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
