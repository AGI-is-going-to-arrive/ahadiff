"""Tests for ``ahadiff.core.orchestrator`` — LearnRequest, LearnResult, run_learn_pipeline."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from ahadiff.core.errors import AhaDiffError
from ahadiff.core.orchestrator import LearnRequest, LearnResult, run_learn_pipeline

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------


def test_learn_request_defaults(tmp_path: Path) -> None:
    req = LearnRequest(workspace_root=tmp_path)
    assert req.workspace_root == tmp_path
    assert req.revision is None
    assert req.last is False
    assert req.since is None
    assert req.author is None
    assert req.staged is False
    assert req.unstaged is False
    assert req.include_untracked is False
    assert req.patch is None
    assert req.compare is None
    assert req.compare_dir is None
    assert req.patch_url is None
    assert req.provider_name is None
    assert req.provider_class == "openai"
    assert req.base_url is None
    assert req.model is None
    assert req.api_key_env == "AHADIFF_PROVIDER_API_KEY"
    assert req.dry_run is False
    assert req.force_learn is False
    assert req.use_graphify is None
    assert req.lang is None
    assert req.privacy_mode is None


def test_learn_result_defaults() -> None:
    res = LearnResult(run_id="r-001", status="completed")
    assert res.run_id == "r-001"
    assert res.status == "completed"
    assert res.overall is None
    assert res.verdict is None
    assert res.weakest_dim is None
    assert res.artifacts_path is None
    assert res.warnings == []
    assert res.learnability_score is None
    assert res.learnability_skip is False


def test_learn_result_warnings_isolation() -> None:
    """Each LearnResult instance should get its own warnings list."""
    r1 = LearnResult(run_id="a", status="ok")
    r2 = LearnResult(run_id="b", status="ok")
    r1.warnings.append("w1")
    assert r2.warnings == []


# ---------------------------------------------------------------------------
# Fake objects for mocking the pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeLearnabilityFactors:
    complexity: float = 0.5
    novelty: float = 0.5
    pattern: float = 0.5

    def as_dict(self) -> dict[str, float]:
        return {"complexity": self.complexity, "novelty": self.novelty, "pattern": self.pattern}


@dataclass(frozen=True)
class _FakeLearnabilityWeights:
    def model_dump(self, *, mode: str = "json") -> dict[str, float]:
        return {"complexity": 0.4, "novelty": 0.3, "pattern": 0.3}


@dataclass(frozen=True)
class _FakeLearnabilityAssessment:
    score: float = 0.8
    threshold: float = 0.3
    skip_lesson_quiz: bool = False
    forced: bool = False
    factors: _FakeLearnabilityFactors = field(default_factory=_FakeLearnabilityFactors)
    weights: _FakeLearnabilityWeights = field(default_factory=_FakeLearnabilityWeights)
    reasons: tuple[str, ...] = ()

    def as_metadata(self) -> dict[str, object]:
        return {
            "score": self.score,
            "threshold": self.threshold,
            "skip_lesson_quiz": self.skip_lesson_quiz,
            "forced": self.forced,
            "factors": self.factors.as_dict(),
            "weights": self.weights.model_dump(mode="json"),
            "reasons": list(self.reasons),
        }


class _FakeRunSource:
    source_kind: str = "git_ref"
    source_ref: str = "abc123"


class _FakeCapture:
    def __init__(self, run_id: str = "run-test-001", *, state_dir: Path | None = None) -> None:
        self.run_id = run_id
        self.state_dir = state_dir or Path(".ahadiff")
        self.persisted_patch_text = "diff --git a/a.py b/a.py\n+print('hello')\n"
        self.metadata: dict[str, Any] = {}
        self.run_source = _FakeRunSource()


class _FakeConfigSnapshot:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {
            "capture": {
                "max_files": 50,
                "hard_limit": 100,
                "max_patch_bytes": 500_000,
            },
            "learn": {"learnability_threshold": 0.3},
            "llm": {
                "generate_model": "test-model",
                "output_lang": "auto",
                "max_concurrent": 2,
                "retry_attempts": 3,
                "request_timeout_seconds": 30,
            },
            "provider": {"qps_limit": 10},
            "privacy_mode": "strict_local",
            "lang": "en",
        }


@dataclass(frozen=True)
class _FakeSecurityConfig:
    local_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")
    strict_local_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")


@dataclass(frozen=True)
class _FakeProviderConfig:
    base_url: str = "http://localhost:11434"
    api_key_env: str = "FAKE_KEY"
    provider_class: str = "ollama"


# ---------------------------------------------------------------------------
# Shared fixture: set up a fake git repo + .ahadiff dir
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    """Create a minimal fake git repo so find_repo_root succeeds."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".ahadiff").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Module paths for monkeypatch (local imports in orchestrator)
# ---------------------------------------------------------------------------
# The orchestrator does `from ahadiff.git.capture import capture_patch` etc.
# inside function bodies.  monkeypatch must target the *source* module.

