"""Centralized SQLite connection helper — rejects symlinks and applies safe pragmas."""

from __future__ import annotations

import errno
import os
import sqlite3
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, cast
from urllib.parse import quote

_VALID_JOURNAL_MODES = frozenset({"DELETE", "WAL", "TRUNCATE", "PERSIST", "MEMORY", "OFF"})
_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_OPEN_VERIFICATION_RETRIES = 8


@dataclass(frozen=True)
class _OpenVerificationState:
    expected_identity: tuple[int, int] | None
    existing_path: bool
    path_change_token: tuple[int, int] | None = None
    parent_identity: tuple[int, int] | None = None
    parent_change_token: tuple[int, int] | None = None
    sidecar_state: tuple[tuple[str, tuple[int, int] | None], ...] = ()
    nofollow_fd: int | None = None


class _RetryOpenVerification(Exception):
    """Retry opening the database after benign SQLite sidecar churn."""


def safe_sqlite_connect(
    path: Path | str,
    *,
    read_only: bool = False,
    journal_mode: str | None = None,
    busy_timeout_ms: int = 5000,
    timeout: float = 5.0,
    row_factory: type | None = None,
    foreign_keys: bool = False,
    defensive: bool = False,
) -> sqlite3.Connection:
    """Open a SQLite database after verifying the path is not a symlink.

    On Windows, also checks for NTFS reparse points (``st_file_attributes & 0x400``).
    Applies safe pragmas: ``trusted_schema=OFF``, ``busy_timeout``, and optionally
    ``journal_mode``, ``foreign_keys``, and ``DBCONFIG_DEFENSIVE``.
    """
    if journal_mode is not None and journal_mode.upper() not in _VALID_JOURNAL_MODES:
        raise ValueError(f"invalid journal_mode: {journal_mode!r}")
    if busy_timeout_ms < 0:
        raise ValueError("busy_timeout_ms must be >= 0")
    if timeout < 0:
        raise ValueError("timeout must be >= 0")

    special_database = _is_special_sqlite_database(path) and not read_only
    p = _canonicalize_system_sqlite_path(Path(path))
    if not special_database:
        _reject_symlink_ancestors(p)
    database_target = str(path) if special_database else str(p)

    uri = None
    if read_only:
        uri = _read_only_sqlite_uri(p)

    for attempt in range(_OPEN_VERIFICATION_RETRIES):
        attempt_state = (
            _OpenVerificationState(expected_identity=None, existing_path=False)
            if special_database
            else _prepare_open_verification(p, create_missing=not read_only)
        )
        conn: sqlite3.Connection | None = None
        try:
            if uri:
                conn = sqlite3.connect(uri, uri=True, timeout=timeout)
            elif attempt_state.expected_identity is not None:
                conn = sqlite3.connect(_read_write_sqlite_uri(p), uri=True, timeout=timeout)
            else:
                conn = sqlite3.connect(database_target, timeout=timeout)
            _verify_opened_database_path(conn, p, attempt_state)
            if row_factory is not None:
                conn.row_factory = row_factory
            conn.execute("PRAGMA trusted_schema = OFF")
            conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
            if journal_mode is not None:
                conn.execute(f"PRAGMA journal_mode = {journal_mode}")
            if foreign_keys:
                conn.execute("PRAGMA foreign_keys = ON")
            if defensive:
                _flag = getattr(sqlite3, "SQLITE_DBCONFIG_DEFENSIVE", None)
                _setconfig = getattr(conn, "setconfig", None)
                if _flag is not None and callable(_setconfig):
                    cast("Any", _setconfig)(_flag, True)
            return conn
        except sqlite3.OperationalError:
            if conn is not None:
                conn.close()
            _raise_if_parent_changed_during_failed_open(p, attempt_state)
            raise
        except _RetryOpenVerification:
            if conn is not None:
                conn.close()
            if attempt + 1 >= _OPEN_VERIFICATION_RETRIES:
                raise PermissionError(f"database path changed during open: {p}") from None
            time.sleep(0.01 * (attempt + 1))
            continue
        except Exception:
            if conn is not None:
                conn.close()
            raise
        finally:
            _close_nofollow_fd(attempt_state.nofollow_fd)

    raise PermissionError(f"database path changed during open: {p}")


