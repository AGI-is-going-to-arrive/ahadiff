# H1 / H2 / H5 Implementation Notes

> Current-truth notes for the backend error code system, per-request locale, and
> locale persistence work landed on 2026-05-10.

---

## Summary

This started as a small plan for three gaps:

- **H1**: API errors should have stable codes, not raw English-only payloads.
- **H2**: run and artifact reads should honor each request's locale, not a
  process-wide fallback.
- **H5**: changing locale through `PUT /api/locale` should survive a serve
  restart.

The current implementation covers those three items and the related test surface.

---

## H1 — Backend Error Code System

### Current Shape

The contract lives in:

- `src/ahadiff/contracts/error_codes.py`
- `src/ahadiff/contracts/error_types.py`
- `src/ahadiff/serve/_errors.py`
- `src/ahadiff/serve/app.py`

`ErrorPayload` always includes:

```json
{
  "error_code": "INPUT_BAD_FIELD",
  "error": "fallback message",
  "status": 400
}
```

`details` is optional and only used for structured context such as validation
errors. Frontend code maps `error_code` to `errors.*` i18n keys and falls back to
the server message only when the key is unknown.

### Error Codes and Statuses

| Code | Status |
|------|--------|
| `LOCALE_INVALID` | 400 |
| `INPUT_INVALID_JSON` | 400 |
| `INPUT_VALIDATION` | 422 |
| `INPUT_BAD_FIELD` | 400 |
| `INPUT_UNKNOWN_KEYS` | 400 |
| `INPUT_PAGINATION` | 400 |
| `RUN_NOT_FOUND` | 404 |
| `RUN_ARTIFACT_NOT_FOUND` | 404 |
| `RUN_ARTIFACT_TOO_LARGE` | 413 |
| `RUN_ARTIFACT_INVALID` | 400 |
| `RUN_ID_INVALID` | 400 |
| `INSTALL_INVALID_MANIFEST` | 400 |
| `PROVIDER_NOT_FOUND` | 404 |
| `PROVIDER_TRANSPORT` | 502 |
| `PROVIDER_HTTP` | 502 |
| `AUTH_REQUIRED` | 401 |
| `LOOPBACK_DENIED` | 403 |
| `RATE_LIMITED` | 429 |
| `REQUEST_TIMEOUT` | 408 |
| `STORAGE_REVIEW_DB` | 500 |
| `STORAGE_USAGE_DB` | 500 |
| `STORAGE_FS` | 500 |
| `LOCK_CONFLICT` | 409 |
| `LESSON_LEVEL_INVALID` | 400 |
| `EXPORT_FORMAT_UNSUPPORTED` | 400 |
| `NOT_FOUND` | 404 |
| `INTERNAL_ERROR` | 500 |

There are 27 enum values and 27 `ERROR_STATUS` entries.

### Route Behavior

- `AhaDiffError` carries `code` and `details`.
- `serve/_errors.py:error_response()` builds the payload and falls back to 500 if
  the status mapping is missing.
- `serve/app.py` maps `JSONDecodeError`, `ValidationError`, `HTTPException`,
  `PermissionError`, and `AhaDiffError` into the same payload shape.
- Auth failures use `401/AUTH_REQUIRED`.
- Loopback and write-origin denials stay `403/LOOPBACK_DENIED`.
- Rate limits keep `retry_after` in both body and `Retry-After`.
- Internal storage/provider failures no longer expose local paths or stack traces
  through the public message.

### Frontend Mapping

`viewer/src/utils/error-codes.ts` exports:

```ts
export function getErrorMessage(
  t: TranslateFn,
  code: string | null | undefined,
  fallback: string,
): string
```

It uses `TranslationKey`, not `as any`. Both `en.json` and `zh-CN.json` have 27
matching `errors.*` entries.

---

## H2 — Per-Request Locale

### Current Shape

The shared helper is `src/ahadiff/serve/locale.py`:

```python
def request_locale(request: Request) -> Locale:
    state = serve_state(request)
    return resolve_locale(
        cookie_lang=request.cookies.get("ahadiff_lang"),
        accept_language=request.headers.get("accept-language"),
        cli_lang=state.cli_lang,
        config_lang=state.config_lang or state.locale,
    )
```

`resolve_locale()` then applies the full resolver order:

```text
cookie -> Accept-Language -> AHADIFF_LANG -> CLI lang -> config lang -> LANG -> en
```

### Adopted Routes

`serve/routes_runs.py` now uses `request_locale(request)` for:

- `GET /api/runs`
- `GET /api/run/{run_id}`
- run artifact content language fallback

`serve/routes_locale.py:get_locale` also uses the helper.

`state.locale` remains a fallback from startup/config state, not the active locale
for each run/artifact response.

---

## H5 — Locale Persistence

### Current Shape

`PUT /api/locale` now:

1. requires the local write token,
2. validates `lang` through `SetLocaleRequest`,
3. acquires `state.write_lock`,
4. writes top-level `lang` to `.ahadiff/config.toml`,
5. updates the in-memory serve state,
6. sets the `ahadiff_lang` cookie.

The write path is derived from `state.state_dir`, not from browser input:

```python
config_path = state.state_dir.parent / ".ahadiff" / "config.toml"
```

If persistence fails, the route returns a storage error instead of silently
changing only runtime state.

---

## Related Fixes

- Claim extraction now receives `output_lang` through the runtime path.
- Git commands resolve `git` through `shutil.which("git")`; missing git gives a
  clear `InputError`.
- Hook helper git calls have a bounded timeout and preserve path spaces by
  trimming only CR/LF.
- The generated verify workflow matrix includes `windows-latest`; Linux-only
  SQLite bootstrap is guarded with `runner.os == 'Linux'`, and Windows runs
  `ahadiff --version` instead of `verify --ci`.
- `viewer/src/utils/format.ts` exposes `FormatTexts`, localized byte labels, and
  deterministic compact-number fallback labels.

---

## Validation

Actual validation from this session:

```text
Targeted backend regression: 455 passed
Full backend unit suite: 2136 passed
ruff check src tests: passed
ruff format --check src tests: passed
pyright: 0 errors
viewer Vitest: 253 passed
viewer typecheck: passed
viewer build: passed
i18n scalar keys: 1011/1011
errors.* coverage: 27/27
Format.* coverage: 6/6
git diff --check: passed
```

Not rerun in this follow-up: integration tests, eval tests, live judge, coverage,
wheel build, Playwright, and remote GitHub Actions workflows.
