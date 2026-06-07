from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from ahadiff import cli as cli_module
from ahadiff.cli import app
from ahadiff.contracts import ClaimRecord, ProviderConfig, ResultEvent, SourceHunk
from ahadiff.core.config import SecurityConfig, write_default_config
from ahadiff.core.errors import AhaDiffError
from ahadiff.eval.deterministic import DimensionScore
from ahadiff.eval.evaluator import ScoreReport
from ahadiff.eval.gates import HardGateResult, HardGateSummary
from ahadiff.eval.results import compute_prompt_version
from ahadiff.improve import regenerate as regenerate_module
from ahadiff.improve.preflight import assert_prompt_tuning_source_checkout
from ahadiff.improve.regenerate import run_regenerate
from ahadiff.lesson.generator import load_lesson_prompt
from ahadiff.llm import ProviderRequest, ProviderResponse
from ahadiff.review.database import (
    initialize_review_db,
    load_result_events_from_db,
    sync_result_event,
)

_RUNNER = CliRunner()


def _provider_config(*, max_output_tokens: int = 64_000) -> ProviderConfig:
    return ProviderConfig(
        provider_class="openai",
        model_name="gpt-5.4-mini",
        base_url="http://127.0.0.1:8318",
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        max_output_tokens=max_output_tokens,
    )


def _dimension_payload(overall: float) -> tuple[DimensionScore, ...]:
    learnability = max(0.0, min(14.0, overall - 60.0))
    values = {
        "accuracy": (18.0, 20.0),
        "evidence": (17.0, 18.0),
        "safety_privacy": (6.0, 6.0),
        "learnability": (learnability, 14.0),
        "diff_coverage": (10.0, 14.0),
        "quiz_transfer": (7.0, 10.0),
        "spec_alignment": (8.0, 10.0),
        "conciseness": (5.0, 8.0),
    }
    return tuple(
        DimensionScore(name=name, score=score, max_score=max_score, reason="fixture")
        for name, (score, max_score) in values.items()
    )


def _score_report(
    *,
    run_id: str,
    source_ref: str = "abc123",
    overall: float,
    weakest_dim: str = "learnability",
    hard_gate_failed: bool = False,
) -> ScoreReport:
    gates = (
        (HardGateResult(name="accuracy", passed=False, detail="fixture failure"),)
        if hard_gate_failed
        else ()
    )
    return ScoreReport(
        run_id=run_id,
        source_ref=source_ref,
        source_kind="git_ref",
        capability_level=3,
        degraded_flags={},
        overall=overall,
        verdict="FAIL" if hard_gate_failed else "PASS",
        weakest_dim=weakest_dim,
        eval_bundle_version="eval123",
        rubric_version="rubric-v1",
        dimensions=_dimension_payload(overall),
        hard_gates=HardGateSummary(results=gates),
        notes=(),
    )


