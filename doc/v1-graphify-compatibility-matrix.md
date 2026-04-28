# Graphify v0.5.0 ↔ AhaDiff v0.2 Compatibility Matrix

> Research date: 2026-04-27 | Graphify commit: HEAD of `safishamsi/graphify` | AhaDiff: `main` (1943746)

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
- Runs through `redaction_pipeline()` + `protect_untrusted_text()` for sanitization
- Copies sanitized content to `.ahadiff/graphify/graph.json`
- Records in metadata: `enabled`, `source_exists`, `freshness`, `provenance`

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
- Projects to 3 modes: `full` (mode=full or freshness=fresh), `learning_only` (mode=learning_only or freshness in {stale, unavailable}), `empty` (fallback)
- Frontend viewer uses these 3 modes for ConceptGraph degradation

### 2.4 Contracts
- `GraphifyMode = Literal["full", "learning_only", "empty"]` in `contracts/serve_app.py`
- `RunDetail` has `graphify_mode`, `graphify_status`, `graphify_notes` fields
- `LearnConfig.use_graphify: bool | None = None` in `contracts/orchestrator.py`

### 2.5 Design Plan (Partially Landed)
The design plan (`ahadiff-graphify-integration.md` + review) now has these pieces in code:
- Pydantic models: `GraphifyNode`, `GraphifyEdge`, `GraphifyHyperedge`, `GraphifyGraph`
- Internal 7-state freshness helper: `current`, `recent`, `stale`, `outdated`, `unknown`, `unavailable`, `disabled`
- 4-value projection: `{current, recent}` → fresh, `{stale, outdated, unknown}` → stale, `unavailable` → unavailable, `disabled` → disabled
- Remaining deeper work is still around richer provenance, graph slicing, and frontend surfacing
- `SUPPORTED_VERSIONS: ["0.3", "0.4", "1.0"]`
- Subgraph slicing: changed files ± 2 hop neighbors
- `graph.slice.json` + `graphify.links.json` per run

### 2.6 Test Coverage
| Test File | Coverage |
|-----------|----------|
| `tests/unit/test_git_capture.py` | `import_graphify_artifact` happy path + symlink rejection |
| `tests/unit/test_graphify.py` | freshness projection, timeout / parse fallback, canonical pathspec, legacy mapping |
| `tests/unit/test_serve_app.py` | `_project_graphify` for full/learning_only/empty modes, plus legacy status normalization |
| `tests/unit/test_contracts.py` | `RunDetail.graphify_notes` field validation |

---

## 3. Compatibility Matrix

### Schema Compatibility

