# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

import httpx
import pytest

import ahadiff.llm.model_registry as model_registry
from ahadiff.contracts import ProviderConfig
from ahadiff.core.config import (
    PROVIDER_STALE_PROBE_FIELDS,
    clear_provider_probe_fields,
    load_config,
    read_config_data,
)
from ahadiff.llm.adapters.anthropic import AnthropicAdapter
from ahadiff.llm.adapters.azure import AzureOpenAIAdapter
from ahadiff.llm.adapters.gemini import GeminiAdapter
from ahadiff.llm.adapters.lmstudio import LMStudioAdapter
from ahadiff.llm.adapters.ollama import OllamaAdapter
from ahadiff.llm.adapters.openai import OpenAIChatAdapter
from ahadiff.llm.adapters.openai_compat import OpenAICompatAdapter
from ahadiff.llm.adapters.openai_responses import OpenAIResponsesAdapter
from ahadiff.llm.cost import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_OUTPUT_TOKEN_BUDGET,
    resolve_model_limits,
)
from ahadiff.llm.model_registry import lookup_model_limits
from ahadiff.llm.probe import _probe_context_window, _safe_positive_int, persist_probe_result
from ahadiff.llm.schemas import ProbeContextResult

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


def _config(
    provider_class: str,
    *,
    model_name: str = "gpt-4o",
    base_url: str = "http://127.0.0.1:8000",
    **overrides: object,
) -> ProviderConfig:
    payload: dict[str, object] = {
        "provider_class": provider_class,
        "model_name": model_name,
        "base_url": base_url,
        "api_key_env": "AHADIFF_PROVIDER_API_KEY",
    }
    payload.update(overrides)
    return ProviderConfig.model_validate(payload)


def _response(payload: object) -> httpx.Response:
    if payload is None:
        return httpx.Response(200, content=b"null")
    return httpx.Response(200, json=payload)


def _registry_payload(entries: list[dict[str, object]]) -> dict[str, object]:
    return {"schema_version": 1, "entries": entries}


def _registry_entry(
    provider: str,
    model: str,
    *,
    max_input_tokens: int | None = 1000,
    max_output_tokens: int | None = 100,
    aliases: list[str] | None = None,
) -> dict[str, object]:
    return {
        "provider": provider,
        "model": model,
        "mode": "chat",
        "max_input_tokens": max_input_tokens,
        "max_output_tokens": max_output_tokens,
        "aliases": aliases or [],
        "confidence": "registry",
    }


@pytest.fixture
def temp_model_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[object | str], None]]:
    def install(payload: object | str) -> None:
        raw_text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        (tmp_path / "model_registry.json").write_text(raw_text, encoding="utf-8")

        def fake_files(package: str) -> Path:
            assert package == "ahadiff.llm"
            return tmp_path

        model_registry._load_registry_entries_cached.cache_clear()
        monkeypatch.setattr(model_registry, "files", fake_files)

    yield install
    model_registry._load_registry_entries_cached.cache_clear()


def _assert_registry_fallback_warning(caplog: pytest.LogCaptureFixture) -> None:
    assert "failed to load model registry; using empty registry:" in caplog.text


def _context_probe_adapters() -> tuple[tuple[str, Any, str], ...]:
    return (
        (
            "anthropic",
            AnthropicAdapter(_config("anthropic", model_name="claude-sonnet-4-6")),
            "claude-sonnet-4-6",
        ),
        ("gemini", GeminiAdapter(_config("gemini", model_name="gemini-2.5-pro")), "gemini-2.5-pro"),
        ("lmstudio", LMStudioAdapter(_config("lmstudio", model_name="local-model")), "local-model"),
        ("ollama", OllamaAdapter(_config("ollama", model_name="llama3.1")), "llama3.1"),
        ("openai", OpenAIChatAdapter(_config("openai", model_name="gpt-4o")), "gpt-4o"),
        (
            "openai_compat",
            OpenAICompatAdapter(_config("newapi", model_name="served-model")),
            "served-model",
        ),
        (
            "openai_responses",
            OpenAIResponsesAdapter(_config("openai_responses", model_name="gpt-4o")),
            "gpt-4o",
        ),
    )


