from __future__ import annotations

import atexit
import errno
import json
import logging
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.contracts import ProviderConfig, ResultEvent, compute_runtime_eval_bundle_version
from ahadiff.core.errors import ConfigError, InputError, StorageError
from ahadiff.core.ids import make_event_id
from ahadiff.core.json_util import safe_json_loads
from ahadiff.eval.evaluator import ScoreReport, evaluate_run
from ahadiff.eval.results import append_result, compute_prompt_version
from ahadiff.git.repo import run_git
from ahadiff.llm import ProviderRequest, make_provider
from ahadiff.llm.cost import effective_output_cap, resolve_model_limits
from ahadiff.review.database import load_result_events_for_improve_chain, load_result_events_from_db

from .program import (
    ImproveSessionState,
    build_replay_learn_args,
    create_improve_session,
    improve_session_dir,
    load_improve_program,
    load_improve_session,
    mutable_prompt_for_dimension,
    save_improve_session,
    update_improve_session,
    validate_improve_session_id,
    validate_mutable_prompt_name,
)
from .rewrite import decide_phase25, phase25_note_payload
from .targeted import load_score_snapshot, snapshot_from_report, verify_targeted_dimensions

if TYPE_CHECKING:
    import httpx

    from ahadiff.core.config import SecurityConfig

_SIGNAL_EVENT_TYPES = frozenset({"learn", "score", "verify", "improve"})
_BASELINE_STATUSES = frozenset(
    {"baseline", "keep", "targeted_verify", "keep_final", "non_ratcheted"}
)
_PENDING_WORKTREE_NOTE = "session has a pending improve worktree; resolve it before resuming"
_REPLAY_LEARN_TIMEOUT_SECONDS = 30 * 60
# Hard cap on bytes for any single mutated prompt produced by the improve LLM.
# 256 KiB is generous for hand-edited Markdown prompts but bounds runaway output.
_MAX_MUTATED_PROMPT_BYTES = 256 * 1024
_MAX_IMPROVE_METADATA_BYTES = 1024 * 1024
_MAX_IMPROVE_CLAIMS_BYTES = 10 * 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
log = logging.getLogger(__name__)
_ACTIVE_WORKTREE_CLEANUPS: dict[str, tuple[Path, Path]] = {}
_ACTIVE_WORKTREE_LOCK = threading.Lock()
_atexit_cleanup_registered = False
_IMPROVE_LOOP_LOCK = threading.Lock()
_SUBPROCESS_RUN = subprocess.run
_CHERRY_PICK_EXPECTED_PARENT: ContextVar[str | None] = ContextVar(
    "_CHERRY_PICK_EXPECTED_PARENT",
    default=None,
)


@dataclass(frozen=True)
class ImproveRoundResult:
    round_index: int
    session_id: str
    run_id: str
    target_prompt: str
    target_dimension: str
    status: str
    overall: float
    verdict: str
    cherry_pick_pending: bool = False
    phase25: bool = False


