from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from ahadiff.contracts import ProviderConfig
from ahadiff.core.config import SecurityConfig
from ahadiff.core.errors import ConfigError, InputError, ProviderError, SafetyError, StorageError
from ahadiff.core.paths import usage_db_path
from ahadiff.llm import ProviderRequest, adapter_conformance_test, make_provider
from ahadiff.llm import provider as provider_module
from ahadiff.llm import usage as usage_module
from ahadiff.llm.adapters.azure import AzureOpenAIAdapter
from ahadiff.llm.adapters.openai_compat import OpenAICompatAdapter
from ahadiff.llm.adapters.openai_responses import OpenAIResponsesAdapter
from ahadiff.llm.cache import build_cache_key
from ahadiff.llm.cost import (
    DEFAULT_OPENROUTER_MODELS_URL,
    PricingEntry,
    estimate_cost_usd,
    fetch_openrouter_pricing_catalog,
    official_pricing_source_url,
    reset_openrouter_pricing_cache,
    resolve_context_window,
    resolve_pricing_entry,
)
from ahadiff.llm.probe import _probe_context_window  # pyright: ignore[reportPrivateUsage]
from ahadiff.llm.provider import reset_provider_runtime_state, transport_target_for_base_url
from ahadiff.llm.schemas import CacheKeyInput
from ahadiff.llm.usage import UsageRecord
from ahadiff.safety.redact import redaction_pipeline

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_provider_runtime_state(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    reset_provider_runtime_state()
    reset_openrouter_pricing_cache()
    yield
    reset_provider_runtime_state()
    reset_openrouter_pricing_cache()


def _provider_config(
    provider_class: str,
    *,
    base_url: str = "http://127.0.0.1:8000",
    model_name: str = "gpt-5.4-mini",
    max_context: int | None = 4096,
) -> ProviderConfig:
    return ProviderConfig(
        provider_class=provider_class,  # pyright: ignore[reportArgumentType]
        model_name=model_name,
        base_url=base_url,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        probed_max_context=max_context,
    )


def _request(**overrides: Any) -> ProviderRequest:
    payload: dict[str, Any] = {
        "prompt_name": "lesson.generate",
        "prompt_fingerprint": "prompt-v1",
        "prompt_version": "prompt-v1",
        "eval_bundle_version": "bundle-v1",
        "model": "gpt-5.4-mini",
        "payload_text": "Explain the diff.",
        "diff_content": "Explain the diff.",
        "source_ref": "HEAD",
    }
    payload.update(overrides)
    return ProviderRequest(**payload)


def _usage_record() -> UsageRecord:
    return UsageRecord(
        workspace_identity="workspace",
        provider_class="openai",
        api_family="openai_chat",
        api_family_version="v1",
        model_id="gpt-5.4-mini",
        prompt_name="lesson.generate",
        prompt_fingerprint="prompt-v1",
        prompt_version="prompt-v1",
        eval_bundle_version="bundle-v1",
        output_lang="en",
        privacy_mode="strict_local",
        source_ref="HEAD",
        cache_key="a" * 64,
        cache_hit=False,
        input_tokens=11,
        output_tokens=7,
        cost_usd=0.01,
        pricing_version="test-pricing",
        cost_confidence="high",
        execution_origin="test",
        request_id="req-1",
    )


def test_llm_reexports_provider_response_byte_cap() -> None:
    from ahadiff.llm import DEFAULT_PROVIDER_RESPONSE_BYTE_CAP

    assert DEFAULT_PROVIDER_RESPONSE_BYTE_CAP == provider_module.DEFAULT_PROVIDER_RESPONSE_BYTE_CAP


def _openai_success_response(
    content: str = "OK",
    *,
    model_id: str = "gpt-5.4-mini",
    prompt_tokens: int = 11,
    completion_tokens: int = 7,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model_id,
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
        headers={
            "x-request-id": "req-123",
            "x-ratelimit-limit-requests": "9",
            "x-ratelimit-remaining-requests": "8",
        },
    )


class _ChunkedByteStream(httpx.SyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.read_chunks = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.chunks:
            self.read_chunks += 1
            yield chunk


class _FailingByteStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield b'{"model":"gpt-5.4-mini",'
        raise httpx.ReadError("server disconnected during response body")


@pytest.mark.parametrize(
    "provider_class",
    [
        "openai",
        "openai_responses",
        "gemini",
        "anthropic",
        "azure",
        "newapi",
        "ollama",
        "lmstudio",
    ],
)
def test_make_provider_builds_all_frozen_adapters(provider_class: str) -> None:
    provider = make_provider(_provider_config(provider_class), api_key="test-key")
    try:
        adapter_conformance_test(provider)
        assert provider.capabilities.provider_kind
    finally:
        provider.close()


def test_openai_responses_adapter_clamps_negative_usage_and_concatenates_content() -> None:
    adapter = OpenAIResponsesAdapter(_provider_config("openai_responses"))
    response = httpx.Response(
        200,
        json={
            "model": "gpt-5.4-mini",
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "first"},
                        {"type": "text", "text": " second"},
                    ]
                }
            ],
            "usage": {"input_tokens": -5, "output_tokens": -2},
            "status": "completed",
        },
    )

    parsed = adapter.parse_response(response)

    assert parsed.content == "first second"
    assert parsed.input_tokens == 0
    assert parsed.output_tokens == 0


