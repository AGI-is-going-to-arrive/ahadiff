from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from ahadiff.core.config import SecurityConfig
from ahadiff.core.errors import InputError
from ahadiff.improve import loop as improve_loop_module
from ahadiff.improve.loop import run_improve_loop
from ahadiff.improve.program import (
    create_improve_session,
    load_improve_program,
    save_improve_session,
    update_improve_session,
)
from ahadiff.llm import ProviderResponse
from ahadiff.review.database import load_result_events_from_db
from tests.unit import test_improve_loop as improve_fixtures

_baseline_event = improve_fixtures._baseline_event  # pyright: ignore[reportPrivateUsage]
_prepare_improve_repo = improve_fixtures._prepare_improve_repo  # pyright: ignore[reportPrivateUsage]
_provider_config = improve_fixtures._provider_config  # pyright: ignore[reportPrivateUsage]
_score_report = improve_fixtures._score_report  # pyright: ignore[reportPrivateUsage]
_write_prompt_files = improve_fixtures._write_prompt_files  # pyright: ignore[reportPrivateUsage]
_write_run_fixture = improve_fixtures._write_run_fixture  # pyright: ignore[reportPrivateUsage]


def test_gate4_create_worktree_refuses_existing_directory_without_deleting(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = tmp_path / ".ahadiff" / "improve" / "wt" / "existing-r1"
    target.mkdir(parents=True)
    sentinel = target / "sentinel.txt"
    sentinel.write_text("keep me\n", encoding="utf-8")

    with pytest.raises(InputError, match="overwrite existing improve worktree"):
        cast("Any", improve_loop_module)._create_worktree(repo_root, target)

    assert sentinel.read_text(encoding="utf-8") == "keep me\n"


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires elevated Windows privileges")
def test_gate4_create_worktree_refuses_symlinked_parent(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target_parent = tmp_path / "outside"
    target_parent.mkdir()
    wt_parent = tmp_path / ".ahadiff" / "improve" / "wt"
    wt_parent.parent.mkdir(parents=True)
    wt_parent.symlink_to(target_parent, target_is_directory=True)

    with pytest.raises(InputError, match="parent directory must not be a symlink"):
        cast("Any", improve_loop_module)._create_worktree(repo_root, wt_parent / "safe-r1")

    assert not (target_parent / "safe-r1").exists()


def test_gate4_directory_no_follow_rejects_windows_reparse_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "junction"
    parent.mkdir()

    class FakeWindowsStat:
        st_mode = stat.S_IFDIR | 0o755
        st_file_attributes = 0x400

    def fake_stat(path: object, *args: object, **kwargs: object) -> FakeWindowsStat:
        del path, args, kwargs
        return FakeWindowsStat()

    monkeypatch.setattr(improve_loop_module.sys, "platform", "win32")
    monkeypatch.setattr(improve_loop_module.os, "stat", fake_stat)

    with pytest.raises(InputError, match="reparse point|junction"):
        cast("Any", improve_loop_module)._assert_directory_no_follow(parent)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires elevated Windows privileges")
def test_gate4_mutate_prompt_rejects_symlinked_repo_prompt_without_provider(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _write_prompt_files(tmp_path)
    repo_prompt = tmp_path / "prompts" / "lesson_generate.md"
    repo_prompt.unlink()
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    repo_prompt.symlink_to(outside)

    def fail_provider(*args: Any, **kwargs: Any) -> object:
        del args, kwargs
        raise AssertionError("provider must not be called for symlinked prompt")

    monkeypatch.setattr(improve_loop_module, "make_provider", fail_provider)

    with pytest.raises(InputError, match="must not be a symlink"):
        cast("Any", improve_loop_module)._mutate_prompt_in_worktree(
            worktree_root=tmp_path,
            target_prompt="lesson_generate.md",
            target_dimension="learnability",
            baseline_event=_baseline_event_fixture("run_anchor", "head-ref"),
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


def test_gate4_mutate_prompt_rejects_surrogate_content_without_writing(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _write_prompt_files(tmp_path)
    repo_prompt = tmp_path / "prompts" / "lesson_generate.md"
    package_prompt = tmp_path / "src" / "ahadiff" / "prompts" / "lesson_generate.md"
    before_repo = repo_prompt.read_text(encoding="utf-8")
    before_package = package_prompt.read_text(encoding="utf-8")

    class FakeProvider:
        def generate(self, request: Any) -> ProviderResponse:
            del request
            return ProviderResponse(
                content=json.dumps(
                    {
                        "target_file": "lesson_generate.md",
                        "content": "bad\ud800prompt",
                    }
                ),
                model_id="fake",
                input_tokens=1,
                output_tokens=1,
            )

        def close(self) -> None:
            return

    def fake_make_provider(*args: object, **kwargs: object) -> FakeProvider:
        del args, kwargs
        return FakeProvider()

    monkeypatch.setattr(improve_loop_module, "make_provider", fake_make_provider)

    with pytest.raises(InputError, match="valid UTF-8"):
        cast("Any", improve_loop_module)._mutate_prompt_in_worktree(
            worktree_root=tmp_path,
            target_prompt="lesson_generate.md",
            target_dimension="learnability",
            baseline_event=_baseline_event_fixture("run_anchor", "head-ref"),
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
    assert package_prompt.read_text(encoding="utf-8") == before_package


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires elevated Windows privileges")
def test_gate4_load_improve_program_rejects_symlink(
    tmp_path: Path,
) -> None:
    _write_prompt_files(tmp_path)
    program = tmp_path / "prompts" / "improve_program.md"
    program.unlink()
    outside = tmp_path / "outside_program.md"
    outside.write_text("outside program\n", encoding="utf-8")
    program.symlink_to(outside)

    with pytest.raises(InputError, match="must not be a symlink"):
        load_improve_program(tmp_path)


def test_gate4_load_improve_program_rejects_null_bytes(tmp_path: Path) -> None:
    _write_prompt_files(tmp_path)
    (tmp_path / "prompts" / "improve_program.md").write_text(
        "valid prefix\x00invalid\n",
        encoding="utf-8",
    )

    with pytest.raises(InputError, match="must not contain null bytes"):
        load_improve_program(tmp_path)


def test_gate4_replay_requires_fresh_run_artifact(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    worktree_root = tmp_path / "worktree"
    existing_run = worktree_root / ".ahadiff" / "runs" / "old_run"
    _write_run_fixture(
        existing_run,
        run_id="old_run",
        source_ref="head-ref",
        base_ref="base-ref",
        finalized=True,
    )
    anchor_run = tmp_path / "anchor"
    _write_run_fixture(
        anchor_run,
        run_id="run_anchor",
        source_ref="head-ref",
        base_ref="base-ref",
        finalized=True,
    )

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = cast("list[str]", args[0])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(improve_loop_module.subprocess, "run", fake_run)

    with pytest.raises(InputError, match="no fresh run artifacts"):
        cast("Any", improve_loop_module)._run_replay_learn_subprocess(
            worktree_root=worktree_root,
            anchor_run_path=anchor_run,
            metadata=json.loads((anchor_run / "metadata.json").read_text(encoding="utf-8")),
            provider_config=_provider_config(),
            api_key=None,
            privacy_mode="strict_local",
        )


def test_gate4_new_session_rejects_existing_pending_worktree(
    tmp_path: Path,
) -> None:
    repo_root, state_dir, db_path, _base_ref, _source_ref = _prepare_improve_repo(tmp_path)
    pending_worktree = state_dir / "improve" / "wt" / "pending-r1"
    pending_worktree.mkdir(parents=True)
    session = create_improve_session(
        session_id="improve_pending_other",
        suite="local",
        anchor_run_id="run_anchor",
    )
    save_improve_session(
        state_dir,
        update_improve_session(session, worktree_path=str(pending_worktree)),
    )

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
        )


def test_gate4_cherry_pick_refuses_when_target_head_moves(
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
            relative.write_text("lesson generate changed\n", encoding="utf-8")

    def fake_run_replay_learn_subprocess(**kwargs: Any) -> Path:
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

    def fake_evaluate_run(path: Path) -> Any:
        (repo_root / "manual.txt").write_text("manual change\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "manual.txt"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "commit", "-m", "manual branch movement"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
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
    monkeypatch.setattr(improve_loop_module, "evaluate_run", fake_evaluate_run)

    with pytest.raises(InputError, match="target HEAD changed"):
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

    assert all(event.run_id != "run_candidate" for event in load_result_events_from_db(db_path))


def test_gate4_candidate_source_ref_mismatch_is_rejected_before_append(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root, state_dir, db_path, base_ref, _source_ref = _prepare_improve_repo(tmp_path)

    def fake_mutate_prompt_in_worktree(**kwargs: Any) -> None:
        worktree_root = Path(kwargs["worktree_root"])
        target_prompt = str(kwargs["target_prompt"])
        for relative in (
            worktree_root / "prompts" / target_prompt,
            worktree_root / "src" / "ahadiff" / "prompts" / target_prompt,
        ):
            relative.write_text("lesson generate changed\n", encoding="utf-8")

    def fake_run_replay_learn_subprocess(**kwargs: Any) -> Path:
        worktree_root = Path(kwargs["worktree_root"])
        run_path = worktree_root / ".ahadiff" / "runs" / "run_wrong_source"
        _write_run_fixture(
            run_path,
            run_id="run_wrong_source",
            source_ref="other-source-ref",
            base_ref=base_ref,
            finalized=True,
        )
        return run_path

    monkeypatch.setattr(
        improve_loop_module, "_mutate_prompt_in_worktree", fake_mutate_prompt_in_worktree
    )
    monkeypatch.setattr(
        improve_loop_module,
        "_run_replay_learn_subprocess",
        fake_run_replay_learn_subprocess,
    )

    with pytest.raises(InputError, match="source_ref does not match improve anchor"):
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

    assert all(event.run_id != "run_wrong_source" for event in load_result_events_from_db(db_path))


def test_gate4_baseline_score_must_match_selected_event(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root, state_dir, db_path, base_ref, source_ref = _prepare_improve_repo(tmp_path)
    score_path = state_dir / "runs" / "run_anchor" / "score.json"
    payload = json.loads(score_path.read_text(encoding="utf-8"))
    payload["overall"] = 1.0
    score_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    def fake_mutate_prompt_in_worktree(**kwargs: Any) -> None:
        worktree_root = Path(kwargs["worktree_root"])
        target_prompt = str(kwargs["target_prompt"])
        for relative in (
            worktree_root / "prompts" / target_prompt,
            worktree_root / "src" / "ahadiff" / "prompts" / target_prompt,
        ):
            relative.write_text("lesson generate changed\n", encoding="utf-8")

    def fake_run_replay_learn_subprocess(**kwargs: Any) -> Path:
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

    def fake_evaluate_run(path: Path) -> Any:
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
    monkeypatch.setattr(improve_loop_module, "evaluate_run", fake_evaluate_run)

    with pytest.raises(InputError, match="overall does not match selected baseline event"):
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


def test_gate4_mutate_prompt_rejects_llm_targeting_different_mutable_prompt(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _write_prompt_files(tmp_path)
    repo_prompt = tmp_path / "prompts" / "lesson_generate.md"
    package_prompt = tmp_path / "src" / "ahadiff" / "prompts" / "lesson_generate.md"
    before_repo = repo_prompt.read_text(encoding="utf-8")
    before_package = package_prompt.read_text(encoding="utf-8")

    class FakeProvider:
        def generate(self, request: Any) -> ProviderResponse:
            del request
            return ProviderResponse(
                content=json.dumps(
                    {
                        "target_file": "claim_extract.md",
                        "content": "hijacked content\n",
                    }
                ),
                model_id="fake",
                input_tokens=1,
                output_tokens=1,
            )

        def close(self) -> None:
            return

    def fake_make_provider(*args: object, **kwargs: object) -> FakeProvider:
        del args, kwargs
        return FakeProvider()

    monkeypatch.setattr(improve_loop_module, "make_provider", fake_make_provider)

    with pytest.raises(InputError, match="attempted to mutate"):
        cast("Any", improve_loop_module)._mutate_prompt_in_worktree(
            worktree_root=tmp_path,
            target_prompt="lesson_generate.md",
            target_dimension="learnability",
            baseline_event=_baseline_event_fixture("run_anchor", "head-ref"),
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
    assert package_prompt.read_text(encoding="utf-8") == before_package
    claim_prompt = tmp_path / "prompts" / "claim_extract.md"
    assert "hijacked" not in claim_prompt.read_text(encoding="utf-8")


def test_gate4_mutate_prompt_rejects_oversized_content(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _write_prompt_files(tmp_path)
    repo_prompt = tmp_path / "prompts" / "lesson_generate.md"
    before_repo = repo_prompt.read_text(encoding="utf-8")

    class FakeProvider:
        def generate(self, request: Any) -> ProviderResponse:
            del request
            return ProviderResponse(
                content=json.dumps(
                    {
                        "target_file": "lesson_generate.md",
                        "content": "A" * (256 * 1024 + 1),
                    }
                ),
                model_id="fake",
                input_tokens=1,
                output_tokens=1,
            )

        def close(self) -> None:
            return

    def fake_make_provider(*args: object, **kwargs: object) -> FakeProvider:
        del args, kwargs
        return FakeProvider()

    monkeypatch.setattr(improve_loop_module, "make_provider", fake_make_provider)

    with pytest.raises(InputError, match="exceeds 262144 bytes"):
        cast("Any", improve_loop_module)._mutate_prompt_in_worktree(
            worktree_root=tmp_path,
            target_prompt="lesson_generate.md",
            target_dimension="learnability",
            baseline_event=_baseline_event_fixture("run_anchor", "head-ref"),
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


def test_gate4_worktree_path_rejects_traversal(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = tmp_path / ".ahadiff" / "improve" / "wt" / ".." / ".." / "escape-r1"

    with pytest.raises(InputError, match="path traversal"):
        cast("Any", improve_loop_module)._create_worktree(repo_root, target)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires elevated Windows privileges")
def test_gate4_copy_candidate_run_rejects_symlinks_in_tree(tmp_path: Path) -> None:
    source_run = tmp_path / "worktree" / ".ahadiff" / "runs" / "run_with_symlink"
    source_run.mkdir(parents=True)
    (source_run / "metadata.json").write_text(
        json.dumps({"run_id": "run_with_symlink", "source_ref": "ref"}),
        encoding="utf-8",
    )
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (source_run / "stolen.txt").symlink_to(outside)

    state_dir = tmp_path / "state"
    state_dir.mkdir()

    with pytest.raises(InputError, match="must not be a symlink"):
        cast("Any", improve_loop_module)._copy_candidate_run_to_state(
            source_run_path=source_run,
            state_dir=state_dir,
        )


def test_gate4_load_improve_program_rejects_oversized(tmp_path: Path) -> None:
    _write_prompt_files(tmp_path)
    program = tmp_path / "prompts" / "improve_program.md"
    program.write_bytes(b"X" * (256 * 1024 + 1))

    with pytest.raises(InputError, match="exceeds 262144 bytes"):
        load_improve_program(tmp_path)


def test_gate4_candidate_base_ref_mismatch_is_rejected(tmp_path: Path) -> None:
    run_path = tmp_path / "run_candidate"
    _write_run_fixture(
        run_path,
        run_id="run_candidate",
        source_ref="head-ref",
        base_ref="wrong-base",
        finalized=True,
    )

    with pytest.raises(InputError, match="base_ref does not match"):
        cast("Any", improve_loop_module)._validate_candidate_run_matches_anchor(
            run_path,
            expected_source_ref="head-ref",
            expected_base_ref="correct-base",
        )


def test_gate4_claims_run_id_mismatch_is_rejected(tmp_path: Path) -> None:
    claims_path = tmp_path / "claims.jsonl"
    claims_path.write_text(
        json.dumps({"run_id": "wrong_run", "claim": "test"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(InputError, match="claims.jsonl run_id does not match"):
        cast("Any", improve_loop_module)._validate_claim_records_belong_to_run(
            claims_path, "expected_run"
        )


def test_gate4_cherry_pick_target_refuses_branch_mismatch(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root, _state_dir, _db_path, _base_ref, _source_ref = _prepare_improve_repo(tmp_path)

    monkeypatch.setattr(
        improve_loop_module,
        "_current_branch",
        lambda _root: "feature-branch",  # type: ignore[arg-type]
    )

    with pytest.raises(InputError, match="unexpected branch"):
        cast("Any", improve_loop_module)._validate_cherry_pick_target(
            repo_root,
            expected_branch="main",
            expected_head="dummy-head",
        )


def test_gate4_cherry_pick_parent_mismatch_auto_reverts(
    tmp_path: Path,
) -> None:
    repo_root, _state_dir, _db_path, _base_ref, _source_ref = _prepare_improve_repo(tmp_path)
    (repo_root / "prompt_file.txt").write_text("original\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "prompt_file.txt"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "commit", "-m", "add prompt file"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    (repo_root / "prompt_file.txt").write_text("modified by improve\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "prompt_file.txt"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "commit", "-m", "improve round 1"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    commit_to_pick = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    subprocess.run(
        ["git", "reset", "--hard", "HEAD~1"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    (repo_root / "other.txt").write_text("interloper\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "other.txt"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "commit", "-m", "concurrent commit"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    with pytest.raises(InputError, match="parent mismatch"):
        cast("Any", improve_loop_module)._cherry_pick_prompt_commit(
            repo_root, commit_to_pick, expected_parent=head_before
        )

    content_after = (repo_root / "prompt_file.txt").read_text(encoding="utf-8")
    assert content_after == "original\n", "cherry-pick changes must be reverted"
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    assert head_after != commit_to_pick, "HEAD must not remain at the cherry-picked commit"


def _baseline_event_fixture(run_id: str, source_ref: str) -> Any:
    return _baseline_event(
        run_id=run_id,
        source_ref=source_ref,
        overall=70.0,
        weakest_dim="learnability",
    )
