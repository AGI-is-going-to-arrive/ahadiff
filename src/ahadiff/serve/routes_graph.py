from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_runtime import GraphStatusResponse

if TYPE_CHECKING:
    from starlette.requests import Request


async def get_graph_status(request: Request) -> JSONResponse:
    from .auth import serve_state

    state = serve_state(request)
    payload = await to_thread.run_sync(lambda: _graph_status_sync(state.state_dir))
    return JSONResponse(payload)


def _graph_status_sync(state_dir: object) -> dict[str, Any]:
    from pathlib import Path

    from ahadiff.core.errors import InputError
    from ahadiff.core.paths import validate_state_path_no_symlinks
    from ahadiff.git.capture import detect_graphify_status
    from ahadiff.git.repo import open_repo

    root = Path(str(state_dir)).parent
    repo = None
    with suppress(InputError, OSError):
        repo = open_repo(root)
    status = detect_graphify_status(root, use_graphify=None, repo=repo)

    node_count = 0
    edge_count = 0
    has_graph = status.imported_exists
    if has_graph:
        try:
            from ahadiff.graphify import parse_graph_json

            validate_state_path_no_symlinks(status.imported_path, allow_missing_leaf=False)
            graph = parse_graph_json(status.imported_path)
            node_count = len(graph.nodes)
            edge_count = len(graph.links)
        except Exception:
            has_graph = False
            pass

    response = GraphStatusResponse(
        enabled=status.enabled,
        source_exists=status.source_exists,
        has_graph=has_graph,
        freshness=status.freshness,
        node_count=node_count,
        edge_count=edge_count,
        source_path=(str(status.imported_path.relative_to(root)) if has_graph else None),
    )
    return response.model_dump(mode="json")


__all__ = ["get_graph_status"]