def reject_symlink_path(path: Path | str) -> None:
    """Raise ``PermissionError`` if *path* is a symlink or (Windows) reparse point."""
    _reject_symlink(_canonicalize_system_sqlite_path(Path(path)))


def _read_only_sqlite_uri(path: PurePath | str) -> str:
    return _sqlite_file_uri(path, "ro")


def _read_write_sqlite_uri(path: PurePath | str) -> str:
    return _sqlite_file_uri(path, "rw")


def _sqlite_file_uri(path: PurePath | str, mode: str) -> str:
    path_text = str(path).replace("\\", "/")
    if len(path_text) >= 2 and path_text[1] == ":" and path_text[0].isalpha():
        path_text = f"/{path_text}"
    return f"file:{quote(path_text, safe='/:')}?mode={mode}"


def _is_special_sqlite_database(path: Path | str) -> bool:
    return (isinstance(path, str) and path == "") or str(path) == ":memory:"


def _canonicalize_system_sqlite_path(path: Path) -> Path:
    if sys.platform != "darwin" or not path.is_absolute():
        return path

    path_parts = path.parts
    if len(path_parts) < 2:
        return path
    if path_parts[1] == "var":
        return Path("/private/var", *path_parts[2:])
    if path_parts[1] == "tmp":
        return Path("/private/tmp", *path_parts[2:])
    return path


def _prepare_open_verification(
    path: Path,
    *,
    create_missing: bool = False,
) -> _OpenVerificationState:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        if create_missing:
            return _prepare_missing_database_file(path)
        return _OpenVerificationState(expected_identity=None, existing_path=False)

    _reject_symlink_stat(path, path_stat)
    if not stat.S_ISREG(path_stat.st_mode):
        return _OpenVerificationState(
            expected_identity=None,
            existing_path=True,
            path_change_token=_stat_change_token(path_stat),
        )
    _reject_hardlink_stat(path, path_stat)

    path_change_token = _stat_change_token(path_stat)
    parent_identity, parent_change_token = _parent_directory_state(path)
    sidecar_state = _sqlite_sidecar_state(path)

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise PermissionError(f"refusing to open symlink: {path}") from exc
        return _OpenVerificationState(
            expected_identity=(path_stat.st_dev, path_stat.st_ino),
            existing_path=True,
            path_change_token=path_change_token,
            parent_identity=parent_identity,
            parent_change_token=parent_change_token,
            sidecar_state=sidecar_state,
        )

    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise PermissionError(f"database path changed during open: {path}")
        if _has_windows_reparse_point(file_stat):
            raise PermissionError(f"refusing to open NTFS reparse point: {path}")
        _reject_hardlink_stat(path, file_stat)
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise PermissionError(f"database path changed during open: {path}")
        return _OpenVerificationState(
            expected_identity=(file_stat.st_dev, file_stat.st_ino),
            existing_path=True,
            path_change_token=path_change_token,
            parent_identity=parent_identity,
            parent_change_token=parent_change_token,
            sidecar_state=sidecar_state,
            nofollow_fd=fd,
        )
    except Exception:
        os.close(fd)
        raise


def _prepare_missing_database_file(path: Path) -> _OpenVerificationState:
    parent_fd = _open_parent_directory_for_create(path)
    try:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
        except FileExistsError:
            return _prepare_open_verification(path, create_missing=False)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise PermissionError(f"refusing to open symlink: {path}") from exc
            raise

        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise PermissionError(f"database path changed during open: {path}")
            if _has_windows_reparse_point(file_stat):
                raise PermissionError(f"refusing to open NTFS reparse point: {path}")
            _reject_hardlink_stat(path, file_stat)
            parent_stat = os.fstat(parent_fd)
            return _OpenVerificationState(
                expected_identity=(file_stat.st_dev, file_stat.st_ino),
                existing_path=True,
                path_change_token=_stat_change_token(file_stat),
                parent_identity=(parent_stat.st_dev, parent_stat.st_ino),
                parent_change_token=_stat_change_token(parent_stat),
                sidecar_state=_sqlite_sidecar_state(path),
                nofollow_fd=fd,
            )
        except Exception:
            os.close(fd)
            raise
    finally:
        os.close(parent_fd)


