# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from ahadiff.contracts import ProviderConfig
from ahadiff.core.config import load_config, read_config_data, write_config_data
from ahadiff.llm import model_registry
from ahadiff.llm.model_registry import lookup_model_limits
from ahadiff.llm.probe import persist_probe_result

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    import pytest


def _repo(root: Path) -> Path:
    (root / ".git").mkdir(parents=True)
    (root / ".ahadiff").mkdir()
    return root


def _env_home(tmp_path: Path) -> dict[str, str]:
    return {"HOME": str(tmp_path / "home with spaces")}


def test_windows_style_repo_config_path_with_spaces_round_trips(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path / r"Users\Ada Lovelace\AppData\Local\AhaDiff Project")
    config_path = repo_root / ".ahadiff" / "config.toml"
    write_config_data(
        config_path,
        {"capture": {"mode": "manual", "max_files": 9, "hard_limit": 321}},
    )

    snapshot = load_config(repo_root, env=_env_home(tmp_path))

    assert snapshot.repo_config_path == config_path.resolve()
    assert snapshot.values["capture"]["mode"] == "manual"
    assert snapshot.values["capture"]["max_files"] == 9
    assert snapshot.values["capture"]["hard_limit"] == 321
    assert str(config_path.resolve()) in snapshot.resolved["capture.max_files"].source


def test_posix_repo_config_path_with_spaces_round_trips(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path / "Users" / "Ada Lovelace" / "Aha Diff Project")
    config_path = repo_root / ".ahadiff" / "config.toml"
    write_config_data(config_path, {"capture": {"mode": "manual", "max_files": 11}})

    snapshot = load_config(repo_root, env=_env_home(tmp_path))

    assert snapshot.repo_config_path == config_path.resolve()
    assert snapshot.values["capture"]["mode"] == "manual"
    assert snapshot.values["capture"]["max_files"] == 11
    assert str(config_path.resolve()) in snapshot.resolved["capture.max_files"].source


def test_unicode_repo_config_path_round_trips(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path / "项目 空间" / "知返 配置")
    config_path = repo_root / ".ahadiff" / "config.toml"
    write_config_data(config_path, {"capture": {"mode": "manual", "file_ranking": "path"}})

    snapshot = load_config(repo_root, env=_env_home(tmp_path))

    assert snapshot.repo_config_path == config_path.resolve()
    assert snapshot.values["capture"]["mode"] == "manual"
    assert snapshot.values["capture"]["file_ranking"] == "path"
    assert str(config_path.resolve()) in snapshot.resolved["capture.file_ranking"].source


def test_capture_mode_migration_handles_crlf_existing_config(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path / "repo with crlf config")
    config_path = repo_root / ".ahadiff" / "config.toml"
    config_path.write_bytes(b"[capture]\r\nmax_files = 12\r\n")

    snapshot = load_config(repo_root, env=_env_home(tmp_path))

    assert snapshot.values["capture"]["mode"] == "manual"
    assert snapshot.values["capture"]["max_files"] == 12
    assert snapshot.resolved["capture.mode"].source == "migration:capture-customized"


def test_model_registry_loads_json_from_pathlib_path_without_shell_interpolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_root = tmp_path / "registry dir with spaces $(should-not-run)"
    resource_root.mkdir()
    (resource_root / "model_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "models": [
                    {
                        "provider": "openai",
                        "model": "unit-path-model",
                        "max_context_tokens": 12345,
                        "max_input_tokens": 12345,
                        "max_output_tokens": 678,
                        "context_policy": "shared_pool",
                        "aliases": ["unit alias with spaces"],
                        "source": "UNIT-TEST-2026-05-22",
                        "confidence": "high",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_files(package: str) -> Path:
        assert package == "ahadiff.llm"
        return resource_root

    cast("Any", model_registry._load_registry_entries).cache_clear()
    monkeypatch.setattr(model_registry, "files", fake_files)
    try:
        limits = lookup_model_limits("openai", "unit alias with spaces")
    finally:
        cast("Any", model_registry._load_registry_entries).cache_clear()

    assert limits is not None
    assert limits.max_input_tokens == 12345
    assert limits.max_output_tokens == 678
    assert limits.source == "UNIT-TEST-2026-05-22"


def test_model_limits_name_with_special_chars_persists_through_probe_config(
    tmp_path: Path,
) -> None:
    repo_root = _repo(tmp_path / "repo with spaces")
    special_name = r"azure\deployments:gpt-4o:2024-08-06 preview+β"

    persist_probe_result(
        repo_root,
        provider_name="demo",
        config=ProviderConfig(
            provider_class="openai",
            model_name="deployment-prod",
            base_url="https://api.example.test/v1",
            api_key_env="AHADIFF_PROVIDER_API_KEY",
            model_limits_name=special_name,
            probed_max_input_tokens=128000,
            probed_max_output_tokens=16384,
            probed_limits_source="live",
        ),
    )

    payload = read_config_data(repo_root / ".ahadiff" / "config.toml")
    providers = cast("dict[str, dict[str, object]]", payload["providers"])
    snapshot = load_config(repo_root, env=_env_home(tmp_path))
    snapshot_providers = cast("dict[str, dict[str, object]]", snapshot.values["providers"])

    assert providers["demo"]["model_limits_name"] == special_name
    assert snapshot_providers["demo"]["model_limits_name"] == special_name
