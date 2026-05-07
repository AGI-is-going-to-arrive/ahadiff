from __future__ import annotations

import inspect
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from ahadiff import cli as cli_module
from ahadiff.cli import app
from ahadiff.contracts import ProviderConfig
from ahadiff.core.config import ResolvedSetting, write_default_config

if TYPE_CHECKING:
    from pathlib import Path

_RUNNER = CliRunner()


def _init_git_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _write_repo_config(repo_root: Path) -> None:
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir()
    write_default_config(state_dir / "config.toml")


def _repo_root(tmp_path: Path, monkeypatch: Any) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    _write_repo_config(repo_root)
    return repo_root


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        provider_class="ollama",
        model_name="local-model",
        base_url="http://127.0.0.1:11434",
        api_key_env="AHADIFF_PROVIDER_API_KEY",
    )


def test_lazy_class_helpers_resolve_real_classes() -> None:
    assert inspect.isclass(cli_module._install_context_cls())  # pyright: ignore[reportPrivateUsage]
    assert inspect.isclass(cli_module._serve_state_cls())  # pyright: ignore[reportPrivateUsage]


def test_runtime_provider_uses_configured_generate_model_override(
    monkeypatch: Any,
) -> None:
    snapshot = SimpleNamespace(
        values={
            "llm": {"generate_model": "gpt-5.5"},
            "providers": {
                "gpt": {
                    "provider_class": "openai_responses",
                    "model_name": "provider-default",
                    "base_url": "http://127.0.0.1:8318",
                    "api_key_env": "AHADIFF_PROVIDER_API_KEY",
                }
            },
        },
        resolved={
            "llm.generate_model": ResolvedSetting(
                key="llm.generate_model",
                value="gpt-5.5",
                source="repo:/tmp/repo/.ahadiff/config.toml",
            )
        },
    )
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    provider_config, _api_key, _target, _explicit = cli_module._resolve_runtime_provider(  # pyright: ignore[reportPrivateUsage]
        snapshot=snapshot,
        operation_label="lesson generation",
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode="strict_local",
        stdin_interactive=False,
        local_hosts=("127.0.0.1",),
        strict_local_hosts=("127.0.0.1",),
    )

    assert provider_config.model_name == "gpt-5.5"


