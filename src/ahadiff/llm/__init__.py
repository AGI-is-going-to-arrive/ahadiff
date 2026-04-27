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
        enforce_token_budget,
        estimate_cost_usd,
        estimate_request_tokens,
        parse_rate_limit_headers,
        resolve_context_window,
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
        ProbeReport,
        ProviderRequest,
        ProviderResponse,
        RateLimitSnapshot,
    )

__all__ = [
    "AdapterBase",
    "CacheKeyInput",
    "DEFAULT_CONTEXT_WINDOW",
    "DEFAULT_INPUT_TOKEN_BUDGET",
    "DEFAULT_OUTPUT_TOKEN_BUDGET",
    "DEFAULT_PROVIDER_RESPONSE_BYTE_CAP",
    "ManagedProvider",
    "ProbeReport",
    "Provider",
    "ProviderRequest",
    "ProviderResponse",
    "RateLimitSnapshot",
    "adapter_conformance_test",
    "assert_context_bundle_hash",
    "build_cache_key",
    "build_context_bundle_hash",
    "clip_text_to_context_limit",
    "enforce_token_budget",
    "estimate_cost_usd",
    "estimate_request_tokens",
    "make_provider",
    "parse_rate_limit_headers",
    "persist_probe_result",
    "probe_provider",
    "resolve_context_window",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AdapterBase": ("provider", "AdapterBase"),
    "CacheKeyInput": ("schemas", "CacheKeyInput"),
    "DEFAULT_CONTEXT_WINDOW": ("cost", "DEFAULT_CONTEXT_WINDOW"),
    "DEFAULT_INPUT_TOKEN_BUDGET": ("cost", "DEFAULT_INPUT_TOKEN_BUDGET"),
    "DEFAULT_OUTPUT_TOKEN_BUDGET": ("cost", "DEFAULT_OUTPUT_TOKEN_BUDGET"),
    "DEFAULT_PROVIDER_RESPONSE_BYTE_CAP": ("provider", "DEFAULT_PROVIDER_RESPONSE_BYTE_CAP"),
    "ManagedProvider": ("provider", "ManagedProvider"),
    "ProbeReport": ("schemas", "ProbeReport"),
    "Provider": ("provider", "Provider"),
    "ProviderRequest": ("schemas", "ProviderRequest"),
    "ProviderResponse": ("schemas", "ProviderResponse"),
    "RateLimitSnapshot": ("schemas", "RateLimitSnapshot"),
    "adapter_conformance_test": ("provider", "adapter_conformance_test"),
    "assert_context_bundle_hash": ("cache", "assert_context_bundle_hash"),
    "build_cache_key": ("cache", "build_cache_key"),
    "build_context_bundle_hash": ("cache", "build_context_bundle_hash"),
    "clip_text_to_context_limit": ("cost", "clip_text_to_context_limit"),
    "enforce_token_budget": ("cost", "enforce_token_budget"),
    "estimate_cost_usd": ("cost", "estimate_cost_usd"),
    "estimate_request_tokens": ("cost", "estimate_request_tokens"),
    "make_provider": ("provider", "make_provider"),
    "parse_rate_limit_headers": ("cost", "parse_rate_limit_headers"),
    "persist_probe_result": ("probe", "persist_probe_result"),
    "probe_provider": ("probe", "probe_provider"),
    "resolve_context_window": ("cost", "resolve_context_window"),
}

_LAZY_SUBMODULES = {
    "cache",
    "cost",
    "probe",
    "provider",
    "schemas",
    "usage",
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
