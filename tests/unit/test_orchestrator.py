"""Tests for ``ahadiff.core.orchestrator`` — LearnRequest, LearnResult, run_learn_pipeline."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

import ahadiff.core.orchestrator as orchestrator_module
from ahadiff.core.config import ResolvedSetting
from ahadiff.core.errors import AhaDiffError, ConfigError, SafetyError
from ahadiff.core.orchestrator import (
    LearnRequest,
    LearnResult,
    PipelineErrorBudget,
    _bounded_judge_failure_message,  # pyright: ignore[reportPrivateUsage]
    _effective_capture_recommendation,  # pyright: ignore[reportPrivateUsage]
    _persist_graphify_context,  # pyright: ignore[reportPrivateUsage]
    _persist_skipped_run,  # pyright: ignore[reportPrivateUsage]
    _resolve_provider_from_config,  # pyright: ignore[reportPrivateUsage]
    is_recoverable_error,
    is_timeout_or_network_error,
    run_learn_pipeline,
    run_with_retry,
)
from ahadiff.git.capture import GraphifyStatus, graphify_signoff_payload_from_capture
from ahadiff.lesson.schemas import LessonHint

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
    assert req.against_spec is None
    assert req.spec_semantic_review is False
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
    assert req.quiz_mode is None


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
    assert res.recoverable_errors == 0


def test_learn_result_warnings_isolation() -> None:
    """Each LearnResult instance should get its own warnings list."""
    r1 = LearnResult(run_id="a", status="ok")
    r2 = LearnResult(run_id="b", status="ok")
    r1.warnings.append("w1")
    assert r2.warnings == []


def test_resolve_provider_allows_duplicate_implicit_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serve cannot pass --provider, so duplicate aliases should not block learn."""
    snapshot = _FakeConfigSnapshot()
    snapshot.values["providers"] = {
        "local8318": {
            "provider_class": "openai",
            "model_name": "gpt-5.4-mini",
            "base_url": "http://127.0.0.1:8318",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
            "probed_max_context": 1_000_000,
            "probe_timestamp": "2026-04-22T19:31:25Z",
        },
        "smoke-test": {
            "provider_class": "openai",
            "model_name": "gpt-5.4-mini",
            "base_url": "http://127.0.0.1:8318/v1/chat/completions",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
            "probed_max_context": 1_000_000,
            "probe_timestamp": "2026-04-22T21:37:44Z",
        },
    }
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    provider_config, api_key, transport_target, explicit = _resolve_provider_from_config(
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )

    assert provider_config.base_url == "http://127.0.0.1:8318"
    assert api_key == "test-key"
    assert transport_target == "local"
    assert explicit is False


def test_resolve_provider_keeps_distinct_implicit_aliases_ambiguous() -> None:
    snapshot = _FakeConfigSnapshot()
    snapshot.values["providers"] = {
        "first": {
            "provider_class": "openai",
            "model_name": "gpt-5.4-mini",
            "base_url": "http://127.0.0.1:8318",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
        },
        "second": {
            "provider_class": "openai",
            "model_name": "gpt-5.4-mini",
            "base_url": "http://127.0.0.1:9321",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
        },
    }

    with pytest.raises(AhaDiffError, match="requires --provider.*when multiple providers"):
        _resolve_provider_from_config(
            snapshot=snapshot,
            operation_label="lesson generation",
            provider_name=None,
            provider_class="openai",
            base_url=None,
            model=None,
            api_key_env="AHADIFF_PROVIDER_API_KEY",
            privacy_mode="strict_local",
            local_hosts=("127.0.0.1",),
            strict_local_hosts=("127.0.0.1",),
        )


def test_resolve_provider_uses_configured_role_model_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _FakeConfigSnapshot()
    snapshot.values["llm"]["generate_provider"] = "gpt"
    snapshot.values["llm"]["generate_model"] = "gpt-5.5"
    snapshot.values["providers"] = {
        "gpt": {
            "provider_class": "openai",
            "model_name": "provider-default-model",
            "base_url": "http://127.0.0.1:8318",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
        }
    }
    snapshot.resolved = {
        "llm.generate_model": ResolvedSetting(
            key="llm.generate_model",
            value="gpt-5.5",
            source="repo:/tmp/repo/.ahadiff/config.toml",
        )
    }
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    provider_config, _, _, _ = _resolve_provider_from_config(
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )

    assert provider_config.model_name == "gpt-5.5"


def test_resolve_provider_treats_single_configured_remote_as_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _FakeConfigSnapshot()
    snapshot.values["llm"]["generate_model"] = "gpt-5.5"
    snapshot.values["providers"] = {
        "gpt55": {
            "provider_class": "openai_responses",
            "model_name": "gpt-5.5",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
        }
    }
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    provider_config, api_key, transport_target, explicit = _resolve_provider_from_config(
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )

    assert provider_config.model_name == "gpt-5.5"
    assert api_key == "test-key"
    assert transport_target == "remote"
    assert explicit is True


def test_resolve_provider_uses_role_models_with_single_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _FakeConfigSnapshot()
    snapshot.values["llm"]["generate_model"] = "learn-model"
    snapshot.values["llm"]["judge_model"] = "judge-model"
    snapshot.values["providers"] = {
        "gpt": {
            "provider_class": "openai_responses",
            "model_name": "provider-default",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
            "available_models": ("learn-model", "judge-model"),
        }
    }
    snapshot.resolved = {
        "llm.generate_model": ResolvedSetting(
            key="llm.generate_model",
            value="learn-model",
            source="repo:/tmp/repo/.ahadiff/config.toml",
        ),
        "llm.judge_model": ResolvedSetting(
            key="llm.judge_model",
            value="judge-model",
            source="repo:/tmp/repo/.ahadiff/config.toml",
        ),
    }
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    generate_config, _, _, generate_explicit = _resolve_provider_from_config(
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )
    judge_config, _, _, judge_explicit = _resolve_provider_from_config(
        snapshot=snapshot,
        operation_label="LLM judge evaluation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
        role="judge",
    )

    assert generate_config.model_name == "learn-model"
    assert judge_config.model_name == "judge-model"
    assert generate_explicit is True
    assert judge_explicit is True


def test_resolve_provider_keeps_single_provider_model_for_default_llm_model() -> None:
    snapshot = _FakeConfigSnapshot()
    snapshot.values["llm"]["generate_model"] = "gpt-default-from-config-schema"
    snapshot.values["providers"] = {
        "local": {
            "provider_class": "openai",
            "model_name": "provider-model",
            "base_url": "http://127.0.0.1:8318",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
        }
    }
    snapshot.resolved = {
        "llm.generate_model": ResolvedSetting(
            key="llm.generate_model",
            value="gpt-default-from-config-schema",
            source="default",
        )
    }

    provider_config, _, transport_target, explicit = _resolve_provider_from_config(
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )

    assert provider_config.model_name == "provider-model"
    assert transport_target == "local"
    assert explicit is False


def test_resolve_provider_uses_configured_generate_provider_with_multiple_remotes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _FakeConfigSnapshot()
    snapshot.values["llm"]["generate_provider"] = "gpt"
    snapshot.values["llm"]["generate_model"] = "gpt-5.5"
    snapshot.values["providers"] = {
        "azure": {
            "provider_class": "azure",
            "model_name": "gpt-5.5-2026-04-24",
            "base_url": "https://example.openai.azure.com/openai/deployments/gpt",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
        },
        "gpt": {
            "provider_class": "openai_responses",
            "model_name": "gpt-5.5",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
        },
    }
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    provider_config, api_key, transport_target, explicit = _resolve_provider_from_config(
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )

    assert provider_config.provider_class == "openai_responses"
    assert provider_config.model_name == "gpt-5.5"
    assert api_key == "test-key"
    assert transport_target == "remote"
    assert explicit is True


