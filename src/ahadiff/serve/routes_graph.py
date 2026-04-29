from __future__ import annotations

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

    from ahadiff.git.capture import detect_graphify_status

    root = Path(str(state_dir)).parent
    status = detect_graphify_status(root, use_graphify=None)

    node_count = 0
    edge_count = 0
    if status.has_graph:
        try:
            from ahadiff.graphify import parse_graph_json

            graph = parse_graph_json(status.source_path)
            node_count = len(graph.nodes)
            edge_count = len(graph.links)
        except Exception:
            pass

    response = GraphStatusResponse(
        enabled=status.enabled,
        source_exists=status.source_exists,
        has_graph=status.has_graph,
        freshness=status.freshness,
        node_count=node_count,
        edge_count=edge_count,
        source_path=(str(status.source_path.relative_to(root)) if status.source_exists else None),
    )
    return response.model_dump(mode="json")


__all__ = ["get_graph_status"]
