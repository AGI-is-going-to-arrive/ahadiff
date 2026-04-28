from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from .state import ServeState


async def search_api(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)

    q = request.query_params.get("q", "")
    raw_limit = request.query_params.get("limit", "50")
    try:
        limit = min(max(int(raw_limit), 1), 200)
    except (ValueError, TypeError):
        limit = 50
    tables_raw = request.query_params.get("tables")
    tables: tuple[str, ...] | None = None
    if tables_raw:
        tables = tuple(t.strip() for t in tables_raw.split(",") if t.strip())

    payload = await to_thread.run_sync(
        lambda: _search_sync(state.review_db_path, q, limit=limit, tables=tables),
    )
    return JSONResponse(payload)


def _search_sync(
    db_path: Path,
    q: str,
    *,
    limit: int,
    tables: tuple[str, ...] | None,
) -> dict[str, Any]:
    from ahadiff.review.search import search_all

    results = search_all(db_path, q, limit=limit, tables=tables)
    return {
        "results": [
            {
                "source_table": r.source_table,
                "primary_key": r.primary_key,
                "snippet": r.snippet,
                "rank": r.rank,
            }
            for r in results
        ]
    }


__all__ = ["search_api"]