_ORCH = "ahadiff.core.orchestrator"  # module-level names (config, paths, etc.)
_GIT_CAPTURE = "ahadiff.git.capture"
_GIT_REPO = "ahadiff.git.repo"
_LEARNABILITY = "ahadiff.lesson.learnability"
_CLAIMS_RUNTIME = "ahadiff.claims.runtime"
_CLAIMS_EXTRACT = "ahadiff.claims.extract"
_CLAIMS_VERIFY = "ahadiff.claims.verify"
_EVAL_RATCHET = "ahadiff.eval.ratchet"
_EVAL_RESULTS = "ahadiff.eval.results"


@contextmanager
def _fake_repo_write_lock(path: Path, command: str = "") -> Generator[None]:
    yield None


def _patch_config_and_paths(monkeypatch: pytest.MonkeyPatch, fake_repo: Path) -> None:
    """Patch Step 1: config loading + path resolution (module-level imports)."""

    def _find_repo_root(_path: Path) -> Path:
        return fake_repo

    def _find_workspace_root(_path: Path) -> Path:
        return fake_repo

    def _assert_local_repo_path(_path: Path) -> None:
        return None

    def _lock_file_path(_path: Path) -> Path:
        return fake_repo / ".ahadiff" / "ahadiff.lock"

    def _run_dir(run_id: str, _root: Path) -> Path:
        return fake_repo / ".ahadiff" / "runs" / run_id

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        return _FakeConfigSnapshot()

    def _load_security_config(_root: Path) -> _FakeSecurityConfig:
        return _FakeSecurityConfig()

    def _resolve_locale(**kwargs: object) -> str:
        return "en"

    monkeypatch.setattr(f"{_ORCH}.find_repo_root", _find_repo_root)
    monkeypatch.setattr(f"{_ORCH}.find_workspace_root", _find_workspace_root)
    monkeypatch.setattr(f"{_ORCH}.assert_local_repo_path", _assert_local_repo_path)
    monkeypatch.setattr(f"{_ORCH}.lock_file_path", _lock_file_path)
    monkeypatch.setattr(f"{_ORCH}.run_dir", _run_dir)
    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    monkeypatch.setattr(f"{_ORCH}.load_security_config", _load_security_config)
    monkeypatch.setattr(f"{_ORCH}.resolve_locale", _resolve_locale)


def _patch_capture(monkeypatch: pytest.MonkeyPatch, fake_repo: Path) -> _FakeCapture:
    """Patch Step 2: capture_patch + write_input_artifacts (local imports)."""
    capture = _FakeCapture(state_dir=fake_repo / ".ahadiff")

    def _capture_patch(**kwargs: object) -> _FakeCapture:
        return capture

    def _write_input_artifacts(_capture: _FakeCapture) -> None:
        return None

    monkeypatch.setattr(f"{_GIT_CAPTURE}.capture_patch", _capture_patch)
    monkeypatch.setattr(f"{_GIT_CAPTURE}.write_input_artifacts", _write_input_artifacts)
    monkeypatch.setattr(f"{_GIT_REPO}.repo_write_lock", _fake_repo_write_lock)
    return capture


