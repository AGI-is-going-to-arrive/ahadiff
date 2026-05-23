from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, cast

ContextPolicy = Literal["shared_pool", "split_envelope", "route_specific", "local_runtime"]
RegistryConfidence = Literal["high", "medium", "low"]
log = logging.getLogger(__name__)
_BUNDLED_FILES = files


@dataclass(frozen=True)
class ModelLimitEntry:
    max_context_tokens: int | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    context_policy: ContextPolicy
    source: str
    confidence: RegistryConfidence
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RegistryEntry:
    provider: str
    model: str
    max_context_tokens: int | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    context_policy: ContextPolicy
    source: str
    aliases: tuple[str, ...]
    confidence: RegistryConfidence
    warnings: tuple[str, ...]


_FAMILY_SUFFIX_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{8}|latest|preview|turbo)$")
_MODEL_RESOURCE = "model_registry.json"
_PROVIDER_PREFIXES: dict[str, tuple[str, ...]] = {
    "anthropic": ("anthropic", "claude"),
    "azure": ("azure",),
    "gemini": ("gemini", "google", "vertex_ai"),
    "lmstudio": ("lmstudio",),
    "newapi": ("newapi",),
    "ollama": ("ollama",),
    "openrouter": ("openrouter",),
    "openai": ("openai",),
    "openai_responses": ("openai", "openai_responses"),
}
_CONTEXT_POLICIES: set[str] = {"shared_pool", "split_envelope", "route_specific", "local_runtime"}
_CONFIDENCE_VALUES: set[str] = {"high", "medium", "low"}


def lookup_model_limits(
    provider_class: str,
    model_name: str,
    model_limits_name: str | None = None,
) -> ModelLimitEntry | None:
    """Return vendored model limits for a provider/model pair."""

    if model_limits_name is not None and model_limits_name.strip():
        explicit_lookup = True
        raw_lookup_name = model_limits_name
    else:
        explicit_lookup = False
        raw_lookup_name = model_name
    lookup_name = _normalize_model_name(raw_lookup_name)
    if not lookup_name:
        return None
    entries = _load_registry_entries_for_lookup()
    provider_names = _provider_candidates(provider_class, explicit_lookup=explicit_lookup)
    if provider_class.strip().lower() == "lmstudio" and "openai_compat" in provider_names:
        primary_match = _lookup_model_limits_for_providers(
            entries,
            ("lmstudio",),
            lookup_name,
            explicit_lookup,
        )
        if primary_match is not None:
            return primary_match
        fallback_names = tuple(provider for provider in provider_names if provider != "lmstudio")
        return _lookup_model_limits_for_providers(
            entries,
            fallback_names,
            lookup_name,
            explicit_lookup,
        )

    return _lookup_model_limits_for_providers(
        entries,
        provider_names,
        lookup_name,
        explicit_lookup,
    )


def _lookup_model_limits_for_providers(
    entries: tuple[_RegistryEntry, ...],
    provider_names: tuple[str, ...],
    lookup_name: str,
    explicit_lookup: bool,
) -> ModelLimitEntry | None:
    if not provider_names:
        return None

    exact = _find_exact(entries, provider_names, lookup_name)
    if exact is not None:
        return _to_public(exact)

    provider_qualified = _provider_qualified_candidates(
        lookup_name, provider_names, explicit_lookup
    )
    if provider_qualified is not None:
        qualified_providers, qualified_name = provider_qualified
        qualified_exact = _find_exact(entries, qualified_providers, qualified_name)
        if qualified_exact is not None:
            return _to_public(qualified_exact)
        qualified_alias = _find_alias(entries, qualified_providers, qualified_name)
        if qualified_alias is not None:
            return _to_public(qualified_alias)

    alias_match = _find_alias(entries, provider_names, lookup_name)
    if alias_match is not None:
        return _to_public(alias_match)

    family_match = _find_family(entries, provider_names, lookup_name)
    if family_match is None and provider_qualified is not None:
        qualified_providers, qualified_name = provider_qualified
        family_match = _find_family(entries, qualified_providers, qualified_name)
    if family_match is None:
        wildcard_match = _find_wildcard(entries, provider_names)
        if wildcard_match is None and provider_qualified is not None:
            qualified_providers, _qualified_name = provider_qualified
            wildcard_match = _find_wildcard(entries, qualified_providers)
        if wildcard_match is None:
            return None
        return _to_public(wildcard_match)
    return _to_public(
        family_match,
        warnings=(f"model limits matched version-family fallback: {family_match.model}",),
    )


