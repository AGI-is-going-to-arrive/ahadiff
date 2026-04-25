from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from ahadiff.contracts import ProviderConfig, ResultEvent
from ahadiff.core.config import SecurityConfig
from ahadiff.core.errors import InputError
from ahadiff.eval.deterministic import DimensionScore
from ahadiff.eval.evaluator import ScoreReport
from ahadiff.eval.gates import HardGateResult, HardGateSummary
from ahadiff.improve import loop as improve_loop_module
from ahadiff.improve.loop import run_improve_loop
from ahadiff.improve.program import (
    create_improve_session,
    load_improve_session,
    save_improve_session,
)
from ahadiff.improve.rewrite import decide_phase25
from ahadiff.review.database import (
    initialize_review_db,
    load_result_events_from_db,
    sync_result_event,
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_commit(path: Path, name: str, content: str, message: str) -> str:
    target = path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_prompt_files(repo_root: Path) -> None:
    prompt_files = {
        "lesson_generate.md": "lesson generate v1\n",
        "lesson_hint.md": "lesson hint v1\n",
        "lesson_compact.md": "lesson compact v1\n",
        "quiz_generate.md": "quiz generate v1\n",
        "claim_extract.md": "claim extract v1\n",
        "improve_program.md": "improve program v1\n",
    }
    for directory in (repo_root / "prompts", repo_root / "src" / "ahadiff" / "prompts"):
        directory.mkdir(parents=True, exist_ok=True)
        for name, content in prompt_files.items():
            (directory / name).write_text(content, encoding="utf-8")


def _write_run_fixture(
    run_path: Path,
    *,
    run_id: str,
    source_ref: str,
    base_ref: str,
    finalized: bool,
    score_overall: float = 70.0,
) -> None:
    run_path.mkdir(parents=True, exist_ok=True)
    (run_path / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "source_kind": "git_ref",
                "source_ref": source_ref,
                "base_ref": base_ref,
                "capability_level": 3,
                "degraded_flags": {},
                "source_detail": {"type": "range"},
                "privacy_mode": "strict_local",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
    (run_path / "score.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "source_ref": source_ref,
                "source_kind": "git_ref",
                "overall": score_overall,
                "verdict": "PASS",
                "weakest_dim": "learnability",
                "dimensions": _dimension_payload(score_overall),
                "hard_gates": {},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    quiz_dir = run_path / "quiz"
    quiz_dir.mkdir(exist_ok=True)
    (quiz_dir / "cards.jsonl").write_text(
        json.dumps({"card_id": "card-1", "concept": "retry"}) + "\n",
        encoding="utf-8",
    )
    if finalized:
        (run_path / "finalized.json").write_text("{}", encoding="utf-8")


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        provider_class="openai",
        model_name="gpt-5.4-mini",
        base_url="http://127.0.0.1:8000",
        api_key_env="AHADIFF_PROVIDER_API_KEY",
    )


def _baseline_event(
    *,
    run_id: str,
    source_ref: str,
    overall: float,
    weakest_dim: str,
) -> ResultEvent:
    return ResultEvent(
        event_id=f"018f0f52-91c0-7abc-8123-{run_id[-3:]:0>12}",
        run_id=run_id,
        event_type="learn",
        timestamp="2026-04-24T00:00:00Z",
        source_ref=source_ref,
        base_ref="base-ref",
        prompt_version="prompt123",
        eval_bundle_version="eval123",
        rubric_version="rubric-v1",
        overall=overall,
        verdict="PASS",
        status="baseline",
        weakest_dim=weakest_dim,
        note_json=None,
    )


def _score_report(*, run_id: str, source_ref: str, overall: float, weakest_dim: str) -> ScoreReport:
    return ScoreReport(
        run_id=run_id,
        source_ref=source_ref,
        source_kind="git_ref",
        capability_level=3,
        degraded_flags={},
        overall=overall,
        verdict="PASS",
        weakest_dim=weakest_dim,
        eval_bundle_version="eval123",
        rubric_version="rubric-v1",
        dimensions=tuple(
            DimensionScore(
                name=name,
                score=float(payload["score"]),
                max_score=float(payload["max_score"]),
                reason="fixture",
            )
            for name, payload in _dimension_payload(overall).items()
        ),
        hard_gates=HardGateSummary(results=()),
        notes=(),
    )


def _dimension_payload(overall: float) -> dict[str, dict[str, float | str]]:
    remaining = max(0.0, overall - 50.0)
    return {
        "accuracy": {"score": 18.0, "max_score": 20.0, "reason": "fixture"},
        "evidence": {"score": 17.0, "max_score": 18.0, "reason": "fixture"},
        "safety_privacy": {"score": 15.0, "max_score": 12.0, "reason": "fixture"},
        "learnability": {"score": remaining, "max_score": 12.0, "reason": "fixture"},
        "diff_coverage": {"score": 5.0, "max_score": 12.0, "reason": "fixture"},
        "quiz_transfer": {"score": 5.0, "max_score": 12.0, "reason": "fixture"},
        "spec_alignment": {"score": 5.0, "max_score": 14.0, "reason": "fixture"},
        "conciseness": {"score": 5.0, "max_score": 12.0, "reason": "fixture"},
    }


def test_decide_phase25_requires_two_discards_and_single_attempt() -> None:
    assert decide_phase25(recent_statuses=("discard",), phase25_attempted=False).should_run is False
    assert (
        decide_phase25(
            recent_statuses=("targeted_verify", "discard"),
            phase25_attempted=False,
        ).should_run
        is False
    )
    assert decide_phase25(
        recent_statuses=("discard", "discard"), phase25_attempted=False
    ).should_run
    assert (
        decide_phase25(
            recent_statuses=("discard", "discard"),
            phase25_attempted=True,
        ).should_run
        is False
    )


def test_phase25_triggers_after_two_discards_and_writes_targeted_verify(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    _write_prompt_files(repo_root)
    base_ref = _git_commit(repo_root, "tracked.txt", "base\n", "base")
    source_ref = _git_commit(repo_root, "tracked.txt", "head\n", "head")
    state_dir = repo_root / ".ahadiff"
    anchor_run_path = state_dir / "runs" / "run_anchor"
    _write_run_fixture(
        anchor_run_path,
        run_id="run_anchor",
        source_ref=source_ref,
        base_ref=base_ref,
        finalized=True,
        score_overall=70.0,
    )
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    sync_result_event(
        db_path,
        _baseline_event(
            run_id="run_anchor",
            source_ref=source_ref,
            overall=70.0,
            weakest_dim="learnability",
        ),
    )
    call_count = 0

    def fake_mutate_prompt_in_worktree(**kwargs: Any) -> None:
        nonlocal call_count
        call_count += 1
        worktree_root = Path(kwargs["worktree_root"])
        target_prompt = str(kwargs["target_prompt"])
        for relative in (
            worktree_root / "prompts" / target_prompt,
            worktree_root / "src" / "ahadiff" / "prompts" / target_prompt,
        ):
            relative.write_text(f"mutation {call_count}\n", encoding="utf-8")

    replay_runs = iter(("run_round1", "run_round2", "run_phase25"))

    def fake_run_replay_learn_subprocess(**kwargs: Any) -> Path:
        worktree_root = Path(kwargs["worktree_root"])
        run_id = next(replay_runs)
        run_path = worktree_root / ".ahadiff" / "runs" / run_id
        _write_run_fixture(
            run_path,
            run_id=run_id,
            source_ref=source_ref,
            base_ref=base_ref,
            finalized=True,
        )
        return run_path

    def fake_evaluate_run(path: Path) -> Any:
        overall_by_run = {
            "run_round1": 69.0,
            "run_round2": 68.0,
            "run_phase25": 76.0,
        }
        return _score_report(
            run_id=path.name,
            source_ref=source_ref,
            overall=overall_by_run[path.name],
            weakest_dim="learnability",
        )

    monkeypatch.setattr(
        improve_loop_module, "_mutate_prompt_in_worktree", fake_mutate_prompt_in_worktree
    )
    monkeypatch.setattr(
        improve_loop_module,
        "_run_replay_learn_subprocess",
        fake_run_replay_learn_subprocess,
    )
    monkeypatch.setattr(improve_loop_module, "evaluate_run", fake_evaluate_run)

    result = run_improve_loop(
        repo_root=repo_root,
        state_dir=state_dir,
        db_path=db_path,
        rounds=2,
        suite="local",
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
    )

    events = load_result_events_from_db(db_path)
    phase25_events = [event for event in events if event.status == "phase25_rewrite"]
    final_phase25 = [
        event
        for event in events
        if event.run_id == "run_phase25" and event.status == "targeted_verify"
    ]
    session = load_improve_session(state_dir, result.session_id)
    note_payload = json.loads(final_phase25[0].note_json or "{}")
    assert [item.status for item in result.outcomes] == [
        "discard",
        "discard",
        "targeted_verify",
    ]
    assert result.outcomes[-1].phase25 is True
    assert len(phase25_events) == 0
    assert len(final_phase25) == 1
    assert session.phase25_attempted is True
    assert note_payload["phase25"] is True
    assert str(note_payload["phase25_note"]).startswith("PHASE25:")
    assert (state_dir / "runs" / "run_phase25" / "finalized.json").exists()


def test_phase25_resume_merges_persisted_discard_history(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    _write_prompt_files(repo_root)
    base_ref = _git_commit(repo_root, "tracked.txt", "base\n", "base")
    source_ref = _git_commit(repo_root, "tracked.txt", "head\n", "head")
    state_dir = repo_root / ".ahadiff"
    anchor_run_path = state_dir / "runs" / "run_anchor"
    _write_run_fixture(
        anchor_run_path,
        run_id="run_anchor",
        source_ref=source_ref,
        base_ref=base_ref,
        finalized=True,
        score_overall=70.0,
    )
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    sync_result_event(
        db_path,
        _baseline_event(
            run_id="run_anchor",
            source_ref=source_ref,
            overall=70.0,
            weakest_dim="learnability",
        ),
    )
    call_count = 0

    def fake_mutate_prompt_in_worktree(**kwargs: Any) -> None:
        nonlocal call_count
        call_count += 1
        worktree_root = Path(kwargs["worktree_root"])
        target_prompt = str(kwargs["target_prompt"])
        for relative in (
            worktree_root / "prompts" / target_prompt,
            worktree_root / "src" / "ahadiff" / "prompts" / target_prompt,
        ):
            relative.write_text(f"resume mutation {call_count}\n", encoding="utf-8")

    replay_runs = iter(("run_round1", "run_round2", "run_phase25"))

    def fake_run_replay_learn_subprocess(**kwargs: Any) -> Path:
        worktree_root = Path(kwargs["worktree_root"])
        run_id = next(replay_runs)
        run_path = worktree_root / ".ahadiff" / "runs" / run_id
        _write_run_fixture(
            run_path,
            run_id=run_id,
            source_ref=source_ref,
            base_ref=base_ref,
            finalized=True,
        )
        return run_path

    def fake_evaluate_run(path: Path) -> Any:
        overall_by_run = {
            "run_round1": 69.0,
            "run_round2": 68.0,
            "run_phase25": 76.0,
        }
        return _score_report(
            run_id=path.name,
            source_ref=source_ref,
            overall=overall_by_run[path.name],
            weakest_dim="learnability",
        )

    monkeypatch.setattr(
        improve_loop_module, "_mutate_prompt_in_worktree", fake_mutate_prompt_in_worktree
    )
    monkeypatch.setattr(
        improve_loop_module,
        "_run_replay_learn_subprocess",
        fake_run_replay_learn_subprocess,
    )
    monkeypatch.setattr(improve_loop_module, "evaluate_run", fake_evaluate_run)

    first = run_improve_loop(
        repo_root=repo_root,
        state_dir=state_dir,
        db_path=db_path,
        rounds=1,
        suite="local",
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
    )
    second = run_improve_loop(
        repo_root=repo_root,
        state_dir=state_dir,
        db_path=db_path,
        rounds=2,
        suite="local",
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
        resume_session_id=first.session_id,
    )

    session = load_improve_session(state_dir, first.session_id)
    assert [item.status for item in first.outcomes] == ["discard"]
    assert [item.status for item in second.outcomes] == ["discard", "targeted_verify"]
    assert second.outcomes[-1].phase25 is True
    assert session.phase25_attempted is True
    assert session.outcome_statuses == ("discard", "discard", "targeted_verify")
    assert (state_dir / "runs" / "run_phase25" / "finalized.json").exists()


def test_phase25_cleans_partial_worktree_when_create_fails(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    _write_prompt_files(repo_root)
    base_ref = _git_commit(repo_root, "tracked.txt", "base\n", "base")
    source_ref = _git_commit(repo_root, "tracked.txt", "head\n", "head")
    state_dir = repo_root / ".ahadiff"
    anchor_run_path = state_dir / "runs" / "run_anchor"
    _write_run_fixture(
        anchor_run_path,
        run_id="run_anchor",
        source_ref=source_ref,
        base_ref=base_ref,
        finalized=True,
    )
    session = create_improve_session(
        session_id="improve_phase25_cleanup",
        suite="local",
        anchor_run_id="run_anchor",
    )
    save_improve_session(state_dir, session)
    expected_worktree = cast("Any", improve_loop_module)._session_phase25_worktree_path(
        state_dir,
        session.session_id,
    )

    def fake_create_worktree(repo_root: Path, worktree_path: Path) -> None:
        del repo_root
        worktree_path.mkdir(parents=True)
        raise InputError("phase25 create failed")

    monkeypatch.setattr(improve_loop_module, "_create_worktree", fake_create_worktree)

    with pytest.raises(InputError, match="phase25 create failed"):
        cast("Any", improve_loop_module)._run_phase25_rewrite(
            repo_root=repo_root,
            state_dir=state_dir,
            session=session,
            baseline_event=_baseline_event(
                run_id="run_anchor",
                source_ref=source_ref,
                overall=70.0,
                weakest_dim="learnability",
            ),
            baseline_run_path=anchor_run_path,
            anchor_metadata=json.loads(
                (anchor_run_path / "metadata.json").read_text(encoding="utf-8")
            ),
            provider_config=_provider_config(),
            api_key=None,
            security_config=SecurityConfig(),
            privacy_mode="strict_local",
            client=None,
            request_timeout_seconds=30,
            max_concurrent=3,
            qps_limit=3,
            retry_attempts=3,
            trigger_reason="consecutive_discard_count=2",
            target_dimension="learnability",
            target_prompt="lesson_generate.md",
            output_lang=None,
        )

    assert not expected_worktree.exists()


def test_targeted_verification_hard_gate_failure_discards_without_cherry_pick(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    _write_prompt_files(repo_root)
    base_ref = _git_commit(repo_root, "tracked.txt", "base\n", "base")
    source_ref = _git_commit(repo_root, "tracked.txt", "head\n", "head")
    state_dir = repo_root / ".ahadiff"
    anchor_run_path = state_dir / "runs" / "run_anchor"
    _write_run_fixture(
        anchor_run_path,
        run_id="run_anchor",
        source_ref=source_ref,
        base_ref=base_ref,
        finalized=True,
    )
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    sync_result_event(
        db_path,
        _baseline_event(
            run_id="run_anchor",
            source_ref=source_ref,
            overall=70.0,
            weakest_dim="learnability",
        ),
    )

    def fake_mutate_prompt_in_worktree(**kwargs: Any) -> None:
        worktree_root = Path(kwargs["worktree_root"])
        target_prompt = str(kwargs["target_prompt"])
        for relative in (
            worktree_root / "prompts" / target_prompt,
            worktree_root / "src" / "ahadiff" / "prompts" / target_prompt,
        ):
            relative.write_text("mutation hard gate\n", encoding="utf-8")

    def fake_run_replay_learn_subprocess(**kwargs: Any) -> Path:
        worktree_root = Path(kwargs["worktree_root"])
        run_path = worktree_root / ".ahadiff" / "runs" / "run_failed_gate"
        _write_run_fixture(
            run_path,
            run_id="run_failed_gate",
            source_ref=source_ref,
            base_ref=base_ref,
            finalized=True,
        )
        return run_path

    def fake_evaluate_run(path: Path) -> Any:
        report = _score_report(
            run_id=path.name,
            source_ref=source_ref,
            overall=82.0,
            weakest_dim="learnability",
        )
        return report.__class__(
            run_id=report.run_id,
            source_ref=report.source_ref,
            source_kind=report.source_kind,
            capability_level=report.capability_level,
            degraded_flags=report.degraded_flags,
            overall=report.overall,
            verdict=report.verdict,
            weakest_dim=report.weakest_dim,
            eval_bundle_version=report.eval_bundle_version,
            rubric_version=report.rubric_version,
            dimensions=report.dimensions,
            hard_gates=HardGateSummary(
                results=(HardGateResult(name="secret_leak", passed=False, detail="bad"),)
            ),
            notes=report.notes,
        )

    def fail_cherry_pick(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("hard gate failure must not cherry-pick")

    monkeypatch.setattr(
        improve_loop_module, "_mutate_prompt_in_worktree", fake_mutate_prompt_in_worktree
    )
    monkeypatch.setattr(
        improve_loop_module,
        "_run_replay_learn_subprocess",
        fake_run_replay_learn_subprocess,
    )
    monkeypatch.setattr(improve_loop_module, "evaluate_run", fake_evaluate_run)
    monkeypatch.setattr(improve_loop_module, "_cherry_pick_prompt_commit", fail_cherry_pick)

    result = run_improve_loop(
        repo_root=repo_root,
        state_dir=state_dir,
        db_path=db_path,
        rounds=1,
        suite="local",
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
    )

    events = load_result_events_from_db(db_path)
    failed_event = next(event for event in events if event.run_id == "run_failed_gate")
    note_payload = json.loads(failed_event.note_json or "{}")
    assert result.outcomes[0].status == "discard"
    assert failed_event.status == "discard"
    assert note_payload["targeted_reason"] == "hard_gates_failed"
    assert note_payload["targeted_failed_gates"] == ["secret_leak"]
