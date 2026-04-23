from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ClaimCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    run_id: str
    text: str
    source_hunks: list[Any]
    symbols: list[str] = Field(default_factory=list)
    hunk_ids: list[str] = Field(default_factory=list)
    extractor: str | None = None

    @model_validator(mode="after")
    def validate_text_and_hunks(self) -> ClaimCandidate:
        self.text = self.text.strip()
        if not self.text:
            raise ValueError("claim text must not be empty")
        if not self.source_hunks:
            raise ValueError("claim candidate requires at least one source_hunk")
        return self

    @field_validator("source_hunks", mode="before")
    @classmethod
    def normalize_source_hunks(cls, values: list[Any]) -> list[Any]:
        from ahadiff.contracts import SourceHunk

        return [
            item if isinstance(item, SourceHunk) else SourceHunk.model_validate(item)
            for item in values
        ]

    @field_validator("symbols", "hunk_ids")
    @classmethod
    def normalize_string_list(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("extractor")
    @classmethod
    def validate_extractor(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in {"python_ast", "regex", "section_header"}:
            raise ValueError("extractor must be python_ast, regex, or section_header")
        return value


class NegativeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    detail: str
    path: str | None = None

    def render(self) -> str:
        if self.path is None:
            return f"{self.code}:{self.detail}"
        return f"{self.code}:{self.path}:{self.detail}"


def _empty_negative_evidence() -> list[NegativeEvidence]:
    return cast("list[NegativeEvidence]", [])


class VerifiedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: Any
    matched_hunk_ids: list[str] = Field(default_factory=list)
    matched_symbols: list[str] = Field(default_factory=list)
    negative_evidence: list[NegativeEvidence] = Field(default_factory=_empty_negative_evidence)

    @field_validator("record", mode="before")
    @classmethod
    def normalize_record(cls, value: Any) -> Any:
        from ahadiff.contracts import ClaimRecord

        if isinstance(value, ClaimRecord):
            return value
        return ClaimRecord.model_validate(value)


__all__ = ["ClaimCandidate", "NegativeEvidence", "VerifiedClaim"]
