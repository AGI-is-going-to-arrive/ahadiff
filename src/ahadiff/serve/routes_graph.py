from __future__ import annotations

import math
from contextlib import suppress
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_runtime import (
    ConceptGraphEdge,
    ConceptGraphNode,
    ConceptGraphResponse,
    GraphStatusResponse,
)

if TYPE_CHECKING:
    from starlette.requests import Request

_DEFAULT_CONCEPT_GRAPH_LIMIT = 500
_MAX_CONCEPT_GRAPH_LIMIT = 2_000


async def get_graph_status(request: Request) -> JSONResponse:
    from .auth import serve_state

    state = serve_state(request)
    payload = await to_thread.run_sync(lambda: _graph_status_sync(state.state_dir))
    return JSONResponse(payload)


async def get_concept_graph(request: Request) -> JSONResponse:
    from .auth import serve_state

    state = serve_state(request)
    raw_limit = request.query_params.get("limit", str(_DEFAULT_CONCEPT_GRAPH_LIMIT))
    try:
        limit = min(max(int(raw_limit), 1), _MAX_CONCEPT_GRAPH_LIMIT)
    except (ValueError, TypeError):
        limit = _DEFAULT_CONCEPT_GRAPH_LIMIT
    payload = await to_thread.run_sync(lambda: _concept_graph_sync(state.state_dir, limit=limit))
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
        freshness=cast("Any", status.freshness),
        node_count=node_count,
        edge_count=edge_count,
        source_path=(str(status.imported_path.relative_to(root)) if has_graph else None),
    )
    return response.model_dump(mode="json")


def _concept_graph_sync(state_dir: object, *, limit: int) -> dict[str, Any]:
    from pathlib import Path

    from ahadiff.core.paths import validate_state_path_no_symlinks
    from ahadiff.graphify import parse_graph_json

    status = GraphStatusResponse.model_validate(_graph_status_sync(state_dir))
    if not status.has_graph or status.source_path is None:
        return ConceptGraphResponse(
            status=status,
            nodes=[],
            edges=[],
            truncated=False,
        ).model_dump(mode="json")

    root = Path(str(state_dir)).parent
    graph_path = root / status.source_path
    try:
        validate_state_path_no_symlinks(graph_path, allow_missing_leaf=False)
        graph = parse_graph_json(graph_path)
    except Exception:
        empty_status = status.model_copy(
            update={"has_graph": False, "node_count": 0, "edge_count": 0}
        )
        return ConceptGraphResponse(
            status=empty_status,
            nodes=[],
            edges=[],
            truncated=False,
        ).model_dump(mode="json")

    selected_nodes = graph.nodes[:limit]
    selected_ids = {node.id for node in selected_nodes}
    freshness = status.freshness
    nodes = [
        ConceptGraphNode(
            id=node.id,
            name=node.label or node.id,
            kind=node.kind,
            file_path=node.file_path,
            freshness=freshness,
            metadata=node.metadata,
        )
        for node in selected_nodes
    ]
    edges: list[ConceptGraphEdge] = []
    max_edges = limit * 2
    dangling_or_truncated_edges = 0
    for index, edge in enumerate(graph.links):
        if edge.source not in selected_ids or edge.target not in selected_ids:
            dangling_or_truncated_edges += 1
            continue
        if len(edges) >= max_edges:
            dangling_or_truncated_edges += 1
            continue
        weight_value = edge.metadata.get("weight")
        weight = float(weight_value) if isinstance(weight_value, int | float) else 1.0
        if not math.isfinite(weight):
            weight = 1.0
        edges.append(
            ConceptGraphEdge(
                id=f"{edge.source}->{edge.target}:{index}",
                source=edge.source,
                target=edge.target,
                relation=edge.relation,
                weight=weight,
            )
        )
    return ConceptGraphResponse(
        status=status,
        nodes=nodes,
        edges=edges,
        truncated=len(graph.nodes) > len(nodes) or dangling_or_truncated_edges > 0,
    ).model_dump(mode="json")


__all__ = ["get_concept_graph", "get_graph_status"]
