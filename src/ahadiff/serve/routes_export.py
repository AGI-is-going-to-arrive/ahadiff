"""GET /api/export/results endpoint — TSV or JSON download."""

from __future__ import annotations

import csv
import errno
import hashlib
import io
import logging
import os
import stat
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.responses import JSONResponse, Response

from ahadiff.contracts import ErrorCode
from ahadiff.core.errors import AhaDiffError, InputError, StorageError
from ahadiff.core.ids import make_event_id
from ahadiff.core.json_util import safe_json_loads, safe_tsv_cell
from ahadiff.core.paths import validate_run_id
from ahadiff.export.preview import (
    ExportManifest,
    build_zip_bytes,
    export_preview,
    validate_preview_run,
)
from ahadiff.export.writer import (
    ensure_output_contained,
    safe_write_export_file,
    validate_export_directory,
)
from ahadiff.review.apkg_export import export_apkg
from ahadiff.review.database import select_result_tsv_rows_readonly
from ahadiff.safety.audit import append_audit_record

from ._errors import error_response

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from .state import ServeState

log = logging.getLogger(__name__)

_TSV_COLUMNS = (
    "timestamp",
    "run_id",
    "source_ref",
    "base_ref",
    "prompt_version",
    "rubric_version",
    "overall",
    "verdict",
    "status",
    "weakest_dim",
    "note_json",
)


def _render_tsv(state: ServeState) -> str:
    """Build TSV content from review.sqlite result_events."""
    try:
        rows = select_result_tsv_rows_readonly(state.review_db_path)
    except InputError:
        rows = ()

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
    writer.writerow(_TSV_COLUMNS)
    for row in rows:
        writer.writerow(safe_tsv_cell(row.get(col, "")) for col in _TSV_COLUMNS)
    return buf.getvalue()


def _result_rows(state: ServeState) -> tuple[dict[str, object], ...]:
    try:
        return select_result_tsv_rows_readonly(state.review_db_path)
    except InputError:
        return ()


async def get_export_results(request: Request) -> Response:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    export_format = request.query_params.get("format") or "tsv"
    if export_format not in {"tsv", "json"}:
        return error_response(
            ErrorCode.EXPORT_FORMAT_UNSUPPORTED,
            "export format must be 'tsv' or 'json'",
        )
    state: ServeState = serve_state(request)
    if export_format == "json":
        rows = await to_thread.run_sync(_result_rows, state)
        return JSONResponse(
            {"format": "json", "results": list(rows)},
            headers={"Content-Disposition": 'attachment; filename="results.json"'},
        )

    tsv_content = await to_thread.run_sync(_render_tsv, state)
    return Response(
        content=tsv_content,
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": 'attachment; filename="results.tsv"'},
    )


async def get_export_apkg(request: Request) -> Response:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)
    try:
        apkg_bytes = await to_thread.run_sync(export_apkg, state.review_db_path)
    except ImportError:
        return error_response(
            ErrorCode.FEATURE_UNAVAILABLE,
            "genanki not installed. Install with: pip install ahadiff[anki]",
            status=501,
        )
    return Response(
        content=apkg_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="ahadiff_review.apkg"'},
    )


def _parse_preview_payload(raw_body: bytes) -> str:
    if not raw_body:
        raise InputError("request body must include a run_id")
    try:
        body = safe_json_loads(raw_body)
    except ValueError as exc:
        raise InputError(f"invalid JSON body: {exc}") from exc
    if not isinstance(body, dict):
        raise InputError("request body must be a JSON object")
    body_dict: dict[str, Any] = cast("dict[str, Any]", body)
    run_id = body_dict.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise InputError("run_id must be a non-empty string")
    validate_run_id(run_id)
    return run_id


def _run_preview_export_sync(
    state: ServeState,
    run_id: str,
) -> dict[str, Any]:
    validate_preview_run(run_id, state.state_dir)
    try:
        exports_parent = validate_export_directory(state.state_dir / "exports", create=True)
    except (InputError, OSError) as exc:
        raise InputError("export target parent is unsafe") from exc
    exports_root = state.state_dir / "exports" / run_id
    cleared_stale_files = _clear_existing_preview_dir(exports_root)
    manifest: ExportManifest = export_preview(
        run_id=run_id,
        output_path=exports_root,
        state_dir=state.state_dir,
        privacy_mode="strict_local",
    )
    zip_bytes = build_zip_bytes(exports_root)
    archive_digest = hashlib.sha256(zip_bytes).hexdigest()
    safe_write_export_file(exports_parent, f"{run_id}.zip", zip_bytes)
    audit_record = {
        "event_id": make_event_id(),
        "schema_version": 1,
        "event_type": "export.preview",
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "run_id": run_id,
        "privacy_mode": manifest.privacy_mode,
        "digest": manifest.digest,
        "archive_digest": archive_digest,
        "file_count": manifest.file_count,
        "total_bytes": manifest.total_bytes,
        "cleared_stale_files": len(cleared_stale_files),
    }
    append_audit_record(state.state_dir / "audit.jsonl", audit_record)
    return {
        "path": f"exports/{run_id}",
        "manifest_digest": manifest.digest,
        "file_count": manifest.file_count,
        "total_bytes": manifest.total_bytes,
        "created_at_utc": manifest.created_at_utc,
        "privacy_mode": manifest.privacy_mode,
        "run_id": manifest.run_id,
        "cleared_stale_files": list(cleared_stale_files),
    }


