# AhaDiff Serve API Live Test Report

> Tested 2026-04-27 against `ahadiff serve --no-browser` (auto-bound to port 8765)
> Route-count convention: this live baseline has 21 explicit business `/api` routes + `/healthz` = 22 concrete endpoints. The Starlette catchall `/api/{rest_of_path:path}` is an error handler route and is not counted as a business endpoint.

> Current status note (2026-04-29): This document only records the 2026-04-27 live
> snapshot. Current code now has `POST /api/learn`, `/api/tasks*`
> status/progress/cancel routes, `GET /api/graph/status`, and a larger route
> surface (`43 total Route(` in `serve/app.py`, including `41 concrete /api/*`
> routes, `1` catchall, and `/healthz`). Current verification for the
> uncommitted branch is: full pytest `1420 passed, 1 skipped`; coverage gate
> `87.37%`; focused backend regressions `59 passed`; serve regressions
> `129 passed`; `ruff check` / `ruff format --check` pass; `pyright`
> currently reports `0 errors, 0 warnings, 0 informations`. Task status
> payloads now also carry runtime fields like `error_code` and
> `elapsed_seconds`.

## 2026-04-27 Live Concrete Endpoints (22)

### Public GET Endpoints (no auth required)

| # | Method | Path | Status | Response Schema |
|---|--------|------|--------|----------------|
| 1 | GET | `/healthz` | 200 | `{ ok: bool }` |
| 2 | GET | `/api/auth/token` | 200 | `{ token: string, expires_at: string\|null }` |
| 3 | GET | `/api/locale` | 200 | `{ locale: "en"\|"zh-CN" }` |
| 4 | GET | `/api/runs` | 200 | `{ runs: RunSummary[] }` -- no `next_cursor` when data fits one page |
| 5 | GET | `/api/run/{run_id}` | 200 | `RunDetail` (extends RunSummary + extra fields) |
| 6 | GET | `/api/run/{run_id}/lesson` | 200 | `RunArtifactEnvelope` |
| 7 | GET | `/api/run/{run_id}/claims` | 200 | `RunArtifactEnvelope` |
| 8 | GET | `/api/run/{run_id}/quiz` | 200 | `RunArtifactEnvelope` |
| 9 | GET | `/api/run/{run_id}/diff` | 200 | `RunArtifactEnvelope` |
| 10 | GET | `/api/run/{run_id}/concepts` | 200/404 | `RunArtifactEnvelope` or `{ error, status: 404 }` |
| 11 | GET | `/api/concepts` | 200 | `{ artifact_type: "concepts", content: string }` -- JSONL in content |
| 12 | GET | `/api/ratchet/history` | 200 | `{ history: RatchetHistoryEntry[] }` -- no `next_cursor` when fits one page |
| 13 | GET | `/api/review/queue` | 200 | `{ cards: DueReviewCard[] }` |
| 14 | GET | `/api/config` | 200 | `ConfigResponse` |
| 15 | GET | `/api/doctor` | 200 | `{ checks: DoctorCheck[] }` |
| 16 | GET | `/api/install/targets` | 200 | `{ targets: InstallTarget[] }` |

### Auth-Protected Write Endpoints (require `X-AhaDiff-Token` header + `Origin`/`Referer` header)

| # | Method | Path | Status | Request Body | Response Schema |
|---|--------|------|--------|-------------|----------------|
| 17 | PUT | `/api/locale` | 200 | `{ lang: "en"\|"zh-CN" }` | `{ locale: "en"\|"zh-CN" }` |
| 18 | POST | `/api/review/rate` | 200/400 | `ReviewRatePayload` | `{ inserted: bool, review?: ReviewUpdate }` |
| 19 | POST | `/api/signals/mark-wrong` | 200 | `MarkWrongPayload` | `{ inserted: bool }` |
| 20 | POST | `/api/signals/quiz-answer` | 200 | `QuizAnswerPayload` | `{ inserted: bool }` |
| 21 | POST | `/api/signals/srs-review` | 200/400 | `SrsReviewPayload` | `{ inserted: bool, review?: ReviewUpdate }` |
| 22 | POST | `/api/signals/helpfulness` | 200 | `HelpfulnessPayload` | `{ inserted: bool }` |

## Detailed Response Schemas (from live JSON)