def test_probe_context_result_field_access() -> None:
    result = ProbeContextResult(
        max_context_tokens=128000,
        max_input_tokens=120000,
        max_output_tokens=8000,
        source="live",
        warnings=("sample",),
    )

    assert result.max_context_tokens == 128000
    assert result.max_input_tokens == 120000
    assert result.max_output_tokens == 8000
    assert result.source == "live"
    assert result.warnings == ("sample",)


def test_context_probe_parsers_ignore_non_object_or_unexpected_roots() -> None:
    malformed_payloads: tuple[object, ...] = (
        None,
        [],
        {},
        {"unexpected": {"limit": 128000}},
    )

    for payload in malformed_payloads:
        for name, adapter, model_name in _context_probe_adapters():
            result = adapter.parse_context_probe(_response(payload), model_name=model_name)
            assert result is None, name


def test_safe_positive_int_rejects_invalid_live_probe_limits() -> None:
    invalid_values: tuple[object, ...] = (
        -1,
        0,
        True,
        False,
        100_000_001,
        "128000",
        128000.0,
        "not-a-number",
    )

    for value in invalid_values:
        assert _safe_positive_int(value) is None
    assert _safe_positive_int(1) == 1
    assert _safe_positive_int(100_000_000) == 100_000_000


def test_context_probe_parsers_reject_invalid_limit_values() -> None:
    invalid_values: tuple[object, ...] = (
        -1,
        0,
        True,
        False,
        100_000_001,
        "128000",
        128000.0,
    )
    cases: tuple[tuple[str, Any, str, Callable[[object], object]], ...] = (
        (
            "anthropic",
            AnthropicAdapter(_config("anthropic", model_name="claude-sonnet-4-6")),
            "claude-sonnet-4-6",
            lambda value: {"max_input_tokens": value, "max_tokens": value},
        ),
        (
            "gemini",
            GeminiAdapter(_config("gemini", model_name="gemini-2.5-pro")),
            "gemini-2.5-pro",
            lambda value: {"inputTokenLimit": value, "outputTokenLimit": value},
        ),
        (
            "lmstudio",
            LMStudioAdapter(_config("lmstudio", model_name="local-model")),
            "local-model",
            lambda value: {
                "models": [
                    {
                        "id": "local-model",
                        "max_context_length": value,
                        "loaded_instances": [{"config": {"context_length": value}}],
                    }
                ]
            },
        ),
        (
            "ollama",
            OllamaAdapter(_config("ollama", model_name="llama3.1")),
            "llama3.1",
            lambda value: {
                "model_info": {"llama.context_length": value},
                "parameters": "",
            },
        ),
        (
            "openai",
            OpenAIChatAdapter(_config("openai", model_name="gpt-4o")),
            "gpt-4o",
            lambda value: {"data": [{"id": "gpt-4o", "context_window": value}]},
        ),
        (
            "openai_compat",
            OpenAICompatAdapter(_config("newapi", model_name="served-model")),
            "served-model",
            lambda value: {"data": [{"id": "served-model", "max_model_len": value}]},
        ),
        (
            "openai_responses",
            OpenAIResponsesAdapter(_config("openai_responses", model_name="gpt-4o")),
            "gpt-4o",
            lambda value: {"data": [{"id": "gpt-4o", "context_window": value}]},
        ),
    )

    for value in invalid_values:
        for name, adapter, model_name, payload_for in cases:
            result = adapter.parse_context_probe(
                _response(payload_for(value)),
                model_name=model_name,
            )
            assert result is None, f"{name}:{value!r}"


def test_openai_context_probe_does_not_guess_limits_from_paginated_miss() -> None:
    adapter = OpenAIChatAdapter(_config("openai", model_name="gpt-4o"))

    result = adapter.parse_context_probe(
        _response({"data": [{"id": "other-model", "context_window": 4096}], "has_more": True}),
        model_name="gpt-4o",
    )

    assert result is None


