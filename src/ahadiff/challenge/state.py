"""Challenge state machine: build -> tour -> challenge -> review -> adapt -> idle.

The state file lives at ``<state_dir>/challenges/<id>/state.json`` and is
written atomically through :func:`ahadiff.core.paths.atomic_write_state_text`
so we inherit no-follow / Windows reparse / leaf-symlink rejection. Aborts
from any non-IDLE stage are permitted to make the surface uncrashable.
"""

from __future__ import annotations

import errno
import json
import os
import re
import stat
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import (
    atomic_write_state_text,
    validate_state_path_no_symlinks,
)

CHALLENGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_CHALLENGE_FEATURE_KEY = "challenge.enabled"
_STATE_FILE_MAX_BYTES = 1_000_000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


class ChallengeStage(str, Enum):
    IDLE = "idle"
    BUILD = "build"
    TOUR = "tour"
    CHALLENGE = "challenge"
    REVIEW = "review"
    ADAPT = "adapt"


VALID_TRANSITIONS: dict[ChallengeStage, frozenset[ChallengeStage]] = {
    ChallengeStage.IDLE: frozenset({ChallengeStage.BUILD}),
    ChallengeStage.BUILD: frozenset({ChallengeStage.TOUR, ChallengeStage.IDLE}),
    ChallengeStage.TOUR: frozenset({ChallengeStage.CHALLENGE, ChallengeStage.IDLE}),
    ChallengeStage.CHALLENGE: frozenset({ChallengeStage.REVIEW, ChallengeStage.IDLE}),
    ChallengeStage.REVIEW: frozenset({ChallengeStage.ADAPT, ChallengeStage.IDLE}),
    ChallengeStage.ADAPT: frozenset({ChallengeStage.IDLE}),
}


class InvalidTransitionError(InputError):
    """Raised when an invalid state transition is requested."""


@dataclass(frozen=True)
class ChallengeState:
    challenge_id: str
    source_run_id: str
    stage: ChallengeStage
    created_at_utc: str
    updated_at_utc: str

    def transition(self, target: ChallengeStage) -> ChallengeState:
        allowed = VALID_TRANSITIONS.get(self.stage, frozenset())
        if target not in allowed:
            raise InvalidTransitionError(
                f"invalid transition {self.stage.value!r} -> {target.value!r}"
            )
        return replace(self, stage=target, updated_at_utc=_now_iso())

    def abort(self) -> ChallengeState:
        if self.stage is ChallengeStage.IDLE:
            return self
        if self.stage is ChallengeStage.ADAPT:
            return self.transition(ChallengeStage.IDLE)
        # All other non-terminal stages allow abort -> IDLE per VALID_TRANSITIONS.
        return self.transition(ChallengeStage.IDLE)

    def to_payload(self) -> dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "source_run_id": self.source_run_id,
            "stage": self.stage.value,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
        }


def is_feature_enabled(snapshot: Any | None) -> bool:
    """Return True if challenge engine is opt-in enabled in config.

    ``snapshot`` may be a :class:`ConfigSnapshot` or ``None``. The check is
    deliberately tolerant: any non-truthy / missing value returns False.
    """

    if snapshot is None:
        return False
    raw_values: Any = getattr(snapshot, "values", None)
    if not isinstance(raw_values, dict):
        return False
    values = cast("dict[str, Any]", raw_values)
    challenge_section: Any = values.get("challenge")
    if not isinstance(challenge_section, dict):
        return False
    section = cast("dict[str, Any]", challenge_section)
    return bool(section.get("enabled", False))


def validate_challenge_id(challenge_id: str) -> str:
    if not CHALLENGE_ID_PATTERN.fullmatch(challenge_id):
        raise InputError(
            "challenge_id must match [A-Za-z0-9._-]{1,64} and contain at least one character"
        )
    if challenge_id in {".", ".."}:
        raise InputError("challenge_id must not be '.' or '..'")
    if challenge_id.endswith("."):
        raise InputError("challenge_id must not end with '.' (Windows compatibility)")
    stem = challenge_id.split(".", 1)[0]
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        raise InputError("challenge_id must not be a Windows reserved device name")
    return challenge_id


def challenge_dir(state_dir: Path, challenge_id: str) -> Path:
    validate_challenge_id(challenge_id)
    target = state_dir / "challenges" / challenge_id
    validate_state_path_no_symlinks(target, allow_missing_leaf=True)
    return target


def create_state(*, challenge_id: str, source_run_id: str) -> ChallengeState:
    validate_challenge_id(challenge_id)
    if not source_run_id.strip():
        raise InputError("source_run_id must be a non-empty string")
    now = _now_iso()
    return ChallengeState(
        challenge_id=challenge_id,
        source_run_id=source_run_id,
        stage=ChallengeStage.BUILD,
        created_at_utc=now,
        updated_at_utc=now,
    )