def test_openai_responses_provider_sends_responses_request_and_parses_response() -> None:
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        payload = json.loads(request.content.decode("utf-8"))
        assert request.method == "POST"
        assert payload["model"] == "gpt-5.4-mini"
        assert payload["input"] == "Explain the diff."
        assert payload["text"] == {"format": {"type": "json_object"}}
        return httpx.Response(
            200,
            json={
                "model": "gpt-5.4-mini",
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": "first"},
                            {"type": "text", "text": " second"},
                        ]
                    }
                ],
                "usage": {"input_tokens": 12, "output_tokens": 5},
                "status": "completed",
            },
            headers={"x-request-id": "req-responses-123"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai_responses"),
        api_key="test-key",
        client=client,
    )
    try:
        response = provider.generate(_request(response_format="json"))
    finally:
        provider.close()

    assert captured_urls == ["http://127.0.0.1:8000/v1/responses"]
    assert response.content == "first second"
    assert response.input_tokens == 12
    assert response.output_tokens == 5
    assert response.request_id == "req-responses-123"


def test_provider_request_rejects_redirect_even_when_client_follows_redirects() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/internal"})

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        trust_env=False,
        follow_redirects=True,
    )
    provider = make_provider(_provider_config("openai"), api_key="test-key", client=client)
    try:
        with pytest.raises(ProviderError, match="redirects are not allowed"):
            provider.generate(_request())
    finally:
        provider.close()

    assert seen_urls == ["http://127.0.0.1:8000/v1/chat/completions"]


def test_provider_revalidates_adapter_generated_request_url() -> None:
    def build_request(
        request: ProviderRequest,
        *,
        api_key: str | None,
    ) -> tuple[str, str, dict[str, str], dict[str, Any]]:
        del request, api_key
        return ("POST", "http://8.8.8.8/v1/chat/completions", {}, {})

    provider = make_provider(
        _provider_config("openai", base_url="http://127.0.0.1:8000"),
        api_key="test-key",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: _openai_success_response()),
            trust_env=False,
        ),
    )
    try:
        cast("Any", provider.adapter).build_request = build_request
        with pytest.raises(SafetyError, match="strict_local mode forbids remote transport"):
            provider.generate(_request())
    finally:
        provider.close()


def test_resolve_context_window_falls_back_when_probe_returns_zero() -> None:
    assert resolve_context_window("gpt-5.4-mini", 0) == 1_000_000


def test_make_provider_default_client_disables_env_proxy_trust() -> None:
    provider = make_provider(_provider_config("openai"), api_key="test-key")
    try:
        assert provider.client._trust_env is False  # pyright: ignore[reportPrivateUsage]
    finally:
        provider.close()


def test_managed_provider_supports_context_manager() -> None:
    provider_ref = None
    with make_provider(_provider_config("openai"), api_key="test-key") as provider:
        provider_ref = provider
        assert provider.client.is_closed is False
    assert provider_ref is not None
    assert provider_ref.client.is_closed is True


def test_strict_local_rejects_injected_client_that_trusts_env_proxy() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: _openai_success_response()))
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
    )
    try:
        with pytest.raises(SafetyError, match="trust_env=False"):
            provider.generate(_request())
    finally:
        provider.close()


def test_make_provider_rejects_unknown_provider_class() -> None:
    config = ProviderConfig.model_construct(
        provider_class="bogus",
        model_name="gpt-5.4-mini",
        base_url="http://127.0.0.1:8000",
        api_key_env="AHADIFF_PROVIDER_API_KEY",
    )
    with pytest.raises(ProviderError, match="unsupported provider_class"):
        make_provider(config)


def test_strict_local_rejects_non_loopback_even_for_ollama() -> None:
    provider = make_provider(
        _provider_config("ollama", base_url="http://remote.example:11434"),
        security_config=SecurityConfig(),
    )
    try:
        with pytest.raises(SafetyError, match="strict_local mode forbids remote transport"):
            provider.generate(_request())
    finally:
        provider.close()


def test_global_local_hosts_allowlist_permits_named_host_under_strict_local() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["messages"][0]["content"] == "Explain the diff."
        return _openai_success_response()

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai", base_url="http://model.local:8000"),
        api_key="test-key",
        security_config=SecurityConfig(
            local_hosts=("model.local",),
            strict_local_hosts=("model.local",),
        ),
        client=client,
    )
    try:
        response = provider.generate(_request())
        assert response.content == "OK"
    finally:
        provider.close()


def test_repo_local_hosts_are_ignored_under_strict_local() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _openai_success_response()

    provider = make_provider(
        _provider_config("openai", base_url="http://model.local:8000"),
        api_key="test-key",
        security_config=SecurityConfig(local_hosts=("model.local",)),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    try:
        with pytest.raises(SafetyError, match="strict_local mode forbids remote transport"):
            provider.generate(_request())
    finally:
        provider.close()


def test_redacted_remote_sends_redacted_payload_and_audit_omits_prompt_text(tmp_path: Path) -> None:
    secret = 'OPENAI_API_KEY="sk-abcdefghijklmnopqrstuvwxyz123456"'
    redaction = redaction_pipeline(secret)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["messages"][0]["content"] == 'OPENAI_API_KEY="[REDACTED:openai_api_key]"'
        return _openai_success_response(content="Sanitized")

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai", base_url="http://8.8.8.8"),
        api_key="test-key",
        security_config=SecurityConfig(),
        workspace_root=tmp_path,
        client=client,
    )
    try:
        response = provider.generate(
            _request(
                payload_text=secret,
                redacted_payload_text=redaction.redacted_text,
                diff_content=secret,
                privacy_mode="redacted_remote",
                findings=redaction.findings,
            )
        )
    finally:
        provider.close()

    assert response.content == "Sanitized"
    audit_text = (tmp_path / ".ahadiff" / "audit.jsonl").read_text(encoding="utf-8")
    assert '"event_id": "evt_' in audit_text
    assert "OPENAI_API_KEY" not in audit_text
    assert "[REDACTED:openai_api_key]" not in audit_text
    assert '"schema_version": 1' in audit_text