def test_resolve_provider_uses_configured_judge_provider_with_multiple_remotes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _FakeConfigSnapshot()
    snapshot.values["llm"]["judge_provider"] = "azure"
    snapshot.values["llm"]["judge_model"] = "gpt-5.5-2026-04-24"
    snapshot.values["providers"] = {
        "azure": {
            "provider_class": "azure",
            "model_name": "provider-default",
            "base_url": "https://example.openai.azure.com/openai/deployments/gpt",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
        },
        "gpt": {
            "provider_class": "openai_responses",
            "model_name": "gpt-5.5",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
        },
    }
    snapshot.resolved = {
        "llm.judge_model": ResolvedSetting(
            key="llm.judge_model",
            value="gpt-5.5-2026-04-24",
            source="repo:/tmp/repo/.ahadiff/config.toml",
        )
    }
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    provider_config, api_key, transport_target, explicit = _resolve_provider_from_config(
        snapshot=snapshot,
        operation_label="LLM judge evaluation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
        role="judge",
    )

    assert provider_config.provider_class == "azure"
    assert provider_config.model_name == "gpt-5.5-2026-04-24"
    assert api_key == "test-key"
    assert transport_target == "remote"
    assert explicit is True


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
            "learn": {"learnability_threshold": 0.3, "desired_retention": 0.9},
            "quiz": {
                "quiz_question_count": 3,
                "quiz_question_count_mode": "fixed",
                "quiz_auto_range_min": 3,
                "quiz_auto_range_max": 12,
            },
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
        self.resolved: dict[str, ResolvedSetting] = {}


@dataclass(frozen=True)
class _FakeSecurityConfig:
    local_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")
    strict_local_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")


@dataclass(frozen=True)
class _FakeProviderConfig:
    base_url: str = "http://localhost:11434"
    api_key_env: str = "FAKE_KEY"
    provider_class: str = "ollama"
    model_name: str = "fake-model"
    max_output_tokens: int | None = None

    def model_copy(self, *, update: dict[str, object]) -> _FakeProviderConfig:
        return replace(self, **update)


def _fake_graphify_capture(tmp_path: Path) -> _FakeCapture:
    capture = _FakeCapture(run_id="run-graphify", state_dir=tmp_path / ".ahadiff")
    capture.graphify_status = GraphifyStatus(  # type: ignore[attr-defined]
        source_path=tmp_path / "graphify-out" / "graph.json",
        imported_path=tmp_path / ".ahadiff" / "graphify" / "graph.json",
        enabled=True,
        source_exists=True,
        imported_exists=True,
        has_graph=True,
        freshness="fresh",
        provenance={
            "edge_count": "0",
            "graph_sha256": "a" * 64,
            "import_time": "2026-05-04T00:00:00Z",
            "node_count": "1",
            "parser_version": "test",
            "source_path": "graphify-out/graph.json",
        },
    )
    return capture


def test_persist_graphify_context_writes_with_random_atomic_temp(tmp_path: Path) -> None:
    run_path = tmp_path / ".ahadiff" / "runs" / "run-graphify"
    run_path.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    deterministic_tmp = run_path / "graphify_context.tmp"
    deterministic_tmp.symlink_to(outside)

    _persist_graphify_context(_fake_graphify_capture(tmp_path), run_path)

    assert not outside.exists()
    assert deterministic_tmp.is_symlink()
    payload = (run_path / "graphify_context.json").read_text(encoding="utf-8")
    assert f'"graph_sha256": "{"a" * 64}"' in payload
    signoff = json.loads((run_path / "graphify_signoff.json").read_text(encoding="utf-8"))
    assert signoff["schema"] == "ahadiff.graphify_signoff"
    assert signoff["signoff"] == "passed"
    assert signoff["graph_sha256"] == "a" * 64


def test_graphify_signoff_degrades_invalid_provenance(tmp_path: Path) -> None:
    capture = _fake_graphify_capture(tmp_path)
    capture.graphify_status.provenance.update(  # type: ignore[attr-defined]
        {
            "edge_count": "not-a-count",
            "graph_sha256": "not-a-sha",
            "node_count": "-1",
        }
    )

    signoff = graphify_signoff_payload_from_capture(cast("Any", capture))

    assert signoff is not None
    assert signoff["signoff"] == "degraded"
    assert signoff["graph_sha256"] == ""
    assert signoff["node_count"] == 0
    assert signoff["edge_count"] == 0
    reasons = set(cast("list[str]", signoff["degradation_reasons"]))
    assert {"graph_digest_invalid", "node_count_invalid", "edge_count_invalid"} <= reasons


def test_capture_recommendation_prefers_split_live_input_over_legacy_context() -> None:
    snapshot = _FakeConfigSnapshot()
    snapshot.values["capture"]["mode"] = "auto"
    snapshot.values["llm"]["generate_provider"] = "local"
    snapshot.values["providers"] = {
        "local": {
            "provider_class": "openai",
            "model_name": "gpt-4o",
            "base_url": "http://127.0.0.1:8318",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
            "probed_max_context": 1_000_000,
            "probed_max_input_tokens": 128_000,
            "probed_limits_source": "live",
        }
    }

    recommendation = _effective_capture_recommendation(
        snapshot=snapshot,
        capture_config=cast("dict[str, Any]", snapshot.values["capture"]),
        llm_config=cast("dict[str, Any]", snapshot.values["llm"]),
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
        require_configured_provider=True,
    )

    assert recommendation.context_window == 1_000_000
    assert recommendation.max_input_tokens == 128_000
    assert recommendation.max_output_tokens == 16_384
    assert recommendation.source == "mixed"


def test_persist_skipped_run_rolls_back_event_when_finalized_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_path = tmp_path / ".ahadiff" / "runs" / "run-skip"
    run_path.mkdir(parents=True)

    def _fail_finalized(**kwargs: object) -> None:
        del kwargs
        raise OSError("disk full")

    monkeypatch.setattr("ahadiff.eval.results.write_finalized_result", _fail_finalized)

    warnings = _persist_skipped_run(
        run_path=run_path,
        run_id="run-skip",
        source_ref="abc123",
        learnability_metadata={"score": 0.1, "threshold": 0.3, "skip_lesson_quiz": True},
        workspace_root=tmp_path,
    )

    assert any("rolled back" in warning for warning in warnings)
    assert not (run_path / "finalized.json").exists()
    assert not (run_path / "score.json").exists()
    db_path = tmp_path / ".ahadiff" / "review.sqlite"
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM result_events").fetchone()
    assert row == (0,)


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
    provider_config: _FakeProviderConfig | None = None,
    on_extract_claims: Callable[[dict[str, object]], None] | None = None,
    on_generate_lessons: Callable[[dict[str, object]], None] | None = None,
    on_generate_quiz: Callable[[dict[str, object]], None] | None = None,
    on_generate_cards: Callable[[], None] | None = None,
    on_persist: Callable[[Path], None] | None = None,
    graphify_cli_available: bool = True,
    graphify_update_result: bool = False,
    on_import_graphify: Callable[[Path, bool], object] | None = None,
) -> None:
    def _resolve_provider_from_config(
        **kwargs: object,
    ) -> tuple[_FakeProviderConfig, str, str, bool]:
        return provider_config or _FakeProviderConfig(), "key", "local", False

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
        if on_extract_claims is not None:
            on_extract_claims(kw)
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
        if on_generate_lessons is not None:
            on_generate_lessons(kwargs)
        sub_progress = kwargs.get("on_sub_progress")
        if callable(sub_progress):
            callback = cast("Callable[[str], None]", sub_progress)
            callback("Generating full lesson (1/3)")
            callback("Generating hint lesson (2/3)")
            callback("Generating compact lesson (3/3)")

    def _generate_quiz_from_run(**kwargs: object) -> tuple[Path, list[object]]:
        if on_generate_quiz is not None:
            on_generate_quiz(kwargs)
        sub_progress = kwargs.get("on_sub_progress")
        if callable(sub_progress):
            callback = cast("Callable[[str], None]", sub_progress)
            callback("Generating quiz questions (1/2)")
            callback("Generating misconception cards (2/2)")
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

    def _import_graphify_artifact(*args: object, **kwargs: object) -> object:
        if on_import_graphify is not None:
            root = cast("Path", args[0])
            force = bool(kwargs.get("force", False))
            return on_import_graphify(root, force)
        del args, kwargs
        return None

    monkeypatch.setattr(
        "ahadiff.git.capture.import_graphify_artifact",
        _import_graphify_artifact,
    )

    def _detect_graphify_cli() -> str | None:
        return "/usr/bin/graphify" if graphify_cli_available else None

    monkeypatch.setattr(
        "ahadiff.graphify.cli.detect_graphify_cli",
        _detect_graphify_cli,
    )

    def _run_graphify_update(*args: object, **kwargs: object) -> bool:
        del args, kwargs
        return graphify_update_result

    monkeypatch.setattr(
        "ahadiff.graphify.cli.run_graphify_update",
        _run_graphify_update,
    )


