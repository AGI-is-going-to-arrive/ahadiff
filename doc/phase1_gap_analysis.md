# Phase 1 Gap Analysis Report (2026-05-10)

This file records the pre-fix gap scan and the current fix status from the same
session. It is not a release note and does not claim that every open item below
has been fixed.

## Baseline

| Check | Pre-fix Snapshot | Current Session Result |
|-------|------------------|------------------------|
| Backend pytest unit | 2130 passed | 2136 passed |
| Targeted backend regression | not recorded in the initial scan | 455 passed |
| Ruff lint | All checks passed | All checks passed |
| Ruff format check | not listed in the initial scan | 251 files already formatted |
| Pyright type check | 0 errors, 0 warnings | 0 errors, 0 warnings |
| Frontend Vitest | 250 passed, 24 files | 253 passed |
| Frontend typecheck/build | build PASS | typecheck PASS, build PASS |
| i18n shape | 969-key shape parity | 1011/1011 scalar keys; `errors.*` 27/27; `Format.*` 6/6 |

Not rerun in this follow-up: integration tests, eval tests, live judge, coverage,
wheel build, Playwright, and remote GitHub Actions workflows.

## Backend-Frontend Route Coverage

| Backend Route | Frontend Consumer | Gap? |
|--------------|-------------------|------|
| 61 concrete `/api/*` routes + 1 catch-all | main product surfaces covered | See below |

### Covered

- Health/Auth/Locale, Runs/Artifacts, Improve/Preflight, Review/SRS
- Search, Audit, Stats/Usage/Spec, Config/Doctor, Install, Providers
- Signals, Graph, Database, Learn, Tasks/SSE, Watch

### Minor Gaps

- `/api/concepts` non-ledger pagination is still not the primary Concepts UI path;
  the frontend mainly uses `/api/concepts/ledger`.
- `/healthz` is not called by the frontend. This is fine because it is a
  monitoring endpoint.

## Severity-Ranked Issues

### HIGH

| ID | Issue | Current status | Notes |
|----|-------|----------------|-------|
| H1 | Backend error messages English-only / raw payloads | Fixed in this session | API errors now use stable `{error_code,error,status,details?}` payloads. `errors.*` i18n coverage is 27/27. |
| H2 | Per-request locale not honored for run/artifact reads | Fixed in this session | `serve/locale.py:request_locale()` is used by run list/detail/artifact routes. |
| H3 | CLI output has broad English-only surface | Open | Not handled in this follow-up. |
| H4 | Claim prompt language not threaded | Partially fixed in this session | Claim extraction now receives `output_lang`; this note does not claim eval/improve prompt text was fully localized. |
| H5 | `PUT /api/locale` did not persist to config.toml | Fixed in this session | The route writes top-level `lang` under the serve repo's `.ahadiff/config.toml` while holding `state.write_lock`. |
| H6 | LandingPage i18n gap | Already covered in current code | The page imports `useTranslation`; no production edit was needed here. |
| H7 | Frontend error fallbacks rely on raw server text | Improved in this session | `ApiError.errorCode` plus `viewer/src/utils/error-codes.ts` let UI map stable codes to localized strings. |

### MEDIUM

| ID | Issue | Current status | Notes |
|----|-------|----------------|-------|
| M1 | Windows missing from generated verify workflow | Fixed in this session | Matrix now includes `windows-latest`; Windows runs CLI load smoke while `verify --ci` stays non-Windows. |
| M2 | Hooks target unsupported on Windows | Open / intentional v0.1 boundary | POSIX shell hooks still reject Windows. |
| M3 | Hardcoded `git` command path | Fixed in this session | Git calls now resolve through `shutil.which("git")` and fail clearly when git is missing. |
| M4 | `formatBytes` / compact suffixes not i18n'd | Fixed in this session | `FormatTexts` and `Format.*` keys cover byte and compact-number labels. |
| M5 | CSS `:has()` reliance on older Firefox | Not handled here | Left for the broader browser-baseline pass. |
| M6 | Min-browser baseline documentation | Not handled here | No new browser baseline was documented in this follow-up. |
| M7 | Git encoding fallback on Windows | Not handled here | No cp936-specific change was made. |
| M8 | CLI `--lang` flag not globally available | Not handled here | Existing per-command/config language behavior remains. |

### LOW

| ID | Issue | Current status |
|----|-------|----------------|
| L1 | macOS `/private` path canonicalization | Already handled elsewhere |
| L2 | Linux no-display heuristic missing `XDG_SESSION_TYPE` | Open |
| L3 | `navigator.language` fallback only en/zh | Open |
| L4 | Font stack not bundled | Open |
| L5 | PWA scope `./` limitation | Open |
| L6 | Cookie missing `Secure` flag | Accepted local-first tradeoff |
| L7 | No RTL support | Not needed for current en/zh-CN scope |
| L8 | CSP `style-src 'unsafe-inline'` | Open |
| L9 | `formatCurrency` defaults to USD only | Open |

## Strengths (No Action Needed)

- Comprehensive Windows reparse point detection
- NFC normalization and long-path warnings
- WSL2 mount detection
- portalocker for cross-platform locking
- i18n catalog shape parity
- CSS feature detection in the current viewer styles
- Zod schema validation on API responses
- Same-origin guard in apiFetch
- Idempotency keys for quiz signals

## Next Steps

- Keep H3 / M2 / M5-M8 as separate work; they were not fixed by this follow-up.
- If browser-baseline docs are added later, tie them to real CSS support checks and
  actual Playwright or browser runs.
- If CLI i18n is tackled later, audit command output separately instead of
  treating this API-error work as full CLI localization.
