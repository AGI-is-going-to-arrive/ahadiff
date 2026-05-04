from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

import ahadiff.git.repo as repo_module
from ahadiff import cli as cli_module
from ahadiff.cli import app
from ahadiff.core import config as config_module
from ahadiff.core.config import (
    DEFAULT_CONFIG,
    iter_resolved_settings,
    load_config,
    load_workspace_config,
    load_workspace_pricing_settings,
    resolve_effective,
    write_default_config,
)
from ahadiff.core.errors import ConfigError, InputError, StorageError
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
    workspace_identity_key,
    workspace_identity_lookup_keys,
)
from ahadiff.git.repo import repo_write_lock, unlock_repo_write_lock


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires elevated Windows privileges")
def test_repo_write_lock_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target_file"
    target.touch()
    link = tmp_path / "ahadiff.lock"
    link.symlink_to(target)
    with pytest.raises(InputError, match="symlink"), repo_write_lock(link, command="test"):
        pass


def test_unlock_repo_write_lock_removes_inactive_regular_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "ahadiff.lock"
    lock_path.write_text("123\n2026-04-26T00:00:00Z\nstale\n", encoding="utf-8")

    assert unlock_repo_write_lock(lock_path) is True
    assert not lock_path.exists()
    assert unlock_repo_write_lock(lock_path) is False


def test_unlock_repo_write_lock_best_effort_unlink_failure_leaves_empty_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "ahadiff.lock"
    lock_path.write_text("123\n2026-04-26T00:00:00Z\nstale\n", encoding="utf-8")
    original_unlink = Path.unlink

    def fail_lock_unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        if self == lock_path:
            raise PermissionError("simulated platform unlink failure")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_lock_unlink)

    assert unlock_repo_write_lock(lock_path) is True
    assert lock_path.exists()
    assert lock_path.read_text(encoding="utf-8") == ""


def test_unlock_repo_write_lock_refuses_active_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "ahadiff.lock"
    lock_path.write_text("123\n2026-04-26T00:00:00Z\nactive\n", encoding="utf-8")

    def fail_lock(_handle: object, _flags: int) -> None:
        raise repo_module.portalocker.exceptions.LockException("active")

    def unlock_noop(_handle: object) -> None:
        return None

    monkeypatch.setattr(repo_module.portalocker, "lock", fail_lock)
    monkeypatch.setattr(repo_module.portalocker, "unlock", unlock_noop)

    with pytest.raises(StorageError, match="active"):
        unlock_repo_write_lock(lock_path)
    assert lock_path.read_text(encoding="utf-8") != ""


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_repo_write_lock_contention_reads_metadata_from_open_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "ahadiff.lock"
    lock_path.write_text("123\n2026-04-26T00:00:00Z\noriginal-lock\n", encoding="utf-8")
    replacement = tmp_path / "replacement.lock"
    replacement.write_text("999\n2026-04-26T00:00:00Z\nleaked-replacement\n", encoding="utf-8")

    def fake_lock(_handle: object, _flags: int) -> None:
        lock_path.unlink()
        os.symlink(replacement, lock_path)
        raise repo_module.portalocker.exceptions.LockException("active")

    monkeypatch.setattr(repo_module.portalocker, "lock", fake_lock)

    with pytest.raises(StorageError) as error, repo_write_lock(lock_path, command="test"):
        raise AssertionError("lock acquisition should have failed")

    message = str(error.value)
    assert "PID=123" in message
    assert "leaked-replacement" not in message


