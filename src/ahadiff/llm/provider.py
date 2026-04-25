from __future__ import annotations

import hashlib
import json
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from ipaddress import ip_address
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

import httpx

from ahadiff.core.config import (
    SecurityConfig,
    load_workspace_pricing_settings,
    local_hosts_for_privacy_mode,
)
from ahadiff.core.errors import ConfigError, ProviderError, SafetyError
from ahadiff.core.ids import make_event_id
from ahadiff.core.paths import path_identity_key
from ahadiff.safety.audit import append_audit_record, build_provider_audit_record
from ahadiff.safety.gates import TransportTarget, enforce_privacy_mode

from .cache import assert_context_bundle_hash, build_cache_key
from .cost import (
    DEFAULT_INPUT_TOKEN_BUDGET,
    DEFAULT_OPENROUTER_MODELS_URL,
    DEFAULT_OPENROUTER_REFRESH_SECONDS,
    DEFAULT_OUTPUT_TOKEN_BUDGET,
    PricingEntry,
    clip_text_to_context_limit,
    enforce_token_budget,
    estimate_cost_usd,
    estimate_request_tokens,
    fetch_openrouter_pricing_catalog,
    parse_rate_limit_headers,
    resolve_context_window,
    resolve_pricing_entry,
)
from .schemas import CacheKeyInput, ProviderRequest, ProviderResponse

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

    from ahadiff.contracts import ProviderCapabilities, ProviderConfig


class Provider(Protocol):
    config: ProviderConfig
    capabilities: ProviderCapabilities

    def generate(self, request: ProviderRequest) -> ProviderResponse: ...


