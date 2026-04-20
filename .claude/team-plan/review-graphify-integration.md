# Design Review: Graphify Auto-Integration

**Reviewer**: Claude (Opus 4.6)
**Date**: 2026-04-20
**Document**: `.claude/team-plan/ahadiff-graphify-integration.md`
**Score**: **78 / 100**

---

## Critical (must fix before implementation)

### C1. `pyproject.toml` optional-dep contradicts "no auto-install" principle
**File**: `ahadiff-graphify-integration.md:337-348`
Section 7 adds `graphify>=0.3` as an optional dependency (`pip install ahadiff[graph]`). Section 3.1 argues against auto-install citing supply-chain risk, referencing `CLAUDE.md`'s LiteLLM lesson. But bundling Graphify as an optional dep still couples AhaDiff's release to Graphify's PyPI availability and version policy. If Graphify publishes a yanked release or gets compromised, `ahadiff[graph]` breaks or becomes a vector.
**Recommendation**: Remove `[graph]` optional-dep entirely. Keep Graphify as a purely external tool detected at runtime. Document install instructions in `ahadiff docs graphify` only.

### C2. Missing Pydantic models for `graph.json` schema validation
**File**: `ahadiff-graphify-integration.md:186-213`
Section 4.2 says "validate JSON schema, must have `nodes[]` and `edges[]`" but provides no Pydantic model definitions. `CLAUDE.md` mandates Pydantic for data validation. Without defined models, implementors will guess field types, leading to fragile `dict.get()` chains.
**Recommendation**: Define `GraphifyNode`, `GraphifyEdge`, `GraphifyMeta`, `GraphifyGraph` Pydantic models in the design. At minimum specify required fields and types for `meta.version`, `nodes[].id`, `nodes[].type`, `edges[].source`, `edges[].target`.

### C3. Freshness check uses mtime -- unreliable after git operations
**File**: `ahadiff-graphify-integration.md:47-63`
`mtime vs HEAD commit` comparison is fragile. `git checkout`, `git stash pop`, and CI artifact downloads all reset mtime. A freshness check based on file mtime will produce false "fresh" or false "stale" results.
**Recommendation**: Store the HEAD commit hash at import time in `.ahadiff/graphify_meta.json`. Compare stored hash against current HEAD. Fall back to mtime only if meta file is missing.

---

## Warning (should fix for v0.1)

### W1. No error type taxonomy
**File**: entire document
The design describes many error scenarios (corrupted JSON, version mismatch, subprocess failure, concurrent write) but defines no error class hierarchy. `CLAUDE.md` plans for structured error handling.
**Recommendation**: Define at minimum: `GraphifyNotFoundError`, `GraphifyImportError`, `GraphifyVersionError`, `GraphifyStaleWarning`. Map each corner case to a specific error type.

### W2. PageRank pruning is overengineered for v0.1
**File**: `ahadiff-graphify-integration.md:231-232`
Implementing PageRank on the graph slice adds a scipy/networkx dependency and algorithmic complexity. For v0.1, a simpler heuristic (keep nodes with highest degree within the slice) achieves 90% of the value.
**Recommendation**: Defer PageRank to v0.2. Use degree-count pruning for v0.1. Add a `TODO(v0.2): upgrade to PageRank` comment.

### W3. Concurrent write detection via ".lock file or mtime in 5s" is ad-hoc
**File**: `ahadiff-graphify-integration.md:454-459`
Checking mtime delta within 5 seconds is a race condition. Graphify itself may not create `.lock` files.
**Recommendation**: Use `fcntl.flock` (POSIX) or simply catch `json.JSONDecodeError` on partial reads and retry once after 2 seconds. Document that Windows requires a different strategy.

### W4. No Windows path handling mentioned
**File**: entire document
All paths use POSIX separators. `shutil.which("graphify")` works cross-platform, but `graphify-out/graph.json` resolution, config path `../../graphify-out`, and `.ahadiff/` storage need `pathlib.Path` enforcement.
**Recommendation**: Add a note that all path construction must use `pathlib.Path`, never string concatenation with `/`.

