from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urlparse

import httpx

from ahadiff.core.errors import ProviderError

from .schemas import ProviderRequest, RateLimitSnapshot

if TYPE_CHECKING:
    from collections.abc import Callable

    from ahadiff.contracts import ProviderConfig, TokenizerEstimation


DEFAULT_INPUT_TOKEN_BUDGET = 200_000
DEFAULT_OUTPUT_TOKEN_BUDGET = 50_000
DEFAULT_CONTEXT_WINDOW = 128_000
DEFAULT_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_OPENROUTER_REFRESH_SECONDS = 3600
_MAX_RETRY_AFTER_SECONDS = 300.0
_DEV_CONTEXT_WINDOWS = {
    "gpt-5.4-mini": 1_000_000,
}


@dataclass(frozen=True)
class PricingEntry:
    input_per_million_usd: float
    output_per_million_usd: float
    pricing_version: str
    source_url: str
    request_per_call_usd: float | None = None


_OFFICIAL_PRICING_BOOK: dict[str, dict[str, PricingEntry]] = {
    "openai": {
        "gpt-5.4": PricingEntry(
            input_per_million_usd=2.50,
            output_per_million_usd=15.00,
            pricing_version="openai-api-pricing-2026-04-23",
            source_url="https://openai.com/api/pricing/",
        ),
        "gpt-5.4-mini": PricingEntry(
            input_per_million_usd=0.75,
            output_per_million_usd=4.50,
            pricing_version="openai-api-pricing-2026-04-23",
            source_url="https://openai.com/api/pricing/",
        ),
        "gpt-5.4-nano": PricingEntry(
            input_per_million_usd=0.20,
            output_per_million_usd=1.25,
            pricing_version="openai-api-pricing-2026-04-23",
            source_url="https://openai.com/api/pricing/",
        ),
    }
}
_OPENROUTER_PRICING_CACHE: dict[str, tuple[float, dict[str, PricingEntry]]] = {}
_OPENROUTER_PRICING_LOCK = threading.Lock()


@dataclass(frozen=True)
class TokenEstimate:
    input_tokens: int
    strategy: TokenizerEstimation
    clipped: bool = False


@dataclass(frozen=True)
class CostEstimate:
    cost_usd: float | None
    pricing_version: str | None
    cost_confidence: str


@dataclass(frozen=True)
class ResolvedModelLimits:
    max_context_tokens: int | None
    max_input_tokens: int
    max_output_tokens: int
    source: Literal["live", "registry", "default", "mixed"]
    input_source: str
    output_source: str
    warnings: tuple[str, ...] = ()


def estimate_request_tokens(
    request: ProviderRequest, strategy: TokenizerEstimation
) -> TokenEstimate:
    schema_overhead = _schema_overhead_text(request)
    payload = request.effective_payload()
    combined = payload if not schema_overhead else f"{payload}\n{schema_overhead}"
    return TokenEstimate(
        input_tokens=estimate_text_tokens(combined, strategy),
        strategy=strategy,
    )


