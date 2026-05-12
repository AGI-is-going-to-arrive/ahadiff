"""Read/write surfaces for the opt-in Diffity-style learning loop.

Routes are not registered when ``challenge.enabled`` is false; the
:func:`require_feature_enabled` check below returns ``FEATURE_UNAVAILABLE``
so probing them yields a stable 501 instead of leaking a 404 that could be
mistaken for a stale build.
"""

from __future__ import annotations

import errno
import os
import stat
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.challenge import (
    ChallengeStage,
    InvalidTransitionError,
    adapt_from_gaps,
    build_challenge,
    create_state,
    is_feature_enabled,
    read_manifest,
    read_state,
    review_attempt,
    write_manifest,
    write_state,
)
from ahadiff.contracts import ErrorCode
from ahadiff.core.errors import InputError

from ._errors import error_response
from .auth import require_write_token, serve_state
from .config_runtime import load_serve_config_snapshot
from .lock import serve_repo_write_lock

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from ahadiff.challenge.manifest import ChallengeManifest
    from ahadiff.challenge.state import ChallengeState

    from .state import ServeState
else:
    Request = Any
    ChallengeManifest = Any
    ChallengeState = Any
    ServeState = Any


def _feature_enabled(state: ServeState) -> bool:
    try:
        snapshot = load_serve_config_snapshot(state)
    except Exception:
        return False
    return is_feature_enabled(snapshot)


def _feature_unavailable() -> JSONResponse:
    return error_response(
        ErrorCode.FEATURE_UNAVAILABLE,
        "challenge_engine_disabled",
        details={"feature": "challenge"},
    )


async def post_challenge_build(request: Request) -> JSONResponse:
    state = serve_state(request)
    if not _feature_enabled(state):
        return _feature_unavailable()
    require_write_token(request)
    raw_payload: Any = await request.json()
    if not isinstance(raw_payload, dict):
        raise InputError("request body must be a JSON object")
    payload = cast("dict[str, Any]", raw_payload)
    raw_run_id: Any = payload.get("run_id")
    if not isinstance(raw_run_id, str) or not raw_run_id.strip():
        raise InputError("run_id is required")
    run_id = raw_run_id.strip()
    requested_challenge_id_raw: Any = payload.get("challenge_id")
    requested_challenge_id: str | None = None
    if isinstance(requested_challenge_id_raw, str) and requested_challenge_id_raw.strip():
        requested_challenge_id = requested_challenge_id_raw.strip()

    manifest, challenge_state = await to_thread.run_sync(
        _build_challenge_sync,
        state,
        run_id,
        requested_challenge_id,
    )
    return JSONResponse(
        {
            "state": challenge_state.to_payload(),
            "manifest": manifest.to_payload(),
        }
    )


async def get_challenge(request: Request) -> JSONResponse:
    state = serve_state(request)
    if not _feature_enabled(state):
        return _feature_unavailable()
    challenge_id = _challenge_id_from_path(request)
    challenge_state, manifest = await to_thread.run_sync(
        _read_challenge_sync,
        state,
        challenge_id,
    )
    return JSONResponse(
        {
            "state": challenge_state.to_payload(),
            "manifest": manifest.to_payload() if manifest is not None else None,
        }
    )


async def post_challenge_advance(request: Request) -> JSONResponse:
    state = serve_state(request)
    if not _feature_enabled(state):
        return _feature_unavailable()
    require_write_token(request)
    challenge_id = _challenge_id_from_path(request)
    raw_payload: Any = await request.json() if await _has_body(request) else {}
    payload = cast("dict[str, Any]", raw_payload if isinstance(raw_payload, dict) else {})
    target_stage = _parse_target_stage(payload, key="target_stage")
    next_state = await to_thread.run_sync(
        _advance_challenge_sync,
        state,
        challenge_id,
        target_stage,
    )
    return JSONResponse({"state": next_state.to_payload()})


async def post_challenge_abort(request: Request) -> JSONResponse:
    state = serve_state(request)
    if not _feature_enabled(state):
        return _feature_unavailable()
    require_write_token(request)
    challenge_id = _challenge_id_from_path(request)
    next_state = await to_thread.run_sync(_abort_challenge_sync, state, challenge_id)
    return JSONResponse({"state": next_state.to_payload()})


