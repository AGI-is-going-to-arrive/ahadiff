# RFC-001: v1.0 Contract Extension

**Status**: APPROVED — R1 adversarial (2H+3M) + R2 cross-review (2 residuals) + R3 final check (1 residual) = all fixed
**Date**: 2026-04-28
**Revised**: 2026-04-30 (current-branch sync: tree-sitter symbol extraction / graph status / timeout model / verification refreshed)
**Authors**: Claude (orchestrator)
**Requires**: contract-freeze.md §8 change rules (RFC + cross-review)

Current branch verification after the latest learn-orchestrator / symbol-extraction updates: full pytest `1479 passed, 1 skipped`; coverage gate `87.08%`; `ruff check` pass; `ruff format --check` pass; `pyright` currently reports `0 errors, 0 warnings, 0 informations`; `uv build --wheel` pass.

## Motivation

v1.0 execution plan requires 15 new serve endpoints (#23-#37), expanded helpfulness
semantics, a new misconception-card DTO, and a formal note on Graphify's dependency
posture. All four changes must be ratified via contract-freeze §8 before implementation
in Phases 1E, 3A-3D, 3C, 5F, and 6B.

## Current State

Current `serve/app.py` registers 45 explicit `Route(...)` entries: 1 `/healthz`, 43 concrete
`/api/*` routes, and 1 `/api/{rest_of_path:path}` catchall. DTOs are frozen across
`contracts/serve_app.py`, `contracts/serve_runtime.py`, `contracts/serve_stats.py`,
`contracts/serve_audit.py`, `contracts/serve_doctor.py`, `contracts/serve_install.py`,
and `contracts/claim_status.py`.

---

## (a) Serve Endpoint Expansion: #23-#37

### Numbering Convention

Endpoints #1-#13: original contract-freeze.
Endpoints #14-#22: v0.2 additions (review/queue, review/rate, config, doctor,
install/targets, signals/mark-wrong, signals/quiz-answer, signals/srs-review,
signals/helpfulness).
Endpoints #23-#37: v1.0 additions below.

### Phase 1E — Simple APIs

| # | Method | Path | Auth | Response DTO | Impl Phase |
|---|--------|------|------|-------------|------------|
| 23 | GET | `/api/stats` | token | `StatsResponse` | 1E |
| 24 | GET | `/api/review/heatmap` | token | `ReviewHeatmapResponse` | 1E |
| 25 | GET | `/api/export/results` | token | streaming TSV (`text/tab-separated-values`) | 1E |
| 26 | GET | `/api/providers` | token | `ProvidersResponse` | 1E |
| 27 | GET | `/api/serve/status` | none | `ServeStatusResponse` | 1E |

### Phase 3D — Medium APIs

| # | Method | Path | Auth | Response DTO | Impl Phase |
|---|--------|------|------|-------------|------------|
| 28 | GET | `/api/concepts/weak` | token | `WeakConceptsResponse` | 3D |
| 29 | GET | `/api/usage` | token | `UsageResponse` | 3D |
| 30 | GET | `/api/audit` | token | `AuditLogResponse` | 3D |
| 31 | GET | `/api/search` | token | `SearchResponse` | 3D |
| 32 | GET | `/api/review/mastery` | token | `MasteryResponse` | 3D |
| 33 | GET | `/api/spec/alignment` | token | `SpecAlignmentResponse` | 3D |
| 34 | PUT | `/api/config` | token | `ConfigResponse` | 3D |

### Phase 3C + 5F + 6B — Infrastructure APIs

| # | Method | Path | Auth | Response DTO | Impl Phase |
|---|--------|------|------|-------------|------------|
| 35 | GET | `/api/tasks/{task_id}/progress` | token | SSE stream (`text/event-stream`) | 3C |
| 36 | GET | `/api/graph/status` | token | `GraphStatusResponse` | 5F |
| 37 | POST | `/api/learn` | token | `202 {"task_id": string}` | 6B |
| 38 | GET | `/api/graph/concepts` | token | `ConceptGraphResponse` | 5D prerequisite |

