from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.contracts import ProviderConfig, ResultEvent, compute_runtime_eval_bundle_version
from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.ids import make_event_id
from ahadiff.eval.evaluator import ScoreReport, evaluate_run
from ahadiff.eval.results import append_result, compute_prompt_version
from ahadiff.git.repo import run_git
from ahadiff.llm import ProviderRequest, make_provider
from ahadiff.review.database import load_result_events_from_db

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

    def install(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        self._previous_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handle_sigint)

    def restore(self) -> None:
        if self._previous_sigint is not None:
            signal.signal(signal.SIGINT, self._previous_sigint)

    @property
    def requested(self) -> bool:
        return self._requested

    def _handle_sigint(self, signum: int, frame: object) -> None:
        del signum, frame
        with self._lock:
            self._count += 1
            if self._count == 1:
                self._requested = True
                return
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
) -> ImproveLoopResult:
    if suite != "local":
        raise InputError("improve currently supports only: --suite local")

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
            raise InputError(_PENDING_WORKTREE_NOTE)

    save_improve_session(state_dir, session)
    anchor_run_path = state_dir / "runs" / session.anchor_run_id
    anchor_metadata = _load_run_metadata(anchor_run_path)
    source_ref = _require_string(anchor_metadata, "source_ref")
    outcomes: list[ImproveRoundResult] = []
    interrupt = _InterruptController()
    interrupt.install()
    try:
        for round_index in range(session.rounds_completed + 1, rounds + 1):
            latest_event = _select_latest_event_for_source(db_path=db_path, source_ref=source_ref)
            baseline_event = _select_baseline_event_for_source(
                state_dir=state_dir,
                db_path=db_path,
                source_ref=source_ref,
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
            _create_worktree(repo_root, worktree_path)
            try:
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
                )
                commit_sha = _commit_prompt_change(
                    worktree_root=worktree_path,
                    target_prompt=target_prompt,
                    round_index=round_index,
                    target_dimension=target_dimension,
                )
                candidate_run_path = _run_replay_learn_subprocess(
                    worktree_root=worktree_path,
                    anchor_run_path=baseline_run_path,
                    metadata=anchor_metadata,
                    provider_config=provider_config,
                    privacy_mode=privacy_mode,
                )
                candidate_report: ScoreReport = evaluate_run(candidate_run_path)
                candidate_prompt_version = compute_prompt_version(worktree_path)
                imported_run_path = _copy_candidate_run_to_state(
                    source_run_path=candidate_run_path,
                    state_dir=state_dir,
                )
                targeted_verify = verify_targeted_dimensions(
                    baseline=load_score_snapshot(baseline_run_path),
                    candidate=snapshot_from_report(candidate_report),
                    target_dimension=target_dimension,
                    failed_gates=tuple(candidate_report.hard_gates.failed_names()),
                )

                note_payload: dict[str, object] = {
                    "improve_session_id": session.session_id,
                    "round": round_index,
                    "target_dimension": target_dimension,
                    "target_prompt": target_prompt,
                    "baseline_overall": round(baseline_event.overall, 2),
                }
                note_payload.update(targeted_verify.note_payload())
                status = "discard"
                cherry_pick_pending = False
                if targeted_verify.passed:
                    cherry_pick = _cherry_pick_prompt_commit(repo_root, commit_sha)
                    if cherry_pick.pending_conflict:
                        cherry_pick_pending = True
                        note_payload["cherry_pick_pending"] = True
                        note_payload["worktree_path"] = str(worktree_path)
                        if cherry_pick.conflicted_files:
                            note_payload["conflicted_files"] = list(cherry_pick.conflicted_files)
                    status = "targeted_verify"

                should_write_finalized = status != "discard" and not cherry_pick_pending
                append_result(
                    run_path=imported_run_path,
                    report=candidate_report,
                    status=status,
                    base_ref=baseline_event.source_ref,
                    event_type="improve",
                    note_payload=note_payload,
                    prompt_version_override=candidate_prompt_version,
                    write_finalized=should_write_finalized,
                )
                if status == "discard":
                    _remove_worktree(repo_root, worktree_path)
                    session = update_improve_session(
                        session,
                        rounds_completed=round_index,
                        worktree_path=None,
                        last_status=status,
                    )
                elif cherry_pick_pending:
                    session = update_improve_session(
                        session,
                        rounds_completed=round_index,
                        worktree_path=str(worktree_path),
                        last_status=status,
                    )
                else:
                    _remove_worktree(repo_root, worktree_path)
                    session = update_improve_session(
                        session,
                        rounds_completed=round_index,
                        worktree_path=None,
                        last_status=status,
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
                    recent_statuses=tuple(item.status for item in outcomes),
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
                    )
                    save_improve_session(state_dir, session)
                    outcomes.append(phase25_result)
                    if phase25_result.cherry_pick_pending:
                        warnings.append(
                            "Phase 2.5 cherry-pick conflict left pending worktree; "
                            "resolve manually before resuming"
                        )
                        break
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
) -> tuple[ImproveRoundResult, ImproveSessionState]:
    worktree_path = _session_phase25_worktree_path(state_dir, session.session_id)
    session = update_improve_session(session, worktree_path=str(worktree_path))
    save_improve_session(state_dir, session)
    _create_worktree(repo_root, worktree_path)
    cherry_pick_pending = False
    status = "discard"
    try:
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
            privacy_mode=privacy_mode,
        )
        candidate_report: ScoreReport = evaluate_run(candidate_run_path)
        candidate_prompt_version = compute_prompt_version(worktree_path)
        imported_run_path = _copy_candidate_run_to_state(
            source_run_path=candidate_run_path,
            state_dir=state_dir,
        )
        targeted_verify = verify_targeted_dimensions(
            baseline=load_score_snapshot(baseline_run_path),
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
        append_result(
            run_path=imported_run_path,
            report=candidate_report,
            status="phase25_rewrite",
            base_ref=baseline_event.source_ref,
            event_type="improve",
            note_payload=note_payload,
            prompt_version_override=candidate_prompt_version,
            write_finalized=False,
        )
        note_payload.update(targeted_verify.note_payload())
        if targeted_verify.passed:
            cherry_pick = _cherry_pick_prompt_commit(repo_root, commit_sha)
            if cherry_pick.pending_conflict:
                cherry_pick_pending = True
                note_payload["cherry_pick_pending"] = True
                note_payload["worktree_path"] = str(worktree_path)
                if cherry_pick.conflicted_files:
                    note_payload["conflicted_files"] = list(cherry_pick.conflicted_files)
            status = "targeted_verify"

        should_write_finalized = status != "discard" and not cherry_pick_pending
        append_result(
            run_path=imported_run_path,
            report=candidate_report,
            status=status,
            base_ref=baseline_event.source_ref,
            event_type="improve",
            note_payload=note_payload,
            prompt_version_override=candidate_prompt_version,
            write_finalized=should_write_finalized,
        )
        if cherry_pick_pending:
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
        if event.status not in _BASELINE_STATUSES:
            continue
        run_path = state_dir / "runs" / event.run_id
        if (run_path / "finalized.json").exists():
            return event
    raise InputError("improve requires an existing finalized run with persisted results")


def _select_latest_event_for_source(*, db_path: Path, source_ref: str) -> ResultEvent | None:
    for event in _sorted_events(load_result_events_from_db(db_path)):
        if event.event_type in _SIGNAL_EVENT_TYPES and event.source_ref == source_ref:
            return event
    return None


def _select_baseline_event_for_source(
    *,
    state_dir: Path,
    db_path: Path,
    source_ref: str,
) -> ResultEvent | None:
    for event in _sorted_events(load_result_events_from_db(db_path)):
        if event.event_type not in _SIGNAL_EVENT_TYPES:
            continue
        if event.source_ref != source_ref:
            continue
        if event.status in _BASELINE_STATUSES:
            if not (state_dir / "runs" / event.run_id / "finalized.json").exists():
                continue
            return event
    return None


def _sorted_events(events: tuple[ResultEvent, ...]) -> list[ResultEvent]:
    return sorted(events, key=lambda item: (item.timestamp, item.event_id), reverse=True)


def _session_worktree_path(state_dir: Path, session_id: str, round_index: int) -> Path:
    validate_improve_session_id(session_id)
    worktree_id = sha256(session_id.encode("utf-8")).hexdigest()[:12]
    return improve_session_dir(state_dir) / "wt" / f"{worktree_id}-r{round_index}"


def _session_phase25_worktree_path(state_dir: Path, session_id: str) -> Path:
    validate_improve_session_id(session_id)
    worktree_id = sha256(session_id.encode("utf-8")).hexdigest()[:12]
    return improve_session_dir(state_dir) / "wt" / f"{worktree_id}-phase25"


def _create_worktree(repo_root: Path, worktree_path: Path) -> None:
    if worktree_path.exists():
        _remove_worktree(repo_root, worktree_path)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    run_git(repo_root, "worktree", "add", "--detach", str(worktree_path), "HEAD")


def _remove_worktree(repo_root: Path, worktree_path: Path) -> None:
    remove_result = run_git(
        repo_root,
        "worktree",
        "remove",
        "--force",
        str(worktree_path),
        check=False,
    )
    try:
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
    finally:
        if remove_result.returncode != 0:
            run_git(repo_root, "worktree", "prune", check=False)


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
) -> _MutationResult:
    validate_mutable_prompt_name(target_prompt)
    repo_prompt_path = worktree_root / "prompts" / target_prompt
    package_prompt_path = worktree_root / "src" / "ahadiff" / "prompts" / target_prompt
    if not repo_prompt_path.is_file() or not package_prompt_path.is_file():
        raise InputError(f"mutable prompt file is missing from worktree: {target_prompt}")
    current_prompt = repo_prompt_path.read_text(encoding="utf-8")
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
                privacy_mode=cast("Any", privacy_mode),
                response_format="json",
                max_output_tokens=6000,
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
    if "\x00" in content:
        raise InputError("improve response content must not contain null bytes")
    normalized_content = content.rstrip() + "\n"
    if normalized_content == current_prompt:
        raise InputError("improve response did not change the target prompt")
    _write_prompt_pair_atomic(repo_prompt_path, package_prompt_path, normalized_content)
    return _MutationResult(
        target_prompt=target_prompt,
        content_hash=sha256(normalized_content.encode("utf-8")).hexdigest()[:12],
    )


