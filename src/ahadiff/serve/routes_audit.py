from __future__ import annotations

import errno
import os
import stat
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_audit import AuditLogResponse
from ahadiff.core.errors import InputError

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from .state import ServeState

_MAX_AUDIT_FILE_BYTES = 10 * 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_AUDIT_FIELD_ALLOWLIST = frozenset(
    {
        "timestamp",
        "ts",
        "event_type",
        "action",
        "provider_class",
        "model_id",
        "prompt_name",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "cost_confidence",
        "execution_origin",
        "billing_mode",
        "pricing_version",
        "privacy_mode",
        "source_ref",
        "note",
    }
)


async def get_audit(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)

    raw_limit = request.query_params.get("limit", "50")
    raw_page = request.query_params.get("page", "1")
    raw_offset = request.query_params.get("offset")
    fields = _parse_audit_fields(request.query_params.get("fields"))
    try:
        limit = min(max(int(raw_limit), 1), 200)
    except (ValueError, TypeError):
        limit = 50
    try:
        page = max(int(raw_page), 1)
    except (ValueError, TypeError):
        page = 1
    try:
        offset = max(int(raw_offset), 0) if raw_offset is not None else (page - 1) * limit
    except (ValueError, TypeError):
        offset = 0

    payload = await to_thread.run_sync(
        lambda: _read_audit_sync(state.state_dir, limit=limit, offset=offset, fields=fields),
    )
    return JSONResponse(payload)


def _parse_audit_fields(raw_fields: str | None) -> tuple[str, ...] | None:
    if raw_fields is None or raw_fields.strip() == "":
        return None
    fields = tuple(field.strip() for field in raw_fields.split(",") if field.strip())
    unknown = sorted(set(fields) - _AUDIT_FIELD_ALLOWLIST)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unsupported audit fields: {unknown}")
    return fields


def _read_audit_sync(
    state_dir: Path,
    *,
    limit: int,
    offset: int,
    fields: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    from ahadiff.core.json_util import safe_json_loads
    from ahadiff.core.paths import validate_state_path_no_symlinks

    validate_state_path_no_symlinks(state_dir, allow_missing_leaf=False)
    audit_path = state_dir / "audit.jsonl"
    if not audit_path.is_file():
        return _audit_response([], total=0, limit=limit, offset=offset, fields=fields)

    try:
        text = _read_audit_text(audit_path)
    except OSError:
        return _audit_response([], total=0, limit=limit, offset=offset, fields=fields)

    parsed_entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed: Any = safe_json_loads(stripped)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            parsed_entries.append(cast("dict[str, Any]", parsed))

    total = len(parsed_entries)
    page_entries: list[dict[str, Any]] = []
    entries_newest_first = list(reversed(parsed_entries))
    for entry in entries_newest_first[offset : offset + limit]:
        if fields is not None:
            entry = {field: entry[field] for field in fields if field in entry}
        page_entries.append(entry)
    return _audit_response(page_entries, total=total, limit=limit, offset=offset, fields=fields)


def _audit_response(
    entries: list[dict[str, Any]],
    *,
    total: int,
    limit: int,
    offset: int,
    fields: tuple[str, ...] | None,
) -> dict[str, Any]:
    page = (offset // limit) + 1 if limit > 0 else 1
    has_more = offset + len(entries) < total
    return AuditLogResponse(
        entries=entries,
        total=total,
        limit=limit,
        offset=offset,
        page=page,
        has_more=has_more,
        next_cursor=str(offset + len(entries)) if has_more else None,
        fields=list(fields) if fields is not None else None,
    ).model_dump(mode="json")


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
