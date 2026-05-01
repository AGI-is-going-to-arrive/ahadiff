from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .models import GraphifyGraph

from .matcher import match_concepts


@dataclass(frozen=True)
class ConceptLink:
    concept: str
    node_id: str
    node_label: str
    file_path: str | None
    score: float


_MAX_CONCEPT_LEN = 500


def link_concepts(
    graph: GraphifyGraph,
    concepts: Sequence[str],
    *,
    threshold: float = 0.5,
) -> tuple[ConceptLink, ...]:
    if not concepts or not graph.nodes:
        return ()
    concepts = [c[:_MAX_CONCEPT_LEN] for c in concepts]

    label_to_ids: dict[str, list[str]] = {}
    for node in graph.nodes:
        if node.label and node.label.strip():
            label_to_ids.setdefault(node.label, []).append(node.id)
    node_files = {n.id: n.file_path for n in graph.nodes}
    unique_labels = list(label_to_ids.keys())

    links: list[ConceptLink] = []
    for concept in concepts:
        matches = match_concepts(concept, unique_labels, threshold=threshold)
        for label, score in matches:
            if score <= 0.0:
                continue
            for nid in label_to_ids[label]:
                links.append(
                    ConceptLink(
                        concept=concept,
                        node_id=nid,
                        node_label=label,
                        file_path=node_files.get(nid),
                        score=score,
                    )
                )

    seen: set[tuple[str, str]] = set()
    deduped: list[ConceptLink] = []
    for lnk in links:
        key = (lnk.concept, lnk.node_id)
        if key not in seen:
            seen.add(key)
            deduped.append(lnk)

    return tuple(deduped)


def link_concepts_to_entries(
    graph: GraphifyGraph,
    entries: Sequence[dict[str, Any]],
    *,
    threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Link concept entries to graph nodes, writing ``graphify_node_id`` back.

    For each entry, the best-scoring match (highest score) is selected.
    Entries with no match keep ``graphify_node_id`` as ``None``.
    Returns a new list — input dicts are not mutated.
    """
    if not entries:
        return []
    if not graph.nodes:
        return [{**e, "graphify_node_id": None} for e in entries]

    concepts = [str(e.get("concept", e.get("term", "")))[:_MAX_CONCEPT_LEN] for e in entries]
    all_links = link_concepts(graph, concepts, threshold=threshold)

    best: dict[str, ConceptLink] = {}
    for lnk in all_links:
        existing = best.get(lnk.concept)
        if existing is None or lnk.score > existing.score:
            best[lnk.concept] = lnk

    result: list[dict[str, Any]] = []
    for entry, concept in zip(entries, concepts, strict=True):
        out = dict(entry)
        match = best.get(concept)
        out["graphify_node_id"] = match.node_id if match else None
        result.append(out)
    return result


__all__ = ["ConceptLink", "link_concepts", "link_concepts_to_entries"]
