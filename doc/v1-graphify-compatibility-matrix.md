# Graphify v0.5.0 ↔ AhaDiff v0.2 Compatibility Matrix

> Research date: 2026-04-27 | Graphify commit: HEAD of `safishamsi/graphify` | AhaDiff audit target: working tree on top of `a3deaca` (2026-04-29)

> Current status note (2026-05-08): this document started as a 2026-04-27 compatibility baseline. The current branch now already has real `graph.json` parsing/validation, `links`/`edges` normalization, hyperedge handling, matcher/linker/slicer/search helpers, `/api/search` graph-node merge, `GET /api/graph/status`, and `GET /api/graph/concepts`. Serve-time consumers now read only the imported artifact `.ahadiff/graphify/graph.json`; raw `graphify-out/graph.json` remains an untrusted source used for detection/import/freshness only. The graph concepts endpoint gives the frontend sanitized nodes/edges. The current ConceptGraph UI has Graph / List views only: it does not use cluster/community grouping, keeps large graphs in List by default, still allows Full graph, and supports pan/zoom without hard viewport bounds. Graphify import provenance, per-run `graphify_context.json`, token-reduction metrics, and the release perf gate are wired. 5E is still partial because full source/provenance UI and real large-repo signoff evidence remain.

> Current status note (2026-05-15): the learn pipeline now has a narrow CLI bridge. Step 10 detects an external `graphify` executable, runs `graphify update <repo>`, then force-imports the refreshed `graphify-out/graph.json` before appending concepts. If the CLI is missing, AhaDiff keeps the older optional behavior of importing an existing `graphify-out/graph.json`; if the CLI exists but update fails or times out, it degrades silently and does not import a stale graph as if it were refreshed. Graphify source import now uses the parser's 50 MiB cap. This does not change the remaining evidence gap: there is still no real large-repo signoff fixture in this document.

## 1. Graphify Official Repo Summary

### Identity
- **Package**: `graphifyy` (PyPI name) v0.5.0
- **Python**: >=3.10, <3.14
- **Build**: setuptools
- **License**: see LICENSE file
- **Dependencies**: networkx, tree-sitter (20 language grammars), graspologic (optional, Leiden), faster-whisper (optional, transcription), anthropic (optional, semantic extraction)

### Architecture (4 passes)
1. **AST pass** (deterministic, no LLM): tree-sitter extracts structure from 20+ languages
2. **Transcription pass** (local): faster-whisper for video/audio files
3. **Semantic pass** (LLM): Claude subagents extract concepts/relationships from docs/papers/images/transcripts
4. **Merge + Cluster**: NetworkX graph, Leiden/Louvain community detection, export

### graph.json Schema (NetworkX JSON format)
```json
{
  "directed": false,
  "multigraph": false,
  "graph": {},
  "nodes": [
    {
      "label": "analyze.py",           // display name
      "file_type": "code",             // "code" | "doc" | "concept" | etc.
      "source_file": "path/to/file",   // relative path
      "source_location": "L6",         // line number
      "id": "analyze_node_community_map",  // unique ID
      "community": 3                   // Leiden community ID
    }
  ],
  "links": [                           // NOTE: "links" not "edges" in serialized form
    {
      "relation": "contains",          // "contains" | "imports" | "calls" | "semantically_similar_to" | etc.
      "confidence": "EXTRACTED",       // "EXTRACTED" | "INFERRED" | "AMBIGUOUS"
      "source_file": "path/to/file",
      "source_location": "L6",
      "weight": 1.0,
      "_src": "analyze",              // original source (preserved for directed display)
      "_tgt": "analyze_node_community_map",
      "source": "analyze",            // NetworkX edge source
      "target": "analyze_node_community_map"  // NetworkX edge target
    }
  ]
}
```

### Key Schema Observations
1. **Edges are serialized as `links`** (NetworkX convention), not `edges`. `build_from_json()` handles both: `if "edges" not in extraction and "links" in extraction: extraction = dict(extraction, edges=extraction["links"])`
2. **No `meta` envelope** in actual output. The `"graph": {}` key is empty. No `version`, `generated_at`, or `graphify_version` fields in the JSON itself.
3. **Legacy `source` field**: Older extractions use `source` instead of `source_file` on nodes. `build_from_json()` auto-renames with a warning.
4. **Node deduplication**: 3-layer (within-file AST, between-file NetworkX idempotent, semantic merge via `seen` set)
5. **Confidence tags**: `EXTRACTED` (AST), `INFERRED` (LLM with confidence score), `AMBIGUOUS` (flagged)