def test_request_hash_is_salted_per_audit_event(tmp_path: Path) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: _openai_success_response(content="OK")),
        trust_env=False,
    )
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        workspace_root=tmp_path,
        client=client,
    )
    try:
        provider.generate(_request(source_ref="first"))
        provider.generate(_request(source_ref="second"))
    finally:
        provider.close()

    lines = (tmp_path / ".ahadiff" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["request_hash"] != second["request_hash"]


def test_provider_slot_blocks_new_entries_until_shrunk_limit_is_satisfied() -> None:
    provider_slot = cast("Any", provider_module._provider_slot)  # pyright: ignore[reportPrivateUsage]
    key = "provider-slot-shrink"
    second_entered = threading.Event()
    release_second = threading.Event()
    shrunk_attempted = threading.Event()
    shrunk_entered = threading.Event()

    def second_holder() -> None:
        with provider_slot(key, 2):
            second_entered.set()
            assert release_second.wait(timeout=1)

    def shrunk_holder() -> None:
        shrunk_attempted.set()
        with provider_slot(key, 1):
            shrunk_entered.set()

    second_thread = threading.Thread(target=second_holder)
    shrunk_thread = threading.Thread(target=shrunk_holder)
    try:
        with provider_slot(key, 2):
            second_thread.start()
            assert second_entered.wait(timeout=1)

            shrunk_thread.start()
            assert shrunk_attempted.wait(timeout=1)
            assert not shrunk_entered.wait(timeout=0.1)

        assert not shrunk_entered.wait(timeout=0.1)
    finally:
        release_second.set()
        second_thread.join(timeout=1)
        shrunk_thread.join(timeout=1)

    assert not second_thread.is_alive()
    assert shrunk_entered.wait(timeout=1)
    assert not shrunk_thread.is_alive()


def test_retry_after_header_triggers_backoff_then_success() -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []
    clock = {"now": 0.0}

    def monotonic() -> float:
        return clock["now"]

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        clock["now"] += seconds

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"retry-after": "0.25"})
        return _openai_success_response(content="Retried")

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
        sleep=sleep,
        monotonic=monotonic,
    )
    try:
        response = provider.generate(_request())
    finally:
        provider.close()

    assert response.content == "Retried"
    assert sleep_calls == [0.25]


def test_negative_retry_after_uses_exponential_backoff() -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []
    clock = {"now": 0.0}

    def monotonic() -> float:
        return clock["now"]

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        clock["now"] += seconds

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"retry-after": "-5"})
        return _openai_success_response(content="Retried")

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
        sleep=sleep,
        monotonic=monotonic,
    )
    try:
        response = provider.generate(_request())
    finally:
        provider.close()

    assert response.content == "Retried"
    assert sleep_calls == [1.0]  # 2**0 = 1 (exponential backoff, not -5)


def test_retry_after_infinity_returns_none() -> None:
    from ahadiff.llm.cost import parse_retry_after

    assert parse_retry_after({"retry-after": "inf"}) is None
    assert parse_retry_after({"retry-after": "-inf"}) is None
    assert parse_retry_after({"retry-after": "nan"}) is None


def test_retry_after_huge_value_is_capped() -> None:
    from ahadiff.llm.cost import parse_retry_after

    result = parse_retry_after({"retry-after": "999999"})
    assert result is not None
    assert result <= 300.0


def test_circuit_breaker_opens_and_recovers() -> None:
    clock = {"now": 0.0}
    calls = {"count": 0}

    def monotonic() -> float:
        return clock["now"]

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] <= 2:
            return httpx.Response(503)
        return _openai_success_response(content="Recovered")

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config(
            "openai",
            base_url="http://127.0.0.1:8001",
            model_name="gpt-5.4-mini-circuit",
        ),
        api_key="test-key",
        client=client,
        retry_attempts=0,
        circuit_failure_threshold=2,
        circuit_cooldown=60,
        monotonic=monotonic,
    )
    try:
        with pytest.raises(ProviderError):
            provider.generate(_request(model="gpt-5.4-mini-circuit", source_ref="attempt-1"))
        with pytest.raises(ProviderError):
            provider.generate(_request(model="gpt-5.4-mini-circuit", source_ref="attempt-2"))
        with pytest.raises(ProviderError, match="circuit breaker is open"):
            provider.generate(_request(model="gpt-5.4-mini-circuit", source_ref="attempt-3"))
        clock["now"] = 61.0
        response = provider.generate(_request(model="gpt-5.4-mini-circuit", source_ref="attempt-4"))
    finally:
        provider.close()

    assert response.content == "Recovered"


