from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .event_log import RunStatus, Verdict
from .run_source import DegradedFlag, SourceKind

ReviewAnswer = Literal["good", "hard", "wrong"]
GraphifyMode = Literal["full", "learning_only", "empty"]


class AuthTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    expires_at: Optional[str] = None


class LocaleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: Literal["en", "zh-CN"]


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    source_ref: str
    source_kind: SourceKind
    verdict: Verdict
    overall: float
    status: RunStatus
    weakest_dim: str
    created_at: str
    degraded_flags: dict[DegradedFlag, bool] = Field(default_factory=dict)


class RunDetail(RunSummary):
    model_config = ConfigDict(extra="forbid")

    base_ref: Optional[str] = None
    prompt_version: str
    eval_bundle_version: str
    note_json: Optional[str] = None
    artifacts: list[str] = Field(default_factory=list)
    graphify_mode: Optional[GraphifyMode] = None
    graphify_status: Optional[str] = None


class RunArtifactEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    artifact_type: str
    content: str


class RatchetHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    source_ref: str
    eval_bundle_version: str
    overall: float
    verdict: Verdict
    status: RunStatus
    timestamp: str
    weakest_dim: str


class SetLocaleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lang: Literal["en", "zh-CN"]


class LearningSignalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str


class MarkWrongRequest(LearningSignalRequest):
    claim_id: str
    reason: Optional[str] = None


class ReviewSignalRequest(LearningSignalRequest):
    card_id: str
    answer: ReviewAnswer


class HelpfulnessRequest(LearningSignalRequest):
    target_kind: Literal["file"] = "file"
    target_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AuthTokenResponse",
    "GraphifyMode",
    "HelpfulnessRequest",
    "LearningSignalRequest",
    "LocaleResponse",
    "MarkWrongRequest",
    "RatchetHistoryEntry",
    "ReviewAnswer",
    "ReviewSignalRequest",
    "RunArtifactEnvelope",
    "RunDetail",
    "RunSummary",
    "SetLocaleRequest",
]