| Aspect | Graphify v0.5 Actual | AhaDiff Assumption | Status | Risk | Action |
|--------|---------------------|-------------------|--------|------|--------|
| Top-level keys | `directed`, `multigraph`, `graph`, `nodes`, `links` | Expects raw JSON text (no parsing) | **NEEDS_ADAPTATION** | HIGH | Must parse and validate using `links` not `edges` |
| Meta envelope | None (`graph: {}` is empty) | Design plan assumes `meta.version` field | **NEEDS_NEW** | HIGH | Cannot rely on `meta.version`; detect schema by structure |
| Node fields | `id`, `label`, `file_type`, `source_file`, `source_location`, `community` | Design plan: `id`, `label`, `meta.type`, `meta.path` | **NEEDS_ADAPTATION** | MED | Map flat fields to planned Pydantic model |
| Edge key name | `links` (NetworkX serialization) | Design plan assumes `edges` | **NEEDS_ADAPTATION** | HIGH | Must handle both `links` and `edges` (Graphify's own `build_from_json` does this) |
| Edge fields | `source`, `target`, `relation`, `confidence`, `weight`, `_src`, `_tgt`, `source_file`, `source_location` | Design plan: `source`, `target`, `relation` | **YES** | LOW | Core fields match; extras are bonus |
| Confidence tags | `EXTRACTED`, `INFERRED`, `AMBIGUOUS` | Not in current design | **NEEDS_NEW** | LOW | Useful for trust-level filtering in viewer |
| Community IDs | Integer on each node | Not in current design | **NEEDS_NEW** | LOW | Useful for ConceptGraph clustering in viewer |
| Version detection | No version field in JSON | `SUPPORTED_VERSIONS: ["0.3", "0.4", "1.0"]` | **NEEDS_ADAPTATION** | MED | Must detect by presence of fields, not version string |

### Functional Compatibility

| AhaDiff Function | Location | Compatible? | Risk | Action Required |
|-----------------|----------|-------------|------|-----------------|
| `detect_graphify_status()` | `git/capture.py:534` | **YES** | LOW | Repo-aware freshness is wired in; no-repo / timeout / parse failures degrade to canonical `stale` |
| `import_graphify_artifact()` | `git/capture.py:547` | **YES** | LOW | Works as-is; reads raw text, sanitizes, copies. No schema parsing. |
| `_project_graphify()` | `serve/routes_runs.py:571` | **YES** | LOW | Reads `freshness` first, still accepts legacy `status` inputs, and normalizes legacy values to canonical API output |
| `GraphifyStatus` dataclass | `git/capture.py:99` | **YES** | LOW | `freshness` now carries canonical 4-value output computed from repo context when available |
| `GraphifyMode` type | `contracts/serve_app.py:17` | **YES** | LOW | 3-value enum is correct for viewer degradation. |
| Sanitization pipeline | `import_graphify_artifact` | **YES** | LOW | Correctly treats graph.json as untrusted text. Runs `redaction_pipeline()` + `protect_untrusted_text()`. |
| Pydantic validation | Planned, not implemented | **NEEDS_NEW** | HIGH | Must define models matching actual v0.5 schema (flat node fields, `links` key, no `meta` envelope) |
| Subgraph slicing | Planned, not implemented | **NEEDS_NEW** | HIGH | Core v1.0 feature: extract ± 2-hop neighbors of changed files |
| Freshness 7-state helper | `graphify/freshness.py` + `git/capture.py` | **PARTIAL** | MED | Repo-aware helper is landed, but imported-at / head-at-import style provenance is still not surfaced |
| `ahadiff graph status/refresh/import` | `cli.py` | **YES** | LOW | CLI commands exist and use the current runtime wiring |

### Graphify API Surface Compatibility

| Graphify Function | Can AhaDiff Use It? | Notes |
|-------------------|---------------------|-------|
| `build_from_json(extraction)` | **YES** | Parses JSON dict → NetworkX graph. Handles `links`/`edges`, legacy `source` field, ID normalization. AhaDiff could use this directly for subgraph slicing. |
| `cluster(G)` | **MAYBE** | Returns `{community_id: [node_ids]}`. AhaDiff could use for ConceptGraph but would add `graphifyy` as dependency. |
| `god_nodes(G)` | **MAYBE** | Returns high-centrality nodes. Useful for context enrichment but adds dependency. |
| `validate_extraction(extraction)` | **YES** | Schema validation. AhaDiff should use or replicate this. |
| `sanitize_label(text)` | **NO** | XSS-focused (HTML escaping). AhaDiff has its own security pipeline. |
| `to_json(G, ...)` | **NO** | Export function. AhaDiff reads, does not write graphs. |

---

## 4. Gap Analysis Summary

### Critical Gaps (Must Fix for v1.0)

| # | Gap | Current State | Required State | Effort |
|---|-----|---------------|----------------|--------|
| G1 | **No graph.json parsing** | Raw text copy only | Parse + validate against actual v0.5 schema | M |
| G2 | **`links` vs `edges` key mismatch** | Design assumes `edges` | Must handle `links` (v0.5 default) + `edges` (fallback) | S |
| G3 | **No meta/version envelope** | Design assumes `meta.version` | Detect schema by structure; version from `.graphify_version` file or inference | S |
| G4 | **No subgraph slicing** | Full graph copy | Extract changed-files ± 2-hop subgraph for each run | L |
| G5 | **Pydantic models undefined** | Planned only | Define `GraphifyNode`/`GraphifyEdge`/`GraphifyGraph` matching actual v0.5 fields | M |
| G6 | **Freshness provenance is still shallow** | Repo-aware 4-value projection is landed, but metadata still only stores source path/projection | If v1.0 needs richer status UI, add imported-at / head-at-import style provenance and a dedicated status endpoint | M |

### Medium Gaps (Should Fix for v1.0)

| # | Gap | Notes |
|---|-----|-------|
| G7 | CLI commands (`ahadiff graph status/refresh/import`) not implemented | Design exists in plan |
| G8 | Confidence-based filtering not available | Graphify provides `EXTRACTED`/`INFERRED`/`AMBIGUOUS`; useful for trust weighting |
| G9 | Community IDs not surfaced to viewer | Graphify computes Leiden communities; viewer ConceptGraph could use them |
| G10 | No `graphify update` integration | AhaDiff could invoke `graphify update .` to refresh AST-only graph |

### Low Gaps (Nice-to-have)

| # | Gap | Notes |
|---|-----|-------|
| G11 | No cross-repo graph merge support | Graphify has `merge-graphs`; future AhaDiff multi-repo feature |
| G12 | No `graphify query` integration | Could enhance `ahadiff graph` CLI with traversal queries |

---

## 5. Recommendations for v1.0

### 5.1 Do NOT add `graphifyy` as a Python dependency
- Graphify has heavy dependencies (20 tree-sitter grammars, optional graspologic/faster-whisper/anthropic)
- AhaDiff should remain a lightweight consumer of `graph.json` output only
- If subgraph operations are needed, replicate minimal NetworkX logic or use `networkx` directly (already lightweight)

### 5.2 Pydantic Models (Match v0.5 Actual Schema)
```python
class GraphifyNode(BaseModel):
    id: str
    label: str
    file_type: str | None = None          # "code", "doc", "concept", etc.
    source_file: str | None = None        # relative path
    source_location: str | None = None    # "L6" format
    community: int | None = None          # Leiden community ID
    # Allow extra fields for forward compatibility
    model_config = ConfigDict(extra="allow")

class GraphifyEdge(BaseModel):
    source: str
    target: str
    relation: str = "related"
    confidence: str | None = None         # "EXTRACTED" | "INFERRED" | "AMBIGUOUS"
    weight: float = 1.0
    source_file: str | None = None
    source_location: str | None = None
    model_config = ConfigDict(extra="allow")

class GraphifyGraph(BaseModel):
    directed: bool = False
    multigraph: bool = False
    nodes: list[GraphifyNode]
    links: list[GraphifyEdge] = Field(default_factory=list, alias="links")
    edges: list[GraphifyEdge] = Field(default_factory=list)
    # NOTE: Must normalize links→edges in validator
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

### 5.5 Implementation Priority Order
1. **G5** Pydantic models → foundation for everything else
2. **G1+G2+G3** Schema parsing with `links`/`edges` normalization + structural version detection
3. **G6** Real freshness computation
4. **G4** Subgraph slicing
5. **G7** CLI commands
6. **G8+G9** Confidence filtering + community surfacing in viewer