@dataclass(frozen=True)
class ImproveLoopResult:
    session_id: str
    anchor_run_id: str
    rounds_completed: int
    outcomes: tuple[ImproveRoundResult, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _CherryPickResult:
    pending_conflict: bool
    conflicted_files: tuple[str, ...] = ()
    new_head: str | None = None


@dataclass(frozen=True)
class _MutationResult:
    target_prompt: str
    content_hash: str


class _InterruptController:
    def __init__(self) -> None:
        self._requested = False
        self._count = 0
        self._lock = threading.Lock()
        self._previous_sigint = None
        self._previous_sigterm = None
        self._active_process: subprocess.Popen[str] | None = None

    def install(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        self._previous_sigint = signal.getsignal(signal.SIGINT)
        self._previous_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, self._handle_interrupt)
        # Windows does not receive external SIGTERM like POSIX; this mainly covers POSIX/tests.
        signal.signal(signal.SIGTERM, self._handle_interrupt)

    def restore(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        if self._previous_sigint is not None:
            signal.signal(signal.SIGINT, self._previous_sigint)
        if self._previous_sigterm is not None:
            signal.signal(signal.SIGTERM, self._previous_sigterm)

    @property
    def requested(self) -> bool:
        return self._requested

    def track_process(self, process: subprocess.Popen[str]) -> None:
        terminate_now = False
        with self._lock:
            self._active_process = process
            terminate_now = self._requested
        if terminate_now:
            _terminate_replay_process(process, force=False)

    def clear_process(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            if self._active_process is process:
                self._active_process = None

    def _handle_interrupt(self, signum: int, frame: object) -> None:
        del signum, frame
        process: subprocess.Popen[str] | None
        force = False
        with self._lock:
            self._count += 1
            self._requested = True
            process = self._active_process
            force = self._count > 1
        if process is not None:
            _terminate_replay_process(process, force=force)
        if force:
            raise SystemExit(1)


def run_improve_loop(
    *,
    repo_root: Path,
    state_dir: Path,
    db_path: Path,
    rounds: int,
    suite: str,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    resume_session_id: str | None = None,
    client: httpx.Client | None = None,
    request_timeout_seconds: int = 30,
    max_concurrent: int = 3,
    qps_limit: int = 3,
    retry_attempts: int = 3,
    privacy_mode: str = "strict_local",
    output_lang: str | None = None,
) -> ImproveLoopResult:
    if not _IMPROVE_LOOP_LOCK.acquire(blocking=False):
        raise StorageError("another ahadiff improve loop is already running in this process")
    try:
        return _run_improve_loop_unlocked(
            repo_root=repo_root,
            state_dir=state_dir,
            db_path=db_path,
            rounds=rounds,
            suite=suite,
            provider_config=provider_config,
            api_key=api_key,
            security_config=security_config,
            resume_session_id=resume_session_id,
            client=client,
            request_timeout_seconds=request_timeout_seconds,
            max_concurrent=max_concurrent,
            qps_limit=qps_limit,
            retry_attempts=retry_attempts,
            privacy_mode=privacy_mode,
            output_lang=output_lang,
        )
    finally:
        _IMPROVE_LOOP_LOCK.release()


def _run_improve_loop_unlocked(
    *,
    repo_root: Path,
    state_dir: Path,
    db_path: Path,
    rounds: int,
    suite: str,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    resume_session_id: str | None = None,
    client: httpx.Client | None = None,
    request_timeout_seconds: int = 30,
    max_concurrent: int = 3,
    qps_limit: int = 3,
    retry_attempts: int = 3,
    privacy_mode: str = "strict_local",
    output_lang: str | None = None,
) -> ImproveLoopResult:
    if suite != "local":
        raise InputError("improve currently supports only: --suite local")
    if privacy_mode == "redacted_remote":
        raise ConfigError(
            "improve does not support redacted_remote privacy mode; "
            "use strict_local or explicit_remote"
        )

    _reject_existing_pending_worktrees(state_dir, allowed_session_id=resume_session_id)
    expected_branch = _current_branch(repo_root)
    expected_head = _current_head(repo_root)

    warnings: list[str] = []
    if _prompts_are_dirty(repo_root):
        warnings.append(
            "prompts/ contains uncommitted changes; improve may conflict with local edits"
        )

    if resume_session_id is None:
        anchor_event = _select_anchor_event(state_dir=state_dir, db_path=db_path)
        session = create_improve_session(
            session_id=f"improve_{make_event_id()}",
            suite=suite,
            anchor_run_id=anchor_event.run_id,
        )
    else:
        session = load_improve_session(state_dir, resume_session_id)
        if session.suite != suite:
            raise InputError(
                f"resume session suite mismatch: expected {session.suite}, got {suite}"
            )
        if session.worktree_path is not None and Path(session.worktree_path).exists():
            if session.interrupted_round is not None and session.interrupted_stage is not None:
                prev_round = session.interrupted_round
                prev_stage = session.interrupted_stage
                removed = _cleanup_interrupted_worktree(
                    repo_root, Path(session.worktree_path), prev_stage
                )
                if removed:
                    session = update_improve_session(
                        session,
                        worktree_path=None,
                        interrupted_round=None,
                        interrupted_stage=None,
                    )
                else:
                    log.warning(
                        "failed to remove interrupted worktree at %s; "
                        "clearing session state to allow resume (manual cleanup may be needed)",
                        session.worktree_path,
                    )
                    session = update_improve_session(
                        session,
                        worktree_path=None,
                        interrupted_round=None,
                        interrupted_stage=None,
                    )
                save_improve_session(state_dir, session)
                log.info(
                    "cleaned up interrupted round %d (stage: %s) for resume",
                    prev_round,
                    prev_stage,
                )
            else:
                raise InputError(_PENDING_WORKTREE_NOTE)
        elif session.interrupted_round is not None:
            session = update_improve_session(
                session,
                interrupted_round=None,
                interrupted_stage=None,
            )
            save_improve_session(state_dir, session)
        anchor_event = _select_anchor_event_by_run_id(
            state_dir=state_dir,
            db_path=db_path,
            run_id=session.anchor_run_id,
        )

    save_improve_session(state_dir, session)
    anchor_run_path = state_dir / "runs" / session.anchor_run_id
    anchor_metadata = _load_run_metadata(anchor_run_path)
    source_ref = anchor_event.source_ref
    base_ref = anchor_event.base_ref
    outcomes: list[ImproveRoundResult] = []
    outcome_statuses = list(session.outcome_statuses)
    interrupt = _InterruptController()
    interrupt.install()
    try:
        for round_index in range(session.rounds_completed + 1, rounds + 1):
            latest_event = _select_latest_event_for_source(
                db_path=db_path,
                source_ref=source_ref,
                base_ref=base_ref,
                anchor_run_id=session.anchor_run_id,
            )
            baseline_event = _select_baseline_event_for_source(
                state_dir=state_dir,
                db_path=db_path,
                source_ref=source_ref,
                base_ref=base_ref,
                anchor_run_id=session.anchor_run_id,
            )
            if latest_event is None or baseline_event is None:
                raise InputError(
                    "improve requires at least one completed run with persisted results"
                )
            baseline_run_path = state_dir / "runs" / baseline_event.run_id
            if not baseline_run_path.exists():
                raise InputError(f"baseline run artifacts are missing: {baseline_event.run_id}")
            target_dimension = latest_event.weakest_dim
            target_prompt = mutable_prompt_for_dimension(target_dimension)
            worktree_path = _session_worktree_path(state_dir, session.session_id, round_index)
            session = update_improve_session(session, worktree_path=str(worktree_path))
            save_improve_session(state_dir, session)
            cherry_pick_pending = False
            _current_round_stage = "creating_worktree"
            try:
                _create_worktree(repo_root, worktree_path)
                _current_round_stage = "mutating"
                _mutate_prompt_in_worktree(
                    worktree_root=worktree_path,
                    target_prompt=target_prompt,
                    target_dimension=target_dimension,
                    baseline_event=baseline_event,
                    provider_config=provider_config,
                    api_key=api_key,
                    security_config=security_config,
                    privacy_mode=privacy_mode,
                    client=client,
                    request_timeout_seconds=request_timeout_seconds,
                    max_concurrent=max_concurrent,
                    qps_limit=qps_limit,
                    retry_attempts=retry_attempts,
                    output_lang=output_lang,
                )
                _current_round_stage = "committing"
                commit_sha = _commit_prompt_change(
                    worktree_root=worktree_path,
                    target_prompt=target_prompt,
                    round_index=round_index,
                    target_dimension=target_dimension,
                )
                _current_round_stage = "replaying"
                candidate_run_path = _run_replay_learn_subprocess(
                    worktree_root=worktree_path,
                    anchor_run_path=baseline_run_path,
                    metadata=anchor_metadata,
                    provider_config=provider_config,
                    api_key=api_key,
                    privacy_mode=privacy_mode,
                    output_lang=output_lang,
                    interrupt=interrupt,
                )
                _current_round_stage = "validating"
                _validate_candidate_run_matches_anchor(
                    candidate_run_path,
                    expected_source_ref=source_ref,
                    expected_base_ref=_metadata_base_ref(anchor_metadata),
                )
                _current_round_stage = "evaluating"
                candidate_report: ScoreReport = evaluate_run(candidate_run_path)
                _validate_candidate_report_matches_run(
                    candidate_report,
                    candidate_run_path=candidate_run_path,
                    expected_source_ref=source_ref,
                )
                candidate_prompt_version = compute_prompt_version(worktree_path)
                imported_run_path = _copy_candidate_run_to_state(
                    source_run_path=candidate_run_path,
                    state_dir=state_dir,
                )
                targeted_verify = verify_targeted_dimensions(
                    baseline=load_score_snapshot(
                        baseline_run_path,
                        expected_run_id=baseline_event.run_id,
                        expected_source_ref=baseline_event.source_ref,
                        expected_overall=baseline_event.overall,
                    ),
                    candidate=snapshot_from_report(candidate_report),
                    target_dimension=target_dimension,
                    failed_gates=tuple(candidate_report.hard_gates.failed_names()),
                )

                _current_round_stage = "persisting"
                note_payload: dict[str, object] = {
                    "anchor_run_id": session.anchor_run_id,
                    "improve_session_id": session.session_id,
                    "round": round_index,
                    "target_dimension": target_dimension,
                    "target_prompt": target_prompt,
                    "baseline_overall": round(baseline_event.overall, 2),
                }
                note_payload.update(targeted_verify.note_payload())
                status = "discard"
                if targeted_verify.passed:
                    _validate_cherry_pick_target(
                        repo_root,
                        expected_branch=expected_branch,
                        expected_head=expected_head,
                    )
                    cherry_pick = _cherry_pick_prompt_commit_for_expected_parent(
                        repo_root,
                        commit_sha,
                        expected_parent=expected_head,
                    )
                    if cherry_pick.pending_conflict:
                        cherry_pick_pending = True
                        note_payload["cherry_pick_pending"] = True
                        note_payload["worktree_path"] = str(worktree_path)
                        if cherry_pick.conflicted_files:
                            note_payload["conflicted_files"] = list(cherry_pick.conflicted_files)
                    status = "targeted_verify"
                    new_head = getattr(cherry_pick, "new_head", None)
                    if new_head is not None:
                        expected_head = new_head

                should_write_finalized = status != "discard" and not cherry_pick_pending
                append_result(
                    run_path=imported_run_path,
                    report=candidate_report,
                    status=status,
                    base_ref=base_ref,
                    event_type="improve",
                    note_payload=note_payload,
                    prompt_version_override=candidate_prompt_version,
                    write_finalized=should_write_finalized,
                )
                if status == "discard":
                    _remove_worktree(repo_root, worktree_path)
                    outcome_statuses.append(status)
                    session = update_improve_session(
                        session,
                        rounds_completed=round_index,
                        worktree_path=None,
                        last_status=status,
                        outcome_statuses=tuple(outcome_statuses),
                    )
                elif cherry_pick_pending:
                    _unregister_active_worktree(worktree_path)
                    outcome_statuses.append(status)
                    session = update_improve_session(
                        session,
                        rounds_completed=round_index,
                        worktree_path=str(worktree_path),
                        last_status=status,
                        outcome_statuses=tuple(outcome_statuses),
                    )
                else:
                    _remove_worktree(repo_root, worktree_path)
                    outcome_statuses.append(status)
                    session = update_improve_session(
                        session,
                        rounds_completed=round_index,
                        worktree_path=None,
                        last_status=status,
                        outcome_statuses=tuple(outcome_statuses),
                    )
                save_improve_session(state_dir, session)
                outcomes.append(
                    ImproveRoundResult(
                        round_index=round_index,
                        session_id=session.session_id,
                        run_id=imported_run_path.name,
                        target_prompt=target_prompt,
                        target_dimension=target_dimension,
                        status=status,
                        overall=candidate_report.overall,
                        verdict=candidate_report.verdict,
                        cherry_pick_pending=cherry_pick_pending,
                    )
                )
                phase25_decision = decide_phase25(
                    recent_statuses=tuple(outcome_statuses),
                    phase25_attempted=session.phase25_attempted,
                )
                if (
                    phase25_decision.should_run
                    and phase25_decision.trigger_reason is not None
                    and not cherry_pick_pending
                    and not interrupt.requested
                ):
                    session = update_improve_session(session, phase25_attempted=True)
                    save_improve_session(state_dir, session)
                    phase25_result, session = _run_phase25_rewrite(
                        repo_root=repo_root,
                        state_dir=state_dir,
                        session=session,
                        baseline_event=baseline_event,
                        anchor_base_ref=base_ref,
                        baseline_run_path=baseline_run_path,
                        anchor_metadata=anchor_metadata,
                        provider_config=provider_config,
                        api_key=api_key,
                        security_config=security_config,
                        privacy_mode=privacy_mode,
                        client=client,
                        request_timeout_seconds=request_timeout_seconds,
                        max_concurrent=max_concurrent,
                        qps_limit=qps_limit,
                        retry_attempts=retry_attempts,
                        trigger_reason=phase25_decision.trigger_reason,
                        target_dimension=target_dimension,
                        target_prompt=target_prompt,
                        output_lang=output_lang,
                        expected_branch=expected_branch,
                        expected_head=expected_head,
                        interrupt=interrupt,
                    )
                    save_improve_session(state_dir, session)
                    outcomes.append(phase25_result)
                    outcome_statuses.append(phase25_result.status)
                    session = update_improve_session(
                        session,
                        outcome_statuses=tuple(outcome_statuses),
                    )
                    save_improve_session(state_dir, session)
                    if phase25_result.cherry_pick_pending:
                        warnings.append(
                            "Phase 2.5 cherry-pick conflict left pending worktree; "
                            "resolve manually before resuming"
                        )
                        break
                    if phase25_result.status == "targeted_verify":
                        expected_head = _current_head(repo_root)
                if cherry_pick_pending:
                    warnings.append(
                        "cherry-pick conflict left pending worktree; "
                        "resolve manually before resuming"
                    )
                    break
                if interrupt.requested:
                    warnings.append(
                        f"interrupt requested after round {round_index}; "
                        "stopped before starting the next round"
                    )
                    break
            except BaseException as exc:
                if not cherry_pick_pending:
                    is_interrupt = interrupt.requested or isinstance(exc, KeyboardInterrupt)
                    if is_interrupt and worktree_path.exists():
                        session = update_improve_session(
                            session,
                            worktree_path=str(worktree_path),
                            interrupted_round=round_index,
                            interrupted_stage=_current_round_stage,
                        )
                    else:
                        removed = _remove_worktree(repo_root, worktree_path)
                        session = update_improve_session(
                            session,
                            worktree_path=None if removed else str(worktree_path),
                            interrupted_round=None,
                            interrupted_stage=None,
                        )
                    try:
                        save_improve_session(state_dir, session)
                    except Exception as save_exc:
                        log.warning(
                            "failed to save improve session cleanup state after exception: %s",
                            save_exc,
                        )
                raise
            finally:
                if session.worktree_path is None and worktree_path.exists():
                    _remove_worktree(repo_root, worktree_path)
    finally:
        interrupt.restore()

    return ImproveLoopResult(
        session_id=session.session_id,
        anchor_run_id=session.anchor_run_id,
        rounds_completed=session.rounds_completed,
        outcomes=tuple(outcomes),
        warnings=tuple(warnings),
    )


def _run_phase25_rewrite(
    *,
    repo_root: Path,
    state_dir: Path,
    session: ImproveSessionState,
    baseline_event: ResultEvent,
    anchor_base_ref: str | None = None,
    baseline_run_path: Path,
    anchor_metadata: dict[str, Any],
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    privacy_mode: str,
    client: httpx.Client | None,
    request_timeout_seconds: int,
    max_concurrent: int,
    qps_limit: int,
    retry_attempts: int,
    trigger_reason: str,
    target_dimension: str,
    target_prompt: str,
    output_lang: str | None,
    expected_branch: str | None = None,
    expected_head: str | None = None,
    interrupt: _InterruptController | None = None,
) -> tuple[ImproveRoundResult, ImproveSessionState]:
    if expected_head is None:
        expected_head = _current_head(repo_root)
    if expected_branch is None:
        expected_branch = _current_branch(repo_root)
    worktree_path = _session_phase25_worktree_path(state_dir, session.session_id)
    session = update_improve_session(session, worktree_path=str(worktree_path))
    save_improve_session(state_dir, session)
    cherry_pick_pending = False
    status = "discard"
    try:
        _create_worktree(repo_root, worktree_path)
        _mutate_prompt_in_worktree(
            worktree_root=worktree_path,
            target_prompt=target_prompt,
            target_dimension=target_dimension,
            baseline_event=baseline_event,
            provider_config=provider_config,
            api_key=api_key,
            security_config=security_config,
            privacy_mode=privacy_mode,
            client=client,
            request_timeout_seconds=request_timeout_seconds,
            max_concurrent=max_concurrent,
            qps_limit=qps_limit,
            retry_attempts=retry_attempts,
            output_lang=output_lang,
        )
        commit_sha = _commit_prompt_change(
            worktree_root=worktree_path,
            target_prompt=target_prompt,
            round_index=session.rounds_completed,
            target_dimension=f"phase25-{target_dimension}",
        )
        candidate_run_path = _run_replay_learn_subprocess(
            worktree_root=worktree_path,
            anchor_run_path=baseline_run_path,
            metadata=anchor_metadata,
            provider_config=provider_config,
            api_key=api_key,
            privacy_mode=privacy_mode,
            output_lang=output_lang,
            interrupt=interrupt,
        )
        _validate_candidate_run_matches_anchor(
            candidate_run_path,
            expected_source_ref=baseline_event.source_ref,
            expected_base_ref=_metadata_base_ref(anchor_metadata),
        )
        candidate_report: ScoreReport = evaluate_run(candidate_run_path)
        _validate_candidate_report_matches_run(
            candidate_report,
            candidate_run_path=candidate_run_path,
            expected_source_ref=baseline_event.source_ref,
        )
        candidate_prompt_version = compute_prompt_version(worktree_path)
        imported_run_path = _copy_candidate_run_to_state(
            source_run_path=candidate_run_path,
            state_dir=state_dir,
        )
        targeted_verify = verify_targeted_dimensions(
            baseline=load_score_snapshot(
                baseline_run_path,
                expected_run_id=baseline_event.run_id,
                expected_source_ref=baseline_event.source_ref,
                expected_overall=baseline_event.overall,
            ),
            candidate=snapshot_from_report(candidate_report),
            target_dimension=target_dimension,
            failed_gates=tuple(candidate_report.hard_gates.failed_names()),
        )
        note_payload = phase25_note_payload(
            session_id=session.session_id,
            round_index=session.rounds_completed,
            target_dimension=target_dimension,
            target_prompt=target_prompt,
            worktree_path=worktree_path,
            commit_sha=commit_sha,
            trigger_reason=trigger_reason,
            baseline_overall=baseline_event.overall,
        )
        note_payload["anchor_run_id"] = session.anchor_run_id
        final_payload = {**note_payload, **targeted_verify.note_payload()}
        if targeted_verify.passed:
            _validate_cherry_pick_target(
                repo_root,
                expected_branch=expected_branch,
                expected_head=expected_head,
            )
            cherry_pick = _cherry_pick_prompt_commit_for_expected_parent(
                repo_root,
                commit_sha,
                expected_parent=expected_head,
            )
            if cherry_pick.pending_conflict:
                cherry_pick_pending = True
                final_payload["cherry_pick_pending"] = True
                final_payload["worktree_path"] = str(worktree_path)
                if cherry_pick.conflicted_files:
                    final_payload["conflicted_files"] = list(cherry_pick.conflicted_files)
            status = "targeted_verify"

        should_write_finalized = status != "discard" and not cherry_pick_pending
        append_result(
            run_path=imported_run_path,
            report=candidate_report,
            status=status,
            base_ref=anchor_base_ref,
            event_type="improve",
            note_payload=final_payload,
            prompt_version_override=candidate_prompt_version,
            write_finalized=should_write_finalized,
        )
        if cherry_pick_pending:
            _unregister_active_worktree(worktree_path)
            session = update_improve_session(
                session,
                worktree_path=str(worktree_path),
                last_status=status,
            )
        else:
            _remove_worktree(repo_root, worktree_path)
            session = update_improve_session(
                session,
                worktree_path=None,
                last_status=status,
            )
        return (
            ImproveRoundResult(
                round_index=session.rounds_completed,
                session_id=session.session_id,
                run_id=imported_run_path.name,
                target_prompt=target_prompt,
                target_dimension=target_dimension,
                status=status,
                overall=candidate_report.overall,
                verdict=candidate_report.verdict,
                cherry_pick_pending=cherry_pick_pending,
                phase25=True,
            ),
            session,
        )
    finally:
        if not cherry_pick_pending and worktree_path.exists():
            _remove_worktree(repo_root, worktree_path)


def _select_anchor_event(*, state_dir: Path, db_path: Path) -> ResultEvent:
    for event in _sorted_events(load_result_events_from_db(db_path)):
        if event.event_type not in _SIGNAL_EVENT_TYPES:
            continue
        if not _is_pass_baseline_event(event):
            continue
        run_path = state_dir / "runs" / event.run_id
        if (run_path / "finalized.json").exists():
            return event
    raise InputError("improve requires an existing finalized run with persisted results")


def _select_anchor_event_by_run_id(*, state_dir: Path, db_path: Path, run_id: str) -> ResultEvent:
    for event in _sorted_events(load_result_events_from_db(db_path)):
        if event.run_id != run_id:
            continue
        if event.event_type not in _SIGNAL_EVENT_TYPES:
            continue
        if not _is_pass_baseline_event(event):
            continue
        if (state_dir / "runs" / event.run_id / "finalized.json").exists():
            return event
    raise InputError(f"improve anchor run is not finalized or persisted: {run_id}")


def _select_latest_event_for_source(
    *,
    db_path: Path,
    source_ref: str,
    base_ref: str | None,
    anchor_run_id: str,
) -> ResultEvent | None:
    for event in load_result_events_for_improve_chain(
        db_path,
        source_ref=source_ref,
        base_ref=base_ref,
        anchor_run_id=anchor_run_id,
    ):
        if event.event_type in _SIGNAL_EVENT_TYPES:
            return event
    return None


def _select_baseline_event_for_source(
    *,
    state_dir: Path,
    db_path: Path,
    source_ref: str,
    base_ref: str | None,
    anchor_run_id: str,
) -> ResultEvent | None:
    for event in load_result_events_for_improve_chain(
        db_path,
        source_ref=source_ref,
        base_ref=base_ref,
        anchor_run_id=anchor_run_id,
    ):
        if event.event_type not in _SIGNAL_EVENT_TYPES:
            continue
        if event.run_id != anchor_run_id:
            continue
        if _is_pass_baseline_event(event):
            if not (state_dir / "runs" / event.run_id / "finalized.json").exists():
                continue
            return event
    return None


def _is_pass_baseline_event(event: ResultEvent) -> bool:
    return event.status in _BASELINE_STATUSES and event.verdict == "PASS"


def _sorted_events(events: tuple[ResultEvent, ...]) -> list[ResultEvent]:
    return sorted(events, key=lambda item: (item.timestamp, item.event_id), reverse=True)


_LATE_INTERRUPT_STAGES = frozenset({"persisting", "cherry_picking"})


def _cleanup_interrupted_worktree(
    repo_root: Path,
    worktree_path: Path,
    interrupted_stage: str,
) -> bool:
    """Clean up a worktree left behind by an interrupted round.

    Returns True if the worktree was successfully removed.
    """
    if interrupted_stage in _LATE_INTERRUPT_STAGES:
        log.warning(
            "interrupted at stage '%s'; imported runs or result events "
            "may need manual inspection in .ahadiff/runs/",
            interrupted_stage,
        )
    log.info(
        "cleaning interrupted worktree (stage=%s): %s",
        interrupted_stage,
        worktree_path,
    )
    return _remove_worktree(repo_root, worktree_path)


def _reject_existing_pending_worktrees(
    state_dir: Path,
    *,
    allowed_session_id: str | None,
) -> None:
    session_dir = improve_session_dir(state_dir)
    allowed_interrupted_worktree: Path | None = None
    if session_dir.exists():
        _assert_directory_no_follow(session_dir)
        for session_file in sorted(session_dir.glob("*.json")):
            try:
                session = load_improve_session(state_dir, session_file.stem)
            except InputError:
                continue
            if session.session_id == allowed_session_id:
                if (
                    session.worktree_path is not None
                    and session.interrupted_round is not None
                    and session.interrupted_stage is not None
                    and Path(session.worktree_path).exists()
                ):
                    allowed_interrupted_worktree = Path(session.worktree_path).absolute()
                continue
            if session.worktree_path is not None and Path(session.worktree_path).exists():
                raise InputError(_PENDING_WORKTREE_NOTE)

    worktree_dir = session_dir / "wt"
    if not worktree_dir.exists():
        return
    _assert_directory_no_follow(worktree_dir)
    leftovers = [child for child in worktree_dir.iterdir() if child.exists() or child.is_symlink()]
    if allowed_interrupted_worktree is not None:
        leftovers = [
            child
            for child in leftovers
            if child.is_symlink() or child.absolute() != allowed_interrupted_worktree
        ]
    if leftovers:
        raise InputError(_PENDING_WORKTREE_NOTE)


def _current_branch(repo_root: Path) -> str | None:
    result = run_git(repo_root, "branch", "--show-current")
    branch = result.stdout.strip()
    return branch or None


def _current_head(repo_root: Path) -> str:
    result = run_git(repo_root, "rev-parse", "HEAD")
    return result.stdout.strip()


def _session_worktree_path(state_dir: Path, session_id: str, round_index: int) -> Path:
    validate_improve_session_id(session_id)
    worktree_id = sha256(session_id.encode("utf-8")).hexdigest()[:12]
    return improve_session_dir(state_dir) / "wt" / f"{worktree_id}-r{round_index}"


def _session_phase25_worktree_path(state_dir: Path, session_id: str) -> Path:
    validate_improve_session_id(session_id)
    worktree_id = sha256(session_id.encode("utf-8")).hexdigest()[:12]
    return improve_session_dir(state_dir) / "wt" / f"{worktree_id}-phase25"


def _create_worktree(repo_root: Path, worktree_path: Path) -> None:
    _prepare_worktree_target(worktree_path)
    _register_active_worktree(repo_root, worktree_path)
    try:
        run_git(repo_root, "worktree", "add", "--detach", str(worktree_path), "HEAD", timeout=600)
    except (InputError, OSError, subprocess.SubprocessError) as exc:
        _remove_worktree(repo_root, worktree_path)
        raise InputError(
            "failed to create detached git worktree; AhaDiff improve requires "
            "Git >= 2.18 for 'git worktree add --detach'. Upgrade Git and retry. "
            f"Detail: {exc}"
        ) from exc


def _remove_worktree(repo_root: Path, worktree_path: Path) -> bool:
    remove_result = run_git(
        repo_root,
        "worktree",
        "remove",
        "--force",
        str(worktree_path),
        check=False,
    )
    removed = True
    try:
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
        if worktree_path.exists():
            removed = False
    finally:
        if remove_result.returncode != 0:
            run_git(repo_root, "worktree", "prune", check=False)
        if removed:
            _unregister_active_worktree(worktree_path)
    return removed


def _prepare_worktree_target(worktree_path: Path) -> None:
    if ".." in worktree_path.parts:
        raise InputError("improve worktree path must not contain path traversal")
    if worktree_path.name in {"", ".", ".."}:
        raise InputError("invalid improve worktree path")
    _mkdir_no_symlink(worktree_path.parent)
    try:
        target_stat = worktree_path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(target_stat.st_mode):
        raise InputError("improve worktree path must not be a symlink")
    raise InputError("refusing to overwrite existing improve worktree path")


def _mkdir_no_symlink(path: Path) -> None:
    if path.exists():
        _assert_directory_no_follow(path)
        return
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    _assert_directory_no_follow(cursor)
    for directory in reversed(missing):
        with suppress(FileExistsError):
            directory.mkdir()
        _assert_directory_no_follow(directory)


def _assert_directory_no_follow(path: Path) -> None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError as exc:
        raise InputError(f"improve worktree parent directory is missing: {path}") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError("improve worktree parent directory must not be a symlink")
    if not stat.S_ISDIR(path_stat.st_mode):
        raise InputError("improve worktree parent path must be a directory")
    if sys.platform.startswith("win"):
        if _has_windows_reparse_point(path_stat):
            raise InputError(
                "improve worktree parent directory must not be a Windows reparse point or junction"
            )
        return
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError("improve worktree parent directory must not be a symlink") from exc
        raise
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISDIR(file_stat.st_mode):
            raise InputError("improve worktree parent path must be a directory")
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError("improve worktree parent changed during validation")
    finally:
        os.close(fd)


def _has_windows_reparse_point(path_stat: object) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _register_active_worktree(repo_root: Path, worktree_path: Path) -> None:
    global _atexit_cleanup_registered
    key = str(worktree_path)
    with _ACTIVE_WORKTREE_LOCK:
        _ACTIVE_WORKTREE_CLEANUPS[key] = (repo_root, worktree_path)
        if not _atexit_cleanup_registered:
            atexit.register(_cleanup_active_worktrees_at_exit)
            _atexit_cleanup_registered = True


def _unregister_active_worktree(worktree_path: Path) -> None:
    with _ACTIVE_WORKTREE_LOCK:
        _ACTIVE_WORKTREE_CLEANUPS.pop(str(worktree_path), None)


def _cleanup_active_worktrees_at_exit() -> None:
    with _ACTIVE_WORKTREE_LOCK:
        items = tuple(_ACTIVE_WORKTREE_CLEANUPS.values())
    for repo_root, worktree_path in items:
        try:
            _remove_worktree(repo_root, worktree_path)
        except Exception as exc:  # pragma: no cover - process-exit best effort
            log.warning("failed to remove improve worktree at exit %s: %s", worktree_path, exc)


def _prompts_are_dirty(repo_root: Path) -> bool:
    result = run_git(repo_root, "status", "--porcelain", "--", "prompts", "src/ahadiff/prompts")
    return bool(result.stdout.strip())


def _mutate_prompt_in_worktree(
    *,
    worktree_root: Path,
    target_prompt: str,
    target_dimension: str,
    baseline_event: ResultEvent,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    privacy_mode: str,
    client: httpx.Client | None,
    request_timeout_seconds: int,
    max_concurrent: int,
    qps_limit: int,
    retry_attempts: int,
    output_lang: str | None = None,
) -> _MutationResult:
    validate_mutable_prompt_name(target_prompt)
    repo_prompt_path = worktree_root / "prompts" / target_prompt
    package_prompt_path = worktree_root / "src" / "ahadiff" / "prompts" / target_prompt
    _assert_prompt_path_no_symlinks(worktree_root, repo_prompt_path)
    _assert_prompt_path_no_symlinks(worktree_root, package_prompt_path)
    current_prompt = _read_prompt_regular_no_follow(repo_prompt_path, target_prompt)
    _assert_prompt_regular_no_follow(package_prompt_path, target_prompt)
    improve_program = load_improve_program(worktree_root)
    payload_text = "\n\n".join(
        (
            improve_program.strip(),
            "## Objective\n"
            f"- weakest_dimension: {target_dimension}\n"
            f"- target_file: {target_prompt}\n"
            f"- baseline_overall: {baseline_event.overall:.2f}\n"
            f"- baseline_verdict: {baseline_event.verdict}\n"
            f"- baseline_status: {baseline_event.status}\n",
            "## Current prompt\n```markdown\n" + current_prompt.rstrip() + "\n```",
        )
    )
    prompt_fingerprint = sha256(
        (improve_program + "\n---\n" + target_prompt).encode("utf-8")
    ).hexdigest()[:12]
    provider = make_provider(
        provider_config,
        api_key=api_key,
        security_config=security_config,
        workspace_root=worktree_root,
        client=client,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        request_timeout_seconds=request_timeout_seconds,
        execution_origin="improve",
    )
    limits = resolve_model_limits(
        str(provider_config.provider_class),
        provider_config.model_name,
        provider_config,
    )
    model_max_candidates = [limits.max_output_tokens]
    if provider_config.max_output_tokens is not None and provider_config.max_output_tokens > 0:
        model_max_candidates.append(provider_config.max_output_tokens)
    try:
        response = provider.generate(
            ProviderRequest(
                prompt_name="improve.program",
                prompt_fingerprint=prompt_fingerprint,
                prompt_version=compute_prompt_version(worktree_root),
                eval_bundle_version=compute_runtime_eval_bundle_version(),
                model=provider_config.model_name,
                payload_text=payload_text,
                diff_content=current_prompt,
                source_ref=baseline_event.source_ref,
                output_lang=output_lang or "en",
                privacy_mode=cast("Any", privacy_mode),
                response_format="json",
                enforcement_mode="json_object",
                max_output_tokens=effective_output_cap(
                    requested_step_cap=6000,
                    llm_output_budget=None,
                    resolved_model_max_output=min(model_max_candidates),
                    default_step_cap=6000,
                ),
                thinking_level=provider_config.thinking_level,
            )
        )
    finally:
        provider.close()
    payload = _parse_json_object(response.content)
    target_file = payload.get("target_file")
    content = payload.get("content")
    if not isinstance(target_file, str) or not isinstance(content, str):
        raise InputError("improve response must contain target_file and content strings")
    validate_mutable_prompt_name(target_file)
    if target_file != target_prompt:
        raise InputError(
            f"improve response attempted to mutate {target_file!r}; expected {target_prompt!r}"
        )
    normalized_content, content_bytes = _normalize_mutated_prompt_content(content)
    if len(content_bytes) > _MAX_MUTATED_PROMPT_BYTES:
        raise InputError("improve response prompt content exceeds 262144 bytes")
    if normalized_content == current_prompt:
        raise InputError("improve response did not change the target prompt")
    _write_prompt_pair_atomic(repo_prompt_path, package_prompt_path, normalized_content)
    return _MutationResult(
        target_prompt=target_prompt,
        content_hash=sha256(content_bytes).hexdigest()[:12],
    )


def _read_prompt_regular_no_follow(path: Path, target_prompt: str) -> str:
    _assert_prompt_regular_no_follow(path, target_prompt)
    try:
        return _read_bounded(
            path,
            max_bytes=_MAX_MUTATED_PROMPT_BYTES,
            label=f"mutable prompt file {target_prompt}",
        )
    except UnicodeDecodeError as exc:
        raise InputError(f"mutable prompt file must be valid UTF-8: {target_prompt}") from exc


def _assert_prompt_regular_no_follow(path: Path, target_prompt: str) -> None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError as exc:
        raise InputError(f"mutable prompt file is missing from worktree: {target_prompt}") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError(f"mutable prompt file must not be a symlink: {target_prompt}")
    if bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
        msg = f"mutable prompt file must not be a Windows reparse point: {target_prompt}"
        raise InputError(msg)
    if not stat.S_ISREG(path_stat.st_mode):
        raise InputError(f"mutable prompt file must be a regular file: {target_prompt}")


def _assert_prompt_path_no_symlinks(worktree_root: Path, path: Path) -> None:
    try:
        relative_path = path.relative_to(worktree_root)
    except ValueError as exc:
        raise InputError("mutable prompt path must stay inside improve worktree") from exc
    current = worktree_root
    for part in relative_path.parts[:-1]:
        current = current / part
        try:
            path_stat = current.lstat()
        except FileNotFoundError as exc:
            raise InputError(f"mutable prompt parent path is missing: {current}") from exc
        if stat.S_ISLNK(path_stat.st_mode):
            raise InputError("mutable prompt parent path must not be a symlink")
        if bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
            raise InputError("mutable prompt parent path must not be a Windows reparse point")


def _normalize_mutated_prompt_content(content: str) -> tuple[str, bytes]:
    if "\x00" in content:
        raise InputError("improve response content must not contain null bytes")
    normalized_content = content.rstrip() + "\n"
    try:
        content_bytes = normalized_content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InputError("improve response content must be valid UTF-8") from exc
    return normalized_content, content_bytes


def _write_prompt_pair_atomic(first_path: Path, second_path: Path, content: str) -> None:
    _assert_prompt_regular_no_follow(first_path, first_path.name)
    _assert_prompt_regular_no_follow(second_path, second_path.name)
    first_temp = _temporary_sibling_path(first_path, suffix=".prompt.tmp")
    second_temp = _temporary_sibling_path(second_path, suffix=".prompt.tmp")
    temp_paths = (first_temp, second_temp)
    try:
        for temp_path in temp_paths:
            temp_path.write_text(content, encoding="utf-8")
        # These prompt copies live only in the detached improve worktree. If the
        # second replace fails after the first one succeeds, the exception
        # propagates to run_improve_loop/_run_phase25_rewrite, which removes the
        # disposable worktree unless a later cherry-pick conflict is pending.
        first_temp.replace(first_path)
        second_temp.replace(second_path)
    finally:
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)


def _temporary_sibling_path(target: Path, *, suffix: str) -> Path:
    fd, path = tempfile.mkstemp(prefix=f".{target.name}.", suffix=suffix, dir=target.parent)
    os.close(fd)
    return Path(path)


def _commit_prompt_change(
    *,
    worktree_root: Path,
    target_prompt: str,
    round_index: int,
    target_dimension: str,
) -> str:
    repo_relative_paths = [
        f"prompts/{target_prompt}",
        f"src/ahadiff/prompts/{target_prompt}",
    ]
    status = run_git(worktree_root, "status", "--porcelain", "--", *repo_relative_paths)
    if not status.stdout.strip():
        raise InputError(f"improve round {round_index} produced no prompt diff")
    run_git(worktree_root, "add", *repo_relative_paths)
    message = f"ahadiff improve round {round_index}: {target_dimension} via {target_prompt}"
    run_git(worktree_root, "commit", "-m", message)
    commit = run_git(worktree_root, "rev-parse", "HEAD")
    return commit.stdout.strip()


def _run_replay_learn_subprocess(
    *,
    worktree_root: Path,
    anchor_run_path: Path,
    metadata: dict[str, Any],
    provider_config: ProviderConfig,
    api_key: str | None,
    privacy_mode: str,
    output_lang: str | None = None,
    interrupt: _InterruptController | None = None,
) -> Path:
    replay_args = build_replay_learn_args(anchor_run_path=anchor_run_path, metadata=metadata)
    command = [
        sys.executable,
        "-m",
        "ahadiff",
        "learn",
        *replay_args,
        "--repo-root",
        str(worktree_root),
        "--provider-class",
        provider_config.provider_class,
        "--base-url",
        provider_config.base_url,
        "--model",
        provider_config.model_name,
        "--api-key-env",
        provider_config.api_key_env,
        "--privacy-mode",
        privacy_mode,
    ]
    if output_lang is not None:
        command.extend(("--lang", output_lang))
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if api_key is not None:
        env[provider_config.api_key_env] = api_key
    state_dir = worktree_root / ".ahadiff" / "runs"
    before_runs: set[str] = (
        {child.name for child in state_dir.iterdir() if child.is_dir()}
        if state_dir.exists()
        else set()
    )
    try:
        if interrupt is None or subprocess.run is not _SUBPROCESS_RUN:
            result = subprocess.run(
                command,
                cwd=worktree_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                env=env,
                timeout=_REPLAY_LEARN_TIMEOUT_SECONDS,
                **_detached_subprocess_kwargs(),
            )
        else:
            result = _run_replay_command_with_interrupt(
                command=command,
                worktree_root=worktree_root,
                env=env,
                interrupt=interrupt,
            )
    except subprocess.TimeoutExpired as exc:
        raise InputError(
            f"improve learn replay timed out after {_REPLAY_LEARN_TIMEOUT_SECONDS} seconds"
        ) from exc
    if result.returncode != 0:
        if interrupt is not None and interrupt.requested:
            raise InputError("improve learn replay interrupted")
        message = result.stderr.strip() or result.stdout.strip()
        raise InputError(message or "improve learn replay failed")
    if not state_dir.exists():
        raise InputError("improve learn replay produced no run artifacts")
    after_runs = [child for child in state_dir.iterdir() if child.is_dir()]
    new_runs = [child for child in after_runs if child.name not in before_runs]
    if len(new_runs) == 1:
        return new_runs[0]
    if new_runs:
        return max(new_runs, key=lambda item: item.stat().st_mtime_ns)
    raise InputError("improve learn replay produced no fresh run artifacts")


def _run_replay_command_with_interrupt(
    *,
    command: list[str],
    worktree_root: Path,
    env: dict[str, str],
    interrupt: _InterruptController,
) -> subprocess.CompletedProcess[str]:
    with subprocess.Popen(
        command,
        cwd=worktree_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **_detached_subprocess_kwargs(),
    ) as process:
        interrupt.track_process(process)
        try:
            try:
                stdout, stderr = process.communicate(timeout=_REPLAY_LEARN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                _terminate_replay_process(process, force=True)
                with suppress(subprocess.TimeoutExpired):
                    process.communicate(timeout=5)
                raise
        finally:
            interrupt.clear_process(process)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _terminate_replay_process(process: subprocess.Popen[str], *, force: bool) -> None:
    if process.poll() is not None:
        return
    if sys.platform.startswith("win"):
        with suppress(OSError):
            if force:
                process.kill()
            else:
                process.terminate()
        return

    signum = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        return
    except OSError:
        with suppress(OSError):
            if force:
                process.kill()
            else:
                process.terminate()


def _detached_subprocess_kwargs() -> dict[str, Any]:
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": creationflags}
    return {"start_new_session": True}


def _validate_candidate_run_matches_anchor(
    candidate_run_path: Path,
    *,
    expected_source_ref: str,
    expected_base_ref: str | None,
) -> None:
    metadata = _load_run_metadata(candidate_run_path)
    run_id = metadata.get("run_id")
    if run_id != candidate_run_path.name:
        raise InputError("candidate run metadata run_id does not match its directory")
    if metadata.get("source_ref") != expected_source_ref:
        raise InputError("candidate run source_ref does not match improve anchor")
    if (metadata.get("base_ref") or None) != (expected_base_ref or None):
        raise InputError("candidate run base_ref does not match improve anchor")
    _validate_claim_records_belong_to_run(
        candidate_run_path / "claims.jsonl", candidate_run_path.name
    )


def _metadata_base_ref(metadata: dict[str, Any]) -> str | None:
    raw_base_ref = metadata.get("base_ref")
    return raw_base_ref if isinstance(raw_base_ref, str) and raw_base_ref else None


def _validate_candidate_report_matches_run(
    report: ScoreReport,
    *,
    candidate_run_path: Path,
    expected_source_ref: str,
) -> None:
    if report.run_id != candidate_run_path.name:
        raise InputError("candidate score report run_id does not match its directory")
    if report.source_ref != expected_source_ref:
        raise InputError("candidate score report source_ref does not match improve anchor")


def _validate_claim_records_belong_to_run(path: Path, expected_run_id: str) -> None:
    if not path.exists():
        return
    claims_text = _read_bounded(
        path,
        max_bytes=_MAX_IMPROVE_CLAIMS_BYTES,
        label="candidate claims.jsonl",
    )
    for index, line in enumerate(claims_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = safe_json_loads(stripped)
        except ValueError as exc:
            raise InputError(f"invalid claims.jsonl line {index}: {path}") from exc
        if not isinstance(payload, dict):
            continue
        payload_map = cast("dict[str, object]", payload)
        if payload_map.get("run_id") != expected_run_id:
            raise InputError("candidate claims.jsonl run_id does not match candidate run")


def _copy_candidate_run_to_state(*, source_run_path: Path, state_dir: Path) -> Path:
    destination = state_dir / "runs" / source_run_path.name
    if destination.exists():
        raise StorageError(f"candidate run already exists in state dir: {destination.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f".{destination.name}.tmp")
    if temp_path.exists():
        shutil.rmtree(temp_path, ignore_errors=True)
    try:
        shutil.copytree(source_run_path, temp_path, symlinks=True)
        _validate_candidate_tree(temp_path)
        _safe_unlink(temp_path / "quiz" / "cards.jsonl", temp_path)
        _safe_unlink(temp_path / "finalized.json", temp_path)
        temp_path.replace(destination)
    except Exception:
        if temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)
        raise
    return destination


def _validate_candidate_tree(root: Path) -> None:
    root_resolved = root.resolve(strict=True)
    for path in root.rglob("*"):
        if path.is_symlink():
            raise InputError(f"candidate run artifact must not be a symlink: {path}")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise InputError(f"candidate run artifact cannot be resolved: {path}") from exc
        if not resolved.is_relative_to(root_resolved):
            raise InputError(f"candidate run artifact resolves outside staging root: {path}")


def _safe_unlink(path: Path, root: Path) -> None:
    if path.is_symlink():
        raise InputError(f"refusing to unlink symlinked candidate artifact: {path}")
    if not path.exists():
        return
    root_resolved = root.resolve(strict=True)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise InputError(f"candidate artifact cannot be resolved before unlink: {path}") from exc
    if not resolved.is_relative_to(root_resolved):
        raise InputError(f"candidate artifact resolves outside staging root: {path}")
    resolved.unlink()


def _verify_cherry_pick_parent(
    repo_root: Path,
    *,
    expected_parent: str,
) -> None:
    parent_result = run_git(repo_root, "rev-parse", "HEAD~1", check=False)
    actual_parent = parent_result.stdout.strip()
    if parent_result.returncode == 0 and actual_parent == expected_parent:
        return

    revert_result = run_git(repo_root, "revert", "--no-edit", "HEAD", check=False)
    if revert_result.returncode == 0:
        raise InputError(
            "cherry-pick parent mismatch detected; auto-reverted the improve commit. "
            "Another commit landed between validation and cherry-pick."
        )
    run_git(repo_root, "revert", "--abort", check=False)
    raise InputError(
        f"cherry-pick parent mismatch (expected {expected_parent[:12]}, "
        f"got {actual_parent[:12]}) and auto-revert failed. "
        "Run 'git revert HEAD --no-edit' to undo the improve commit."
    )


def _cherry_pick_prompt_commit_for_expected_parent(
    repo_root: Path,
    commit_sha: str,
    *,
    expected_parent: str,
) -> _CherryPickResult:
    token = _CHERRY_PICK_EXPECTED_PARENT.set(expected_parent)
    try:
        return _cherry_pick_prompt_commit(repo_root, commit_sha)
    finally:
        _CHERRY_PICK_EXPECTED_PARENT.reset(token)


def _cherry_pick_prompt_commit(
    repo_root: Path, commit_sha: str, *, expected_parent: str | None = None
) -> _CherryPickResult:
    result = run_git(repo_root, "cherry-pick", commit_sha, check=False)
    if result.returncode == 0:
        new_head = _current_head(repo_root)
        effective_expected_parent = expected_parent or _CHERRY_PICK_EXPECTED_PARENT.get()
        if effective_expected_parent is not None:
            _verify_cherry_pick_parent(
                repo_root,
                expected_parent=effective_expected_parent,
            )
        return _CherryPickResult(pending_conflict=False, new_head=new_head)
    conflict_result = run_git(
        repo_root,
        "diff",
        "--name-only",
        "--diff-filter=U",
        check=False,
    )
    conflicted_files = tuple(
        line.strip() for line in conflict_result.stdout.splitlines() if line.strip()
    )
    abort_result = run_git(repo_root, "cherry-pick", "--abort", check=False)
    if not conflicted_files:
        message = result.stderr.strip() or result.stdout.strip()
        raise InputError(message or "git cherry-pick failed without merge conflicts")
    if abort_result.returncode != 0:
        files_hint = ", ".join(conflicted_files[:5])
        raise InputError(
            f"git cherry-pick --abort failed after conflict (rc={abort_result.returncode}); "
            f"main repo may have CHERRY_PICK_HEAD — run 'git cherry-pick --abort' manually. "
            f"Conflicted files: {files_hint}. "
            f"Detail: {(abort_result.stderr or abort_result.stdout).strip()}"
        )
    return _CherryPickResult(
        pending_conflict=True,
        conflicted_files=conflicted_files,
    )


def _validate_cherry_pick_target(
    repo_root: Path,
    *,
    expected_branch: str | None,
    expected_head: str,
) -> None:
    current_branch = _current_branch(repo_root)
    if current_branch != expected_branch:
        expected = expected_branch or "detached HEAD"
        current = current_branch or "detached HEAD"
        raise InputError(
            f"refusing to cherry-pick improve commit onto unexpected branch: "
            f"expected {expected}, got {current}"
        )
    current_head = _current_head(repo_root)
    if current_head != expected_head:
        raise InputError("refusing to cherry-pick improve commit because target HEAD changed")


def _load_run_metadata(run_path: Path) -> dict[str, Any]:
    target = run_path / "metadata.json"
    if not target.exists():
        raise InputError(f"run metadata is missing: {run_path.name}")
    try:
        payload = safe_json_loads(
            _read_bounded(target, max_bytes=_MAX_IMPROVE_METADATA_BYTES, label="run metadata")
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise InputError(f"invalid JSON in run metadata: {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InputError(f"run metadata must be a JSON object: {target}")
    return cast("dict[str, Any]", payload)


def _read_bounded(path: Path, *, max_bytes: int, label: str) -> str:
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise InputError(f"{label} is unreadable") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError(f"{label} must not be a symlink")
    if _has_windows_reparse_point(path_stat):
        raise InputError(f"{label} must not be a Windows reparse point")
    if not stat.S_ISREG(path_stat.st_mode):
        raise InputError(f"{label} must be a regular file")
    if path_stat.st_size > max_bytes:
        raise InputError(f"{label} exceeds {max_bytes} bytes")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(f"{label} must not be a symlink") from exc
        raise InputError(f"{label} is unreadable") from exc
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise InputError(f"{label} must be a regular file")
        if _has_windows_reparse_point(file_stat):
            raise InputError(f"{label} must not be a Windows reparse point")
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError(f"{label} changed during validation")
        if file_stat.st_size > max_bytes:
            raise InputError(f"{label} exceeds {max_bytes} bytes")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            data = handle.read(max_bytes + 1)
    except InputError:
        raise
    except OSError as exc:
        raise InputError(f"{label} is unreadable") from exc
    finally:
        if fd != -1:
            os.close(fd)
    if len(data) > max_bytes:
        raise InputError(f"{label} exceeds {max_bytes} bytes")
    return data.decode("utf-8")


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        payload = safe_json_loads(text)
    except ValueError as exc:
        raise InputError("improve response must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise InputError("improve response must be a JSON object")
    return cast("dict[str, Any]", payload)


__all__ = [
    "ImproveLoopResult",
    "ImproveRoundResult",
    "run_improve_loop",
]
