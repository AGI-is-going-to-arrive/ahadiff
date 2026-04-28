"""GET /api/export/results endpoint — TSV download."""

from __future__ import annotations

import csv
import io
import logging
from typing import TYPE_CHECKING

from anyio import to_thread
from starlette.responses import Response

from ahadiff.core.errors import InputError
from ahadiff.review.database import select_result_tsv_rows

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
_FORMULA_PREFIX_CHARS = frozenset("=+-@\t\r")


def _safe_tsv_cell(value: object) -> str:
    text = str(value) if value is not None else ""
    if text and text[0] in _FORMULA_PREFIX_CHARS:
        return f"'{text}"
    return text


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
        writer.writerow(_safe_tsv_cell(row.get(col, "")) for col in _TSV_COLUMNS)
    return buf.getvalue()


async def get_export_results(request: Request) -> Response:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    export_format = request.query_params.get("format")
    if export_format is not None and export_format != "tsv":
        raise InputError("only 'tsv' export format is supported")
    state: ServeState = serve_state(request)
    tsv_content = await to_thread.run_sync(_render_tsv, state)
    return Response(
        content=tsv_content,
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": 'attachment; filename="results.tsv"'},
    )


__all__ = ["get_export_results"]
