"""DTOs for stats, heatmap, providers, and serve-status endpoints."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt

NonNegativeCount: TypeAlias = Annotated[StrictInt, Field(ge=0)]
FiniteNumber: TypeAlias = Annotated[StrictFloat, Field(allow_inf_nan=False)]
NonNegativeFiniteNumber: TypeAlias = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]


class HeatmapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str  # YYYY-MM-DD
    review_count: NonNegativeCount
    avg_rating: FiniteNumber | None


class StatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_runs: NonNegativeCount
    total_lessons: NonNegativeCount
    total_quizzes: NonNegativeCount
    total_concepts: NonNegativeCount
    total_claims: NonNegativeCount
    total_reviews: NonNegativeCount
    avg_overall_score: FiniteNumber | None
    weakest_dimensions: list[str]
    last_run_at: str | None


class ReviewHeatmapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[HeatmapEntry]


class ProviderSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str
    scope: Literal["repo", "global"] = "repo"
    overrides_global: bool | None = None
    role: str | None = None
    provider_class: str
    provider_kind: str
    model_name: str
    base_url: str
    api_key_env: str | None = None
    key_status: Literal["configured", "missing", "unknown"]
    api_family: str | None = None
    api_family_version: str | None = None
    max_output_tokens: int | None = None
    thinking_level: str | None = None
    probed: bool
    probed_max_context: int | None
    probed_max_input_tokens: int | None = None
    probed_max_output_tokens: int | None = None
    probed_limits_source: str | None = None
    model_limits_name: str | None = None
    probed_tpm: int | None = None
    probed_rpm: int | None = None
    probe_timestamp: str | None = None
    available_models: list[str] = Field(default_factory=list)


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providers: list[ProviderSummary]


class UsageModelSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_class: str
    model_id: str
    call_count: NonNegativeCount
    total_input_tokens: NonNegativeCount
    total_output_tokens: NonNegativeCount
    total_cost_usd: NonNegativeFiniteNumber


class UsageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: list[UsageModelSummary]
    total_calls: NonNegativeCount
    total_input_tokens: NonNegativeCount
    total_output_tokens: NonNegativeCount
    total_cost_usd: NonNegativeFiniteNumber
    cache_hits: NonNegativeCount
    cache_misses: NonNegativeCount


class ServeStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    uptime_seconds: NonNegativeFiniteNumber
    review_db_exists: bool
    runs_count: NonNegativeCount


class HelpfulnessAggregateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_kind: str
    target_id: str
    signal_count: NonNegativeCount
    positive_count: NonNegativeCount
    negative_count: NonNegativeCount
    helpfulness_score: FiniteNumber


class TransferConceptDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept: str
    total_reviews: NonNegativeCount
    avg_rating: FiniteNumber
    improving: bool


class LearningEffectivenessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_concepts_reviewed: NonNegativeCount
    concepts_improving: NonNegativeCount
    concepts_stable: NonNegativeCount
    concepts_declining: NonNegativeCount
    transfer_rate: FiniteNumber
    helpfulness: list[HelpfulnessAggregateDTO]
    transfer_metrics: list[TransferConceptDTO]


class SpecAlignmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alignment_score: FiniteNumber | None
    total_evaluated: NonNegativeCount
    recent_trend: Literal["improving", "stable", "declining"] | None
    total_requirements: NonNegativeCount = 0
    implemented: NonNegativeCount = 0
    partial: NonNegativeCount = 0
    missing: NonNegativeCount = 0
    unknown: NonNegativeCount = 0
    degraded_count: NonNegativeCount = 0
    semantic_reviewed: NonNegativeCount = 0
    semantic_degraded_count: NonNegativeCount = 0
    semantic_disagreement_count: NonNegativeCount = 0


__all__ = [
    "HeatmapEntry",
    "HelpfulnessAggregateDTO",
    "LearningEffectivenessResponse",
    "ProvidersResponse",
    "ProviderSummary",
    "ReviewHeatmapResponse",
    "ServeStatusResponse",
    "SpecAlignmentResponse",
    "StatsResponse",
    "TransferConceptDTO",
    "UsageModelSummary",
    "UsageResponse",
]
