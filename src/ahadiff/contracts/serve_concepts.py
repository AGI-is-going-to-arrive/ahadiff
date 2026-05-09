from __future__ import annotations

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


class ConceptLedgerPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[ConceptLedgerEntry]
    next_cursor: str | None = None
    total_count: int = 0