async def post_challenge_review(request: Request) -> JSONResponse:
    state = serve_state(request)
    if not _feature_enabled(state):
        return _feature_unavailable()
    require_write_token(request)
    challenge_id = _challenge_id_from_path(request)
    raw_payload: Any = await request.json()
    if not isinstance(raw_payload, dict):
        raise InputError("request body must be a JSON object")
    payload = cast("dict[str, Any]", raw_payload)
    learner_diff_raw: Any = payload.get("learner_diff", "")
    if not isinstance(learner_diff_raw, str):
        raise InputError("learner_diff must be a string")

    result = await to_thread.run_sync(
        _review_challenge_sync,
        state,
        challenge_id,
        learner_diff_raw,
    )
    return JSONResponse(result)


async def get_challenge_feedback(request: Request) -> JSONResponse:
    state = serve_state(request)
    if not _feature_enabled(state):
        return _feature_unavailable()
    challenge_id = _challenge_id_from_path(request)
    feedback = await to_thread.run_sync(_load_feedback_sync, state, challenge_id)
    return JSONResponse(feedback)


def _challenge_id_from_path(request: Request) -> str:
    path_params = cast("dict[str, Any]", getattr(request, "path_params", {}) or {})
    raw_id = path_params.get("challenge_id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise InputError("challenge_id path parameter is required")
    return raw_id.strip()


async def _has_body(request: Request) -> bool:
    body = await request.body()
    return bool(body and body.strip())


def _parse_target_stage(payload: dict[str, Any], *, key: str) -> ChallengeStage | None:
    raw = payload.get(key)
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise InputError(f"{key} must be a string if provided")
    try:
        return ChallengeStage(raw)
    except ValueError as exc:
        raise InputError(f"{key} is not a valid challenge stage: {raw!r}") from exc


def _build_challenge_sync(
    state: ServeState,
    run_id: str,
    requested_challenge_id: str | None,
) -> tuple[ChallengeManifest, ChallengeState]:
    with serve_repo_write_lock(state, command="serve challenge build"):
        manifest = build_challenge(
            source_run_id=run_id,
            state_dir=state.state_dir,
            challenge_id=requested_challenge_id,
        )
        challenge_state = create_state(
            challenge_id=manifest.challenge_id,
            source_run_id=run_id,
        )
        write_state(state.state_dir, challenge_state)
        write_manifest(state.state_dir, manifest)
        return manifest, challenge_state


def _read_challenge_sync(
    state: ServeState,
    challenge_id: str,
) -> tuple[ChallengeState, ChallengeManifest | None]:
    challenge_state = read_state(state.state_dir, challenge_id)
    try:
        manifest = read_manifest(state.state_dir, challenge_id)
    except InputError:
        manifest = None
    return challenge_state, manifest


def _advance_challenge_sync(
    state: ServeState,
    challenge_id: str,
    target_stage: ChallengeStage | None,
) -> ChallengeState:
    with serve_repo_write_lock(state, command="serve challenge advance"):
        current = read_state(state.state_dir, challenge_id)
        # Guard: CHALLENGE → REVIEW/ADAPT must go through POST /review so the
        # learner_diff is actually evaluated and a feedback envelope is persisted.
        # Allowing /advance to slide CHALLENGE forward let clients silently
        # "complete" a challenge without submitting any diff at all. IDLE remains
        # reachable via POST /abort.
        if current.stage is ChallengeStage.CHALLENGE and target_stage in {
            ChallengeStage.REVIEW,
            ChallengeStage.ADAPT,
        }:
            raise InvalidTransitionError(
                "advancing past 'challenge' requires submitting a learner diff "
                "via POST /review; use /abort to return to idle"
            )
        if target_stage is None:
            if current.stage is ChallengeStage.CHALLENGE:
                raise InvalidTransitionError(
                    "advancing past 'challenge' requires submitting a learner diff "
                    "via POST /review; use /abort to return to idle"
                )
            target_stage = _default_next_stage(current.stage)
        try:
            next_state = current.transition(target_stage)
        except InvalidTransitionError:
            raise
        write_state(state.state_dir, next_state)
        return next_state


def _abort_challenge_sync(state: ServeState, challenge_id: str) -> ChallengeState:
    with serve_repo_write_lock(state, command="serve challenge abort"):
        current = read_state(state.state_dir, challenge_id)
        next_state = current.abort()
        write_state(state.state_dir, next_state)
        return next_state


def _review_challenge_sync(
    state: ServeState,
    challenge_id: str,
    learner_diff: str,
) -> dict[str, Any]:
    with serve_repo_write_lock(state, command="serve challenge review"):
        current = read_state(state.state_dir, challenge_id)
        if current.stage is not ChallengeStage.CHALLENGE:
            raise InvalidTransitionError(
                f"challenge must be in 'challenge' stage to submit a review "
                f"(currently {current.stage.value!r})"
            )
        manifest = read_manifest(state.state_dir, challenge_id)
        feedback = review_attempt(manifest=manifest, learner_diff=learner_diff)
        next_state = current.transition(ChallengeStage.REVIEW)
        write_state(state.state_dir, next_state)

        adapt_summary = adapt_from_gaps(
            challenge_id=challenge_id,
            gap_claim_ids=feedback.get("gap_claim_ids", []),
            db_path=state.review_db_path,
        )
        after_adapt = next_state.transition(ChallengeStage.ADAPT)
        write_state(state.state_dir, after_adapt)
        final_state = after_adapt.transition(ChallengeStage.IDLE)
        write_state(state.state_dir, final_state)

        feedback_payload = {
            **feedback,
            "adapt": adapt_summary,
            "state": final_state.to_payload(),
        }
        _write_feedback(state, challenge_id, feedback_payload)
        return feedback_payload


def _load_feedback_sync(state: ServeState, challenge_id: str) -> dict[str, Any]:
    from ahadiff.challenge.state import challenge_dir
    from ahadiff.core.json_util import safe_json_loads

    target_dir = challenge_dir(state.state_dir, challenge_id)
    feedback_path = target_dir / "feedback.json"
    if not feedback_path.exists():
        return {"feedback": None}
    raw = _read_feedback_text(feedback_path, max_bytes=5_000_000)
    payload = safe_json_loads(raw)
    if not isinstance(payload, dict):
        return {"feedback": None}
    return {"feedback": payload}


def _read_feedback_text(path: Path, *, max_bytes: int) -> str:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        raise InputError("challenge feedback file does not exist") from None
    except OSError as exc:
        raise InputError("challenge feedback file is unreadable") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError("challenge feedback file must not be a symlink")
    if bool(getattr(path_stat, "st_file_attributes", 0) & 0x400):
        raise InputError("challenge feedback file must not be a Windows reparse point or junction")
    if not stat.S_ISREG(path_stat.st_mode):
        raise InputError("challenge feedback file must be a regular file")
    if getattr(path_stat, "st_nlink", 1) > 1:
        raise InputError("challenge feedback file must not be a hardlink")
    if path_stat.st_size > max_bytes:
        raise InputError(f"challenge feedback file exceeds {max_bytes} bytes")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(os.fspath(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError("challenge feedback file must not be a symlink") from exc
        raise InputError("challenge feedback file is unreadable") from exc
    try:
        file_stat = os.fstat(fd)
        if (
            stat.S_ISLNK(file_stat.st_mode)
            or bool(getattr(file_stat, "st_file_attributes", 0) & 0x400)
            or not stat.S_ISREG(file_stat.st_mode)
            or getattr(file_stat, "st_nlink", 1) > 1
        ):
            raise InputError("challenge feedback file must be a regular no-follow file")
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError("challenge feedback file changed during validation")
        if file_stat.st_size > max_bytes:
            raise InputError(f"challenge feedback file exceeds {max_bytes} bytes")
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
                raise InputError(f"challenge feedback file exceeds {max_bytes} bytes")
        return b"".join(chunks).decode("utf-8", errors="replace")
    except OSError as exc:
        raise InputError("challenge feedback file is unreadable") from exc
    finally:
        os.close(fd)


def _write_feedback(
    state: ServeState,
    challenge_id: str,
    feedback: dict[str, Any],
) -> None:
    import json

    from ahadiff.challenge.state import challenge_dir
    from ahadiff.core.paths import atomic_write_state_text

    target_dir = challenge_dir(state.state_dir, challenge_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "feedback.json"
    atomic_write_state_text(
        path,
        json.dumps(feedback, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def _default_next_stage(current: ChallengeStage) -> ChallengeStage:
    mapping = {
        ChallengeStage.IDLE: ChallengeStage.BUILD,
        ChallengeStage.BUILD: ChallengeStage.TOUR,
        ChallengeStage.TOUR: ChallengeStage.CHALLENGE,
        ChallengeStage.CHALLENGE: ChallengeStage.REVIEW,
        ChallengeStage.REVIEW: ChallengeStage.ADAPT,
        ChallengeStage.ADAPT: ChallengeStage.IDLE,
    }
    return mapping[current]


__all__ = [
    "get_challenge",
    "get_challenge_feedback",
    "post_challenge_abort",
    "post_challenge_advance",
    "post_challenge_build",
    "post_challenge_review",
]