**Note on #37 (`POST /api/learn`)**: The current branch now lands this endpoint.
It triggers the background learn pipeline via the concrete `core/orchestrator.py`
implementation, returns `202 {"task_id": ...}`, and reuses `/api/tasks/{task_id}`
plus `/api/tasks/{task_id}/progress` for polling / SSE progress. The HTTP request
surface intentionally stays narrow: only safe learn capture / option fields are
accepted at the route layer, while provider override fields are not exposed over HTTP.

### New Response DTOs

All DTOs use Pydantic `BaseModel` with `ConfigDict(extra="forbid")`, consistent with
existing frozen DTOs.

```python
# --- Phase 1E ---

class StatsResponse(BaseModel):
    """Aggregate statistics (CR-22 V1-V7)."""
    model_config = ConfigDict(extra="forbid")
    total_runs: int
    total_lessons: int
    total_quizzes: int
    total_concepts: int
    total_claims: int
    total_reviews: int
    avg_overall_score: float | None
    weakest_dimensions: list[str]
    last_run_at: str | None  # ISO 8601


class ReviewHeatmapResponse(BaseModel):
    """Calendar heatmap data for review activity."""
    model_config = ConfigDict(extra="forbid")
    entries: list[HeatmapEntry]

class HeatmapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str  # YYYY-MM-DD
    review_count: int
    avg_rating: float | None


class ProvidersResponse(BaseModel):
    """List of configured LLM providers."""
    model_config = ConfigDict(extra="forbid")
    providers: list[ProviderSummary]

class ProviderSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_class: str
    model_name: str
    base_url: str
    probed: bool
    probed_max_context: int | None


class ServeStatusResponse(BaseModel):
    """Health check + version info. No auth required."""
    model_config = ConfigDict(extra="forbid")
    version: str
    uptime_seconds: float
    repo_path: str
    review_db_exists: bool
    runs_count: int


# --- Phase 3D ---

class WeakConceptsResponse(BaseModel):
    """Bottom-N concepts by mastery score."""
    model_config = ConfigDict(extra="forbid")
    concepts: list[WeakConcept]

class WeakConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept: str
    mastery_score: float
    review_count: int
    last_reviewed_at: str | None


class UsageResponse(BaseModel):
    """LLM cost/usage aggregates."""
    model_config = ConfigDict(extra="forbid")
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    by_provider: list[ProviderUsage]

class ProviderUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_class: str
    model_name: str
    cost_usd: float
    call_count: int


class AuditLogResponse(BaseModel):
    """Paginated audit log entries."""
    model_config = ConfigDict(extra="forbid")
    entries: list[AuditEntry]
    has_more: bool
    cursor: str | None

class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: str
    event_type: str
    model_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    note: str | None


class SearchResponse(BaseModel):
    """FTS5 full-text search results (paginated)."""
    model_config = ConfigDict(extra="forbid")
    query: str
    results: list[SearchHit]
    total: int
    has_more: bool
    cursor: str | None

class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["lesson", "claim", "concept", "quiz"]
    run_id: str | None
    title: str
    snippet: str
    score: float


class MasteryResponse(BaseModel):
    """Review mastery metrics across concepts."""
    model_config = ConfigDict(extra="forbid")
    total_cards: int
    mastered_cards: int  # interval >= 21 days
    learning_cards: int
    new_cards: int
    avg_retention: float | None
    streak_days: int


class SpecAlignmentResponse(BaseModel):
    """How well lessons align with specs."""
    model_config = ConfigDict(extra="forbid")
    total_specs: int
    aligned_runs: int
    misaligned_runs: int
    alignment_ratio: float | None
    details: list[AlignmentDetail]

class AlignmentDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    spec_file: str | None
    aligned: bool
    note: str | None


class ConfigResponse(BaseModel):
    """Resolved configuration (read) or update result (write)."""
    model_config = ConfigDict(extra="forbid")
    resolved: dict[str, Any]
    source: Literal["repo", "global", "default"]


# --- Phase 3C ---

# SSE progress events use text/event-stream format:
# event: progress
# data: {"task_id": "...", "phase": "...", "progress": 0.42, "message": "..."}
#
# event: complete
# data: {"task_id": "...", "result": {...}}
#
# event: error
# data: {"task_id": "...", "error": "..."}
# No DTO — wire format is SSE with JSON data payloads.


# --- Phase 5F ---

class GraphStatusResponse(BaseModel):
    """Graphify graph.json freshness + statistics.

    ``freshness`` is a free-form string per contract-freeze §6 (Stage 0 does
    NOT freeze the 4 projection label literals).  Runtime values are expected
    to be one of "fresh"/"stale"/"unknown"/"missing", but the DTO does not
    enforce this via Literal — enforcement lives in the Graphify freshness
    module (Phase 3E).
    """
    model_config = ConfigDict(extra="forbid")
    detected: bool
    path: str | None
    node_count: int | None
    edge_count: int | None
    freshness: str
    last_imported_at: str | None
```