def write_state(state_dir: Path, state: ChallengeState) -> Path:
    target_dir = challenge_dir(state_dir, state.challenge_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    validate_state_path_no_symlinks(target_dir, allow_missing_leaf=False)
    state_path = target_dir / "state.json"
    atomic_write_state_text(
        state_path,
        json.dumps(state.to_payload(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )
    return state_path


def ensure_rebuild_allowed(state_dir: Path, challenge_id: str) -> None:
    """Refuse overwriting an in-flight challenge with the same id."""

    target_dir = challenge_dir(state_dir, challenge_id)
    state_path = target_dir / "state.json"
    try:
        os.lstat(state_path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise InputError("existing challenge state is unreadable") from exc

    existing = read_state(state_dir, challenge_id)
    if existing.stage is not ChallengeStage.IDLE:
        raise InvalidTransitionError(
            "challenge rebuild is only allowed when the existing challenge state is idle"
        )


def read_state(state_dir: Path, challenge_id: str) -> ChallengeState:
    target_dir = challenge_dir(state_dir, challenge_id)
    state_path = target_dir / "state.json"
    if not state_path.exists():
        raise InputError(f"challenge state not found: {challenge_id}")
    raw = _read_regular_text(
        state_path,
        label="challenge state file",
        max_bytes=_STATE_FILE_MAX_BYTES,
    )
    try:
        payload = safe_json_loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"challenge state file is not valid JSON: {challenge_id}") from exc
    if not isinstance(payload, dict):
        raise InputError("challenge state file must contain a JSON object")
    return _state_from_payload(cast("dict[str, Any]", payload))


def _state_from_payload(payload: dict[str, Any]) -> ChallengeState:
    required = {"challenge_id", "source_run_id", "stage", "created_at_utc", "updated_at_utc"}
    missing = required - payload.keys()
    if missing:
        raise InputError(f"challenge state missing fields: {sorted(missing)}")
    raw_stage = payload["stage"]
    if not isinstance(raw_stage, str):
        raise InputError("challenge state.stage must be a string")
    try:
        stage = ChallengeStage(raw_stage)
    except ValueError as exc:
        raise InputError(f"challenge state.stage is not a valid stage: {raw_stage!r}") from exc
    payload_challenge_id = str(payload["challenge_id"])
    validate_challenge_id(payload_challenge_id)
    return ChallengeState(
        challenge_id=payload_challenge_id,
        source_run_id=str(payload["source_run_id"]),
        stage=stage,
        created_at_utc=str(payload["created_at_utc"]),
        updated_at_utc=str(payload["updated_at_utc"]),
    )


def _read_regular_text(path: Path, *, label: str, max_bytes: int) -> str:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        raise InputError(f"{label} does not exist: {path}") from None
    except OSError as exc:
        raise InputError(f"{label} is unreadable: {path}") from exc
    _validate_regular_state_artifact(path_stat, label=label)
    if path_stat.st_size > max_bytes:
        raise InputError(f"{label} exceeds {max_bytes} bytes")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(f"{label} must not be a symlink") from exc
        raise InputError(f"{label} is unreadable: {path}") from exc
    try:
        file_stat = os.fstat(fd)
        _validate_regular_state_artifact(file_stat, label=label)
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError(f"{label} changed during validation")
        if file_stat.st_size > max_bytes:
            raise InputError(f"{label} exceeds {max_bytes} bytes")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk_size = min(65_536, max_bytes + 1 - total)
            if chunk_size <= 0:
                break
            chunk = os.read(fd, chunk_size)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise InputError(f"{label} exceeds {max_bytes} bytes")
        return b"".join(chunks).decode("utf-8", errors="replace")
    except OSError as exc:
        raise InputError(f"{label} is unreadable: {path}") from exc
    finally:
        os.close(fd)


def _validate_regular_state_artifact(path_stat: os.stat_result, *, label: str) -> None:
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError(f"{label} must not be a symlink")
    if bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
        raise InputError(f"{label} must not be a Windows reparse point or junction")
    if not stat.S_ISREG(path_stat.st_mode):
        raise InputError(f"{label} must be a regular file")
    if getattr(path_stat, "st_nlink", 1) > 1:
        raise InputError(f"{label} must not be a hardlink")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "CHALLENGE_ID_PATTERN",
    "ChallengeStage",
    "ChallengeState",
    "InvalidTransitionError",
    "VALID_TRANSITIONS",
    "challenge_dir",
    "create_state",
    "ensure_rebuild_allowed",
    "is_feature_enabled",
    "read_state",
    "validate_challenge_id",
    "write_state",
]
