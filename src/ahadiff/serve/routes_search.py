from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_runtime import SearchResponse, SearchResultItem
from ahadiff.core.errors import StorageError

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
    raw_cursor = request.query_params.get("cursor")
    try:
        offset = max(int(raw_cursor), 0) if raw_cursor is not None else 0
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="search cursor must be an integer") from exc
    tables_raw = request.query_params.get("tables")
    tables: tuple[str, ...] | None = None
    if tables_raw:
        tables = tuple(t.strip() for t in tables_raw.split(",") if t.strip())

    try:
        payload = await to_thread.run_sync(
            lambda: _search_sync(
                state.review_db_path,
                state.state_dir,
                q,
                limit=limit,
                offset=offset,
                tables=tables,
                include_graph=_should_include_graph(tables),
            ),
        )
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=_public_storage_error(exc)) from exc
    return JSONResponse(payload)


def _should_include_graph(tables: tuple[str, ...] | None) -> bool:
    return tables is None or "graph_nodes" in tables


def _public_storage_error(exc: StorageError) -> str:
    message = str(exc)
    if message.startswith("review.sqlite is not a valid database"):
        return "review.sqlite is not a valid database"
    if message.startswith("SQLite quick_check failed"):
        return "review.sqlite quick_check failed"
    if message.startswith("failed to open review.sqlite safely"):
        return "failed to open review.sqlite safely"
    return "review storage is unavailable"


def _load_graph(state_dir: Path) -> object | None:
    try:
        from ahadiff.core.paths import validate_state_path_no_symlinks

        graph_path = state_dir / "graphify" / "graph.json"
        validate_state_path_no_symlinks(graph_path, allow_missing_leaf=False)
        if not graph_path.is_file():
            return None
        from ahadiff.graphify import parse_graph_json

        return parse_graph_json(graph_path)
    except Exception:
        return None


def _search_sync(
    db_path: Path,
    state_dir: Path,
    q: str,
    *,
    limit: int,
    offset: int,
    tables: tuple[str, ...] | None,
    include_graph: bool,
) -> dict[str, Any]:
    from ahadiff.review.search import search_all_with_graph

    graph = _load_graph(state_dir) if include_graph else None
    results = search_all_with_graph(
        db_path,
        q,
        limit=limit + offset + 1,
        tables=tables,
        graph=graph,
    )
    page = results[offset : offset + limit]
    next_cursor = str(offset + limit) if len(results) > offset + limit else None
    response = SearchResponse(
        results=[
            SearchResultItem(
                source_table=r.source_table,
                primary_key=r.primary_key,
                snippet=r.snippet,
                rank=r.rank,
                href=r.href,
            )
            for r in page
        ],
        next_cursor=next_cursor,
    )
    return response.model_dump(mode="json")


__all__ = ["search_api"]