def _patch_persist_warnings(monkeypatch: pytest.MonkeyPatch, warnings: list[str]) -> None:
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
        del report, workspace_root, event_type, force, note_payload
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fake_event = MagicMock()
        fake_event.status = "keep"
        fake_event.event_id = "evt-001"
        fake_outcome = MagicMock()
        fake_outcome.event = fake_event
        return fake_outcome, list(warnings)

    monkeypatch.setattr(f"{_ORCH}._persist_evaluated_run_sync", _persist)


def _patch_successful_post_persist_steps(monkeypatch: pytest.MonkeyPatch, run_path: Path) -> None:
    def _import_cards_from_jsonl(*args: object, **kwargs: object) -> int:
        del args, kwargs
        return 0

    def _append_concepts(**kwargs: object) -> Path:
        del kwargs
        output_path = run_path / "concepts_local.jsonl"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}\n", encoding="utf-8")
        return output_path

    monkeypatch.setattr("ahadiff.review.database.import_cards_from_jsonl", _import_cards_from_jsonl)
    monkeypatch.setattr("ahadiff.wiki.concepts.append_concepts", _append_concepts)


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


def test_dry_run_metadata_includes_capture_limits_and_truncation_audit(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    capture.metadata.update(
        {
            "degraded_flags": {"diff_clipped": True},
            "omitted_files": ["large.py"],
        }
    )
    _patch_learnability(monkeypatch, score=0.7)
    written: dict[str, dict[str, object]] = {}

    def _write_input_artifacts(seen_capture: _FakeCapture) -> None:
        written["metadata"] = json.loads(json.dumps(seen_capture.metadata))

    def _register_repo(_root: Path, _state_dir: Path) -> None:
        return None

    monkeypatch.setattr(f"{_GIT_CAPTURE}.write_input_artifacts", _write_input_artifacts)
    monkeypatch.setattr("ahadiff.core.registry.register_repo", _register_repo)

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo, dry_run=True))

    assert result.status == "dry_run"
    metadata = written["metadata"]
    assert cast("dict[str, object]", metadata["degraded_flags"])["diff_clipped"] is True
    assert metadata["omitted_files"] == ["large.py"]
    limits = cast("dict[str, object]", metadata["effective_capture_limits"])
    assert limits["mode"] == "manual"
    assert limits["max_files"] == 50
    assert limits["hard_limit"] == 100
    assert limits["max_patch_bytes"] == 500_000


def test_concurrent_dry_run_learn_calls_serialize_on_repo_write_lock(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    _patch_capture(monkeypatch, fake_repo)

    repo_lock = threading.Lock()
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    call_count = 0
    max_active = 0
    active = 0
    assess_lock = threading.Lock()
    errors: list[BaseException] = []

    @contextmanager
    def _serial_repo_write_lock(path: Path, command: str = "") -> Generator[None]:
        del path, command
        with repo_lock:
            yield None

    def _assess_learnability(
        _text: str,
        threshold: float = 0.3,
        force_learn: bool = False,
    ) -> _FakeLearnabilityAssessment:
        del threshold, force_learn
        nonlocal call_count, active, max_active
        with assess_lock:
            call_count += 1
            active += 1
            max_active = max(max_active, active)
            current_call = call_count
        try:
            if current_call == 1:
                first_entered.set()
                assert release_first.wait(timeout=2.0)
            else:
                second_entered.set()
            return _FakeLearnabilityAssessment(score=0.7)
        finally:
            with assess_lock:
                active -= 1

    monkeypatch.setattr(f"{_GIT_REPO}.repo_write_lock", _serial_repo_write_lock)
    monkeypatch.setattr(f"{_LEARNABILITY}.assess_learnability", _assess_learnability)

    def _register_repo(*args: object, **kwargs: object) -> None:
        del args, kwargs

    monkeypatch.setattr("ahadiff.core.registry.register_repo", _register_repo)

    def _run_pipeline() -> None:
        try:
            result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo, dry_run=True))
            assert result.status == "dry_run"
        except BaseException as exc:  # pragma: no cover - defensive thread capture
            errors.append(exc)

    first = threading.Thread(target=_run_pipeline)
    second = threading.Thread(target=_run_pipeline)
    first.start()
    assert first_entered.wait(timeout=2.0)
    second.start()
    time.sleep(0.2)
    assert not second_entered.is_set()
    release_first.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert call_count == 2
    assert max_active == 1


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


