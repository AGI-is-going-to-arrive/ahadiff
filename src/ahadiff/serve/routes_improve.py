"""GET /api/improve/preflight - read-only preview of an improve session.

This endpoint is intentionally side-effect free:

* No filesystem writes, no git mutations, no worktree creation.
* No locks acquired (write lock or otherwise).
* Repo-level info is gathered through ``ahadiff.improve.preflight`` helpers
  that wrap ``git rev-parse`` / ``git diff --quiet`` and degrade to ``None``
  on failure.
* ``review.sqlite`` is opened through ``load_result_events_from_db`` which
  uses the standard read connection but never writes.
* Existing improve sessions are listed by globbing
  ``<state_dir>/improve/*.json``; each file is parsed in isolation and
  malformed sessions are skipped, never repaired.

The endpoint never leaks absolute paths: ``has_pending_worktree`` is the only
worktree-related field, and it is a boolean derived from ``Path.exists()``.
"""

from __future__ import annotations

import functools
import logging
import os
import stat
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_improve import (
    ImprovePreflightResponse,
    ImproveRepoState,
    ImproveRunSnapshot,
    ImproveSessionSummary,
)
from ahadiff.core.json_util import safe_json_loads
from ahadiff.improve.preflight import current_branch, current_head, prompts_are_dirty
from ahadiff.improve.program import (
    mutable_prompt_for_dimension,
    mutable_prompt_names,
)

from .auth import require_write_token, serve_state

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from .state import ServeState

log = logging.getLogger(__name__)

__all__ = ["get_improve_preflight"]

_FINALIZED_STATUSES = frozenset({"baseline", "keep", "keep_final"})
_MAX_SESSION_SUMMARIES = 20
_MAX_SESSION_BYTES = 256 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


async def get_improve_preflight(request: Request) -> JSONResponse:
    try:
        require_write_token(request)
    except PermissionError as exc:
        # Match the read-endpoint convention used by /api/concepts/ledger:
        # missing/invalid token returns 401 rather than 403 to keep the
        # client-side error taxonomy consistent.
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    state = serve_state(request)
    payload = await to_thread.run_sync(functools.partial(_preflight_sync, state))
    return JSONResponse(payload)


def _preflight_sync(state: ServeState) -> dict[str, Any]:
    state_dir = state.state_dir
    repo_root = state_dir.parent

    repo_state = ImproveRepoState(
        branch=current_branch(repo_root),
        head_sha=current_head(repo_root),
        prompts_dirty=prompts_are_dirty(repo_root),
    )

    provider_configured = _check_provider_configured(state)

    anchor_run, baseline_run, available, reason = _resolve_runs(state_dir)

    target_dimension: str | None = None
    target_prompt_file: str | None = None
    if anchor_run is not None and anchor_run.weakest_dim:
        target_dimension = anchor_run.weakest_dim
        target_prompt_file = mutable_prompt_for_dimension(anchor_run.weakest_dim)

    sessions = _list_sessions(state_dir)

    phase25_eligible = False
    phase25_trigger_reason: str | None = None
    if sessions:
        latest = sessions[0]
        if latest.last_status == "discard" and not latest.phase25_attempted:
            phase25_eligible = True
            phase25_trigger_reason = "latest_session_discarded"

    response = ImprovePreflightResponse(
        available=available,
        reason=reason,
        anchor_run=anchor_run,
        baseline_run=baseline_run,
        target_dimension=target_dimension,
        target_prompt_file=target_prompt_file,
        mutable_prompts=list(mutable_prompt_names()),
        phase25_eligible=phase25_eligible,
        phase25_trigger_reason=phase25_trigger_reason,
        existing_sessions=sessions,
        repo_state=repo_state,
        provider_configured=provider_configured,
    )
    return response.model_dump(mode="json")


def _resolve_runs(
    state_dir: Path,
) -> tuple[ImproveRunSnapshot | None, ImproveRunSnapshot | None, bool, str | None]:
    """Best-effort lookup of the latest finalized learn event and a baseline."""
    db_path = state_dir / "review.sqlite"
    if not db_path.exists():
        return None, None, False, "no_finalized_runs"

    try:
        from ahadiff.review.database import load_result_events_from_db

        events = load_result_events_from_db(db_path)
    except Exception:
        log.debug("failed to read result events for preflight", exc_info=True)
        return None, None, False, "no_finalized_runs"

    # ``load_result_events_from_db`` returns events ordered DESC by timestamp,
    # so index 0 is the most recent. Restrict to learn events with a finalized
    # status; non-ratcheted/crash/discard runs are not anchor candidates.
    learn_events = [
        ev
        for ev in events
        if ev.event_type == "learn"
        and ev.status in _FINALIZED_STATUSES
        and _has_finalized_run_marker(state_dir, ev.run_id, ev.event_id)
    ]
    if not learn_events:
        return None, None, False, "no_finalized_runs"

    latest = learn_events[0]
    anchor_run = ImproveRunSnapshot(
        run_id=latest.run_id,
        source_ref=latest.source_ref,
        overall=latest.overall,
        weakest_dim=latest.weakest_dim or None,
        finalized=True,
    )

    baseline_run: ImproveRunSnapshot | None = None
    for ev in learn_events[1:]:
        if ev.source_ref != latest.source_ref:
            continue
        baseline_run = ImproveRunSnapshot(
            run_id=ev.run_id,
            source_ref=ev.source_ref,
            overall=ev.overall,
            weakest_dim=ev.weakest_dim or None,
            finalized=True,
        )
        break

    return anchor_run, baseline_run, True, None


