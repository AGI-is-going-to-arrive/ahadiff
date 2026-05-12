"""Centralized safe JSON loading — rejects NaN / Infinity / -Infinity constants."""

from __future__ import annotations

import json
import math
from typing import Any


def _reject_constants(c: str) -> Any:
    raise ValueError(f"Disallowed JSON constant: {c!r}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"Non-finite JSON number: {value!r}")
    return parsed


_FORMULA_PREFIX_CHARS = frozenset("=+-@\t\r")


def safe_tsv_cell(value: object) -> str:
    """Escape spreadsheet formula injection prefixes for TSV cells."""
    text = str(value) if value is not None else ""
    if text and text[0] in _FORMULA_PREFIX_CHARS:
        return f"'{text}"
    return text


def safe_json_loads(
    s: str | bytes,
    *,
    max_input_bytes: int = 50 * 1024 * 1024,
    **kwargs: Any,
) -> Any:
    """Drop-in replacement for ``json.loads`` that rejects non-finite floats."""
    input_size = len(s.encode("utf-8")) if isinstance(s, str) else len(s)
    if input_size > max_input_bytes:
        raise ValueError(
            f"JSON input too large: {input_size} bytes exceeds limit of {max_input_bytes} bytes"
        )
    kwargs.pop("parse_constant", None)
    kwargs.pop("parse_float", None)
    kwargs.pop("cls", None)
    return json.loads(
        s,
        parse_constant=_reject_constants,
        parse_float=_parse_finite_float,
        **kwargs,
    )