def test_progress_callback_emits_lesson_substeps(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    _patch_completed_pipeline(monkeypatch, fake_repo, capture)
    collected: list[tuple[int, int, str]] = []

    run_learn_pipeline(
        LearnRequest(workspace_root=fake_repo),
        on_progress=lambda step, total, message: collected.append((step, total, message)),
    )

    step6_messages = [message for step, _total, message in collected if step == 6]
    assert step6_messages == [
        "Generating full lesson (1/3)",
        "Generating hint lesson (2/3)",
        "Generating compact lesson (3/3)",
    ]
    assert all(total == 10 for step, total, _message in collected if step == 6)


def test_against_spec_writes_spec_alignment_artifact_before_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    _patch_completed_pipeline(monkeypatch, fake_repo, capture)
    spec_path = fake_repo / "SPEC.md"
    spec_path.write_text("- The retry helper must attempt three times.\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def _write_spec_alignment_artifact(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        run_path = cast("Path", kwargs["run_path"])
        (run_path / "spec_alignment.json").write_text("{}\n", encoding="utf-8")
        return {"score": 10.0}

    monkeypatch.setattr(
        "ahadiff.eval.spec_alignment.write_spec_alignment_artifact",
        _write_spec_alignment_artifact,
    )

    result = run_learn_pipeline(
        LearnRequest(workspace_root=fake_repo, against_spec=Path("SPEC.md")),
    )

    assert result.status == "keep"
    assert len(calls) == 1
    assert calls[0]["workspace_root"] == fake_repo
    assert calls[0]["spec_path"] == Path("SPEC.md")
    assert calls[0]["run_path"] == fake_repo / ".ahadiff" / "runs" / capture.run_id


def test_against_spec_semantic_review_runs_before_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    snapshot.values["llm"]["judge_provider"] = "judge"
    snapshot.values["llm"]["judge_model"] = "gpt-5.5"

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    _patch_completed_pipeline(monkeypatch, fake_repo, capture)
    spec_path = fake_repo / "SPEC.md"
    spec_path.write_text("- The retry helper must attempt three times.\n", encoding="utf-8")
    semantic_calls: list[dict[str, object]] = []

    def _write_spec_alignment_artifact(**kwargs: object) -> dict[str, object]:
        run_path = cast("Path", kwargs["run_path"])
        (run_path / "spec_alignment.json").write_text(
            '{"artifact":"spec_alignment","schema":"ahadiff.spec_alignment","score":8}\n',
            encoding="utf-8",
        )
        return {"score": 8.0}

    def _run_semantic_alignment_review_for_run(**kwargs: object) -> dict[str, object]:
        semantic_calls.append(kwargs)
        return {}

    monkeypatch.setattr(
        "ahadiff.eval.spec_alignment.write_spec_alignment_artifact",
        _write_spec_alignment_artifact,
    )
    monkeypatch.setattr(
        "ahadiff.eval.spec_alignment.run_semantic_alignment_review_for_run",
        _run_semantic_alignment_review_for_run,
    )

    result = run_learn_pipeline(
        LearnRequest(
            workspace_root=fake_repo,
            against_spec=Path("SPEC.md"),
            spec_semantic_review=True,
        ),
    )

    assert result.status == "keep"
    assert len(semantic_calls) == 1
    assert semantic_calls[0]["run_path"] == fake_repo / ".ahadiff" / "runs" / capture.run_id
    assert semantic_calls[0]["output_lang"] == "en"


def test_configured_judge_provider_runs_after_deterministic_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    snapshot.values["llm"]["judge_provider"] = "judge"

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    _patch_completed_pipeline(monkeypatch, fake_repo, capture)
    judge_calls: list[dict[str, object]] = []

    def _run_llm_judge_for_run(**kwargs: object) -> None:
        judge_calls.append(kwargs)

    monkeypatch.setattr("ahadiff.eval.evaluator.run_llm_judge_for_run", _run_llm_judge_for_run)

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert len(judge_calls) == 1
    assert judge_calls[0]["run_path"] == fake_repo / ".ahadiff" / "runs" / capture.run_id
    assert judge_calls[0]["output_lang"] == "en"
    assert cast("MagicMock", judge_calls[0]["deterministic_report"]).verdict == "PASS"
    assert not (fake_repo / ".ahadiff" / "runs" / capture.run_id / "judge_failure.json").exists()


def test_judge_failure_warning_survives_persist_and_writes_artifact(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    snapshot.values["llm"]["judge_provider"] = "judge"
    snapshot.values["llm"]["judge_model"] = "judge-model"

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        del cli_overrides
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    run_path = fake_repo / ".ahadiff" / "runs" / capture.run_id
    _patch_learnability(monkeypatch, score=0.7)
    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        provider_config=_FakeProviderConfig(
            provider_class="openai_responses",
            model_name="judge-model",
        ),
    )
    _patch_persist_warnings(monkeypatch, ["persist warning"])
    _patch_successful_post_persist_steps(monkeypatch, run_path)
    secret = "sk-" + ("A" * 32)
    key_secret = "key-" + ("B" * 32)
    bearer_secret = "Bearer " + ("C" * 40)
    long_message = (
        f"judge failed with {secret} {key_secret} {bearer_secret} "
        "request body: diff --git a/secret.py b/secret.py\n" + ("x" * 2500)
    )

    def _run_llm_judge_for_run(**kwargs: object) -> None:
        del kwargs
        raise RuntimeError(long_message)

    monkeypatch.setattr("ahadiff.eval.evaluator.run_llm_judge_for_run", _run_llm_judge_for_run)

    with caplog.at_level("WARNING", logger=orchestrator_module.__name__):
        result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert result.warnings[0] == "LLM judge evaluation failed: RuntimeError"
    expected_log_message = "LLM judge evaluation failed: RuntimeError"
    assert any(
        record.exc_info is not None and record.message == expected_log_message
        for record in caplog.records
    )
    assert secret not in result.warnings[0]
    assert key_secret not in result.warnings[0]
    assert bearer_secret not in result.warnings[0]
    assert "judge failed with" not in result.warnings[0]
    assert result.warnings[-1] == "persist warning"
    failure_path = run_path / "judge_failure.json"
    assert failure_path.exists()
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    assert failure["schema"] == "ahadiff.judge_failure.v1"
    assert failure["provider_class"] == "openai_responses"
    assert failure["model_name"] == "judge-model"
    assert failure["error_type"] == "RuntimeError"
    redacted_payload_message = (
        "Judge failure details were redacted because the error included provider payload "
        "or diff text."
    )
    assert failure["message"] == redacted_payload_message
    assert secret not in failure["message"]
    assert key_secret not in failure["message"]
    assert bearer_secret not in failure["message"]
    assert "diff --git" not in failure["message"]
    assert "request body" not in failure["message"]
    assert "sk-" not in failure["message"]
    assert "key-" not in failure["message"]
    assert "Bearer" not in failure["message"]
    assert "Traceback" not in failure["message"]


def test_judge_failure_message_preserves_unicode_without_utf16_over_truncation() -> None:
    message = _bounded_judge_failure_message(RuntimeError("评审失败 😀" * 300))

    assert len(message) <= 2000
    assert "评审失败" in message
    assert "😀" in message


def test_semantic_alignment_failure_warning_survives_persist(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    snapshot.values["llm"]["judge_provider"] = "judge"
    snapshot.values["llm"]["judge_model"] = "judge-model"

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        del cli_overrides
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    run_path = fake_repo / ".ahadiff" / "runs" / capture.run_id
    _patch_learnability(monkeypatch, score=0.7)
    _patch_completed_pipeline(monkeypatch, fake_repo, capture)
    _patch_persist_warnings(monkeypatch, ["persist warning"])
    _patch_successful_post_persist_steps(monkeypatch, run_path)
    spec_path = fake_repo / "SPEC.md"
    spec_path.write_text("- The retry helper must attempt three times.\n", encoding="utf-8")

    def _write_spec_alignment_artifact(**kwargs: object) -> dict[str, object]:
        run = cast("Path", kwargs["run_path"])
        (run / "spec_alignment.json").write_text(
            '{"artifact":"spec_alignment","schema":"ahadiff.spec_alignment","score":8}\n',
            encoding="utf-8",
        )
        return {"score": 8.0}

    secret = "key-" + ("C" * 32)
    degraded_calls: list[dict[str, object]] = []

    def _run_semantic_alignment_review_for_run(**kwargs: object) -> dict[str, object]:
        del kwargs
        raise RuntimeError(f"semantic review failed with {secret}")

    def _mark_semantic_alignment_review_degraded(**kwargs: object) -> dict[str, object]:
        degraded_calls.append(kwargs)
        return {}

    def _run_llm_judge_for_run(**kwargs: object) -> None:
        del kwargs

    monkeypatch.setattr(
        "ahadiff.eval.spec_alignment.write_spec_alignment_artifact",
        _write_spec_alignment_artifact,
    )
    monkeypatch.setattr(
        "ahadiff.eval.spec_alignment.run_semantic_alignment_review_for_run",
        _run_semantic_alignment_review_for_run,
    )
    monkeypatch.setattr(
        "ahadiff.eval.spec_alignment.mark_semantic_alignment_review_degraded",
        _mark_semantic_alignment_review_degraded,
    )
    monkeypatch.setattr("ahadiff.eval.evaluator.run_llm_judge_for_run", _run_llm_judge_for_run)

    result = run_learn_pipeline(
        LearnRequest(
            workspace_root=fake_repo,
            against_spec=Path("SPEC.md"),
            spec_semantic_review=True,
        )
    )

    assert result.status == "keep"
    assert result.warnings == [
        "semantic spec alignment review failed: RuntimeError",
        "persist warning",
    ]
    assert secret not in result.warnings[0]
    assert degraded_calls[0]["reason"] == "RuntimeError"


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


def test_pipeline_passes_step_specific_output_caps(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    snapshot.values["llm"].update(
        {
            "output_token_budget": 50_000,
            "claim_extraction_output_cap": 7_000,
            "lesson_full_output_cap": 11_000,
            "lesson_hint_output_cap": 2_900,
            "lesson_compact_output_cap": 2_400,
            "quiz_generation_output_cap": 5_500,
            "misconception_cards_output_cap": 2_800,
        }
    )
    snapshot.values["quiz"]["quiz_question_count"] = 7

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        del cli_overrides
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    seen: dict[str, dict[str, object]] = {}

    def _record(name: str) -> Callable[[dict[str, object]], None]:
        def _inner(kwargs: dict[str, object]) -> None:
            seen[name] = kwargs

        return _inner

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        provider_config=_FakeProviderConfig(max_output_tokens=131_072),
        on_extract_claims=_record("claims"),
        on_generate_lessons=_record("lessons"),
        on_generate_quiz=_record("quiz"),
    )

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    claim_provider = cast("_FakeProviderConfig", seen["claims"]["provider_config"])
    assert claim_provider.max_output_tokens == 7_000
    assert seen["claims"]["claim_output_token_cap"] == 7_000
    assert seen["claims"]["output_token_budget"] == 50_000

    lesson_provider = cast("_FakeProviderConfig", seen["lessons"]["provider_config"])
    assert lesson_provider.max_output_tokens == 11_000
    assert seen["lessons"]["lesson_output_token_caps"] == {
        "full": 11_000,
        "hint": 2_900,
        "compact": 2_400,
    }
    assert seen["lessons"]["output_token_budget"] == 50_000

    quiz_provider = cast("_FakeProviderConfig", seen["quiz"]["provider_config"])
    assert quiz_provider.max_output_tokens == 5_500
    assert seen["quiz"]["quiz_output_token_cap"] == 5_500
    assert seen["quiz"]["misconception_output_token_cap"] == 2_800
    assert seen["quiz"]["question_count"] == 7
    assert seen["quiz"]["output_token_budget"] == 50_000


def test_pipeline_passes_default_quiz_output_caps(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        del cli_overrides
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    seen: dict[str, object] = {}

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        provider_config=_FakeProviderConfig(max_output_tokens=131_072),
        on_generate_quiz=lambda kwargs: seen.update(kwargs),
    )

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert seen["quiz_output_token_cap"] == 18_000
    assert seen["misconception_output_token_cap"] == 6_000


def test_pipeline_uses_adaptive_question_count_from_capture_stats(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    snapshot.values["quiz"].update(
        {
            "quiz_question_count": 4,
            "quiz_question_count_mode": "auto",
            "quiz_auto_range_min": 3,
            "quiz_auto_range_max": 8,
        }
    )

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        del cli_overrides
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    capture.metadata["diff_stats"] = {
        "total_changed_lines": 500,
        "total_hunk_count": 5,
        "file_count": 9,
    }
    _patch_learnability(monkeypatch, score=0.7)
    seen: dict[str, object] = {}

    def _record_quiz(kwargs: dict[str, object]) -> None:
        seen.update(kwargs)

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_generate_quiz=_record_quiz,
    )

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert seen["question_count"] == 8


def test_pipeline_applies_quiz_mode_request_override(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    seen_overrides: dict[str, object] = {}

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        seen_overrides.update(cli_overrides or {})
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)

    result = run_learn_pipeline(
        LearnRequest(workspace_root=fake_repo, dry_run=True, quiz_mode="auto")
    )

    assert result.status == "dry_run"
    assert seen_overrides["quiz.quiz_question_count_mode"] == "auto"


def test_pipeline_falls_back_to_fixed_mode_when_quiz_mode_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    del snapshot.values["quiz"]["quiz_question_count_mode"]
    snapshot.values["quiz"]["quiz_question_count"] = 5

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        del cli_overrides
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    capture.metadata["diff_stats"] = {
        "total_changed_lines": 500,
        "total_hunk_count": 5,
        "file_count": 9,
    }
    _patch_learnability(monkeypatch, score=0.7)
    seen: dict[str, object] = {}

    def _record_quiz(kwargs: dict[str, object]) -> None:
        seen.update(kwargs)

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_generate_quiz=_record_quiz,
    )

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert seen["question_count"] == 5


@pytest.mark.parametrize(
    "diff_stats",
    [
        {"file_count": 9},
        {"total_changed_lines": 500},
        {"total_changed_lines": 500, "file_count": False},
        {"total_changed_lines": -1, "file_count": 9},
    ],
)
def test_pipeline_falls_back_to_fixed_count_for_incomplete_adaptive_stats(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
    diff_stats: dict[str, object],
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    snapshot.values["quiz"].update(
        {
            "quiz_question_count": 4,
            "quiz_question_count_mode": "auto",
            "quiz_auto_range_min": 3,
            "quiz_auto_range_max": 8,
        }
    )

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        del cli_overrides
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    capture.metadata["diff_stats"] = diff_stats
    _patch_learnability(monkeypatch, score=0.7)
    seen: dict[str, object] = {}

    def _record_quiz(kwargs: dict[str, object]) -> None:
        seen.update(kwargs)

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_generate_quiz=_record_quiz,
    )

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert seen["question_count"] == 4


def test_pipeline_uses_default_auto_range_when_legacy_range_keys_are_missing(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    snapshot.values["quiz"] = {
        "quiz_question_count": 4,
        "quiz_question_count_mode": "auto",
    }

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        del cli_overrides
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    capture.metadata["diff_stats"] = {
        "total_changed_lines": 500,
        "total_hunk_count": 5,
        "file_count": 100,
    }
    _patch_learnability(monkeypatch, score=0.7)
    seen: dict[str, object] = {}

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_generate_quiz=lambda kwargs: seen.update(kwargs),
    )

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert seen["question_count"] == 12


def test_pipeline_falls_back_to_fixed_count_when_diff_stats_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    snapshot.values["quiz"].update(
        {
            "quiz_question_count": 4,
            "quiz_question_count_mode": "auto",
            "quiz_auto_range_min": 3,
            "quiz_auto_range_max": 8,
        }
    )

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        del cli_overrides
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    seen: dict[str, object] = {}

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_generate_quiz=lambda kwargs: seen.update(kwargs),
    )

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert seen["question_count"] == 4


def test_pipeline_uses_auto_lower_bound_for_zero_diff_stats(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    snapshot = _FakeConfigSnapshot()
    snapshot.values["quiz"].update(
        {
            "quiz_question_count": 4,
            "quiz_question_count_mode": "auto",
            "quiz_auto_range_min": 5,
            "quiz_auto_range_max": 8,
        }
    )

    def _load_config(
        _root: Path,
        cli_overrides: dict[str, object] | None = None,
    ) -> _FakeConfigSnapshot:
        del cli_overrides
        return snapshot

    monkeypatch.setattr(f"{_ORCH}.load_config", _load_config)
    capture = _patch_capture(monkeypatch, fake_repo)
    capture.metadata["diff_stats"] = {
        "total_changed_lines": 0,
        "total_hunk_count": 0,
        "file_count": 0,
    }
    _patch_learnability(monkeypatch, score=0.7)
    seen: dict[str, object] = {}

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_generate_quiz=lambda kwargs: seen.update(kwargs),
    )

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert seen["question_count"] == 5


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


def test_cancellation_after_persist_rolls_back_run_artifacts_and_skips_append_concepts(
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

    assert append_called is False
    assert not finalized_path.exists()
    assert not score_path.exists()
    assert not run_path.exists()


def test_cancellation_cleanup_runs_inside_repo_write_lock(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)

    cancelled = False
    lock_held = False
    cleanup_lock_state: list[bool] = []

    @contextmanager
    def _tracked_repo_write_lock(path: Path, command: str = "") -> Generator[None]:
        del path, command
        nonlocal lock_held
        lock_held = True
        try:
            yield None
        finally:
            lock_held = False

    def _persist(current_run_path: Path) -> None:
        del current_run_path
        nonlocal cancelled
        cancelled = True

    def _cleanup_cancelled_run(*, run_path: Path | None, learn_outcome: object) -> None:
        del run_path, learn_outcome
        cleanup_lock_state.append(lock_held)

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_persist=_persist,
    )
    monkeypatch.setattr(f"{_GIT_REPO}.repo_write_lock", _tracked_repo_write_lock)
    monkeypatch.setattr(f"{_ORCH}._cleanup_cancelled_run", _cleanup_cancelled_run)

    with pytest.raises(AhaDiffError, match="cancelled"):
        run_learn_pipeline(LearnRequest(workspace_root=fake_repo), is_cancelled=lambda: cancelled)

    assert cleanup_lock_state == [True]


def test_failed_lesson_artifact_cleanup_runs_inside_repo_write_lock(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    import ahadiff.core.orchestrator as orchestrator_module

    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)

    lock_held = False
    cleanup_lock_state: list[bool] = []
    run_path = fake_repo / ".ahadiff" / "runs" / capture.run_id

    @contextmanager
    def _tracked_repo_write_lock(path: Path, command: str = "") -> Generator[None]:
        del path, command
        nonlocal lock_held
        lock_held = True
        try:
            yield None
        finally:
            lock_held = False

    original_cleanup = cast(
        "Callable[..., None]",
        vars(orchestrator_module)["_cleanup_lesson_generation_artifacts"],
    )

    def _tracked_cleanup(*args: object, **kwargs: object) -> None:
        cleanup_lock_state.append(lock_held)
        original_cleanup(*args, **kwargs)

    def _fail_generate_lessons(**kwargs: object) -> None:
        del kwargs
        (run_path / "lesson").mkdir(parents=True, exist_ok=True)
        (run_path / "lesson" / "partial.md").write_text("partial\n", encoding="utf-8")
        raise RuntimeError("lesson interrupted")

    _patch_completed_pipeline(monkeypatch, fake_repo, capture)
    monkeypatch.setattr(f"{_GIT_REPO}.repo_write_lock", _tracked_repo_write_lock)
    monkeypatch.setattr(f"{_ORCH}._cleanup_lesson_generation_artifacts", _tracked_cleanup)
    monkeypatch.setattr(
        "ahadiff.lesson.generator.generate_lessons_from_run",
        _fail_generate_lessons,
    )

    with pytest.raises(AhaDiffError, match="lesson generation failed"):
        run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert cleanup_lock_state == [True]
    assert not (run_path / "claims.raw.jsonl").exists()
    assert not (run_path / "claims.jsonl").exists()
    assert not (run_path / "lesson").exists()


def test_lesson_schema_validation_failure_retries_once_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    call_count = 0

    def _generate_lessons(kwargs: dict[str, object]) -> None:
        del kwargs
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            LessonHint.model_validate({"tl_dr": "Missing required lists."})

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_generate_lessons=_generate_lessons,
    )

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert result.recoverable_errors == 1
    assert call_count == 2


