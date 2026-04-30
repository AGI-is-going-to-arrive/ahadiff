"""DTOs for serve doctor endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DoctorCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    category: str
    status: Literal["pass", "warn", "fail"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DoctorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary_status: Literal["pass", "warn", "fail"]
    checks: list[DoctorCheck]


__all__ = ["DoctorCheck", "DoctorResponse"]
