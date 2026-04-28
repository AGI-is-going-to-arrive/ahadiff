from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads

from .models import GraphifyGraph

_SCRIPT_STYLE_TAG_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?(?:</\1>|$)",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MAX_LABEL_LEN = 500


def _sanitize_text(raw: str) -> str:
    cleaned = _SCRIPT_STYLE_TAG_RE.sub("", raw)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    if len(cleaned) > _MAX_LABEL_LEN:
        cleaned = cleaned[:_MAX_LABEL_LEN]
    return cleaned


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


def parse_graph_json_text(text: str) -> GraphifyGraph:
    try:
        data = safe_json_loads(text)
    except (ValueError, TypeError) as exc:
        raise InputError(f"Invalid graph JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise InputError("Graph JSON must be an object at the top level")

    obj = cast("dict[str, object]", _sanitize_json_value(cast("object", data)))
    for key in ("nodes", "links", "hyperedges"):
        raw_items = obj.get(key)
        if isinstance(raw_items, list):
            obj[key] = [
                cast("dict[str, object]", item)
                for item in cast("list[object]", raw_items)
                if isinstance(item, dict)
            ]

    try:
        return GraphifyGraph.model_validate(obj)
    except Exception as exc:
        raise InputError(f"Graph JSON validation failed: {exc}") from exc


def parse_graph_json(path: Path) -> GraphifyGraph:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"Cannot read graph file {path}: {exc}") from exc

    return parse_graph_json_text(text)