def test_anthropic_context_probe_request_and_parse_result() -> None:
    adapter = AnthropicAdapter(_config("anthropic", model_name="claude-sonnet-4-6"))
    context_request = adapter.build_context_probe_request(
        api_key="secret",
        model_name="claude-sonnet-4-6",
    )
    assert context_request is not None
    method, url, headers = context_request

    result = adapter.parse_context_probe(
        _response({"max_input_tokens": 200000, "max_tokens": 64000}),
        model_name="claude-sonnet-4-6",
    )

    assert method == "GET"
    assert url.endswith("/v1/models/claude-sonnet-4-6")
    assert headers["x-api-key"] == "secret"
    assert headers["anthropic-version"] == "2023-06-01"
    assert result == ProbeContextResult(
        max_context_tokens=None,
        max_input_tokens=200000,
        max_output_tokens=64000,
        source="live",
    )


def test_anthropic_context_probe_escapes_model_name_path_segment() -> None:
    adapter = AnthropicAdapter(_config("anthropic", model_name="safe/../evil?x=1#frag"))
    context_request = adapter.build_context_probe_request(
        api_key="secret",
        model_name="safe/../evil?x=1#frag",
    )
    assert context_request is not None
    _method, url, _headers = context_request
    parsed = urlsplit(url)

    assert parsed.query == ""
    assert parsed.fragment == ""
    assert parsed.path.endswith("/v1/models/safe%2F..%2Fevil%3Fx%3D1%23frag")


def test_gemini_context_probe_parses_split_limits() -> None:
    adapter = GeminiAdapter(_config("gemini", model_name="gemini-2.5-pro"))

    result = adapter.parse_context_probe(
        _response({"inputTokenLimit": 1048576, "outputTokenLimit": 65536}),
        model_name="gemini-2.5-pro",
    )

    assert result is not None
    assert result.max_context_tokens is None
    assert result.max_input_tokens == 1048576
    assert result.max_output_tokens == 65536
    assert result.source == "live"


def test_gemini_context_probe_escapes_model_name_path_segment() -> None:
    adapter = GeminiAdapter(_config("gemini", model_name="safe/../evil?x=1#frag"))
    context_request = adapter.build_context_probe_request(
        api_key="secret",
        model_name="safe/../evil?x=1#frag",
    )
    assert context_request is not None
    _method, url, _headers = context_request
    parsed = urlsplit(url)

    assert parsed.query == ""
    assert parsed.fragment == ""
    assert parsed.path.endswith("/v1beta/models/safe%2F..%2Fevil%3Fx%3D1%23frag")


def test_ollama_context_probe_uses_post_body_and_warns_on_lower_num_ctx() -> None:
    adapter = OllamaAdapter(_config("ollama", model_name="llama3.1"))
    method, url, headers, body = adapter.build_context_probe_request(
        api_key=None,
        model_name="llama3.1",
    )

    result = adapter.parse_context_probe(
        _response(
            {
                "model_info": {"llama.context_length": 131072},
                "parameters": "temperature 0.8\nnum_ctx 4096\n",
            }
        ),
        model_name="llama3.1",
    )

    assert method == "POST"
    assert url.endswith("/api/show")
    assert headers["content-type"] == "application/json"
    assert json.loads(body.decode("utf-8")) == {"name": "llama3.1"}
    assert result is not None
    assert result.max_context_tokens == 4096
    assert result.max_input_tokens is None
    assert result.max_output_tokens is None
    assert result.source == "live"
    assert result.warnings == ("ollama_num_ctx_below_architecture_context_length:4096<131072",)


def test_ollama_context_probe_does_not_exceed_architecture_context_length() -> None:
    adapter = OllamaAdapter(_config("ollama", model_name="llama3.1"))

    result = adapter.parse_context_probe(
        _response(
            {
                "model_info": {"llama.context_length": 8192},
                "parameters": "num_ctx 131072\n",
            }
        ),
        model_name="llama3.1",
    )

    assert result is not None
    assert result.max_context_tokens == 8192
    assert result.warnings == ()


def test_lmstudio_context_probe_prefers_loaded_instance_config() -> None:
    adapter = LMStudioAdapter(_config("lmstudio", model_name="local-model"))
    context_request = adapter.build_context_probe_request(
        api_key=None,
        model_name="local-model",
    )
    assert context_request is not None
    method, url, _headers = context_request

    result = adapter.parse_context_probe(
        _response(
            {
                "models": [
                    {
                        "id": "local-model",
                        "max_context_length": 4096,
                        "loaded_instances": [{"config": {"context_length": 32768}}],
                    }
                ]
            }
        ),
        model_name="local-model",
    )

    assert method == "GET"
    assert url.endswith("/api/v1/models")
    assert result == ProbeContextResult(
        max_context_tokens=32768,
        max_input_tokens=None,
        max_output_tokens=None,
        source="live",
    )


