from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConceptLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term_key: str = Field(min_length=1)
    concept: str = Field(min_length=1)
    display_name: str = ""
    related_claims: list[str] = Field(default_factory=list)
    file_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    updated_by_runs: list[str] = Field(default_factory=list)
    health_status: (
        Literal[
            "healthy",
            "orphan",
            "stale",
            "contradicted",
            "dismissed",
        ]
        | None
    ) = None


class ConceptLedgerPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[ConceptLedgerEntry]
    next_cursor: str | None = None
    total_count: int = 0
