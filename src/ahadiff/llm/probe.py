from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from ahadiff.contracts import PrivacyMode, ProviderConfig
from ahadiff.core.config import (
    SecurityConfig,
    local_hosts_for_privacy_mode,
    read_config_data,
    write_config_data,
)
from ahadiff.core.errors import InputError, ProviderError

from .cost import resolve_context_window
from .probe_limits import safe_positive_int as _safe_positive_int
from .provider import make_provider, transport_target_for_base_url
from .schemas import ProbeContextResult, ProbeReport, ProviderRequest

if TYPE_CHECKING:
    from pathlib import Path

    from ahadiff.safety.gates import TransportTarget

from ahadiff.git.repo import repo_write_lock


def probe_provider(
    *,
    provider_name: str,
    provider_class: str,
    model_name: str,
    base_url: str,
    api_key: str | None,
    api_key_env: str,
    workspace_root: Path | None,
    security_config: SecurityConfig | None,
    client: httpx.Client | None = None,
    max_concurrent: int = 3,
    qps_limit: int = 3,
    retry_attempts: int = 3,
    request_timeout_seconds: int = 30,
    persist_result: bool = True,
    privacy_mode: PrivacyMode = "explicit_remote",
) -> ProbeReport:
    base_config = ProviderConfig(
        provider_class=provider_class,  # pyright: ignore[reportArgumentType]
        model_name=model_name,
        base_url=base_url,
        api_key_env=api_key_env,
    )
    provider = make_provider(
        base_config,
        api_key=api_key,
        security_config=security_config,
        workspace_root=workspace_root,
        client=client,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        request_timeout_seconds=request_timeout_seconds,
        execution_origin="provider_test",
    )
    try:
        response = provider.generate(
            _build_probe_request(
                model_name=model_name,
                prompt_name="provider.test",
                prompt_fingerprint="provider-test-v1",
                source_ref="provider_test",
                payload_text="Reply with exactly OK.",
                privacy_mode=privacy_mode,
            )
        )
        context_result, context_source = _probe_context_window(
            provider,
            model_name=model_name,
            privacy_mode=privacy_mode,
        )
        config = ProviderConfig(
            provider_class=base_config.provider_class,
            model_name=base_config.model_name,
            base_url=base_config.base_url,
            api_key_env=base_config.api_key_env,
            probed_max_context=context_result.max_context_tokens,
            probed_max_input_tokens=context_result.max_input_tokens,
            probed_max_output_tokens=context_result.max_output_tokens,
            probed_limits_source="live" if context_result.source == "live" else "default",
            probed_tpm=response.rate_limits.tpm_limit if response.rate_limits else None,
            probed_rpm=response.rate_limits.rpm_limit if response.rate_limits else None,
            probe_timestamp=_utc_now(),
        )
        report = ProbeReport(
            provider_name=provider_name,
            config=config,
            capabilities=provider.capabilities,
            connectivity_ok=True,
            transport_target=_transport_target(base_url, security_config),
            rate_limits=response.rate_limits,
            context_window_source=context_source,
            notes=("provider probe succeeded", *context_result.warnings),
        )
    finally:
        provider.close()

    if persist_result and workspace_root is not None:
        persist_probe_result(workspace_root, provider_name=provider_name, config=report.config)
    return report


def persist_probe_result(
    workspace_root: Path, *, provider_name: str, config: ProviderConfig
) -> Path:
    if "." in provider_name:
        raise InputError("provider alias must not contain '.' because it becomes a TOML table path")
    config_path = workspace_root / ".ahadiff" / "config.toml"
    lock_path = workspace_root / ".ahadiff" / "ahadiff.lock"
    with repo_write_lock(lock_path, command="provider probe persist"):
        payload = read_config_data(config_path)
        providers = payload.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ProviderError("config key [providers] must be a table")
        providers[provider_name] = {
            key: value
            for key, value in {
                "provider_class": config.provider_class,
                "model_name": config.model_name,
                "base_url": config.base_url,
                "api_key_env": config.api_key_env,
                "max_output_tokens": config.max_output_tokens,
                "thinking_level": config.thinking_level,
                "probed_max_context": config.probed_max_context,
                "probed_max_input_tokens": config.probed_max_input_tokens,
                "probed_max_output_tokens": config.probed_max_output_tokens,
                "probed_limits_source": config.probed_limits_source,
                "model_limits_name": config.model_limits_name,
                "probed_tpm": config.probed_tpm,
                "probed_rpm": config.probed_rpm,
                "probe_timestamp": config.probe_timestamp,
            }.items()
            if value is not None
        }
        return write_config_data(config_path, payload)


