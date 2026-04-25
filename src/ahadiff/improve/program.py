from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.resources import files
from typing import TYPE_CHECKING, Any, cast

from ahadiff.core.errors import InputError

if TYPE_CHECKING:
    from pathlib import Path

IMPROVE_PROGRAM_FILENAME = "improve_program.md"
IMPROVE_SESSION_DIRNAME = "improve"
_MUTABLE_PROMPT_NAMES = (
    "claim_extract.md",
    "lesson_generate.md",
    "lesson_hint.md",
    "lesson_compact.md",
    "quiz_generate.md",
)
_MUTABLE_PROMPT_BY_DIMENSION: dict[str, str] = {
    "accuracy": "claim_extract.md",
    "evidence": "claim_extract.md",
    "diff_coverage": "claim_extract.md",
    "safety_privacy": "claim_extract.md",
    "quiz_transfer": "quiz_generate.md",
    "learnability": "lesson_generate.md",
    "spec_alignment": "lesson_generate.md",
    "conciseness": "lesson_compact.md",
}
DEFAULT_MUTABLE_PROMPT = "lesson_generate.md"
_IMMUTABLE_PROMPTS = frozenset({IMPROVE_PROGRAM_FILENAME})
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_UNSET = object()


@dataclass(frozen=True)
class ImproveSessionState:
    session_id: str
    suite: str
    anchor_run_id: str
    phase25_attempted: bool
    rounds_completed: int
    worktree_path: str | None
    created_at: str
    updated_at: str
    last_status: str | None = None
    outcome_statuses: tuple[str, ...] = ()


def mutable_prompt_names() -> tuple[str, ...]:
    return _MUTABLE_PROMPT_NAMES


def mutable_prompt_for_dimension(weakest_dim: str | None) -> str:
    if weakest_dim is None:
        return DEFAULT_MUTABLE_PROMPT
    return _MUTABLE_PROMPT_BY_DIMENSION.get(weakest_dim, DEFAULT_MUTABLE_PROMPT)


def load_improve_program(repo_root: Path) -> str:
    prompt_path = repo_root / "prompts" / IMPROVE_PROGRAM_FILENAME
    if prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8")
    try:
        package_prompt = files("ahadiff").joinpath("prompts", IMPROVE_PROGRAM_FILENAME)
        if package_prompt.is_file():
            return package_prompt.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass
    raise InputError(f"missing improve program prompt: {IMPROVE_PROGRAM_FILENAME}")


def improve_session_dir(state_dir: Path) -> Path:
    return state_dir / IMPROVE_SESSION_DIRNAME


def improve_session_file(state_dir: Path, session_id: str) -> Path:
    validate_improve_session_id(session_id)
    return improve_session_dir(state_dir) / f"{session_id}.json"


