from __future__ import annotations

from enum import Enum
from typing import Literal

FreshnessProjection = Literal["fresh", "stale", "unavailable", "disabled"]


class FreshnessState(Enum):
    CURRENT = "current"
    RECENT = "recent"
    STALE = "stale"
    OUTDATED = "outdated"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


_COMMIT_RECENT_THRESHOLD = 5
_COMMIT_OUTDATED_THRESHOLD = 50


def compute_freshness(
    graph_commit: str | None,
    head_commit: str,
    commit_count_between: int | None,
) -> FreshnessState:
    if graph_commit is None:
        return FreshnessState.UNKNOWN

    if graph_commit == head_commit:
        return FreshnessState.CURRENT

    if commit_count_between is None:
        return FreshnessState.UNKNOWN
    if commit_count_between < 0:
        return FreshnessState.UNKNOWN

    if commit_count_between <= _COMMIT_RECENT_THRESHOLD:
        return FreshnessState.RECENT

    if commit_count_between > _COMMIT_OUTDATED_THRESHOLD:
        return FreshnessState.OUTDATED

    return FreshnessState.STALE


_PROJECTION_MAP: dict[FreshnessState, FreshnessProjection] = {
    FreshnessState.CURRENT: "fresh",
    FreshnessState.RECENT: "fresh",
    FreshnessState.STALE: "stale",
    FreshnessState.OUTDATED: "stale",
    FreshnessState.UNKNOWN: "stale",
    FreshnessState.UNAVAILABLE: "unavailable",
    FreshnessState.DISABLED: "disabled",
}


def project_freshness(state: FreshnessState) -> FreshnessProjection:
    return _PROJECTION_MAP[state]
