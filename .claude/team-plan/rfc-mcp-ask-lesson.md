# RFC 2.4 — MCP `ask_lesson` Extension

**Status**: IMPLEMENTED — read-only `ask_lesson` registered as tool 7
**Date**: 2026-05-12
**Module**: `src/ahadiff/mcp/`
**Scope**: Add one read-only tool to the existing stdio MCP server. Current code registers 7 tools (`list_runs`, `get_run_summary`, `list_due_cards`, `search`, `get_concepts`, `get_stats`, `ask_lesson`); the existing 6 tools' schemas and outputs remain unchanged.

**Current-code truth (2026-05-12)**:
- The current server has 7 tools and a stdio entrypoint.
- MCP DB access now has an MCP-specific read-only helper using URI `mode=ro` and `PRAGMA query_only=ON`; stats/search table access also uses allowlists.
- Stable `ErrorCode` still has 28 values. `ask_lesson` uses existing validation/not-found errors; no new ErrorCode was added.
- `ask_lesson` reads finalized run lesson files in priority order (`lesson.full.md`, `lesson.hint.md`, `lesson.compact.md`) and joins local `claims.jsonl` evidence. It does not call an LLM and does not write to SQLite.

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

The stdio MCP transport stays read-only. MCP DB reads use the MCP-specific read-only DB helper with `PRAGMA query_only=ON`; the tool never touches `runs/*/audit.private.jsonl`.

Input is bounded (`run_id` validated through the existing safe run path validation, `question` rejected above 512 chars, `top_k` clamped to [1, 10]) to prevent pathological queries. All input goes through `redaction_pipeline()` before being used in log lines. Returned snippets inherit the run's already-redacted lesson body — no fresh raw content is exposed.

## 4. Local-First Privacy

`ask_lesson` only reads files under `<repo>/.ahadiff/`. No network calls, no LLM provider invocation, no telemetry. The tool advertises `privacy: "strict_local"` in its MCP description so clients can surface it to users.

## 5. Cross-Platform

stdio MCP exists today, but Windows stdio is not proven by the current CI matrix. Path handling reuses `core.paths` (Pathlib + reparse-point guards). Add a Windows smoke or explicitly mark Windows stdio as not locally verified in release notes.

## 6. Test Strategy

- Unit: implemented in `tests/unit/test_mcp_ask_lesson.py` and `tests/unit/test_mcp_server.py`, covering fragment ranking, missing run, bounded query/top_k behavior, plain-token regex-like text, finalized-run gate, and evidence join.
- Integration-style stdio snapshot for all existing tools remains a future hardening item.
- No live LLM tests required (pure retrieval).

## 7. Release Gate

- Existing 6 tools' JSON schemas and outputs unchanged.
- Registry test asserts the tool count is 7.
- ruff + pyright strict clean; coverage for `mcp/` module ≥ 90%.
- CHANGELOG entry under v1.2 once merged.

## 8. What NOT to Do

- No write-back to `review.sqlite`, concepts.jsonl, or any run artifact.
- No LLM calls — retrieval only; ranking is bounded deterministic token scoring over run-scoped lesson fragments.
- No cross-run aggregation (one `run_id` per call); cross-run search stays in the existing `search` tool.
- No streaming response — single JSON payload, bounded size.
- No new config keys; reuses existing repo resolution and locale.