def test_context_bundle_hash_mismatch_fails_before_dispatch() -> None:
    provider = make_provider(_provider_config("openai"), api_key="test-key")
    try:
        with pytest.raises(SafetyError, match="context_bundle_hash drift"):
            provider.generate(
                _request(
                    context_bundle_hash="wrong",
                    context_artifacts={"diff.md": "actual"},
                )
            )
    finally:
        provider.close()


def test_malformed_success_payload_retries_before_failing() -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, json={"model": "gpt-5.4-mini", "choices": []})
        return _openai_success_response(content="Recovered after malformed payload")

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
        retry_attempts=1,
        sleep=sleep,
    )
    try:
        response = provider.generate(_request())
    finally:
        provider.close()

    assert response.content == "Recovered after malformed payload"
    assert calls["count"] == 2
    assert sleep_calls == [1]


def test_context_clipping_sets_token_exceeded_flag() -> None:
    captured_lengths: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured_lengths.append(len(payload["messages"][0]["content"]))
        return _openai_success_response(content="Clipped")

    long_payload = "x" * 4000
    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai", max_context=300),
        api_key="test-key",
        client=client,
    )
    try:
        response = provider.generate(_request(payload_text=long_payload, diff_content=long_payload))
    finally:
        provider.close()

    assert response.degraded_flags["token_exceeded"] is True
    assert captured_lengths[0] < len(long_payload)


def test_cache_key_hashes_diff_content_without_embedding_raw_patch() -> None:
    large_diff = "x" * 20_000
    cache_key = build_cache_key(
        CacheKeyInput(
            diff_content=large_diff,
            source_ref="HEAD",
            prompt_name="lesson.generate",
            prompt_fingerprint="prompt-v1",
            prompt_version="prompt-v1",
            eval_bundle_version="bundle-v1",
            provider_class="openai",
            provider_kind="openai_chat",
            base_url="https://api.openai.com/v1",
            model_id="gpt-5.4-mini",
            api_family="openai",
            api_family_version="v1",
            output_lang="en",
            privacy_mode="strict_local",
            redaction_config="cfg",
            context_bundle_hash="ctx",
            request_payload_sha256="payload",
        )
    )
    assert len(cache_key) == 64
    assert large_diff not in cache_key


def test_cache_key_separates_api_family_versions() -> None:
    def make_input(api_family_version: str) -> CacheKeyInput:
        return CacheKeyInput(
            diff_content="diff --git a/app.py b/app.py\n+print('hi')",
            source_ref="HEAD",
            prompt_name="lesson.generate",
            prompt_fingerprint="prompt-v1",
            prompt_version="prompt-v1",
            eval_bundle_version="bundle-v1",
            provider_class="openai",
            provider_kind="openai_chat",
            base_url="https://api.openai.com/v1",
            model_id="gpt-5.4-mini",
            api_family="openai",
            api_family_version=api_family_version,
            output_lang="en",
            privacy_mode="strict_local",
            redaction_config="cfg",
            context_bundle_hash="ctx",
            request_payload_sha256="payload",
        )

    v1_key = build_cache_key(make_input("v1"))
    v2_key = build_cache_key(make_input("v2"))

    assert v1_key != v2_key


def test_cache_key_separates_provider_and_base_url() -> None:
    def make_input(provider_class: str, provider_kind: str, base_url: str) -> CacheKeyInput:
        return CacheKeyInput(
            diff_content="diff --git a/app.py b/app.py\n+print('hi')",
            source_ref="HEAD",
            prompt_name="lesson.generate",
            prompt_fingerprint="prompt-v1",
            prompt_version="prompt-v1",
            eval_bundle_version="bundle-v1",
            provider_class=provider_class,
            provider_kind=provider_kind,
            base_url=base_url,
            model_id="gpt-5.4-mini",
            api_family="openai",
            api_family_version="v1",
            output_lang="en",
            privacy_mode="strict_local",
            redaction_config="cfg",
            context_bundle_hash="ctx",
            request_payload_sha256="payload",
        )

    official_key = build_cache_key(
        make_input("openai", "openai_chat", "https://api.openai.com/v1/")
    )
    proxy_key = build_cache_key(make_input("openai", "openai_chat", "https://proxy.example/v1"))
    newapi_key = build_cache_key(make_input("newapi", "openai_compat", "https://proxy.example/v1"))

    assert official_key != proxy_key
    assert proxy_key != newapi_key


def test_provider_disk_cache_hit_skips_network_and_records_usage(tmp_path: Path) -> None:
    calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return _openai_success_response(content="Cached", prompt_tokens=13, completion_tokens=5)

    workspace_root = tmp_path / "repo"
    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        workspace_root=workspace_root,
        client=client,
    )
    try:
        first = provider.generate(_request())
        second = provider.generate(_request())
    finally:
        provider.close()

    assert calls["count"] == 1
    assert first.content == "Cached"
    assert second.content == "Cached"
    assert "cache_hit" in second.notes
    assert any(note.startswith("cache_key=") for note in second.notes)
    cache_files = list((workspace_root / ".ahadiff" / "cache").glob("*.json"))
    assert len(cache_files) == 1

    with sqlite3.connect(usage_db_path()) as connection:
        rows = connection.execute(
            """
            SELECT cache_hit, input_tokens, output_tokens, cost_usd, pricing_version
            FROM llm_usage
            ORDER BY rowid
            """
        ).fetchall()

    assert rows == [
        (0, 13, 5, 0.00003225, "openai-api-pricing-2026-04-23"),
        (1, 13, 5, 0.0, "cache-hit"),
    ]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_provider_cache_rejects_symlink_cache_dir(tmp_path: Path) -> None:
    calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return _openai_success_response(content="Cached")

    workspace_root = tmp_path / "repo"
    state_dir = workspace_root / ".ahadiff"
    outside_cache = tmp_path / "outside-cache"
    state_dir.mkdir(parents=True)
    outside_cache.mkdir()
    os.symlink(outside_cache, state_dir / "cache", target_is_directory=True)
    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        workspace_root=workspace_root,
        client=client,
    )
    try:
        with pytest.raises(InputError, match="state path must not contain symlinks"):
            provider.generate(_request())
    finally:
        provider.close()

    assert calls["count"] == 0
    assert list(outside_cache.iterdir()) == []