def test_lmstudio_context_probe_falls_back_to_max_context_length() -> None:
    adapter = LMStudioAdapter(_config("lmstudio", model_name="local-model"))

    result = adapter.parse_context_probe(
        _response({"data": [{"id": "local-model", "max_context_length": 8192}]}),
        model_name="local-model",
    )

    assert result is not None
    assert result.max_context_tokens == 8192


def test_openai_context_probes_wrap_legacy_context_window() -> None:
    payload = {"data": [{"id": "gpt-4o", "context_window": 128000}]}

    chat_result = OpenAIChatAdapter(_config("openai")).parse_context_probe(
        _response(payload),
        model_name="gpt-4o",
    )
    responses_result = OpenAIResponsesAdapter(_config("openai_responses")).parse_context_probe(
        _response(payload), model_name="gpt-4o"
    )

    for result in (chat_result, responses_result):
        assert result == ProbeContextResult(
            max_context_tokens=128000,
            max_input_tokens=None,
            max_output_tokens=None,
            source="live",
        )


def test_openai_compat_context_probe_prefers_vllm_max_model_len() -> None:
    adapter = OpenAICompatAdapter(_config("newapi", model_name="served-model"))

    result = adapter.parse_context_probe(
        _response(
            {
                "data": [
                    {
                        "id": "served-model",
                        "max_model_len": 65536,
                        "context_window": 32768,
                        "max_context_length": 16384,
                        "max_tokens": 8192,
                    }
                ]
            }
        ),
        model_name="served-model",
    )

    assert result is not None
    assert result.max_context_tokens == 65536
    assert result.max_input_tokens is None
    assert result.max_output_tokens is None


def test_azure_context_probe_stays_disabled() -> None:
    adapter = AzureOpenAIAdapter(_config("azure", model_name="deployment"))

    assert adapter.capabilities.supports_context_probe is False
    assert adapter.build_context_probe_request(api_key="secret", model_name="deployment") is None


def test_probe_context_window_sends_optional_body() -> None:
    class FakeAdapter:
        def build_context_probe_request(
            self,
            *,
            api_key: str | None,
            model_name: str,
        ) -> tuple[str, str, dict[str, str], bytes]:
            return "POST", "http://127.0.0.1:11434/api/show", {}, b'{"name":"llama3"}'

        def parse_context_probe(
            self,
            response: httpx.Response,
            *,
            model_name: str,
        ) -> ProbeContextResult:
            payload = response.json()
            return ProbeContextResult(
                max_context_tokens=int(payload["context_window"]),
                max_input_tokens=None,
                max_output_tokens=None,
                source="live",
            )

    class FakeClient:
        def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            raise AssertionError("context probe must use provider.request_context_probe")

    class FakeProvider:
        def __init__(self) -> None:
            self.adapter = FakeAdapter()
            self.config = _config("ollama", model_name="llama3")
            self.client = FakeClient()
            self.api_key = None
            self.seen_content: bytes | None = None

        def request_context_probe(
            self,
            *,
            method: str,
            url: str,
            headers: dict[str, str],
            content: bytes | None,
            privacy_mode: str,
        ) -> httpx.Response:
            assert method == "POST"
            assert url.endswith("/api/show")
            assert headers == {}
            assert privacy_mode == "explicit_remote"
            self.seen_content = content
            return _response({"context_window": 4096})

    provider = FakeProvider()
    result, source = _probe_context_window(provider, model_name="llama3")

    assert provider.seen_content == b'{"name":"llama3"}'
    assert source == "live"
    assert result.max_context_tokens == 4096


