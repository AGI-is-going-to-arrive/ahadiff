# Cross-Platform Compatibility Audit Report

**Date**: 2026-04-28
**Scope**: New and changed files — json_util.py, sqlite_util.py, allowlist.yaml, benchmark scripts, cli.py lazy imports, middleware.py

---

## Current Re-check

The confirmed portability bugs from the first pass are closed in the current branch.

| # | Severity | File | Line(s) | Platform | Issue |
|---|----------|------|---------|----------|-------|
| 1 | **INFO** | `run_all.sh`, `bench_bundle_size.sh` | 1 | Windows | These wrappers still require bash. This is an intentional tool boundary, not a current bug. |
| 2 | **INFO** | `bench_api_latency.py` | — | All | Returns `status=skipped` until a local `ahadiff serve` is running. This is expected. |

Current verification used for the re-check:

- `uv run pytest tests -q --tb=long` → `845 passed, 1 skipped`
- `uv run pyright` → `0 errors`
- `uv run python benchmarks/scripts/bench_diff_parse.py` → `status=ok`
- `uv run python benchmarks/scripts/bench_sqlite_queries.py` → `status=ok`
- `AHADIFF_BENCH_PYTHON="$(pwd)/.venv/bin/python" bash benchmarks/scripts/run_all.sh` → aggregate JSON written successfully

---

## Findings Summary

No confirmed High / Medium / Low portability bug remains in the audited Phase 0 files after the current fixes.

---

## Detailed Analysis by Check

### CHECK 1: New Files

**json_util.py** — No platform-specific behavior. The current helper now rejects `NaN` / `Infinity` and overflow floats such as `1e309` consistently on every platform.

**sqlite_util.py** — The Windows read-only URI issue is fixed. The helper now builds `/C:/...` style SQLite URIs, rejects dangling symlinks before connect, and keeps the `st_file_attributes & 0x400` reparse-point fallback.

**allowlist.yaml** — Plain YAML with comments and an empty list `[]`. PyYAML/ruamel.yaml parse this identically on all platforms. Clean.

**Benchmark scripts** — The runner now resolves project Python explicitly (`AHADIFF_BENCH_PYTHON` or `.venv`) and validates every child JSON payload before aggregation. The shell wrappers still assume bash by design.

### CHECK 2: sqlite_util.py Deep Platform Audit

1. **`os.lstat()` on Windows**: Correctly returns `S_ISLNK` for symbolic links on Python 3.11+ Windows. For junction points, `S_ISLNK` returns False, but the `st_file_attributes & 0x400` check on line 62 correctly catches both symlinks and junctions via `FILE_ATTRIBUTE_REPARSE_POINT`. The `getattr` with default 0 is correct defensive code.

2. **`sqlite3.connect()` with URI**: the current helper uses a dedicated `_read_only_sqlite_uri()` path builder and percent-encodes only what SQLite URI parsing needs escaped, while preserving `/C:/...` drive-letter form on Windows.

3. **`PermissionError` messages**: Windows paths with backslashes display correctly in Python exception messages. No issue.

### CHECK 3: cli.py Lazy Imports

1. **`__package__` reliability**: When executed as `python -m ahadiff`, `__package__` is `"ahadiff"`. When run via console_scripts entry point, the entry point calls a function inside the package, so `__package__` is also `"ahadiff"`. When imported directly, `__package__` follows normal package semantics. All three paths are correct. No issue.

2. **`@cache` thread-safety**: `functools.cache` (alias for `lru_cache(maxsize=None)`) uses a C-level lock on CPython. Thread-safe on all platforms. No issue.

### CHECK 4: Middleware Changes

1. **`urlparse()` behavior**: `urllib.parse.urlparse` is pure Python and fully cross-platform. `parsed.hostname` always returns lowercase. No platform differences. Clean.

2. **HTTP header case sensitivity**: Starlette normalizes all header names to lowercase internally via `MutableHeaders`. The code uses `.get("origin")`, `.get("referer")`, `.get("content-type")`, etc. — all lowercase. Correct on all platforms. No issue.

### CHECK 5: Benchmark Scripts

1. **`bench_bundle_size.sh`** still delegates file size measurement to Python via `path.stat().st_size`. The only remaining platform boundary is bash availability.

2. **`run_all.sh`** now uses `#!/usr/bin/env bash`, pins the project interpreter, and writes fallback error JSON when a child script exits non-zero or prints invalid JSON.

3. **`bench_cli_startup.py`** now runs under the interpreter supplied by the caller. The Windows-specific `bin/python` assumption that existed in the first pass is no longer present in the committed runner flow.

4. **`bench_diff_parse.py`** generates diffs with LF endings in-process. No CRLF issue (finding #11).

### CHECK 6: Shell Script POSIX Compliance

Both `run_all.sh` and `bench_bundle_size.sh`:
- Use `#!/usr/bin/env bash` — explicit bash requirement, but portable across common macOS/Linux environments that expose `bash` on `PATH`
- Use bash-specific `${BASH_SOURCE[0]}` — acceptable since shebang declares bash
- Use `[[ ]]` double brackets — bash-only, not POSIX `[ ]`
- Use `local` keyword — bash extension (though widely supported)
- Use `set -u -o pipefail` — bash extension
- Handle paths with spaces correctly via proper quoting
- Do NOT use GNU coreutils-only features (no `stat --format`, no `find -printf`)
- Do NOT use macOS-only features
- Properly use `trap ... EXIT` for cleanup

---

## Recommended Fixes

No additional code fix is required in the audited Phase 0 scope at the time of this re-check. The current remaining boundary is operational: Windows users still need a bash environment for the shell wrappers.

---

## Items Confirmed Correct (No Action Needed)

- `json_util.py`: Fully cross-platform, including finite-number rejection
- `allowlist.yaml`: Standard YAML, no platform concerns
- `cli.py` `__package__` + `@cache`: Correct on all execution modes and platforms
- `middleware.py` `urlparse()`: Cross-platform, headers case-insensitive via Starlette
- `sqlite_util.py` `_reject_symlink`: Correctly handles symlinks, dangling symlinks, and NTFS reparse points
- `sqlite_util.py` `st_file_attributes`: Defensive `getattr` pattern is correct
- `bench_diff_parse.py` line endings: LF-only generation is correct for unified diff
- Shell scripts: No GNU-only or macOS-only coreutils usage; paths properly quoted
