"""DTOs for stats, heatmap, providers, and serve-status endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HeatmapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str  # YYYY-MM-DD
    review_count: int
    avg_rating: float | None


class StatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_runs: int
    total_lessons: int
    total_quizzes: int
    total_concepts: int
    total_claims: int
    total_reviews: int
    avg_overall_score: float | None
    weakest_dimensions: list[str]
    last_run_at: str | None


class ReviewHeatmapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[HeatmapEntry]


class ProviderSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str
    role: str | None = None
    provider_class: str
    provider_kind: str
    model_name: str
    base_url: str
    api_key_env: str | None = None
    key_status: Literal["configured", "missing", "unknown"]
    api_family: str | None = None
    api_family_version: str | None = None
    probed: bool
    probed_max_context: int | None
    probed_tpm: int | None = None
    probed_rpm: int | None = None
    supports_temperature: bool | None = None
    probe_timestamp: str | None = None


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providers: list[ProviderSummary]


class UsageModelSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_class: str
    model_id: str
    call_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


class UsageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: list[UsageModelSummary]
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    cache_hits: int
    cache_misses: int


class ServeStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    uptime_seconds: float
    review_db_exists: bool
    runs_count: int


class HelpfulnessAggregateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_kind: str
    target_id: str
    signal_count: int
    positive_count: int
    negative_count: int
    helpfulness_score: float


class TransferConceptDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept: str
    total_reviews: int
    avg_rating: float
    improving: bool


class LearningEffectivenessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_concepts_reviewed: int
    concepts_improving: int
    concepts_stable: int
    concepts_declining: int
    transfer_rate: float
    helpfulness: list[HelpfulnessAggregateDTO]
    transfer_metrics: list[TransferConceptDTO]


__all__ = [
    "HeatmapEntry",
    "HelpfulnessAggregateDTO",
    "LearningEffectivenessResponse",
    "ProvidersResponse",
    "ProviderSummary",
    "ReviewHeatmapResponse",
    "ServeStatusResponse",
    "StatsResponse",
    "TransferConceptDTO",
    "UsageModelSummary",
    "UsageResponse",
]
