from __future__ import annotations

import errno
import os
import stat
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.core.errors import InputError

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from .state import ServeState

_MAX_AUDIT_FILE_BYTES = 10 * 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


async def get_audit(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)

    raw_limit = request.query_params.get("limit", "50")
    raw_offset = request.query_params.get("offset", "0")
    try:
        limit = min(max(int(raw_limit), 1), 200)
    except (ValueError, TypeError):
        limit = 50
    try:
        offset = max(int(raw_offset), 0)
    except (ValueError, TypeError):
        offset = 0

    payload = await to_thread.run_sync(
        lambda: _read_audit_sync(state.state_dir, limit=limit, offset=offset),
    )
    return JSONResponse(payload)


def _read_audit_sync(
    state_dir: Path,
    *,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    from ahadiff.core.json_util import safe_json_loads
    from ahadiff.core.paths import validate_state_path_no_symlinks

    validate_state_path_no_symlinks(state_dir, allow_missing_leaf=False)
    audit_path = state_dir / "audit.jsonl"
    if not audit_path.is_file():
        return {"entries": [], "total": 0, "limit": limit, "offset": offset}

    try:
        text = _read_audit_text(audit_path)
    except OSError:
        return {"entries": [], "total": 0, "limit": limit, "offset": offset}

    page_entries: list[dict[str, Any]] = []
    total = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed: Any = safe_json_loads(stripped)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            if total >= offset and len(page_entries) < limit:
                page_entries.append(cast("dict[str, Any]", parsed))
            total += 1

    return {"entries": page_entries, "total": total, "limit": limit, "offset": offset}


def _read_audit_text(path: Path) -> str:
    from ahadiff.core.paths import validate_state_path_no_symlinks

    validate_state_path_no_symlinks(path.parent, allow_missing_leaf=False)
    path_stat = os.lstat(path)
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError("audit.jsonl must not be a symlink")
    if _has_windows_reparse_point(path_stat):
        raise InputError("audit.jsonl must not be a Windows reparse point or junction")
    _reject_hardlinked_regular_file(path_stat)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError("audit.jsonl must not be a symlink") from exc
        raise
    try:
        opened_stat = os.fstat(fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise InputError("audit.jsonl must be a regular file")
        if _has_windows_reparse_point(opened_stat):
            raise InputError("audit.jsonl must not be a Windows reparse point or junction")
        _reject_hardlinked_regular_file(opened_stat)
        if (opened_stat.st_dev, opened_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError("audit.jsonl changed during validation")
        if opened_stat.st_size > _MAX_AUDIT_FILE_BYTES:
            return ""
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd != -1:
            os.close(fd)


def _has_windows_reparse_point(path_stat: os.stat_result) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _reject_hardlinked_regular_file(path_stat: os.stat_result) -> None:
    if stat.S_ISREG(path_stat.st_mode) and getattr(path_stat, "st_nlink", 1) > 1:
        raise InputError("audit.jsonl must not be a hardlink")


__all__ = ["get_audit"]