def test_failed_quiz_artifact_cleanup_removes_lesson_and_quiz_outputs(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    run_path = fake_repo / ".ahadiff" / "runs" / capture.run_id

    def _write_lesson_artifact(kwargs: dict[str, object]) -> None:
        del kwargs
        (run_path / "lesson").mkdir(parents=True, exist_ok=True)
        (run_path / "lesson" / "lesson.full.md").write_text("partial\n", encoding="utf-8")

    def _fail_generate_quiz(kwargs: dict[str, object]) -> None:
        del kwargs
        (run_path / "quiz").mkdir(parents=True, exist_ok=True)
        (run_path / "quiz" / "quiz.jsonl").write_text("partial\n", encoding="utf-8")
        raise RuntimeError("invalid quiz payload")

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_generate_lessons=_write_lesson_artifact,
        on_generate_quiz=_fail_generate_quiz,
    )

    with pytest.raises(AhaDiffError, match="quiz generation failed"):
        run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert not (run_path / "claims.raw.jsonl").exists()
    assert not (run_path / "claims.jsonl").exists()
    assert not (run_path / "lesson").exists()
    assert not (run_path / "quiz").exists()


def test_cancellation_after_append_concepts_commits_published_run(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)

    cancelled = False
    run_path = fake_repo / ".ahadiff" / "runs" / capture.run_id
    finalized_path = run_path / "finalized.json"
    score_path = run_path / "score.json"

    def _persist(current_run_path: Path) -> None:
        current_run_path.mkdir(parents=True, exist_ok=True)
        finalized_path.write_text("{}\n", encoding="utf-8")
        score_path.write_text("{}\n", encoding="utf-8")

    def _append_concepts(**kwargs: object) -> Path:
        del kwargs
        nonlocal cancelled
        output_path = run_path / "concepts_local.jsonl"
        output_path.write_text("{}\n", encoding="utf-8")
        cancelled = True
        return output_path

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_persist=_persist,
    )
    monkeypatch.setattr("ahadiff.wiki.concepts.append_concepts", _append_concepts)

    req = LearnRequest(workspace_root=fake_repo)
    result = run_learn_pipeline(req, is_cancelled=lambda: cancelled)

    assert result.status == "keep"
    assert finalized_path.exists()
    assert score_path.exists()
    assert run_path.exists()