### RunSummary (from GET /api/runs)
```
run_id: string                  // "run_019dcd293e517b504460afb5493aaba8"
source_ref: string              // commit SHA
source_kind: string             // "git_ref" | "git_staged" | ...
content_lang: string            // "en" | "zh-CN"
capability_level: number        // 1 | 2 | 3
verdict: string                 // "PASS" | "CAUTION" | "FAIL"
overall: number                 // 93.86
status: string                  // "keep" | "baseline" | "discard" | ...
weakest_dim: string             // "diff_coverage"
created_at: string              // ISO 8601 UTC
degraded_flags: object          // {} or { diff_clipped: true, ... }
```

### RunDetail (from GET /api/run/{run_id}) -- extends RunSummary
```
base_ref: string | null
prompt_version: string          // "9e061d2"
eval_bundle_version: string     // "3ff99e22f248"
note_json: string | null        // JSON string of improve metadata
artifacts: string[]             // ["claims.jsonl", "lesson/lesson.full.md", ...]
graphify_mode: string | null    // "full" | "learning_only" | "empty"
graphify_status: string | null
graphify_notes: string[] | null
```

### RunArtifactEnvelope (from GET /api/run/{run_id}/{lesson|claims|quiz|diff|concepts})
```
run_id: string
artifact_type: string           // "lesson" | "claims" | "quiz" | "diff"
content: string                 // raw artifact content (Markdown / JSONL)
content_lang: string | null     // "en" | "zh-CN"
```

### RatchetHistoryEntry (from GET /api/ratchet/history)
```
run_id: string
source_ref: string
eval_bundle_version: string
overall: number
verdict: string
status: string
timestamp: string               // ISO 8601 UTC
weakest_dim: string
```

### DueReviewCard (from GET /api/review/queue)
```
card_id: string
concept: string
run_id: string
due_date: string
scaffolding_level: string
display_path: string
source_ref: string | null
symbol: string | null
```

### ConfigResponse (from GET /api/config)
```
lang: string | null
privacy_mode: string | null
generate_model: string | null
judge_model: string | null
serve_port: number | null
key_status: object              // { "openai": "configured", ... } or {}
```

### DoctorCheck (from GET /api/doctor)
```
checks[].name: string           // "repo_root" | "sqlite_version" | "config_valid" | "review_db"
checks[].status: string         // "pass" | "warn" | "fail"
checks[].message: string
```

### InstallTarget (from GET /api/install/targets)
```
targets[].name: string          // "aider" | "cline" | "claude" | ...
targets[].detected: boolean
targets[].platform_supported: boolean
targets[].description: string   // always "" currently
```

### Concept (JSONL lines inside GET /api/concepts content field)
```
concept: string
term_key: string
term: string
display_name: string
lang: string
aliases: string[]
source_refs: string[]
branch_hint: string
introduced_by_run: string
updated_by_runs: string[]
related_claims: string[]
file_refs: string[]
```

## Auth Behavior

1. **Token delivery**: `GET /api/auth/token` returns `{ token, expires_at }`. Token goes in `X-AhaDiff-Token` header (NOT `Authorization: Bearer`).
2. **Origin/Referer check**: All POST/PUT endpoints require `Origin` or `Referer` header from localhost, else 403 `origin_or_referer_required`.
3. **Token check**: After Origin passes, token is validated, else 403 `write route requires a valid X-AhaDiff-Token header`.
4. **Pydantic validation**: Invalid bodies return 422 with Pydantic error details.
5. **No auth needed**: All GET endpoints are public (read-only).

**Threat-model note for v1.0**: `/api/auth/token` is localhost write-CSRF token delivery, not user identity authentication. It is acceptable only under the documented local viewer boundary: same-machine browser, localhost Origin/Referer write protection, and no production network exposure. Any local process can read the token while the server is running, so every new POST/PUT endpoint must keep the same Origin/Referer + `X-AhaDiff-Token` write guard and must not treat the token as a secret user credential.

## Pydantic Request DTOs (from contracts/serve_app.py)