def _find_exact(
    entries: tuple[_RegistryEntry, ...],
    providers: tuple[str, ...],
    model_name: str,
) -> _RegistryEntry | None:
    for provider in providers:
        for entry in entries:
            if entry.provider == provider and _normalize_model_name(entry.model) == model_name:
                return entry
    return None


def _find_alias(
    entries: tuple[_RegistryEntry, ...],
    providers: tuple[str, ...],
    model_name: str,
) -> _RegistryEntry | None:
    for provider in providers:
        for entry in entries:
            if entry.provider != provider:
                continue
            if model_name in {_normalize_model_name(alias) for alias in entry.aliases}:
                return entry
    return None


def _find_family(
    entries: tuple[_RegistryEntry, ...],
    providers: tuple[str, ...],
    model_name: str,
) -> _RegistryEntry | None:
    for provider in providers:
        candidates = sorted(
            (entry for entry in entries if entry.provider == provider),
            key=lambda entry: len(entry.model),
            reverse=True,
        )
        for entry in candidates:
            normalized_entry = _normalize_model_name(entry.model)
            if _matches_family(model_name, normalized_entry):
                return entry
            for alias in entry.aliases:
                normalized_alias = _normalize_model_name(alias)
                if normalized_alias and _matches_family(model_name, normalized_alias):
                    return entry
    return None


def _find_wildcard(
    entries: tuple[_RegistryEntry, ...],
    providers: tuple[str, ...],
) -> _RegistryEntry | None:
    for provider in providers:
        for entry in entries:
            if entry.provider == provider and _normalize_model_name(entry.model) == "*":
                return entry
    return None


def _to_public(
    entry: _RegistryEntry,
    *,
    warnings: tuple[str, ...] = (),
) -> ModelLimitEntry:
    return ModelLimitEntry(
        max_context_tokens=entry.max_context_tokens,
        max_input_tokens=entry.max_input_tokens,
        max_output_tokens=entry.max_output_tokens,
        context_policy=entry.context_policy,
        source=entry.source,
        confidence=entry.confidence,
        warnings=entry.warnings + warnings,
    )


def _provider_candidates(
    provider_class: str,
    *,
    explicit_lookup: bool = False,
) -> tuple[str, ...]:
    normalized = provider_class.strip().lower()
    if normalized == "lmstudio" and not explicit_lookup:
        return ("lmstudio",)
    aliases: dict[str, tuple[str, ...]] = {
        "openai_responses": ("openai_responses", "openai"),
        "azure": ("azure", "openai"),
        "newapi": ("newapi", "openai_compat"),
        "lmstudio": ("lmstudio", "openai_compat"),
    }
    return aliases.get(normalized, (normalized,))


def _provider_qualified_candidates(
    model_name: str,
    provider_names: tuple[str, ...],
    explicit_lookup: bool,
) -> tuple[tuple[str, ...], str] | None:
    split_name = _split_provider_qualified_name(model_name)
    if split_name is None:
        return None
    qualifier, qualified_name = split_name
    qualified_providers = _provider_candidates_for_qualifier(qualifier)
    if not explicit_lookup and not (set(qualified_providers) & set(provider_names)):
        return None
    return qualified_providers, qualified_name


def _split_provider_qualified_name(model_name: str) -> tuple[str, str] | None:
    if "/" not in model_name:
        return None
    qualifier, remainder = model_name.split("/", 1)
    qualifier = qualifier.strip().lower()
    remainder = _normalize_model_name(remainder)
    if not qualifier or not remainder:
        return None
    return qualifier, remainder


def _provider_candidates_for_qualifier(provider_prefix: str) -> tuple[str, ...]:
    normalized = provider_prefix.strip().lower()
    matches = tuple(
        provider
        for provider, prefixes in _PROVIDER_PREFIXES.items()
        if normalized == provider or normalized in prefixes
    )
    if matches:
        return matches
    return (normalized,)


