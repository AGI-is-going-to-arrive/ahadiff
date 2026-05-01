from __future__ import annotations

import html
import logging
import re
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads

from .models import GraphifyGraph

_log = logging.getLogger(__name__)

_SCRIPT_STYLE_TAG_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?(?:</\1>|$)",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_DANGEROUS_URI_RE = re.compile(
    r"\b(javascript|data|vbscript)\s*:",
    re.IGNORECASE,
)
_EVENT_HANDLER_RE = re.compile(
    r"\bon(?:abort|blur|change|click|dblclick|error|focus|input|invalid"
    r"|key(?:down|press|up)|load|mouse(?:down|enter|leave|move|out|over|up)"
    r"|pointer(?:down|enter|leave|move|up)|reset|resize|scroll|select"
    r"|submit|touch(?:cancel|end|move|start)|unload|wheel"
    r"|contextmenu|copy|cut|drag(?:end|enter|leave|over|start)?|drop|paste)\s*=",
    re.IGNORECASE,
)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MAX_LABEL_LEN = 500
_MAX_GRAPH_FILE_BYTES = 50 * 1024 * 1024  # 50 MiB
_MAX_GRAPH_EDGES = 50_000
_NODE_FILE_PATH_KEYS = ("file_path", "source_file", "path")
_NODE_KIND_KEYS = ("kind", "type", "file_type")
_EDGE_RELATION_KEYS = ("relation", "type")
_NODE_CORE_KEYS = frozenset({"id", "label", "metadata", *_NODE_FILE_PATH_KEYS, *_NODE_KIND_KEYS})
_EDGE_CORE_KEYS = frozenset({"source", "target", "metadata", *_EDGE_RELATION_KEYS})
_HYPEREDGE_CORE_KEYS = frozenset({"id", "nodes", "relation", "type", "metadata"})


def _sanitize_text(raw: str) -> str:
    cleaned = _unescape_html_entities(raw)
    cleaned = _CONTROL_CHAR_RE.sub("", cleaned)
    cleaned = _SCRIPT_STYLE_TAG_RE.sub("", cleaned)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = _DANGEROUS_URI_RE.sub("", cleaned)
    cleaned = _EVENT_HANDLER_RE.sub("", cleaned)
    if len(cleaned) > _MAX_LABEL_LEN:
        cleaned = cleaned[:_MAX_LABEL_LEN]
    return html.unescape(cleaned)


def _unescape_html_entities(raw: str) -> str:
    previous = raw
    for _ in range(3):
        current = html.unescape(previous)
        if current == previous:
            return current
        previous = current
    return previous


def _sanitize_json_value(value: object, *, sanitize_keys: bool = False) -> object:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, list):
        return [
            _sanitize_json_value(item, sanitize_keys=sanitize_keys)
            for item in cast("list[object]", value)
        ]
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, item in cast("dict[object, object]", value).items():
            raw_key = str(key)
            safe_key = _sanitize_text(raw_key) if sanitize_keys else raw_key
            sanitized[safe_key] = _sanitize_json_value(
                item,
                sanitize_keys=sanitize_keys or raw_key in {"graph", "metadata"},
            )
        return sanitized
    return value


