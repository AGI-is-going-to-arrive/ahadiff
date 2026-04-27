"""Centralized SQLite connection helper — rejects symlinks and applies safe pragmas."""

from __future__ import annotations

import os
import sqlite3
import stat
import sys
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import quote


def safe_sqlite_connect(
    path: Path | str,
    *,
    read_only: bool = False,
    journal_mode: str | None = None,
    busy_timeout_ms: int = 5000,
) -> sqlite3.Connection:
    """Open a SQLite database after verifying the path is not a symlink.

    On Windows, also checks for NTFS reparse points (``st_file_attributes & 0x400``).
    Applies safe pragmas: ``trusted_schema=OFF``, ``busy_timeout``, and optionally
    ``journal_mode``.
    """
    p = Path(path)

    _reject_symlink(p)

    uri = None
    if read_only:
        uri = _read_only_sqlite_uri(p)

    conn = sqlite3.connect(uri, uri=True) if uri else sqlite3.connect(str(p))

    conn.execute("PRAGMA trusted_schema = OFF")
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")

    if journal_mode is not None:
        conn.execute(f"PRAGMA journal_mode = {journal_mode}")

    return conn


def reject_symlink_path(path: Path | str) -> None:
    """Raise ``PermissionError`` if *path* is a symlink or (Windows) reparse point."""
    _reject_symlink(Path(path))


def _read_only_sqlite_uri(path: PurePath | str) -> str:
    path_text = str(path).replace("\\", "/")
    if len(path_text) >= 2 and path_text[1] == ":" and path_text[0].isalpha():
        path_text = f"/{path_text}"
    return f"file:{quote(path_text, safe='/:')}?mode=ro"


def _reject_symlink(p: Path) -> None:
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return

    if stat.S_ISLNK(st.st_mode):
        raise PermissionError(f"refusing to open symlink: {p}")

    if sys.platform == "win32":
        attrs: Any = getattr(st, "st_file_attributes", 0)
        if attrs & 0x400:
            raise PermissionError(f"refusing to open NTFS reparse point: {p}")


__all__ = ["reject_symlink_path", "safe_sqlite_connect"]
