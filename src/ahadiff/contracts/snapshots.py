"""Versioned, sanitized local comparison baselines and their API payloads."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .run_source import COMPARE_FILE_MAX_BYTES, CompareFileInput

SNAPSHOT_MAX_COUNT = 100
SNAPSHOT_MAX_BYTES = 16 * 1024 * 1024
SNAPSHOT_ID_PATTERN = r"^snap_[0-9a-f]{32}$"
SNAPSHOT_HASH_PATTERN = r"^[0-9a-f]{64}$"
SnapshotHashScope = Literal["sanitized_utf8_nfc_lf"]


def validate_snapshot_name(value: str) -> str:
    """Validate a display name without echoing untrusted input in errors."""
    if not 1 <= len(value) <= 80:
        raise ValueError("snapshot name must contain 1 to 80 characters")
    CompareFileInput(name=value, content="")
    return value


class SnapshotSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    snapshot_id: str = Field(pattern=SNAPSHOT_ID_PATTERN)
    status: Literal["ready", "corrupt", "unsupported"]
    stored_bytes: int = Field(ge=0)
    record_hash: str | None = Field(default=None, pattern=SNAPSHOT_HASH_PATTERN)
    schema_version: int | None = None
    name: str | None = None
    file_name: str | None = None
    content_hash: str | None = Field(default=None, pattern=SNAPSHOT_HASH_PATTERN)
    hash_scope: SnapshotHashScope = "sanitized_utf8_nfc_lf"
    created_at: str | None = None
    size_bytes: int | None = Field(default=None, ge=0, le=COMPARE_FILE_MAX_BYTES)
    source: Literal["explicit_file"] = "explicit_file"
    sanitized: bool | None = None


class SnapshotRecord(BaseModel):
    """The hash covers sanitized text, never the original file or a backup."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    schema_version: Literal[1] = 1
    snapshot_id: str = Field(pattern=SNAPSHOT_ID_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    file_name: str = Field(min_length=1, max_length=255)
    content: str = Field(repr=False)
    content_hash: str = Field(pattern=SNAPSHOT_HASH_PATTERN)
    hash_scope: SnapshotHashScope = "sanitized_utf8_nfc_lf"
    created_at: str
    size_bytes: int = Field(ge=0, le=COMPARE_FILE_MAX_BYTES)
    source: Literal["explicit_file"] = "explicit_file"
    sanitized: bool

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_snapshot_name(value)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
            raise ValueError("snapshot creation time must be a UTC timestamp")
        datetime.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        CompareFileInput(name=self.file_name, content=self.content)
        for text in (self.name, self.file_name, self.content):
            if unicodedata.normalize("NFC", text) != text or "\r" in text:
                raise ValueError("snapshot text must be normalized")
        raw = self.content.encode("utf-8")
        if len(raw) != self.size_bytes or hashlib.sha256(raw).hexdigest() != self.content_hash:
            raise ValueError("snapshot content integrity check failed")
        return self

    def to_summary(
        self, *, stored_bytes: int | None = None, record_hash: str | None = None
    ) -> SnapshotSummary:
        """Use actual bytes on reads; newly saved records use canonical JSON."""
        encoded = self.model_dump_json().encode("utf-8") + b"\n"
        return SnapshotSummary.model_validate(
            {
                **self.model_dump(exclude={"content"}),
                "status": "ready",
                "stored_bytes": len(encoded) if stored_bytes is None else stored_bytes,
                "record_hash": hashlib.sha256(encoded).hexdigest()
                if record_hash is None
                else record_hash,
            }
        )


class SnapshotSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=80)
    file: CompareFileInput = Field(repr=False)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_snapshot_name(value)


class SnapshotDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    expected_hash: str = Field(pattern=SNAPSHOT_HASH_PATTERN)


class SnapshotListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    snapshots: list[SnapshotSummary]
    max_count: int = SNAPSHOT_MAX_COUNT
    max_bytes: int = SNAPSHOT_MAX_BYTES


class SnapshotDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    snapshot_id: str = Field(pattern=SNAPSHOT_ID_PATTERN)
    deleted: Literal[True] = True


__all__ = [
    "SNAPSHOT_HASH_PATTERN",
    "SNAPSHOT_ID_PATTERN",
    "SNAPSHOT_MAX_BYTES",
    "SNAPSHOT_MAX_COUNT",
    "SnapshotDeleteRequest",
    "SnapshotDeleteResponse",
    "SnapshotListResponse",
    "SnapshotRecord",
    "SnapshotSaveRequest",
    "SnapshotSummary",
    "validate_snapshot_name",
]