def test_cancellation_after_append_concepts_failure_keeps_published_run(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)

    cancelled = False
    run_path = fake_repo / ".ahadiff" / "runs" / capture.run_id
    finalized_path = run_path / "finalized.json"
    score_path = run_path / "score.json"

    def _persist(current_run_path: Path) -> None:
        current_run_path.mkdir(parents=True, exist_ok=True)
        finalized_path.write_text("{}\n", encoding="utf-8")
        score_path.write_text("{}\n", encoding="utf-8")

    def _append_concepts(**kwargs: object) -> Path:
        del kwargs
        nonlocal cancelled
        cancelled = True
        raise RuntimeError("concept sync failed")

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_persist=_persist,
    )
    monkeypatch.setattr("ahadiff.wiki.concepts.append_concepts", _append_concepts)

    req = LearnRequest(workspace_root=fake_repo)
    result = run_learn_pipeline(req, is_cancelled=lambda: cancelled)

    assert result.status == "keep"
    assert result.warnings == ["concepts append failed: concept sync failed"]
    assert finalized_path.exists()
    assert score_path.exists()
    assert run_path.exists()


def test_append_concepts_contract_error_after_publish_keeps_published_run(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)

    run_path = fake_repo / ".ahadiff" / "runs" / capture.run_id
    finalized_path = run_path / "finalized.json"
    score_path = run_path / "score.json"

    def _persist(current_run_path: Path) -> None:
        current_run_path.mkdir(parents=True, exist_ok=True)
        finalized_path.write_text("{}\n", encoding="utf-8")
        score_path.write_text("{}\n", encoding="utf-8")

    def _append_concepts(**kwargs: object) -> Path:
        del kwargs
        raise AhaDiffError("cancelled")

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_persist=_persist,
    )
    monkeypatch.setattr("ahadiff.wiki.concepts.append_concepts", _append_concepts)

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert result.warnings == ["concepts append failed: cancelled"]
    assert finalized_path.exists()
    assert score_path.exists()
    assert run_path.exists()


def test_review_card_import_failure_is_warning_after_publish(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)

    run_path = fake_repo / ".ahadiff" / "runs" / capture.run_id
    finalized_path = run_path / "finalized.json"
    score_path = run_path / "score.json"

    def _persist(current_run_path: Path) -> None:
        current_run_path.mkdir(parents=True, exist_ok=True)
        finalized_path.write_text("{}\n", encoding="utf-8")
        score_path.write_text("{}\n", encoding="utf-8")

    def _fail_import_cards(*args: object, **kwargs: object) -> int:
        del args, kwargs
        raise RuntimeError("review db locked")

    def _append_concepts(**kwargs: object) -> Path:
        del kwargs
        output_path = run_path / "concepts_local.jsonl"
        output_path.write_text("{}\n", encoding="utf-8")
        return output_path

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        on_persist=_persist,
    )
    monkeypatch.setattr("ahadiff.review.database.import_cards_from_jsonl", _fail_import_cards)
    monkeypatch.setattr("ahadiff.wiki.concepts.append_concepts", _append_concepts)

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert result.warnings == ["review card import failed: review db locked"]
    assert finalized_path.exists()
    assert score_path.exists()


