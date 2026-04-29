# v1.0 Execution Plan -- R4 Deep Backend Verification Report

**Auditor**: Claude (R4 independent backend verification)
**Date**: 2026-04-28
**Baseline at review time**: 808 passed, 1 skipped
**Scope**: 9 dimensions of backend technical feasibility

> Current status note (2026-04-29): This report is an R4 historical audit, not the
> current branch truth. The current uncommitted branch already has
> `src/ahadiff/core/orchestrator.py`, `POST /api/learn`, `/api/tasks*`
> status/progress/cancel wiring, `GET /api/graph/status`, and watcher core.
> Current verification is: full pytest `1420 passed, 1 skipped`; coverage gate
> `87.37%`; focused backend regressions `59 passed`; serve regressions
> `129 passed`; `ruff check` / `ruff format --check` pass; `pyright`
> currently reports `0 errors, 0 warnings, 0 informations`.

---

## Post-fix update (2026-04-28)

The Phase 0 follow-up closed the concrete issues from this report that were still live in the current branch:

- `cli.py` doctor now rejects symlinked `review.sqlite` paths before `sqlite3.connect()`.
- `serve` write paths now reject malformed IPv6 origins, preflight requests on the wrong loopback port, and non-finite helpfulness payload numbers as controlled client errors.
- the benchmark runner now uses the project Python explicitly and writes stable error JSON when a child script exits non-zero or prints non-JSON.

Current verification after those fixes:

- `uv run pytest tests -q --tb=long` → `845 passed, 1 skipped in 33.20s`
- `uv run ruff check src tests` → pass
- `uv run ruff format --check src tests` → pass
- `uv run pyright` → `0 errors`

This addendum is only claiming the Phase 0 follow-up items above are now closed. It does not retroactively mark unrelated gaps in the rest of this report as fixed.

The rest of this report should still be read as an R4 planning audit, not as a claim that every non-Phase-0 item below is already implemented.

---

## 1. Orchestrator Gap Analysis

**Verdict: WARNING -- Plan underestimates extraction complexity**

**Evidence:**
- `src/ahadiff/contracts/orchestrator.py` defines an abstract `Orchestrator` class (line 87-95) with `run_learn()`, `run_improve()`, `run_verify()` -- all `async` and returning `OrchestratorResult`.
- `src/ahadiff/cli.py` is 2,746 lines. `learn_cmd` starts at line 660 and spans ~200+ lines of inline orchestration.
- `learn_cmd` (lines 780-900) directly calls: `capture_patch()` -> `assess_learnability()` -> `write_input_artifacts()` -> `_resolve_runtime_provider()` -> `extract_claim_candidates_from_run()` -> lesson generation -> quiz generation -> eval -- all inlined with complex error handling and conditional branching.
- **No runtime `Orchestrator` implementation exists** (`src/ahadiff/core/orchestrator.py` = FILE NOT FOUND). The contract is defined but never implemented.
- Extracting this requires: (a) implementing `RuntimeOrchestrator` as an `Orchestrator` subclass, (b) moving ~200 lines of flow control + error handling + provider resolution out of `learn_cmd`, (c) making it `async` (currently sync typer commands), (d) similar extraction for `improve_cmd` and `verify_cmd`.

**Assessment:** The 7-10 PD estimate in Phase 6B is **tight but feasible** for extraction alone. However, the sync-to-async transition (typer is sync, the contract is async) adds hidden complexity. The plan should note this explicitly.

---

## 2. FSRS Implementation Depth

**Verdict: WARNING -- "3-stage self-adaptive" is a significant leap**