def _first_present(item: dict[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in item:
            return item[key]
    return None


def _metadata_from_unknown(
    item: dict[str, object],
    *,
    core_keys: frozenset[str],
) -> dict[str, object]:
    raw_metadata = item.get("metadata")
    metadata = (
        dict(cast("dict[str, object]", raw_metadata)) if isinstance(raw_metadata, dict) else {}
    )
    for key, value in item.items():
        if key in core_keys:
            continue
        metadata[_sanitize_text(str(key))] = value
    return metadata


def _normalize_node(item: dict[str, object]) -> dict[str, object]:
    node: dict[str, object] = {}
    if "id" in item:
        node["id"] = item["id"]
    if "label" in item:
        node["label"] = item["label"]
    file_path = _first_present(item, _NODE_FILE_PATH_KEYS)
    if file_path is not None:
        node["file_path"] = file_path
    kind = _first_present(item, _NODE_KIND_KEYS)
    if kind is not None:
        node["kind"] = kind
    metadata = _metadata_from_unknown(item, core_keys=_NODE_CORE_KEYS)
    if metadata:
        node["metadata"] = metadata
    return node


def _normalize_edge(item: dict[str, object]) -> dict[str, object]:
    edge: dict[str, object] = {}
    if "source" in item:
        edge["source"] = item["source"]
    if "target" in item:
        edge["target"] = item["target"]
    relation = _first_present(item, _EDGE_RELATION_KEYS)
    if relation is not None:
        edge["relation"] = relation
    metadata = _metadata_from_unknown(item, core_keys=_EDGE_CORE_KEYS)
    if metadata:
        edge["metadata"] = metadata
    return edge


def _normalize_hyperedge(item: dict[str, object]) -> dict[str, object]:
    hyperedge: dict[str, object] = {}
    if "id" in item:
        hyperedge["id"] = item["id"]
    if "nodes" in item:
        hyperedge["nodes"] = item["nodes"]
    relation = _first_present(item, _EDGE_RELATION_KEYS)
    if relation is not None:
        hyperedge["relation"] = relation
    metadata = _metadata_from_unknown(item, core_keys=_HYPEREDGE_CORE_KEYS)
    if metadata:
        hyperedge["metadata"] = metadata
    return hyperedge


def _normalize_graph_object(obj: dict[str, object]) -> dict[str, object]:
    normalized = dict(obj)

    raw_nodes = normalized.get("nodes")
    if isinstance(raw_nodes, list):
        normalized["nodes"] = [
            _normalize_node(cast("dict[str, object]", item))
            for item in cast("list[object]", raw_nodes)
            if isinstance(item, dict)
        ]

    raw_links: object = normalized.get("links")
    raw_edges: object = normalized.pop("edges", None)
    raw_link_items: list[object] | None = None
    if isinstance(raw_links, list):
        raw_link_items = cast("list[object]", raw_links)
    elif isinstance(raw_edges, list):
        raw_link_items = cast("list[object]", raw_edges)
    if raw_link_items is not None:
        normalized["links"] = [
            _normalize_edge(cast("dict[str, object]", item))
            for item in raw_link_items
            if isinstance(item, dict)
        ]

    raw_hyperedges = normalized.get("hyperedges")
    if isinstance(raw_hyperedges, list):
        normalized["hyperedges"] = [
            _normalize_hyperedge(cast("dict[str, object]", item))
            for item in cast("list[object]", raw_hyperedges)
            if isinstance(item, dict)
        ]

    return normalized


def _deduplicate_nodes(
    nodes: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Remove duplicate node IDs, keeping the *last* occurrence.

    When duplicates are found a warning is logged so operators can fix the
    upstream graph generator.  Last-wins is chosen because later entries are
    more likely to be corrections.
    """
    seen: dict[str, int] = {}
    missing_id_indices: list[int] = []
    dropped_invalid_ids = 0
    for idx, node in enumerate(nodes):
        node_id = node.get("id")
        if "id" not in node:
            missing_id_indices.append(idx)
            continue
        if not isinstance(node_id, str) or node_id == "":
            dropped_invalid_ids += 1
            continue
        if node_id in seen:
            _log.warning("Duplicate graph node ID %r (keeping last occurrence)", node_id)
        seen[node_id] = idx
    if dropped_invalid_ids:
        _log.warning("Dropped %d graph node(s) with invalid IDs", dropped_invalid_ids)
    if len(seen) + len(missing_id_indices) == len(nodes):
        return nodes  # no duplicates — fast path
    keep_indices = set(seen.values()) | set(missing_id_indices)
    return [n for i, n in enumerate(nodes) if i in keep_indices]


def _remove_dangling_edges(
    links: list[dict[str, object]],
    node_ids: frozenset[str],
) -> list[dict[str, object]]:
    """Drop edges whose source or target does not reference an existing node."""
    valid: list[dict[str, object]] = []
    dropped = 0
    for edge in links:
        src = edge.get("source")
        tgt = edge.get("target")
        if isinstance(src, str) and isinstance(tgt, str) and src in node_ids and tgt in node_ids:
            valid.append(edge)
        else:
            dropped += 1
    if dropped:
        _log.warning("Dropped %d dangling edge(s) referencing missing nodes", dropped)
    return valid


def parse_graph_json_text(text: str) -> GraphifyGraph:
    try:
        data = safe_json_loads(text)
    except (ValueError, TypeError) as exc:
        raise InputError(f"Invalid graph JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise InputError("Graph JSON must be an object at the top level")

    obj = _normalize_graph_object(
        cast("dict[str, object]", _sanitize_json_value(cast("object", data)))
    )

    # --- duplicate node IDs: keep last occurrence ---
    raw_nodes = obj.get("nodes")
    if not isinstance(raw_nodes, list):
        raw_nodes = []
    deduped_nodes = _deduplicate_nodes(cast("list[dict[str, object]]", raw_nodes))
    obj["nodes"] = deduped_nodes

    # --- collect valid node IDs (reject empty-string IDs) ---
    node_ids: frozenset[str] = frozenset(
        str(n["id"]) for n in deduped_nodes if isinstance(n.get("id"), str) and n["id"] != ""
    )

    # --- edge count cap (check raw count first to bound work) ---
    raw_links = obj.get("links")
    if isinstance(raw_links, list):
        raw_links_typed = cast("list[dict[str, object]]", raw_links)
        if len(raw_links_typed) > _MAX_GRAPH_EDGES:
            n = len(raw_links_typed)
            raise InputError(f"Graph has {n} edges, exceeding the {_MAX_GRAPH_EDGES} edge limit")
        obj["links"] = _remove_dangling_edges(raw_links_typed, node_ids)

    try:
        return GraphifyGraph.model_validate(obj)
    except Exception as exc:
        raise InputError(f"Graph JSON validation failed: {exc}") from exc


def parse_graph_json(path: Path, *, max_bytes: int = _MAX_GRAPH_FILE_BYTES) -> GraphifyGraph:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise InputError(f"Cannot read graph file {path}: {exc}") from exc
    if size > max_bytes:
        raise InputError(f"Graph file {path} is {size} bytes, exceeding {max_bytes} byte limit")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"Cannot read graph file {path}: {exc}") from exc

    return parse_graph_json_text(text)
