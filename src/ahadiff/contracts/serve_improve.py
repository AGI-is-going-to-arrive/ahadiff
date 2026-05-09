"""DTOs for GET /api/improve/preflight (read-only).

Every nested model declares ``extra="forbid"`` so a typo or an unexpected field
fails fast at serialization time. The endpoint never returns absolute paths so
the schema intentionally has no path-shaped fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ImprovePreflightResponse",
    "ImproveRepoState",
    "ImproveRunSnapshot",
    "ImproveSessionSummary",
]


class ImproveRunSnapshot(BaseModel):
    """Compact view of an immutable result_event row used to seed an improve session."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    source_ref: str = ""
    overall: float = 0.0
    weakest_dim: str | None = None
    finalized: bool = False


class ImproveSessionSummary(BaseModel):
    """A single ``.ahadiff/improve/<session>.json`` summary, scrubbed of paths."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    rounds_completed: int = Field(ge=0, default=0)
    last_status: str | None = None
    phase25_attempted: bool = False
    has_pending_worktree: bool = False
    interrupted_round: int | None = None
    interrupted_stage: str | None = None
    updated_at: str = ""


class ImproveRepoState(BaseModel):
    """Read-only snapshot of repo-level git state needed for the preflight UI."""

    model_config = ConfigDict(extra="forbid")

    branch: str | None = None
    head_sha: str | None = None
    prompts_dirty: bool = False


class ImprovePreflightResponse(BaseModel):
    """Top-level response for GET /api/improve/preflight."""

    model_config = ConfigDict(extra="forbid")

    available: bool = False
    reason: str | None = None
    anchor_run: ImproveRunSnapshot | None = None
    baseline_run: ImproveRunSnapshot | None = None
    target_dimension: str | None = None
    target_prompt_file: str | None = None
    mutable_prompts: list[str] = Field(default_factory=list)
    phase25_eligible: bool = False
    phase25_trigger_reason: str | None = None
    existing_sessions: list[ImproveSessionSummary] = Field(default_factory=lambda: [])
    repo_state: ImproveRepoState = Field(default_factory=ImproveRepoState)
    provider_configured: bool = False
