"""DTOs for serve audit log endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    page: int
    has_more: bool
    next_cursor: str | None = None
    fields: list[str] | None = None


__all__ = ["AuditLogResponse"]