class AdapterBase(ABC):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    @abstractmethod
    def build_request(
        self,
        request: ProviderRequest,
        *,
        api_key: str | None,
    ) -> tuple[str, str, dict[str, str], dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def parse_response(self, response: httpx.Response) -> ProviderResponse:
        raise NotImplementedError

    def build_context_probe_request(
        self,
        *,
        api_key: str | None,
        model_name: str,
    ) -> tuple[str, str, dict[str, str]] | None:
        return None

    def parse_context_probe(self, response: httpx.Response, *, model_name: str) -> int | None:
        return None


@dataclass
class _SemaphoreState:
    limit: int
    active: int = 0
    condition: threading.Condition = field(default_factory=threading.Condition)


@dataclass
class _RateLimiterState:
    timestamps: deque[float] = field(default_factory=lambda: deque[float]())
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class _CircuitState:
    failures: int = 0
    opened_until: float = 0.0


@dataclass(frozen=True)
class _RetryableProviderError(Exception):
    message: str
    retry_after_seconds: float | None = None


_STATE_LOCK = threading.Lock()
_SEMAPHORES: dict[str, _SemaphoreState] = {}
_RATE_LIMITERS: dict[str, _RateLimiterState] = {}
_CIRCUITS: dict[str, _CircuitState] = {}


class ManagedProvider:
    def __init__(
        self,
        adapter: AdapterBase,
        *,
        api_key: str | None,
        security_config: SecurityConfig | None,
        workspace_root: Path | None,
        client: httpx.Client | None = None,
        max_concurrent: int = 3,
        qps_limit: int = 3,
        retry_attempts: int = 3,
        request_timeout_seconds: int = 30,
        circuit_failure_threshold: int = 5,
        circuit_cooldown: int = 60,
        input_token_budget: int = DEFAULT_INPUT_TOKEN_BUDGET,
        output_token_budget: int = DEFAULT_OUTPUT_TOKEN_BUDGET,
        pricing_overrides: Mapping[str, PricingEntry] | None = None,
        openrouter_enabled: bool = True,
        openrouter_models_url: str = DEFAULT_OPENROUTER_MODELS_URL,
        openrouter_refresh_seconds: int = DEFAULT_OPENROUTER_REFRESH_SECONDS,
        openrouter_pricing_fetcher: Callable[[str, int], Mapping[str, PricingEntry]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        execution_origin: str = "runtime",
    ) -> None:
        self.adapter = adapter
        self.config = adapter.config
        self.capabilities = adapter.capabilities
        self.api_key = api_key
        self.security_config = security_config or SecurityConfig()
        self.workspace_root = workspace_root
        if max_concurrent < 1:
            raise ConfigError("max_concurrent must be >= 1")
        self.max_concurrent = max_concurrent
        self.qps_limit = qps_limit
        self.retry_attempts = retry_attempts
        self.request_timeout_seconds = request_timeout_seconds
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_cooldown = circuit_cooldown
        self.input_token_budget = input_token_budget
        self.output_token_budget = output_token_budget
        self.pricing_overrides = dict(pricing_overrides or {})
        self.openrouter_enabled = openrouter_enabled
        self.openrouter_models_url = openrouter_models_url
        self.openrouter_refresh_seconds = openrouter_refresh_seconds
        self.openrouter_pricing_fetcher = (
            fetch_openrouter_pricing_catalog
            if openrouter_pricing_fetcher is None
            else openrouter_pricing_fetcher
        )
        self.sleep = sleep
        self.monotonic = monotonic
        self.execution_origin = execution_origin
        self._client_owned = client is None
        self.client = client or httpx.Client(timeout=request_timeout_seconds, trust_env=False)

    def close(self) -> None:
        if self._client_owned:
            self.client.close()

    def __enter__(self) -> ManagedProvider:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        transport_target = transport_target_for_base_url(
            self.config.base_url,
            local_hosts=local_hosts_for_privacy_mode(
                self.security_config,
                request.privacy_mode,
            ),
            strict_local=request.privacy_mode == "strict_local",
        )
        if (
            request.privacy_mode == "strict_local"
            and transport_target == "local"
            and getattr(self.client, "_trust_env", False)
        ):
            raise SafetyError("strict_local mode requires an http client with trust_env=False")
        payload_text = request.effective_payload()
        enforce_privacy_mode(
            request.privacy_mode,
            target=transport_target,
            text=payload_text,
            findings=request.findings,
            is_redacted=request.is_redacted_payload,
        )

        context_bundle_hash = request.context_bundle_hash
        if request.context_artifacts:
            context_bundle_hash = assert_context_bundle_hash(
                request.context_bundle_hash,
                request.context_artifacts,
            )

        request_to_send = request
        estimate = estimate_request_tokens(request_to_send, self.capabilities.tokenizer_estimation)
        max_context = resolve_context_window(request.model, self.config.probed_max_context)
        degraded_flags: dict[str, bool] = {}
        notes: list[str] = []
        if estimate.input_tokens > int(max_context * 0.9):
            clipped_payload = clip_text_to_context_limit(
                payload_text,
                max_tokens=int(max_context * 0.9),
                strategy=self.capabilities.tokenizer_estimation,
            )
            if clipped_payload != payload_text:
                request_to_send = replace(
                    request_to_send,
                    payload_text=clipped_payload,
                    redacted_payload_text=(
                        clipped_payload if request.privacy_mode == "redacted_remote" else None
                    ),
                )
                estimate = estimate_request_tokens(
                    request_to_send,
                    self.capabilities.tokenizer_estimation,
                )
                degraded_flags["token_exceeded"] = True
                notes.append("prompt_clipped_for_context")
        if estimate.input_tokens > int(max_context * 0.9):
            raise ProviderError("context window exceeded after clipping")

        enforce_token_budget(
            input_tokens=estimate.input_tokens,
            output_tokens=request.max_output_tokens,
            input_budget=self.input_token_budget,
            output_budget=self.output_token_budget,
        )

        cache_key = build_cache_key(
            CacheKeyInput(
                diff_content=request.diff_content,
                source_ref=request.source_ref,
                prompt_version=request.prompt_version,
                eval_bundle_version=request.eval_bundle_version,
                model_id=request.model,
                api_family=self.capabilities.api_family,
                api_family_version=self.capabilities.api_family_version,
                output_lang=request.output_lang,
                privacy_mode=request.privacy_mode,
                redaction_config=request.redaction_config,
                context_bundle_hash=context_bundle_hash,
            )
        )

        self._assert_circuit_closed()
        last_error: Exception | None = None
        with _provider_slot(self._provider_key, self.max_concurrent):
            for attempt in range(self.retry_attempts + 1):
                self._wait_for_rate_window()
                try:
                    response = self._send_once(request_to_send)
                except SafetyError:
                    raise
                except _RetryableProviderError as error:
                    last_error = ProviderError(error.message)
                    if attempt >= self.retry_attempts:
                        break
                    self.sleep(error.retry_after_seconds or min(2**attempt, 8))
                    continue
                except httpx.TransportError as error:
                    last_error = ProviderError(f"provider transport failed: {error}")
                    if attempt >= self.retry_attempts:
                        break
                    self.sleep(min(2**attempt, 8))
                    continue
                except json.JSONDecodeError as error:
                    last_error = ProviderError(f"provider returned invalid JSON: {error}")
                    if attempt >= self.retry_attempts:
                        break
                    self.sleep(min(2**attempt, 8))
                    continue
                except (KeyError, IndexError, TypeError, ValueError) as error:
                    last_error = ProviderError(f"provider returned malformed payload: {error}")
                    if attempt >= self.retry_attempts:
                        break
                    self.sleep(min(2**attempt, 8))
                    continue
                self._record_success()
                cost = estimate_cost_usd(
                    provider_class=self.config.provider_class,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    model_id=response.model_id,
                    pricing_entry=self._resolve_pricing_entry(response.model_id),
                )
                merged_flags = dict(response.degraded_flags)
                merged_flags.update(degraded_flags)
                merged_notes = (*response.notes, *notes, f"cache_key={cache_key}")
                final_response = replace(
                    response,
                    degraded_flags=merged_flags,
                    notes=merged_notes,
                )
                self._append_audit_record(
                    request=request_to_send,
                    response=final_response,
                    cache_key=cache_key,
                    cost=cost,
                )
                return final_response

        self._record_failure()
        raise ProviderError(str(last_error) if last_error else "provider request failed")

    @property
    def _provider_key(self) -> str:
        workspace_scope = "__process__"
        if self.workspace_root is not None:
            workspace_scope = path_identity_key(self.workspace_root)
        return (
            f"{workspace_scope}:"
            f"{self.config.provider_class}:"
            f"{self.config.base_url.rstrip('/')}:"
            f"{self.config.model_name}"
        )

    def _send_once(self, request: ProviderRequest) -> ProviderResponse:
        method, url, headers, payload = self.adapter.build_request(request, api_key=self.api_key)
        response = self.client.request(method, url, headers=headers, json=payload)
        if response.status_code in {401, 403}:
            raise SafetyError("provider authentication failed")
        if response.status_code == 429:
            retry_after = parse_rate_limit_headers(response.headers).retry_after_seconds
            raise _RetryableProviderError("provider rate limit exceeded", retry_after)
        if response.status_code in {408, 409} or response.status_code >= 500:
            raise _RetryableProviderError(
                f"provider returned retryable status {response.status_code}"
            )
        if response.status_code >= 400:
            raise ProviderError(f"provider request failed with status {response.status_code}")
        parsed = self.adapter.parse_response(response)
        if not parsed.content.strip():
            raise ProviderError("provider returned empty response")
        return replace(parsed, rate_limits=parse_rate_limit_headers(response.headers))

    def _assert_circuit_closed(self) -> None:
        with _STATE_LOCK:
            circuit = _CIRCUITS.setdefault(self._provider_key, _CircuitState())
            if circuit.opened_until > self.monotonic():
                raise ProviderError("provider circuit breaker is open")

    def _record_success(self) -> None:
        with _STATE_LOCK:
            circuit = _CIRCUITS.setdefault(self._provider_key, _CircuitState())
            circuit.failures = 0
            circuit.opened_until = 0.0

    def _record_failure(self) -> None:
        with _STATE_LOCK:
            circuit = _CIRCUITS.setdefault(self._provider_key, _CircuitState())
            circuit.failures += 1
            if circuit.failures >= self.circuit_failure_threshold:
                circuit.opened_until = self.monotonic() + self.circuit_cooldown

    def _wait_for_rate_window(self) -> None:
        if self.qps_limit <= 0:
            return
        state = _rate_limiter_state(self._provider_key)
        while True:
            with state.lock:
                now = self.monotonic()
                if state.timestamps and now < state.timestamps[0]:
                    state.timestamps.clear()
                while state.timestamps and now - state.timestamps[0] >= 1.0:
                    state.timestamps.popleft()
                if len(state.timestamps) < self.qps_limit:
                    state.timestamps.append(now)
                    return
                wait_seconds = max(0.0, 1.0 - (now - state.timestamps[0]))
            self.sleep(wait_seconds)

    def _append_audit_record(
        self,
        *,
        request: ProviderRequest,
        response: ProviderResponse,
        cache_key: str,
        cost: Any,
    ) -> None:
        if self.workspace_root is None:
            return
        audit_dir = self.workspace_root / ".ahadiff"
        audit_path = audit_dir / "audit.jsonl"
        private_audit_path = audit_dir / "audit.private.jsonl"
        event_id = make_event_id()
        request_hash = hashlib.sha256(
            f"{event_id}:{request.effective_payload()}".encode()
        ).hexdigest()
        principal_hash = (
            hashlib.sha256((self.api_key or "").encode("utf-8")).hexdigest()
            if self.api_key
            else "local"
        )
        record = build_provider_audit_record(
            event_id=event_id,
            event_type="provider_call",
            provider_class=self.config.provider_class,
            model_id=response.model_id,
            prompt_name=request.prompt_name,
            prompt_fingerprint=request.prompt_fingerprint,
            request_hash=request_hash,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=cost.cost_usd,
            pricing_version=cost.pricing_version,
            cost_confidence=cost.cost_confidence,
            billing_mode="token_budget",
            execution_origin=self.execution_origin,
            api_principal_hash=principal_hash,
            note=f"cache_key={cache_key}",
        )
        append_audit_record(audit_path, record)
        if request.privacy_mode == "strict_local":
            append_audit_record(private_audit_path, record)

    def _resolve_pricing_entry(self, model_id: str) -> PricingEntry | None:
        return resolve_pricing_entry(
            provider_class=self.config.provider_class,
            model_id=model_id,
            base_url=self.config.base_url,
            pricing_entry=self.pricing_overrides.get(model_id),
            openrouter_enabled=self.openrouter_enabled,
            openrouter_models_url=self.openrouter_models_url,
            openrouter_refresh_seconds=self.openrouter_refresh_seconds,
            openrouter_fetcher=self.openrouter_pricing_fetcher,
        )


@contextmanager
def _provider_slot(key: str, limit: int) -> Iterator[None]:
    state = _semaphore_state(key, limit)
    with state.condition:
        while state.active >= state.limit:
            state.condition.wait()
        state.active += 1
    try:
        yield
    finally:
        with state.condition:
            state.active -= 1
            state.condition.notify_all()


def _semaphore_state(key: str, limit: int) -> _SemaphoreState:
    with _STATE_LOCK:
        state = _SEMAPHORES.get(key)
        if state is None:
            state = _SemaphoreState(limit=limit)
            _SEMAPHORES[key] = state
    with state.condition:
        if state.limit != limit:
            state.limit = limit
            state.condition.notify_all()
    return state


def _rate_limiter_state(key: str) -> _RateLimiterState:
    with _STATE_LOCK:
        return _RATE_LIMITERS.setdefault(key, _RateLimiterState())


def reset_provider_runtime_state(provider_key: str | None = None) -> None:
    with _STATE_LOCK:
        if provider_key is None:
            _SEMAPHORES.clear()
            _RATE_LIMITERS.clear()
            _CIRCUITS.clear()
            return
        _SEMAPHORES.pop(provider_key, None)
        _RATE_LIMITERS.pop(provider_key, None)
        _CIRCUITS.pop(provider_key, None)


def transport_target_for_base_url(
    base_url: str,
    *,
    local_hosts: tuple[str, ...],
    strict_local: bool = False,
) -> TransportTarget:
    parsed = urlparse(base_url)
    if parsed.scheme in {"unix", "http+unix", "npipe", "http+npipe"}:
        return "local"
    hostname = parsed.hostname
    if hostname is None:
        raise SafetyError(f"unable to determine transport boundary for base_url {base_url!r}")
    hostname_normalized = hostname.lower()
    normalized_local_hosts = {item.lower() for item in local_hosts}
    if strict_local:
        if hostname_normalized in {"localhost", "127.0.0.1", "::1", *normalized_local_hosts}:
            return "local"
        return "remote"
    if hostname_normalized in {"localhost", *normalized_local_hosts}:
        return "local"
    try:
        if ip_address(hostname).is_loopback:
            return "local"
    except ValueError:
        pass
    return "remote"


def adapter_conformance_test(provider: Provider) -> None:
    capabilities = provider.capabilities
    if not capabilities.provider_kind:
        raise ProviderError("provider_kind must not be empty")
    if (
        provider.config.supports_temperature is not None
        and provider.config.supports_temperature != capabilities.supports_temperature
    ):
        raise ProviderError("ProviderConfig.supports_temperature disagrees with capabilities")
    if capabilities.tokenizer_estimation not in {"tiktoken", "char_div_4", "probe_cached"}:
        raise ProviderError("tokenizer_estimation is outside the frozen contract")


def make_provider(
    config: ProviderConfig,
    *,
    api_key: str | None = None,
    security_config: SecurityConfig | None = None,
    workspace_root: Path | None = None,
    client: httpx.Client | None = None,
    max_concurrent: int = 3,
    qps_limit: int = 3,
    retry_attempts: int = 3,
    request_timeout_seconds: int = 30,
    circuit_failure_threshold: int = 5,
    circuit_cooldown: int = 60,
    input_token_budget: int = DEFAULT_INPUT_TOKEN_BUDGET,
    output_token_budget: int = DEFAULT_OUTPUT_TOKEN_BUDGET,
    pricing_overrides: Mapping[str, PricingEntry] | None = None,
    openrouter_pricing_fetcher: Callable[[str, int], Mapping[str, PricingEntry]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    execution_origin: str = "runtime",
) -> ManagedProvider:
    from .adapters.anthropic import AnthropicAdapter
    from .adapters.azure import AzureOpenAIAdapter
    from .adapters.cherryin import CherryINAdapter
    from .adapters.gemini import GeminiAdapter
    from .adapters.newapi import NewAPIAdapter
    from .adapters.ollama import OllamaAdapter
    from .adapters.openai import OpenAIChatAdapter
    from .adapters.openai_responses import OpenAIResponsesAdapter

    registry: dict[str, type[AdapterBase]] = {
        "anthropic": AnthropicAdapter,
        "azure": AzureOpenAIAdapter,
        "cherryin": CherryINAdapter,
        "gemini": GeminiAdapter,
        "newapi": NewAPIAdapter,
        "ollama": OllamaAdapter,
        "openai": OpenAIChatAdapter,
        "openai_responses": OpenAIResponsesAdapter,
    }
    try:
        adapter_type = registry[config.provider_class]
    except KeyError as error:
        raise ProviderError(f"unsupported provider_class: {config.provider_class}") from error

    effective_pricing_overrides = dict(pricing_overrides or {})
    openrouter_enabled = True
    openrouter_models_url = DEFAULT_OPENROUTER_MODELS_URL
    openrouter_refresh_seconds = DEFAULT_OPENROUTER_REFRESH_SECONDS
    if workspace_root is not None:
        pricing_settings = load_workspace_pricing_settings(workspace_root)
        effective_pricing_overrides = {
            model_id: PricingEntry(
                input_per_million_usd=override.input_per_million_usd,
                output_per_million_usd=override.output_per_million_usd,
                request_per_call_usd=override.request_per_call_usd,
                pricing_version="user-config",
                source_url="config://ahadiff/pricing",
            )
            for model_id, override in pricing_settings.model_overrides.items()
        } | effective_pricing_overrides
        openrouter_enabled = pricing_settings.openrouter_enabled
        openrouter_models_url = pricing_settings.openrouter_models_url
        openrouter_refresh_seconds = pricing_settings.openrouter_refresh_seconds

    return ManagedProvider(
        adapter_type(config),
        api_key=api_key,
        security_config=security_config,
        workspace_root=workspace_root,
        client=client,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        request_timeout_seconds=request_timeout_seconds,
        circuit_failure_threshold=circuit_failure_threshold,
        circuit_cooldown=circuit_cooldown,
        input_token_budget=input_token_budget,
        output_token_budget=output_token_budget,
        pricing_overrides=effective_pricing_overrides,
        openrouter_enabled=openrouter_enabled,
        openrouter_models_url=openrouter_models_url,
        openrouter_refresh_seconds=openrouter_refresh_seconds,
        openrouter_pricing_fetcher=openrouter_pricing_fetcher,
        sleep=sleep,
        monotonic=monotonic,
        execution_origin=execution_origin,
    )


__all__ = [
    "AdapterBase",
    "ManagedProvider",
    "Provider",
    "adapter_conformance_test",
    "make_provider",
    "reset_provider_runtime_state",
    "transport_target_for_base_url",
]
