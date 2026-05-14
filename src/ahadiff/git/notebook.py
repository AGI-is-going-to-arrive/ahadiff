from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ahadiff.core.json_util import safe_json_loads

_HEADER_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_HEADER_MAX_CHARS = 160


@dataclass(frozen=True)
class NotebookRender:
    text: str
    cell_count: int
    warnings: tuple[str, ...]


def render_notebook_source_for_diff(data: bytes, *, display_path: str) -> NotebookRender | None:
    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    try:
        payload = safe_json_loads(decoded)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    payload_map = cast("dict[str, Any]", payload)
    raw_cells = payload_map.get("cells")
    if not isinstance(raw_cells, list):
        return None
    cells = cast("list[object]", raw_cells)

    warnings: list[str] = []
    lines = [
        f"# Notebook source view: {_header_text(Path(display_path).as_posix())}",
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
            lines.extend(source_text.splitlines())
        lines.append("")
    if not cells:
        warnings.append("notebook has no cells")
        lines.append("# %% [empty] cell 0")
        lines.append("")
    return NotebookRender(text="\n".join(lines), cell_count=len(cells), warnings=tuple(warnings))


def _cell_type(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return _header_text(value)
    return "unknown"


def _header_text(value: str) -> str:
    cleaned = _HEADER_CONTROL_RE.sub(" ", value).strip()
    if not cleaned:
        return "unknown"
    if len(cleaned) > _HEADER_MAX_CHARS:
        return cleaned[: _HEADER_MAX_CHARS - 3] + "..."
    return cleaned


def _cell_source(value: object, warnings: list[str], *, index: int) -> str:
    if isinstance(value, str):
        return value.replace("\r\n", "\n")
    if isinstance(value, list):
        parts: list[str] = []
        for item in cast("list[object]", value):
            if isinstance(item, str):
                parts.append(item)
            elif item is not None:
                warnings.append(f"cell {index} source contains non-string entries")
        return "".join(parts).replace("\r\n", "\n")
    if value is None:
        warnings.append(f"cell {index} source is null")
        return ""
    warnings.append(f"cell {index} source is not a string or list")
    return ""