def save_improve_session(state_dir: Path, session: ImproveSessionState) -> Path:
    target = improve_session_file(state_dir, session.session_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.tmp")
    try:
        temp_path.write_text(
            json.dumps(asdict(session), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(target)
    finally:
        temp_path.unlink(missing_ok=True)
    return target


def load_improve_session(state_dir: Path, session_id: str) -> ImproveSessionState:
    target = improve_session_file(state_dir, session_id)
    if not target.exists():
        raise InputError(f"improve session does not exist: {session_id}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid improve session JSON: {target}") from exc
    if not isinstance(payload, dict):
        raise InputError(f"invalid improve session payload: {target}")
    payload_map = cast("dict[str, Any]", payload)
    payload_session_id = _require_string(payload_map, "session_id")
    validate_improve_session_id(payload_session_id)
    if payload_session_id != session_id:
        raise InputError(
            f"improve session id mismatch: expected {session_id}, got {payload_session_id}"
        )
    return ImproveSessionState(
        session_id=payload_session_id,
        suite=_require_string(payload_map, "suite"),
        anchor_run_id=_require_string(payload_map, "anchor_run_id"),
        phase25_attempted=_require_bool(payload_map, "phase25_attempted"),
        rounds_completed=_require_int(payload_map, "rounds_completed"),
        worktree_path=_optional_string(payload_map, "worktree_path"),
        created_at=_require_string(payload_map, "created_at"),
        updated_at=_require_string(payload_map, "updated_at"),
        last_status=_optional_string(payload_map, "last_status"),
        outcome_statuses=_load_outcome_statuses(payload_map),
    )


def create_improve_session(
    *,
    session_id: str,
    suite: str,
    anchor_run_id: str,
) -> ImproveSessionState:
    validate_improve_session_id(session_id)
    timestamp = _utc_now()
    return ImproveSessionState(
        session_id=session_id,
        suite=suite,
        anchor_run_id=anchor_run_id,
        phase25_attempted=False,
        rounds_completed=0,
        worktree_path=None,
        created_at=timestamp,
        updated_at=timestamp,
        last_status=None,
    )


def update_improve_session(
    session: ImproveSessionState,
    *,
    phase25_attempted: bool | None = None,
    rounds_completed: int | None = None,
    worktree_path: str | None | object = _UNSET,
    last_status: str | None | object = _UNSET,
    outcome_statuses: tuple[str, ...] | None = None,
) -> ImproveSessionState:
    next_worktree = session.worktree_path if worktree_path is _UNSET else worktree_path
    next_status = session.last_status if last_status is _UNSET else last_status
    return ImproveSessionState(
        session_id=session.session_id,
        suite=session.suite,
        anchor_run_id=session.anchor_run_id,
        phase25_attempted=(
            session.phase25_attempted if phase25_attempted is None else phase25_attempted
        ),
        rounds_completed=session.rounds_completed if rounds_completed is None else rounds_completed,
        worktree_path=(
            next_worktree if isinstance(next_worktree, str) or next_worktree is None else None
        ),
        created_at=session.created_at,
        updated_at=_utc_now(),
        last_status=next_status if isinstance(next_status, str) or next_status is None else None,
        outcome_statuses=session.outcome_statuses if outcome_statuses is None else outcome_statuses,
    )


def build_replay_learn_args(*, anchor_run_path: Path, metadata: dict[str, Any]) -> list[str]:
    source_kind = str(metadata.get("source_kind", ""))
    source_ref = str(metadata.get("source_ref", ""))
    base_ref = metadata.get("base_ref")

    if source_kind in {"git_ref", "git_since"} and base_ref and source_ref:
        return [f"{base_ref}..{source_ref}"]

    patch_path = anchor_run_path / "patch.diff"
    if not patch_path.exists():
        raise InputError(f"anchor run is missing patch.diff: {anchor_run_path}")
    return ["--patch", str(patch_path)]


def validate_mutable_prompt_name(filename: str) -> None:
    if filename in _IMMUTABLE_PROMPTS or filename not in mutable_prompt_names():
        allowed = ", ".join(mutable_prompt_names())
        raise InputError(f"improve may modify only mutable prompts: {allowed}")


def validate_improve_session_id(session_id: str) -> None:
    if (
        session_id in {"", ".", ".."}
        or session_id.startswith(".")
        or ".." in session_id
        or not _SESSION_ID_PATTERN.fullmatch(session_id)
    ):
        raise InputError("invalid improve session id")


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise InputError(f"improve session field {key!r} must be a non-empty string")
    return value


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError(f"improve session field {key!r} must be a string when present")
    return value


def _load_outcome_statuses(payload: dict[str, Any]) -> tuple[str, ...]:
    statuses = _statuses_from_sequence(payload.get("outcome_statuses"))
    if statuses:
        return statuses
    for key in ("outcomes", "rounds"):
        statuses = _statuses_from_sequence(payload.get(key))
        if statuses:
            return statuses
    last_status = _optional_string(payload, "last_status")
    rounds_completed = payload.get("rounds_completed")
    if last_status is not None and isinstance(rounds_completed, int) and rounds_completed > 0:
        return (last_status,)
    return ()


def _statuses_from_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    statuses: list[str] = []
    items = cast("list[object] | tuple[object, ...]", value)
    for item in items:
        if isinstance(item, str):
            statuses.append(item)
            continue
        if isinstance(item, dict):
            item_map = cast("dict[object, object]", item)
            status = item_map.get("status")
            if isinstance(status, str):
                statuses.append(status)
    return tuple(statuses)


def _require_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise InputError(f"improve session field {key!r} must be a boolean")
    return value


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise InputError(f"improve session field {key!r} must be an integer")
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "create_improve_session",
    "DEFAULT_MUTABLE_PROMPT",
    "build_replay_learn_args",
    "IMPROVE_PROGRAM_FILENAME",
    "IMPROVE_SESSION_DIRNAME",
    "improve_session_dir",
    "improve_session_file",
    "ImproveSessionState",
    "load_improve_program",
    "load_improve_session",
    "mutable_prompt_for_dimension",
    "mutable_prompt_names",
    "save_improve_session",
    "update_improve_session",
    "validate_improve_session_id",
    "validate_mutable_prompt_name",
]