def _patch_learnability(
    monkeypatch: pytest.MonkeyPatch,
    *,
    score: float = 0.7,
    skip: bool = False,
) -> None:
    """Patch Step 3: assess_learnability (local import)."""

    def _assess_learnability(
        _text: str,
        threshold: float = 0.3,
        force_learn: bool = False,
    ) -> _FakeLearnabilityAssessment:
        return _FakeLearnabilityAssessment(
            score=score,
            skip_lesson_quiz=skip,
        )

    monkeypatch.setattr(
        f"{_LEARNABILITY}.assess_learnability",
        _assess_learnability,
    )


def _patch_completed_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
    capture: _FakeCapture,
    *,
    on_generate_cards: Callable[[], None] | None = None,
    on_persist: Callable[[Path], None] | None = None,
) -> None:
    def _resolve_provider_from_config(
        **kwargs: object,
    ) -> tuple[_FakeProviderConfig, str, str, bool]:
        return _FakeProviderConfig(), "key", "local", False

    monkeypatch.setattr(
        f"{_ORCH}._resolve_provider_from_config",
        _resolve_provider_from_config,
    )

    @dataclass
    class _FakeVerifiedRecord:
        status: str = "verified"

    @dataclass
    class _FakeVerifiedClaim:
        record: _FakeVerifiedRecord = field(default_factory=_FakeVerifiedRecord)

    def _extract_claim_candidates_from_run(**kw: object) -> tuple[Path, int]:
        output_path = fake_repo / ".ahadiff" / "runs" / capture.run_id / "claims.raw.jsonl"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}\n", encoding="utf-8")
        return output_path, 1

    def _write_verified_claims_jsonl(
        output_path: Path,
        verified: object,
        overwrite: bool = False,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        f"{_CLAIMS_RUNTIME}.extract_claim_candidates_from_run",
        _extract_claim_candidates_from_run,
    )

    def _load_claim_candidates(_path: Path, **kwargs: object) -> list[str]:
        return ["claim"]

    def _load_line_map_records(_path: Path) -> list[object]:
        return []

    def _load_symbol_records(_path: Path) -> list[object]:
        return []

    def _load_text_map(_path: Path, expected_artifact: str = "") -> dict[str, str]:
        return {}

    def _verify_claim_candidates(
        _candidates: object,
        **kwargs: object,
    ) -> list[_FakeVerifiedClaim]:
        return [_FakeVerifiedClaim()]

    def _generate_lessons_from_run(**kwargs: object) -> None:
        return None

    def _generate_quiz_from_run(**kwargs: object) -> tuple[Path, list[object]]:
        return fake_repo / ".ahadiff" / "runs" / capture.run_id / "quiz.json", []

    def _evaluate_run(_run_path: Path) -> MagicMock:
        return fake_report

    monkeypatch.setattr(f"{_CLAIMS_EXTRACT}.load_claim_candidates", _load_claim_candidates)
    monkeypatch.setattr(f"{_CLAIMS_EXTRACT}.load_line_map_records", _load_line_map_records)
    monkeypatch.setattr(f"{_CLAIMS_EXTRACT}.load_symbol_records", _load_symbol_records)
    monkeypatch.setattr(f"{_CLAIMS_EXTRACT}.load_text_map", _load_text_map)
    monkeypatch.setattr(
        f"{_CLAIMS_VERIFY}.verify_claim_candidates",
        _verify_claim_candidates,
    )
    monkeypatch.setattr(
        f"{_CLAIMS_EXTRACT}.write_verified_claims_jsonl",
        _write_verified_claims_jsonl,
    )

    monkeypatch.setattr(
        "ahadiff.lesson.generator.generate_lessons_from_run",
        _generate_lessons_from_run,
    )
    monkeypatch.setattr(
        "ahadiff.quiz.generator.generate_quiz_from_run",
        _generate_quiz_from_run,
    )

    def _generate_cards_for_run(**kw: object) -> None:
        if on_generate_cards is not None:
            on_generate_cards()

    monkeypatch.setattr("ahadiff.quiz.generator.generate_cards_for_run", _generate_cards_for_run)

    fake_report = MagicMock()
    fake_report.overall = 91.0
    fake_report.verdict = "PASS"
    fake_report.weakest_dim = "safety"
    monkeypatch.setattr("ahadiff.eval.evaluator.evaluate_run", _evaluate_run)

    def _persist(
        *,
        run_path: Path,
        report: object,
        workspace_root: Path,
        event_type: str,
        output_path: Path,
        force: bool,
        note_payload: dict[str, object] | None = None,
    ) -> tuple[object, list[str]]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if on_persist is not None:
            on_persist(run_path)
        fake_event = MagicMock()
        fake_event.status = "keep"
        fake_event.event_id = "evt-001"
        fake_outcome = MagicMock()
        fake_outcome.event = fake_event
        return fake_outcome, []

    monkeypatch.setattr(f"{_ORCH}._persist_evaluated_run_sync", _persist)

    def _register_repo(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("ahadiff.core.registry.register_repo", _register_repo)


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------


def test_dry_run_returns_early(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    register_calls: list[tuple[Path, Path]] = []

    def _register_repo(root: Path, state_dir: Path) -> None:
        register_calls.append((root, state_dir))

    monkeypatch.setattr(
        "ahadiff.core.registry.register_repo",
        _register_repo,
    )

    req = LearnRequest(workspace_root=fake_repo, dry_run=True)
    result = run_learn_pipeline(req)

    assert result.status == "dry_run"
    assert result.learnability_score == 0.7
    assert result.overall is None  # no eval happened
    assert register_calls == [(fake_repo, fake_repo / ".ahadiff")]


def test_learnability_skip_returns_early(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.1, skip=True)
    register_calls: list[tuple[Path, Path]] = []

    def _register_repo(root: Path, state_dir: Path) -> None:
        register_calls.append((root, state_dir))

    monkeypatch.setattr(
        "ahadiff.core.registry.register_repo",
        _register_repo,
    )

    req = LearnRequest(workspace_root=fake_repo)
    result = run_learn_pipeline(req)

    assert result.status == "learnability_skip"
    assert result.learnability_skip is True
    assert result.overall is None
    assert register_calls == [(fake_repo, fake_repo / ".ahadiff")]


def test_cancellation_raises_error(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    """Providing an is_cancelled that returns True should raise AhaDiffError('cancelled')."""
    _patch_config_and_paths(monkeypatch, fake_repo)

    req = LearnRequest(workspace_root=fake_repo)
    with pytest.raises(AhaDiffError, match="cancelled"):
        run_learn_pipeline(req, is_cancelled=lambda: True)


def test_progress_callback_called(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    """on_progress should be called with (step, 10, message) tuples."""
    _patch_config_and_paths(monkeypatch, fake_repo)
    _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)

    collected: list[tuple[int, int, str]] = []

    def _track(step: int, total: int, msg: str) -> None:
        collected.append((step, total, msg))

    req = LearnRequest(workspace_root=fake_repo, dry_run=True)
    run_learn_pipeline(req, on_progress=_track)

    # dry_run exits after step 3 (capture + learnability)
    steps_seen = [s for s, _t, _m in collected]
    assert 1 in steps_seen
    assert 2 in steps_seen
    assert 3 in steps_seen
    # All totals should be 10
    assert all(t == 10 for _s, t, _m in collected)


def test_no_verified_claims_skip(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    """When claim verification produces 0 verified claims, pipeline returns early."""
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    register_calls: list[tuple[Path, Path]] = []

    def _register_repo(root: Path, state_dir: Path) -> None:
        register_calls.append((root, state_dir))

    monkeypatch.setattr(
        "ahadiff.core.registry.register_repo",
        _register_repo,
    )

    # Step 4: provider resolution (orchestrator internal helper, module-level)
    def _resolve_provider_from_config(
        **kwargs: object,
    ) -> tuple[_FakeProviderConfig, str, str, bool]:
        return _FakeProviderConfig(), "key", "local", False

    monkeypatch.setattr(
        f"{_ORCH}._resolve_provider_from_config",
        _resolve_provider_from_config,
    )

    # Step 5: claims — produce 0 verified
    @dataclass
    class _FakeClaimRecord:
        status: str = "not_proven"

    @dataclass
    class _FakeVerifiedClaim:
        record: _FakeClaimRecord = field(default_factory=_FakeClaimRecord)

    def _extract_claim_candidates_from_run(**kwargs: object) -> tuple[Path, int]:
        return fake_repo / ".ahadiff" / "runs" / capture.run_id / "claims.raw.jsonl", 3

    def _load_claim_candidates(_path: Path, **kwargs: object) -> list[object]:
        return []

    def _load_line_map_records(_path: Path) -> list[object]:
        return []

    def _load_symbol_records(_path: Path) -> list[object]:
        return []

    def _load_text_map(_path: Path, expected_artifact: str = "") -> dict[str, str]:
        return {}

    def _verify_claim_candidates(
        _candidates: object,
        **kwargs: object,
    ) -> list[_FakeVerifiedClaim]:
        return [_FakeVerifiedClaim()]

    def _write_verified_claims_jsonl(
        _path: Path,
        _verified: object,
        overwrite: bool = False,
    ) -> None:
        return None

    monkeypatch.setattr(
        f"{_CLAIMS_RUNTIME}.extract_claim_candidates_from_run",
        _extract_claim_candidates_from_run,
    )
    monkeypatch.setattr(f"{_CLAIMS_EXTRACT}.load_claim_candidates", _load_claim_candidates)
    monkeypatch.setattr(f"{_CLAIMS_EXTRACT}.load_line_map_records", _load_line_map_records)
    monkeypatch.setattr(f"{_CLAIMS_EXTRACT}.load_symbol_records", _load_symbol_records)
    monkeypatch.setattr(f"{_CLAIMS_EXTRACT}.load_text_map", _load_text_map)
    monkeypatch.setattr(
        f"{_CLAIMS_VERIFY}.verify_claim_candidates",
        _verify_claim_candidates,
    )
    monkeypatch.setattr(
        f"{_CLAIMS_EXTRACT}.write_verified_claims_jsonl",
        _write_verified_claims_jsonl,
    )

    req = LearnRequest(workspace_root=fake_repo)
    result = run_learn_pipeline(req)

    assert result.status == "no_verified_claims"
    assert "no verified claims" in result.warnings[0]
    assert register_calls == [(fake_repo, fake_repo / ".ahadiff")]


def test_cancellation_before_persist_skips_finalized_and_result_events(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)

    cancelled = False
    persist_called = False
    append_called = False
    run_path = fake_repo / ".ahadiff" / "runs" / capture.run_id
    finalized_path = run_path / "finalized.json"
    score_path = run_path / "score.json"

    def _cancel_after_cards() -> None:
        nonlocal cancelled
        cancelled = True

    def _persist(*args: object, **kwargs: object) -> tuple[object, list[str]]:
        nonlocal persist_called
        persist_called = True
        finalized_path.parent.mkdir(parents=True, exist_ok=True)
        finalized_path.write_text("{}\n", encoding="utf-8")
        score_path.write_text("{}\n", encoding="utf-8")
        return MagicMock(), []

    def _append_concepts(**kwargs: object) -> Path:
        nonlocal append_called
        append_called = True
        output_path = run_path / "concepts_local.jsonl"
        output_path.write_text("{}\n", encoding="utf-8")
        return output_path

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_generate_cards=_cancel_after_cards,
    )
    monkeypatch.setattr(f"{_ORCH}._persist_evaluated_run_sync", _persist)
    monkeypatch.setattr("ahadiff.wiki.concepts.append_concepts", _append_concepts)

    req = LearnRequest(workspace_root=fake_repo)
    with pytest.raises(AhaDiffError, match="cancelled"):
        run_learn_pipeline(req, is_cancelled=lambda: cancelled)

    assert persist_called is False
    assert append_called is False
    assert not finalized_path.exists()
    assert not score_path.exists()
    assert not (fake_repo / ".ahadiff" / "review.sqlite").exists()


def test_cancellation_after_persist_skips_append_concepts(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)

    cancelled = False
    append_called = False
    run_path = fake_repo / ".ahadiff" / "runs" / capture.run_id
    finalized_path = run_path / "finalized.json"
    score_path = run_path / "score.json"

    def _persist_and_cancel(current_run_path: Path) -> None:
        nonlocal cancelled
        current_run_path.mkdir(parents=True, exist_ok=True)
        finalized_path.write_text("{}\n", encoding="utf-8")
        score_path.write_text("{}\n", encoding="utf-8")
        cancelled = True

    def _append_concepts(**kwargs: object) -> Path:
        nonlocal append_called
        append_called = True
        output_path = run_path / "concepts_local.jsonl"
        output_path.write_text("{}\n", encoding="utf-8")
        return output_path

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_persist=_persist_and_cancel,
    )
    monkeypatch.setattr("ahadiff.wiki.concepts.append_concepts", _append_concepts)

    req = LearnRequest(workspace_root=fake_repo)
    with pytest.raises(AhaDiffError, match="cancelled"):
        run_learn_pipeline(req, is_cancelled=lambda: cancelled)

    assert finalized_path.exists()
    assert score_path.exists()
    assert append_called is False
    assert not (run_path / "concepts_local.jsonl").exists()


def test_persist_evaluated_run_rollback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """_persist_evaluated_run_sync should rollback on publish failure."""
    import ahadiff.core.orchestrator as orchestrator_module

    _persist_evaluated_run_sync = cast(
        "Callable[..., tuple[Any, list[str]]]",
        vars(orchestrator_module)["_persist_evaluated_run_sync"],
    )

    fake_report = MagicMock()
    fake_report.overall = 85.0
    fake_report.verdict = "PASS"

    fake_decision = MagicMock()
    fake_decision.status = "keep"
    fake_decision.base_ref = "base123"
    fake_decision.note_payload = None

    fake_event = MagicMock()
    fake_event.event_id = "evt-001"

    fake_outcome = MagicMock()
    fake_outcome.event = fake_event
    fake_outcome.warnings = []
    fake_outcome.sqlite_inserted = True

    run_path = tmp_path / ".ahadiff" / "runs" / "r-001"
    run_path.mkdir(parents=True)

    rollback_called = False

    def _mock_rollback(*, run_path: Path, event_id: str) -> None:
        nonlocal rollback_called
        rollback_called = True

    # _persist_evaluated_run_sync does local imports from eval.ratchet / eval.results
    def _decide_learn_ratchet(**kwargs: object) -> MagicMock:
        return fake_decision

    def _load_result_events(_path: Path) -> list[object]:
        return []

    def _append_result(**kwargs: object) -> MagicMock:
        return fake_outcome

    monkeypatch.setattr(f"{_EVAL_RATCHET}.decide_learn_ratchet", _decide_learn_ratchet)
    monkeypatch.setattr(f"{_EVAL_RESULTS}.load_result_events", _load_result_events)
    monkeypatch.setattr(f"{_EVAL_RESULTS}.append_result", _append_result)
    monkeypatch.setattr(
        f"{_EVAL_RESULTS}.publish_result_artifacts",
        MagicMock(side_effect=OSError("disk full")),
    )
    monkeypatch.setattr(f"{_EVAL_RESULTS}.rollback_result_event", _mock_rollback)

    with pytest.raises(AhaDiffError, match="failed to publish score artifacts"):
        _persist_evaluated_run_sync(
            run_path=run_path,
            report=fake_report,
            workspace_root=tmp_path,
            event_type="learn",
            output_path=run_path / "score.json",
            force=False,
        )

    assert rollback_called
    assert not (run_path / "finalized.json").exists()
    assert not (run_path / "score.json").exists()


def test_register_repo_failure_becomes_warning(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    _patch_completed_pipeline(monkeypatch, fake_repo, capture)

    def _raise_register_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr("ahadiff.core.registry.register_repo", _raise_register_error)

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert "registry auto-register failed: registry unavailable" in result.warnings


def test_dry_run_preserves_register_repo_warning(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)

    def _raise_register_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr("ahadiff.core.registry.register_repo", _raise_register_error)

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo, dry_run=True))

    assert result.status == "dry_run"
    assert "registry auto-register failed: registry unavailable" in result.warnings


__all__: list[str] = []