### CLI Commands
```
graphify install [--platform P]     # 15 platforms: claude|codex|opencode|cursor|gemini|aider|...
graphify path "A" "B"              # shortest path between nodes
graphify explain "X"               # node explanation
graphify query "<question>"        # BFS/DFS traversal
graphify update <path>             # re-extract code (no LLM)
graphify watch <path>              # watch + rebuild on changes
graphify cluster-only <path>       # rerun clustering only
graphify merge-graphs <g1> <g2>    # cross-repo merge
graphify clone <github-url>        # clone for analysis
graphify add <url>                 # fetch URL content
graphify save-result               # feedback loop
graphify benchmark [graph.json]    # token reduction measurement
graphify hook install/uninstall    # git hooks
```

### Internal Modules
| Module | Lines | Purpose |
|--------|-------|---------|
| `__main__.py` | ~1020 | CLI + install logic (raw argparse, no framework) |
| `build.py` | ~100 | `build()` / `build_from_json()` → NetworkX graph |
| `cluster.py` | ~100 | Leiden/Louvain community detection |
| `analyze.py` | ~150 | `god_nodes()`, `surprising_connections()`, `suggest_questions()` |
| `export.py` | ~200 | JSON, HTML, SVG, GraphML, Obsidian, Neo4j Cypher |
| `report.py` | ~100 | Markdown report generation |
| `extract.py` | ~200 | tree-sitter AST extraction |
| `validate.py` | ~50 | Schema validation |
| `security.py` | ~30 | `sanitize_label()` for XSS prevention |
| `merge.py` | ~80 | Cross-repo graph merging |

---

## 2. AhaDiff's Current Graphify Integration

### 2.1 Detection (`git/capture.py`)
```python
class GraphifyStatus:
    source_path: Path           # graphify-out/graph.json
    imported_path: Path         # .ahadiff/graphify/graph.json
    enabled: bool
    source_exists: bool
    imported_exists: bool
    has_graph: bool
    freshness: str | None       # "fresh" | "stale" | "unavailable" | "disabled", or None when no source
    provenance: dict[str, str]  # {"source": "graphify-out/graph.json"}
```
- Looks for `graphify-out/graph.json` at workspace root
- `--use-graphify` flag forces requirement / `--no-graphify` disables
- Auto-detect: if file exists, enabled; otherwise silent degradation

### 2.2 Import (`import_graphify_artifact()`)
- Reads `graphify-out/graph.json` via `_read_regular_file_no_follow_bounded()` (symlink-safe, size-bounded)
- Parses JSON first (`safe_json_loads()`), sanitizes recursively, then validates/normalizes with `parse_graph_json_text()`
- Writes the validated, normalized artifact to `.ahadiff/graphify/graph.json`
- Records in metadata/status: `enabled`, `source_exists`, `imported_exists`, `freshness`, `provenance`
- During `ahadiff learn`, Step 10 may first run external `graphify update <repo>` and then call `import_graphify_artifact(..., force=True)` before concepts are appended

### 2.3 Serve Projection (`serve/routes_runs.py`)
```python
_CANONICAL_GRAPHIFY_STATUSES = frozenset({"fresh", "stale", "unavailable", "disabled"})
_LEGACY_GRAPHIFY_STATUS_MAP = {
    "source_present": "stale",
    "missing_partial": "stale",
    "missing": "unavailable",
}
GraphifyMode = Literal["full", "learning_only", "empty"]
```
- `_project_graphify(metadata)` reads the `graphify` dict from run metadata
- Accepts both canonical values and legacy metadata inputs, but normalizes API output to the canonical 4-value set
- Projects to 3 API modes for run-detail compatibility: `full` (mode=full or freshness=fresh), `learning_only` (mode=learning_only or freshness in {stale, unavailable}), `empty` (fallback)
- Current ConceptGraph UI does not expose those values as UI modes; it renders `/api/graph/concepts` with Graph / List controls and uses `GraphStatusResponse` for status/empty states

### 2.4 Contracts
- `GraphifyMode = Literal["full", "learning_only", "empty"]` in `contracts/serve_app.py`
- `RunDetail` has `graphify_mode`, `graphify_status`, `graphify_notes` fields
- `LearnConfig.use_graphify: bool | None = None` in `contracts/orchestrator.py`

