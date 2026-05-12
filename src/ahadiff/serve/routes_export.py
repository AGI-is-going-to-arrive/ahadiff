"""GET /api/export/results endpoint — TSV or JSON download."""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.responses import JSONResponse, Response

from ahadiff.contracts import ErrorCode
from ahadiff.core.errors import AhaDiffError, InputError, StorageError
from ahadiff.core.ids import make_event_id
from ahadiff.core.json_util import safe_json_loads, safe_tsv_cell
from ahadiff.core.paths import validate_run_id
from ahadiff.export.preview import ExportManifest, export_preview
from ahadiff.review.apkg_export import export_apkg
from ahadiff.review.database import select_result_tsv_rows
from ahadiff.safety.audit import append_audit_record

from ._errors import error_response

if TYPE_CHECKING:
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
        rows = select_result_tsv_rows(state.review_db_path)
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
        return select_result_tsv_rows(state.review_db_path)
    except InputError:
        return ()


async def get_export_results(request: Request) -> Response:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    export_format = request.query_params.get("format") or "tsv"
    if export_format not in {"tsv", "json"}:
        raise InputError("export format must be 'tsv' or 'json'")
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
    except ImportError as exc:
        return error_response(ErrorCode.FEATURE_UNAVAILABLE, str(exc), status=501)
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
    exports_root = state.state_dir / "exports" / run_id
    if exports_root.exists() and not exports_root.is_dir():
        raise InputError("export target is not a directory")
    manifest: ExportManifest = export_preview(
        run_id=run_id,
        output_path=exports_root,
        state_dir=state.state_dir,
        privacy_mode="strict_local",
    )
    audit_record = {
        "event_id": make_event_id(),
        "schema_version": 1,
        "event_type": "export.preview",
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "run_id": run_id,
        "privacy_mode": manifest.privacy_mode,
        "digest": manifest.digest,
        "file_count": manifest.file_count,
        "total_bytes": manifest.total_bytes,
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
    }


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
