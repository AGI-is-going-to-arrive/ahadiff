"""DTOs for stats, heatmap, providers, and serve-status endpoints."""

from __future__ import annotations

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
    provider_class: str
    model_name: str
    base_url: str
    probed: bool
    probed_max_context: int | None


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providers: list[ProviderSummary]


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
]
