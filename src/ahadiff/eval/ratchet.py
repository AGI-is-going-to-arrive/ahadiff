from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from ahadiff.contracts import RATCHET_COUNTED_STATUSES, ResultEvent
from ahadiff.core.json_util import safe_json_loads
from ahadiff.git.repo import run_git

if TYPE_CHECKING:
    import pathlib as _pathlib
    from collections.abc import Collection, Sequence

    from .evaluator import ScoreReport

    Path = _pathlib.Path
else:
    import pathlib as _pathlib

    Path = _pathlib.Path

RATCHETABLE_SOURCE_KINDS = frozenset({"git_ref", "git_since"})
_MAX_FINALIZED_MARKER_BYTES = 64 * 1024


@dataclass(frozen=True)
class RatchetDecision:
    status: str
    base_ref: str | None = None
    note_payload: dict[str, object] | None = None

    def rendered_note_json(self) -> str | None:
        if self.note_payload is None:
            return None
        return json.dumps(self.note_payload, ensure_ascii=False, sort_keys=True)


def decide_learn_ratchet(
    *,
    workspace_root: Path,
    report: ScoreReport,
    prior_events: Sequence[ResultEvent],
) -> RatchetDecision:
    if not has_git_ancestry(workspace_root, report.source_kind, report.source_ref):
        return RatchetDecision(
            status="non_ratcheted",
            note_payload={
                "ratchet_reason": "no_git_ancestry",
                "source_kind": report.source_kind,
            },
        )

    baseline = select_baseline_event(
        workspace_root=workspace_root,
        source_ref=report.source_ref,
        prior_events=prior_events,
        allowed_event_types=frozenset({"learn"}),
    )
    if baseline is None:
        return RatchetDecision(status="baseline")

    note_payload: dict[str, object] = {
        "baseline_overall": round(baseline.overall, 2),
    }
    if report.degraded_flags and report.overall < baseline.overall:
        note_payload["ratchet_note"] = "degraded_comparison"
        return RatchetDecision(
            status="keep",
            base_ref=baseline.source_ref,
            note_payload=note_payload,
        )

    status = "keep" if report.overall >= baseline.overall else "discard"
    return RatchetDecision(status=status, base_ref=baseline.source_ref, note_payload=note_payload)


def select_baseline_event(
    *,
    workspace_root: Path,
    source_ref: str,
    prior_events: Sequence[ResultEvent],
    allowed_event_types: Collection[str] | None = None,
) -> ResultEvent | None:
    best_event: ResultEvent | None = None
    best_distance: int | None = None
    for event in prior_events:
        if event.status not in RATCHET_COUNTED_STATUSES:
            continue
        if allowed_event_types is not None and event.event_type not in allowed_event_types:
            continue
        if not _event_has_matching_finalized_marker(workspace_root, event):
            continue
        if _event_has_degraded_flags(event):
            continue
        if not _looks_like_commitish(event.source_ref):
            continue
        if _is_ancestor(workspace_root, event.source_ref, source_ref):
            distance = _commit_distance(workspace_root, event.source_ref, source_ref)
            if distance is None:
                continue
            if best_distance is None or distance < best_distance:
                best_event = event
                best_distance = distance
    return best_event


def has_git_ancestry(workspace_root: Path, source_kind: str, source_ref: str) -> bool:
    if source_kind not in RATCHETABLE_SOURCE_KINDS:
        return False
    return _looks_like_commitish(source_ref) and _git_commit_exists(workspace_root, source_ref)


def should_trigger_phase25(recent_statuses: Sequence[str]) -> bool:
    relevant = tuple(recent_statuses[-2:])
    return len(relevant) == 2 and relevant == ("discard", "discard")


def _git_commit_exists(workspace_root: Path, source_ref: str) -> bool:
    result = run_git(workspace_root, "cat-file", "-e", f"{source_ref}^{{commit}}", check=False)
    return result.returncode == 0


def _is_ancestor(workspace_root: Path, base_ref: str, source_ref: str) -> bool:
    result = run_git(
        workspace_root,
        "merge-base",
        "--is-ancestor",
        base_ref,
        source_ref,
        check=False,
    )
    return result.returncode == 0


def _commit_distance(workspace_root: Path, base_ref: str, source_ref: str) -> int | None:
    result = run_git(
        workspace_root,
        "rev-list",
        "--count",
        f"{base_ref}..{source_ref}",
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def _event_has_degraded_flags(event: ResultEvent) -> bool:
    if event.note_json is None:
        return False
    try:
        payload = safe_json_loads(event.note_json)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    payload_map = cast("dict[str, object]", payload)
    degraded_flags = payload_map.get("degraded_flags")
    if not isinstance(degraded_flags, dict):
        return False
    degraded_flag_map = cast("dict[str, object]", degraded_flags)
    return any(bool(value) for value in degraded_flag_map.values())


def _event_has_matching_finalized_marker(workspace_root: Path, event: ResultEvent) -> bool:
    if not event.run_id or ".." in event.run_id or "/" in event.run_id or "\\" in event.run_id:
        return False
    marker_path = workspace_root / ".ahadiff" / "runs" / event.run_id / "finalized.json"
    try:
        with marker_path.open("rb") as handle:
            marker_bytes = handle.read(_MAX_FINALIZED_MARKER_BYTES + 1)
    except OSError:
        return False
    if len(marker_bytes) > _MAX_FINALIZED_MARKER_BYTES:
        return False
    try:
        marker = safe_json_loads(marker_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(marker, dict):
        return False
    marker_payload = cast("dict[str, object]", marker)
    if str(marker_payload.get("event_id", "")) != event.event_id:
        return False
    return str(marker_payload.get("run_id", "")) == event.run_id


def _looks_like_commitish(value: str) -> bool:
    if not value:
        return False
    if value.startswith("sha256:"):
        return False
    return ":" not in value


__all__ = [
    "decide_learn_ratchet",
    "has_git_ancestry",
    "RatchetDecision",
    "select_baseline_event",
    "should_trigger_phase25",
]