def _write_prompt_pair_atomic(first_path: Path, second_path: Path, content: str) -> None:
    first_temp = _temporary_sibling_path(first_path, suffix=".prompt.tmp")
    second_temp = _temporary_sibling_path(second_path, suffix=".prompt.tmp")
    temp_paths = (first_temp, second_temp)
    try:
        for temp_path in temp_paths:
            temp_path.write_text(content, encoding="utf-8")
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
    privacy_mode: str,
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
    state_dir = worktree_root / ".ahadiff" / "runs"
    before_runs: set[str] = (
        {child.name for child in state_dir.iterdir() if child.is_dir()}
        if state_dir.exists()
        else set()
    )
    try:
        result = subprocess.run(
            command,
            cwd=worktree_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_REPLAY_LEARN_TIMEOUT_SECONDS,
            **_detached_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise InputError(
            f"improve learn replay timed out after {_REPLAY_LEARN_TIMEOUT_SECONDS} seconds"
        ) from exc
    if result.returncode != 0:
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
    return max(after_runs, key=lambda item: item.stat().st_mtime_ns)


def _detached_subprocess_kwargs() -> dict[str, Any]:
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": creationflags}
    return {"start_new_session": True}


def _copy_candidate_run_to_state(*, source_run_path: Path, state_dir: Path) -> Path:
    destination = state_dir / "runs" / source_run_path.name
    if destination.exists():
        raise StorageError(f"candidate run already exists in state dir: {destination.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f".{destination.name}.tmp")
    if temp_path.exists():
        shutil.rmtree(temp_path, ignore_errors=True)
    shutil.copytree(source_run_path, temp_path)
    (temp_path / "quiz" / "cards.jsonl").unlink(missing_ok=True)
    (temp_path / "finalized.json").unlink(missing_ok=True)
    temp_path.replace(destination)
    return destination


def _cherry_pick_prompt_commit(repo_root: Path, commit_sha: str) -> _CherryPickResult:
    result = run_git(repo_root, "cherry-pick", commit_sha, check=False)
    if result.returncode == 0:
        return _CherryPickResult(pending_conflict=False)
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
    run_git(repo_root, "cherry-pick", "--abort", check=False)
    if not conflicted_files:
        message = result.stderr.strip() or result.stdout.strip()
        raise InputError(message or "git cherry-pick failed without merge conflicts")
    return _CherryPickResult(
        pending_conflict=True,
        conflicted_files=conflicted_files,
    )


def _load_run_metadata(run_path: Path) -> dict[str, Any]:
    target = run_path / "metadata.json"
    if not target.exists():
        raise InputError(f"run metadata is missing: {run_path.name}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InputError(f"run metadata must be a JSON object: {target}")
    return cast("dict[str, Any]", payload)


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError("improve response must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise InputError("improve response must be a JSON object")
    return cast("dict[str, Any]", payload)


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise InputError(f"run metadata field {key!r} must be a non-empty string")
    return value


__all__ = [
    "ImproveLoopResult",
    "ImproveRoundResult",
    "run_improve_loop",
]
