from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast

from ahadiff.review.scheduler import DEFAULT_DESIRED_RETENTION

if TYPE_CHECKING:
    from ahadiff.core.config import ConfigSnapshot

    from .state import ServeState


def load_serve_config_snapshot(state: ServeState) -> ConfigSnapshot:
    from ahadiff.core.config import load_config, load_workspace_config

    root = state.state_dir.parent
    try:
        return load_config(root)
    except Exception:
        return load_workspace_config(root)


def configured_desired_retention(state: ServeState) -> float:
    try:
        snapshot = load_serve_config_snapshot(state)
    except Exception:
        return DEFAULT_DESIRED_RETENTION

    raw_values = getattr(snapshot, "values", None)
    if not isinstance(raw_values, dict):
        return DEFAULT_DESIRED_RETENTION
    values = cast("dict[str, object]", raw_values)
    raw_learn = values.get("learn")
    if not isinstance(raw_learn, dict):
        return DEFAULT_DESIRED_RETENTION
    learn = cast("dict[str, object]", raw_learn)
    value = learn.get(
        "desired_retention",
        DEFAULT_DESIRED_RETENTION,
    )
    if not isinstance(value, int | float) or isinstance(value, bool):
        return DEFAULT_DESIRED_RETENTION
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.7 or parsed > 0.99:
        return DEFAULT_DESIRED_RETENTION
    return parsed


__all__ = ["configured_desired_retention", "load_serve_config_snapshot"]