def test_probe_context_window_treats_empty_live_probe_as_fallback() -> None:
    class FakeAdapter:
        def build_context_probe_request(
            self,
            *,
            api_key: str | None,
            model_name: str,
        ) -> tuple[str, str, dict[str, str]]:
            return "GET", "http://127.0.0.1:8000/models", {}

        def parse_context_probe(
            self,
            response: httpx.Response,
            *,
            model_name: str,
        ) -> ProbeContextResult:
            return ProbeContextResult(
                max_context_tokens=None,
                max_input_tokens=None,
                max_output_tokens=None,
                source="live",
            )

    class FakeClient:
        def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            raise AssertionError("context probe must use provider.request_context_probe")

    class FakeProvider:
        def __init__(self) -> None:
            self.adapter = FakeAdapter()
            self.config = _config("openai", model_name="unknown-model")
            self.client = FakeClient()
            self.api_key = None

        def request_context_probe(
            self,
            *,
            method: str,
            url: str,
            headers: dict[str, str],
            content: bytes | None,
            privacy_mode: str,
        ) -> httpx.Response:
            assert method == "GET"
            assert url.endswith("/models")
            assert headers == {}
            assert content is None
            assert privacy_mode == "explicit_remote"
            return _response({})

    result, source = _probe_context_window(FakeProvider(), model_name="unknown-model")

    assert source == "fallback"
    assert result.source == "fallback"
    assert result.max_context_tokens == DEFAULT_CONTEXT_WINDOW


def test_lookup_model_limits_exact_prefix_alias_family_and_miss() -> None:
    exact = lookup_model_limits("openai", "gpt-4o")
    prefixed = lookup_model_limits("openai", "openai/gpt-4o")
    alias = lookup_model_limits("anthropic", "claude-3-7-sonnet-latest")
    family = lookup_model_limits("anthropic", "claude-sonnet-4-6-20260101")
    missing = lookup_model_limits("openai", "not-a-real-model")

    assert exact is not None
    assert exact.max_input_tokens == 128000
    assert prefixed is not None
    assert prefixed.max_output_tokens == 16384
    assert alias is not None
    assert alias.max_input_tokens == 200000
    assert family is not None
    assert family.max_output_tokens == 64000
    assert family.warnings == ("model limits matched version-family fallback: claude-sonnet-4-6",)
    assert missing is None


def test_lookup_model_limits_restricts_prefix_and_family_suffixes() -> None:
    cross_provider_prefix = lookup_model_limits("openai", "anthropic/gpt-4o")
    arbitrary_suffix = lookup_model_limits("openai", "gpt-4o-miniature")
    date_suffix = lookup_model_limits("openai", "gpt-4o-2024-08-06")

    assert cross_provider_prefix is None
    assert arbitrary_suffix is None
    assert date_suffix is not None
    assert date_suffix.max_input_tokens == 128000
    assert date_suffix.warnings == ("model limits matched version-family fallback: gpt-4o",)


def test_lookup_model_limits_uses_model_limits_name_escape_hatch() -> None:
    limits = lookup_model_limits("azure", "deployment-prod", model_limits_name="gpt-4o")
    prefixed_limits = lookup_model_limits(
        "azure",
        "deployment-prod",
        model_limits_name="openai/gpt-4o",
    )

    assert limits is not None
    assert limits.max_input_tokens == 128000
    assert limits.max_output_tokens == 16384
    assert prefixed_limits is not None
    assert prefixed_limits.max_input_tokens == 128000
    assert prefixed_limits.max_output_tokens == 16384


def test_registry_confidence_stays_distinct_from_live_probe_source() -> None:
    registry = lookup_model_limits("openai", "gpt-4o")
    registry_limits = resolve_model_limits("openai", "gpt-4o", _config("openai"))
    live_limits = resolve_model_limits(
        "openai",
        "gpt-4o",
        _config(
            "openai",
            probed_max_input_tokens=111000,
            probed_max_output_tokens=22000,
            probed_limits_source="live",
        ),
    )

    assert registry is not None
    assert registry.confidence == "registry"
    assert registry_limits.source == "registry"
    assert registry_limits.input_source == "registry"
    assert live_limits.source == "live"
    assert live_limits.input_source == "live"