def test_unlock_repo_write_lock_refuses_real_cross_process_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "ahadiff.lock"
    source_root = Path(__file__).resolve().parents[2] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{source_root}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else str(source_root)
    )
    script = """
import sys
import time
from pathlib import Path
from ahadiff.git.repo import repo_write_lock

with repo_write_lock(Path(sys.argv[1]), command="child-lock"):
    print("locked", flush=True)
    time.sleep(30)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "locked"
        with pytest.raises(StorageError, match="active"):
            unlock_repo_write_lock(lock_path)
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


def test_repo_write_lock_rejects_windows_reparse_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.git import repo as _repo_mod

    lock_path = tmp_path / "ahadiff.lock"
    lock_path.touch()

    def _always_reparse(stat_obj: object) -> bool:  # noqa: ARG001
        return True

    monkeypatch.setattr(_repo_mod, "_has_windows_reparse_point", _always_reparse)
    with pytest.raises(InputError, match="reparse"), repo_write_lock(lock_path, command="test"):
        pass


def test_unlock_repo_write_lock_rejects_windows_reparse_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.git import repo as _repo_mod

    lock_path = tmp_path / "ahadiff.lock"
    lock_path.write_text("123\n2026-04-26T00:00:00Z\nstale\n", encoding="utf-8")

    def _always_reparse_unlock(stat_obj: object) -> bool:  # noqa: ARG001
        return True

    monkeypatch.setattr(_repo_mod, "_has_windows_reparse_point", _always_reparse_unlock)
    with pytest.raises(StorageError, match="reparse"):
        unlock_repo_write_lock(lock_path)


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


def test_render_toml_quotes_special_keys_for_roundtrip() -> None:
    rendered = config_module._render_toml(  # pyright: ignore[reportPrivateUsage]
        {
            "pricing": {
                "input_per_million_usd": {
                    "openrouter/custom.model": 0.4,
                }
            }
        }
    )
    parsed = tomllib.loads(rendered)
    assert parsed["pricing"]["input_per_million_usd"]["openrouter/custom.model"] == 0.4


def test_read_config_data_uses_tomllib_message_without_synthetic_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("invalid = \n", encoding="utf-8")
    decode_error = tomllib.TOMLDecodeError("synthetic invalid TOML", "", 0)
    decode_error.lineno = 99  # pyright: ignore[reportAttributeAccessIssue]
    decode_error.colno = 42  # pyright: ignore[reportAttributeAccessIssue]

    def fail_loads(_text: str) -> dict[str, Any]:
        raise decode_error

    monkeypatch.setattr(config_module.tomllib, "loads", fail_loads)

    with pytest.raises(ConfigError) as error:
        config_module.read_config_data(config_path)

    message = str(error.value)
    assert str(config_path) in message
    assert "synthetic invalid TOML" in message
    assert "line 99" not in message
    assert "column 42" not in message


def test_load_config_resolves_five_layer_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    global_root = tmp_path / "global-home"
    env = {
        "HOME": str(global_root),
        "AHADIFF_LANG": "en",
        "AHADIFF_PRIVACY_MODE": "explicit_remote",
    }
    global_path = global_config_dir(env=env) / "config.toml"
    global_path.parent.mkdir(parents=True)
    global_path.write_text(
        'lang = "zh-CN"\n\n[learn]\nlearnability_threshold = 0.5\n',
        encoding="utf-8",
    )

    repo_path = repo_config_path(repo_root)
    repo_path.parent.mkdir(parents=True)
    repo_path.write_text(
        'privacy_mode = "redacted_remote"\n\n[provider]\nqps_limit = 9\n\n[serve]\nport = 9001\n',
        encoding="utf-8",
    )

    snapshot = load_config(
        repo_root,
        cli_overrides={"serve.port": 9100},
        env=env,
    )

    assert resolve_effective("lang", snapshot=snapshot).value == "zh-CN"
    assert resolve_effective("lang", snapshot=snapshot).source == f"global:{global_path}"
    assert resolve_effective("serve.port", snapshot=snapshot).value == 9100
    assert resolve_effective("serve.port", snapshot=snapshot).source == "cli"
    assert resolve_effective("privacy_mode", snapshot=snapshot).value == "explicit_remote"
    assert resolve_effective("privacy_mode", snapshot=snapshot).source == "env:AHADIFF_PRIVACY_MODE"
    provider_source = resolve_effective("provider.qps_limit", snapshot=snapshot).source
    assert provider_source.endswith(".ahadiff/config.toml")
    assert resolve_effective("learn.learnability_threshold", snapshot=snapshot).value == 0.5
    global_source = resolve_effective("learn.learnability_threshold", snapshot=snapshot).source
    assert global_source == f"global:{global_path}"
    assert resolve_effective("llm.judge_model", snapshot=snapshot).value == "gpt-5.4-mini"
    assert resolve_effective("llm.judge_model", snapshot=snapshot).source == "default"

    keys = [setting.key for setting in iter_resolved_settings(snapshot)]
    assert "llm.generate_model" in keys


def test_locale_config_values_are_schema_checked(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    repo_path = repo_config_path(repo_root)
    repo_path.parent.mkdir(parents=True)
    repo_path.write_text('lang = "fr-FR"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="lang must be one of auto, en, zh-CN"):
        load_config(repo_root, env={"HOME": str(tmp_path / "home")})


def test_llm_language_config_values_are_schema_checked(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    repo_path = repo_config_path(repo_root)
    repo_path.parent.mkdir(parents=True)
    repo_path.write_text("[llm]\noutput_lang = 42\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="llm.output_lang expects str"):
        load_config(repo_root, env={"HOME": str(tmp_path / "home")})


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


def test_provider_tables_and_security_local_hosts_are_supported_config_keys(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    repo_path = repo_config_path(repo_root)
    repo_path.parent.mkdir(parents=True)
    repo_path.write_text(
        '[security]\nlocal_hosts = ["model.local"]\n\n'
        "[pricing]\nopenrouter_enabled = true\nopenrouter_refresh_seconds = 900\n\n"
        '[pricing.input_per_million_usd]\n"openrouter/custom.model" = 0.4\n\n'
        '[pricing.output_per_million_usd]\n"openrouter/custom.model" = 1.6\n\n'
        '[providers.demo]\nprovider_class = "openai"\nmodel_name = "gpt-5.4-mini"\n'
        'base_url = "http://127.0.0.1:8000"\napi_key_env = "AHADIFF_PROVIDER_API_KEY"\n'
        "probed_max_context = 1000000\nsupports_temperature = true\n",
        encoding="utf-8",
    )

    snapshot = load_config(repo_root, env={"HOME": str(tmp_path / "home")})
    pricing = load_workspace_pricing_settings(repo_root, env={"HOME": str(tmp_path / "home")})

    assert snapshot.repo_unknown_keys == ()
    assert resolve_effective("security.local_hosts", snapshot=snapshot).value == ("model.local",)
    assert resolve_effective("pricing.openrouter_enabled", snapshot=snapshot).value is True
    assert (
        resolve_effective(
            "pricing.input_per_million_usd.openrouter/custom.model",
            snapshot=snapshot,
        ).value
        == 0.4
    )
    assert pricing.openrouter_refresh_seconds == 900
    assert pricing.model_overrides["openrouter/custom.model"].output_per_million_usd == 1.6


@pytest.mark.parametrize(
    "base_url",
    (
        "https://api.example.test/v1",
        "http://api.example.test",
    ),
)
def test_validate_provider_base_url_accepts_http_and_https(base_url: str) -> None:
    assert config_module.validate_provider_base_url(base_url) == base_url


@pytest.mark.parametrize(
    "base_url",
    (
        "ftp://api.example.test",
        "https://user:pass@api.example.test/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/computeMetadata/v1",
        "https://metadata.azure.com/metadata/instance",
        "http://[fd00:ec2::254]/latest/meta-data",
        "http://localhost:11434",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
        "http://10.0.0.7:8000",
        "http://172.16.0.7:8000",
        "http://192.168.1.7:8000",
    ),
)
def test_validate_provider_base_url_rejects_ssrf_and_secret_url_cases(base_url: str) -> None:
    with pytest.raises(ConfigError):
        config_module.validate_provider_base_url(base_url)


def test_validate_provider_base_url_allows_explicit_local_host_opt_in() -> None:
    assert (
        config_module.validate_provider_base_url(
            "http://127.0.0.1:11434",
            allowed_local_hosts=("127.0.0.1",),
        )
        == "http://127.0.0.1:11434"
    )


def test_provider_url_normalization_and_probe_helpers_are_stable() -> None:
    normalized = config_module.normalize_provider_base_url(
        "HTTPS://API.EXAMPLE.TEST:443/Foo/Bar/",
        provider_class="anthropic",
    )
    assert normalized == "https://api.example.test/Foo/Bar/"
    assert (
        config_module.normalize_provider_base_url(
            "HTTP://API.EXAMPLE.TEST:80/",
            provider_class="openai",
        )
        == "http://api.example.test"
    )
    assert (
        config_module.normalize_provider_base_url(
            "https://API.EXAMPLE.TEST/v1/chat/completions/",
            provider_class="openai",
        )
        == "https://api.example.test"
    )

    provider: dict[str, object] = {
        "provider_class": "openai",
        "model_name": "gpt-5.4-mini",
        "base_url": "https://api.example.test/v1",
        "api_key_env": "AHADIFF_PROVIDER_API_KEY",
        "api_key": "sk-test-secret",
        "probed_max_context": 1000,
        "probe_timestamp": "2026-05-04T00:00:00Z",
    }
    fingerprint = config_module.provider_core_fingerprint(provider)
    provider["api_key"] = "sk-rotated-secret"
    provider["probed_max_context"] = 2000
    provider["probe_timestamp"] = "2026-05-05T00:00:00Z"
    assert config_module.provider_core_fingerprint(provider) == fingerprint

    config_module.clear_provider_probe_fields(provider)
    config_module.clear_provider_probe_fields(provider)
    assert "probed_max_context" not in provider
    assert "probe_timestamp" not in provider


def test_repo_provider_api_key_env_rejects_arbitrary_env_var(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    repo_path = repo_config_path(repo_root)
    repo_path.parent.mkdir(parents=True)
    repo_path.write_text(
        '[providers.demo]\nprovider_class = "openai"\nmodel_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.test"\napi_key_env = "AWS_SECRET_ACCESS_KEY"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="repo provider api_key_env"):
        load_config(repo_root, env={"HOME": str(tmp_path / "home")})


def test_global_provider_api_key_env_is_exempt_from_repo_restriction(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    home_root = tmp_path / "home"
    global_path = global_config_dir(env={"HOME": str(home_root)}) / "config.toml"
    global_path.parent.mkdir(parents=True)
    global_path.write_text(
        '[providers.demo]\nprovider_class = "openai"\nmodel_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.test"\napi_key_env = "AWS_SECRET_ACCESS_KEY"\n',
        encoding="utf-8",
    )

    snapshot = load_config(repo_root, env={"HOME": str(home_root)})

    providers = snapshot.values["providers"]
    assert isinstance(providers, dict)
    assert providers["demo"]["api_key_env"] == "AWS_SECRET_ACCESS_KEY"


def test_security_config_keeps_global_local_hosts_for_strict_local(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    home_root = tmp_path / "home"
    global_path = global_config_dir(env={"HOME": str(home_root)}) / "config.toml"
    global_path.parent.mkdir(parents=True)
    global_path.write_text('[security]\nlocal_hosts = ["global.model"]\n', encoding="utf-8")
    repo_path = repo_config_path(repo_root)
    repo_path.parent.mkdir(parents=True)
    repo_path.write_text('[security]\nlocal_hosts = ["repo.model"]\n', encoding="utf-8")

    snapshot = load_config(repo_root, env={"HOME": str(home_root)})
    security = config_module._security_config_from_snapshot(snapshot)  # pyright: ignore[reportPrivateUsage]

    assert security.local_hosts == ("repo.model",)
    assert security.strict_local_hosts == ("global.model",)


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


def test_load_workspace_config_resolves_capture_symbol_extractor_precedence(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    home_root = tmp_path / "home"
    global_path = global_config_dir(env={"HOME": str(home_root)}) / "config.toml"
    global_path.parent.mkdir(parents=True)
    global_path.write_text('[capture]\nsymbol_extractor = "builtin"\n', encoding="utf-8")
    (workspace_root / ".ahadiff").mkdir()
    (workspace_root / ".ahadiff" / "config.toml").write_text(
        '[capture]\nsymbol_extractor = "tree_sitter"\n',
        encoding="utf-8",
    )

    snapshot = load_workspace_config(
        workspace_root,
        cli_overrides={"capture.symbol_extractor": "builtin"},
        env={
            "HOME": str(home_root),
            "AHADIFF_CAPTURE_SYMBOL_EXTRACTOR": "auto",
        },
    )

    assert resolve_effective("capture.symbol_extractor", snapshot=snapshot).value == "auto"


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


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_project_state_dir_rejects_symlink(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    outside = tmp_path / "outside-state"
    outside.mkdir()
    os.symlink(outside, repo_root / ".ahadiff", target_is_directory=True)

    with pytest.raises(InputError, match="state dir must not be a symlink"):
        project_state_dir(repo_root)


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


def test_workspace_identity_key_preserves_case_on_linux() -> None:
    upper = workspace_identity_key(Path("/tmp/AhaDiffRepo"), platform="linux")
    lower = workspace_identity_key(Path("/tmp/ahadiffrepo"), platform="linux")

    assert upper != lower


def test_workspace_identity_key_casefolds_on_windows() -> None:
    upper = workspace_identity_key(Path("C:/Repo/AhaDiff"), platform="win32")
    lower = workspace_identity_key(Path("c:/repo/ahadiff"), platform="win32")

    assert upper == lower


def test_workspace_identity_lookup_keys_include_legacy_alias() -> None:
    current, legacy = workspace_identity_lookup_keys(Path("/tmp/Repo"), platform="linux")

    assert current == "workspace:v1:/tmp/Repo"
    assert legacy == "/tmp/repo"


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


def test_cli_graph_status_surfaces_unexpected_open_repo_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    monkeypatch.chdir(repo_root)

    def boom(_repo_root: Path | None = None) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr("ahadiff.git.repo.open_repo", boom)

    runner = CliRunner()
    result = runner.invoke(app(), ["graph", "status"], catch_exceptions=False)

    assert result.exit_code == 2
    assert "Unexpected error:" in result.stderr
    assert "boom" in result.stderr


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


def test_cli_serve_headless_linux_does_not_open_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    monkeypatch.chdir(repo_root)
    monkeypatch.setattr(cli_module.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("CI", raising=False)
    opened: list[str] = []
    captured: dict[str, object] = {}

    def fake_run(app_instance: object, *, host: str, port: int, log_level: str) -> None:
        captured.update(
            {
                "app": app_instance,
                "host": host,
                "port": port,
                "log_level": log_level,
            }
        )

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    def record_opened_url(url: str) -> None:
        opened.append(url)

    monkeypatch.setattr(cli_module.webbrowser, "open", record_opened_url)

    runner = CliRunner()
    result = runner.invoke(app(), ["serve", "--port", "9123"], catch_exceptions=False)

    assert result.exit_code == 0
    assert opened == []
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9123
    assert captured["log_level"] == "info"
    assert "http://127.0.0.1:9123" in result.stdout
    assert "localhost" not in result.stdout


def test_cli_serve_browser_disabled_in_ci_even_with_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module.sys, "platform", "linux")
    monkeypatch.setenv("CI", "1")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    assert cli_module._should_open_serve_browser(no_browser=False) is False  # pyright: ignore[reportPrivateUsage]


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


def test_cli_maint_clean_orphans_removes_tmp_runs_and_audit_tmp_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    monkeypatch.chdir(repo_root)

    state_dir = repo_root / ".ahadiff"
    orphan_run_dir = state_dir / "runs" / ".run_123.tmp"
    orphan_run_dir.mkdir(parents=True)
    (orphan_run_dir / "lesson.md").write_text("placeholder", encoding="utf-8")
    audit_tmp = state_dir / "audit.1.jsonl.gz.tmp"
    audit_tmp.parent.mkdir(parents=True, exist_ok=True)
    audit_tmp.write_text("tmp", encoding="utf-8")
    snapshot = state_dir / "audit.jsonl.rotation-src"
    snapshot.write_text("keep", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app(), ["maint", "clean-orphans"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "Removed" in result.stdout
    assert ".ahadiff/runs/.run_123.tmp" in result.stdout
    assert not orphan_run_dir.exists()
    assert not audit_tmp.exists()
    assert snapshot.exists()


def test_cli_maint_clean_orphans_dry_run_preserves_state_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    monkeypatch.chdir(repo_root)

    state_dir = repo_root / ".ahadiff"
    orphan_run_dir = state_dir / "runs" / ".run_456.tmp"
    orphan_run_dir.mkdir(parents=True)
    audit_tmp = state_dir / "audit.private.1.jsonl.gz.tmp"
    audit_tmp.parent.mkdir(parents=True, exist_ok=True)
    audit_tmp.write_text("tmp", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app(),
        ["maint", "clean-orphans", "--dry-run"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "Would remove" in result.stdout
    assert orphan_run_dir.exists()
    assert audit_tmp.exists()
