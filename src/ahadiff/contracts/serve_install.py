"""DTOs for serve install target endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PlatformNotes = dict[Literal["windows", "macos", "linux"], str]


def _empty_platform_notes() -> PlatformNotes:
    return {}


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


class ToolUsageHint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_category: Literal["cli", "ide", "ci"]
    invocation_pattern: str = Field(min_length=1)
    quick_start_steps: list[str] = Field(min_length=1, max_length=5)
    example_prompts: list[str] = Field(default_factory=list, max_length=5)
    expected_behavior: str = Field(min_length=1)
    platform_notes: PlatformNotes = Field(default_factory=_empty_platform_notes)


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
    usage_hint: ToolUsageHint | None = None


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
    "ToolUsageHint",
]