### New Request DTO (PUT /api/config)

```python
_WRITABLE_CONFIG_KEYS: frozenset[str] = frozenset({
    "llm.generate_model",
    "llm.judge_model",
    "llm.base_url",
    "privacy_mode",
    "learn.learnability_threshold",
    "locale",
})


class UpdateConfigRequest(BaseModel):
    """Partial config update.  ``key`` must be in the writable allowlist."""
    model_config = ConfigDict(extra="forbid")
    key: str
    value: Any

    @model_validator(mode="after")
    def validate_writable_key(self) -> UpdateConfigRequest:
        if self.key not in _WRITABLE_CONFIG_KEYS:
            raise ValueError(
                f"config key {self.key!r} is not in the writable allowlist"
            )
        return self
```

Only keys in `_WRITABLE_CONFIG_KEYS` can be modified via the API.  Credential keys
(`api_key_env`, secrets) are never writable via serve.  The allowlist can be expanded
in future RFCs.

### Query Parameters

| Endpoint | Query Params |
|----------|-------------|
| `/api/stats` | none |
| `/api/review/heatmap` | `?from=YYYY-MM-DD&to=YYYY-MM-DD` (optional, defaults to last 365 days; max span 730 days) |
| `/api/export/results` | `?format=tsv` (only tsv supported in v1.0) |
| `/api/providers` | none |
| `/api/serve/status` | none |
| `/api/concepts/weak` | `?limit=N` (default 10, max 100) |
| `/api/usage` | `?from=YYYY-MM-DD&to=YYYY-MM-DD` (optional; max span 730 days) |
| `/api/audit` | `?cursor=C&limit=N` (default 50, max 200) |
| `/api/search` | `?q=text&kind=lesson|claim|concept|quiz&limit=N&cursor=C` (q required; kind optional; limit default 20, max 100) |
| `/api/review/mastery` | none |
| `/api/spec/alignment` | `?run_id=R` (optional, defaults to all finalized runs) |
| `/api/config` | none |
| `/api/tasks/{task_id}/progress` | none (SSE stream) |
| `/api/graph/status` | none |

---

## (b) Section-Level Helpfulness Expansion

### Current Contract

```python
class HelpfulnessRequest(LearningSignalRequest):
    target_kind: Literal["file", "section"] = "file"
    target_id: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_section_target(self) -> HelpfulnessRequest:
        if self.target_kind == "section":
            if ":" not in self.target_id:
                raise ValueError("target_id must contain ':' when target_kind is 'section'")
            run_id, section_name = self.target_id.split(":", 1)
            run_id = run_id.strip()
            section_name = section_name.strip()
            if not run_id or not section_name:
                raise ValueError("target_id must have non-empty run_id and section_name")
            self.target_id = f"{run_id}:{section_name}"
        return self
```

### Final Decision

Keep a single `target_id` field and encode section scope as `{run_id}:{section_name}`.

- No separate `section_id` field was added
- Existing file-target payloads keep working unchanged
- Section payloads reuse the same `target_id` field and are normalized to canonical form after validation
- Fullwidth `：` is rejected; only ASCII `:` is accepted as the separator

### Aggregation Semantics

- `section` → `file` → `lesson`: helpfulness rolls up the chain
- Phase 3A implements section-level helpfulness aggregation
- Phase 3A also adds learning transfer validation (LS-6) and effectiveness metrics (LS-7)

### Backward Compatibility

