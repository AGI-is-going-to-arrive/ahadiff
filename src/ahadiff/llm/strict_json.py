from __future__ import annotations

import json
import re
from typing import Any, cast

from ahadiff.core.json_util import safe_json_loads

_JSON_FENCE_RE = re.compile(
    r"```(?P<lang>[^\r\n`]*)\r?\n(?P<body>[\s\S]*?)```",
    re.IGNORECASE,
)


def strict_json_envelope(
    payload: str,
    *,
    root_key: str,
    allow_empty: bool,
) -> dict[str, Any]:
    parsed: Any = safe_json_loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError(f"structured output must be a JSON object with {root_key!r}")
    parsed_map = cast("dict[str, Any]", parsed)
    if set(parsed_map) != {root_key}:
        raise ValueError(f"structured output must contain only {root_key!r}")
    items = parsed_map[root_key]
    if not isinstance(items, list):
        raise ValueError(f"structured output {root_key!r} must be an array")
    if not allow_empty and not items:
        raise ValueError(f"structured output {root_key!r} must not be empty")
    return parsed_map


def require_complete_json_for_fallback(payload: str) -> None:
    stripped = payload.strip()
    if not stripped:
        raise ValueError("structured output payload is empty")
    if _complete_json_value_exists(stripped) or _complete_jsonl_values_exist(stripped):
        return
    raise ValueError("structured output is incomplete or malformed; retry required")


def _complete_json_value_exists(text: str) -> bool:
    for candidate in _top_level_json_candidates(text):
        try:
            safe_json_loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        return True
    return False


def _top_level_json_candidates(text: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for match in _JSON_FENCE_RE.finditer(text):
        language = (match.group("lang") or "").strip().casefold()
        if language and language != "json":
            continue
        body = match.group("body").strip()
        if body:
            candidates.append(body)
    first_json = _first_json_start(text)
    if first_json < 0:
        return tuple(dict.fromkeys((*candidates, text)))
    fragment = text[first_json:].strip()
    if first_json == 0:
        candidates.append(fragment)
        return tuple(dict.fromkeys(candidates))
    decoder = json.JSONDecoder()
    try:
        _parsed, end_offset = decoder.raw_decode(fragment)
    except json.JSONDecodeError:
        candidates.append(fragment)
    else:
        candidates.append(fragment[:end_offset])
    return tuple(dict.fromkeys(candidates))


def _complete_jsonl_values_exist(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    for line in lines:
        try:
            parsed: Any = safe_json_loads(line)
        except (json.JSONDecodeError, ValueError):
            return False
        if not isinstance(parsed, dict):
            return False
    return True


def _first_json_start(text: str) -> int:
    starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
    return min(starts) if starts else -1


__all__ = ["require_complete_json_for_fallback", "strict_json_envelope"]
