from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .matcher import match_concepts

if TYPE_CHECKING:
    from .models import GraphifyGraph

_MAX_GRAPH_SEARCH_RESULTS = 50


@dataclass(frozen=True)
class GraphSearchResult:
    node_id: str
    label: str
    file_path: str | None
    kind: str | None
    score: float


def search_graph_nodes(
    graph: GraphifyGraph,
    query: str,
    *,
    limit: int = 20,
    threshold: float = 0.3,
) -> tuple[GraphSearchResult, ...]:
    if not query or not query.strip() or not graph.nodes:
        return ()

    limit = min(max(limit, 1), _MAX_GRAPH_SEARCH_RESULTS)

    labels = [n.label for n in graph.nodes if n.label and n.label.strip()]
    if not labels:
        return ()

    matches = match_concepts(
        query,
        labels,
        threshold=threshold,
        max_results=limit,
    )
    if not matches:
        return ()

    label_to_nodes: dict[str, list[int]] = {}
    for i, node in enumerate(graph.nodes):
        if node.label and node.label.strip():
            label_to_nodes.setdefault(node.label, []).append(i)

    results: list[GraphSearchResult] = []
    seen_ids: set[str] = set()
    for label, score in matches:
        if score <= 0.0:
            continue
        for idx in label_to_nodes.get(label, ()):
            node = graph.nodes[idx]
            if node.id in seen_ids:
                continue
            seen_ids.add(node.id)
            results.append(
                GraphSearchResult(
                    node_id=node.id,
                    label=node.label,
                    file_path=node.file_path,
                    kind=node.kind,
                    score=score,
                )
            )

    results.sort(key=lambda r: r.score, reverse=True)
    return tuple(results[:limit])


__all__ = ["GraphSearchResult", "search_graph_nodes"]