def _check_provider_configured(state: ServeState) -> bool:
    """Detect whether at least one provider exists in the per-repo config.

    Reads ``.ahadiff/config.toml`` directly with the standard config reader.
    Any exception is treated as "not configured" so the preflight never fails
    on a malformed file.
    """
    config_path = state.state_dir / "config.toml"
    if not config_path.exists():
        return False
    try:
        from ahadiff.core.config import read_config_data

        data = read_config_data(config_path)
    except Exception:
        log.debug("failed to read config.toml for provider check", exc_info=True)
        return False
    providers = data.get("providers")
    if isinstance(providers, dict) and providers:
        return True
    # Legacy: a top-level ``[llm]`` table with model_name/base_url is a valid
    # provider configuration even before the multi-provider table existed.
    llm = data.get("llm")
    if isinstance(llm, dict):
        llm_table = cast("dict[str, Any]", llm)
        model_name = llm_table.get("model_name")
        if isinstance(model_name, str) and model_name.strip():
            return True
    return False


def _list_sessions(state_dir: Path) -> list[ImproveSessionSummary]:
    """List up to ``_MAX_SESSION_SUMMARIES`` sessions, newest first.

    Ordering uses ``mtime`` so a recently-touched session appears first; this
    matches the convention used by ``ahadiff.improve.program.save_improve_session``
    which writes via ``replace`` and updates ``mtime`` on every save.
    """
    session_dir = state_dir / "improve"
    if not session_dir.is_dir():
        return []
    try:
        candidates = sorted(
            (p for p in session_dir.glob("*.json") if not p.name.startswith(".")),
            key=_safe_session_mtime,
            reverse=True,
        )
    except OSError:
        return []

    sessions: list[ImproveSessionSummary] = []
    for path in candidates[:_MAX_SESSION_SUMMARIES]:
        summary = _summary_from_path(path)
        if summary is not None:
            sessions.append(summary)
    return sessions


def _summary_from_path(path: Path) -> ImproveSessionSummary | None:
    try:
        raw = _read_session_json(path)
        loaded = safe_json_loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None
    data = cast("dict[str, Any]", loaded)

    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        session_id = path.stem
        if not session_id:
            return None

    worktree_path = data.get("worktree_path")
    has_pending_worktree = False
    if isinstance(worktree_path, str) and worktree_path:
        # Boolean only - we never expose the path itself in the response.
        try:
            from pathlib import Path as _Path

            has_pending_worktree = _Path(worktree_path).exists()
        except OSError:
            has_pending_worktree = False

    rounds_completed = data.get("rounds_completed")
    if not isinstance(rounds_completed, int) or rounds_completed < 0:
        rounds_completed = 0

    last_status = data.get("last_status")
    if not isinstance(last_status, str) or not last_status:
        last_status = None

    interrupted_round = data.get("interrupted_round")
    if not isinstance(interrupted_round, int):
        interrupted_round = None

    interrupted_stage = data.get("interrupted_stage")
    if not isinstance(interrupted_stage, str) or not interrupted_stage:
        interrupted_stage = None

    updated_at = data.get("updated_at")
    if not isinstance(updated_at, str):
        updated_at = ""

    phase25_attempted = bool(data.get("phase25_attempted"))

    try:
        return ImproveSessionSummary(
            session_id=session_id,
            rounds_completed=rounds_completed,
            last_status=last_status,
            phase25_attempted=phase25_attempted,
            has_pending_worktree=has_pending_worktree,
            interrupted_round=interrupted_round,
            interrupted_stage=interrupted_stage,
            updated_at=updated_at,
        )
    except ValueError:
        return None


def _safe_session_mtime(path: Path) -> float:
    try:
        path_stat = path.lstat()
    except OSError:
        return 0.0
    return float(getattr(path_stat, "st_mtime", 0.0))


def _read_session_json(path: Path) -> str:
    path_stat = path.lstat()
    if (
        stat.S_ISLNK(path_stat.st_mode)
        or _has_windows_reparse_point(path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or _is_hardlinked_regular_file(path_stat)
        or path_stat.st_size > _MAX_SESSION_BYTES
    ):
        raise ValueError("invalid improve session file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    try:
        opened_stat = os.fstat(fd)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _has_windows_reparse_point(opened_stat)
            or _is_hardlinked_regular_file(opened_stat)
            or opened_stat.st_size > _MAX_SESSION_BYTES
            or (opened_stat.st_dev, opened_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise ValueError("invalid improve session file")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd != -1:
            os.close(fd)


def _has_windows_reparse_point(path_stat: object) -> bool:
    if os.name != "nt":
        return False
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _is_hardlinked_regular_file(path_stat: os.stat_result) -> bool:
    return stat.S_ISREG(path_stat.st_mode) and getattr(path_stat, "st_nlink", 1) > 1


def _has_finalized_run_marker(state_dir: Path, run_id: str, event_id: str) -> bool:
    run_path = state_dir / "runs" / run_id
    try:
        run_stat = run_path.lstat()
    except OSError:
        return False
    if (
        not stat.S_ISDIR(run_stat.st_mode)
        or stat.S_ISLNK(run_stat.st_mode)
        or _has_windows_reparse_point(run_stat)
    ):
        return False
    marker_path = run_path / "finalized.json"
    try:
        marker_text = _read_session_json(marker_path)
        marker = safe_json_loads(marker_text)
    except (OSError, ValueError):
        return False
    if not isinstance(marker, dict):
        return False
    marker_map = cast("dict[str, Any]", marker)
    return marker_map.get("run_id") == run_id and marker_map.get("event_id") == event_id
