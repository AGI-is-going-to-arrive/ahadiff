from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from typer.testing import CliRunner

from ahadiff import cli as cli_module
from ahadiff.cli import app
from ahadiff.contracts import ProviderConfig
from ahadiff.core.config import load_config, read_config_data
from ahadiff.core.errors import InputError
from ahadiff.llm import persist_probe_result, probe_provider
from ahadiff.llm.provider import reset_provider_runtime_state

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


def _init_git_repo(root: Path) -> None:
    (root / ".git").mkdir()


@pytest.fixture(autouse=True)
def _reset_provider_runtime_state() -> Generator[None, None, None]:  # pyright: ignore[reportUnusedFunction]
    reset_provider_runtime_state()
    yield
    reset_provider_runtime_state()


def test_probe_provider_reads_headers_and_context_probe_and_persists_result(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"data": [{"id": "gpt-5.4-mini", "context_window": 123456}]},
            )
        payload = json.loads(request.content.decode("utf-8"))
        content = payload["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "model": "gpt-5.4-mini",
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
            headers={
                "x-ratelimit-limit-requests": "12",
                "x-ratelimit-limit-tokens": "3456",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    report = probe_provider(
        provider_name="demo",
        provider_class="openai",
        model_name="gpt-5.4-mini",
        base_url="http://127.0.0.1:8000",
        api_key="test-key",
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        workspace_root=repo_root,
        security_config=None,
        client=client,
    )

    snapshot = load_config(repo_root, env={"HOME": str(tmp_path / "home")})
    raw_config = read_config_data(repo_root / ".ahadiff" / "config.toml")

    assert report.config.probed_max_context == 123456
    assert report.config.probed_rpm == 12
    assert report.config.probed_tpm == 3456
    assert report.context_window_source == "live"
    assert snapshot.repo_unknown_keys == ()
    assert raw_config["providers"]["demo"]["probed_max_context"] == 123456


def test_probe_provider_falls_back_when_context_probe_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "model": "gpt-5.4-mini",
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    report = probe_provider(
        provider_name="demo",
        provider_class="openai",
        model_name="gpt-5.4-mini",
        base_url="http://127.0.0.1:8000",
        api_key="test-key",
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        workspace_root=repo_root,
        security_config=None,
        client=client,
    )

    assert report.config.probed_max_context == 1_000_000
    assert report.context_window_source == "fallback"


def test_probe_provider_allows_remote_targets_by_default(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"data": [{"id": "gpt-5.4-mini", "context_window": 123456}]},
            )
        return httpx.Response(
            200,
            json={
                "model": "gpt-5.4-mini",
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    report = probe_provider(
        provider_name="demo",
        provider_class="openai",
        model_name="gpt-5.4-mini",
        base_url="https://api.openai.com",
        api_key="test-key",
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        workspace_root=repo_root,
        security_config=None,
        client=client,
        persist_result=False,
    )

    assert report.connectivity_ok is True
    assert report.transport_target == "remote"


def test_provider_cli_outputs_capabilities_table_and_persists_probe_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()
    (repo_root / ".ahadiff" / "config.toml").write_text(
        '[pricing.input_per_million_usd]\n"openrouter/custom.model" = 0.4\n\n'
        '[pricing.output_per_million_usd]\n"openrouter/custom.model" = 1.6\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    # The CLI imports probe_provider directly, so patch that name with a tiny stub.
    def cli_probe_provider(**kwargs: Any):
        from ahadiff.contracts import ProviderConfig
        from ahadiff.llm.adapters.openai import OpenAIChatAdapter
        from ahadiff.llm.schemas import ProbeReport

        config = ProviderConfig(
            provider_class="openai",
            model_name="gpt-5.4-mini",
            base_url="http://127.0.0.1:8000",
            api_key_env="AHADIFF_PROVIDER_API_KEY",
            probed_max_context=123456,
            probed_tpm=222,
            probed_rpm=33,
            supports_temperature=True,
            probe_timestamp="2026-04-22T00:00:00Z",
        )
        persist_probe_result(repo_root, provider_name="demo", config=config)
        return ProbeReport(
            provider_name="demo",
            config=config,
            capabilities=OpenAIChatAdapter(config).capabilities,
            connectivity_ok=True,
            transport_target="local",
            context_window_source="live",
            notes=("ok",),
        )

    monkeypatch.setattr(cli_module, "probe_provider", cli_probe_provider)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "provider",
            "test",
            "--name",
            "demo",
            "--base-url",
            "http://127.0.0.1:8000",
            "--repo-root",
            str(repo_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "Provider probe succeeded" in result.stdout
    assert "supports_context_probe" in result.stdout
    resolved = runner.invoke(
        app(),
        ["config", "show", "--resolved", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )
    assert resolved.exit_code == 0
    assert "providers.demo.base_url" in resolved.stdout
    plain = runner.invoke(
        app(),
        ["config", "show", "--repo-root", str(repo_root)],
        catch_exceptions=False,
    )
    assert plain.exit_code == 0
    assert "pricing.input_per_million_usd.openrouter/custom.model = 0.4" in plain.stdout
    assert load_config(repo_root, env={"HOME": str(tmp_path / "home")}).repo_unknown_keys == ()


@pytest.mark.parametrize("provider_class", ["openai", "newapi", "cherryin"])
def test_provider_cli_normalizes_chat_completions_base_url_before_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_class: str,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()
    captured: dict[str, object] = {}

    def cli_probe_provider(**kwargs: Any):
        from ahadiff.llm.adapters.openai import OpenAIChatAdapter
        from ahadiff.llm.schemas import ProbeReport

        captured["base_url"] = kwargs["base_url"]
        config = ProviderConfig(
            provider_class=provider_class,  # pyright: ignore[reportArgumentType]
            model_name="gpt-5.4-mini",
            base_url=str(kwargs["base_url"]),
            api_key_env="AHADIFF_PROVIDER_API_KEY",
            probed_max_context=123456,
            supports_temperature=True,
            probe_timestamp="2026-04-22T00:00:00Z",
        )
        return ProbeReport(
            provider_name="demo",
            config=config,
            capabilities=OpenAIChatAdapter(config).capabilities,
            connectivity_ok=True,
            transport_target="local",
            context_window_source="live",
            notes=("ok",),
        )

    monkeypatch.setattr(cli_module, "probe_provider", cli_probe_provider)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "provider",
            "test",
            "--name",
            "demo",
            "--provider-class",
            provider_class,
            "--base-url",
            "http://127.0.0.1:8318/v1/chat/completions",
            "--repo-root",
            str(repo_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["base_url"] == "http://127.0.0.1:8318"


def test_provider_cli_normalizes_openai_responses_base_url_before_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()
    captured: dict[str, object] = {}

    def cli_probe_provider(**kwargs: Any):
        from ahadiff.llm.adapters.openai_responses import OpenAIResponsesAdapter
        from ahadiff.llm.schemas import ProbeReport

        captured["base_url"] = kwargs["base_url"]
        config = ProviderConfig(
            provider_class="openai_responses",
            model_name="gpt-5.4-mini",
            base_url=str(kwargs["base_url"]),
            api_key_env="AHADIFF_PROVIDER_API_KEY",
            probed_max_context=123456,
            supports_temperature=True,
            probe_timestamp="2026-04-22T00:00:00Z",
        )
        return ProbeReport(
            provider_name="demo",
            config=config,
            capabilities=OpenAIResponsesAdapter(config).capabilities,
            connectivity_ok=True,
            transport_target="local",
            context_window_source="live",
            notes=("ok",),
        )

    monkeypatch.setattr(cli_module, "probe_provider", cli_probe_provider)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "provider",
            "test",
            "--name",
            "demo",
            "--provider-class",
            "openai_responses",
            "--base-url",
            "http://127.0.0.1:8318/v1/responses",
            "--repo-root",
            str(repo_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["base_url"] == "http://127.0.0.1:8318"


def test_provider_cli_can_fallback_to_api_key_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key-from-env")

    def cli_probe_provider(**kwargs: Any):
        assert kwargs["api_key"] == "test-key-from-env"
        from ahadiff.contracts import ProviderConfig
        from ahadiff.llm.adapters.openai import OpenAIChatAdapter
        from ahadiff.llm.schemas import ProbeReport

        config = ProviderConfig(
            provider_class="openai",
            model_name="gpt-5.4-mini",
            base_url="http://127.0.0.1:8000",
            api_key_env="AHADIFF_PROVIDER_API_KEY",
            probed_max_context=123456,
            supports_temperature=True,
            probe_timestamp="2026-04-22T00:00:00Z",
        )
        return ProbeReport(
            provider_name="demo",
            config=config,
            capabilities=OpenAIChatAdapter(config).capabilities,
            connectivity_ok=True,
            transport_target="local",
            context_window_source="live",
            notes=("ok",),
        )

    monkeypatch.setattr(cli_module, "probe_provider", cli_probe_provider)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "provider",
            "test",
            "--name",
            "demo",
            "--base-url",
            "http://127.0.0.1:8000",
            "--repo-root",
            str(repo_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0


def test_provider_cli_allows_local_provider_without_api_key_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()

    def cli_probe_provider(**kwargs: Any):
        assert kwargs["api_key"] is None
        assert kwargs["privacy_mode"] == "strict_local"
        from ahadiff.contracts import ProviderConfig
        from ahadiff.llm.adapters.openai import OpenAIChatAdapter
        from ahadiff.llm.schemas import ProbeReport

        config = ProviderConfig(
            provider_class="openai",
            model_name="gpt-5.4-mini",
            base_url="http://127.0.0.1:8000",
            api_key_env="AHADIFF_PROVIDER_API_KEY",
            probed_max_context=123456,
            supports_temperature=True,
            probe_timestamp="2026-04-22T00:00:00Z",
        )
        return ProbeReport(
            provider_name="demo",
            config=config,
            capabilities=OpenAIChatAdapter(config).capabilities,
            connectivity_ok=True,
            transport_target="local",
            context_window_source="live",
            notes=("ok",),
        )

    monkeypatch.setattr(cli_module, "probe_provider", cli_probe_provider)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "provider",
            "test",
            "--name",
            "demo",
            "--base-url",
            "http://127.0.0.1:8000",
            "--repo-root",
            str(repo_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0


def test_provider_cli_defaults_remote_probe_to_explicit_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")

    def cli_probe_provider(**kwargs: Any):
        assert kwargs["api_key"] == "test-key"
        assert kwargs["privacy_mode"] == "explicit_remote"
        from ahadiff.contracts import ProviderConfig
        from ahadiff.llm.adapters.openai import OpenAIChatAdapter
        from ahadiff.llm.schemas import ProbeReport

        config = ProviderConfig(
            provider_class="openai",
            model_name="gpt-5.4-mini",
            base_url="https://api.openai.com",
            api_key_env="AHADIFF_PROVIDER_API_KEY",
            probed_max_context=123456,
            supports_temperature=True,
            probe_timestamp="2026-04-22T00:00:00Z",
        )
        return ProbeReport(
            provider_name="demo",
            config=config,
            capabilities=OpenAIChatAdapter(config).capabilities,
            connectivity_ok=True,
            transport_target="remote",
            context_window_source="live",
            notes=("ok",),
        )

    monkeypatch.setattr(cli_module, "probe_provider", cli_probe_provider)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "provider",
            "test",
            "--name",
            "demo",
            "--base-url",
            "https://api.openai.com",
            "--repo-root",
            str(repo_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0


def test_provider_cli_rejects_plaintext_api_key_argument(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "provider",
            "test",
            "--name",
            "demo",
            "--base-url",
            "http://127.0.0.1:8000",
            "--api-key",
            "plaintext",
            "--repo-root",
            str(repo_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "Passing raw API keys on the command line is not allowed" in result.stderr


def test_provider_cli_rejects_invalid_provider_class_as_cli_error(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "provider",
            "test",
            "--name",
            "demo",
            "--provider-class",
            "bogus",
            "--base-url",
            "http://127.0.0.1:8000",
            "--repo-root",
            str(repo_root),
        ],
    )

    assert result.exit_code == 1
    assert "invalid provider configuration" in result.stderr
    assert "Unexpected error" not in result.stderr


def test_persist_probe_result_rejects_aliases_with_dot(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()

    with pytest.raises(InputError, match="must not contain"):
        persist_probe_result(
            repo_root,
            provider_name="demo.alias",
            config=ProviderConfig(
                provider_class="openai",
                model_name="gpt-5.4-mini",
                base_url="http://127.0.0.1:8000",
                api_key_env="AHADIFF_PROVIDER_API_KEY",
            ),
        )