def test_graphify_update_imports_before_concepts_with_force(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    calls: list[tuple[str, bool | None]] = []

    def _import_graphify(root: Path, force: bool) -> object:
        assert root == fake_repo
        calls.append(("graphify_import", force))
        return None

    def _append_concepts(**kwargs: object) -> Path:
        del kwargs
        calls.append(("append_concepts", None))
        output_path = fake_repo / ".ahadiff" / "runs" / capture.run_id / "concepts_local.jsonl"
        output_path.write_text("{}\n", encoding="utf-8")
        return output_path

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        graphify_cli_available=True,
        graphify_update_result=True,
        on_import_graphify=_import_graphify,
    )
    monkeypatch.setattr("ahadiff.wiki.concepts.append_concepts", _append_concepts)

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert calls == [("graphify_import", True), ("append_concepts", None)]


def test_graphify_missing_cli_without_source_skips_import_silently(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    imports: list[tuple[Path, bool]] = []

    def _import_graphify(root: Path, force: bool) -> object:
        imports.append((root, force))
        return None

    def _append_concepts(**kwargs: object) -> Path:
        del kwargs
        output_path = fake_repo / ".ahadiff" / "runs" / capture.run_id / "concepts_local.jsonl"
        output_path.write_text("{}\n", encoding="utf-8")
        return output_path

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        graphify_cli_available=False,
        graphify_update_result=False,
        on_import_graphify=_import_graphify,
    )
    monkeypatch.setattr("ahadiff.wiki.concepts.append_concepts", _append_concepts)

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert imports == []
    assert not any("graphify refresh skipped" in warning for warning in result.warnings)


def test_graphify_cli_failure_does_not_import_stale_source(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
) -> None:
    _patch_config_and_paths(monkeypatch, fake_repo)
    capture = _patch_capture(monkeypatch, fake_repo)
    _patch_learnability(monkeypatch, score=0.7)
    graph_source = fake_repo / "graphify-out" / "graph.json"
    graph_source.parent.mkdir(parents=True)
    graph_source.write_text('{"nodes": [], "links": []}\n', encoding="utf-8")
    imports: list[tuple[Path, bool]] = []

    def _import_graphify(root: Path, force: bool) -> object:
        imports.append((root, force))
        return None

    def _append_concepts(**kwargs: object) -> Path:
        del kwargs
        output_path = fake_repo / ".ahadiff" / "runs" / capture.run_id / "concepts_local.jsonl"
        output_path.write_text("{}\n", encoding="utf-8")
        return output_path

    _patch_completed_pipeline(
        monkeypatch,
        fake_repo,
        capture,
        graphify_cli_available=True,
        graphify_update_result=False,
        on_import_graphify=_import_graphify,
    )
    monkeypatch.setattr("ahadiff.wiki.concepts.append_concepts", _append_concepts)

    result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    assert result.status == "keep"
    assert imports == []
    assert not any("graphify refresh skipped" in warning for warning in result.warnings)


def test_cleanup_cancelled_run_keeps_artifacts_when_result_rollback_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import ahadiff.core.orchestrator as orchestrator_module

    cleanup_cancelled_run = cast(
        "Callable[..., None]",
        vars(orchestrator_module)["_cleanup_cancelled_run"],
    )
    run_path = tmp_path / "runs" / "run-1"
    run_path.mkdir(parents=True)
    finalized_path = run_path / "finalized.json"
    finalized_path.write_text("{}\n", encoding="utf-8")
    fake_event = MagicMock()
    fake_event.event_id = "evt-123"
    fake_outcome = MagicMock()
    fake_outcome.event = fake_event

    def _fail_rollback(*args: object, **kwargs: object) -> None:
        raise RuntimeError("db locked")

    monkeypatch.setattr("ahadiff.eval.results.rollback_result_event", _fail_rollback)

    cleanup_cancelled_run(run_path=run_path, learn_outcome=fake_outcome)

    assert finalized_path.exists()
    assert run_path.exists()


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


# ---------------------------------------------------------------------------
# PipelineErrorBudget and retry tests
# ---------------------------------------------------------------------------


class TestPipelineErrorBudget:
    def test_defaults(self) -> None:
        b = PipelineErrorBudget()
        assert b.max_step_retries == 2
        assert b.max_total_errors == 8
        assert b.error_count == 0
        assert b.exhausted() is False

    def test_record_and_exhaust(self) -> None:
        b = PipelineErrorBudget(max_total_errors=2)
        b.record_error()
        assert b.error_count == 1
        assert b.exhausted() is False
        b.record_error()
        assert b.error_count == 2
        assert b.exhausted() is True


class TestIsRecoverableError:
    def test_connection_error_is_recoverable(self) -> None:
        assert is_recoverable_error(ConnectionError("refused")) is True

    def test_timeout_error_is_recoverable(self) -> None:
        assert is_recoverable_error(TimeoutError("timed out")) is True

    def test_generic_os_error_not_recoverable(self) -> None:
        assert is_recoverable_error(OSError("broken pipe")) is False

    def test_config_error_not_recoverable(self) -> None:
        assert is_recoverable_error(ConfigError("bad config")) is False

    def test_safety_error_not_recoverable(self) -> None:
        assert is_recoverable_error(SafetyError("blocked")) is False

    def test_permission_error_not_recoverable(self) -> None:
        assert is_recoverable_error(PermissionError("denied")) is False

    def test_rate_limit_message_is_recoverable(self) -> None:
        assert is_recoverable_error(RuntimeError("rate limit exceeded")) is True

    def test_503_message_is_recoverable(self) -> None:
        assert is_recoverable_error(RuntimeError("HTTP 503 Service Unavailable")) is True

    def test_generic_runtime_error_not_recoverable(self) -> None:
        assert is_recoverable_error(RuntimeError("unknown failure")) is False

    def test_value_error_not_recoverable(self) -> None:
        assert is_recoverable_error(ValueError("bad value")) is False

    def test_timeout_or_network_error_detects_provider_transport_failures(self) -> None:
        assert is_timeout_or_network_error(ConnectionError("refused")) is True
        assert is_timeout_or_network_error(TimeoutError("timed out")) is True
        assert is_timeout_or_network_error(RuntimeError("provider transport failed")) is True
        assert is_timeout_or_network_error(RuntimeError("rate limit exceeded")) is True
        assert is_timeout_or_network_error(RuntimeError("retryable status 500")) is True

    def test_timeout_or_network_error_excludes_format_failures(self) -> None:
        assert is_timeout_or_network_error(ValueError("payload does not contain JSON")) is False
        assert is_timeout_or_network_error(ValueError("not valid json")) is False
        assert is_timeout_or_network_error(ValueError("not valid json at char 500")) is False

    def test_schema_validation_error_is_recoverable_format_failure(self) -> None:
        with pytest.raises(Exception) as exc_info:
            LessonHint.model_validate({"tl_dr": "Missing required lists."})

        assert is_recoverable_error(exc_info.value) is True