def _clear_existing_preview_dir(exports_root: Path) -> tuple[str, ...]:
    try:
        safe_parent = validate_export_directory(exports_root.parent, create=False)
    except (InputError, OSError) as exc:
        try:
            exports_root.parent.lstat()
        except FileNotFoundError:
            return ()
        raise InputError("export target parent is unsafe") from exc
    parent = ensure_output_contained(safe_parent.parent, safe_parent)
    parent_fd: int | None = None
    root_fd: int | None = None
    try:
        parent_stat = os.lstat(parent)
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise InputError("export target parent is unreadable") from exc
    _validate_clearable_path(parent_stat, label="export target parent")
    try:
        parent_fd = _open_clearable_dir_path(parent, parent_stat, label="export target parent")
        try:
            root_stat = os.stat(exports_root.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return ()
        except OSError as exc:
            raise InputError("export target is unreadable") from exc
        _validate_clearable_path(root_stat, label="export target")
        if not stat.S_ISDIR(root_stat.st_mode):
            raise InputError("export target is not a directory")
        root_fd = _open_clearable_child_dir(
            parent_fd,
            exports_root.name,
            root_stat,
            label="export target",
        )
        stale = _clear_dir_contents_fd(root_fd, rel_prefix="")
        os.rmdir(exports_root.name, dir_fd=parent_fd)
        os.mkdir(exports_root.name, mode=0o755, dir_fd=parent_fd)
        return tuple(stale)
    finally:
        if root_fd is not None:
            os.close(root_fd)
        if parent_fd is not None:
            os.close(parent_fd)


def _clear_dir_contents_fd(dir_fd: int, *, rel_prefix: str) -> list[str]:
    stale: list[str] = []
    for name in sorted(os.listdir(dir_fd)):
        rel = f"{rel_prefix}/{name}" if rel_prefix else name
        entry_stat = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        _validate_clearable_path(entry_stat, label="stale export entry")
        stale.append(rel)
        if stat.S_ISDIR(entry_stat.st_mode):
            child_fd = _open_clearable_child_dir(
                dir_fd,
                name,
                entry_stat,
                label="stale export directory",
            )
            try:
                stale.extend(_clear_dir_contents_fd(child_fd, rel_prefix=rel))
            finally:
                os.close(child_fd)
            os.rmdir(name, dir_fd=dir_fd)
        else:
            _verify_clearable_file_fd(dir_fd, name, entry_stat)
            os.unlink(name, dir_fd=dir_fd)
    return stale


def _stat_identity(path_stat: os.stat_result) -> tuple[int, int]:
    return int(path_stat.st_dev), int(path_stat.st_ino)


def _open_clearable_dir_path(path: Path, expected: os.stat_result, *, label: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(f"{label} must not be a symlink") from exc
        raise InputError(f"{label} is unreadable") from exc
    try:
        _validate_opened_dir(fd, expected, label=label)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_clearable_child_dir(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
    *,
    label: str,
) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(f"{label} must not be a symlink") from exc
        raise InputError(f"{label} is unreadable") from exc
    try:
        _validate_opened_dir(fd, expected, label=label)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _validate_opened_dir(fd: int, expected: os.stat_result, *, label: str) -> None:
    opened = os.fstat(fd)
    _validate_clearable_path(opened, label=label)
    if not stat.S_ISDIR(opened.st_mode):
        raise InputError(f"{label} is not a directory")
    if _stat_identity(opened) != _stat_identity(expected):
        raise InputError(f"{label} changed during validation")


def _verify_clearable_file_fd(parent_fd: int, name: str, expected: os.stat_result) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError("stale export entry must not be a symlink") from exc
        raise InputError("stale export entry is unreadable") from exc
    try:
        opened = os.fstat(fd)
        _validate_clearable_path(opened, label="stale export entry")
        if _stat_identity(opened) != _stat_identity(expected):
            raise InputError("stale export entry changed during validation")
    finally:
        os.close(fd)


def _validate_clearable_path(path_stat: os.stat_result, *, label: str) -> None:
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError(f"{label} must not be a symlink")
    if bool(getattr(path_stat, "st_file_attributes", 0) & 0x400):
        raise InputError(f"{label} must not be a Windows reparse point or junction")
    if not stat.S_ISDIR(path_stat.st_mode) and not stat.S_ISREG(path_stat.st_mode):
        raise InputError(f"{label} must be a regular file or directory")
    if not stat.S_ISDIR(path_stat.st_mode) and getattr(path_stat, "st_nlink", 1) > 1:
        raise InputError(f"{label} must not be a hardlink")


async def post_export_preview(request: Request) -> Response:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)
    raw_body = await request.body()
    try:
        run_id = _parse_preview_payload(raw_body)
    except InputError as exc:
        return error_response(ErrorCode.INPUT_VALIDATION, str(exc))
    try:
        payload = await to_thread.run_sync(_run_preview_export_sync, state, run_id)
    except InputError as exc:
        message = str(exc)
        if "run not found" in message or "not finalized" in message:
            return error_response(ErrorCode.RUN_NOT_FOUND, message)
        log.warning("export preview rejected invalid input: %s", type(exc).__name__)
        return error_response(ErrorCode.INPUT_VALIDATION, "export preview input is invalid")
    except StorageError as exc:
        log.warning("export preview storage failure: %s", type(exc).__name__)
        return error_response(ErrorCode.STORAGE_FS, "export preview storage is unavailable")
    except AhaDiffError as exc:
        log.warning("export preview failed: %s", type(exc).__name__)
        return error_response(ErrorCode.INTERNAL_ERROR, "export preview failed")
    except OSError as exc:
        log.warning("export preview filesystem failure: %s", type(exc).__name__)
        return error_response(ErrorCode.STORAGE_FS, "export preview storage is unavailable")
    return JSONResponse(payload)


__all__ = ["get_export_apkg", "get_export_results", "post_export_preview"]
