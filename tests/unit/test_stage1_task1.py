from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ahadiff import cli as cli_module
from ahadiff.cli import app
from ahadiff.core import config as config_module
from ahadiff.core.config import (
    DEFAULT_CONFIG,
    iter_resolved_settings,
    load_config,
    load_workspace_config,
    resolve_effective,
    write_default_config,
)
from ahadiff.core.errors import StorageError
from ahadiff.core.ids import make_claim_id, make_hunk_id, make_run_id
from ahadiff.core.paths import (
    assert_local_repo_path,
    find_workspace_root,
    global_config_dir,
    inspect_repo_path,
    project_state_dir,
    repo_config_path,
    review_db_path,
    run_dir,
)


def _init_git_repo(root: Path) -> None:
    (root / ".git").mkdir()


def test_write_default_config_materializes_expected_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_default_config(config_path)

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload == DEFAULT_CONFIG


def test_render_scalar_escapes_literal_newlines_for_toml_roundtrip() -> None:
    rendered = config_module._render_scalar("line1\nline2")  # pyright: ignore[reportPrivateUsage]
    parsed = tomllib.loads(f"value = {rendered}\n")
    assert parsed["value"] == "line1\nline2"


def test_load_config_resolves_five_layer_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    global_root = tmp_path / "global-home"
    env = {"HOME": str(global_root), "AHADIFF_LANG": "en"}
    global_path = global_config_dir(env=env) / "config.toml"
    global_path.parent.mkdir(parents=True)
    global_path.write_text(
        'lang = "zh-CN"\n\n[learn]\nlearnability_threshold = 0.5\n',
        encoding="utf-8",
    )

    repo_path = repo_config_path(repo_root)
    repo_path.parent.mkdir(parents=True)
    repo_path.write_text(
        'privacy_mode = "redacted_remote"\n\n[serve]\nport = 9001\n',
        encoding="utf-8",
    )

    snapshot = load_config(
        repo_root,
        cli_overrides={"serve.port": 9100},
        env=env,
    )

    assert resolve_effective("lang", snapshot=snapshot).value == "en"
    assert resolve_effective("lang", snapshot=snapshot).source == "env:AHADIFF_LANG"
    assert resolve_effective("serve.port", snapshot=snapshot).value == 9100
    assert resolve_effective("serve.port", snapshot=snapshot).source == "cli"
    assert resolve_effective("privacy_mode", snapshot=snapshot).value == "redacted_remote"
    privacy_source = resolve_effective("privacy_mode", snapshot=snapshot).source
    assert privacy_source.endswith(".ahadiff/config.toml")
    assert resolve_effective("learn.learnability_threshold", snapshot=snapshot).value == 0.5
    global_source = resolve_effective("learn.learnability_threshold", snapshot=snapshot).source
    assert global_source == f"global:{global_path}"
    assert resolve_effective("llm.judge_model", snapshot=snapshot).value == "gpt-5.4-mini"
    assert resolve_effective("llm.judge_model", snapshot=snapshot).source == "default"

    keys = [setting.key for setting in iter_resolved_settings(snapshot)]
    assert "llm.generate_model" in keys


