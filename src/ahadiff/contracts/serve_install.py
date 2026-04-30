"""DTOs for serve install target endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InstallTargetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    detected: bool
    platform_supported: bool
    status: Literal["installed", "available", "unsupported", "error"]
    description: str
    error_message: str | None = None


class InstallTargetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: list[InstallTargetSummary]
    total: int


__all__ = ["InstallTargetSummary", "InstallTargetsResponse"]
