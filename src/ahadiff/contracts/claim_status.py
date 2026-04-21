from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    peeked_this_session: bool = False
    file_id: str
    display_path: str
    hunk_id: str
    hunk_hash: str
    symbol: str | None = None
    change_kind: str | None = None


class ClaimRecord(BaseModel):
    """Stage 0 minimal importable claim schema."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    run_id: str
    text: str
    status: ClaimStatus
    reason_code: RejectReasonCode | None = None
    confidence: ClaimConfidence = "medium"
    source_hunks: list[dict[str, Any]]
    symbols: list[str] = Field(default_factory=list)
    negative_evidence: list[str] = Field(default_factory=list)
    extractor: ClaimExtractor | None = None


__all__ = [
    "ClaimStatus",
    "RejectReasonCode",
    "CardState",
    "StaleReason",
    "ScaffoldingLevel",
    "ClaimConfidence",
    "ClaimExtractor",
    "ReviewCard",
    "ClaimRecord",
]
