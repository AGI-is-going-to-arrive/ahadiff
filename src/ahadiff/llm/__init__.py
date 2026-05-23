from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .cache import assert_context_bundle_hash, build_cache_key, build_context_bundle_hash
    from .cost import (
        DEFAULT_CONTEXT_WINDOW,
        DEFAULT_INPUT_TOKEN_BUDGET,
        DEFAULT_OUTPUT_TOKEN_BUDGET,
        clip_text_to_context_limit,
        effective_output_cap,
        enforce_token_budget,
        estimate_cost_usd,
        estimate_request_tokens,
        parse_rate_limit_headers,
        resolve_context_window,
        resolve_model_limits,
    )
    from .probe import persist_probe_result, probe_provider
    from .provider import (
        DEFAULT_PROVIDER_RESPONSE_BYTE_CAP,
        AdapterBase,
        ManagedProvider,
        Provider,
        adapter_conformance_test,
        make_provider,
    )
    from .schemas import (
        CacheKeyInput,
        EnforcementMode,
        ProbeContextResult,
        ProbeReport,
        ProviderRequest,
        ProviderResponse,
        RateLimitSnapshot,
    )
    from .structured import (
        OutputSchemaSpec,
        canonical_json,
        normalize_schema_for_provider,
        schema_hash,
        schema_spec_for,
    )
    from .validation_retry import (
        StructuredCallResult,
        build_validation_retry_feedback,
        generate_with_validation_retry,
    )

__all__ = [
    "AdapterBase",
    "CacheKeyInput",
    "EnforcementMode",
    "DEFAULT_CONTEXT_WINDOW",
    "DEFAULT_INPUT_TOKEN_BUDGET",
    "DEFAULT_OUTPUT_TOKEN_BUDGET",
    "DEFAULT_PROVIDER_RESPONSE_BYTE_CAP",
    "ManagedProvider",
    "ProbeContextResult",
    "ProbeReport",
    "Provider",
    "ProviderRequest",
    "ProviderResponse",
    "RateLimitSnapshot",
    "OutputSchemaSpec",
    "StructuredCallResult",
    "adapter_conformance_test",
    "assert_context_bundle_hash",
    "build_validation_retry_feedback",
    "build_cache_key",
    "build_context_bundle_hash",
    "clip_text_to_context_limit",
    "effective_output_cap",
    "enforce_token_budget",
    "estimate_cost_usd",
    "estimate_request_tokens",
    "make_provider",
    "parse_rate_limit_headers",
    "persist_probe_result",
    "probe_provider",
    "canonical_json",
    "normalize_schema_for_provider",
    "resolve_context_window",
    "resolve_model_limits",
    "schema_hash",
    "schema_spec_for",
    "generate_with_validation_retry",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AdapterBase": ("provider", "AdapterBase"),
    "CacheKeyInput": ("schemas", "CacheKeyInput"),
    "EnforcementMode": ("schemas", "EnforcementMode"),
    "DEFAULT_CONTEXT_WINDOW": ("cost", "DEFAULT_CONTEXT_WINDOW"),
    "DEFAULT_INPUT_TOKEN_BUDGET": ("cost", "DEFAULT_INPUT_TOKEN_BUDGET"),
    "DEFAULT_OUTPUT_TOKEN_BUDGET": ("cost", "DEFAULT_OUTPUT_TOKEN_BUDGET"),
    "DEFAULT_PROVIDER_RESPONSE_BYTE_CAP": ("provider", "DEFAULT_PROVIDER_RESPONSE_BYTE_CAP"),
    "ManagedProvider": ("provider", "ManagedProvider"),
    "ProbeContextResult": ("schemas", "ProbeContextResult"),
    "ProbeReport": ("schemas", "ProbeReport"),
    "Provider": ("provider", "Provider"),
    "ProviderRequest": ("schemas", "ProviderRequest"),
    "ProviderResponse": ("schemas", "ProviderResponse"),
    "RateLimitSnapshot": ("schemas", "RateLimitSnapshot"),
    "OutputSchemaSpec": ("structured", "OutputSchemaSpec"),
    "StructuredCallResult": ("validation_retry", "StructuredCallResult"),
    "adapter_conformance_test": ("provider", "adapter_conformance_test"),
    "assert_context_bundle_hash": ("cache", "assert_context_bundle_hash"),
    "build_validation_retry_feedback": (
        "validation_retry",
        "build_validation_retry_feedback",
    ),
    "build_cache_key": ("cache", "build_cache_key"),
    "build_context_bundle_hash": ("cache", "build_context_bundle_hash"),
    "clip_text_to_context_limit": ("cost", "clip_text_to_context_limit"),
    "effective_output_cap": ("cost", "effective_output_cap"),
    "enforce_token_budget": ("cost", "enforce_token_budget"),
    "estimate_cost_usd": ("cost", "estimate_cost_usd"),
    "estimate_request_tokens": ("cost", "estimate_request_tokens"),
    "make_provider": ("provider", "make_provider"),
    "parse_rate_limit_headers": ("cost", "parse_rate_limit_headers"),
    "persist_probe_result": ("probe", "persist_probe_result"),
    "probe_provider": ("probe", "probe_provider"),
    "canonical_json": ("structured", "canonical_json"),
    "normalize_schema_for_provider": ("structured", "normalize_schema_for_provider"),
    "resolve_context_window": ("cost", "resolve_context_window"),
    "resolve_model_limits": ("cost", "resolve_model_limits"),
    "schema_hash": ("structured", "schema_hash"),
    "schema_spec_for": ("structured", "schema_spec_for"),
    "generate_with_validation_retry": (
        "validation_retry",
        "generate_with_validation_retry",
    ),
}

_LAZY_SUBMODULES = {
    "cache",
    "cost",
    "probe",
    "provider",
    "schemas",
    "structured",
    "usage",
    "validation_retry",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(f"{__name__}.{module_name}"), attr_name)
        globals()[name] = value
        return value
    if name in _LAZY_SUBMODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | _LAZY_SUBMODULES)
