# AhaDiff Cross-Platform Compatibility Audit

> Research date: 2026-04-26 | Scope: Windows / Linux / macOS / Universal

---

## Windows

### W-1. subprocess encoding on CJK Windows (Critical)

`subprocess.run(..., text=True)` decodes stdout using the system locale (cp936 on Chinese Windows, cp950 on Traditional Chinese). Git for Windows outputs UTF-8 by default. This mismatch causes `UnicodeDecodeError` in `_readerthread`, crashing diff parsing silently. CPython issue #105312 confirms this is a known footgun; Python 3.15 will default to UTF-8 in subprocess, but 3.11-3.14 do not.

**Mitigation (code change required):** All `subprocess.run/Popen` calls must pass `encoding="utf-8"` explicitly (not `text=True`). Also set `env={...,"PYTHONUTF8":"1"}` for child Python processes. Wrap with `errors="replace"` as safety net.

### W-2. SQLite WAL mode file lock retention (High)

On Windows, closing a SQLite WAL-mode database does not release file locks immediately. The `.db` file remains locked (`EBUSY`) even after `close()` + checkpoint. This blocks file deletion/move in tests and cleanup. Additionally, Windows Defender can lock `.db` files during scanning, causing intermittent `database is locked` errors.

**Mitigation (code change required):** Run `PRAGMA wal_checkpoint(TRUNCATE)` before close on Windows. Add `.ahadiff/` to antivirus exclusion guidance in docs. Consider `PRAGMA locking_mode=EXCLUSIVE` for single-writer scenarios.

### W-3. portalocker shared lock semantics (High)

portalocker on Windows uses `win32file.LockFileEx` for exclusive locks but `msvcrt.locking()` does not support true shared locks -- `LOCK_SH` behaves identically to `LOCK_EX`. Cross-process read-during-write scenarios that work on POSIX will deadlock on Windows.

**Mitigation (code change required):** AhaDiff uses `LOCK_EX` for `ahadiff.lock`, so shared locks are not a current concern. Verify no code path requests `LOCK_SH`. Document this behavioral difference.

### W-4. NTFS reserved names and MAX_PATH (Medium)

NTFS reserves CON, PRN, AUX, NUL, COM1-9, LPT1-9 as filenames. A repo with a file named `aux.py` will fail on Windows. MAX_PATH (260 chars) still applies unless the user opts in via registry on Windows 10 1607+. Deep `.ahadiff/runs/<run_id>/` paths can exceed 260 chars.

