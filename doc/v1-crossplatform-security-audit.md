# v1.0 Cross-Platform Security Audit Report

> Auditor: Claude Opus 4.6 | Date: 2026-04-27 | Scope: `src/ahadiff/` full codebase

> 2026-04-28 addendum: the current branch now has centralized `core/json_util.py` and
> `core/sqlite_util.py`, and `cli.py` doctor's old symlink gap is closed. The findings
> below should be read as "remaining call sites not yet fully migrated," not as a claim
> that the whole branch still lacks those helpers.

---

## 1. sqlite3.connect — Symlink / Reparse Point Audit

| # | File:Line | Pre-connect symlink check? | Windows reparse? | Verdict |
|---|-----------|---------------------------|-------------------|---------|
| 1 | `review/database.py:105` (`connect_review_db`) | YES — `_reject_symlink_db()` at line 104 | **NO** — only checks `S_ISLNK`, no `st_file_attributes & 0x400` | **GAP (Medium)** |
| 2 | `review/database.py:131` (`_connect_review_db_maintenance`) | YES — `_reject_symlink_db()` at line 130 | **NO** — same function, no reparse check | **GAP (Medium)** |
| 3 | `llm/usage.py:59` (`connect_usage_db`) | **NO** — zero symlink check before connect | N/A | **GAP (High)** |
| 4 | `cli.py:625` (doctor command) | YES — `reject_symlink_path(review_path)` at line 627 | N/A | **SAFE** |

### Detail

- **`_reject_symlink_db`** (database.py:88-95) only does `stat.S_ISLNK(st.st_mode)`. On Windows, NTFS junctions and directory symlinks created via `mklink /J` are reparse points that `S_ISLNK` does NOT detect. The codebase already has `_has_windows_reparse_point()` (checking `st_file_attributes & 0x400`) in `core/paths.py`, `improve/loop.py`, and `git/capture.py` — but it is NOT used in `_reject_symlink_db`.
- **`connect_usage_db`** (usage.py:59) has zero pre-connect defense. An attacker who can plant a symlink at `~/.config/ahadiff/usage.sqlite` could redirect writes to an arbitrary location.
- **`cli.py:625`** doctor command now rejects symlinked `review.sqlite` before opening the database. This old gap is closed in the current branch.

---

## 2. os.open — O_NOFOLLOW Audit

All 12 `os.open` call sites use `getattr(os, "O_NOFOLLOW", 0)` for graceful Windows degradation. On Windows, `O_NOFOLLOW` is absent, so the flag evaluates to 0 — the open proceeds without symlink protection. Every call site compensates with pre-open `lstat()` + `S_ISLNK` checks, and most also check `_has_windows_reparse_point`.

| # | File:Line | O_NOFOLLOW? | Pre-lstat? | Reparse check? | inode verify? | Verdict |
|---|-----------|-------------|------------|----------------|---------------|---------|
| 1 | `safety/audit.py:224` | YES | YES (`validate_state_path_no_symlinks`) | YES (via `validate_state_path_no_symlinks` which walks ancestors in `core/paths.py`) | YES (fstat vs lstat) | **SAFE** |
| 2 | `improve/loop.py:934` (`_assert_directory_no_follow`) | YES | YES | YES (Win branch checks reparse) | YES | **SAFE** |
| 3 | `improve/loop.py:1557` (program read) | YES | YES | YES | YES | **SAFE** |
| 4 | `eval/results.py:242` | YES | YES (expected_stat param) | NO explicit reparse check on `expected_stat` | YES | **GAP (Low)** — caller passes stat from `os.lstat`; reparse checked by caller context |
| 5 | `serve/routes_runs.py:584` (`_read_text_capped`) | YES | **NO** pre-lstat | NO reparse check | NO inode verify | **GAP (Medium)** — relies only on O_NOFOLLOW which is no-op on Windows |
| 6 | `serve/routes_runs.py:683` (`_bounded_finalized_artifact_digest`) | YES | YES (via scandir stat) | NO explicit reparse | YES | **GAP (Low)** |
| 7 | `git/capture.py:1376` (`_open_compare_dir_root_fd`) | YES | YES | YES | YES | **SAFE** |
| 8 | `git/capture.py:1485` (`_open_child_compare_directory_fd`) | YES | YES | YES (via `_has_windows_reparse_point`) | YES | **SAFE** |
| 9 | `git/capture.py:1535` (`_read_regular_file_no_follow_bounded`) | YES | YES | YES | YES | **SAFE** |
| 10 | `git/capture.py:1589` (`_read_regular_file_from_dir_fd`) | YES | YES | YES | YES | **SAFE** |
| 11 | `git/repo.py:236` (`repo_write_lock`) | YES | YES | YES | YES (triple check) | **SAFE** |
| 12 | `git/repo.py:299` (`unlock_repo_write_lock`) | YES | YES | YES | YES | **SAFE** |