### W5. Symlinks in `graphify-out/` not addressed
**File**: corner cases section (9.1-9.10)
If `graphify-out/` or `graph.json` is a symlink (common in monorepo setups), `Path.exists()` follows symlinks but `mtime` may reflect the link, not the target. Also a security concern if symlinks point outside the repo.
**Recommendation**: Add corner case 9.11: resolve symlinks with `Path.resolve()`, reject if resolved path is outside the git root (path traversal prevention).

### W6. Logging strategy undefined
**File**: entire document
Rich console output is specified for user-facing messages, but no structured logging (for debugging, CI logs) is defined. `CLAUDE.md` plans for structured logging in the CLI.
**Recommendation**: Define log levels: DEBUG (detection details), INFO (import success), WARNING (stale/corrupted), ERROR (subprocess failure). Use Python `logging` module alongside Rich console.

---

## Info (non-blocking, consider for later)

### I1. Disk space for large slices unmentioned
`max_slice_kb = 512` caps the slice, but the full `graph.json` (10MB+) is still read into memory. For very large repos, streaming JSON parsing (`ijson`) may be needed.

### I2. `graph.json` vs `graph.html` confusion risk
Graphify produces both `graph.json` and `GRAPH_REPORT.md`. The v5 HTML prototype (line 1845) shows `ahadiff graph import graphify-out/GRAPH_REPORT.md` (a Markdown file), but the design only describes importing `graph.json`. Clarify which files are importable and what each provides.

### I3. Network-less / air-gapped environments
The design handles Graphify-absent scenarios well. However, the `pip install graphify` suggestion in CLI prompts (line 115) is unhelpful in air-gapped environments. Consider adding: "or install from local wheel: `pip install graphify-0.3.2.whl`".

### I4. Docker/CI scenario underdeveloped
Corner case 9.3 mentions CI briefly. A dedicated CI section should cover: Docker image with pre-installed Graphify, cache `graphify-out/` between CI runs, `--no-graphify` as CI default to avoid flaky graph detection.

### I5. `ahadiff graph refresh` runs `graphify .` as subprocess -- no timeout
If Graphify hangs on a huge repo, `ahadiff graph refresh` blocks indefinitely. Add `subprocess.run(..., timeout=300)`.

### I6. Frontend 3-mode degradation aligns well with v5 prototype
The v5 Graph page (lines 1820-1970) already has: Graphify Source Card with "synced" status, filter chips including "From Graphify", legend with repo-context grey nodes, and a list fallback. The 3-mode design maps cleanly to this. Mode B would hide grey nodes and the "From Graphify" chip -- consistent with filter design. Mode C would replace the SVG area with an empty state. Good alignment overall.

---

## Consistency Check vs CLAUDE.md

| Rule | Status |
|------|--------|
| "AhaDiff 不重造 repo graph" | PASS -- design explicitly delegates to Graphify |
| "文件即真相源" | PASS -- `graph.slice.json` is the truth source for frontend |
| "不使用 LiteLLM" supply-chain lesson | WARNING -- optional-dep in pyproject.toml partially contradicts this (see C1) |
| "所有 LLM 调用走 llm/provider.py" | N/A -- Graphify integration has no LLM calls |
| "prompt 写成独立 .md" | N/A |
| "Jinja2 静态 HTML 首版" | PASS -- template snippets use Jinja2 syntax |
| Graphify = "repo-level map, AhaDiff = diff learning overlay" | PASS -- stated in design principles |

---

## Summary

The design is well-structured with thoughtful degradation and 10 corner cases. The main gaps are: (1) coupling via `pyproject.toml` optional-dep contradicts the supply-chain caution principle, (2) missing Pydantic models make implementation ambiguous, (3) mtime-based freshness is unreliable. PageRank pruning is overengineered for v0.1. Frontend 3-mode mapping to the existing v5 prototype is coherent and well-aligned.