class TestRunWithRetry:
    def test_success_on_first_try(self) -> None:
        budget = PipelineErrorBudget(max_step_retries=2)
        result = run_with_retry(
            lambda: 42,
            step_name="test",
            budget=budget,
            is_cancelled=lambda: False,
        )
        assert result == 42
        assert budget.error_count == 0

    def test_success_after_transient_failure(self) -> None:
        call_count = 0

        def _flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("transient")
            return "ok"

        budget = PipelineErrorBudget(max_step_retries=2)
        result = run_with_retry(
            _flaky,
            step_name="test",
            budget=budget,
            is_cancelled=lambda: False,
        )
        assert result == "ok"
        assert call_count == 2
        assert budget.error_count == 1

    def test_non_recoverable_error_not_retried(self) -> None:
        call_count = 0

        def _config_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise ConfigError("bad config")

        budget = PipelineErrorBudget(max_step_retries=2)
        with pytest.raises(ConfigError, match="bad config"):
            run_with_retry(
                _config_fail,
                step_name="test",
                budget=budget,
                is_cancelled=lambda: False,
            )
        assert call_count == 1
        assert budget.error_count == 0

    def test_retries_exhausted_raises_original(self) -> None:
        call_count = 0

        def _always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionError(f"failure #{call_count}")

        budget = PipelineErrorBudget(max_step_retries=2, max_total_errors=10)
        with pytest.raises(ConnectionError, match="failure #3"):
            run_with_retry(
                _always_fail,
                step_name="test",
                budget=budget,
                is_cancelled=lambda: False,
            )
        assert call_count == 3  # 1 initial + 2 retries
        assert budget.error_count == 3

    def test_max_retries_override_limits_attempts(self) -> None:
        call_count = 0

        def _always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise RuntimeError(f"not valid json #{call_count}")

        budget = PipelineErrorBudget(max_step_retries=5, max_total_errors=10)
        with pytest.raises(RuntimeError, match="not valid json #2"):
            run_with_retry(
                _always_fail,
                step_name="llm_step",
                budget=budget,
                is_cancelled=lambda: False,
                max_retries_override=1,
            )
        assert call_count == 2  # 1 initial + 1 override retry
        assert budget.error_count == 2

    def test_max_retries_override_allows_format_retry(self) -> None:
        call_count = 0

        def _format_flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("payload does not contain a JSON object")
            return "ok"

        budget = PipelineErrorBudget(max_step_retries=2)
        result = run_with_retry(
            _format_flaky,
            step_name="llm_step",
            budget=budget,
            is_cancelled=lambda: False,
            max_retries_override=1,
        )
        assert result == "ok"
        assert call_count == 2
        assert budget.error_count == 1

    def test_max_retries_override_allows_schema_validation_retry(self) -> None:
        call_count = 0

        def _format_flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                LessonHint.model_validate({"tl_dr": "Missing required lists."})
            return "ok"

        budget = PipelineErrorBudget(max_step_retries=2)
        result = run_with_retry(
            _format_flaky,
            step_name="lesson_generation",
            budget=budget,
            is_cancelled=lambda: False,
            max_retries_override=1,
        )
        assert result == "ok"
        assert call_count == 2
        assert budget.error_count == 1

    def test_max_retries_override_does_not_retry_network_failure(self) -> None:
        call_count = 0

        def _provider_timeout() -> str:
            nonlocal call_count
            call_count += 1
            raise TimeoutError("provider request timed out")

        budget = PipelineErrorBudget(max_step_retries=2)
        with pytest.raises(TimeoutError, match="provider request timed out"):
            run_with_retry(
                _provider_timeout,
                step_name="llm_step",
                budget=budget,
                is_cancelled=lambda: False,
                max_retries_override=1,
            )
        assert call_count == 1
        assert budget.error_count == 1

    def test_budget_exhausted_raises_ahadiff_error(self) -> None:
        call_count = 0

        def _always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        budget = PipelineErrorBudget(max_step_retries=5, max_total_errors=2)
        with pytest.raises(AhaDiffError, match="error budget exhausted"):
            run_with_retry(
                _always_fail,
                step_name="flaky_step",
                budget=budget,
                is_cancelled=lambda: False,
            )
        assert budget.error_count == 2
        assert call_count == 2

    def test_cancellation_during_retry(self) -> None:
        call_count = 0
        cancelled = False

        def _fail_then_cancel() -> str:
            nonlocal call_count, cancelled
            call_count += 1
            if call_count == 1:
                cancelled = True
                raise ConnectionError("fail")
            return "should not reach"

        budget = PipelineErrorBudget(max_step_retries=3)
        with pytest.raises(AhaDiffError, match="cancelled"):
            run_with_retry(
                _fail_then_cancel,
                step_name="test",
                budget=budget,
                is_cancelled=lambda: cancelled,
            )
        assert call_count == 1

    def test_cancellation_interrupts_backoff_sleep(self) -> None:
        """H1 fix: cancel during backoff sleep should abort quickly."""
        import time as _time

        call_count = 0
        cancelled = False

        def _fail_once() -> str:
            nonlocal call_count, cancelled
            call_count += 1
            if call_count == 1:
                raise ConnectionError("transient")
            return "ok"

        budget = PipelineErrorBudget(max_step_retries=2)
        start = _time.monotonic()

        def _delayed_cancel() -> bool:
            nonlocal cancelled
            if not cancelled and _time.monotonic() - start > 0.1:
                cancelled = True
            return cancelled

        with pytest.raises(AhaDiffError, match="cancelled"):
            run_with_retry(
                _fail_once,
                step_name="test",
                budget=budget,
                is_cancelled=_delayed_cancel,
            )
        elapsed = _time.monotonic() - start
        assert elapsed < 2.0

    def test_os_error_not_recoverable(self) -> None:
        """M3 fix: local filesystem OSError should not be retried."""
        call_count = 0

        def _disk_full() -> str:
            nonlocal call_count
            call_count += 1
            raise OSError(28, "No space left on device")

        budget = PipelineErrorBudget(max_step_retries=2)
        with pytest.raises(OSError, match="No space left"):
            run_with_retry(
                _disk_full,
                step_name="test",
                budget=budget,
                is_cancelled=lambda: False,
            )
        assert call_count == 1
        assert budget.error_count == 0

    def test_file_not_found_not_recoverable(self) -> None:
        assert is_recoverable_error(FileNotFoundError("missing")) is False

    def test_is_a_directory_not_recoverable(self) -> None:
        assert is_recoverable_error(IsADirectoryError("dir")) is False


class TestPipelineRetryIntegration:
    def test_completed_pipeline_has_zero_recoverable_errors(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_repo: Path,
    ) -> None:
        _patch_config_and_paths(monkeypatch, fake_repo)
        capture = _patch_capture(monkeypatch, fake_repo)
        _patch_learnability(monkeypatch, score=0.7)
        _patch_completed_pipeline(monkeypatch, fake_repo, capture)

        result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))
        assert result.status == "keep"
        assert result.recoverable_errors == 0

    def test_env_override_retry_budget(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_repo: Path,
    ) -> None:
        monkeypatch.setenv("AHADIFF_PIPELINE_MAX_STEP_RETRIES", "0")
        monkeypatch.setenv("AHADIFF_PIPELINE_ERROR_BUDGET", "1")
        _patch_config_and_paths(monkeypatch, fake_repo)
        _patch_capture(monkeypatch, fake_repo)
        _patch_learnability(monkeypatch, score=0.7)

        def _resolve_provider(**kwargs: object) -> tuple[_FakeProviderConfig, str, str, bool]:
            return _FakeProviderConfig(), "key", "local", False

        monkeypatch.setattr(f"{_ORCH}._resolve_provider_from_config", _resolve_provider)

        def _extract_fail(**kwargs: object) -> tuple[Path, int]:
            raise ConnectionError("transient LLM failure")

        monkeypatch.setattr(
            f"{_CLAIMS_RUNTIME}.extract_claim_candidates_from_run",
            _extract_fail,
        )

        with pytest.raises(AhaDiffError, match="error budget exhausted|claim extraction failed"):
            run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

    def test_llm_generation_steps_use_single_step_retry_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_repo: Path,
    ) -> None:
        _patch_config_and_paths(monkeypatch, fake_repo)
        capture = _patch_capture(monkeypatch, fake_repo)
        _patch_learnability(monkeypatch, score=0.7)
        _patch_completed_pipeline(monkeypatch, fake_repo, capture)

        overrides: dict[str, int | None] = {}

        def _recording_run_with_retry(
            step_fn: Callable[[], object],
            *,
            step_name: str,
            budget: PipelineErrorBudget,
            is_cancelled: Callable[[], bool],
            max_retries_override: int | None = None,
        ) -> object:
            overrides[step_name] = max_retries_override
            return run_with_retry(
                step_fn,
                step_name=step_name,
                budget=budget,
                is_cancelled=is_cancelled,
                max_retries_override=max_retries_override,
            )

        monkeypatch.setattr(f"{_ORCH}.run_with_retry", _recording_run_with_retry)

        result = run_learn_pipeline(LearnRequest(workspace_root=fake_repo))

        assert result.status == "keep"
        assert overrides == {
            "claim_extraction": 1,
            "lesson_generation": 1,
            "quiz_generation": 1,
        }


__all__: list[str] = []