---

## 3. subprocess — Encoding Audit

| # | File:Line | Function | encoding="utf-8"? | errors="replace"? | Verdict |
|---|-----------|----------|-------------------|--------------------|---------|
| 1 | `git/repo.py:64` (`run_git`) | `subprocess.run` | YES | YES | **SAFE** |
| 2 | `git/repo.py:89` (`run_git_bytes`) | `subprocess.run` | N/A (text=False, binary mode) | N/A | **SAFE** |
| 3 | `install/hooks.py:141` (`_git_path`) | `subprocess.run` | YES | YES | **SAFE** |
| 4 | `install/hooks.py:181` (`_git_directory_path`) | `subprocess.run` | YES | YES | **SAFE** |
| 5 | `improve/loop.py:1223` (replay learn) | `subprocess.run` | YES | YES | **SAFE** |
| 6 | `improve/loop.py:1269` (replay with interrupt) | `subprocess.Popen` | YES | YES | **SAFE** |
| 7 | `git/capture.py:1931` (`_run_git_patch_text`) | `subprocess.Popen` | **NO** — binary mode, manual decode via `_decode_text_bytes` | N/A (correct — reads bytes then decodes) | **SAFE** |

**Summary**: All text-mode subprocess calls have explicit `encoding="utf-8", errors="replace"`. Binary-mode calls decode manually. No gaps.

---

## 4. Platform Branching Completeness

| # | File:Line | Check | Platforms handled | Default/else? | WSL2? | Verdict |
|---|-----------|-------|-------------------|---------------|-------|---------|
| 1 | `install/hooks.py:22,133` | `sys.platform == "win32"` | Win32 explicit reject | YES (non-win32 proceeds) | N/A (POSIX path) | **SAFE** |
| 2 | `core/paths.py:33` | `sys.platform` passthrough | All (returns platform string) | YES | YES (`is_wsl2_mnt` separate) | **SAFE** |
| 3 | `cli.py:205` | `sys.platform.startswith("linux")` | Linux (headless check) | YES (non-Linux skips DISPLAY check) | YES (Linux path covers WSL2) | **SAFE** |
| 4 | `improve/loop.py:926` | `sys.platform.startswith("win")` | Win reparse check branch | YES (non-win uses O_NOFOLLOW+O_DIRECTORY) | N/A | **SAFE** |
| 5 | `improve/loop.py:1297,1319` | `sys.platform.startswith("win")` | Win process termination | YES (non-win uses SIGTERM) | N/A | **SAFE** |
| 6 | `git/capture.py:1095` | `os.name == "nt"` | NT vs POSIX | YES | N/A (git quoting) | **SAFE** |
| 7 | `git/capture.py:1371` | `sys.platform.startswith("win")` | Win returns None for dir_fd | YES (non-win opens dir_fd) | N/A | **SAFE** |

**WSL2 handling**: Dedicated `is_wsl2_mnt()` in `core/paths.py` checks `WSL_DISTRO_NAME`, `WSL_INTEROP`, `WSL2_GUI_APPS_ENABLED` env vars + `/mnt/*` path prefix. Used by `review/database.py` and `llm/usage.py` for SQLite journal mode degradation.

---

## 5. Path Handling — os.path Legacy

- **`os.path.*`**: **ZERO** hits. Fully migrated to pathlib.
- **`os.sep` / `os.pathsep` / `ntpath` / `posixpath`**: **ZERO** hits.

**Verdict**: **CLEAN** — no legacy path handling.

---

## 6. Temp File Safety

| # | File:Line | Method | Secure permissions? | Cleanup? | Verdict |
|---|-----------|--------|---------------------|----------|---------|
| 1 | `llm/cache.py:132` | `NamedTemporaryFile(delete=False)` | Default (0o600 on Unix) | YES — `finally: unlink` | **SAFE** |
| 2 | `install/base.py:226` | `mkstemp(dir=..., suffix=...)` | YES (mkstemp is 0o600) | YES — `finally: unlink` in caller | **SAFE** |
| 3 | `core/config.py:402` | `NamedTemporaryFile(delete=False)` | Default | YES — atomic replace | **SAFE** |
| 4 | `quiz/generator.py:452` | `NamedTemporaryFile(delete=False)` | Default | YES — `except: unlink` + atomic replace | **SAFE** |
| 5 | `wiki/concepts.py:288` | `NamedTemporaryFile(delete=False)` | Default | YES — `except: unlink` + atomic replace | **SAFE** |
| 6 | `cli.py:394` | `mkstemp(prefix=..., suffix=..., dir=parent)` | YES | YES — unlink immediately, used as path only | **SAFE** |
| 7 | `cli.py:1191` | `NamedTemporaryFile(delete=False)` | Default | Cleanup via caller rollback logic | **SAFE** |
| 8 | `review/database.py:1708` | `mkstemp(prefix=..., suffix=..., dir=parent)` | YES | YES — unlink in finally | **SAFE** |
| 9 | `improve/loop.py:1152` | `mkstemp(prefix=..., suffix=..., dir=parent)` | YES | YES — cleanup in finally block | **SAFE** |
| 10 | `eval/results.py:494` | `mkstemp(prefix=..., suffix=..., dir=parent)` | YES | Unlink immediately, path-only usage | **SAFE** |
| 11 | `eval/benchmark.py:201` | `TemporaryDirectory(prefix=...)` | Default | YES — context manager auto-cleanup | **SAFE** |

