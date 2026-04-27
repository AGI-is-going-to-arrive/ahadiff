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


def safe_json_loads(s: str | bytes, **kwargs: Any) -> Any:
    """Drop-in replacement for ``json.loads`` that rejects non-finite floats."""
    kwargs.pop("parse_constant", None)
    kwargs.pop("parse_float", None)
    kwargs.pop("cls", None)
    return json.loads(
        s,
        parse_constant=_reject_constants,
        parse_float=_parse_finite_float,
        **kwargs,
    )