def test_improve_lang_is_passed_to_run_improve_loop(tmp_path: Path, monkeypatch: Any) -> None:
    repo_root = _repo_root(tmp_path, monkeypatch)
    captured: dict[str, Any] = {}

    def fake_resolve_runtime_provider(**kwargs: Any) -> tuple[ProviderConfig, None, str, bool]:
        del kwargs
        return _provider_config(), None, "local", True

    def fake_run_improve_loop(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            session_id="improve-test",
            anchor_run_id="run-anchor",
            rounds_completed=0,
            outcomes=(),
            warnings=(),
        )

    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", fake_resolve_runtime_provider)
    monkeypatch.setattr(cli_module, "run_improve_loop", fake_run_improve_loop)

    result = _RUNNER.invoke(
        app(),
        ["improve", "--repo-root", str(repo_root), "--lang", "zh-CN"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["output_lang"] == "zh-CN"


def test_improve_without_lang_still_runs(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.delenv("AHADIFF_LANG", raising=False)
    repo_root = _repo_root(tmp_path, monkeypatch)
    captured: dict[str, Any] = {}

    def fake_resolve_runtime_provider(**kwargs: Any) -> tuple[ProviderConfig, None, str, bool]:
        del kwargs
        return _provider_config(), None, "local", True

    def fake_run_improve_loop(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            session_id="improve-test",
            anchor_run_id="run-anchor",
            rounds_completed=0,
            outcomes=(),
            warnings=(),
        )

    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", fake_resolve_runtime_provider)
    monkeypatch.setattr(cli_module, "run_improve_loop", fake_run_improve_loop)

    result = _RUNNER.invoke(
        app(),
        ["improve", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["output_lang"] == "en"


def test_improve_uses_ahadiff_lang_when_lang_flag_is_omitted(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("AHADIFF_LANG", "zh-CN")
    repo_root = _repo_root(tmp_path, monkeypatch)
    captured: dict[str, Any] = {}

    def fake_resolve_runtime_provider(**kwargs: Any) -> tuple[ProviderConfig, None, str, bool]:
        del kwargs
        return _provider_config(), None, "local", True

    def fake_run_improve_loop(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            session_id="improve-test",
            anchor_run_id="run-anchor",
            rounds_completed=0,
            outcomes=(),
            warnings=(),
        )

    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", fake_resolve_runtime_provider)
    monkeypatch.setattr(cli_module, "run_improve_loop", fake_run_improve_loop)

    result = _RUNNER.invoke(
        app(),
        ["improve", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["output_lang"] == "zh-CN"


def test_improve_rejects_redacted_remote_before_provider_resolution(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo_root = _repo_root(tmp_path, monkeypatch)
    (repo_root / ".ahadiff" / "config.toml").write_text(
        'privacy_mode = "redacted_remote"\n',
        encoding="utf-8",
    )

    def fail_resolve_runtime_provider(**kwargs: Any) -> tuple[ProviderConfig, None, str, bool]:
        del kwargs
        raise AssertionError("provider resolution should not run for redacted_remote improve")

    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", fail_resolve_runtime_provider)

    result = _RUNNER.invoke(
        app(),
        ["improve", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "improve does not support redacted_remote privacy mode" in result.stderr


def test_verify_ci_rejects_finalized_event_from_different_run(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import json

    from ahadiff.contracts import ResultEvent
    from ahadiff.eval.results import finalized_artifact_digest
    from ahadiff.review.database import initialize_review_db, sync_result_event

    repo_root = _repo_root(tmp_path, monkeypatch)
    state_dir = repo_root / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    run_a = state_dir / "runs" / "run_a"
    run_b = state_dir / "runs" / "run_b"
    for run_path in (run_a, run_b):
        run_path.mkdir(parents=True)
        (run_path / "metadata.json").write_text(
            json.dumps({"run_id": run_path.name, "source_ref": "abc123"}) + "\n",
            encoding="utf-8",
        )
        (run_path / "patch.diff").write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
    event_id = "018f0f52-91c0-7abc-8123-000000000777"
    artifact_count, checksum = finalized_artifact_digest(run_b)
    (run_b / "finalized.json").write_text(
        json.dumps(
            {
                "run_id": "run_b",
                "event_id": event_id,
                "finalized_at": "2026-04-24T00:00:00Z",
                "artifact_count": artifact_count,
                "checksum": checksum,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    initialize_review_db(db_path)
    sync_result_event(
        db_path,
        ResultEvent(
            event_id=event_id,
            run_id="run_a",
            event_type="learn",
            timestamp="2026-04-24T00:00:00Z",
            source_ref="abc123",
            base_ref=None,
            prompt_version="prompt123",
            eval_bundle_version="eval123",
            rubric_version="rubric-v1",
            overall=88.0,
            verdict="PASS",
            status="keep",
            weakest_dim="evidence",
            note_json=None,
        ),
    )

    result = _RUNNER.invoke(app(), ["verify", "--ci", "--repo-root", str(repo_root)])

    assert result.exit_code == 1
    assert "finalized result event does not exist for run: run_b" in result.stderr


def test_review_lang_is_resolved_inside_handler(tmp_path: Path, monkeypatch: Any) -> None:
    repo_root = _repo_root(tmp_path, monkeypatch)
    captured: dict[str, str | None] = {}

    def fake_resolve_locale(**kwargs: str | None) -> str:
        captured.update(kwargs)
        return "en"

    monkeypatch.setattr(cli_module, "resolve_locale", fake_resolve_locale)

    result = _RUNNER.invoke(
        app(),
        ["review", "--repo-root", str(repo_root), "--lang", "en"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["cli_lang"] == "en"


def test_quiz_lang_is_resolved_inside_handler(tmp_path: Path, monkeypatch: Any) -> None:
    repo_root = _repo_root(tmp_path, monkeypatch)
    captured: dict[str, str | None] = {}

    def fake_resolve_locale(**kwargs: str | None) -> str:
        captured.update(kwargs)
        return "zh-CN"

    def fake_load_quiz_questions(path: Path) -> list[Any]:
        del path
        return []

    monkeypatch.setattr(cli_module, "resolve_locale", fake_resolve_locale)
    monkeypatch.setattr(cli_module, "load_quiz_questions", fake_load_quiz_questions)

    result = _RUNNER.invoke(
        app(),
        ["quiz", "run-1", "--repo-root", str(repo_root), "--lang", "zh-CN"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["cli_lang"] == "zh-CN"


# --- F2 regression: --api-key-env prefix validation ---


def test_api_key_env_rejects_unsafe_names() -> None:
    """validate_repo_api_key_env_name blocks non-AHADIFF_ prefixed env var names."""
    import pytest

    from ahadiff.core.config import validate_repo_api_key_env_name
    from ahadiff.core.errors import ConfigError

    with pytest.raises(ConfigError, match="AHADIFF_"):
        validate_repo_api_key_env_name("AWS_SECRET_ACCESS_KEY")
    with pytest.raises(ConfigError, match="AHADIFF_"):
        validate_repo_api_key_env_name("GITHUB_TOKEN")
    validate_repo_api_key_env_name("AHADIFF_PROVIDER_API_KEY")
    validate_repo_api_key_env_name("OPENAI_API_KEY")