### 2.5 Design Plan (Partially Landed)
The design plan (`ahadiff-graphify-integration.md` + review) now has these pieces in code:
- Pydantic models: `GraphifyNode`, `GraphifyEdge`, `GraphifyHyperedge`, `GraphifyGraph`
- Parser normalization for flat node fields, `links`/`edges`, and `hyperedges`
- HTML/entity/URI sanitization before validation
- Internal 7-state freshness helper: `current`, `recent`, `stale`, `outdated`, `unknown`, `unavailable`, `disabled`
- 4-value projection: `{current, recent}` → fresh, `{stale, outdated, unknown}` → stale, `unavailable` → unavailable, `disabled` → disabled
- Backend helpers for subgraph slicing, fuzzy concept matching, concept linking, and graph search
- `GET /api/graph/status` and `/api/search` graph-node merge
- Optional external CLI bridge for `graphify update <repo>` during learn; failure only degrades the Graphify enhancement
- Remaining deeper work is now around frontend surfacing, optional graph slice emission, and real large-repo signoff evidence

### 2.6 Test Coverage
| Test File | Coverage |
|-----------|----------|
| `tests/unit/test_git_capture.py` | `import_graphify_artifact` happy path + symlink rejection |
| `tests/unit/test_graphify.py` | freshness projection, timeout / parse fallback, canonical pathspec, legacy mapping |
| `tests/unit/test_graphify_slicer.py` | file-based subgraph slicing, hop-depth bounds, hyperedge inclusion, deep-copy extraction |
| `tests/unit/test_graphify_matcher.py` | normalization, token overlap, containment, zero-width/control-char handling |
| `tests/unit/test_graphify_linker.py` | label matching, duplicate labels, score propagation, deduplication |
| `tests/unit/test_graphify_search.py` | graph-node search, limit/threshold behavior, search-result ranking |
| `tests/unit/test_orchestrator.py` | learn Step 10 Graphify update/import ordering and optional failure behavior |
| `tests/unit/test_routes_graph.py` | `/api/graph/status` payload, workspace-root relative path, missing/invalid graph fallback |
| `tests/unit/test_serve_app.py` | `_project_graphify` for full/learning_only/empty modes, plus legacy status normalization |
| `tests/unit/test_contracts.py` | `RunDetail.graphify_notes` field validation |
| `tests/unit/test_benchmark_scripts.py` | token-reduction metric, release workflow Graphify perf gate, graph-present fixture manifest/parser coverage |
| `tests/eval/test_benchmark.py` + `tests/integration/test_learn_pipeline.py` | 20 eval fixtures + 11 pinned integration fixtures; graph-present fixture `graph.json` is included in suite digest and materializes `graphify_context.json` / `artifact_set.json` |

---

## 3. Compatibility Matrix

### Schema Compatibility

| Aspect | Graphify v0.5 Actual | AhaDiff Current Handling | Status | Risk | Action |
|--------|---------------------|--------------------------|--------|------|--------|
| Top-level keys | `directed`, `multigraph`, `graph`, `nodes`, `links` | `parse_graph_json[_text]()` parses and validates the object shape | **YES** | LOW | Keep structural validation; no raw-text-only assumptions remain |
| Meta envelope | None (`graph: {}` is empty) | Structural parsing ignores missing `meta.version` and validates by shape | **YES** | LOW | Continue avoiding version-string dependence |
| Node fields | `id`, `label`, `file_type`, `source_file`, `source_location`, `community` | Parser normalizes `source_file|file_path|path` to `file_path` and `file_type|type|kind` to `kind`; extras stay in `metadata` | **YES** | LOW | Keep metadata-preserving normalization |
| Edge key name | `links` (NetworkX serialization) | Parser accepts `links` or `edges` and normalizes to `links` | **YES** | LOW | No further adaptation required for v1.0 |
| Edge fields | `source`, `target`, `relation`, `confidence`, `weight`, `_src`, `_tgt`, `source_file`, `source_location` | Design plan: `source`, `target`, `relation` | **YES** | LOW | Core fields match; extras are bonus |
| Confidence tags | `EXTRACTED`, `INFERRED`, `AMBIGUOUS` | Not in current design | **NEEDS_NEW** | LOW | Useful for trust-level filtering in viewer |
| Community IDs | Integer on each node | Preserved in metadata when present; current viewer does not cluster by community | **NEEDS_NEW** | LOW | Useful for a future community/filter view, not for the current Graph/List UI |
| Version detection | No version field in JSON | Structural parsing/validation; no `SUPPORTED_VERSIONS` whitelist in runtime | **YES** | LOW | Keep structure-based compatibility instead of version-string checks |

