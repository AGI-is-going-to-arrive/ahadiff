# RFC 2.4 — MCP `ask_lesson` Extension

**Status**: Draft
**Date**: 2026-05-12
**Module**: `src/ahadiff/mcp/`
**Scope**: Add one read-only tool to the existing stdio MCP server. Current code registers 6 tools (`list_runs`, `get_run_summary`, `list_due_cards`, `search`, `get_concepts`, `get_stats`); this RFC must not modify their schemas or outputs.

## 1. Target Users

Developers using MCP-aware clients (Claude Desktop, Cursor, custom IDE plugins) who need to interrogate a previously generated AhaDiff lesson without leaving their editor. Today they must call `get_run_summary` then post-process the JSON to find the section they care about; `ask_lesson` provides a single-shot, question-scoped lookup that returns the relevant lesson fragment plus its claim-evidence chain.

## 2. Data Model

**Input** (JSON Schema, MCP tool parameters):
- `run_id` (string, required) — must exist under `<repo>/.ahadiff/runs/`.
- `question` (string, required, length 1..512) — natural-language query, bounded deterministic token scoring, not sent to any LLM.
- `top_k` (int, optional, default 3, max 10) — number of fragments returned.

**Output** (`AskLessonResult`):
- `fragments`: list of `{section_id, heading, snippet, score}` where `snippet` is at most 800 chars and is sourced from the immutable lesson markdown.
- `evidence`: list of `{claim_id, status, file, line_start, line_end, hunk_hash}` joined from `claims.jsonl` for the matched section. `status` ∈ {verified, weak, not_proven, contradicted, rejected}.
- `run_meta`: `{run_id, generated_at, lesson_tier}`.

Retrieval uses the existing `review.sqlite` FTS5 index only for the tables that exist today (`concepts`, `result_events`, `cards`, plus optional imported `graph_nodes`). There is no current lesson FTS table. `ask_lesson` therefore reads the run-scoped lesson/claims files and performs bounded deterministic token scoring over lesson fragments in memory; no new tables, no new indexes, no schema migration. Empty results return `fragments: []` with `error_code: null` — not a 4xx.

## 3. Security Boundary

The stdio MCP transport stays read-only. The tool opens `review.sqlite` with the existing `query_only=ON` pragma path and never touches `runs/*/audit.private.jsonl`. Input is bounded (`run_id` validated against `RUN_ID_RE`, `question` truncated at 512 chars, `top_k` clamped to [1, 10]) to prevent FTS pathological queries. All input goes through `redaction_pipeline()` before being used in log lines. Returned snippets inherit the run's already-redacted lesson body — no fresh raw content is exposed.

## 4. Local-First Privacy

`ask_lesson` only reads files under `<repo>/.ahadiff/`. No network calls, no LLM provider invocation, no telemetry. The tool advertises `privacy: "strict_local"` in its MCP description so clients can surface it to users.

## 5. Cross-Platform

stdio MCP is already validated on macOS/Linux/Windows by the existing server. Path handling reuses `core.paths` (Pathlib + reparse-point guards). No new platform surface.

## 6. Test Strategy

- Unit: `tests/unit/mcp/test_ask_lesson.py` covers (a) exact-heading match, (b) multi-fragment ranking, (c) empty repo / missing run_id → `ErrorCode.RUN_NOT_FOUND`, (d) oversized question → `ErrorCode.INPUT_TOO_LARGE`, (e) punctuation / regex-like query text as plain tokens, (f) evidence join with all 5 claim statuses.
- Integration: `tests/integration/test_mcp_server.py` adds an end-to-end stdio fixture asserting the existing 6 tools' responses are byte-identical with and without the new tool registered.
- No live LLM tests required (pure retrieval).

## 7. Release Gate

- Existing 6 tools' JSON schemas and outputs unchanged (snapshot-tested).
- New tool gated behind a single registration line; `tests/unit/mcp/test_tool_registry.py` asserts the registry length is exactly 7.
- ruff + pyright strict clean; coverage for `mcp/` module ≥ 90%.
- CHANGELOG entry under v1.2 once merged.

## 8. What NOT to Do

- No write-back to `review.sqlite`, concepts.jsonl, or any run artifact.
- No LLM calls — retrieval only; ranking is bounded deterministic token scoring over run-scoped lesson fragments.
- No cross-run aggregation (one `run_id` per call); cross-run search stays in the existing `search` tool.
- No streaming response — single JSON payload, bounded size.
- No new config keys; reuses existing repo resolution and locale.
