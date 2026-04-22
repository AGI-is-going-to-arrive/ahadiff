from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ahadiff.contracts import PrivacyMode, ProviderConfig
from ahadiff.core.config import SecurityConfig, read_config_data, write_config_data
from ahadiff.core.errors import InputError, ProviderError

from .cost import resolve_context_window
from .provider import make_provider, transport_target_for_base_url
from .schemas import ProbeReport, ProviderRequest

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

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
        supports_temperature = _probe_temperature_support(
            provider,
            model_name=model_name,
            privacy_mode=privacy_mode,
        )
        context_window, context_source = _probe_context_window(provider, model_name=model_name)
        config = ProviderConfig(
            provider_class=base_config.provider_class,
            model_name=base_config.model_name,
            base_url=base_config.base_url,
            api_key_env=base_config.api_key_env,
            probed_max_context=context_window,
            probed_tpm=response.rate_limits.tpm_limit if response.rate_limits else None,
            probed_rpm=response.rate_limits.rpm_limit if response.rate_limits else None,
            supports_temperature=supports_temperature,
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
            notes=("provider probe succeeded",),
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
                "probed_max_context": config.probed_max_context,
                "probed_tpm": config.probed_tpm,
                "probed_rpm": config.probed_rpm,
                "supports_temperature": config.supports_temperature,
                "probe_timestamp": config.probe_timestamp,
            }.items()
            if value is not None
        }
        return write_config_data(config_path, payload)


def _probe_temperature_support(
    provider: Any, *, model_name: str, privacy_mode: PrivacyMode
) -> bool:
    if not provider.capabilities.supports_temperature:
        return False
    try:
        low = provider.generate(
            _build_probe_request(
                model_name=model_name,
                prompt_name="provider.temperature",
                prompt_fingerprint="provider-temperature-v1",
                source_ref="provider_temperature_low",
                payload_text="Return a short token.",
                privacy_mode=privacy_mode,
                temperature=0.0,
            )
        )
        high = provider.generate(
            _build_probe_request(
                model_name=model_name,
                prompt_name="provider.temperature",
                prompt_fingerprint="provider-temperature-v1",
                source_ref="provider_temperature_high",
                payload_text="Return a short token.",
                privacy_mode=privacy_mode,
                temperature=1.0,
            )
        )
    except ProviderError:
        return False
    return low.content != "" and high.content != ""


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


def _probe_context_window(provider: Any, *, model_name: str) -> tuple[int, str]:
    request = provider.adapter.build_context_probe_request(
        api_key=provider.api_key, model_name=model_name
    )
    if request is None:
        return resolve_context_window(model_name, provider.config.probed_max_context), "fallback"
    method, url, headers = request
    response = provider.client.request(method, url, headers=headers)
    if response.status_code >= 400:
        return resolve_context_window(model_name, provider.config.probed_max_context), "fallback"
    probed = provider.adapter.parse_context_probe(response, model_name=model_name)
    if probed is None:
        return resolve_context_window(model_name, provider.config.probed_max_context), "fallback"
    return probed, "live"


def _transport_target(
    base_url: str,
    security_config: SecurityConfig | None,
) -> TransportTarget:
    local_hosts = () if security_config is None else security_config.local_hosts
    return transport_target_for_base_url(base_url, local_hosts=local_hosts)


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["persist_probe_result", "probe_provider"]