def test_provider_disk_cache_key_separates_prompt_identity(tmp_path: Path) -> None:
    calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return _openai_success_response(content=f"Call {calls['count']}")

    workspace_root = tmp_path / "repo"
    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        workspace_root=workspace_root,
        client=client,
    )
    try:
        first = provider.generate(_request())
        second = provider.generate(
            _request(
                prompt_name="quiz.generate",
                prompt_fingerprint="prompt-v1",
                payload_text="Explain the diff.",
                diff_content="Explain the diff.",
            )
        )
    finally:
        provider.close()

    assert calls["count"] == 2
    assert first.content == "Call 1"
    assert second.content == "Call 2"


def test_provider_usage_write_failure_does_not_fail_successful_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_record_usage(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    workspace_root = tmp_path / "repo"
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: _openai_success_response(content="OK")),
        trust_env=False,
    )
    monkeypatch.setattr(provider_module, "record_usage_event", fail_record_usage)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        workspace_root=workspace_root,
        client=client,
    )
    try:
        response = provider.generate(_request())
    finally:
        provider.close()

    assert response.content == "OK"


def test_usage_db_retries_locked_write_and_records_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "usage.sqlite"
    monkeypatch.setattr(usage_module, "_USAGE_BUSY_TIMEOUT_MS", 1)
    monkeypatch.setattr(usage_module, "_USAGE_WRITE_ATTEMPTS", 5)
    with usage_module.connect_usage_db(db_path, create_parent=True) as connection:
        usage_module._ensure_usage_schema(connection, db_path)  # pyright: ignore[reportPrivateUsage]

    lock_connection = sqlite3.connect(db_path, timeout=0.001, check_same_thread=False)
    lock_connection.execute("BEGIN EXCLUSIVE")

    def release_lock() -> None:
        try:
            import time

            time.sleep(0.05)
            lock_connection.rollback()
        finally:
            lock_connection.close()

    releaser = threading.Thread(target=release_lock)
    releaser.start()
    try:
        usage_module.record_usage_event(_usage_record(), db_path=db_path)
    finally:
        releaser.join(timeout=1)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT cache_key, cache_hit FROM llm_usage").fetchall()

    assert rows == [("a" * 64, 0)]


def test_usage_schema_initialization_is_thread_safe(tmp_path: Path) -> None:
    db_path = tmp_path / "usage.sqlite"
    usage_module._SCHEMA_INITIALIZED.pop(  # pyright: ignore[reportPrivateUsage]
        str(db_path),
        None,
    )
    thread_count = 12
    start = threading.Barrier(thread_count)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            start.wait(timeout=2)
            usage_module.record_usage_event(_usage_record(), db_path=db_path)
        except BaseException as exc:  # pragma: no cover - failure path asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    with sqlite3.connect(db_path) as connection:
        row_count = connection.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0]
    assert row_count == thread_count


def test_usage_db_corrupt_quick_check_raises_storage_error(tmp_path: Path) -> None:
    db_path = tmp_path / "usage.sqlite"
    db_path.write_bytes(b"not a sqlite database")

    with pytest.raises(StorageError, match="quick_check"):
        usage_module.connect_usage_db(db_path)


def test_usage_db_rejects_unsupported_sqlite_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(usage_module.sqlite3, "sqlite_version_info", (3, 40, 0))
    monkeypatch.setattr(usage_module.sqlite3, "sqlite_version", "3.40.0")

    with pytest.raises(StorageError, match="SQLite runtime"):
        usage_module.connect_usage_db(tmp_path / "usage.sqlite", create_parent=True)


def test_provider_ignores_cache_entry_with_mismatched_eval_bundle_version(
    tmp_path: Path,
) -> None:
    calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return _openai_success_response(content=f"Miss {calls['count']}")

    workspace_root = tmp_path / "repo"
    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        workspace_root=workspace_root,
        client=client,
    )
    try:
        first = provider.generate(_request())
        cache_file = next((workspace_root / ".ahadiff" / "cache").glob("*.json"))
        cached_payload = json.loads(cache_file.read_text(encoding="utf-8"))
        cached_payload["eval_bundle_version"] = "bundle-v2"
        cache_file.write_text(json.dumps(cached_payload), encoding="utf-8")

        second = provider.generate(_request())
    finally:
        provider.close()

    assert first.content == "Miss 1"
    assert second.content == "Miss 2"
    assert "cache_hit" not in second.notes
    assert calls["count"] == 2


