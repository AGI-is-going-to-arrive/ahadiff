from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt

from . import run_source as run_source_contract

ProviderClass: TypeAlias = run_source_contract.ProviderClass
RunStatus: TypeAlias = Literal[
    "baseline",
    "keep",
    "discard",
    "crash",
    "targeted_verify",
    "keep_final",
    "phase25_rewrite",
    "non_ratcheted",
]
Verdict: TypeAlias = Literal["PASS", "CAUTION", "FAIL"]
EventType: TypeAlias = str
CostConfidence: TypeAlias = Literal["high", "medium", "low"]

TERMINAL_RUN_STATUSES = frozenset(
    {"baseline", "keep", "discard", "crash", "keep_final", "non_ratcheted"}
)
RATCHET_COUNTED_STATUSES = frozenset({"baseline", "keep", "keep_final"})


class ResultEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    event_type: EventType
    timestamp: str
    source_ref: str
    base_ref: str | None = None
    prompt_version: str
    eval_bundle_version: str
    rubric_version: str | None = None
    overall: StrictFloat
    verdict: Verdict
    status: RunStatus
    weakest_dim: str
    note_json: str | None = None


class UsageEvent(BaseModel):
    """Reserved v0.2 schema imported from Stage 0."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    repo_id: str
    provider_class: ProviderClass
    model_id: str
    input_tokens: StrictInt
    output_tokens: StrictInt
    cost_usd: StrictFloat | None = None
    pricing_version: str | None = None
    cost_confidence: CostConfidence = "medium"
    billing_mode: str
    execution_origin: str
    api_principal_hash: str
    timestamp: str


__all__ = [
    "EventType",
    "RunStatus",
    "TERMINAL_RUN_STATUSES",
    "RATCHET_COUNTED_STATUSES",
    "ResultEvent",
    "Verdict",
    "CostConfidence",
    "UsageEvent",
]