def _build_probe_request(
    *,
    model_name: str,
    prompt_name: str,
    prompt_fingerprint: str,
    source_ref: str,
    payload_text: str,
    privacy_mode: PrivacyMode,
    temperature: float | None = None,
) -> ProviderRequest:
    redacted_payload_text = payload_text if privacy_mode == "redacted_remote" else None
    return ProviderRequest(
        prompt_name=prompt_name,
        prompt_fingerprint=prompt_fingerprint,
        prompt_version="provider-test-v1",
        eval_bundle_version="provider-test-v1",
        model=model_name,
        payload_text=payload_text,
        diff_content=payload_text,
        source_ref=source_ref,
        privacy_mode=privacy_mode,
        redacted_payload_text=redacted_payload_text,
        temperature=temperature,
    )


def _probe_context_window(
    provider: Any,
    *,
    model_name: str,
    privacy_mode: PrivacyMode = "explicit_remote",
) -> tuple[ProbeContextResult, str]:
    request = provider.adapter.build_context_probe_request(
        api_key=provider.api_key, model_name=model_name
    )
    if request is None:
        return _fallback_context_result(provider, model_name=model_name), "fallback"
    method, url, headers = request[:3]
    body = request[3] if len(request) == 4 else None
    try:
        response = provider.request_context_probe(
            method=method,
            url=url,
            headers=headers,
            content=body,
            privacy_mode=privacy_mode,
        )
    except (ProviderError, httpx.DecodingError, httpx.TimeoutException, httpx.TransportError):
        return _fallback_context_result(provider, model_name=model_name), "fallback"
    if response.status_code >= 400:
        return _fallback_context_result(provider, model_name=model_name), "fallback"
    try:
        probed = provider.adapter.parse_context_probe(response, model_name=model_name)
    except (KeyError, TypeError, ValueError):
        return _fallback_context_result(provider, model_name=model_name), "fallback"
    if probed is None:
        return _fallback_context_result(provider, model_name=model_name), "fallback"
    if isinstance(probed, ProbeContextResult):
        if not _probe_result_has_limits(probed):
            return _fallback_context_result(provider, model_name=model_name), "fallback"
        return probed, probed.source
    probed_value = _safe_positive_int(probed)
    if probed_value is None:
        return _fallback_context_result(provider, model_name=model_name), "fallback"
    return (
        ProbeContextResult(
            max_context_tokens=probed_value,
            max_input_tokens=None,
            max_output_tokens=None,
            source="live",
        ),
        "live",
    )


def _probe_result_has_limits(result: ProbeContextResult) -> bool:
    return any(
        value is not None
        for value in (
            result.max_context_tokens,
            result.max_input_tokens,
            result.max_output_tokens,
        )
    )


def _fallback_context_result(provider: Any, *, model_name: str) -> ProbeContextResult:
    return ProbeContextResult(
        max_context_tokens=resolve_context_window(model_name, provider.config.probed_max_context),
        max_input_tokens=None,
        max_output_tokens=None,
        source="fallback",
    )


def _transport_target(
    base_url: str,
    security_config: SecurityConfig | None,
) -> TransportTarget:
    if security_config is None:
        return transport_target_for_base_url(base_url, local_hosts=())
    return transport_target_for_base_url(
        base_url,
        local_hosts=local_hosts_for_privacy_mode(security_config, "explicit_remote"),
    )


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["persist_probe_result", "probe_provider"]