def test_load_config_reports_unknown_and_sensitive_repo_keys(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    repo_path = repo_config_path(repo_root)
    repo_path.parent.mkdir(parents=True)
    repo_path.write_text(
        '[llm]\napi_key = "sk-abcdefghijklmnopqrstuvwxyz"\nunknown_flag = true\n',
        encoding="utf-8",
    )

    snapshot = load_config(repo_root, env={"HOME": str(tmp_path / "home")})
    assert snapshot.repo_unknown_keys == ("llm.api_key", "llm.unknown_flag")
    assert snapshot.repo_sensitive_keys == ("llm.api_key",)


def test_load_workspace_config_resolves_local_and_global_layers_without_git(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    home_root = tmp_path / "home"
    global_path = global_config_dir(env={"HOME": str(home_root)}) / "config.toml"
    global_path.parent.mkdir(parents=True)
    global_path.write_text("[capture]\nmax_files = 9\n", encoding="utf-8")
    (workspace_root / ".ahadiff").mkdir()
    (workspace_root / ".ahadiff" / "config.toml").write_text(
        'privacy_mode = "explicit_remote"\n\n[capture]\nhard_limit = 7\n',
        encoding="utf-8",
    )

    snapshot = load_workspace_config(
        workspace_root,
        cli_overrides={"capture.max_patch_bytes": 1234},
        env={"HOME": str(home_root)},
    )

    assert resolve_effective("privacy_mode", snapshot=snapshot).value == "explicit_remote"
    assert resolve_effective("capture.max_files", snapshot=snapshot).value == 9
    assert resolve_effective("capture.hard_limit", snapshot=snapshot).value == 7
    assert resolve_effective("capture.max_patch_bytes", snapshot=snapshot).value == 1234


def test_load_workspace_config_finds_parent_workspace_root_from_subdir(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    subdir = workspace_root / "nested" / "child"
    subdir.mkdir(parents=True)
    (workspace_root / ".ahadiff").mkdir()
    (workspace_root / ".ahadiff" / "config.toml").write_text(
        'privacy_mode = "explicit_remote"\n',
        encoding="utf-8",
    )

    snapshot = load_workspace_config(subdir)

    assert find_workspace_root(subdir) == workspace_root
    assert resolve_effective("privacy_mode", snapshot=snapshot).value == "explicit_remote"


def test_sensitive_repo_config_detection_matches_supported_keys(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    repo_path = repo_config_path(repo_root)
    repo_path.parent.mkdir(parents=True)
    repo_path.write_text('provider_token = "plain-text-token"\n', encoding="utf-8")

    snapshot = load_config(repo_root, env={"HOME": str(tmp_path / "home")})
    assert snapshot.repo_sensitive_keys == ("provider_token",)


def test_path_helpers_and_global_config_dir_cover_stage1_contract(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    assert project_state_dir(repo_root) == repo_root / ".ahadiff"
    assert run_dir("run_123", repo_root) == repo_root / ".ahadiff" / "runs" / "run_123"
    assert review_db_path(repo_root) == repo_root / ".ahadiff" / "review.sqlite"

    linux_path = global_config_dir(platform="linux", env={"HOME": "/tmp/home"})
    mac_path = global_config_dir(platform="darwin", env={"HOME": "/tmp/home"})
    win_env = {"APPDATA": r"C:\Users\Test\AppData\Roaming"}
    win_path = global_config_dir(platform="win32", env=win_env)

    assert linux_path == Path("/tmp/home/.config/ahadiff")
    assert mac_path == Path("/tmp/home/Library/Application Support/ahadiff")
    assert str(win_path).replace("\\", "/").endswith("AppData/Roaming/ahadiff")


def test_global_config_dir_rejects_empty_home() -> None:
    with pytest.raises(StorageError, match="HOME is empty"):
        global_config_dir(platform="darwin", env={"HOME": ""})


def test_network_path_guard_rejects_unc_roots() -> None:
    with pytest.raises(StorageError, match="UNC or network-mounted path"):
        assert_local_repo_path(Path("//server/share/repo"), platform="win32")


def test_inspect_repo_path_warns_about_casefold_and_length() -> None:
    path = Path("/Users/Example/" + ("VeryLongSegment" * 20))
    warnings = inspect_repo_path(path, platform="darwin")
    warning_codes = {warning.code for warning in warnings}
    assert "casefold_identity" in warning_codes
    assert "long_path" in warning_codes


def test_id_helpers_are_stable_and_shaped() -> None:
    run_id = make_run_id()
    assert re.fullmatch(r"run_[0-9a-f]{32}", run_id)

    claim_id = make_claim_id("run_123", 1)
    hunk_id = make_hunk_id("src/a.py", 10, 12, "def f():")

    assert claim_id == make_claim_id("run_123", 1)
    assert hunk_id == make_hunk_id("src/a.py", 10, 12, "def f():")
    assert claim_id != make_claim_id("run_123", 2)
    assert hunk_id != make_hunk_id("src/a.py", 11, 12, "def f():")


def test_cli_init_and_config_show_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    monkeypatch.chdir(repo_root)

    runner = CliRunner()
    result = runner.invoke(app(), ["init"], catch_exceptions=False)
    assert result.exit_code == 0
    assert (repo_root / ".ahadiff" / "config.toml").exists()

    resolved = runner.invoke(app(), ["config", "show", "--resolved"], catch_exceptions=False)
    assert resolved.exit_code == 0
    assert "privacy_mode" in resolved.stdout
    assert "repo:" in resolved.stdout


def test_cli_browser_flag_can_override_repo_no_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    monkeypatch.chdir(repo_root)
    write_default_config(repo_root / ".ahadiff" / "config.toml")
    (repo_root / ".ahadiff" / "config.toml").write_text(
        'lang = "zh-CN"\n\n[serve]\nno_browser = true\n',
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app(), ["config", "show", "--resolved", "--browser"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert "serve.no_browser" in result.stdout
    assert "false" in result.stdout
    assert "cli" in result.stdout


def test_cli_version_flag_is_reachable() -> None:
    runner = CliRunner()
    result = runner.invoke(app(), ["--version"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "ahadiff 0.1.0a0" in result.stdout


def test_cli_without_subcommand_still_shows_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app(), [], catch_exceptions=False)
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_cli_doctor_reports_unknown_repo_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    monkeypatch.chdir(repo_root)
    write_default_config(repo_root / ".ahadiff" / "config.toml")
    (repo_root / ".ahadiff" / "config.toml").write_text(
        'lang = "zh-CN"\nrogue = true\nprovider_token = "plain-text-token"\n',
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app(), ["doctor"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "Unknown repo keys" in result.stdout
    assert "rogue" in result.stdout
    assert "Sensitive repo config keys" in result.stdout


def test_cli_doctor_handles_corrupt_sqlite_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    monkeypatch.chdir(repo_root)
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "review.sqlite").write_text("not a sqlite db", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app(), ["doctor"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "review.sqlite is not a valid SQLite database" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_doctor_exits_non_zero_when_sqlite_gate_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    monkeypatch.chdir(repo_root)
    monkeypatch.setattr(cli_module, "_sqlite_version_tuple", lambda: (3, 50, 4))
    monkeypatch.setattr(cli_module.sqlite3, "sqlite_version", "3.50.4")

    runner = CliRunner()
    result = runner.invoke(app(), ["doctor"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "SQLite gate" in result.stdout
    assert "does not satisfy the frozen doctor gate" in result.stderr
