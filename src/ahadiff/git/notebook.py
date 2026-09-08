from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads

if TYPE_CHECKING:
    from collections.abc import Iterator

_HEADER_MAX_CHARS = 160
_MAX_JSON_DEPTH = 128
_JSON_DEPTH_ERROR = f"Notebook JSON nesting exceeds {_MAX_JSON_DEPTH} levels"


@dataclass(frozen=True)
class NotebookRender:
    text: str
    cell_count: int
    warnings: tuple[str, ...]
    cell_spans: tuple[dict[str, object], ...] = ()


def render_notebook_source_for_diff(data: bytes) -> NotebookRender | None:
    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    try:
        payload: object = safe_json_loads(decoded, object_pairs_hook=_unique_notebook_keys)
    except RecursionError:
        raise InputError(_JSON_DEPTH_ERROR) from None
    except (json.JSONDecodeError, ValueError):
        return None
    _validate_json_depth(payload)
    if not isinstance(payload, dict):
        return None
    payload_map = cast("dict[str, Any]", payload)
    raw_cells = payload_map.get("cells")
    if not isinstance(raw_cells, list):
        return None
    cells = cast("list[object]", raw_cells)

    warnings: list[str] = []
    cell_spans: list[dict[str, object]] = []
    lines = [
        "# Notebook source view",
        "# Metadata and outputs are intentionally ignored by AhaDiff.",
        "",
    ]
    for index, raw_cell in enumerate(cells):
        if not isinstance(raw_cell, dict):
            warnings.append(f"cell {index} is not an object")
            cell_type = "unknown"
            cell_id = None
            source_text = ""
        else:
            cell = cast("dict[str, object]", raw_cell)
            cell_type = _cell_type(cell.get("cell_type"))
            cell_id = cell.get("id")
            source_text = _cell_source(cell.get("source"), warnings, index=index)
        suffix = f" id={_header_text(cell_id)}" if isinstance(cell_id, str) and cell_id else ""
        lines.append(f"# %% [{cell_type}] cell {index}{suffix}")
        if source_text:
            source_start = len(lines) + 1
            lines.extend(source_text.splitlines())
            cell_spans.append(
                {
                    "cell_index": index,
                    "cell_id": _header_text(cell_id)
                    if isinstance(cell_id, str) and cell_id
                    else None,
                    "start": source_start,
                    "end": len(lines),
                }
            )
        lines.append("")
    if not cells:
        warnings.append("notebook has no cells")
        lines.append("# %% [empty] cell 0")
        lines.append("")
    return NotebookRender(
        text="\n".join(lines),
        cell_count=len(cells),
        warnings=tuple(warnings),
        cell_spans=tuple(cell_spans),
    )


def _unique_notebook_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("Notebook JSON contains an ambiguous duplicate key")
        payload[key] = value
    return payload


def _validate_json_depth(payload: object) -> None:
    # Iterator frames keep extra memory proportional to depth, even for wide
    # output/metadata arrays. JSON strings (including brackets) are leaf values.
    stack: list[Iterator[object]] = [iter((payload,))]
    while stack:
        try:
            value = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        if isinstance(value, dict):
            children = iter(cast("dict[str, object]", value).values())
        elif isinstance(value, list):
            children = iter(cast("list[object]", value))
        else:
            continue
        if len(stack) > _MAX_JSON_DEPTH:
            raise InputError(_JSON_DEPTH_ERROR)
        stack.append(children)


def _cell_type(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return _header_text(value)
    return "unknown"


def _header_text(value: str) -> str:
    _validate_notebook_text(value, source=False)
    cleaned = "".join(char if char.isprintable() else " " for char in value).strip()
    if not cleaned:
        return "unknown"
    if len(cleaned) > _HEADER_MAX_CHARS:
        return cleaned[: _HEADER_MAX_CHARS - 3] + "..."
    return cleaned


def _cell_source(value: object, warnings: list[str], *, index: int) -> str:
    if isinstance(value, str):
        _validate_notebook_text(value, source=True)
        return value.replace("\r\n", "\n")
    if isinstance(value, list):
        parts: list[str] = []
        for item in cast("list[object]", value):
            if isinstance(item, str):
                _validate_notebook_text(item, source=True)
                parts.append(item)
            elif item is not None:
                warnings.append(f"cell {index} source contains non-string entries")
        return "".join(parts).replace("\r\n", "\n")
    if value is None:
        warnings.append(f"cell {index} source is null")
        return ""
    warnings.append(f"cell {index} source is not a string or list")
    return ""


def _validate_notebook_text(value: str, *, source: bool) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise InputError("Notebook cell text contains invalid Unicode") from None
    if "\x00" in value:
        raise InputError("Notebook cell text contains a null character")
    if source and any(
        (ord(char) < 32 or ord(char) == 127) and char not in "\t\r\n" for char in value
    ):
        raise InputError("Notebook source contains unsupported control characters")
