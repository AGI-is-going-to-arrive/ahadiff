from __future__ import annotations

import math
from contextlib import suppress
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_runtime import (
    GRAPH_EDGE_WEIGHT_MAX,
    GRAPH_EDGE_WEIGHT_MIN,
    ConceptGraphEdge,
    ConceptGraphNode,
    ConceptGraphResponse,
    GraphEdgeConfidence,
    GraphProvenance,
    GraphStatusResponse,
)

if TYPE_CHECKING:
    from pathlib import PurePath

    from starlette.requests import Request

    from .state import ServeState

_DEFAULT_CONCEPT_GRAPH_LIMIT = 500
_MAX_CONCEPT_GRAPH_LIMIT = 2_000
_GRAPH_EDGE_CONFIDENCE_VALUES: frozenset[GraphEdgeConfidence] = frozenset(
    {"EXTRACTED", "INFERRED", "AMBIGUOUS"}
)


def api_relative_path(path: PurePath, root: PurePath) -> str:
    return path.relative_to(root).as_posix()


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


async def post_graph_refresh(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state = serve_state(request)
    payload = await to_thread.run_sync(_graph_refresh_sync, state)
    return JSONResponse(payload)


def _graph_refresh_sync(state: ServeState) -> dict[str, Any]:
    from ahadiff.core.paths import validate_state_path_no_symlinks
    from ahadiff.git.capture import import_graphify_artifact

    from .lock import serve_repo_write_lock

    root = state.state_dir.parent
    imported_path = state.state_dir / "graphify" / "graph.json"
    with serve_repo_write_lock(state, command="serve graph refresh"):
        validate_state_path_no_symlinks(imported_path, allow_missing_leaf=True)
        status = import_graphify_artifact(root, force=True)
        validate_state_path_no_symlinks(status.imported_path, allow_missing_leaf=False)
    return {
        "status": "ok",
        "nodes": _int_provenance_value(status.provenance.get("node_count")),
        "edges": _int_provenance_value(status.provenance.get("edge_count")),
    }


def _int_provenance_value(value: object) -> int:
    if not isinstance(value, str):
        return 0
    try:
        parsed = int(value)
    except ValueError:
        return 0
    return max(parsed, 0)


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

    provenance: GraphProvenance | None = None
    if has_graph:
        prov = status.provenance
        sha = prov.get("graph_sha256", "")
        imp_time = prov.get("import_time", "")
        parser_ver = prov.get("parser_version", "")
        if sha and imp_time and parser_ver:
            try:
                provenance = GraphProvenance(
                    graph_sha256=sha,
                    import_time=imp_time,
                    parser_version=parser_ver,
                )
            except Exception:
                provenance = None

    response = GraphStatusResponse(
        enabled=status.enabled,
        source_exists=status.source_exists,
        has_graph=has_graph,
        freshness=cast("Any", status.freshness),
        node_count=node_count,
        edge_count=edge_count,
        source_path=(api_relative_path(status.imported_path, root) if has_graph else None),
        provenance=provenance,
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
            update={
                "has_graph": False,
                "node_count": 0,
                "edge_count": 0,
                "source_path": None,
                "provenance": None,
            }
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
            metadata=dict(node.metadata),
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
        weight = _coerce_graph_edge_weight(edge.metadata.get("weight"))
        edge_metadata = edge.metadata or {}
        confidence = _coerce_graph_edge_confidence(edge_metadata.get("confidence"))
        edges.append(
            ConceptGraphEdge(
                id=f"{edge.source}->{edge.target}:{index}",
                source=edge.source,
                target=edge.target,
                relation=edge.relation,
                weight=weight,
                confidence=confidence,
            )
        )
    response_payload = ConceptGraphResponse(
        status=status,
        nodes=nodes,
        edges=edges,
        truncated=len(graph.nodes) > len(nodes) or dangling_or_truncated_edges > 0,
    ).model_dump(mode="json")
    for edge_payload in response_payload.get("edges", []):
        if isinstance(edge_payload, dict):
            edge_dict = cast("dict[str, Any]", edge_payload)
            if edge_dict.get("confidence") is None:
                edge_dict.pop("confidence", None)
    return response_payload


def _coerce_graph_edge_weight(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 1.0
    weight = float(value)
    if not math.isfinite(weight):
        return 1.0
    return min(GRAPH_EDGE_WEIGHT_MAX, max(GRAPH_EDGE_WEIGHT_MIN, weight))


def _coerce_graph_edge_confidence(value: object) -> GraphEdgeConfidence | None:
    if not isinstance(value, str):
        return None
    if value not in _GRAPH_EDGE_CONFIDENCE_VALUES:
        return None
    return value


__all__ = ["get_concept_graph", "get_graph_status", "post_graph_refresh"]