**Note**: All `NamedTemporaryFile` calls use `delete=False` with explicit cleanup, avoiding the Windows issue where `delete=True` can fail due to file locking.

---

## 7. Previously Flagged Gaps — Verification

| # | Flagged Item | Still present? | Severity | Detail |
|---|-------------|----------------|----------|--------|
| 1 | `llm/usage.py` sqlite3.connect WITHOUT symlink check | **YES — CONFIRMED** | **High** | `connect_usage_db()` line 59 has zero symlink/reparse defense before `sqlite3.connect` |
| 2 | `cli.py` doctor sqlite3.connect WITHOUT symlink check | **NO — RESOLVED** | — | Current code calls `reject_symlink_path(review_path)` before `sqlite3.connect()` |
| 3 | `llm/provider.py` base_url only does local/remote classification, not SSRF blocking | **CONFIRMED — by design** | **Low** | `transport_target_for_base_url()` classifies local vs remote for audit routing only. SSRF blocking is in `git/download.py` for `--patch-url` (full chain: scheme allowlist + private IP block + DNS rebinding prevention + TLS SNI + redirect re-check + HTTPS downgrade rejection). Provider base_url is user-configured (BYOK), not attacker-controlled input, so SSRF blocking is not applicable. |

---

## Summary of Confirmed Gaps

### High Severity (must fix for v1.0)

| ID | File | Line | Description |
|----|------|------|-------------|
| **H-1** | `llm/usage.py` | 59 | `connect_usage_db()` — no symlink/reparse check before `sqlite3.connect`. Attacker with local write access can redirect `usage.sqlite` via symlink to overwrite arbitrary files. |

### Medium Severity (should fix for v1.0)

| ID | File | Line | Description |
|----|------|------|-------------|
| **M-1** | `review/database.py` | 88-95 | `_reject_symlink_db()` checks `S_ISLNK` only — does NOT check `st_file_attributes & 0x400` for Windows NTFS reparse points/junctions. The codebase has `_has_windows_reparse_point()` available in multiple modules. |
| **M-2** | `serve/routes_runs.py` | 584 | `_read_text_capped()` uses `O_NOFOLLOW` (no-op on Windows) without pre-lstat or reparse check. On Windows, could follow NTFS junctions. |

### Low Severity (track for v1.0)

| ID | File | Line | Description |
|----|------|------|-------------|
| **L-1** | `eval/results.py` | 242 | `_hash_finalized_artifact_file` — no explicit reparse check on `expected_stat`. Relies on caller context. |
| **L-2** | `serve/routes_runs.py` | 683 | `_bounded_finalized_artifact_digest` — no explicit reparse check in scandir loop. |

---

## Recommended Fixes

### H-1: Add symlink defense to `connect_usage_db`

```python
# In llm/usage.py, before sqlite3.connect:
def _reject_symlink_usage_db(db_path: Path) -> None:
    try:
        st = db_path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(st.st_mode):
        raise InputError(f"usage.sqlite is a symlink: {db_path}")
    if _has_windows_reparse_point(st):
        raise InputError(f"usage.sqlite is a Windows reparse point: {db_path}")
```

### M-1: Add reparse check to `_reject_symlink_db`

```python
# In review/database.py:
def _reject_symlink_db(db_path: Path) -> None:
    try:
        st = db_path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(st.st_mode):
        raise StorageError(f"review.sqlite is a symlink: {db_path}")
    if _has_windows_reparse_point(st):  # ADD THIS
        raise StorageError(f"review.sqlite is a Windows reparse point: {db_path}")
```

### M-2: Add symlink check to doctor command

```python
# In cli.py doctor, before sqlite3.connect:
if review_path.is_symlink():
    console.print("[red]review.sqlite is a symlink — refusing to open[/red]")
else:
    with sqlite3.connect(review_path) as connection:
        ...
```

### M-3: Add pre-lstat to `_read_text_capped`

Add `lstat()` + `S_ISLNK` + reparse check before `os.open` in `_read_text_capped`.
