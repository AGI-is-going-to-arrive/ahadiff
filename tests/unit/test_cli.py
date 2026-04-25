from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from ahadiff import cli as cli_module
from ahadiff.cli import app
from ahadiff.contracts import ProviderConfig
from ahadiff.core.config import write_default_config

if TYPE_CHECKING:
    from pathlib import Path

_RUNNER = CliRunner()


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)


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