def test_model_registry_invalid_schema_version_falls_back_to_empty(
    temp_model_registry: Callable[[object | str], None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=model_registry.__name__)
    temp_model_registry(
        {
            "schema_version": 2,
            "entries": [_registry_entry("openai", "fixture-model")],
        }
    )

    assert lookup_model_limits("openai", "fixture-model") is None
    _assert_registry_fallback_warning(caplog)


def test_model_registry_missing_entries_array_falls_back_to_empty(
    temp_model_registry: Callable[[object | str], None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=model_registry.__name__)
    temp_model_registry({"schema_version": 1})

    assert lookup_model_limits("openai", "fixture-model") is None
    _assert_registry_fallback_warning(caplog)


def test_model_registry_non_dict_json_falls_back_to_empty(
    temp_model_registry: Callable[[object | str], None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=model_registry.__name__)
    temp_model_registry([_registry_entry("openai", "fixture-model")])

    assert lookup_model_limits("openai", "fixture-model") is None
    _assert_registry_fallback_warning(caplog)


def test_model_registry_corrupt_json_falls_back_to_empty(
    temp_model_registry: Callable[[object | str], None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=model_registry.__name__)
    temp_model_registry('{"schema_version":1,"entries":[')

    assert model_registry._load_registry_entries() == ()
    assert lookup_model_limits("openai", "fixture-model") is None
    _assert_registry_fallback_warning(caplog)


def test_model_registry_invalid_entry_falls_back_to_empty(
    temp_model_registry: Callable[[object | str], None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=model_registry.__name__)
    temp_model_registry(_registry_payload([{"provider": "openai", "model": "fixture-model"}]))

    assert lookup_model_limits("openai", "fixture-model") is None
    _assert_registry_fallback_warning(caplog)


def test_model_registry_failed_load_does_not_poison_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry_path = tmp_path / "model_registry.json"

    def fake_files(package: str) -> Path:
        assert package == "ahadiff.llm"
        return tmp_path

    caplog.set_level(logging.WARNING, logger=model_registry.__name__)
    model_registry._load_registry_entries_cached.cache_clear()
    monkeypatch.setattr(model_registry, "files", fake_files)

    registry_path.write_text('{"schema_version":1,"entries":[', encoding="utf-8")
    assert lookup_model_limits("openai", "retry-model") is None
    assert model_registry._load_registry_entries_cached.cache_info().currsize == 0
    _assert_registry_fallback_warning(caplog)

    registry_path.write_text(
        json.dumps(
            _registry_payload([_registry_entry("openai", "retry-model", max_input_tokens=3210)]),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    limits = lookup_model_limits("openai", "retry-model")

    assert limits is not None
    assert limits.max_input_tokens == 3210


def test_model_registry_empty_entries_lookup_does_not_crash(
    temp_model_registry: Callable[[object | str], None],
) -> None:
    temp_model_registry(_registry_payload([]))

    assert lookup_model_limits("openai", "fixture-model") is None


def test_model_registry_duplicate_entries_first_match_wins(
    temp_model_registry: Callable[[object | str], None],
) -> None:
    temp_model_registry(
        _registry_payload(
            [
                _registry_entry("openai", "duplicate-model", max_input_tokens=111),
                _registry_entry("openai", "duplicate-model", max_input_tokens=222),
            ]
        )
    )

    limits = lookup_model_limits("openai", "duplicate-model")

    assert limits is not None
    assert limits.max_input_tokens == 111


def test_model_registry_unicode_model_names_lookup(
    temp_model_registry: Callable[[object | str], None],
) -> None:
    temp_model_registry(
        _registry_payload(
            [
                _registry_entry(
                    "openai_compat",
                    "模型-α",
                    max_input_tokens=4096,
                    max_output_tokens=512,
                    aliases=["模型-β"],
                )
            ]
        )
    )

    exact = lookup_model_limits("newapi", "模型-α")
    alias = lookup_model_limits("newapi", "模型-β")

    assert exact is not None
    assert exact.max_input_tokens == 4096
    assert alias is not None
    assert alias.max_output_tokens == 512


def test_model_registry_cache_clear_after_reload(
    temp_model_registry: Callable[[object | str], None],
) -> None:
    temp_model_registry(
        _registry_payload([_registry_entry("openai", "reload-model", max_input_tokens=1000)])
    )
    first = lookup_model_limits("openai", "reload-model")
    assert first is not None
    assert first.max_input_tokens == 1000
    assert model_registry._load_registry_entries_cached.cache_info().currsize == 1

    temp_model_registry(
        _registry_payload([_registry_entry("openai", "reload-model", max_input_tokens=2000)])
    )
    second = lookup_model_limits("openai", "reload-model")

    assert second is not None
    assert second.max_input_tokens == 2000


def test_model_registry_concurrent_access_is_deterministic(
    temp_model_registry: Callable[[object | str], None],
) -> None:
    temp_model_registry(
        _registry_payload(
            [
                _registry_entry(
                    "openai",
                    "threaded-model",
                    max_input_tokens=8192,
                    max_output_tokens=1024,
                )
            ]
        )
    )

    def lookup(_: int) -> tuple[int | None, int | None]:
        limits = lookup_model_limits("openai", "threaded-model")
        assert limits is not None
        return limits.max_input_tokens, limits.max_output_tokens

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(lookup, range(64)))

    assert set(results) == {(8192, 1024)}


def test_resolve_model_limits_prefers_live_split_limits() -> None:
    limits = resolve_model_limits(
        "openai",
        "gpt-4o",
        _config(
            "openai",
            probed_max_input_tokens=111000,
            probed_max_output_tokens=22000,
            probed_limits_source="live",
        ),
    )

    assert limits.max_context_tokens == 133000
    assert limits.max_input_tokens == 111000
    assert limits.max_output_tokens == 22000
    assert limits.source == "live"
    assert limits.input_source == "live"
    assert limits.output_source == "live"


def test_resolve_model_limits_mixes_live_and_registry_sources() -> None:
    limits = resolve_model_limits(
        "openai",
        "gpt-4o",
        _config("openai", probed_max_input_tokens=100000),
    )

    assert limits.max_input_tokens == 100000
    assert limits.max_output_tokens == 16384
    assert limits.source == "mixed"
    assert limits.input_source == "live"
    assert limits.output_source == "registry"


def test_resolve_model_limits_uses_registry_before_legacy_context() -> None:
    limits = resolve_model_limits(
        "gemini",
        "models/gemini-2.5-pro",
        _config("gemini", model_name="models/gemini-2.5-pro", probed_max_context=4096),
    )

    assert limits.max_context_tokens == 1114112
    assert limits.max_input_tokens == 1048576
    assert limits.max_output_tokens == 65536
    assert limits.source == "registry"


def test_resolve_model_limits_does_not_add_default_output_to_known_split_input() -> None:
    limits = resolve_model_limits(
        "ollama",
        "llama3.1",
        _config("ollama", model_name="llama3.1"),
    )

    assert limits.max_context_tokens == 131072
    assert limits.max_input_tokens == 131072
    assert limits.max_output_tokens == DEFAULT_OUTPUT_TOKEN_BUDGET
    assert limits.source == "mixed"
    assert limits.input_source == "registry"
    assert limits.output_source == "default"


def test_resolve_model_limits_falls_back_to_legacy_context_and_defaults() -> None:
    limits = resolve_model_limits(
        "openai",
        "unknown-model",
        _config("openai", model_name="unknown-model", probed_max_context=77777),
    )

    assert limits.max_context_tokens == 77777
    assert limits.max_input_tokens == 77777
    assert limits.max_output_tokens == DEFAULT_OUTPUT_TOKEN_BUDGET
    assert limits.source == "default"
    assert limits.input_source == "total_derived"
    assert limits.output_source == "default"


def test_resolve_model_limits_uses_default_without_probe_or_registry() -> None:
    limits = resolve_model_limits(
        "openai",
        "unknown-model",
        _config("openai", model_name="unknown-model"),
    )

    assert limits.max_context_tokens == DEFAULT_CONTEXT_WINDOW
    assert limits.max_input_tokens == DEFAULT_CONTEXT_WINDOW
    assert limits.max_output_tokens == DEFAULT_OUTPUT_TOKEN_BUDGET
    assert limits.source == "default"


def test_resolve_model_limits_ignores_stale_legacy_context_when_split_limits_exist() -> None:
    limits = resolve_model_limits(
        "openai",
        "gpt-4o",
        _config(
            "openai",
            probed_max_context=4096,
            probed_max_input_tokens=128000,
            probed_max_output_tokens=24000,
        ),
    )

    assert limits.max_context_tokens == 152000
    assert limits.max_input_tokens == 128000
    assert limits.max_output_tokens == 24000
    assert limits.input_source == "live"
    assert limits.output_source == "live"


@pytest.mark.parametrize("model_name", ["", "   ", "模型-" + "x" * 1200])
def test_lookup_model_limits_handles_empty_and_very_long_names(model_name: str) -> None:
    assert lookup_model_limits("openai", model_name) is None


def test_provider_config_new_fields_round_trip_and_old_configs_still_validate() -> None:
    old_config = ProviderConfig.model_validate(
        {
            "provider_class": "openai",
            "model_name": "gpt-4o",
            "base_url": "https://api.example.test/v1",
            "api_key_env": "AHADIFF_PROVIDER_API_KEY",
        }
    )
    new_config = ProviderConfig.model_validate(
        {
            **old_config.model_dump(mode="python"),
            "probed_max_input_tokens": 128000,
            "probed_max_output_tokens": 16384,
            "probed_limits_source": "live",
            "model_limits_name": "gpt-4o",
        }
    )

    assert old_config.probed_max_input_tokens is None
    assert old_config.probed_max_output_tokens is None
    assert old_config.probed_limits_source is None
    assert old_config.model_limits_name is None
    assert new_config.model_dump(mode="json")["probed_max_input_tokens"] == 128000
    assert new_config.model_dump(mode="json")["model_limits_name"] == "gpt-4o"


def test_stale_probe_fields_include_new_probe_fields_but_not_model_limits_name() -> None:
    assert "probed_max_input_tokens" in PROVIDER_STALE_PROBE_FIELDS
    assert "probed_max_output_tokens" in PROVIDER_STALE_PROBE_FIELDS
    assert "probed_limits_source" in PROVIDER_STALE_PROBE_FIELDS
    assert "model_limits_name" not in PROVIDER_STALE_PROBE_FIELDS


def test_clear_provider_probe_fields_clears_new_fields() -> None:
    provider: dict[str, object] = {
        "probed_max_context": 100,
        "probed_max_input_tokens": 90,
        "probed_max_output_tokens": 10,
        "probed_limits_source": "live",
        "model_limits_name": "gpt-4o",
    }

    clear_provider_probe_fields(provider)

    assert "probed_max_context" not in provider
    assert "probed_max_input_tokens" not in provider
    assert "probed_max_output_tokens" not in provider
    assert "probed_limits_source" not in provider
    assert provider["model_limits_name"] == "gpt-4o"


def test_persist_probe_result_writes_split_limit_fields(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    (repo_root / ".ahadiff").mkdir()

    persist_probe_result(
        repo_root,
        provider_name="demo",
        config=_config(
            "openai",
            probed_max_context=144000,
            probed_max_input_tokens=128000,
            probed_max_output_tokens=16000,
            probed_limits_source="live",
            probe_timestamp="2026-05-21T00:00:00Z",
        ),
    )

    payload = read_config_data(repo_root / ".ahadiff" / "config.toml")
    provider = cast("dict[str, object]", cast("dict[str, object]", payload["providers"])["demo"])
    assert provider["probed_max_context"] == 144000
    assert provider["probed_max_input_tokens"] == 128000
    assert provider["probed_max_output_tokens"] == 16000
    assert provider["probed_limits_source"] == "live"


def test_load_config_accepts_new_and_old_provider_fields(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    (repo_root / ".ahadiff").mkdir()
    (repo_root / ".ahadiff" / "config.toml").write_text(
        "[providers.old]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-4o"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n\n'
        "[providers.new]\n"
        'provider_class = "azure"\n'
        'model_name = "deployment-prod"\n'
        'base_url = "https://example.openai.azure.com"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n'
        'model_limits_name = "gpt-4o"\n'
        "probed_max_input_tokens = 128000\n"
        "probed_max_output_tokens = 16384\n"
        'probed_limits_source = "live"\n',
        encoding="utf-8",
    )

    snapshot = load_config(repo_root, env={"HOME": str(tmp_path / "home")})
    providers = cast("dict[str, dict[str, object]]", snapshot.values["providers"])

    assert snapshot.repo_unknown_keys == ()
    assert providers["old"]["model_name"] == "gpt-4o"
    assert providers["new"]["model_limits_name"] == "gpt-4o"
    assert providers["new"]["probed_max_input_tokens"] == 128000