### Functional Compatibility

| AhaDiff Function | Location | Compatible? | Risk | Action Required |
|-----------------|----------|-------------|------|-----------------|
| `detect_graphify_status()` | `git/capture.py:534` | **YES** | LOW | Repo-aware freshness is wired in; no-repo / timeout / parse failures degrade to canonical `stale` |
| `import_graphify_artifact()` | `git/capture.py:547` | **YES** | LOW | Import now parses, sanitizes, validates, and writes the normalized `.ahadiff/graphify/graph.json` artifact up front. |
| `_project_graphify()` | `serve/routes_runs.py:571` | **YES** | LOW | Reads `freshness` first, still accepts legacy `status` inputs, and normalizes legacy values to canonical API output |
| `GraphifyStatus` dataclass | `git/capture.py:99` | **YES** | LOW | `freshness` now carries canonical 4-value output computed from repo context when available |
| `GraphifyMode` type | `contracts/serve_app.py:17` | **YES** | LOW | 3-value enum remains correct for run-detail projection; current ConceptGraph uses Graph/List UI state separately. |
| Sanitization pipeline | `import_graphify_artifact` | **YES** | LOW | Correctly treats graph.json as untrusted text. Runs `redaction_pipeline()` + `protect_untrusted_text()`. |
| Pydantic validation | `graphify/models.py` + `graphify/parser.py` | **YES** | LOW | Models and parser now validate the normalized schema in-process. |
| Subgraph slicing | `graphify/slicer.py` | **YES** | MED | Extracts changed-files ± N-hop subgraphs in memory; per-run `graphify_context.json` is emitted, while optional `graph.slice.json` emission is still future work. |
| Fuzzy concept matching | `graphify/matcher.py` | **YES** | LOW | Matching helper landed; default threshold is `0.85`, with linked concept IDs persisted through JSONL + SQLite derived cache when concept linking runs. |
| Concept linking | `graphify/linker.py` | **YES** | LOW | Helper and production concept append wiring exist; `concepts.graphify_node_id` is covered by migration/upsert tests. |
| Graph-node search | `graphify/search.py` + `review/search.py` | **YES** | LOW | `/api/search` merges graph hits at runtime via `search_all_with_graph()`, but only from imported `.ahadiff/graphify/graph.json`; raw `graphify-out/graph.json` is not read directly by the route. |
| Freshness 7-state helper | `graphify/freshness.py` + `git/capture.py` | **YES** | LOW | Repo-aware helper landed with 7→4 projection; import provenance now includes `graph_sha256`, `import_time`, `parser_version`, node/edge counts, and source path. |
| `ahadiff graph status/refresh/import` | `cli.py` | **YES** | LOW | CLI commands exist and use the current runtime wiring |
| `GET /api/graph/status` | `serve/routes_graph.py` | **YES** | LOW | Returns freshness plus current node/edge counts from imported `.ahadiff/graphify/graph.json`; raw `graphify-out/graph.json` only influences detection/freshness. |
| `GET /api/graph/concepts` | `serve/routes_graph.py` | **YES** | LOW | Returns sanitized ConceptGraph nodes/edges plus status for frontend consumption; it is not a full Graphify provenance API. |

### Graphify API Surface Compatibility

| Graphify Function | Can AhaDiff Use It? | Notes |
|-------------------|---------------------|-------|
| `build_from_json(extraction)` | **YES** | Parses JSON dict → NetworkX graph. Handles `links`/`edges`, legacy `source` field, ID normalization. AhaDiff could use this directly for subgraph slicing. |
| `cluster(G)` | **MAYBE** | Returns `{community_id: [node_ids]}`. Current AhaDiff viewer does not use clustering; this would only be relevant for a future community/filter view and would add `graphifyy` as dependency. |
| `god_nodes(G)` | **MAYBE** | Returns high-centrality nodes. Useful for context enrichment but adds dependency. |
| `validate_extraction(extraction)` | **YES** | Schema validation. AhaDiff should use or replicate this. |
| `sanitize_label(text)` | **NO** | XSS-focused (HTML escaping). AhaDiff has its own security pipeline. |
| `to_json(G, ...)` | **NO** | Export function. AhaDiff reads, does not write graphs. |

