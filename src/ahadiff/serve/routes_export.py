"""GET /api/export/results endpoint — TSV or JSON download."""

from __future__ import annotations

import csv
import io
import logging
from typing import TYPE_CHECKING

from anyio import to_thread
from starlette.responses import JSONResponse, Response

from ahadiff.contracts import ErrorCode
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_tsv_cell
from ahadiff.review.apkg_export import export_apkg
from ahadiff.review.database import select_result_tsv_rows

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


__all__ = ["get_export_apkg", "get_export_results"]
