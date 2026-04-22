from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from . import event_log as event_log_contract
from . import run_source as run_source_contract

DegradedFlag: TypeAlias = run_source_contract.DegradedFlag
DegradedFlagsMap: TypeAlias = run_source_contract.DegradedFlagsMap
SourceKind: TypeAlias = run_source_contract.SourceKind
RunStatus: TypeAlias = event_log_contract.RunStatus
Verdict: TypeAlias = event_log_contract.Verdict

ReviewAnswer = Literal["good", "hard", "wrong"]
GraphifyMode = Literal["full", "learning_only", "empty"]


class AuthTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    expires_at: str | None = None


class LocaleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: Literal["en", "zh-CN"]


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    source_ref: str
    source_kind: SourceKind
    capability_level: Literal[1, 2, 3]
    verdict: Verdict
    overall: float
    status: RunStatus
    weakest_dim: str
    created_at: str
    degraded_flags: DegradedFlagsMap = Field(
        default_factory=run_source_contract.empty_degraded_flags
    )


class RunDetail(RunSummary):
    model_config = ConfigDict(extra="forbid")

    base_ref: str | None = None
    prompt_version: str
    eval_bundle_version: str
    note_json: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    graphify_mode: GraphifyMode | None = None
    graphify_status: str | None = None


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
    reason: str | None = None


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
