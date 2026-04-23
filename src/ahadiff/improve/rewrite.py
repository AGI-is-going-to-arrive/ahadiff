from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ahadiff.eval.ratchet import should_trigger_phase25

if TYPE_CHECKING:
    from pathlib import Path

PHASE25_NOTE_PREFIX = "PHASE25:"
PHASE25_TRIGGER_REASON = "consecutive_discard_count=2"


@dataclass(frozen=True)
class Phase25Decision:
    should_run: bool
    trigger_reason: str | None


def decide_phase25(*, recent_statuses: tuple[str, ...], phase25_attempted: bool) -> Phase25Decision:
    if phase25_attempted:
        return Phase25Decision(should_run=False, trigger_reason=None)
    if not should_trigger_phase25(recent_statuses):
        return Phase25Decision(should_run=False, trigger_reason=None)
    return Phase25Decision(
        should_run=True,
        trigger_reason=PHASE25_TRIGGER_REASON,
    )


def phase25_note_payload(
    *,
    session_id: str,
    round_index: int,
    target_dimension: str,
    target_prompt: str,
    worktree_path: Path,
    commit_sha: str,
    trigger_reason: str,
    baseline_overall: float,
) -> dict[str, object]:
    return {
        "phase25": True,
        "phase25_note": f"{PHASE25_NOTE_PREFIX} {trigger_reason}",
        "improve_session_id": session_id,
        "round": round_index,
        "target_dimension": target_dimension,
        "target_prompt": target_prompt,
        "worktree_path": str(worktree_path),
        "stash_ref": commit_sha,
        "trigger_reason": trigger_reason,
        "baseline_overall": round(baseline_overall, 2),
    }


__all__ = [
    "PHASE25_NOTE_PREFIX",
    "PHASE25_TRIGGER_REASON",
    "Phase25Decision",
    "decide_phase25",
    "phase25_note_payload",
]