def _schema_overhead_text(request: ProviderRequest) -> str:
    if request.output_schema is None or request.response_format != "json_schema":
        return ""
    return json.dumps(
        request.output_schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def estimate_text_tokens(
    text: str,
    strategy: TokenizerEstimation,
    *,
    safety_margin: float = 0.05,
) -> int:
    if not text:
        return 1
    raw_count: int
    if strategy == "tiktoken":
        raw_count = _estimate_with_tiktoken(text)
    elif strategy == "probe_cached":
        raw_count = math.ceil(len(text) / 4)
    else:
        raw_count = math.ceil(len(text) / 4)
    return max(1, math.ceil(raw_count * (1 + safety_margin)))


def clip_text_to_context_limit(
    text: str,
    *,
    max_tokens: int,
    strategy: TokenizerEstimation,
) -> str:
    estimated = estimate_text_tokens(text, strategy)
    if estimated <= max_tokens:
        return text
    marker = "\n...\n[TRUNCATED FOR CONTEXT WINDOW]\n...\n"
    keep_chars = max(64, int(len(text) * (max_tokens / max(estimated, 1))))
    clipped = text
    while keep_chars < len(text):
        head_chars = keep_chars // 2
        tail_chars = keep_chars - head_chars
        clipped = text[:head_chars] + marker + text[-tail_chars:]
        if estimate_text_tokens(clipped, strategy) <= max_tokens or keep_chars <= 64:
            return clipped
        keep_chars = max(64, int(keep_chars * 0.8))
    return clipped


def resolve_context_window(model_name: str, probed_max_context: int | None) -> int:
    if probed_max_context is not None and probed_max_context > 0:
        return probed_max_context
    return _DEV_CONTEXT_WINDOWS.get(model_name, DEFAULT_CONTEXT_WINDOW)


def resolve_model_limits(
    provider_class: str,
    model_name: str,
    config: ProviderConfig,
) -> ResolvedModelLimits:
    from .model_registry import lookup_model_limits

    registry = lookup_model_limits(
        provider_class,
        model_name,
        getattr(config, "model_limits_name", None),
    )
    registry_warnings = registry.warnings if registry is not None else ()
    legacy_context = _positive_int_or_none(getattr(config, "probed_max_context", None))

    output_value, output_source = _resolve_output_limit(config, registry)
    split_input_value, split_input_source = _resolve_split_input_limit(config, registry)
    if split_input_value is not None:
        input_value = split_input_value
        input_source = split_input_source
        output_for_context = output_value if output_source in {"live", "registry"} else 0
        split_context = input_value + output_for_context
        context_value = max(legacy_context or 0, split_context)
    else:
        context_value = legacy_context or resolve_context_window(model_name, None)
        output_for_context = output_value if output_source in {"live", "registry"} else 0
        input_value = max(context_value - output_for_context, 0)
        input_source = "total_derived"

    return ResolvedModelLimits(
        max_context_tokens=context_value,
        max_input_tokens=input_value,
        max_output_tokens=output_value,
        source=_combined_limit_source(input_source, output_source),
        input_source=input_source,
        output_source=output_source,
        warnings=registry_warnings,
    )


def _resolve_split_input_limit(
    config: ProviderConfig,
    registry: Any,
) -> tuple[int | None, str]:
    live_input = _positive_int_or_none(getattr(config, "probed_max_input_tokens", None))
    if live_input is not None:
        return live_input, "live"
    if registry is not None:
        registry_input = _positive_int_or_none(registry.max_input_tokens)
        if registry_input is not None:
            return registry_input, "registry"
    return None, "total_derived"


def _resolve_output_limit(config: ProviderConfig, registry: Any) -> tuple[int, str]:
    live_output = _positive_int_or_none(getattr(config, "probed_max_output_tokens", None))
    if live_output is not None:
        return live_output, "live"
    if registry is not None:
        registry_output = _positive_int_or_none(registry.max_output_tokens)
        if registry_output is not None:
            return registry_output, "registry"
    return DEFAULT_OUTPUT_TOKEN_BUDGET, "default"


def _positive_int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _combined_limit_source(
    input_source: str,
    output_source: str,
) -> Literal["live", "registry", "default", "mixed"]:
    source_map = {
        "legacy_context": "default",
        "total_derived": "default",
        "default": "default",
        "live": "live",
        "registry": "registry",
    }
    input_group = source_map.get(input_source, "default")
    output_group = source_map.get(output_source, "default")
    if input_group == output_group:
        return cast("Literal['live', 'registry', 'default', 'mixed']", input_group)
    return "mixed"


def enforce_token_budget(
    *,
    input_tokens: int,
    output_tokens: int | None,
    input_budget: int,
    output_budget: int,
) -> None:
    if input_tokens > input_budget:
        raise ProviderError(f"input token budget exceeded: {input_tokens} > {input_budget}")
    if output_tokens is not None and output_tokens > output_budget:
        raise ProviderError(f"output token budget exceeded: {output_tokens} > {output_budget}")


def parse_rate_limit_headers(headers: Mapping[str, str]) -> RateLimitSnapshot:
    return RateLimitSnapshot(
        rpm_limit=_parse_optional_int(headers.get("x-ratelimit-limit-requests")),
        rpm_remaining=_parse_optional_int(headers.get("x-ratelimit-remaining-requests")),
        tpm_limit=_parse_optional_int(headers.get("x-ratelimit-limit-tokens")),
        tpm_remaining=_parse_optional_int(headers.get("x-ratelimit-remaining-tokens")),
        retry_after_seconds=parse_retry_after(headers),
    )


def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    raw_value = headers.get("retry-after")
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
        if not math.isfinite(value) or value <= 0.0:
            return None
        return min(value, _MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw_value)
        except (TypeError, ValueError):
            return None
        delta = max(0.0, parsed.timestamp() - datetime.now(tz=parsed.tzinfo).timestamp())
        if not math.isfinite(delta):
            return None
        return min(delta, _MAX_RETRY_AFTER_SECONDS)


def estimate_cost_usd(
    *,
    provider_class: str | None = None,
    input_tokens: int,
    output_tokens: int,
    pricing_entry: PricingEntry | None = None,
    price_table: Mapping[str, tuple[float, float]] | None = None,
    model_id: str | None = None,
) -> CostEstimate:
    if not model_id:
        return CostEstimate(cost_usd=None, pricing_version=None, cost_confidence="low")
    entry = pricing_entry
    if entry is None and price_table is not None and model_id in price_table:
        input_rate, output_rate = price_table[model_id]
        entry = PricingEntry(
            input_per_million_usd=input_rate,
            output_per_million_usd=output_rate,
            pricing_version="manual",
            source_url="manual",
        )
    if entry is None:
        entry = _lookup_official_pricing_entry(provider_class=provider_class, model_id=model_id)
    if entry is None:
        return CostEstimate(cost_usd=None, pricing_version=None, cost_confidence="low")
    cost = (
        ((input_tokens / 1_000_000) * entry.input_per_million_usd)
        + ((output_tokens / 1_000_000) * entry.output_per_million_usd)
        + (entry.request_per_call_usd or 0.0)
    )
    return CostEstimate(
        cost_usd=round(cost, 8),
        pricing_version=entry.pricing_version,
        cost_confidence="high",
    )


def official_pricing_source_url(provider_class: str) -> str | None:
    entries = _OFFICIAL_PRICING_BOOK.get(provider_class)
    if not entries:
        return None
    return next(iter(entries.values())).source_url


def _lookup_official_pricing_entry(
    *,
    provider_class: str | None,
    model_id: str,
) -> PricingEntry | None:
    if provider_class is None:
        return None
    return _OFFICIAL_PRICING_BOOK.get(provider_class, {}).get(model_id)


def resolve_pricing_entry(
    *,
    provider_class: str | None,
    model_id: str,
    base_url: str | None = None,
    pricing_entry: PricingEntry | None = None,
    price_table: Mapping[str, tuple[float, float]] | None = None,
    openrouter_enabled: bool = True,
    openrouter_models_url: str = DEFAULT_OPENROUTER_MODELS_URL,
    openrouter_refresh_seconds: int = DEFAULT_OPENROUTER_REFRESH_SECONDS,
    openrouter_fetcher: Callable[[str, int], Mapping[str, PricingEntry]] | None = None,
) -> PricingEntry | None:
    if pricing_entry is not None:
        return pricing_entry
    if price_table is not None and model_id in price_table:
        input_rate, output_rate = price_table[model_id]
        return PricingEntry(
            input_per_million_usd=input_rate,
            output_per_million_usd=output_rate,
            pricing_version="manual",
            source_url="manual",
        )
    if openrouter_enabled and _is_openrouter_base_url(base_url):
        fetcher = openrouter_fetcher or fetch_openrouter_pricing_catalog
        try:
            catalog = fetcher(openrouter_models_url, openrouter_refresh_seconds)
        except (httpx.HTTPError, ProviderError, ValueError):
            catalog = {}
        entry = catalog.get(model_id)
        if entry is not None:
            return entry
    return _lookup_official_pricing_entry(provider_class=provider_class, model_id=model_id)


def fetch_openrouter_pricing_catalog(
    models_url: str = DEFAULT_OPENROUTER_MODELS_URL,
    refresh_seconds: int = DEFAULT_OPENROUTER_REFRESH_SECONDS,
    *,
    client: httpx.Client | None = None,
    now: Callable[[], float] = time.time,
) -> dict[str, PricingEntry]:
    _validate_openrouter_models_url(models_url)
    current_time = now()
    with _OPENROUTER_PRICING_LOCK:
        cached = _OPENROUTER_PRICING_CACHE.get(models_url)
        if cached is not None and current_time - cached[0] < refresh_seconds:
            return dict(cached[1])

    owns_client = client is None
    http_client = client or httpx.Client(timeout=5.0, trust_env=False)
    try:
        response = http_client.get(
            models_url,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        catalog = _parse_openrouter_pricing_catalog(response.json(), models_url=models_url)
    finally:
        if owns_client:
            http_client.close()

    with _OPENROUTER_PRICING_LOCK:
        _OPENROUTER_PRICING_CACHE[models_url] = (current_time, catalog)
    return dict(catalog)


def _validate_openrouter_models_url(models_url: str) -> None:
    parsed = urlparse(models_url)
    if parsed.scheme != "https":
        raise ProviderError("OpenRouter pricing URL must use https")
    if parsed.hostname != "openrouter.ai":
        raise ProviderError("OpenRouter pricing URL host must be openrouter.ai")


def reset_openrouter_pricing_cache() -> None:
    with _OPENROUTER_PRICING_LOCK:
        _OPENROUTER_PRICING_CACHE.clear()


def _parse_openrouter_pricing_catalog(
    payload: Any,
    *,
    models_url: str,
) -> dict[str, PricingEntry]:
    if not isinstance(payload, dict):
        raise ProviderError("OpenRouter pricing payload must be a JSON object")
    payload_mapping = cast("Mapping[str, Any]", payload)
    raw_models = cast("list[object] | None", payload_mapping.get("data"))
    if not isinstance(raw_models, list):
        raise ProviderError("OpenRouter pricing payload is missing a data array")

    catalog: dict[str, PricingEntry] = {}
    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            continue
        model_mapping = cast("Mapping[str, Any]", raw_model)
        model_id = cast("str | None", model_mapping.get("id"))
        pricing = cast("Mapping[str, Any] | None", model_mapping.get("pricing"))
        if not isinstance(model_id, str) or not isinstance(pricing, Mapping):
            continue
        input_rate = _parse_openrouter_pricing_component(
            pricing.get("prompt"),
            multiply_by_million=True,
        )
        output_rate = _parse_openrouter_pricing_component(
            pricing.get("completion"),
            multiply_by_million=True,
        )
        if input_rate is None or output_rate is None:
            continue
        catalog[model_id] = PricingEntry(
            input_per_million_usd=input_rate,
            output_per_million_usd=output_rate,
            request_per_call_usd=_parse_openrouter_pricing_component(
                pricing.get("request"),
                multiply_by_million=False,
            ),
            pricing_version="openrouter-models-api-live",
            source_url=models_url,
        )
    return catalog


def _parse_openrouter_pricing_component(
    raw_value: Any,
    *,
    multiply_by_million: bool,
) -> float | None:
    if raw_value is None or raw_value == "":
        return None
    if isinstance(raw_value, bool):
        return None
    try:
        amount = Decimal(str(raw_value))
    except InvalidOperation:
        return None
    if amount < 0:
        return None
    if multiply_by_million:
        amount *= Decimal(1_000_000)
    return float(amount)


def _is_openrouter_base_url(base_url: str | None) -> bool:
    if not base_url:
        return False
    hostname = urlparse(base_url).hostname
    if hostname is None:
        return False
    return hostname == "openrouter.ai" or hostname.endswith(".openrouter.ai")


def _estimate_with_tiktoken(text: str) -> int:
    try:
        import tiktoken  # pyright: ignore[reportMissingImports]
    except ImportError:
        return math.ceil(len(text) / 4)
    get_encoding = cast("Any", getattr(tiktoken, "get_encoding", None))
    if get_encoding is None:
        return math.ceil(len(text) / 4)
    encoding = get_encoding("cl100k_base")
    encode = cast("Any", getattr(encoding, "encode", None))
    if encode is None:
        return math.ceil(len(text) / 4)
    return len(cast("list[int]", encode(text)))


def _parse_optional_int(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


__all__ = [
    "CostEstimate",
    "DEFAULT_CONTEXT_WINDOW",
    "DEFAULT_INPUT_TOKEN_BUDGET",
    "DEFAULT_OPENROUTER_MODELS_URL",
    "DEFAULT_OPENROUTER_REFRESH_SECONDS",
    "DEFAULT_OUTPUT_TOKEN_BUDGET",
    "PricingEntry",
    "ResolvedModelLimits",
    "TokenEstimate",
    "clip_text_to_context_limit",
    "enforce_token_budget",
    "estimate_cost_usd",
    "estimate_request_tokens",
    "estimate_text_tokens",
    "fetch_openrouter_pricing_catalog",
    "official_pricing_source_url",
    "parse_rate_limit_headers",
    "parse_retry_after",
    "reset_openrouter_pricing_cache",
    "resolve_pricing_entry",
    "resolve_context_window",
    "resolve_model_limits",
]
