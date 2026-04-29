from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection

    from .models import GraphifyGraph

_DEFAULT_HOP_DEPTH = 1
_MAX_HOP_DEPTH = 10


@dataclass(frozen=True)
class Subgraph:
    node_ids: frozenset[str]
    edge_indices: tuple[int, ...]
    hyperedge_indices: tuple[int, ...]


def slice_by_files(
    graph: GraphifyGraph,
    file_paths: Collection[str],
    *,
    hop_depth: int = _DEFAULT_HOP_DEPTH,
) -> Subgraph:
    if not file_paths or not graph.nodes:
        return Subgraph(
            node_ids=frozenset(),
            edge_indices=(),
            hyperedge_indices=(),
        )
    hop_depth = min(hop_depth, _MAX_HOP_DEPTH)

    path_set = frozenset(file_paths)
    seed_ids: set[str] = set()
    for node in graph.nodes:
        if node.file_path and node.file_path in path_set:
            seed_ids.add(node.id)

    if not seed_ids:
        return Subgraph(
            node_ids=frozenset(),
            edge_indices=(),
            hyperedge_indices=(),
        )

    reachable = set(seed_ids)

    if hop_depth > 0:
        adj: dict[str, set[str]] = {}
        for edge in graph.links:
            adj.setdefault(edge.source, set()).add(edge.target)
            adj.setdefault(edge.target, set()).add(edge.source)

        frontier = set(seed_ids)
        for _ in range(hop_depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                for neighbor in adj.get(nid, ()):
                    if neighbor not in reachable:
                        next_frontier.add(neighbor)
            reachable |= next_frontier
            frontier = next_frontier
            if not frontier:
                break

    valid_node_ids = frozenset(n.id for n in graph.nodes)
    reachable &= valid_node_ids

    edge_indices: list[int] = []
    for i, edge in enumerate(graph.links):
        if edge.source in reachable and edge.target in reachable:
            edge_indices.append(i)

    hyperedge_indices: list[int] = []
    for i, he in enumerate(graph.hyperedges):
        if he.nodes and all(nid in reachable for nid in he.nodes):
            hyperedge_indices.append(i)

    return Subgraph(
        node_ids=frozenset(reachable),
        edge_indices=tuple(edge_indices),
        hyperedge_indices=tuple(hyperedge_indices),
    )


def extract_subgraph(graph: GraphifyGraph, sub: Subgraph) -> GraphifyGraph:
    from .models import GraphifyGraph as GG

    n_links = len(graph.links)
    n_he = len(graph.hyperedges)
    return GG(
        directed=graph.directed,
        multigraph=graph.multigraph,
        graph=copy.deepcopy(graph.graph),
        nodes=[n.model_copy(deep=True) for n in graph.nodes if n.id in sub.node_ids],
        links=[graph.links[i].model_copy(deep=True) for i in sub.edge_indices if 0 <= i < n_links],
        hyperedges=[
            graph.hyperedges[i].model_copy(deep=True)
            for i in sub.hyperedge_indices
            if 0 <= i < n_he
        ],
    )


__all__ = ["Subgraph", "extract_subgraph", "slice_by_files"]
