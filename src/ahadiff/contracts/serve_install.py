"""DTOs for serve install target endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InstallManifestActionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(min_length=1)
    file_strategy: Literal["generated", "user-managed"]
    path: str = Field(min_length=1)


class InstallManifestSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview: list[InstallManifestActionSummary]
    write: list[InstallManifestActionSummary]
    uninstall: list[InstallManifestActionSummary]


class InstallTargetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    detected: bool
    platform_supported: bool
    status: Literal["installed", "available", "unsupported", "error"]
    description: str
    install_command: str = Field(min_length=1)
    uninstall_command: str = Field(min_length=1)
    manifest: InstallManifestSummary | None = None
    manifest_hash: str | None = Field(default=None, min_length=64, max_length=64)
    manifest_error: str | None = None
    error_message: str | None = None


class InstallTargetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: list[InstallTargetSummary]
    total: int


class InstallPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    force: bool = False
    layer2: bool = False


class InstallMutationRequest(InstallPreviewRequest):
    confirmed_manifest_hash: str = Field(min_length=64, max_length=64)


class InstallTargetPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: InstallTargetSummary
    manifest_hash: str = Field(min_length=64, max_length=64)


class InstallTargetMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: InstallTargetSummary
    operation: Literal["install", "uninstall"]
    updated: bool
    updated_paths: list[str]
    manifest_hash: str = Field(min_length=64, max_length=64)


__all__ = [
    "InstallManifestActionSummary",
    "InstallManifestSummary",
    "InstallMutationRequest",
    "InstallPreviewRequest",
    "InstallTargetSummary",
    "InstallTargetMutationResponse",
    "InstallTargetPreviewResponse",
    "InstallTargetsResponse",
]
