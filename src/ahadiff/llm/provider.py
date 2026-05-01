from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import socket
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

import httpx

from ahadiff.core.config import (
    SecurityConfig,
    load_workspace_pricing_settings,
    local_hosts_for_privacy_mode,
)
from ahadiff.core.errors import ConfigError, InputError, ProviderError, SafetyError, StorageError
from ahadiff.core.ids import make_event_id
from ahadiff.core.paths import path_identity_key, workspace_identity_key
from ahadiff.safety.audit import append_audit_record, build_provider_audit_record
from ahadiff.safety.gates import TransportTarget, enforce_privacy_mode
from ahadiff.safety.injection import scan_model_output, strip_model_output_fences

from .cache import (
    assert_context_bundle_hash,
    build_cache_key,
    lookup_cached_response,
    store_cached_response,
)
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
from .usage import UsageRecord, record_usage_event

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

    from ahadiff.contracts import ProviderCapabilities, ProviderConfig

log = logging.getLogger(__name__)


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


@dataclass
class _RetryableProviderError(Exception):
    message: str
    retry_after_seconds: float | None = None


_STATE_LOCK = threading.Lock()
_SEMAPHORES: dict[str, _SemaphoreState] = {}
_RATE_LIMITERS: dict[str, _RateLimiterState] = {}
_CIRCUITS: dict[str, _CircuitState] = {}
DEFAULT_PROVIDER_RESPONSE_BYTE_CAP = 10 * 1024 * 1024


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
        response_byte_cap: int = DEFAULT_PROVIDER_RESPONSE_BYTE_CAP,
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
        if response_byte_cap < 1:
            raise ConfigError("response_byte_cap must be >= 1")
        self.max_concurrent = max_concurrent
        self.qps_limit = qps_limit
        self.retry_attempts = retry_attempts
        self.request_timeout_seconds = request_timeout_seconds
        self.response_byte_cap = response_byte_cap
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
        if transport_target == "remote":
            validate_remote_url(self.config.base_url)

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

        cache_parts = CacheKeyInput(
            diff_content=request.diff_content,
            source_ref=request.source_ref,
            prompt_name=request.prompt_name,
            prompt_fingerprint=request.prompt_fingerprint,
            prompt_version=request.prompt_version,
            eval_bundle_version=request.eval_bundle_version,
            provider_class=self.config.provider_class,
            provider_kind=self.capabilities.provider_kind,
            base_url=self.config.base_url,
            model_id=request.model,
            api_family=self.capabilities.api_family,
            api_family_version=self.capabilities.api_family_version,
            output_lang=request.output_lang,
            privacy_mode=request.privacy_mode,
            redaction_config=request.redaction_config,
            context_bundle_hash=context_bundle_hash,
            request_payload_sha256=hashlib.sha256(
                request_to_send.effective_payload().encode("utf-8")
            ).hexdigest(),
        )
        cache_key = build_cache_key(cache_parts)
        if self.workspace_root is not None:
            cached_response = lookup_cached_response(
                self.workspace_root,
                cache_parts,
                cache_key=cache_key,
            )
            if cached_response is not None:
                cache_hit_response = replace(
                    cached_response,
                    notes=_append_unique_notes(
                        cached_response.notes,
                        "cache_hit",
                        f"cache_key={cache_key}",
                    ),
                )
                self._append_usage_record(
                    request=request_to_send,
                    response=cache_hit_response,
                    cache_key=cache_key,
                    cache_hit=True,
                    cost_usd=0.0,
                    pricing_version="cache-hit",
                    cost_confidence="high",
                )
                return cache_hit_response

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
                if self.workspace_root is not None:
                    store_cached_response(
                        self.workspace_root,
                        cache_parts,
                        final_response,
                        cache_key=cache_key,
                    )
                    self._append_usage_record(
                        request=request_to_send,
                        response=final_response,
                        cache_key=cache_key,
                        cache_hit=False,
                        cost_usd=cost.cost_usd,
                        pricing_version=cost.pricing_version,
                        cost_confidence=cost.cost_confidence,
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
        request_target = transport_target_for_base_url(
            url,
            local_hosts=local_hosts_for_privacy_mode(
                self.security_config,
                request.privacy_mode,
            ),
            strict_local=request.privacy_mode == "strict_local",
        )
        if request.privacy_mode == "strict_local" and request_target != "local":
            raise SafetyError("strict_local mode forbids remote transport")
        # DNS-pinning: resolve + validate once, then connect to the validated
        # IP directly so a DNS rebinding attack cannot redirect the TCP
        # connection to a private address between validation and connect.
        stream_extensions: dict[str, Any] | None = None
        if request_target == "remote":
            pinned_ip = validate_remote_url(url)
            if pinned_ip is not None:
                url, original_host, sni_hostname = _pin_url_to_ip(url, pinned_ip)
                headers = {**headers, "Host": original_host}
                if sni_hostname is not None:
                    stream_extensions = {"sni_hostname": sni_hostname.encode("ascii")}
        with self.client.stream(
            method,
            url,
            headers=headers,
            json=payload,
            follow_redirects=False,
            extensions=stream_extensions,
        ) as response:
            if response.is_redirect:
                raise ProviderError("provider redirects are not allowed")
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
            buffered_response = httpx.Response(
                response.status_code,
                headers=response.headers,
                content=self._read_capped_response_body(response),
                request=response.request,
                extensions=response.extensions,
            )
        parsed = self.adapter.parse_response(buffered_response)
        guarded_content = strip_model_output_fences(parsed.content)
        if not guarded_content.strip():
            raise ProviderError("provider returned empty response")
        output_guard_notes = tuple(scan_model_output(parsed.content))
        return replace(
            parsed,
            content=guarded_content,
            rate_limits=parse_rate_limit_headers(buffered_response.headers),
            notes=_append_unique_notes(parsed.notes, *output_guard_notes),
        )

    def _read_capped_response_body(self, response: httpx.Response) -> bytes:
        body = bytearray()
        total_bytes = 0
        for chunk in response.iter_bytes(chunk_size=65_536):
            total_bytes += len(chunk)
            if total_bytes > self.response_byte_cap:
                raise ProviderError(
                    f"provider response exceeded byte cap ({self.response_byte_cap} bytes)"
                )
            body.extend(chunk)
        return bytes(body)

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

    def _append_usage_record(
        self,
        *,
        request: ProviderRequest,
        response: ProviderResponse,
        cache_key: str,
        cache_hit: bool,
        cost_usd: float | None,
        pricing_version: str | None,
        cost_confidence: str,
    ) -> None:
        if self.workspace_root is None:
            return
        try:
            record_usage_event(
                UsageRecord(
                    workspace_identity=workspace_identity_key(self.workspace_root),
                    provider_class=self.config.provider_class,
                    api_family=self.capabilities.api_family,
                    api_family_version=self.capabilities.api_family_version,
                    model_id=response.model_id,
                    prompt_name=request.prompt_name,
                    prompt_fingerprint=request.prompt_fingerprint,
                    prompt_version=request.prompt_version,
                    eval_bundle_version=request.eval_bundle_version,
                    output_lang=request.output_lang,
                    privacy_mode=request.privacy_mode,
                    source_ref=request.source_ref,
                    cache_key=cache_key,
                    cache_hit=cache_hit,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cost_usd=cost_usd,
                    pricing_version=pricing_version,
                    cost_confidence=cost_confidence,
                    execution_origin=self.execution_origin,
                    request_id=response.request_id,
                )
            )
        except (InputError, OSError, sqlite3.Error, StorageError) as error:
            log.warning("failed to record LLM usage for cache key %s: %s", cache_key, error)


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


def _append_unique_notes(notes: tuple[str, ...], *new_notes: str) -> tuple[str, ...]:
    merged = list(notes)
    for note in new_notes:
        if note not in merged:
            merged.append(note)
    return tuple(merged)


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


def _is_non_public_ip(addr: IPv4Address | IPv6Address) -> bool:
    if isinstance(addr, IPv6Address) and addr.ipv4_mapped is not None:
        return _is_non_public_ip(addr.ipv4_mapped)
    return (
        addr.is_private
        or addr.is_reserved
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
    )


def _resolve_hostname_ips(hostname: str) -> list[IPv4Address | IPv6Address]:
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return []
    addrs: list[IPv4Address | IPv6Address] = []
    seen: set[str] = set()
    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip_str: str = str(sockaddr[0])
        if ip_str in seen:
            continue
        seen.add(ip_str)
        with contextlib.suppress(ValueError):
            addrs.append(ip_address(ip_str))
    return addrs


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
        addr = ip_address(hostname)
        if addr.is_loopback:
            return "local"
        if _is_non_public_ip(addr):
            return "local"
    except ValueError:
        pass
    return "remote"


def validate_remote_url(base_url: str) -> str | None:
    """Validate *base_url* for remote privacy mode.

    Returns the first validated public IP string when DNS resolution was
    performed (hostname case), or ``None`` when the URL already contains a
    literal IP address.  The caller can use the returned IP to pin the TCP
    connection, closing the TOCTOU gap between DNS validation and the actual
    HTTP request.
    """
    parsed = urlparse(base_url)
    if parsed.scheme in {"unix", "http+unix", "npipe", "http+npipe"}:
        raise SafetyError(
            f"local transport scheme {parsed.scheme!r} not allowed in remote privacy mode"
        )
    hostname = parsed.hostname
    if hostname is None:
        raise SafetyError(f"unable to determine hostname for base_url {base_url!r}")
    try:
        addr = ip_address(hostname)
        if _is_non_public_ip(addr):
            raise SafetyError(
                f"private/reserved IP {hostname} not allowed in remote privacy mode"
            )
        return None
    except ValueError:
        pass
    resolved = _resolve_hostname_ips(hostname)
    if not resolved:
        raise SafetyError(
            f"hostname {hostname!r} could not be resolved in remote privacy mode"
        )
    for addr in resolved:
        if _is_non_public_ip(addr):
            raise SafetyError(
                f"hostname {hostname!r} resolves to private/reserved IP {addr}, "
                "not allowed in remote privacy mode"
            )
    return str(resolved[0])


def _pin_url_to_ip(
    url: str,
    pinned_ip: str,
) -> tuple[str, str, str | None]:
    """Rewrite *url* so the hostname is replaced by *pinned_ip*.

    Returns ``(pinned_url, host_header, sni_hostname_or_none)``.

    * ``pinned_url`` — URL with hostname replaced by the validated IP.
    * ``host_header`` — original authority for the ``Host`` header
      (includes port when non-default).
    * ``sni_hostname_or_none`` — the original hostname when the scheme is
      ``https`` (used for TLS SNI); ``None`` for plain ``http``.
    """
    parsed = urlparse(url)
    original_hostname = parsed.hostname or ""
    # Bracket IPv6 addresses in URLs.
    ip_host = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    # Rebuild netloc preserving port and userinfo.
    port_suffix = f":{parsed.port}" if parsed.port is not None else ""
    userinfo = f"{parsed.username}@" if parsed.username else ""
    new_netloc = f"{userinfo}{ip_host}{port_suffix}"
    pinned_url = parsed._replace(netloc=new_netloc).geturl()
    sni_hostname = original_hostname if parsed.scheme == "https" else None
    # Host header must include port when non-default (RFC 7230 §5.4).
    # Bracket IPv6 hostnames in the Host header per RFC 2732.
    host_name = f"[{original_hostname}]" if ":" in original_hostname else original_hostname
    host_header = f"{host_name}{port_suffix}"
    return pinned_url, host_header, sni_hostname


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
    response_byte_cap: int = DEFAULT_PROVIDER_RESPONSE_BYTE_CAP,
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
        response_byte_cap=response_byte_cap,
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
    "DEFAULT_PROVIDER_RESPONSE_BYTE_CAP",
    "ManagedProvider",
    "Provider",
    "adapter_conformance_test",
    "make_provider",
    "reset_provider_runtime_state",
    "transport_target_for_base_url",
    "validate_remote_url",
]
