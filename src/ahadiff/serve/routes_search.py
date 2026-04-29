from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_runtime import SearchResponse, SearchResultItem

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
        lambda: _search_sync(
            state.review_db_path,
            state.state_dir,
            q,
            limit=limit,
            tables=tables,
            include_graph=_should_include_graph(tables),
        ),
    )
    return JSONResponse(payload)


def _should_include_graph(tables: tuple[str, ...] | None) -> bool:
    return tables is None or "graph_nodes" in tables


def _load_graph(state_dir: Path) -> object | None:
    import stat as stat_mod

    graph_path = state_dir.parent / "graphify-out" / "graph.json"
    if not graph_path.is_file():
        return None
    try:
        leaf_stat = graph_path.lstat()
        if stat_mod.S_ISLNK(leaf_stat.st_mode):
            return None
        if bool(getattr(leaf_stat, "st_file_attributes", 0) & 0x400):
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
    tables: tuple[str, ...] | None,
    include_graph: bool,
) -> dict[str, Any]:
    from ahadiff.review.search import search_all_with_graph

    graph = _load_graph(state_dir) if include_graph else None
    results = search_all_with_graph(
        db_path,
        q,
        limit=limit,
        tables=tables,
        graph=graph,
    )
    response = SearchResponse(
        results=[
            SearchResultItem(
                source_table=r.source_table,
                primary_key=r.primary_key,
                snippet=r.snippet,
                rank=r.rank,
            )
            for r in results
        ]
    )
    return response.model_dump(mode="json")


__all__ = ["search_api"]