def test_cache_cleanup_only_removes_old_cache_tmp_files(tmp_path: Path) -> None:
    import time

    from ahadiff.llm import cache as cache_module

    cache_dir = tmp_path / "repo" / ".ahadiff" / "cache"
    cache_dir.mkdir(parents=True)
    old_cache_tmp = cache_dir / f".{'a' * 64}.old.tmp"
    recent_cache_tmp = cache_dir / f".{'b' * 64}.recent.tmp"
    unrelated_tmp = cache_dir / ".not-cache.tmp"
    for path in (old_cache_tmp, recent_cache_tmp, unrelated_tmp):
        path.write_text("tmp\n", encoding="utf-8")

    now = time.time()
    ttl = cache_module._ORPHANED_TMP_TTL_SECONDS  # pyright: ignore[reportPrivateUsage]
    old_timestamp = now - ttl - 1
    recent_timestamp = now - ttl + 60
    os.utime(old_cache_tmp, (old_timestamp, old_timestamp))
    os.utime(recent_cache_tmp, (recent_timestamp, recent_timestamp))
    os.utime(unrelated_tmp, (old_timestamp, old_timestamp))

    cache_module._cleanup_orphaned_tmp_files(cache_dir)  # pyright: ignore[reportPrivateUsage]

    assert not old_cache_tmp.exists()
    assert recent_cache_tmp.exists()
    assert unrelated_tmp.exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_cache_cleanup_does_not_follow_symlink_directory(tmp_path: Path) -> None:
    import time

    from ahadiff.llm import cache as cache_module

    outside_cache = tmp_path / "outside-cache"
    outside_cache.mkdir()
    victim = outside_cache / f".{'a' * 64}.victim.tmp"
    victim.write_text("outside\n", encoding="utf-8")
    ttl = cache_module._ORPHANED_TMP_TTL_SECONDS  # pyright: ignore[reportPrivateUsage]
    old_timestamp = time.time() - ttl - 1
    os.utime(victim, (old_timestamp, old_timestamp))
    link = tmp_path / "repo" / ".ahadiff" / "cache"
    link.parent.mkdir(parents=True)
    os.symlink(outside_cache, link, target_is_directory=True)

    cache_module._cleanup_orphaned_tmp_files(link)  # pyright: ignore[reportPrivateUsage]

    assert victim.exists()


