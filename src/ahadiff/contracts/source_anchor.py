"""Portable evidence identities for sanitized, persisted source text."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

AnchorSourceKind = Literal["diff", "document"]
AnchorFormat = Literal["markdown", "notebook", "json", "toml", "yaml", "text"]
AnchorSide = Literal["old", "new", "document"]
AssertionKind = Literal["source_fact", "semantic", "runtime_effect"]


class AnchorLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: Literal["heading", "paragraph", "cell", "key_path", "line"]
    heading_path: list[str] = Field(default_factory=list, max_length=32)
    paragraph_index: StrictInt | None = Field(default=None, ge=0)
    cell_index: StrictInt | None = Field(default=None, ge=0)
    cell_id: str | None = Field(default=None, max_length=160)
    key_path: list[str | StrictInt] = Field(
        default_factory=lambda: list[str | int](), max_length=48
    )
    fallback_reason: str | None = Field(default=None, max_length=120)

    @field_validator("heading_path", "key_path")
    @classmethod
    def validate_path_parts(cls, value: list[str | int]) -> list[str | int]:
        if any(isinstance(part, str) and len(part) > 512 for part in value):
            raise ValueError("source locator part exceeds 512 characters")
        for part in value:
            if isinstance(part, str):
                try:
                    part.encode("utf-8")
                except UnicodeEncodeError:
                    raise ValueError("source locator part must be valid Unicode") from None
        return value


class SourceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    schema_version: Literal[1] = 1
    source_kind: AnchorSourceKind
    format: AnchorFormat
    side: AnchorSide
    file: str = Field(min_length=1, max_length=1024)
    anchor_id: str = Field(pattern=r"^anchor_[0-9a-f]{32}$")
    locator: AnchorLocator
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    start: StrictInt = Field(ge=1)
    end: StrictInt = Field(ge=1)
    quote: str = Field(max_length=2048)

    @model_validator(mode="after")
    def validate_source(self) -> SourceAnchor:
        if self.end < self.start or self.end - self.start >= 120:
            raise ValueError("source anchor must have a bounded positive line range")
        if (self.source_kind == "document") != (self.side == "document"):
            raise ValueError("source kind and side do not agree")
        return self


class EvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    file: str
    side: AnchorSide
    format: AnchorFormat
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceAnchorIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, populate_by_name=True)

    schema_name: Literal["ahadiff.evidence_anchors"] = Field(
        default="ahadiff.evidence_anchors", alias="schema"
    )
    schema_version: Literal[1] = 1
    source_kind: AnchorSourceKind
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=20)
    anchors: list[SourceAnchor] = Field(
        default_factory=lambda: list[SourceAnchor](), max_length=4096
    )
    sources: list[EvidenceSource] = Field(
        default_factory=lambda: list[EvidenceSource](), max_length=1000
    )


class ReviewContextArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    schema_version: Literal[1] = 1
    kind: Literal["auxiliary_untrusted"] = "auxiliary_untrusted"
    content: str = Field(repr=False)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    sanitized: bool


__all__ = [
    "AnchorFormat",
    "AnchorLocator",
    "AnchorSide",
    "AnchorSourceKind",
    "AssertionKind",
    "EvidenceAnchorIndex",
    "EvidenceSource",
    "ReviewContextArtifact",
    "SourceAnchor",
]