- Default `target_kind="file"` preserves existing behavior
- Existing frontend `helpfulness` signal calls continue to work unchanged for file targets
- Section targets are backward-compatible on the wire because they reuse `target_id` instead of adding a new field

---

## (c) Misconception Card Data Model

### Decision

**Option 2: New `MisconceptionCard` DTO** (sibling to `ReviewCard`, NOT an extension).

Rationale:
1. Misconceptions have a distinct lifecycle (not spaced-repetition-driven)
2. Different verification criteria (correction accuracy vs. recall)
3. Different frontend display (correction comparison, not flashcard)
4. Adding fields to frozen `ReviewCard` risks breaking existing FSRS scheduling logic

### New DTO (in `contracts/claim_status.py`)

```python
MisconceptionSeverity = Literal["critical", "moderate", "minor"]
MisconceptionStatus = Literal["active", "resolved", "archived"]


class MisconceptionCard(BaseModel):
    """Safety-tagged concept identifying a common misunderstanding."""
    model_config = ConfigDict(extra="forbid")

    misconception_id: str
    concept: str
    misconception_text: str
    correction_text: str
    severity: MisconceptionSeverity
    source_claim_ids: list[str]
    run_id: str
    source_ref: str
    status: MisconceptionStatus = "active"
    created_at: str  # ISO 8601
    resolved_at: str | None = None
    evidence_hunks: list[SourceHunk] = Field(default_factory=list)
```

### Storage

Misconception cards are stored in `review.sqlite` in a new `misconception_cards` table
(schema version bump required, handled in Phase 3B migration).

### Serve Endpoints

No dedicated endpoint in v1.0. Misconception cards are returned as part of:
- `GET /api/run/{run_id}/quiz` response (embedded in quiz artifact)
- `GET /api/concepts/weak` response (if a weak concept has associated misconceptions)

Future v1.1 may add `GET /api/misconceptions` as a dedicated endpoint.

---

## (d) Graphify: Runtime-Only Dependency

### Confirmation

Graphify remains **runtime-detected only** in v1.0. Formally documented:

1. **No `[graph]` extras group** in `pyproject.toml`
2. **No import-time dependency** on graph parsing libraries
3. raw `graphify-out/graph.json` is detected at runtime, then imported/sanitized to `.ahadiff/graphify/graph.json`; current `/api/graph/status` counts and `source_path` use the imported copy
4. All Graphify Pydantic models live in `src/ahadiff/graphify/` (Phase 3E)
5. Parser uses `stdlib json` only — no NetworkX, no igraph, no additional deps
6. If `graph.json` is absent or malformed, all Graphify features degrade silently
7. CLI flags `--use-graphify` / `--no-graphify` control opt-in/opt-out at runtime

### Rationale

- Keeps `pip install ahadiff` lightweight (no C extensions, no graph deps)
- Graphify is a power-user feature; most users won't have `graphify-out/`
- Parser complexity is bounded (Pydantic validation + dict traversal)

---

## Impact Assessment

### Files Modified by This RFC

| File | Change | Phase |
|------|--------|-------|
| `doc/contract-freeze.md` | Add endpoints #23-#37 to §4.2; add new DTOs to §4.3 | 0G |
| `src/ahadiff/contracts/serve_app.py` | Add 15 new response DTOs + UpdateConfigRequest + export in `__all__` | 1E/3D/6B |
| `src/ahadiff/contracts/claim_status.py` | Add `MisconceptionCard` + `MisconceptionSeverity` + `MisconceptionStatus` | 3B |

### eval_bundle_version Impact

**None.** No evaluation semantics are changed by this RFC.

### Frontend Impact

New endpoints require frontend consumers in Phases 4A-4G. Gemini gate required per
contract-freeze §8 rule 3.

---

## Acceptance Criteria

1. All 15 new endpoint paths (#23-#37), methods, and auth requirements documented
2. All new DTOs defined with Pydantic `extra="forbid"` and type annotations
3. HelpfulnessRequest expansion is backward-compatible
4. MisconceptionCard is a separate DTO, not a ReviewCard extension
5. Graphify runtime-only posture formally documented
6. Codex + Claude cross-review PASS
7. No existing tests regress against the current backend baseline (`1479 passed, 1 skipped`)
