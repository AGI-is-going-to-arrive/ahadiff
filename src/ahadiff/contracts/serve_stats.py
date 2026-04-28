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


__all__ = [
    "HeatmapEntry",
    "ProvidersResponse",
    "ProviderSummary",
    "ReviewHeatmapResponse",
    "ServeStatusResponse",
    "StatsResponse",
]
