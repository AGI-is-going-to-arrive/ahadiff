"""DTOs for search, graph status, learn submit, and task runtime endpoints."""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator

FreshnessProjection = Literal["fresh", "stale", "unavailable", "disabled"]
TaskErrorCode = Literal[
    "network_error",
    "timeout",
    "config_error",
    "permission_error",
    "claim_error",
    "lesson_error",
    "quiz_error",
    "learnability_error",
    "cancelled",
    "internal_error",
]
RecoveryHint = Literal["retry", "check_config", "check_permissions", "dismiss", "none"]
GRAPH_EDGE_WEIGHT_MIN = 0.1
GRAPH_EDGE_WEIGHT_MAX = 3.0
NonNegativeCount: TypeAlias = Annotated[StrictInt, Field(ge=0)]
FiniteNumber: TypeAlias = Annotated[StrictFloat, Field(allow_inf_nan=False)]
NonNegativeFiniteNumber: TypeAlias = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
GraphEdgeWeight: TypeAlias = Annotated[
    StrictFloat,
    Field(ge=GRAPH_EDGE_WEIGHT_MIN, le=GRAPH_EDGE_WEIGHT_MAX, allow_inf_nan=False),
]


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


class GraphProvenance(BaseModel):
    """Provenance metadata for the imported Graphify artifact."""

    model_config = ConfigDict(extra="forbid")
    graph_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    import_time: str = Field(min_length=1, max_length=64)
    parser_version: str = Field(min_length=1, max_length=64)


class GraphStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    source_exists: bool
    has_graph: bool
    freshness: FreshnessProjection | None
    node_count: NonNegativeCount
    edge_count: NonNegativeCount
    source_path: str | None
    provenance: GraphProvenance | None = None


class WeakConceptItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_id: str = Field(min_length=1)
    concept: str
    stability: FiniteNumber
    difficulty: FiniteNumber
    scaffolding_level: str
    display_path: str


class WeakConceptsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concepts: list[WeakConceptItem]
    new_concepts: list[WeakConceptItem] = Field(default_factory=lambda: [])


class WatchStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    running: bool
    last_trigger_time: float | None = Field(default=None, allow_inf_nan=False)
    pending_changes: NonNegativeCount
    restartable: bool
    stop_timed_out: bool
    consecutive_failures: NonNegativeCount
    total_triggers: NonNegativeCount
    total_failures: NonNegativeCount
    last_error: str | None
    failure_threshold_hit: bool


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
    weight: GraphEdgeWeight = 1.0


class ConceptGraphResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: GraphStatusResponse
    nodes: list[ConceptGraphNode]
    edges: list[ConceptGraphEdge]
    truncated: bool = False


class TaskProgressResponse(BaseModel):
    """Progress snapshot for a running task."""

    model_config = ConfigDict(extra="forbid")
    current: NonNegativeCount = Field(description="Steps completed so far.")
    total: NonNegativeCount = Field(description="Total steps expected (0 if unknown).")
    message: str = Field(description="Human-readable progress message.")
    step_started_at: str = Field(
        default="",
        description="ISO-8601 timestamp when this step started.",
    )


class TaskResultSummary(BaseModel):
    """Stable subset of a learn task result exposed to public consumers.

    Fields here are considered part of the public contract.  Internal
    details (thread refs, raw result dict) are never surfaced.
    """

    model_config = ConfigDict(extra="forbid")
    run_id: str | None = Field(default=None, description="Run ID produced by learn, if any.")
    status: str | None = Field(default=None, description="Pipeline outcome status string.")
    overall: float | None = Field(
        default=None,
        ge=0,
        le=100,
        allow_inf_nan=False,
        description="Overall score (0-100).",
    )
    verdict: str | None = Field(default=None, description="Evaluation verdict.")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings.")


class TaskInfoResponse(BaseModel):
    """Public task information.

    **Stable fields** (will not change shape across minor versions):
    ``task_id``, ``task_type``, ``status``, ``progress``, ``error``,
    ``error_code``, ``recovery_hint``, ``created_at``, ``started_at``,
    ``completed_at``, ``elapsed_seconds``, ``timeout_seconds``,
    ``deadline_at``, ``result_summary``.

    Raw task results are intentionally omitted; consumers should use
    ``result_summary`` instead.
    """

    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, description="Unique task identifier.")
    task_type: str = Field(description="Task kind (e.g. 'learn').")
    status: str = Field(description="One of: pending, running, completed, failed, cancelled.")
    progress: TaskProgressResponse = Field(description="Current progress snapshot.")
    result_summary: TaskResultSummary | None = Field(
        default=None,
        description="Stable result summary for completed tasks.",
    )
    error: str | None = Field(default=None, description="Error message on failure.")
    error_code: TaskErrorCode | None = Field(
        default=None,
        description="Categorized error code (e.g. 'timeout', 'config_error').",
    )
    created_at: str = Field(description="ISO-8601 creation timestamp.")
    started_at: str | None = Field(default=None, description="ISO-8601 start timestamp.")
    completed_at: str | None = Field(default=None, description="ISO-8601 completion timestamp.")
    elapsed_seconds: NonNegativeFiniteNumber | None = Field(
        default=None,
        description="Wall-clock seconds from start to completion/now.",
    )
    timeout_seconds: float | None = None
    deadline_at: str | None = None
    recovery_hint: RecoveryHint | None = Field(
        default=None,
        description="Suggested recovery action on failure.",
    )

    @field_validator("timeout_seconds")
    @classmethod
    def _validate_timeout_seconds(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or value <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        return value


class TaskProgressEvent(BaseModel):
    """SSE progress event payload.

    Sent as ``event: progress`` on the ``/api/tasks/{id}/progress`` SSE
    stream.  Terminal states (completed/failed/cancelled) close the
    stream after the final event.

    Cancel semantics: when a task is cancelled while draining (thread-
    backed work still running after timeout), the SSE stream emits a
    final event with ``status='failed'`` and ``error_code='timeout'``;
    if the background thread completes successfully the status is later
    corrected to ``completed``, but the SSE stream will already have
    closed.
    """

    model_config = ConfigDict(extra="forbid")
    event: Literal["progress", "error"] = Field(description="SSE event type.")
    data: TaskInfoResponse | dict[str, str] = Field(
        description="TaskInfoResponse for progress events, error dict for error events.",
    )


class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: list[TaskInfoResponse]


class TaskSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, description="ID of the submitted task.")


class TaskCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cancelled: bool = Field(description="True if the task was successfully cancelled.")


__all__ = [
    "ConceptGraphEdge",
    "ConceptGraphNode",
    "ConceptGraphResponse",
    "ConceptsTextPageResponse",
    "GRAPH_EDGE_WEIGHT_MAX",
    "GRAPH_EDGE_WEIGHT_MIN",
    "GraphProvenance",
    "GraphStatusResponse",
    "RecoveryHint",
    "SearchResponse",
    "SearchResultItem",
    "TaskCancelResponse",
    "TaskErrorCode",
    "TaskInfoResponse",
    "TaskListResponse",
    "TaskProgressEvent",
    "TaskProgressResponse",
    "TaskResultSummary",
    "TaskSubmitResponse",
    "WatchStatusResponse",
    "WeakConceptItem",
    "WeakConceptsResponse",
]