---

## 4. Gap Analysis Summary

### Current Remaining Gaps

| # | Gap | Current State | Resolution |
|---|-----|---------------|------------|
| G1 | Freshness/import provenance needs backend evidence | Repo-aware 4-value projection and import provenance are landed | **CLOSED for backend v1.0** — remaining work is UI surfacing / 5E polish, not backend provenance capture |
| G2 | DB-level Graphify linkage | matcher/linker helpers plus concept append wiring exist | **CLOSED** — JSONL + SQLite derived cache carry `graphify_node_id` when linking runs |
| G3 | Per-run graph artifacts | `graphify_context.json` is emitted and listed in `artifact_set.json` | **CLOSED for context manifest** — optional `graph.slice.json` remains future work |
| G4 | Graph nodes SQLite FTS indexing | `graph_nodes` + `fts_graph_nodes` import/indexing landed | **CLOSED** — imports above 10k nodes fail explicitly instead of silently truncating |
| G5 | Community/confidence are not surfaced as first-class UI filters | parser preserves them in metadata; current viewer does not cluster by them | **DEFERRED** to a future filter/detail view; backend already stores them in `GraphifyNode.metadata` |
| G6 | Benchmark coverage for graph operations | Graphify benchmark fixture, token-reduction metric, release perf gate, and graph-present pinned integration fixture landed | **PARTIAL** — `benchmarks/fixtures/integration/pinned_011_graph_present/graph.json` is included in the suite digest and materializes graph context artifacts, but it is still a synthetic 15-node smoke fixture and does not by itself prove full fidelity against every real Graphify v0.5 export |

---

## 5. Recommendations for v1.0

### 5.1 Do NOT add `graphifyy` as a Python dependency
- Graphify has heavy dependencies (20 tree-sitter grammars, optional graspologic/faster-whisper/anthropic)
- AhaDiff should remain a lightweight consumer of `graph.json` output only
- If subgraph operations are needed, replicate minimal NetworkX logic or use `networkx` directly (already lightweight)

### 5.2 Implemented Model Shape
```python
class GraphifyNode(BaseModel):
    id: str
    label: str
    file_path: str | None = None          # normalized from source_file|file_path|path
    kind: str | None = None               # normalized from file_type|type|kind
    metadata: dict[str, object] = Field(default_factory=dict)

class GraphifyEdge(BaseModel):
    source: str
    target: str
    relation: str = "related"
    metadata: dict[str, object] = Field(default_factory=dict)

class GraphifyGraph(BaseModel):
    directed: bool = False
    multigraph: bool = False
    nodes: list[GraphifyNode]
    links: list[GraphifyEdge] = Field(default_factory=list)
    hyperedges: list[GraphifyHyperedge] = Field(default_factory=list)
```

### 5.3 Freshness Computation Strategy
```
1. Read .graphify_version file (if exists) → know which graphify produced the graph
2. Read graph.json mtime vs current repo HEAD commit timestamp
3. Check if any files in graph's source_file list have been modified since graph mtime
4. Map to 7-state: fresh (no changes) / stale (minor changes) / outdated (major changes) / ...
```

### 5.4 Subgraph Slicing (Core v1.0 Feature)
```python
def slice_subgraph(graph: GraphifyGraph, changed_files: list[str], hops: int = 2) -> GraphifyGraph:
    """Extract subgraph: nodes within ±hops of changed files, plus all connecting edges."""
    # 1. Find node IDs whose source_file matches any changed file
    # 2. BFS/DFS to collect ±hop neighbors
    # 3. Filter edges to only those between collected nodes
    # 4. Return sliced GraphifyGraph
```

### 5.5 Remaining Priority Order
1. **5E frontend polish**: basic cross-page freshness/status now uses the shared `GraphifyCard`; the learn-time CLI update bridge exists, but full source/provenance UI and real large-repo signoff are still pending
2. **Optional graph slice artifact**: `graphify_context.json` is emitted today; a real `graph.slice.json` remains future work
3. **Frontend surfacing**: expose `community` / `confidence` in a future filter/detail view rather than only preserving them in metadata; do not treat clustering as current UI behavior
4. **Stronger compatibility evidence**: add at least one benchmark or regression fixture sourced from a real Graphify v0.5 export, not only the synthetic 15-node smoke fixture