def _normalize_model_name(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("models/"):
        normalized = normalized.removeprefix("models/")
    return normalized


def _matches_family(model_name: str, family_name: str) -> bool:
    prefix = f"{family_name}-"
    if not model_name.startswith(prefix):
        return False
    return _FAMILY_SUFFIX_RE.fullmatch(model_name.removeprefix(prefix)) is not None


@lru_cache(maxsize=1)
def _load_registry_entries_cached() -> tuple[_RegistryEntry, ...]:
    raw_text = files("ahadiff.llm").joinpath(_MODEL_RESOURCE).read_text(encoding="utf-8")
    raw_payload: object = json.loads(raw_text)
    if not isinstance(raw_payload, dict):
        raise ValueError("model_registry.json must be a JSON object")
    payload = cast("dict[str, Any]", raw_payload)
    if payload.get("schema_version") != 2:
        raise ValueError("model_registry.json must use schema_version=2")
    raw_entries = payload.get("models")
    if not isinstance(raw_entries, list):
        raise ValueError("model_registry.json models must be a list")
    entries = cast("list[object]", raw_entries)
    return tuple(_parse_entry(item) for item in entries)


def _load_registry_entries() -> tuple[_RegistryEntry, ...]:
    try:
        return _load_registry_entries_cached()
    except json.JSONDecodeError as exc:
        if not _uses_external_registry_source():
            raise
        return _empty_external_registry_after_failed_load(exc)


def _load_registry_entries_for_lookup() -> tuple[_RegistryEntry, ...]:
    if _uses_external_registry_source():
        return _load_external_registry_entries()
    return _load_registry_entries()


def _uses_external_registry_source() -> bool:
    return files is not _BUNDLED_FILES


def _load_external_registry_entries() -> tuple[_RegistryEntry, ...]:
    try:
        return _load_registry_entries_cached()
    except (OSError, TypeError, ValueError) as exc:
        return _empty_external_registry_after_failed_load(exc)


def _empty_external_registry_after_failed_load(exc: Exception) -> tuple[_RegistryEntry, ...]:
    _load_registry_entries_cached.cache_clear()
    log.warning("failed to load model registry; using empty registry: %s", exc)
    return ()


cast("Any", _load_registry_entries).cache_clear = _load_registry_entries_cached.cache_clear
cast("Any", _load_registry_entries).cache_info = _load_registry_entries_cached.cache_info


def _parse_entry(item: object) -> _RegistryEntry:
    if not isinstance(item, dict):
        raise ValueError("model registry entry must be an object")
    entry = cast("dict[str, Any]", item)
    mode = entry.get("mode")
    if mode is not None and mode != "chat":
        raise ValueError("model registry entry mode must be chat")
    aliases = entry.get("aliases", [])
    if not isinstance(aliases, list):
        raise ValueError("model registry entry aliases must be a list")
    alias_values = cast("list[object]", aliases)
    context_policy = _required_context_policy(entry)
    max_context_tokens = _context_tokens(entry, context_policy)
    max_output_tokens = _optional_int(entry, "max_output_tokens")
    if (
        max_context_tokens is not None
        and max_output_tokens is not None
        and max_output_tokens > max_context_tokens
    ):
        raise ValueError(
            "model registry entry max_output_tokens must not exceed max_context_tokens"
        )
    return _RegistryEntry(
        provider=_required_string(entry, "provider"),
        model=_required_string(entry, "model"),
        max_context_tokens=max_context_tokens,
        max_input_tokens=_optional_int(entry, "max_input_tokens"),
        max_output_tokens=max_output_tokens,
        context_policy=context_policy,
        source=_required_source(entry),
        aliases=tuple(str(alias) for alias in alias_values if isinstance(alias, str) and alias),
        confidence=_required_confidence(entry),
        warnings=_optional_string_tuple(entry, "warnings"),
    )


def _required_string(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"model registry entry {key} must be a non-empty string")
    return value.strip().lower()


def _optional_int(entry: dict[str, Any], key: str) -> int | None:
    value = entry.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"model registry entry {key} must be a positive int or null")
    return value


def _context_tokens(entry: dict[str, Any], context_policy: ContextPolicy) -> int | None:
    value = entry.get("max_context_tokens")
    if value is None:
        if context_policy == "local_runtime":
            return None
        raise ValueError("model registry entry max_context_tokens must be a positive int")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("model registry entry max_context_tokens must be a positive int")
    return value


def _required_context_policy(entry: dict[str, Any]) -> ContextPolicy:
    value = entry.get("context_policy")
    if not isinstance(value, str) or value not in _CONTEXT_POLICIES:
        raise ValueError("model registry entry context_policy must be a supported value")
    return cast("ContextPolicy", value)


def _required_source(entry: dict[str, Any]) -> str:
    value = entry.get("source")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("model registry entry source must be a non-empty string")
    return value.strip()


def _required_confidence(entry: dict[str, Any]) -> RegistryConfidence:
    value = entry.get("confidence")
    if not isinstance(value, str) or value not in _CONFIDENCE_VALUES:
        raise ValueError("model registry entry confidence must be high, medium, or low")
    return cast("RegistryConfidence", value)


def _optional_string_tuple(entry: dict[str, Any], key: str) -> tuple[str, ...]:
    value = entry.get(key, [])
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"model registry entry {key} must be a list")
    values = cast("list[object]", value)
    return tuple(item for item in values if isinstance(item, str) and item)


__all__ = ["ModelLimitEntry", "lookup_model_limits"]