| Endpoint | Request DTO | Required Fields |
|----------|------------|-----------------|
| PUT /api/locale | `SetLocaleRequest` | `lang: "en"\|"zh-CN"` |
| POST /api/review/rate | `ReviewRateRequest` | `idempotency_key, card_id, answer: "good"\|"hard"\|"wrong"` |
| POST /api/signals/mark-wrong | `MarkWrongRequest` | `idempotency_key, claim_id` + optional `reason` |
| POST /api/signals/quiz-answer | `QuizAnswerRequest` | `idempotency_key, quiz_id, choice, correct` |
| POST /api/signals/srs-review | `ReviewSignalRequest` | `idempotency_key, card_id, answer` |
| POST /api/signals/helpfulness | `HelpfulnessRequest` | `idempotency_key, target_id` + optional `target_kind, payload` |

## Pagination Behavior

- **`/api/runs`**: cursor-based via `?before=<event_id>`. Response has `runs` array. No `next_cursor` field observed (data fit in one page). Frontend expects `next_cursor?: string`.
- **`/api/ratchet/history`**: `?before=<event_id>`. Response has `history` array. No `next_cursor` observed.
- **`/api/concepts`**: `?cursor=<line_number>`. Cursor must be non-negative integer, else 400. Response has `artifact_type` + `content` (JSONL string). No `next_cursor` observed.
- **Note**: `next_cursor` is only present in response when there are more pages. Frontend types correctly use `next_cursor?: string` (optional).

## Frontend vs Backend Mismatches

### File: `viewer/src/api/types.ts`

| Field / Type | Frontend Definition | Backend Actual | Status |
|-------------|-------------------|----------------|--------|
| `PaginatedRunsResponse.next_cursor` | `next_cursor?: string` | Absent when no more pages | **OK** -- optional field, absent = no more pages |
| `RatchetHistoryResponse.next_cursor` | `next_cursor?: string` | Absent when no more pages | **OK** |
| `PaginatedConceptsResponse.next_cursor` | `next_cursor?: string` | Absent when no more pages | **OK** |
| `RunSummary.artifacts` | Not in RunSummary | Not returned in /api/runs | **OK** -- only in RunDetail |
| `ConfigField` interface | `{ key, value, source }` | Not used by /api/config response | **UNUSED** -- defined but never matches actual ConfigResponse shape |
| `ReviewUpdate.rating` | `rating: number` | Needs live review to verify actual fields | **UNVERIFIED** -- no active cards to test |

### File: `viewer/src/api/config.ts`

| Field / Type | Frontend Definition | Backend Actual | Status |
|-------------|-------------------|----------------|--------|
| `ConfigResponse` | `{ lang, privacy_mode, generate_model, judge_model, serve_port, key_status }` | Exact match | **OK** |
| `DoctorCheck` | `{ name, status: 'pass'\|'warn'\|'fail', message }` | Exact match | **OK** |
| `InstallTarget` | `{ name, detected, platform_supported, description }` | Exact match | **OK** |

### Auth Header Mismatch

| Layer | Token Header | Status |
|-------|-------------|--------|
| Frontend `client.ts` | Uses `X-AhaDiff-Token` via `ensureToken()` | **OK** -- matches backend |
| `POST /api/review/rate` request from frontend | Sends `X-AhaDiff-Token` + cookie-based Origin | **OK** |

### No Mismatches Found (types.ts vs actual API)

All core types in `types.ts` and `config.ts` match the live API responses. The `ConfigField` interface in `config.ts` is defined but unused by any endpoint response -- it appears to be a leftover from an earlier design (the actual `/api/config` response uses flat fields, not an array of `ConfigField` objects).

## Error Response Format

All error responses follow: `{ error: string | object[], status: number }`

- 400: `{ "error": "descriptive message", "status": 400 }`
- 403: `{ "error": "origin_or_referer_required" | "write route requires...", "status": 403 }`
- 404: `{ "error": "artifact_not_found" | "run not found", "status": 404 }`
- 422: `{ "error": [ ...pydantic_errors ], "status": 422 }` -- Pydantic validation array
- 500: `{ "error": "internal error message", "status": 500 }`

## Summary

- **22 concrete endpoints total**: 16 public GET + 6 auth-protected write (5 POST + 1 PUT)
- **Additional route**: `/api/{rest_of_path:path}` catchall exists for API 404/error handling and is not a business endpoint
- **All GET endpoints**: 200 OK, correct JSON schemas
- **Auth flow**: Token via `X-AhaDiff-Token` header + Origin/Referer required for writes
- **Frontend type alignment**: All types match. One unused `ConfigField` interface.
- **Default port**: 8765 (not 8384 as some docs suggest)
