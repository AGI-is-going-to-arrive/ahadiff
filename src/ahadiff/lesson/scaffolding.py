from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ahadiff.contracts import ScaffoldingLevel

_LEARNING_STATES = {"learning", "relearning"}
_REVIEW_STATES = {"review"}


def compute_scaffolding_level(
    *,
    fsrs_state: str | Mapping[str, object] | None,
    recent_successes: int = 0,
) -> ScaffoldingLevel:
    parsed = parse_fsrs_state(fsrs_state)
    if parsed is None:
        return "full"
    state_name = _normalized_state_name(parsed)
    stability_days = _stability_days(parsed)
    if state_name in _LEARNING_STATES:
        return "full"
    if stability_days is None or stability_days < 3.0:
        return "full"
    if state_name in _REVIEW_STATES and stability_days < 14.0:
        return "hint"
    if stability_days >= 14.0 and recent_successes >= 2:
        return "compact"
    return "hint"


def parse_fsrs_state(fsrs_state: str | Mapping[str, object] | None) -> dict[str, object] | None:
    if fsrs_state is None:
        return None
    if isinstance(fsrs_state, str):
        parsed = json.loads(fsrs_state)
        if not isinstance(parsed, dict):
            return None
        return cast("dict[str, object]", parsed)
    return dict(fsrs_state)


def _normalized_state_name(state: Mapping[str, object]) -> str:
    raw_state = state.get("state_name", state.get("state"))
    if isinstance(raw_state, str):
        return raw_state.strip().casefold()
    return ""


def _stability_days(state: Mapping[str, object]) -> float | None:
    raw_stability = state.get("stability_days", state.get("stability"))
    if not isinstance(raw_stability, int | float):
        return None
    return float(raw_stability)


__all__ = ["compute_scaffolding_level", "parse_fsrs_state"]
