"""DTOs for search, graph status, learn submit, and task runtime endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FreshnessProjection = Literal["fresh", "stale", "unavailable", "disabled"]


class SearchResultItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_table: str
    primary_key: str
    snippet: str
    rank: float
    href: str | None = None


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[SearchResultItem]
    next_cursor: str | None = None


class ConceptsTextPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_type: Literal["concepts"]
    content: str
    next_cursor: str | None = None


class GraphStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    source_exists: bool
    has_graph: bool
    freshness: FreshnessProjection | None
    node_count: int
    edge_count: int
    source_path: str | None


class WeakConceptItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_id: str = Field(min_length=1)
    concept: str
    stability: float
    difficulty: float
    scaffolding_level: str
    display_path: str


class WeakConceptsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concepts: list[WeakConceptItem]


class ConceptGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str | None = None
    file_path: str | None = None
    freshness: FreshnessProjection | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConceptGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation: str | None = None
    weight: float = 1.0


class ConceptGraphResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: GraphStatusResponse
    nodes: list[ConceptGraphNode]
    edges: list[ConceptGraphEdge]
    truncated: bool = False


class TaskProgressResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current: int
    total: int
    message: str


class TaskInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1)
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
    task_id: str = Field(min_length=1)


class TaskCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cancelled: bool


__all__ = [
    "ConceptGraphEdge",
    "ConceptGraphNode",
    "ConceptGraphResponse",
    "ConceptsTextPageResponse",
    "GraphStatusResponse",
    "SearchResponse",
    "SearchResultItem",
    "TaskCancelResponse",
    "TaskInfoResponse",
    "TaskListResponse",
    "TaskProgressResponse",
    "TaskSubmitResponse",
    "WeakConceptItem",
    "WeakConceptsResponse",
]