**Mitigation (code change + docs):** Validate run_id length to keep total path < 200 chars. Document long path opt-in. Use `pathlib` consistently (handles `\\?\` prefix internally on Python 3.6+).

### W-5. Uvicorn --reload and signal handling (High)

Uvicorn `--reload` is broken or unreliable on Windows due to `CTRL_C_EVENT` propagation to the entire process group instead of just the child. `Ctrl+C` can freeze the terminal. The root cause is CPython's `multiprocessing.popen_spawn_win32` lacking `CREATE_NEW_PROCESS_GROUP` support.

**Mitigation (code change required):** Disable `--reload` on Windows in `ahadiff serve`. Use `--workers 1` (no multiprocess supervisor). Implement graceful shutdown via `CTRL_BREAK_EVENT` or polling instead of SIGTERM.

### W-6. Git for Windows CRLF and core.quotePath (Medium)

`core.autocrlf=true` (Windows default) converts LF to CRLF on checkout, affecting diff output. `core.quotePath=true` (default) escapes non-ASCII filenames in diff headers as octal sequences (e.g., `\344\270\255`), breaking Unicode filename parsing.

**Mitigation (code change required):** Run `git -c core.quotePath=false` for all git subprocess calls. Handle both `\n` and `\r\n` line endings in diff parser. Already have Unicode filename test (R5-BE-5), but need CRLF-in-diff test.

### W-7. webbrowser.open() (Low)

Works reliably on native Windows via `os.startfile()`. Ignores `new` and `autoraise` params. No issues expected.

**Mitigation (testing only):** Verify `--no-browser` flag works. No code change needed.

### W-8. rich on legacy cmd.exe (Low)

`rich` auto-detects terminal capabilities. Legacy cmd.exe (pre-Windows 10) lacks true-color support but `rich` degrades gracefully. Windows Terminal and modern PowerShell fully support rich output.

**Mitigation (testing only):** No code change needed. rich handles this internally.

### W-9. tempfile.mkdtemp permissions (Medium)

CVE-2024-4030: `mkdtemp()` on Windows may inherit overly permissive ACLs from parent directory in Python 3.8-3.12. Fixed in later patch versions. Also, AppContainer environments (Python 3.12.4+) may deny write access to created temp dirs.

**Mitigation (testing only):** Require Python >= 3.11.x with the CVE fix backported. Verify temp dir operations in CI.

### W-10. os.chmod on NTFS (Low)

`os.chmod()` on Windows only toggles read-only attribute. It cannot set Unix-style permissions. `stat.S_IRUSR` etc. are no-ops beyond read-only.

**Mitigation (code review):** Audit for any `os.chmod()` calls. Replace with platform-conditional logic or remove. AhaDiff lock file creation should not rely on chmod.

---

## Linux

### L-1. webbrowser.open() on headless servers (High)

On headless Linux (no X11/Wayland), `webbrowser.open()` either blocks waiting for a text browser or returns False silently. No `DISPLAY`/`WAYLAND_DISPLAY` means no graphical browser.

**Mitigation (code change required):** Check `os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")` before calling `webbrowser.open()`. Print URL to terminal as fallback. `--no-browser` already exists but auto-detection is needed.

### L-2. WSL2 SQLite WAL mode on /mnt/c/ (Critical)

SQLite WAL mode does not work on WSL2's 9P filesystem (`/mnt/c/`, `/mnt/d/`). Shared memory files (`.db-shm`) cannot be properly mapped across the WSL2/Windows boundary. This causes silent data corruption or `database is locked` errors.

**Mitigation (code change required):** Detect WSL2 + `/mnt/` paths (check `/proc/version` for "microsoft" + path prefix). Fall back to `journal_mode=DELETE` or warn user to keep `.ahadiff/` on the Linux filesystem (e.g., `~/`).

### L-3. Python 3.11 distro availability (Low)

Python 3.11 is available on: Fedora 37+ (as `python3.11`), Ubuntu 22.04+ (via deadsnakes PPA or 23.04+ native), Debian 12 (bookworm, as default), Arch (always latest). No concern for modern distros.

**Mitigation (docs only):** Document minimum Python 3.11 requirement. Recommend `pyenv` or `pipx` for older distros.

### L-4. SELinux/AppArmor (Low)

Default SELinux policies (Fedora/RHEL) and AppArmor profiles (Ubuntu) do not restrict user-space Python apps from creating directories or SQLite WAL files in home directories. Custom hardened policies could block, but this is rare for CLI tools.

**Mitigation (docs only):** Document that `.ahadiff/` must be in an accessible directory. No code change needed.

### L-5. XDG directories (Medium)

AhaDiff already uses `~/.config/ahadiff/` on Linux (matching XDG_CONFIG_HOME default). Should respect `$XDG_CONFIG_HOME` if set.

**Mitigation (code review):** Verify `global_config_dir()` checks `os.environ.get("XDG_CONFIG_HOME", "~/.config")` on Linux. Likely already correct per CLAUDE.md spec.

### L-6. systemd service for ahadiff serve (Low)

Standard `Type=simple` systemd unit with `ExecStart=ahadiff serve` works. Uvicorn handles signals correctly on Linux.

**Mitigation (docs only):** Provide example `.service` file in documentation.

---

## macOS

### M-1. Spotlight indexing of .ahadiff/ (Medium)

`.ahadiff/` is a dot-prefixed directory, which Spotlight skips by default on macOS. The older `.metadata_never_index` trick no longer works reliably on Sequoia+. The dot prefix is sufficient.

**Mitigation (none needed):** Dot-prefix already excludes from Spotlight. Verify with `mdls` in CI.

### M-2. Homebrew Python vs system Python (Low)

Homebrew Python and system Python coexist. `pip install` into system Python is restricted on macOS Ventura+ (`externally-managed-environment`). `pipx` or `uv` recommended.

**Mitigation (docs only):** Recommend `pipx install ahadiff` or `uv tool install ahadiff`.

### M-3. macOS Sequoia+ localhost binding (Low)

macOS Sequoia does not add new security prompts for localhost-only binding (127.0.0.1). Only non-localhost bindings (0.0.0.0) trigger the firewall dialog. AhaDiff binds localhost-only, so no prompt.

**Mitigation (none needed):** Already binding to 127.0.0.1 only.

### M-4. Apple Silicon SQLite/portalocker (Low)

No known ARM64-specific issues for SQLite or portalocker on Apple Silicon. The Python `sqlite3` module uses the system SQLite (3.43+ on macOS 14+), which fully supports WAL.

**Mitigation (none needed):** No code change needed.

---

## Universal

### U-1. datetime.utcnow() deprecation (High)

`datetime.utcnow()` is deprecated since Python 3.12 and emits `DeprecationWarning`. It returns a naive datetime that is NOT timezone-aware. This is a footgun for FSRS-6 scheduling where review intervals depend on accurate UTC timestamps.

**Mitigation (code change required):** Replace all `datetime.utcnow()` with `datetime.now(datetime.UTC)`. Audit FSRS-6 scheduling code to ensure all timestamps are timezone-aware UTC.

### U-2. Mixed CRLF/LF and BOM in files (Medium)

Git repos may contain files with mixed line endings or UTF-8 BOM. The diff parser must handle `\r\n` in diff output and BOM (`\xef\xbb\xbf`) at file start.

**Mitigation (code change required):** Strip `\r` from diff lines before parsing. Handle BOM in file content comparison. Add test cases for mixed-ending diffs.

### U-3. IPv4 vs IPv6 localhost binding (Medium)

`127.0.0.1` is IPv4-only. Some systems resolve `localhost` to `::1` (IPv6). If the serve backend binds to `127.0.0.1` but the browser requests `http://localhost:PORT/`, connection may fail on IPv6-preferred systems.

**Mitigation (code change required):** Bind to `127.0.0.1` explicitly (not `localhost` string). Document that the URL is `http://127.0.0.1:PORT/`. Alternatively, bind to both `127.0.0.1` and `::1`.

### U-4. Locale affecting string sorting (Low)

`LC_ALL`/`LANG` settings can affect Python's `locale.strxfrm()` and collation. AhaDiff uses concept IDs as keys, which should use byte-order sorting, not locale-dependent sorting.

**Mitigation (code review):** Ensure all sorting uses default Python `str` comparison (Unicode codepoint order), not `locale.strcoll()`. No change likely needed.

---

## Priority Summary

| # | Issue | Severity | Needs Code Change | Platform |
|---|-------|----------|-------------------|----------|
| W-1 | subprocess encoding on CJK Windows | Critical | Yes | Windows |
| L-2 | WSL2 SQLite WAL on /mnt/ | Critical | Yes | Linux/WSL2 |
| W-2 | SQLite WAL lock retention | High | Yes | Windows |
| W-3 | portalocker shared lock semantics | High | Audit | Windows |
| W-5 | Uvicorn --reload broken | High | Yes | Windows |
| L-1 | webbrowser.open() headless | High | Yes | Linux |
| U-1 | datetime.utcnow() deprecated | High | Yes | All |
| W-4 | NTFS reserved names / MAX_PATH | Medium | Yes | Windows |
| W-6 | Git CRLF / quotePath | Medium | Yes | Windows |
| W-9 | tempfile.mkdtemp permissions | Medium | Testing | Windows |
| L-5 | XDG directories | Medium | Audit | Linux |
| M-1 | Spotlight indexing | Medium | None | macOS |
| U-2 | Mixed CRLF/LF and BOM | Medium | Yes | All |
| U-3 | IPv4 vs IPv6 localhost | Medium | Yes | All |
| W-7 | webbrowser.open() Windows | Low | Testing | Windows |
| W-8 | rich on legacy cmd.exe | Low | Testing | Windows |
| W-10 | os.chmod on NTFS | Low | Audit | Windows |
| L-3 | Python 3.11 distro availability | Low | Docs | Linux |
| L-4 | SELinux/AppArmor | Low | Docs | Linux |
| L-6 | systemd service | Low | Docs | Linux |
| M-2 | Homebrew Python | Low | Docs | macOS |
| M-3 | macOS Sequoia localhost | Low | None | macOS |
| M-4 | Apple Silicon | Low | None | macOS |
| U-4 | Locale string sorting | Low | Audit | All |