def _open_parent_directory_for_create(path: Path) -> int:
    parent = path.parent
    parent_lstat = os.lstat(parent)
    _reject_symlink_stat(parent, parent_lstat)
    if not stat.S_ISDIR(parent_lstat.st_mode):
        raise PermissionError(f"database path parent must be a directory: {parent}")

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(parent), flags)
    try:
        parent_stat = os.fstat(fd)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise PermissionError(f"database path parent must be a directory: {parent}")
        if _has_windows_reparse_point(parent_stat):
            raise PermissionError(f"refusing to open NTFS reparse point: {parent}")
        if (parent_stat.st_dev, parent_stat.st_ino) != (
            parent_lstat.st_dev,
            parent_lstat.st_ino,
        ):
            raise PermissionError(f"database path parent changed during open: {parent}")
        return fd
    except Exception:
        os.close(fd)
        raise


def _verify_opened_database_path(
    conn: sqlite3.Connection,
    requested_path: Path,
    verification_state: _OpenVerificationState,
) -> None:
    actual_path = _main_database_path(conn)
    if actual_path is None:
        return

    actual_stat = actual_path.stat()
    if not stat.S_ISREG(actual_stat.st_mode):
        raise PermissionError(f"database path changed during open: {requested_path}")
    _reject_hardlink_stat(requested_path, actual_stat)

    actual_identity = (actual_stat.st_dev, actual_stat.st_ino)
    expected_identity = verification_state.expected_identity
    if expected_identity is not None:
        _verify_nofollow_fd_identity(requested_path, verification_state)
        _verify_parent_directory_unchanged(requested_path, verification_state)
        if actual_identity != expected_identity:
            raise PermissionError(f"database path changed during open: {requested_path}")
        return

    if not verification_state.existing_path:
        try:
            requested_lstat = os.lstat(requested_path)
        except FileNotFoundError as exc:
            raise PermissionError(f"database path changed during open: {requested_path}") from exc
        _reject_symlink_stat(requested_path, requested_lstat)
        requested_stat = requested_path.stat()
        if not stat.S_ISREG(requested_stat.st_mode):
            raise PermissionError(f"database path changed during open: {requested_path}")
        _reject_hardlink_stat(requested_path, requested_stat)
        if (requested_stat.st_dev, requested_stat.st_ino) != actual_identity:
            raise PermissionError(f"database path changed during open: {requested_path}")


def _verify_nofollow_fd_identity(
    requested_path: Path,
    verification_state: _OpenVerificationState,
) -> None:
    expected_identity = verification_state.expected_identity
    fd = verification_state.nofollow_fd
    if expected_identity is None or fd is None:
        return
    try:
        fd_stat = os.fstat(fd)
    except OSError as exc:
        raise PermissionError(f"database path changed during open: {requested_path}") from exc
    if not stat.S_ISREG(fd_stat.st_mode):
        raise PermissionError(f"database path changed during open: {requested_path}")
    if (fd_stat.st_dev, fd_stat.st_ino) != expected_identity:
        raise PermissionError(f"database path changed during open: {requested_path}")


def _verify_parent_directory_unchanged(
    requested_path: Path,
    verification_state: _OpenVerificationState,
) -> None:
    expected_identity = verification_state.parent_identity
    expected_change_token = verification_state.parent_change_token
    if expected_identity is None or expected_change_token is None:
        return
    current_identity, current_change_token = _parent_directory_state(requested_path)
    if current_identity == expected_identity and current_change_token == expected_change_token:
        return
    if _sqlite_sidecar_state(requested_path) != verification_state.sidecar_state:
        raise _RetryOpenVerification
    try:
        current_stat = os.lstat(requested_path)
    except FileNotFoundError as exc:
        raise PermissionError(f"database path changed during open: {requested_path}") from exc
    _reject_symlink_stat(requested_path, current_stat)
    if not stat.S_ISREG(current_stat.st_mode):
        raise PermissionError(f"database path changed during open: {requested_path}")
    _reject_hardlink_stat(requested_path, current_stat)
    requested_identity = verification_state.expected_identity
    current_requested_identity = (current_stat.st_dev, current_stat.st_ino)
    if requested_identity is not None and current_requested_identity != requested_identity:
        raise PermissionError(f"database path changed during open: {requested_path}")
    if _stat_change_token(current_stat) == verification_state.path_change_token:
        return
    raise PermissionError(f"database path changed during open: {requested_path}")


