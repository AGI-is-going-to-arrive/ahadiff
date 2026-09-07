"""Model/protocol thinking contracts, without live inference or credentials."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from pydantic import ValidationError

from ahadiff.contracts import ProviderConfig
from ahadiff.core import config as config_module
from ahadiff.core import paths as paths_module
from ahadiff.core.errors import ProviderError
from ahadiff.llm import make_provider
from ahadiff.llm import provider as provider_module
from ahadiff.llm.adapters.anthropic import AnthropicAdapter
from ahadiff.llm.adapters.azure import AzureOpenAIAdapter
from ahadiff.llm.adapters.gemini import GeminiAdapter
from ahadiff.llm.adapters.ollama import OllamaAdapter
from ahadiff.llm.adapters.openai import OpenAIChatAdapter
from ahadiff.llm.adapters.openai_compat import OpenAICompatAdapter
from ahadiff.llm.adapters.openai_responses import OpenAIResponsesAdapter
from ahadiff.llm.adapters.thinking import thinking_policy_for
from ahadiff.llm.provider import reset_provider_runtime_state
from ahadiff.llm.schemas import ProviderRequest, ProviderResponse

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ahadiff.contracts import ProviderClass
    from ahadiff.llm.provider import AdapterBase


@pytest.fixture(autouse=True)
def _isolated_provider_state(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    def isolated_global_dir(**kwargs: object) -> Path:
        return tmp_path / "global-config"

    monkeypatch.setattr(paths_module, "global_config_dir", isolated_global_dir)
    monkeypatch.setattr(config_module, "global_config_dir", isolated_global_dir)
    reset_provider_runtime_state()
    yield
    reset_provider_runtime_state()


def _config(
    provider: ProviderClass, model: str, base_url: str = "http://127.0.0.1:8000"
) -> ProviderConfig:
    return ProviderConfig(
        provider_class=provider, model_name=model, base_url=base_url, api_key_env="TEST_KEY"
    )


def _request(model: str, level: str | None = None) -> ProviderRequest:
    return ProviderRequest(
        model=model,
        thinking_level=level,
        prompt_name="test",
        prompt_fingerprint="v1",
        prompt_version="v1",
        eval_bundle_version="v1",
        payload_text="Reply OK.",
        diff_content="synthetic fixture",
        source_ref="test",
        max_output_tokens=128,
    )


@pytest.mark.parametrize(
    "level", [None, "none", "minimal", "low", "medium", "high", "xhigh", "max", "enabled"]
)
def test_provider_config_round_trips_all_canonical_levels(level: str | None) -> None:
    config = _config("openai_responses", "gpt-5.6-luna")
    parsed = ProviderConfig.model_validate({**config.model_dump(), "thinking_level": level})
    assert parsed.model_dump()["thinking_level"] == level


def test_provider_config_rejects_agent_harness_only_effort() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig.model_validate(
            {**_config("openai", "gpt-6-astra").model_dump(), "thinking_level": "ultra"}
        )


@pytest.mark.parametrize(
    "adapter_cls,provider",
    [
        (OpenAIChatAdapter, "openai"),
        (OpenAICompatAdapter, "openai_compat"),
        (OpenAIResponsesAdapter, "openai_responses"),
    ],
)
@pytest.mark.parametrize("level", [None, "none", "max"])
def test_openai_defaults_disable_and_max_are_distinct(
    adapter_cls: type[AdapterBase], provider: ProviderClass, level: str | None
) -> None:
    adapter = adapter_cls(_config(provider, "gpt-5.6-luna"))
    payload = adapter.build_request(_request("gpt-5.6-luna", level), api_key=None)[3]
    if level is None:
        assert "reasoning" not in payload and "reasoning_effort" not in payload
    elif provider == "openai_responses":
        assert payload["reasoning"] == {"effort": level}
    else:
        assert payload["reasoning_effort"] == level
    token_key = "max_output_tokens" if provider == "openai_responses" else "max_completion_tokens"
    assert payload[token_key] == 128
    assert "max_tokens" not in payload


@pytest.mark.parametrize(
    "provider,model,level",
    [
        ("openai_responses", "gpt-6-astra", "none"),
        ("openai_responses", "gpt-5.6-luna", "ultra"),
        ("openai_responses", "gpt-4o", "high"),
        ("openai_responses", "unknown-new-model", "high"),
        ("openai_responses", "gpt-6-astra-lookalike", "high"),
        ("openai", "gpt-5", "none"),
        ("openai", "o3", "max"),
        ("anthropic", "claude-fable-5-1", "none"),
        ("anthropic", "claude-sonnet-4-6", "xhigh"),
        ("anthropic", "claude-haiku-99", "high"),
        ("gemini", "gemini-3.8-flash", "minimal"),
        ("gemini", "gemini-3.7-flash", "none"),
        ("gemini", "gemini-2.5-pro", "none"),
        ("ollama", "gpt-oss:20b", "none"),
        ("ollama", "llama3.1", "enabled"),
    ],
)
def test_invalid_model_effort_rejected_before_network(
    provider: ProviderClass, model: str, level: str
) -> None:
    def reject_network(_: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid settings must never invoke inference")

    with (
        httpx.Client(transport=httpx.MockTransport(reject_network), trust_env=False) as client,
        make_provider(_config(provider, model), api_key=None, client=client) as managed,
        pytest.raises(ProviderError, match="does not support thinking_level"),
    ):
        managed.generate(_request(model, level))


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-opus-4-7",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5-1",
    ],
)
def test_anthropic_adaptive_wire_shape(model: str) -> None:
    payload = AnthropicAdapter(_config("anthropic", model)).build_request(
        _request(model, "high"), api_key=None
    )[3]
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"] == {"effort": "high"}
    assert "budget_tokens" not in payload["thinking"]


@pytest.mark.parametrize(
    "adapter_cls,provider,model,expected",
    [
        (AnthropicAdapter, "anthropic", "claude-opus-5", {"thinking": {"type": "disabled"}}),
        (
            GeminiAdapter,
            "gemini",
            "gemini-2.5-flash",
            {"generationConfig": {"maxOutputTokens": 128, "thinkingConfig": {"thinkingBudget": 0}}},
        ),
        (OllamaAdapter, "ollama", "qwen3:8b", {"think": False}),
    ],
)
def test_explicit_disable_is_sent(
    adapter_cls: type[AdapterBase], provider: ProviderClass, model: str, expected: dict[str, object]
) -> None:
    adapter = adapter_cls(_config(provider, model))
    payload = adapter.build_request(_request(model, "none"), api_key=None)[3]
    for key, value in expected.items():
        assert payload[key] == value
    default_payload = adapter.build_request(_request(model), api_key=None)[3]
    for key in ("thinking", "think"):
        assert key not in default_payload
    assert "thinkingConfig" not in default_payload.get("generationConfig", {})


@pytest.mark.parametrize(
    "model,level,expected",
    [
        ("gemini-2.5-pro", "high", {"thinkingBudget": 8192}),
        ("gemini-2.5-flash-lite", "low", {"thinkingBudget": 1024}),
        ("gemini-3.5-flash", "minimal", {"thinkingLevel": "minimal"}),
        ("gemini-3.6-flash", "medium", {"thinkingLevel": "medium"}),
        ("gemini-3.8-flash", "low", {"thinkingLevel": "low"}),
    ],
)
def test_gemini_uses_model_specific_thinking_control(
    model: str, level: str, expected: dict[str, object]
) -> None:
    request = _request(model, level)
    if "thinkingBudget" in expected:
        request = replace(request, max_output_tokens=9000)
    payload = GeminiAdapter(_config("gemini", model)).build_request(request, api_key=None)[3]
    assert payload["generationConfig"]["thinkingConfig"] == expected


@pytest.mark.parametrize(
    "provider,adapter_cls,base,model,level,expected",
    [
        (
            "openai",
            OpenAIChatAdapter,
            "https://api.deepseek.com",
            "deepseek-v4-pro",
            "max",
            {"thinking": {"type": "enabled"}, "reasoning_effort": "max"},
        ),
        (
            "openai",
            OpenAIChatAdapter,
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            "none",
            {"thinking": {"type": "disabled"}},
        ),
        (
            "openai_responses",
            OpenAIResponsesAdapter,
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            "none",
            {"reasoning": {"effort": "none"}},
        ),
        (
            "anthropic",
            AnthropicAdapter,
            "https://api.deepseek.com/anthropic",
            "deepseek-v4-pro",
            "low",
            {"thinking": {"type": "enabled"}, "output_config": {"effort": "low"}},
        ),
        (
            "openai_compat",
            OpenAICompatAdapter,
            "https://api.z.ai/api/paas/v4",
            "glm-5.3",
            "low",
            {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
        ),
        (
            "openai_compat",
            OpenAICompatAdapter,
            "https://api.z.ai/api/paas/v4",
            "glm-5.2",
            "none",
            {"thinking": {"type": "disabled"}},
        ),
        (
            "openai_compat",
            OpenAICompatAdapter,
            "https://api.moonshot.ai/v1",
            "kimi-k3",
            "max",
            {"reasoning_effort": "max"},
        ),
        (
            "openai_compat",
            OpenAICompatAdapter,
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "qwen3.8-max-0902",
            "xhigh",
            {"enable_thinking": True, "reasoning_effort": "xhigh"},
        ),
        (
            "openai_responses",
            OpenAIResponsesAdapter,
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "qwen3.8-max",
            "none",
            {"enable_thinking": False},
        ),
        (
            "openai_compat",
            OpenAICompatAdapter,
            "https://api.minimax.io/v1",
            "MiniMax-M3",
            "enabled",
            {"thinking": {"type": "adaptive"}},
        ),
        (
            "anthropic",
            AnthropicAdapter,
            "https://api.minimax.io/anthropic",
            "MiniMax-M3",
            "none",
            {"thinking": {"type": "disabled"}},
        ),
    ],
)
def test_native_vendor_protocol_mapping(
    provider: ProviderClass,
    adapter_cls: type[AdapterBase],
    base: str,
    model: str,
    level: str,
    expected: dict[str, object],
) -> None:
    adapter = adapter_cls(_config(provider, model, base))
    _, url, _, payload = adapter.build_request(_request(model, level), api_key=None)
    for key, value in expected.items():
        assert payload[key] == value
    if model.startswith("glm-"):
        assert url == "https://api.z.ai/api/paas/v4/chat/completions"
    default = adapter.build_request(_request(model), api_key=None)[3]
    for key in ("thinking", "enable_thinking", "reasoning", "reasoning_effort", "output_config"):
        assert key not in default


def test_azure_deployment_uses_explicit_profile_without_rewriting_model() -> None:
    config = _config(
        "azure", "production-deployment", "https://example.openai.azure.com/openai/v1"
    ).model_copy(update={"model_limits_name": "gpt-5.6-luna"})
    adapter = AzureOpenAIAdapter(config)
    payload = adapter.build_request(_request("production-deployment", "none"), api_key=None)[3]
    assert payload["model"] == "production-deployment"
    assert payload["reasoning_effort"] == "none"
    assert payload["max_completion_tokens"] == 128
    with pytest.raises(ProviderError, match="does not support"):
        adapter.build_request(_request("another-deployment", "none"), api_key=None)
    assert (
        thinking_policy_for("openai_responses", "unknown-model", model_limits_name="gpt-5.6-luna")[
            "supported"
        ]
        is False
    )


def test_ollama_output_budget_and_thinking_are_both_sent() -> None:
    request = replace(_request("gpt-oss:20b", "medium"), temperature=0.3)
    payload = OllamaAdapter(_config("ollama", "gpt-oss:20b")).build_request(request, api_key=None)[
        3
    ]
    assert payload["think"] == "medium"
    assert payload["options"] == {"num_predict": 128, "temperature": 0.3}


def test_provider_cache_keeps_default_separate_from_explicit_disable(tmp_path: Path) -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "gpt-5.6-luna",
                "output_text": f"Answer {len(sent)}",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client,
        make_provider(
            _config("openai_responses", "gpt-5.6-luna"),
            api_key=None,
            client=client,
            workspace_root=tmp_path,
            openrouter_pricing_fetcher=lambda _url, _timeout: {},
        ) as managed,
    ):
        default = managed.generate(_request("gpt-5.6-luna"))
        disabled = managed.generate(_request("gpt-5.6-luna", "none"))
        repeated = managed.generate(_request("gpt-5.6-luna", "none"))
    assert len(sent) == 2
    assert "reasoning" not in sent[0]
    assert sent[1]["reasoning"] == {"effort": "none"}
    assert default.content != disabled.content == repeated.content
    assert "cache_hit" in repeated.notes


def test_invalid_thinking_cannot_be_satisfied_by_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_lookup(*args: object, **kwargs: object) -> ProviderResponse:
        raise AssertionError("validate settings before cache access")

    monkeypatch.setattr(provider_module, "lookup_cached_response", reject_lookup)
    with (
        make_provider(
            _config("openai_responses", "gpt-6-astra"),
            api_key=None,
            workspace_root=tmp_path,
            openrouter_pricing_fetcher=lambda _url, _timeout: {},
        ) as managed,
        pytest.raises(ProviderError, match="does not support"),
    ):
        managed.generate(_request("gpt-6-astra", "none"))


@pytest.mark.parametrize(
    "adapter_cls,provider",
    [(OpenAIChatAdapter, "openai"), (OpenAIResponsesAdapter, "openai_responses")],
)
def test_astra_omits_unsupported_temperature(
    adapter_cls: type[AdapterBase], provider: ProviderClass
) -> None:
    request = replace(_request("gpt-6-astra", "high"), temperature=0.7)
    payload = adapter_cls(_config(provider, "gpt-6-astra")).build_request(request, api_key=None)[3]
    assert "temperature" not in payload


@pytest.mark.parametrize(
    "model,level,expected",
    [
        ("anthropic/claude-sonnet-5", "xhigh", {"effort": "xhigh"}),
        ("z-ai/glm-5.2", "xhigh", {"effort": "xhigh"}),
        ("z-ai/glm-5.3", "max", {"effort": "max"}),
        ("deepseek/deepseek-v4-pro", "xhigh", {"effort": "xhigh"}),
        ("deepseek/deepseek-v4-pro-0813", "max", {"effort": "max"}),
        ("google/gemini-3.6-flash", "minimal", {"effort": "minimal"}),
        ("minimax/minimax-m3", "none", {"enabled": False}),
        ("x-ai/grok-4.6", "xhigh", {"effort": "xhigh"}),
    ],
)
def test_openrouter_uses_its_own_reasoning_contract(
    model: str, level: str, expected: dict[str, object]
) -> None:
    adapter = OpenAICompatAdapter(_config("openai_compat", model, "https://openrouter.ai/api/v1"))
    payload = adapter.build_request(_request(model, level), api_key=None)[3]
    assert payload["reasoning"] == expected
    assert "reasoning_effort" not in payload
    assert "thinking" not in payload


@pytest.mark.parametrize(
    "model,level",
    [
        ("qwen/qwen3.8-max", "none"),
        ("google/gemini-3.7-flash", "minimal"),
        ("moonshotai/kimi-k3", "none"),
        ("deepseek/deepseek-v4-pro", "max"),
        ("unverified/unknown", "high"),
    ],
)
def test_openrouter_rejects_unverified_or_mandatory_reasoning_controls(
    model: str, level: str
) -> None:
    adapter = OpenAICompatAdapter(_config("openai_compat", model, "https://openrouter.ai/api/v1"))
    with pytest.raises(ProviderError, match="does not support"):
        adapter.build_request(_request(model, level), api_key=None)


@pytest.mark.parametrize("model", ["deepseek-v4-pro-0813", "deepseek-v4-flash-0731"])
def test_native_deepseek_dated_aliases_keep_thinking_controls(model: str) -> None:
    payload = OpenAIChatAdapter(_config("openai", model, "https://api.deepseek.com")).build_request(
        _request(model, "max"), api_key=None
    )[3]
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"


@pytest.mark.parametrize(
    "adapter_cls,provider,model,base",
    [
        (AnthropicAdapter, "anthropic", "claude-sonnet-4-5", "http://127.0.0.1:8000"),
        (
            GeminiAdapter,
            "gemini",
            "gemini-2.5-pro",
            "http://127.0.0.1:8000",
        ),
        (
            OpenAICompatAdapter,
            "openai_compat",
            "anthropic/claude-sonnet-4-5",
            "https://openrouter.ai/api/v1",
        ),
    ],
)
def test_manual_thinking_budget_cannot_exceed_output_cap(
    adapter_cls: type[AdapterBase], provider: ProviderClass, model: str, base: str
) -> None:
    adapter = adapter_cls(_config(provider, model, base))
    with pytest.raises(ProviderError, match="budget_tokens=8192"):
        adapter.build_request(_request(model, "high"), api_key=None)
    prepared = adapter.prepare_request(replace(_request(model, "high"), max_output_tokens=None))
    assert prepared.max_output_tokens == 8448
    capped_adapter = adapter_cls(
        _config(provider, model, base).model_copy(update={"max_output_tokens": 128})
    )
    with pytest.raises(ProviderError, match="budget_tokens=8192"):
        capped_adapter.prepare_request(replace(_request(model, "high"), max_output_tokens=None))


def test_managed_anthropic_enforces_implicit_thinking_budget_before_network() -> None:
    def reject_network(_: httpx.Request) -> httpx.Response:
        raise AssertionError("output reservation must fail before network")

    with (
        httpx.Client(transport=httpx.MockTransport(reject_network), trust_env=False) as client,
        make_provider(
            _config("anthropic", "claude-sonnet-4-5"),
            api_key=None,
            client=client,
            output_token_budget=1000,
        ) as managed,
        pytest.raises(ProviderError, match="output token budget exceeded"),
    ):
        managed.generate(replace(_request("claude-sonnet-4-5", "high"), max_output_tokens=None))


def test_gemini_separates_thoughts_and_accounts_for_thinking_tokens() -> None:
    response = httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"text": "internal", "thought": True}, {"text": "answer"}]}}
            ],
            "usageMetadata": {"candidatesTokenCount": 10, "thoughtsTokenCount": 100},
        },
    )
    parsed = GeminiAdapter(_config("gemini", "gemini-3.8-flash")).parse_response(response)
    assert parsed.content == "answer"
    assert parsed.reasoning_content == "internal"
    assert parsed.output_tokens == 110


@pytest.mark.parametrize(
    "adapter_cls,provider,payload",
    [
        (
            AzureOpenAIAdapter,
            "azure",
            {"choices": [{"message": {"content": "", "reasoning_content": "private reasoning"}}]},
        ),
        (OllamaAdapter, "ollama", {"message": {"content": "", "thinking": "private reasoning"}}),
    ],
)
def test_reasoning_only_response_is_not_promoted_to_final_content(
    adapter_cls: type[AdapterBase], provider: ProviderClass, payload: dict[str, object]
) -> None:
    parsed = adapter_cls(_config(provider, "test-model")).parse_response(
        httpx.Response(200, json=payload)
    )
    assert parsed.content == ""
    assert parsed.reasoning_content == "private reasoning"


def test_azure_cache_separates_model_profiles(tmp_path: Path) -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "deployment",
                "choices": [{"message": {"content": f"Answer {len(sent)}"}}],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        for profile in ("gpt-5.6-luna", "gpt-4o"):
            config = _config("azure", "deployment").model_copy(
                update={"model_limits_name": profile}
            )
            with make_provider(
                config,
                api_key=None,
                client=client,
                workspace_root=tmp_path,
                openrouter_pricing_fetcher=lambda _url, _timeout: {},
            ) as managed:
                managed.generate(_request("deployment"))
    assert len(sent) == 2
    assert sent[0]["max_completion_tokens"] == 128
    assert sent[1]["max_tokens"] == 128