def test_estimate_cost_uses_official_openai_pricing_for_default_model() -> None:
    estimate = estimate_cost_usd(
        provider_class="openai",
        model_id="gpt-5.4-mini",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert estimate.cost_usd == 5.25
    assert estimate.cost_confidence == "high"
    assert estimate.pricing_version == "openai-api-pricing-2026-04-23"
    assert official_pricing_source_url("openai") == "https://openai.com/api/pricing/"


def test_estimate_cost_accepts_request_level_fee() -> None:
    estimate = estimate_cost_usd(
        model_id="openrouter/test-model",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        pricing_entry=PricingEntry(
            input_per_million_usd=0.4,
            output_per_million_usd=1.6,
            request_per_call_usd=0.01,
            pricing_version="openrouter-models-api-live",
            source_url=DEFAULT_OPENROUTER_MODELS_URL,
        ),
    )
    assert estimate.cost_usd == 2.01
    assert estimate.pricing_version == "openrouter-models-api-live"


def test_fetch_openrouter_pricing_catalog_parses_and_caches_results() -> None:
    calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "openrouter/test-model",
                        "pricing": {
                            "prompt": "0.0000004",
                            "completion": "0.0000016",
                            "request": "0.01",
                        },
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    try:
        first = fetch_openrouter_pricing_catalog(
            "https://openrouter.ai/api/v1/models",
            300,
            client=client,
            now=lambda: 10.0,
        )
        second = fetch_openrouter_pricing_catalog(
            "https://openrouter.ai/api/v1/models",
            300,
            client=client,
            now=lambda: 20.0,
        )
    finally:
        client.close()

    assert calls["count"] == 1
    assert first["openrouter/test-model"].input_per_million_usd == 0.4
    assert second["openrouter/test-model"].request_per_call_usd == 0.01


@pytest.mark.parametrize(
    "models_url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://openrouter.ai.evil.example/api/v1/models",
    ],
)
def test_fetch_openrouter_pricing_catalog_rejects_untrusted_url(models_url: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    try:
        with pytest.raises(ProviderError, match="OpenRouter pricing URL"):
            fetch_openrouter_pricing_catalog(models_url, client=client)
    finally:
        client.close()


def test_resolve_pricing_entry_prefers_openrouter_catalog_for_openrouter_base_url() -> None:
    calls: list[tuple[str, int]] = []

    def fetcher(models_url: str, refresh_seconds: int) -> dict[str, PricingEntry]:
        calls.append((models_url, refresh_seconds))
        return {
            "openrouter/test-model": PricingEntry(
                input_per_million_usd=0.4,
                output_per_million_usd=1.6,
                request_per_call_usd=0.01,
                pricing_version="openrouter-models-api-live",
                source_url=models_url,
            )
        }

    entry = resolve_pricing_entry(
        provider_class="openai",
        model_id="openrouter/test-model",
        base_url="https://openrouter.ai/api/v1",
        openrouter_fetcher=fetcher,
    )

    assert entry is not None
    assert entry.pricing_version == "openrouter-models-api-live"
    assert calls == [(DEFAULT_OPENROUTER_MODELS_URL, 3600)]


def test_workspace_model_pricing_override_updates_audit_cost(tmp_path: Path) -> None:
    (tmp_path / ".ahadiff").mkdir()
    (tmp_path / ".ahadiff" / "config.toml").write_text(
        '[pricing.input_per_million_usd]\n"gpt-5.4-mini" = 0.4\n\n'
        '[pricing.output_per_million_usd]\n"gpt-5.4-mini" = 1.6\n',
        encoding="utf-8",
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: _openai_success_response(
                content="Priced",
                prompt_tokens=1_000,
                completion_tokens=500,
            )
        ),
        trust_env=False,
    )
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        workspace_root=tmp_path,
        client=client,
    )
    try:
        provider.generate(_request())
    finally:
        provider.close()

    audit = json.loads(
        (tmp_path / ".ahadiff" / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert audit["pricing_version"] == "user-config"
    assert audit["cost_usd"] == 0.0012


def test_provider_uses_openrouter_pricing_source_for_cost_audit(tmp_path: Path) -> None:
    (tmp_path / ".ahadiff").mkdir()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: _openai_success_response(
                content="OpenRouter",
                model_id="openrouter/test-model",
                prompt_tokens=1_000,
                completion_tokens=500,
            )
        ),
        trust_env=False,
    )
    provider = make_provider(
        _provider_config(
            "openai",
            base_url="https://openrouter.ai/api/v1",
            model_name="openrouter/test-model",
        ),
        api_key="test-key",
        workspace_root=tmp_path,
        client=client,
        openrouter_pricing_fetcher=lambda _url, _refresh: {
            "openrouter/test-model": PricingEntry(
                input_per_million_usd=0.4,
                output_per_million_usd=1.6,
                request_per_call_usd=0.01,
                pricing_version="openrouter-models-api-live",
                source_url=DEFAULT_OPENROUTER_MODELS_URL,
            )
        },
    )
    try:
        provider.generate(
            _request(
                model="openrouter/test-model",
                privacy_mode="explicit_remote",
            )
        )
    finally:
        provider.close()

    audit = json.loads(
        (tmp_path / ".ahadiff" / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert audit["pricing_version"] == "openrouter-models-api-live"
    assert audit["cost_usd"] == 0.0112


def test_azure_adapter_accepts_api_version_override_in_base_url() -> None:
    adapter = AzureOpenAIAdapter(
        _provider_config(
            "azure",
            base_url="https://example.openai.azure.com/openai/deployments?api-version=2025-01-01-preview",
        )
    )
    _, url, _, _ = adapter.build_request(_request(model="demo-deployment"), api_key="test-key")
    assert "api-version=2025-01-01-preview" in url


def test_openai_compat_adapters_share_common_base() -> None:
    from ahadiff.llm.adapters.lmstudio import LMStudioAdapter
    from ahadiff.llm.adapters.newapi import NewAPIAdapter

    assert issubclass(NewAPIAdapter, OpenAICompatAdapter)
    assert issubclass(LMStudioAdapter, OpenAICompatAdapter)


def test_make_provider_rejects_max_concurrent_below_one() -> None:
    with pytest.raises(ConfigError, match="max_concurrent must be >= 1"):
        make_provider(_provider_config("openai"), api_key="test-key", max_concurrent=0)


def test_make_provider_rejects_response_byte_cap_below_one() -> None:
    with pytest.raises(ConfigError, match="response_byte_cap must be >= 1"):
        make_provider(_provider_config("openai"), api_key="test-key", response_byte_cap=0)


def test_provider_rejects_empty_completion_response() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: _openai_success_response(content="   ")),
        trust_env=False,
    )
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
        retry_attempts=0,
    )
    try:
        with pytest.raises(ProviderError, match="provider returned empty response"):
            provider.generate(_request())
    finally:
        provider.close()


def test_provider_strips_and_notes_model_output_role_fences() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: _openai_success_response(content="answer <system>evil</system> end")
        ),
        trust_env=False,
    )
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
        retry_attempts=0,
    )
    try:
        response = provider.generate(_request())
    finally:
        provider.close()

    assert response.content == "answer evil end"
    assert "model_output_contains_role_fence_tags" in response.notes


def test_provider_rejects_overlong_completion_during_streaming_read() -> None:
    stream = _ChunkedByteStream(
        (
            b"{",
            b'"choices": [{"message": {"content": "too large"}}]',
            b"additional over-cap payload",
        )
    )
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
        trust_env=False,
    )
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
        response_byte_cap=16,
        retry_attempts=0,
    )
    try:
        with pytest.raises(ProviderError, match="provider response exceeded byte cap"):
            provider.generate(_request())
    finally:
        provider.close()


def test_read_capped_response_body_uses_bounded_iter_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_chunk_sizes: list[int | None] = []

    def recording_iter_bytes(
        self: httpx.Response,
        chunk_size: int | None = None,
    ) -> Iterator[bytes]:
        seen_chunk_sizes.append(chunk_size)
        yield b'{"model":"gpt-5.4-mini","choices":[{"message":{"content":"OK"}}]}'

    monkeypatch.setattr(httpx.Response, "iter_bytes", recording_iter_bytes)
    response = httpx.Response(200)
    seen_chunk_sizes.clear()
    provider = make_provider(_provider_config("openai"), api_key="test-key")
    try:
        body = provider._read_capped_response_body(  # pyright: ignore[reportPrivateUsage]
            response
        )
    finally:
        provider.close()

    assert body.startswith(b'{"model":"gpt-5.4-mini"')
    assert seen_chunk_sizes == [65_536]