def _raise_if_parent_changed_during_failed_open(
    requested_path: Path,
    verification_state: _OpenVerificationState,
) -> None:
    expected_identity = verification_state.parent_identity
    expected_change_token = verification_state.parent_change_token
    if expected_identity is None or expected_change_token is None:
        return
    try:
        current_identity, current_change_token = _parent_directory_state(requested_path)
    except PermissionError as exc:
        raise PermissionError(f"database path changed during open: {requested_path}") from exc
    if current_identity != expected_identity or current_change_token != expected_change_token:
        raise PermissionError(f"database path changed during open: {requested_path}")


def _parent_directory_state(path: Path) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    try:
        parent_stat = path.parent.lstat()
    except OSError:
        return None, None
    _reject_symlink_stat(path.parent, parent_stat)
    return (
        (parent_stat.st_dev, parent_stat.st_ino),
        (
            _stat_time_ns(parent_stat, "st_mtime_ns", "st_mtime"),
            _stat_time_ns(parent_stat, "st_ctime_ns", "st_ctime"),
        ),
    )


def _sqlite_sidecar_state(path: Path) -> tuple[tuple[str, tuple[int, int] | None], ...]:
    state: list[tuple[str, tuple[int, int] | None]] = []
    for suffix in _SQLITE_SIDECAR_SUFFIXES:
        sidecar_path = path.with_name(f"{path.name}{suffix}")
        try:
            sidecar_stat = os.lstat(sidecar_path)
        except FileNotFoundError:
            state.append((suffix, None))
            continue
        _reject_symlink_stat(sidecar_path, sidecar_stat)
        if not stat.S_ISREG(sidecar_stat.st_mode):
            raise PermissionError(f"refusing non-regular SQLite sidecar: {sidecar_path}")
        _reject_hardlink_stat(sidecar_path, sidecar_stat)
        state.append((suffix, (sidecar_stat.st_dev, sidecar_stat.st_ino)))
    return tuple(state)


def _stat_time_ns(st: os.stat_result, ns_attr: str, seconds_attr: str) -> int:
    value = getattr(st, ns_attr, None)
    if value is not None:
        return int(value)
    return int(float(getattr(st, seconds_attr)) * 1_000_000_000)


def _stat_change_token(st: os.stat_result) -> tuple[int, int]:
    return (
        _stat_time_ns(st, "st_mtime_ns", "st_mtime"),
        _stat_time_ns(st, "st_ctime_ns", "st_ctime"),
    )


def _main_database_path(conn: sqlite3.Connection) -> Path | None:
    cursor = conn.execute("PRAGMA database_list")
    try:
        row = cursor.fetchone()
    finally:
        cursor.close()
    if row is None:
        return None
    path_text = str(row[2])
    if path_text == "":
        return None
    return Path(path_text)


def _reject_symlink(p: Path) -> None:
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return

    _reject_symlink_stat(p, st)


def _reject_symlink_ancestors(path: Path) -> None:
    absolute_path = path if path.is_absolute() else path.absolute()
    anchor = absolute_path.anchor
    if not anchor:
        return
    cursor = Path(anchor)
    for part in absolute_path.parts[1:-1]:
        cursor = cursor / part
        try:
            st = os.lstat(cursor)
        except FileNotFoundError:
            return
        _reject_symlink_stat(cursor, st)
        if not stat.S_ISDIR(st.st_mode):
            raise PermissionError(f"database path parent must be a directory: {cursor}")


def _reject_symlink_stat(path: Path, st: os.stat_result) -> None:
    if stat.S_ISLNK(st.st_mode):
        raise PermissionError(f"refusing to open symlink: {path}")
    if _has_windows_reparse_point(st):
        raise PermissionError(f"refusing to open NTFS reparse point: {path}")


def _reject_hardlink_stat(path: Path, st: os.stat_result) -> None:
    if getattr(st, "st_nlink", 1) > 1:
        raise PermissionError(f"refusing to open hardlinked database path: {path}")


def _has_windows_reparse_point(st: os.stat_result) -> bool:
    if sys.platform != "win32":
        return False
    attrs: Any = getattr(st, "st_file_attributes", 0)
    return bool(attrs & 0x400)


def _close_nofollow_fd(fd: int | None) -> None:
    if fd is None:
        return
    os.close(fd)


__all__ = ["reject_symlink_path", "safe_sqlite_connect"]
