"""DTOs for search, graph status, learn submit, and task runtime endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SearchResultItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_table: str
    primary_key: str
    snippet: str
    rank: float


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[SearchResultItem]


class GraphStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    source_exists: bool
    has_graph: bool
    freshness: str | None
    node_count: int
    edge_count: int
    source_path: str | None


class TaskProgressResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current: int
    total: int
    message: str


class TaskInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    task_type: str
    status: str
    progress: TaskProgressResponse
    result: Any = None
    error: str | None = None
    error_code: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    elapsed_seconds: float | None = None


class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: list[TaskInfoResponse]


class TaskSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str


class TaskCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cancelled: bool


__all__ = [
    "GraphStatusResponse",
    "SearchResponse",
    "SearchResultItem",
    "TaskCancelResponse",
    "TaskInfoResponse",
    "TaskListResponse",
    "TaskProgressResponse",
    "TaskSubmitResponse",
]