def test_retry_succeeds_after_transport_error() -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("connection refused")
        return _openai_success_response(content="Recovered after transport error")

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
        retry_attempts=1,
        sleep=sleep,
    )
    try:
        response = provider.generate(_request())
    finally:
        provider.close()

    assert response.content == "Recovered after transport error"
    assert calls["count"] == 2
    assert len(sleep_calls) == 1


def test_retry_succeeds_after_streaming_transport_error() -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, stream=_FailingByteStream())
        return _openai_success_response(content="Recovered after streaming transport error")

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
        retry_attempts=1,
        sleep=sleep,
    )
    try:
        response = provider.generate(_request())
    finally:
        provider.close()

    assert response.content == "Recovered after streaming transport error"
    assert calls["count"] == 2
    assert sleep_calls == [1]


def test_retry_succeeds_after_remote_protocol_error() -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.RemoteProtocolError("server disconnected")
        return _openai_success_response(content="Recovered after protocol error")

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
        retry_attempts=1,
        sleep=sleep,
    )
    try:
        response = provider.generate(_request())
    finally:
        provider.close()

    assert response.content == "Recovered after protocol error"
    assert calls["count"] == 2
    assert sleep_calls == [1]


def test_transport_target_accepts_loopback_ips_and_named_pipe_schemes() -> None:
    assert transport_target_for_base_url("http://127.0.0.2:8000", local_hosts=()) == "local"
    assert transport_target_for_base_url("http://[::1]:8000", local_hosts=()) == "local"
    assert transport_target_for_base_url("npipe://./pipe/ollama", local_hosts=()) == "local"
    assert (
        transport_target_for_base_url("http://model.local:8000", local_hosts=("model.local",))
        == "local"
    )
    assert (
        transport_target_for_base_url(
            "http://127.0.0.2:8000",
            local_hosts=(),
            strict_local=True,
        )
        == "remote"
    )
    assert (
        transport_target_for_base_url(
            "http://model.local:8000",
            local_hosts=("model.local",),
            strict_local=True,
        )
        == "local"
    )


def test_probe_context_window_returns_fallback_on_transport_error() -> None:
    class FakeAdapter:
        def __init__(self) -> None:
            self.config = _provider_config("openai")

        def build_context_probe_request(
            self, *, api_key: str | None, model_name: str
        ) -> tuple[str, str, dict[str, str]]:
            return ("GET", "http://127.0.0.1:8000/v1/models/gpt-5.4-mini", {})

        def parse_context_probe(self, response: httpx.Response, *, model_name: str) -> int | None:
            return None

    class FakeClient:
        def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

    class FakeProvider:
        def __init__(self) -> None:
            self.adapter = FakeAdapter()
            self.config = _provider_config("openai")
            self.client = FakeClient()
            self.api_key = "test-key"

    context_window, source = _probe_context_window(FakeProvider(), model_name="gpt-5.4-mini")

    assert source == "fallback"
    assert context_window > 0


# ---------------------------------------------------------------------------
# DecodingError / decompression regression tests
# ---------------------------------------------------------------------------


class _DecodingErrorByteStream(httpx.SyncByteStream):
    """Simulates corrupt gzip body that triggers httpx.DecodingError."""

    def __iter__(self) -> Iterator[bytes]:
        raise httpx.DecodingError("Error -3 while decompressing data: incorrect header check")


def test_retry_succeeds_after_decoding_error() -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(
                200,
                stream=_DecodingErrorByteStream(),
                headers={"content-encoding": "gzip"},
            )
        return _openai_success_response(content="Recovered after decompression error")

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
        retry_attempts=1,
        sleep=sleep,
    )
    try:
        response = provider.generate(_request())
    finally:
        provider.close()

    assert response.content == "Recovered after decompression error"
    assert calls["count"] == 2
    assert len(sleep_calls) == 1


def test_decoding_error_exhausts_retries() -> None:
    sleep_calls: list[float] = []

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=_DecodingErrorByteStream(),
            headers={"content-encoding": "gzip"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
        retry_attempts=2,
        sleep=sleep,
    )
    try:
        with pytest.raises(ProviderError, match="decompression"):
            provider.generate(_request())
    finally:
        provider.close()


def test_buffered_response_strips_content_encoding() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_success_response(content="OK-stripped")

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
    )
    try:
        response = provider.generate(_request())
    finally:
        provider.close()

    assert response.content == "OK-stripped"
    assert response.rate_limits is not None
    assert response.rate_limits.rpm_limit == 9


def test_rate_limit_headers_preserved_after_encoding_strip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        resp = _openai_success_response(content="rate-limit-check")
        return httpx.Response(
            resp.status_code,
            content=resp.content,
            headers={
                **dict(resp.headers),
                "content-encoding": "identity",
                "x-ratelimit-limit-requests": "42",
                "x-ratelimit-remaining-requests": "41",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = make_provider(
        _provider_config("openai"),
        api_key="test-key",
        client=client,
    )
    try:
        response = provider.generate(_request())
    finally:
        provider.close()

    assert response.rate_limits is not None
    assert response.rate_limits.rpm_limit == 42
    assert response.rate_limits.rpm_remaining == 41