**Evidence:**
- `src/ahadiff/review/scheduler.py` (198 lines) wraps `py-fsrs` library: imports `Card, Rating, Scheduler` (line 9).
- Current integration is **thin wrapper**: `review_fsrs_card()` (line 83) creates a `Scheduler`, calls `scheduler.review_card()`, returns a `ScheduledReview` dataclass.
- `_make_scheduler()` (line 141) accepts `parameters` tuple + `desired_retention` + `enable_fuzzing` -- supports custom weights but **does not optimize them**.
- `database.py` (1,828 lines, 74 functions) stores `scheduler_presets` table with `weights`, `desired_retention`, `maximum_interval`, `scheduler_version` columns.
- `_scheduler_weights_for_card()` (line 1639) loads per-card or default weights.
- `_review_day_deltas()` (line 1675) calculates review intervals -- the only analytics primitive.

**Gap:** A "3-stage self-adaptive optimizer" requires: (a) collecting review history statistics, (b) running FSRS parameter optimization (the `py-fsrs` library's `Optimizer` class or equivalent), (c) per-user/per-deck weight adaptation, (d) staged rollout (bootstrap -> adaptive -> stabilized). Current code has **zero optimizer infrastructure**. The 3-4 PD estimate is **optimistic** -- 5-7 PD is more realistic given the need to build the optimizer pipeline, validation framework, and A/B comparison logic.

---

## 3. Concepts SQLite Migration

**Verdict: PASS -- Straightforward with known schema**

**Evidence:**
- `src/ahadiff/wiki/concepts.py` (line 231-253) defines concept entry fields:
  ```
  concept, term_key, term, display_name, lang, aliases[], source_refs[],
  branch_hint, introduced_by_run, updated_by_runs[], related_claims[], file_refs[]
  ```
- Currently stored as `concepts.jsonl` (append-only, line-delimited JSON).
- `load_concepts_page()` (line 148) uses cursor-based pagination via line index offset -- simple but O(n) for large files.
- `_AncestryCache` (line 36) limits subprocess calls to 200 -- already a scaling concern that SQLite would help resolve.

**Assessment:** 5-7 PD is **realistic**. Schema design is straightforward (12 columns, 3 array columns need junction tables or JSON columns). The main work is: (a) schema design, (b) migration tool from JSONL, (c) rewriting `append_concepts()` / `load_visible_concepts()` / `load_concepts_page()` to use SQL, (d) index design for `term_key` + `branch_hint`. The array fields (`aliases`, `source_refs`, `updated_by_runs`, `related_claims`, `file_refs`) can use `JSON` type columns to minimize schema complexity.

---

## 4. FTS5 Feasibility

**Verdict: PASS -- Infrastructure ready**

**Evidence:**
- System SQLite version: 3.47.2 (well above FTS5 minimum of 3.9.0).
- FTS5 confirmed working: `CREATE VIRTUAL TABLE test USING fts5(content)` succeeds.
- Current tables needing FTS5 mirrors: `cards` (concept + question text), `result_events` (run metadata), and the future `concepts` table. That's **3 virtual tables**.
- `review.sqlite` already has 5 tables (`scheduler_presets`, `cards`, `review_logs`, `result_events`, `learning_signals`).

**Assessment:** 5-7 PD is **realistic**. Main work: (a) FTS5 virtual table DDL for cards/concepts/result_events, (b) trigger-based sync or content= external content tables, (c) search API endpoints, (d) rank/snippet helpers. No blockers.

---

## 5. Background Task Queue

**Verdict: WARNING -- SSE available but no task infrastructure exists**

**Evidence:**
- `src/ahadiff/serve/app.py` uses Starlette (`from starlette.applications import Starlette`).
- All route handlers are `async def` using `anyio.to_thread.run_sync` for blocking I/O (confirmed in routes_signals.py:6, routes_config.py:9, routes_install.py:9).
- `sse-starlette` v3.3.2 is installed globally (required by `mcp`), but **not in the project's own dependencies**.
- No `StreamingResponse`, `EventSourceResponse`, `BackgroundTask`, or any task queue infrastructure exists in the serve module.
- No task state management, no progress tracking, no cancellation support.

**Assessment:** The 4-5 PD estimate for Phase 3C is **tight**. Needs: (a) add `sse-starlette` to project deps, (b) task registry with ID/status/progress tracking, (c) SSE endpoint for progress streaming, (d) background task runner (likely `anyio.create_task_group`), (e) cancellation support, (f) task persistence across restarts. Consider 6-8 PD.

---

## 6. Security Gap Verification

**Verdict: 2 NEW findings, 3 confirmed existing gaps**

### NEW FINDING R4-SEC-1: `usage.py` missing symlink rejection (Medium)
- **File:** `src/ahadiff/llm/usage.py` line 59
- `connect_usage_db()` calls `sqlite3.connect(db_path)` with **no `_reject_symlink_db()` check**.
- Compare with `review/database.py` line 104 which properly calls `_reject_symlink_db(db_path)` before `sqlite3.connect()`.
- Attack: symlink `usage.sqlite` to arbitrary file -> SQLite creates/corrupts target.

### NEW FINDING R4-SEC-2: `cli.py` doctor command missing symlink rejection (Low)
- **File:** `src/ahadiff/cli.py` line 593
- `sqlite3.connect(review_path)` in doctor/check command has no symlink pre-check.
- Lower severity since doctor is read-only diagnostic, but still follows symlink.

### Confirmed existing gaps from plan section 13:
- **`_has_windows_reparse_point`**: Confirmed in `src/ahadiff/improve/loop.py` line 949, `_FILE_ATTRIBUTE_REPARSE_POINT = 0x400` at line 63. 16 call sites. Working correctly.
- **`O_NOFOLLOW` in routes_runs.py**: Confirmed in `_read_text_capped()` and `_hash_bounded_finalized_artifact()` -- both use `getattr(os, "O_NOFOLLOW", 0)` graceful degradation. Working correctly.
- **`_reject_symlink_db` in database.py**: Confirmed at line 89-95, `lstat()` + `S_ISLNK` check before `sqlite3.connect()`. Working correctly.

---

## 7. Serve API Current State

**Verdict: PASS -- Corrected count is 22 concrete + 1 catchall = 23 Route() total**

**Evidence from `src/ahadiff/serve/app.py` lines 48-74:**

| # | Method | Endpoint | Source |
|---|--------|----------|--------|
| 1 | GET | `/healthz` | app.py |
| 2 | GET | `/api/auth/token` | app.py |
| 3 | GET | `/api/locale` | routes_locale.py |
| 4 | PUT | `/api/locale` | routes_locale.py |
| 5 | GET | `/api/runs` | routes_runs.py |
| 6 | GET | `/api/run/{run_id}` | routes_runs.py |
| 7 | GET | `/api/run/{run_id}/lesson` | routes_runs.py |
| 8 | GET | `/api/run/{run_id}/claims` | routes_runs.py |
| 9 | GET | `/api/run/{run_id}/quiz` | routes_runs.py |
| 10 | GET | `/api/run/{run_id}/diff` | routes_runs.py |
| 11 | GET | `/api/run/{run_id}/concepts` | routes_runs.py |
| 12 | GET | `/api/concepts` | routes_runs.py |
| 13 | GET | `/api/ratchet/history` | routes_runs.py |
| 14 | GET | `/api/review/queue` | routes_review.py |
| 15 | POST | `/api/review/rate` | routes_review.py |
| 16 | GET | `/api/config` | routes_config.py |
| 17 | GET | `/api/doctor` | routes_config.py |
| 18 | GET | `/api/install/targets` | routes_install.py |
| 19 | POST | `/api/signals/mark-wrong` | routes_signals.py |
| 20 | POST | `/api/signals/quiz-answer` | routes_signals.py |
| 21 | POST | `/api/signals/srs-review` | routes_signals.py |
| 22 | POST | `/api/signals/helpfulness` | routes_signals.py |
| **23** | **ALL** | `/api/{path:path}` | app.py (catchall) |

**Total Route() count from grep: 23** (matches `grep -c 'Route(' app.py` = 23).

Plan claims "22 concrete + 1 catchall" which matches exactly: 22 named endpoints + 1 `api_not_found` catchall that handles GET/POST/PUT/DELETE/PATCH/OPTIONS/HEAD.

Serve code totals 1,293 lines across 7 route files.

---

## 8. Provider Architecture

**Verdict: PASS -- Ready for extension**

**Evidence:**
- `src/ahadiff/llm/provider.py` has well-structured extension points: `Provider` Protocol (line 63), `AdapterBase` ABC (line 70), `ManagedProvider` class (line 136).
- `make_provider()` (line 676) is the factory with configurable: `max_concurrent`, `qps_limit`, `retry_attempts`, `request_timeout_seconds`, `response_byte_cap`, `circuit_failure_threshold`, `input_token_budget`, `output_token_budget`.
- `transport_target_for_base_url()` (line 635) has local/remote classification with IP resolution.
- Cache key is 13-dimensional: `CacheKeyInput` class at `src/ahadiff/llm/cache.py` line 48 with `build_cache_key()`.
- Streaming byte cap + circuit breaker + rate limiter + semaphore already implemented.

**Assessment:** Provider architecture is mature and ready for the new APIs planned in v1.0. Adding new adapters follows established patterns.

---

## 9. Install Targets

**Verdict: PASS -- 13 targets confirmed**

**Evidence from `src/ahadiff/install/registry.py` lines 39-53:**

1. `aider` (AiderTarget)
2. `claude` (ClaudeTarget)
3. `cline` (ClineTarget)
4. `codex` (CodexTarget)
5. `continue` (ContinueTarget)
6. `copilot` (CopilotTarget)
7. `cursor` (CursorTarget)
8. `gemini` (GeminiTarget)
9. `github-action` (GitHubActionTarget)
10. `hooks` (HooksTarget)
11. `opencode` (OpenCodeTarget)
12. `roo` (RooTarget)
13. `windsurf` (WindsurfTarget)

All 13 concrete `*Target` classes confirmed with separate `.py` files + `InstallTarget` Protocol in `base.py`. Templates directory present.

---

## Summary: Issues Requiring Plan Revision

### NEW Findings (not caught in R1-R3)

| ID | Severity | File | Issue |
|----|----------|------|-------|
| **R4-SEC-1** | Medium | `src/ahadiff/llm/usage.py:59` | `connect_usage_db()` missing `_reject_symlink_db()` before `sqlite3.connect()` -- symlink attack vector on `usage.sqlite` |
| **R4-SEC-2** | Low | `src/ahadiff/cli.py:593` | Doctor command `sqlite3.connect(review_path)` missing symlink pre-check |

### PD Estimate Adjustments

| Phase | Plan PD | Recommended PD | Reason |
|-------|---------|----------------|--------|
| 1C FSRS Optimizer | 3-4 | 5-7 | Zero optimizer infrastructure exists; need optimizer pipeline + validation + staged rollout |
| 3C Task Queue + SSE | 4-5 | 6-8 | No task infrastructure; `sse-starlette` not in project deps; need full task lifecycle |
| 6B Orchestrator Extract | 7-10 | 7-10 (keep) | Feasible but plan should note sync-to-async transition complexity |

### Dimensions Summary

| # | Dimension | Verdict |
|---|-----------|---------|
| 1 | Orchestrator Gap | WARNING -- sync/async transition undermentioned |
| 2 | FSRS Optimizer | WARNING -- 3-4 PD optimistic, recommend 5-7 |
| 3 | Concepts Migration | PASS |
| 4 | FTS5 Feasibility | PASS |
| 5 | Background Task Queue | WARNING -- 4-5 PD tight, recommend 6-8 |
| 6 | Security Gaps | 2 NEW + 3 confirmed |
| 7 | Serve API State | PASS -- 22+1 confirmed |
| 8 | Provider Architecture | PASS |
| 9 | Install Targets | PASS -- 13 confirmed |