def _score_payload(run_id: str, *, overall: float, weakest_dim: str = "learnability") -> str:
    report = _score_report(run_id=run_id, overall=overall, weakest_dim=weakest_dim)
    return json.dumps(report.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_run(workspace_root: Path, run_id: str, *, overall: float = 70.0) -> Path:
    run_path = workspace_root / ".ahadiff" / "runs" / run_id
    run_path.mkdir(parents=True)
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,4 @@
-def retry_once():
-    return 1
+def retry_once():
+    for attempt in range(3):
+        return attempt
"""
    metadata = {
        "run_id": run_id,
        "source_kind": "git_ref",
        "source_ref": "abc123",
        "base_ref": "base123",
        "capability_level": 3,
        "degraded_flags": {},
        "privacy_mode": "strict_local",
        "learnability": {"score": 0.6},
    }
    claim = ClaimRecord(
        claim_id="claim_retry_loop",
        run_id=run_id,
        text="The retry helper now loops over attempts.",
        status="verified",
        confidence="high",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=4, side="new")],
        symbols=["retry_once"],
    )
    (run_path / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text(patch, encoding="utf-8")
    (run_path / "line_map.json").write_text(
        json.dumps(
            [
                {
                    "file": "src/app.py",
                    "old_start": 1,
                    "old_count": 2,
                    "new_start": 1,
                    "new_count": 4,
                    "hunk_id": "hunk_retry",
                    "hunk_hash": "sha256:" + ("a" * 64),
                    "lines": [
                        {"old": 1, "new": 1, "kind": "context"},
                        {"old": None, "new": 2, "kind": "add"},
                    ],
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_path / "symbols.json").write_text("[]\n", encoding="utf-8")
    (run_path / "claims.jsonl").write_text(
        json.dumps(claim.model_dump(mode="json"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lesson_dir = run_path / "lesson"
    lesson_dir.mkdir()
    (lesson_dir / "lesson.full.md").write_text("## TL;DR\nBaseline lesson\n", encoding="utf-8")
    (lesson_dir / "lesson.hint.md").write_text("## Hint\nBaseline hint\n", encoding="utf-8")
    (lesson_dir / "lesson.compact.md").write_text(
        "## Compact\nBaseline compact\n",
        encoding="utf-8",
    )
    quiz_dir = run_path / "quiz"
    quiz_dir.mkdir()
    (quiz_dir / "quiz.jsonl").write_text(
        json.dumps(
            {
                "question_id": "q1",
                "run_id": run_id,
                "prompt": "Why does the loop matter?",
                "source_claims": ["claim_retry_loop"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_path / "score.json").write_text(
        _score_payload(run_id, overall=overall),
        encoding="utf-8",
    )
    (run_path / "finalized.json").write_text(
        json.dumps({"run_id": run_id, "event_id": "evt-baseline"}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_path


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _fake_generate_lessons_from_run(**kwargs: Any) -> None:
    run_path = Path(kwargs["run_path"])
    lesson_dir = run_path / "lesson"
    lesson_dir.mkdir(exist_ok=True)
    (lesson_dir / "lesson.full.md").write_text(
        "## TL;DR\nCandidate regenerated lesson\n",
        encoding="utf-8",
    )


def _sync_baseline_event(db_path: Path, run_id: str, *, prompt_version: str) -> None:
    sync_result_event(
        db_path,
        ResultEvent(
            event_id=f"evt-{run_id}",
            run_id=run_id,
            event_type="learn",
            timestamp="2026-05-01T00:00:00Z",
            source_ref="abc123",
            base_ref="base123",
            prompt_version=prompt_version,
            eval_bundle_version="eval123",
            rubric_version="rubric-v1",
            overall=70.0,
            verdict="PASS",
            status=cast("Any", "baseline"),
            weakest_dim="learnability",
            note_json=None,
        ),
    )


def test_run_regenerate_resolves_non_git_workspace_and_keeps_baseline_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "plain-project"
    workspace.mkdir()
    state_dir = workspace / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    baseline_path = _write_run(workspace, "run_base", overall=70.0)
    before = _snapshot_tree(baseline_path)
    seen_run_paths: list[Path] = []
    scores = [72.0, 76.0]

    def fake_evaluate_run(path: Path) -> ScoreReport:
        seen_run_paths.append(path)
        return _score_report(run_id=path.name, overall=scores.pop(0))

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        regenerate_module,
        "generate_lessons_from_run",
        _fake_generate_lessons_from_run,
    )
    monkeypatch.setattr(regenerate_module, "evaluate_run", fake_evaluate_run)

    result = run_regenerate(
        "run_base",
        candidates=2,
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
    )

    assert result.accepted_run_id is not None
    assert result.accepted_overall == 76.0
    assert result.baseline_overall == 70.0
    assert result.status == "accepted"
    assert (state_dir / "runs" / result.accepted_run_id).is_dir()
    assert before == _snapshot_tree(baseline_path)
    assert all(path.parent.parent == state_dir for path in seen_run_paths)
    events = load_result_events_from_db(state_dir / "review.sqlite")
    assert [event.run_id for event in events] == [result.accepted_run_id]
    assert events[0].event_type == "improve_run"
    assert events[0].status == "keep"
    accepted_score = json.loads(
        (state_dir / "runs" / result.accepted_run_id / "score.json").read_text(
            encoding="utf-8",
        )
    )
    assert accepted_score["overall"] == 76.0


def test_run_regenerate_persists_bundled_prompt_version_when_workspace_has_stray_prompts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "plain-project"
    workspace.mkdir()
    state_dir = workspace / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    _write_run(workspace, "run_base", overall=70.0)
    bundled_prompt_version = compute_prompt_version(tmp_path / "clean-source-checkout")
    _sync_baseline_event(
        state_dir / "review.sqlite",
        "run_base",
        prompt_version=bundled_prompt_version,
    )
    stray_prompts = workspace / "src" / "ahadiff" / "prompts"
    stray_prompts.mkdir(parents=True)
    (stray_prompts / "lesson_generate.md").write_text(
        "stray user workspace prompt bytes\n",
        encoding="utf-8",
    )
    stray_prompt_version = compute_prompt_version(workspace)
    assert stray_prompt_version != bundled_prompt_version

    def fake_evaluate_run(path: Path) -> ScoreReport:
        return _score_report(run_id=path.name, overall=72.0)

    monkeypatch.setattr(
        regenerate_module,
        "generate_lessons_from_run",
        _fake_generate_lessons_from_run,
    )
    monkeypatch.setattr(regenerate_module, "evaluate_run", fake_evaluate_run)

    result = run_regenerate(
        "run_base",
        candidates=1,
        workspace_root=workspace,
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
    )

    assert result.accepted_run_id is not None
    improve_events = [
        event
        for event in load_result_events_from_db(state_dir / "review.sqlite")
        if event.event_type == "improve_run"
    ]
    assert len(improve_events) == 1
    assert improve_events[0].prompt_version == bundled_prompt_version
    assert improve_events[0].prompt_version != stray_prompt_version


def test_run_regenerate_legacy_baseline_uses_bundled_prompt_version_with_stray_prompts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "plain-project"
    workspace.mkdir()
    state_dir = workspace / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    baseline_path = _write_run(workspace, "run_base", overall=70.0)
    score_path = baseline_path / "score.json"
    score_payload = json.loads(score_path.read_text(encoding="utf-8"))
    score_payload.pop("prompt_version", None)
    score_path.write_text(
        json.dumps(score_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert "prompt_version" not in score_payload
    assert load_result_events_from_db(state_dir / "review.sqlite") == ()
    bundled_prompt_version = compute_prompt_version(tmp_path / "clean-source-checkout")
    stray_prompts = workspace / "src" / "ahadiff" / "prompts"
    stray_prompts.mkdir(parents=True)
    (stray_prompts / "lesson_generate.md").write_text(
        "legacy baseline must not hash these workspace prompt bytes\n",
        encoding="utf-8",
    )
    stray_prompt_version = compute_prompt_version(workspace)
    assert stray_prompt_version != bundled_prompt_version

    def fake_evaluate_run(path: Path) -> ScoreReport:
        return _score_report(run_id=path.name, overall=72.0)

    monkeypatch.setattr(
        regenerate_module,
        "generate_lessons_from_run",
        _fake_generate_lessons_from_run,
    )
    monkeypatch.setattr(regenerate_module, "evaluate_run", fake_evaluate_run)

    result = run_regenerate(
        "run_base",
        candidates=1,
        workspace_root=workspace,
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
    )

    assert result.accepted_run_id is not None
    improve_events = [
        event
        for event in load_result_events_from_db(state_dir / "review.sqlite")
        if event.event_type == "improve_run"
    ]
    assert len(improve_events) == 1
    assert improve_events[0].prompt_version == bundled_prompt_version
    assert improve_events[0].prompt_version != stray_prompt_version


def test_run_regenerate_keeps_baseline_when_no_candidate_strictly_improves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "plain-project"
    workspace.mkdir()
    state_dir = workspace / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    _write_run(workspace, "run_base", overall=70.0)
    scores = [
        _score_report(run_id="candidate-a", overall=70.0),
        _score_report(run_id="candidate-b", overall=75.0, hard_gate_failed=True),
    ]

    def fake_evaluate_run(path: Path) -> ScoreReport:
        report = scores.pop(0)
        return _score_report(
            run_id=path.name,
            overall=report.overall,
            hard_gate_failed=not report.hard_gates.passed,
        )

    monkeypatch.setattr(
        regenerate_module,
        "generate_lessons_from_run",
        _fake_generate_lessons_from_run,
    )
    monkeypatch.setattr(regenerate_module, "evaluate_run", fake_evaluate_run)

    result = run_regenerate(
        "run_base",
        candidates=2,
        workspace_root=workspace,
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
    )

    assert result.accepted_run_id is None
    assert result.status == "no_improvement"
    assert result.message == "no improvement, baseline kept"
    assert sorted(path.name for path in (state_dir / "runs").iterdir()) == ["run_base"]
    assert load_result_events_from_db(state_dir / "review.sqlite") == ()


class _CapturingLessonProvider:
    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        if request.prompt_name == "lesson.hint":
            content = {
                "tl_dr": "The regenerated hint explains the retry loop.",
                "key_points": ["retry_once now iterates through attempts."],
                "watch_fors": ["This does not prove exponential backoff."],
                "claims": ["The helper loops over attempts."],
                "sources": ["src/app.py:new:1-4"],
            }
        elif request.prompt_name == "lesson.compact":
            content = {
                "headline": "Candidate compact retry lesson",
                "summary": ["retry_once now iterates through attempts."],
                "concepts": ["retry loop"],
                "sources": ["src/app.py:new:1-4"],
            }
        else:
            content = {
                "tl_dr": "The regenerated full lesson explains the retry loop.",
                "what_changed": ["retry_once now iterates through attempts."],
                "why": ["The diff adds control flow that repeats work."],
                "walkthrough": ["Read the new loop before the return statement."],
                "claims": ["The helper loops over attempts."],
                "concepts": ["retry loop"],
                "misconceptions": ["This does not prove backoff was added."],
                "not_proven": ["Runtime reliability is not measured by the diff."],
                "quiz": ["What does the added loop change?"],
                "sources": ["src/app.py:new:1-4"],
            }
        return ProviderResponse(
            content=json.dumps(content),
            model_id="gpt-5.4-mini",
            input_tokens=10,
            output_tokens=20,
        )

    def close(self) -> None:
        return None


def test_run_regenerate_keeps_default_lesson_prompt_metadata_and_adds_steering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "plain-project"
    workspace.mkdir()
    initialize_review_db(workspace / ".ahadiff" / "review.sqlite")
    _write_run(workspace, "run_base", overall=70.0)
    provider = _CapturingLessonProvider()

    def fake_make_provider(*args: object, **kwargs: object) -> _CapturingLessonProvider:
        del args, kwargs
        return provider

    def fake_evaluate_run(path: Path) -> ScoreReport:
        return _score_report(run_id=path.name, overall=72.0)

    monkeypatch.setattr("ahadiff.lesson.generator.make_provider", fake_make_provider)
    monkeypatch.setattr(regenerate_module, "evaluate_run", fake_evaluate_run)

    result = run_regenerate(
        "run_base",
        candidates=1,
        workspace_root=workspace,
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
    )

    assert result.accepted_run_id is not None
    assert [request.prompt_name for request in provider.requests] == [
        "lesson.generate",
        "lesson.hint",
        "lesson.compact",
    ]
    request = provider.requests[0]
    default_prompt = load_lesson_prompt("full")
    expected_fingerprint = hashlib.sha256(default_prompt.encode("utf-8")).hexdigest()[:12]
    assert request.prompt_name == "lesson.generate"
    assert request.prompt_fingerprint == expected_fingerprint
    assert request.prompt_version == expected_fingerprint
    assert "Prior weakest deterministic dimension: learnability" in request.payload_text
    assert "claim_retry_loop" in request.payload_text
    assert cast("int", request.max_output_tokens) > 24_000


def test_run_regenerate_scores_only_regenerated_lesson_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "plain-project"
    workspace.mkdir()
    initialize_review_db(workspace / ".ahadiff" / "review.sqlite")
    _write_run(workspace, "run_base", overall=70.0)

    def fake_generate_lessons_from_run(**kwargs: Any) -> None:
        run_path = Path(kwargs["run_path"])
        lesson_dir = run_path / "lesson"
        lesson_dir.mkdir(exist_ok=True)
        variants = cast("tuple[str, ...]", kwargs["lesson_variants"])
        for variant in variants:
            (lesson_dir / f"lesson.{variant}.md").write_text(
                f"## {variant.title()}\nCandidate regenerated {variant} lesson\n",
                encoding="utf-8",
            )

    def fake_evaluate_run(path: Path) -> ScoreReport:
        lesson_dir = path / "lesson"
        for variant in ("full", "hint", "compact"):
            text = (lesson_dir / f"lesson.{variant}.md").read_text(encoding="utf-8")
            assert "Candidate regenerated" in text
            assert "Baseline" not in text
        return _score_report(run_id=path.name, overall=72.0)

    monkeypatch.setattr(
        regenerate_module,
        "generate_lessons_from_run",
        fake_generate_lessons_from_run,
    )
    monkeypatch.setattr(regenerate_module, "evaluate_run", fake_evaluate_run)

    result = run_regenerate(
        "run_base",
        candidates=1,
        workspace_root=workspace,
        provider_config=_provider_config(),
        api_key=None,
        security_config=SecurityConfig(),
    )

    assert result.status == "accepted"


def test_run_regenerate_warns_when_full_output_cap_is_clamped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "plain-project"
    workspace.mkdir()
    initialize_review_db(workspace / ".ahadiff" / "review.sqlite")
    _write_run(workspace, "run_base", overall=70.0)

    def fake_generate_lessons_from_run(**kwargs: Any) -> None:
        caps = cast("dict[str, int]", kwargs["lesson_output_token_caps"])
        assert caps["full"] == 32_000
        _fake_generate_lessons_from_run(**kwargs)

    def fake_evaluate_run(path: Path) -> ScoreReport:
        return _score_report(run_id=path.name, overall=72.0)

    monkeypatch.setattr(
        regenerate_module,
        "generate_lessons_from_run",
        fake_generate_lessons_from_run,
    )
    monkeypatch.setattr(regenerate_module, "evaluate_run", fake_evaluate_run)

    result = run_regenerate(
        "run_base",
        candidates=1,
        workspace_root=workspace,
        provider_config=_provider_config(max_output_tokens=12_000),
        api_key=None,
        security_config=SecurityConfig(),
    )

    assert any(
        "full lesson output cap" in warning and "32000" in warning and "12000" in warning
        for warning in result.warnings
    )


def _run_git_fixture(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _init_git_repo(path: Path) -> None:
    _run_git_fixture(path, "init")
    _run_git_fixture(path, "config", "user.email", "test@example.com")
    _run_git_fixture(path, "config", "user.name", "Test User")


def _git_commit_all(path: Path, message: str) -> None:
    _run_git_fixture(path, "add", "-A")
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def test_prompt_tuning_preflight_fast_fails_when_prompt_dirs_absent(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _git_commit_all(repo_root, "tracked")

    with pytest.raises(AhaDiffError, match="prompt-tuning improve only runs inside"):
        assert_prompt_tuning_source_checkout(repo_root)


def test_improve_cli_routes_non_source_checkout_to_improve_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir()
    write_default_config(state_dir / "config.toml")
    (repo_root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _git_commit_all(repo_root, "tracked")

    def fail_provider_resolution(**kwargs: Any) -> tuple[ProviderConfig, None, str, bool]:
        del kwargs
        raise AssertionError("provider resolution must not run before prompt preflight")

    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", fail_provider_resolution)

    result = _RUNNER.invoke(
        app(),
        ["improve", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "prompt-tuning improve only runs inside an ahadiff source checkout" in result.stderr
    assert "ahadiff improve-run <run_id>" in result.stderr


def test_improve_run_cli_calls_run_regenerate_for_non_git_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "plain-project"
    workspace.mkdir()
    state_dir = workspace / ".ahadiff"
    state_dir.mkdir()
    write_default_config(state_dir / "config.toml")
    captured: dict[str, Any] = {}

    def fake_resolve_runtime_provider(**kwargs: Any) -> tuple[ProviderConfig, None, str, bool]:
        captured["provider_kwargs"] = kwargs
        return _provider_config(), None, "local", True

    def fake_run_regenerate(run_id: str, candidates: int, **kwargs: Any) -> SimpleNamespace:
        captured["run_id"] = run_id
        captured["candidates"] = candidates
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            baseline_run_id=run_id,
            accepted_run_id="run_candidate",
            baseline_overall=70.0,
            accepted_overall=73.0,
            weakest_dim="learnability",
            candidates=candidates,
            status="accepted",
            message="accepted regenerated lesson",
            event_id="evt_candidate",
            warnings=(),
        )

    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", fake_resolve_runtime_provider)
    monkeypatch.setattr(cli_module, "run_regenerate", fake_run_regenerate)

    result = _RUNNER.invoke(
        app(),
        [
            "improve-run",
            "run_base",
            "--candidates",
            "2",
            "--repo-root",
            str(workspace),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["run_id"] == "run_base"
    assert captured["candidates"] == 2
    assert captured["kwargs"]["workspace_root"] == workspace
    assert captured["kwargs"]["state_dir"] == state_dir
    assert captured["kwargs"]["output_lang"] == "en"
    assert "Accepted run" in result.stdout
