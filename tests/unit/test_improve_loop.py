from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any, cast

import pytest

from ahadiff.contracts import ProviderConfig, ResultEvent
from ahadiff.core.config import SecurityConfig
from ahadiff.core.errors import ConfigError, InputError
from ahadiff.eval.deterministic import DimensionScore
from ahadiff.eval.evaluator import ScoreReport
from ahadiff.eval.gates import HardGateSummary
from ahadiff.eval.results import finalized_marker_path
from ahadiff.improve import loop as improve_loop_module
from ahadiff.improve.loop import run_improve_loop
from ahadiff.improve.program import (
    ImproveSessionState,
    build_replay_learn_args,
    create_improve_session,
    improve_session_file,
    load_improve_program,
    load_improve_session,
    mutable_prompt_names,
    save_improve_session,
    update_improve_session,
    validate_mutable_prompt_name,
)
from ahadiff.llm import ProviderRequest, ProviderResponse
from ahadiff.review.database import (
    initialize_review_db,
    load_result_events_from_db,
    sync_result_event,
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _git_commit(path: Path, name: str, content: str, message: str) -> str:
    target = path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
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
    base_ref: str = "base-ref",
    overall: float,
    weakest_dim: str,
    timestamp: str = "2026-04-24T00:00:00Z",
    event_id: str | None = None,
) -> ResultEvent:
    return ResultEvent(
        event_id=event_id or f"018f0f52-91c0-7abc-8123-{run_id[-3:]:0>12}",
        run_id=run_id,
        event_type="learn",
        timestamp=timestamp,
        source_ref=source_ref,
        base_ref=base_ref,
        prompt_version="prompt123",
        eval_bundle_version="eval123",
        rubric_version="rubric-v1",
        overall=overall,
        verdict="PASS",
        status="baseline",
        weakest_dim=weakest_dim,
        note_json=None,
    )


def _prepare_improve_repo(tmp_path: Path) -> tuple[Path, Path, Path, str, str]:
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
            base_ref=base_ref,
            overall=70.0,
            weakest_dim="learnability",
        ),
    )
    return repo_root, state_dir, db_path, base_ref, source_ref


def _load_single_improve_session(state_dir: Path) -> ImproveSessionState:
    session_files = sorted((state_dir / "improve").glob("improve_*.json"))
    assert len(session_files) == 1
    return load_improve_session(state_dir, session_files[0].stem)


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
    learnability = max(0.0, min(14.0, overall - 60.0))
    return {
        "accuracy": {"score": 18.0, "max_score": 20.0, "reason": "fixture"},
        "evidence": {"score": 17.0, "max_score": 18.0, "reason": "fixture"},
        "safety_privacy": {"score": 6.0, "max_score": 6.0, "reason": "fixture"},
        "learnability": {"score": learnability, "max_score": 14.0, "reason": "fixture"},
        "diff_coverage": {"score": 10.0, "max_score": 14.0, "reason": "fixture"},
        "quiz_transfer": {"score": 7.0, "max_score": 10.0, "reason": "fixture"},
        "spec_alignment": {"score": 8.0, "max_score": 10.0, "reason": "fixture"},
        "conciseness": {"score": 5.0, "max_score": 8.0, "reason": "fixture"},
    }


