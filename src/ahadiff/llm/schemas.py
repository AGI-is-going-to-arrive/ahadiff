from __future__ import annotations

import collections.abc as _collections_abc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ahadiff.contracts import PrivacyMode, ProviderCapabilities, ProviderConfig
    from ahadiff.safety.redact import SecretFinding
else:
    Mapping = _collections_abc.Mapping
    PrivacyMode = Any
    ProviderCapabilities = Any
    ProviderConfig = Any
    SecretFinding = Any

RequestFormat = Literal["text", "json", "json_schema"]
EnforcementMode = Literal[
    "prompt_contract",
    "json_object",
    "native_json_schema",
    "strict_tool",
]


@dataclass(frozen=True)
class RateLimitSnapshot:
    rpm_limit: int | None = None
    rpm_remaining: int | None = None
    tpm_limit: int | None = None
    tpm_remaining: int | None = None
    retry_after_seconds: float | None = None


@dataclass(frozen=True)
class CacheKeyInput:
    diff_content: str
    source_ref: str
    prompt_name: str
    prompt_fingerprint: str
    prompt_version: str
    eval_bundle_version: str
    provider_class: str
    provider_kind: str
    base_url: str
    model_id: str
    api_family: str
    api_family_version: str
    output_lang: str
    privacy_mode: PrivacyMode
    redaction_config: str
    context_bundle_hash: str
    request_payload_sha256: str
    max_output_tokens: int | None = None
    thinking_level: str = "none"
    response_format: RequestFormat = "text"
    output_schema_id: str | None = None
    output_schema_version: str | None = None
    output_schema_hash: str | None = None
    normalized_output_schema_hash: str | None = None
    enforcement_mode: EnforcementMode = "prompt_contract"
    temperature: float | None = None


@dataclass(frozen=True)
class ProviderRequest:
    prompt_name: str
    prompt_fingerprint: str
    prompt_version: str
    eval_bundle_version: str
    model: str
    payload_text: str
    diff_content: str
    source_ref: str
    output_lang: str = "en"
    privacy_mode: PrivacyMode = "strict_local"
    redacted_payload_text: str | None = None
    redaction_config: str = ""
    context_bundle_hash: str = ""
    context_artifacts: Mapping[str, bytes | str] = field(
        default_factory=lambda: dict[str, bytes | str]()
    )
    temperature: float | None = None
    max_output_tokens: int | None = None
    thinking_level: str | None = None
    response_format: RequestFormat = "text"
    output_schema_id: str | None = None
    output_schema_version: str | None = None
    output_schema: Mapping[str, Any] | None = None
    output_schema_hash: str | None = None
    normalized_output_schema_hash: str | None = None
    enforcement_mode: EnforcementMode = "prompt_contract"
    findings: tuple[SecretFinding, ...] = ()

    def effective_payload(self) -> str:
        if self.privacy_mode == "redacted_remote":
            return self.redacted_payload_text or self.payload_text
        return self.payload_text

    @property
    def is_redacted_payload(self) -> bool:
        if self.privacy_mode != "redacted_remote":
            return False
        return self.redacted_payload_text is not None


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    model_id: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None = None
    request_id: str | None = None
    rate_limits: RateLimitSnapshot | None = None
    degraded_flags: dict[str, bool] = field(default_factory=lambda: dict[str, bool]())
    notes: tuple[str, ...] = ()
    raw_json: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_tokens", max(0, self.input_tokens))
        object.__setattr__(self, "output_tokens", max(0, self.output_tokens))


@dataclass(frozen=True)
class ProbeReport:
    provider_name: str
    config: ProviderConfig
    capabilities: ProviderCapabilities
    connectivity_ok: bool
    transport_target: Literal["local", "remote"]
    notes: tuple[str, ...] = ()
    rate_limits: RateLimitSnapshot | None = None
    context_window_source: str = "fallback"


__all__ = [
    "CacheKeyInput",
    "EnforcementMode",
    "ProbeReport",
    "ProviderRequest",
    "ProviderResponse",
    "RateLimitSnapshot",
    "RequestFormat",
]