def test_improve_rejects_redacted_remote(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    state_dir = repo_root / ".ahadiff"
    with pytest.raises(ConfigError, match="redacted_remote"):
        run_improve_loop(
            repo_root=repo_root,
            state_dir=state_dir,
            db_path=state_dir / "review.sqlite",
            rounds=1,
            suite="local",
            provider_config=_provider_config(),
            api_key=None,
            security_config=SecurityConfig(),
            privacy_mode="redacted_remote",
        )


def test_build_replay_learn_args_prefers_git_range(tmp_path: Path) -> None:
    run_path = tmp_path / "run"
    _write_run_fixture(
        run_path,
        run_id="run_anchor",
        source_ref="head-ref",
        base_ref="base-ref",
        finalized=False,
    )

    args = build_replay_learn_args(
        anchor_run_path=run_path,
        metadata=json.loads((run_path / "metadata.json").read_text(encoding="utf-8")),
    )

    assert args == ["base-ref..head-ref"]


def test_build_replay_learn_args_replays_volatile_inputs_from_saved_patch(tmp_path: Path) -> None:
    run_path = tmp_path / "run"
    _write_run_fixture(
        run_path,
        run_id="run_anchor",
        source_ref="sha256:staged",
        base_ref="",
        finalized=False,
    )
    metadata = json.loads((run_path / "metadata.json").read_text(encoding="utf-8"))
    metadata["source_kind"] = "git_staged"
    metadata["base_ref"] = None

    args = build_replay_learn_args(anchor_run_path=run_path, metadata=metadata)

    assert args == ["--patch", str(run_path / "patch.diff")]


def test_improve_program_prompt_parity() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    repo_prompt = load_improve_program(repo_root)
    package_prompt = (repo_root / "src" / "ahadiff" / "prompts" / "improve_program.md").read_text(
        encoding="utf-8"
    )
    assert repo_prompt == package_prompt


def test_mutable_prompt_contract_allows_lesson_hint_and_blocks_immutable_program() -> None:
    assert mutable_prompt_names() == (
        "claim_extract.md",
        "lesson_generate.md",
        "lesson_hint.md",
        "lesson_compact.md",
        "quiz_generate.md",
    )
    validate_mutable_prompt_name("lesson_hint.md")

    with pytest.raises(InputError, match="improve may modify only mutable prompts"):
        validate_mutable_prompt_name("improve_program.md")

    with pytest.raises(InputError, match="improve may modify only mutable prompts"):
        validate_mutable_prompt_name("../lesson_hint.md")


def test_improve_session_file_rejects_path_traversal_session_id(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"

    for session_id in ("../x", "..\\x", "a/b", "/tmp/x", "C:\\tmp\\x", "..", ".hidden"):
        with pytest.raises(InputError, match="invalid improve session id"):
            improve_session_file(state_dir, session_id)

    safe_path = improve_session_file(state_dir, "improve_018f0f52-91c0-7abc-8123-safe")
    assert safe_path.parent == state_dir / "improve"

    safe_path.parent.mkdir(parents=True)
    safe_path.write_text(
        json.dumps(
            {
                "session_id": "../escape",
                "suite": "local",
                "anchor_run_id": "run_anchor",
                "phase25_attempted": False,
                "rounds_completed": 0,
                "worktree_path": None,
                "created_at": "2026-04-24T00:00:00Z",
                "updated_at": "2026-04-24T00:00:00Z",
                "last_status": None,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(InputError, match="invalid improve session id"):
        load_improve_session(state_dir, "improve_018f0f52-91c0-7abc-8123-safe")


def test_session_worktree_path_uses_short_stable_directory(tmp_path: Path) -> None:
    session_id = "improve_018f0f52-91c0-7abc-8123-0123456789ab"

    worktree_path = cast("Any", improve_loop_module)._session_worktree_path(
        tmp_path / ".ahadiff",
        session_id,
        3,
    )

    assert worktree_path.parent.name == "wt"
    assert worktree_path.name.endswith("-r3")
    assert session_id not in str(worktree_path)


def test_interrupt_controller_installs_and_restores_sigterm(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[int, Any]] = []
    previous: dict[int, object] = {
        int(signal.SIGINT): object(),
        int(signal.SIGTERM): object(),
    }

    def fake_getsignal(signum: int) -> Any:
        return previous[signum]

    def fake_signal(signum: int, handler: Any) -> Any:
        calls.append((signum, handler))
        return previous[signum]

    monkeypatch.setattr(improve_loop_module.signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(improve_loop_module.signal, "signal", fake_signal)

    controller = cast("Any", improve_loop_module)._InterruptController()
    controller.install()
    controller.restore()

    assert calls[0][0] == signal.SIGINT
    assert calls[1][0] == signal.SIGTERM
    assert calls[2] == (signal.SIGINT, previous[int(signal.SIGINT)])
    assert calls[3] == (signal.SIGTERM, previous[int(signal.SIGTERM)])


def test_interrupt_controller_restore_is_noop_off_main_thread(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[int, Any]] = []
    errors: list[BaseException] = []

    def fake_signal(signum: int, handler: Any) -> None:
        calls.append((signum, handler))
        raise AssertionError("restore must not call signal.signal off the main thread")

    monkeypatch.setattr(improve_loop_module.signal, "signal", fake_signal)

    controller = cast("Any", improve_loop_module)._InterruptController()
    controller._previous_sigint = object()
    controller._previous_sigterm = object()

    def restore() -> None:
        try:
            controller.restore()
        except BaseException as exc:  # pragma: no cover - asserted via errors list
            errors.append(exc)

    worker = threading.Thread(target=restore)
    worker.start()
    worker.join()

    assert errors == []
    assert calls == []


def test_run_replay_learn_subprocess_timeout_is_bounded_and_reported(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    run_path = tmp_path / "anchor"
    _write_run_fixture(
        run_path,
        run_id="run_anchor",
        source_ref="head-ref",
        base_ref="base-ref",
        finalized=False,
    )

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del args
        timeout = kwargs.get("timeout")
        assert isinstance(timeout, int)
        assert timeout > 0
        raise subprocess.TimeoutExpired(cmd="ahadiff learn", timeout=timeout)

    monkeypatch.setattr(improve_loop_module.subprocess, "run", fake_run)

    with pytest.raises(InputError, match="timed out"):
        cast("Any", improve_loop_module)._run_replay_learn_subprocess(
            worktree_root=tmp_path,
            anchor_run_path=run_path,
            metadata=json.loads((run_path / "metadata.json").read_text(encoding="utf-8")),
            provider_config=_provider_config(),
            api_key=None,
            privacy_mode="strict_local",
        )


def test_run_improve_loop_propagates_interactive_api_key_to_replay(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    run_path = tmp_path / "anchor"
    _write_run_fixture(
        run_path,
        run_id="run_anchor",
        source_ref="head-ref",
        base_ref="base-ref",
        finalized=False,
    )
    captured_env: dict[str, str] = {}

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del args
        env = kwargs.get("env")
        assert isinstance(env, dict)
        captured_env.update(cast("dict[str, str]", env))
        _write_run_fixture(
            tmp_path / ".ahadiff" / "runs" / "run_replay",
            run_id="run_replay",
            source_ref="head-ref",
            base_ref="base-ref",
            finalized=True,
        )
        return subprocess.CompletedProcess(["ahadiff", "learn"], 0, stdout="", stderr="")

    monkeypatch.setattr(improve_loop_module.subprocess, "run", fake_run)

    replay_path = cast("Any", improve_loop_module)._run_replay_learn_subprocess(
        worktree_root=tmp_path,
        anchor_run_path=run_path,
        metadata=json.loads((run_path / "metadata.json").read_text(encoding="utf-8")),
        provider_config=_provider_config(),
        api_key="interactive-secret",
        privacy_mode="explicit_remote",
    )

    assert replay_path.name == "run_replay"
    assert captured_env["AHADIFF_PROVIDER_API_KEY"] == "interactive-secret"
    assert captured_env["PYTHONUTF8"] == "1"


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires elevated Windows privileges")
def test_copy_candidate_run_rejects_symlink_before_unlinking_artifacts(tmp_path: Path) -> None:
    source_run_path = tmp_path / "worktree" / ".ahadiff" / "runs" / "run_candidate"
    source_run_path.mkdir(parents=True)
    (source_run_path / "metadata.json").write_text("{}\n", encoding="utf-8")
    (source_run_path / "patch.diff").write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_cards = outside_dir / "cards.jsonl"
    outside_cards.write_text('{"card_id":"outside"}\n', encoding="utf-8")
    (source_run_path / "quiz").symlink_to(outside_dir, target_is_directory=True)
    (source_run_path / "finalized.json").write_text("{}\n", encoding="utf-8")
    state_dir = tmp_path / ".ahadiff"

    with pytest.raises(InputError, match="symlink"):
        cast("Any", improve_loop_module)._copy_candidate_run_to_state(
            source_run_path=source_run_path,
            state_dir=state_dir,
        )

    assert outside_cards.read_text(encoding="utf-8") == '{"card_id":"outside"}\n'
    assert not (state_dir / "runs" / "run_candidate").exists()


def test_improve_baseline_selection_is_bound_to_source_base_and_anchor(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    for run_id in ("run_101", "run_202"):
        run_path = state_dir / "runs" / run_id
        run_path.mkdir(parents=True)
        (run_path / "finalized.json").write_text("{}\n", encoding="utf-8")
    sync_result_event(
        db_path,
        _baseline_event(
            run_id="run_101",
            source_ref="shared-head",
            base_ref="base-a",
            overall=70.0,
            weakest_dim="learnability",
            timestamp="2026-04-24T00:00:01Z",
            event_id="018f0f52-91c0-7abc-8123-000000000101",
        ),
    )
    sync_result_event(
        db_path,
        _baseline_event(
            run_id="run_202",
            source_ref="shared-head",
            base_ref="base-b",
            overall=91.0,
            weakest_dim="accuracy",
            timestamp="2026-04-24T00:00:02Z",
            event_id="018f0f52-91c0-7abc-8123-000000000202",
        ),
    )
    sync_result_event(
        db_path,
        _baseline_event(
            run_id="run_303",
            source_ref="shared-head",
            base_ref="base-a",
            overall=76.0,
            weakest_dim="evidence",
            timestamp="2026-04-24T00:00:03Z",
            event_id="018f0f52-91c0-7abc-8123-000000000303",
        ).model_copy(
            update={
                "event_type": "improve",
                "status": "targeted_verify",
                "note_json": json.dumps({"anchor_run_id": "run_101"}),
            }
        ),
    )

    latest = cast("Any", improve_loop_module)._select_latest_event_for_source(
        db_path=db_path,
        source_ref="shared-head",
        base_ref="base-a",
        anchor_run_id="run_101",
    )
    baseline = cast("Any", improve_loop_module)._select_baseline_event_for_source(
        state_dir=state_dir,
        db_path=db_path,
        source_ref="shared-head",
        base_ref="base-a",
        anchor_run_id="run_101",
    )

    assert latest is not None
    assert latest.run_id == "run_303"
    assert baseline is not None
    assert baseline.run_id == "run_101"


def test_run_improve_loop_records_targeted_verify_and_cherry_picks(
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
            base_ref=base_ref,
            overall=70.0,
            weakest_dim="learnability",
        ),
    )

    seen_output_lang: list[str | None] = []

    def fake_mutate_prompt_in_worktree(**kwargs: Any) -> None:
        seen_output_lang.append(cast("str | None", kwargs.get("output_lang")))
        worktree_root = Path(kwargs["worktree_root"])
        target_prompt = str(kwargs["target_prompt"])
        for relative in (
            worktree_root / "prompts" / target_prompt,
            worktree_root / "src" / "ahadiff" / "prompts" / target_prompt,
        ):
            relative.write_text("lesson generate v2\n", encoding="utf-8")

    def fake_run_replay_learn_subprocess(**kwargs: Any) -> Path:
        seen_output_lang.append(cast("str | None", kwargs.get("output_lang")))
        worktree_root = Path(kwargs["worktree_root"])
        run_path = worktree_root / ".ahadiff" / "runs" / "run_candidate"
        _write_run_fixture(
            run_path,
            run_id="run_candidate",
            source_ref=source_ref,
            base_ref=base_ref,
            finalized=True,
        )
        return run_path

    monkeypatch.setattr(
        "ahadiff.improve.loop._mutate_prompt_in_worktree",
        fake_mutate_prompt_in_worktree,
    )
    monkeypatch.setattr(
        "ahadiff.improve.loop._run_replay_learn_subprocess",
        fake_run_replay_learn_subprocess,
    )

    def fake_evaluate_run(path: Path) -> ScoreReport:
        return _score_report(
            run_id=path.name,
            source_ref=source_ref,
            overall=75.0,
            weakest_dim="evidence",
        )

    monkeypatch.setattr("ahadiff.improve.loop.evaluate_run", fake_evaluate_run)

    result = run_improve_loop(
        repo_root=repo_root,
        state_dir=state_dir,
        db_path=db_path,
        rounds=1,
        suite="local",
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
        output_lang="zh-CN",
    )

    events = load_result_events_from_db(db_path)
    candidate_event = next(event for event in events if event.run_id == "run_candidate")
    assert result.rounds_completed == 1
    assert result.outcomes[0].status == "targeted_verify"
    assert seen_output_lang == ["zh-CN", "zh-CN"]
    assert candidate_event.event_type == "improve"
    assert candidate_event.status == "targeted_verify"
    assert (state_dir / "runs" / "run_candidate").exists()
    assert not (state_dir / "runs" / "run_candidate" / "quiz" / "cards.jsonl").exists()
    assert (repo_root / "prompts" / "lesson_generate.md").read_text(
        encoding="utf-8"
    ) == "lesson generate v2\n"


def test_run_improve_loop_propagates_output_lang_to_replay_and_provider_request(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root, state_dir, db_path, base_ref, source_ref = _prepare_improve_repo(tmp_path)
    seen_requests: list[ProviderRequest] = []
    seen_commands: list[list[str]] = []
    real_subprocess_run = subprocess.run

    class FakeProvider:
        def generate(self, request: ProviderRequest) -> ProviderResponse:
            seen_requests.append(request)
            return ProviderResponse(
                content=json.dumps(
                    {
                        "target_file": "lesson_generate.md",
                        "content": "lesson generate zh\n",
                    }
                ),
                model_id="fake",
                input_tokens=1,
                output_tokens=1,
            )

        def close(self) -> None:
            return

    def fake_make_provider(*args: Any, **kwargs: Any) -> FakeProvider:
        del args, kwargs
        return FakeProvider()

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = cast("list[str]", args[0])
        if command and command[0] == "git":
            return cast("subprocess.CompletedProcess[str]", real_subprocess_run(*args, **kwargs))
        seen_commands.append(command)
        cwd = kwargs.get("cwd")
        assert isinstance(cwd, Path)
        _write_run_fixture(
            cwd / ".ahadiff" / "runs" / "run_candidate",
            run_id="run_candidate",
            source_ref=source_ref,
            base_ref=base_ref,
            finalized=True,
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    class FakeCherryPickResult:
        pending_conflict = False
        conflicted_files: tuple[str, ...] = ()

    def fake_cherry_pick(repo_root: Path, commit_sha: str) -> FakeCherryPickResult:
        del repo_root, commit_sha
        return FakeCherryPickResult()

    def fake_evaluate_run(path: Path) -> ScoreReport:
        return _score_report(
            run_id=path.name,
            source_ref=source_ref,
            overall=75.0,
            weakest_dim="evidence",
        )

    monkeypatch.setattr(improve_loop_module, "make_provider", fake_make_provider)
    monkeypatch.setattr(improve_loop_module.subprocess, "run", fake_run)
    monkeypatch.setattr(improve_loop_module, "_cherry_pick_prompt_commit", fake_cherry_pick)
    monkeypatch.setattr(improve_loop_module, "evaluate_run", fake_evaluate_run)

    result = run_improve_loop(
        repo_root=repo_root,
        state_dir=state_dir,
        db_path=db_path,
        rounds=1,
        suite="local",
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
        output_lang="zh-CN",
    )

    assert result.outcomes[0].status == "targeted_verify"
    assert [request.output_lang for request in seen_requests] == ["zh-CN"]
    assert seen_commands
    assert "--lang" in seen_commands[0]
    lang_index = seen_commands[0].index("--lang")
    assert seen_commands[0][lang_index + 1] == "zh-CN"


def test_run_improve_loop_records_discard_without_cherry_pick(
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
            base_ref=base_ref,
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
            relative.write_text("lesson generate discard\n", encoding="utf-8")

    def fake_run_replay_learn_subprocess(**kwargs: Any) -> Path:
        worktree_root = Path(kwargs["worktree_root"])
        run_path = worktree_root / ".ahadiff" / "runs" / "run_discard"
        _write_run_fixture(
            run_path,
            run_id="run_discard",
            source_ref=source_ref,
            base_ref=base_ref,
            finalized=False,
        )
        return run_path

    def fake_cherry_pick(repo_root: Path, commit_sha: str) -> None:
        del repo_root, commit_sha
        raise AssertionError("discard path must not cherry-pick")

    monkeypatch.setattr(
        "ahadiff.improve.loop._mutate_prompt_in_worktree",
        fake_mutate_prompt_in_worktree,
    )
    monkeypatch.setattr(
        "ahadiff.improve.loop._run_replay_learn_subprocess",
        fake_run_replay_learn_subprocess,
    )
    monkeypatch.setattr(
        "ahadiff.improve.loop._cherry_pick_prompt_commit",
        fake_cherry_pick,
    )

    def fake_evaluate_run(path: Path) -> ScoreReport:
        return _score_report(
            run_id=path.name,
            source_ref=source_ref,
            overall=69.0,
            weakest_dim="evidence",
        )

    monkeypatch.setattr("ahadiff.improve.loop.evaluate_run", fake_evaluate_run)

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
    candidate_event = next(event for event in events if event.run_id == "run_discard")
    candidate_run_path = state_dir / "runs" / "run_discard"
    assert result.outcomes[0].status == "discard"
    assert candidate_event.status == "discard"
    assert not finalized_marker_path(candidate_run_path).exists()
    assert (repo_root / "prompts" / "lesson_generate.md").read_text(
        encoding="utf-8"
    ) == "lesson generate v1\n"


def test_run_improve_loop_cleans_worktree_on_mutation_failure(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root, state_dir, db_path, _base_ref, _source_ref = _prepare_improve_repo(tmp_path)
    seen_worktrees: list[Path] = []

    def fake_mutate_prompt_in_worktree(**kwargs: Any) -> None:
        seen_worktrees.append(Path(kwargs["worktree_root"]))
        raise InputError("mutation failed")

    monkeypatch.setattr(
        improve_loop_module, "_mutate_prompt_in_worktree", fake_mutate_prompt_in_worktree
    )

    with pytest.raises(InputError, match="mutation failed"):
        run_improve_loop(
            repo_root=repo_root,
            state_dir=state_dir,
            db_path=db_path,
            rounds=1,
            suite="local",
            provider_config=_provider_config(),
            api_key=None,
            security_config=SecurityConfig(),
        )

    session = _load_single_improve_session(state_dir)
    assert session.worktree_path is None
    assert seen_worktrees
    assert not seen_worktrees[0].exists()


def test_run_improve_loop_cleans_worktree_on_system_exit(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root, state_dir, db_path, _base_ref, _source_ref = _prepare_improve_repo(tmp_path)
    seen_worktrees: list[Path] = []

    def fake_mutate_prompt_in_worktree(**kwargs: Any) -> None:
        seen_worktrees.append(Path(kwargs["worktree_root"]))
        raise SystemExit(2)

    monkeypatch.setattr(
        improve_loop_module, "_mutate_prompt_in_worktree", fake_mutate_prompt_in_worktree
    )

    with pytest.raises(SystemExit):
        run_improve_loop(
            repo_root=repo_root,
            state_dir=state_dir,
            db_path=db_path,
            rounds=1,
            suite="local",
            provider_config=_provider_config(),
            api_key=None,
            security_config=SecurityConfig(),
        )

    session = _load_single_improve_session(state_dir)
    assert session.worktree_path is None
    assert seen_worktrees
    assert not seen_worktrees[0].exists()


def test_run_improve_loop_cleans_worktree_on_replay_failure(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root, state_dir, db_path, _base_ref, _source_ref = _prepare_improve_repo(tmp_path)
    seen_worktrees: list[Path] = []
    real_subprocess_run = subprocess.run

    def fake_mutate_prompt_in_worktree(**kwargs: Any) -> None:
        worktree_root = Path(kwargs["worktree_root"])
        seen_worktrees.append(worktree_root)
        target_prompt = str(kwargs["target_prompt"])
        for relative in (
            worktree_root / "prompts" / target_prompt,
            worktree_root / "src" / "ahadiff" / "prompts" / target_prompt,
        ):
            relative.write_text("lesson generate replay failure\n", encoding="utf-8")

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = cast("list[str]", args[0])
        if command and command[0] == "git":
            return cast("subprocess.CompletedProcess[str]", real_subprocess_run(*args, **kwargs))
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="replay failed",
        )

    monkeypatch.setattr(
        improve_loop_module, "_mutate_prompt_in_worktree", fake_mutate_prompt_in_worktree
    )
    monkeypatch.setattr(improve_loop_module.subprocess, "run", fake_run)

    with pytest.raises(InputError, match="replay failed"):
        run_improve_loop(
            repo_root=repo_root,
            state_dir=state_dir,
            db_path=db_path,
            rounds=1,
            suite="local",
            provider_config=_provider_config(),
            api_key=None,
            security_config=SecurityConfig(),
        )

    session = _load_single_improve_session(state_dir)
    assert session.worktree_path is None
    assert seen_worktrees
    assert not seen_worktrees[0].exists()


def test_run_improve_loop_keeps_worktree_on_cherry_pick_conflict(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root, state_dir, db_path, base_ref, source_ref = _prepare_improve_repo(tmp_path)

    def fake_mutate_prompt_in_worktree(**kwargs: Any) -> None:
        worktree_root = Path(kwargs["worktree_root"])
        target_prompt = str(kwargs["target_prompt"])
        for relative in (
            worktree_root / "prompts" / target_prompt,
            worktree_root / "src" / "ahadiff" / "prompts" / target_prompt,
        ):
            relative.write_text("lesson generate pending conflict\n", encoding="utf-8")

    def fake_run_replay_learn_subprocess(**kwargs: Any) -> Path:
        worktree_root = Path(kwargs["worktree_root"])
        run_path = worktree_root / ".ahadiff" / "runs" / "run_pending"
        _write_run_fixture(
            run_path,
            run_id="run_pending",
            source_ref=source_ref,
            base_ref=base_ref,
            finalized=True,
        )
        return run_path

    def fake_evaluate_run(path: Path) -> ScoreReport:
        return _score_report(
            run_id=path.name,
            source_ref=source_ref,
            overall=75.0,
            weakest_dim="evidence",
        )

    class FakeCherryPickResult:
        pending_conflict = True
        conflicted_files = ("prompts/lesson_generate.md",)

    def fake_cherry_pick(repo_root: Path, commit_sha: str) -> FakeCherryPickResult:
        del repo_root, commit_sha
        return FakeCherryPickResult()

    monkeypatch.setattr(
        improve_loop_module, "_mutate_prompt_in_worktree", fake_mutate_prompt_in_worktree
    )
    monkeypatch.setattr(
        improve_loop_module,
        "_run_replay_learn_subprocess",
        fake_run_replay_learn_subprocess,
    )
    monkeypatch.setattr(improve_loop_module, "evaluate_run", fake_evaluate_run)
    monkeypatch.setattr(improve_loop_module, "_cherry_pick_prompt_commit", fake_cherry_pick)

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

    session = load_improve_session(state_dir, result.session_id)
    assert result.outcomes[0].cherry_pick_pending is True
    assert session.worktree_path is not None
    assert Path(session.worktree_path).exists()
    with pytest.raises(InputError, match="pending improve worktree"):
        run_improve_loop(
            repo_root=repo_root,
            state_dir=state_dir,
            db_path=db_path,
            rounds=1,
            suite="local",
            provider_config=_provider_config(),
            api_key=None,
            security_config=SecurityConfig(),
            resume_session_id=result.session_id,
        )


def test_run_improve_loop_conflict_pending_is_not_finalized_or_used_as_baseline(
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
            base_ref=base_ref,
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
            relative.write_text("lesson generate pending conflict\n", encoding="utf-8")

    def fake_run_replay_learn_subprocess(**kwargs: Any) -> Path:
        worktree_root = Path(kwargs["worktree_root"])
        run_path = worktree_root / ".ahadiff" / "runs" / "run_pending"
        _write_run_fixture(
            run_path,
            run_id="run_pending",
            source_ref=source_ref,
            base_ref=base_ref,
            finalized=True,
        )
        return run_path

    def fake_evaluate_run(path: Path) -> ScoreReport:
        return _score_report(
            run_id=path.name,
            source_ref=source_ref,
            overall=75.0,
            weakest_dim="evidence",
        )

    monkeypatch.setattr(
        improve_loop_module, "_mutate_prompt_in_worktree", fake_mutate_prompt_in_worktree
    )
    monkeypatch.setattr(
        improve_loop_module,
        "_run_replay_learn_subprocess",
        fake_run_replay_learn_subprocess,
    )

    class FakeCherryPickResult:
        pending_conflict = True
        conflicted_files = ("prompts/lesson_generate.md",)

    def fake_cherry_pick(repo_root: Path, commit_sha: str) -> FakeCherryPickResult:
        del repo_root, commit_sha
        return FakeCherryPickResult()

    monkeypatch.setattr(improve_loop_module, "_cherry_pick_prompt_commit", fake_cherry_pick)
    monkeypatch.setattr(improve_loop_module, "evaluate_run", fake_evaluate_run)

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

    pending_run_path = state_dir / "runs" / "run_pending"
    baseline_event = cast("Any", improve_loop_module)._select_baseline_event_for_source(
        state_dir=state_dir,
        db_path=db_path,
        source_ref=source_ref,
        base_ref=base_ref,
        anchor_run_id="run_anchor",
    )
    assert result.outcomes[0].status == "targeted_verify"
    assert result.outcomes[0].cherry_pick_pending is True
    assert not finalized_marker_path(pending_run_path).exists()
    assert baseline_event is not None
    assert baseline_event.run_id == "run_anchor"


def test_run_improve_loop_resume_rejects_pending_worktree_without_mutation(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root = tmp_path / "repo"
    state_dir = repo_root / ".ahadiff"
    pending_worktree = state_dir / "improve" / "wt" / "pending-r1"
    pending_worktree.mkdir(parents=True)
    session = update_improve_session(
        create_improve_session(
            session_id="improve_pending",
            suite="local",
            anchor_run_id="run_anchor",
        ),
        worktree_path=str(pending_worktree),
    )
    save_improve_session(state_dir, session)

    def fail_if_called(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("pending resume must stop before mutating worktrees")

    def fake_prompts_are_dirty(repo_root: Path) -> bool:
        del repo_root
        return False

    monkeypatch.setattr(improve_loop_module, "_prompts_are_dirty", fake_prompts_are_dirty)
    monkeypatch.setattr(improve_loop_module, "_create_worktree", fail_if_called)
    monkeypatch.setattr(improve_loop_module, "_mutate_prompt_in_worktree", fail_if_called)

    with pytest.raises(InputError, match="pending improve worktree"):
        run_improve_loop(
            repo_root=repo_root,
            state_dir=state_dir,
            db_path=state_dir / "review.sqlite",
            rounds=1,
            suite="local",
            provider_config=_provider_config(),
            api_key=None,
            security_config=SecurityConfig(),
            resume_session_id="improve_pending",
        )

    assert pending_worktree.exists()


def test_run_improve_loop_interrupt_after_round_does_not_double_append(
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
            base_ref=base_ref,
            overall=70.0,
            weakest_dim="learnability",
        ),
    )

    class FakeInterrupt:
        requested = True

        def install(self) -> None:
            return

        def restore(self) -> None:
            return

    def fake_mutate_prompt_in_worktree(**kwargs: Any) -> None:
        worktree_root = Path(kwargs["worktree_root"])
        target_prompt = str(kwargs["target_prompt"])
        for relative in (
            worktree_root / "prompts" / target_prompt,
            worktree_root / "src" / "ahadiff" / "prompts" / target_prompt,
        ):
            relative.write_text("lesson generate v2\n", encoding="utf-8")

    def fake_run_replay_learn_subprocess(**kwargs: Any) -> Path:
        worktree_root = Path(kwargs["worktree_root"])
        run_path = worktree_root / ".ahadiff" / "runs" / "run_interrupt"
        _write_run_fixture(
            run_path,
            run_id="run_interrupt",
            source_ref=source_ref,
            base_ref=base_ref,
            finalized=False,
        )
        return run_path

    def fake_evaluate_run(path: Path) -> ScoreReport:
        return _score_report(
            run_id=path.name,
            source_ref=source_ref,
            overall=75.0,
            weakest_dim="evidence",
        )

    monkeypatch.setattr(improve_loop_module, "_InterruptController", FakeInterrupt)
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

    improve_events = [
        event for event in load_result_events_from_db(db_path) if event.run_id == "run_interrupt"
    ]
    assert result.rounds_completed == 1
    assert [event.status for event in improve_events] == ["targeted_verify"]
    assert result.warnings == (
        "interrupt requested after round 1; stopped before starting the next round",
    )


def test_cherry_pick_prompt_commit_raises_on_non_conflict_failure(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def fake_run_git(
        repo_root: Path, *args: str, **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        del repo_root, kwargs
        if args[:1] == ("cherry-pick",) and args[1:] != ("--abort",):
            return subprocess.CompletedProcess(
                ["git", *args],
                1,
                stdout="",
                stderr="fatal: bad revision 'bad-sha'",
            )
        if args[:3] == ("diff", "--name-only", "--diff-filter=U"):
            return subprocess.CompletedProcess(["git", *args], 0, stdout="", stderr="")
        if args == ("cherry-pick", "--abort"):
            return subprocess.CompletedProcess(["git", *args], 128, stdout="", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(improve_loop_module, "run_git", fake_run_git)

    with pytest.raises(InputError, match="bad revision"):
        cast("Any", improve_loop_module)._cherry_pick_prompt_commit(tmp_path, "bad-sha")


def test_mutate_prompt_in_worktree_rejects_null_byte_content_without_writing(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _write_prompt_files(tmp_path)

    class FakeProvider:
        def generate(self, request: Any) -> ProviderResponse:
            del request
            return ProviderResponse(
                content=json.dumps(
                    {
                        "target_file": "lesson_generate.md",
                        "content": "changed\x00prompt",
                    }
                ),
                model_id="fake",
                input_tokens=1,
                output_tokens=1,
            )

        def close(self) -> None:
            return

    def fake_make_provider(*args: Any, **kwargs: Any) -> FakeProvider:
        del args, kwargs
        return FakeProvider()

    monkeypatch.setattr(improve_loop_module, "make_provider", fake_make_provider)

    before_repo = (tmp_path / "prompts" / "lesson_generate.md").read_text(encoding="utf-8")
    before_pkg = (tmp_path / "src" / "ahadiff" / "prompts" / "lesson_generate.md").read_text(
        encoding="utf-8"
    )
    with pytest.raises(InputError, match="null bytes"):
        cast("Any", improve_loop_module)._mutate_prompt_in_worktree(
            worktree_root=tmp_path,
            target_prompt="lesson_generate.md",
            target_dimension="learnability",
            baseline_event=_baseline_event(
                run_id="run_anchor",
                source_ref="head-ref",
                overall=70.0,
                weakest_dim="learnability",
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
        )

    assert (tmp_path / "prompts" / "lesson_generate.md").read_text(encoding="utf-8") == before_repo
    assert (tmp_path / "src" / "ahadiff" / "prompts" / "lesson_generate.md").read_text(
        encoding="utf-8"
    ) == before_pkg


def test_mutate_prompt_in_worktree_rejects_oversized_content_without_writing(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _write_prompt_files(tmp_path)
    oversized_content = "x" * (improve_loop_module._MAX_MUTATED_PROMPT_BYTES + 1)  # pyright: ignore[reportPrivateUsage]

    class FakeProvider:
        def generate(self, request: Any) -> ProviderResponse:
            del request
            return ProviderResponse(
                content=json.dumps(
                    {
                        "target_file": "lesson_generate.md",
                        "content": oversized_content,
                    }
                ),
                model_id="fake",
                input_tokens=1,
                output_tokens=1,
            )

        def close(self) -> None:
            return

    def fake_make_provider(*args: Any, **kwargs: Any) -> FakeProvider:
        del args, kwargs
        return FakeProvider()

    monkeypatch.setattr(improve_loop_module, "make_provider", fake_make_provider)

    repo_prompt = tmp_path / "prompts" / "lesson_generate.md"
    package_prompt = tmp_path / "src" / "ahadiff" / "prompts" / "lesson_generate.md"
    before_repo = repo_prompt.read_text(encoding="utf-8")
    before_pkg = package_prompt.read_text(encoding="utf-8")

    with pytest.raises(InputError, match="exceeds 262144 bytes"):
        cast("Any", improve_loop_module)._mutate_prompt_in_worktree(
            worktree_root=tmp_path,
            target_prompt="lesson_generate.md",
            target_dimension="learnability",
            baseline_event=_baseline_event(
                run_id="run_anchor",
                source_ref="head-ref",
                overall=70.0,
                weakest_dim="learnability",
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
        )

    assert repo_prompt.read_text(encoding="utf-8") == before_repo
    assert package_prompt.read_text(encoding="utf-8") == before_pkg
