from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, cast

RegistryConfidence = Literal["registry"]
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelLimitEntry:
    max_input_tokens: int | None
    max_output_tokens: int | None
    source: str
    confidence: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RegistryEntry:
    provider: str
    model: str
    max_input_tokens: int | None
    max_output_tokens: int | None
    aliases: tuple[str, ...]
    confidence: RegistryConfidence


_FAMILY_SUFFIX_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{8}|latest|preview|turbo|mini)$")
_MODEL_RESOURCE = "model_registry.json"
_PROVIDER_PREFIXES: dict[str, tuple[str, ...]] = {
    "anthropic": ("anthropic", "claude"),
    "azure": ("azure",),
    "gemini": ("gemini", "google", "vertex_ai"),
    "lmstudio": ("lmstudio",),
    "newapi": ("newapi",),
    "ollama": ("ollama",),
    "openai": ("openai",),
    "openai_responses": ("openai", "openai_responses"),
}


def lookup_model_limits(
    provider_class: str,
    model_name: str,
    model_limits_name: str | None = None,
) -> ModelLimitEntry | None:
    """Return vendored model limits for a provider/model pair."""

    lookup_name = _normalize_model_name(model_limits_name or model_name)
    if not lookup_name:
        return None
    entries = _load_registry_entries()
    provider_names = _provider_candidates(provider_class)

    exact = _find_exact(entries, provider_names, lookup_name)
    if exact is not None:
        return _to_public(exact)

    stripped = _strip_provider_prefix(lookup_name, provider_names)
    if stripped != lookup_name:
        stripped_match = _find_exact(entries, provider_names, stripped)
        if stripped_match is not None:
            return _to_public(stripped_match)

    alias_match = _find_alias(entries, provider_names, lookup_name)
    if alias_match is not None:
        return _to_public(alias_match)
    if stripped != lookup_name:
        alias_match = _find_alias(entries, provider_names, stripped)
        if alias_match is not None:
            return _to_public(alias_match)

    family_match = _find_family(entries, provider_names, stripped)
    if family_match is None:
        return None
    return _to_public(
        family_match,
        warnings=(f"model limits matched version-family fallback: {family_match.model}",),
    )


def _find_exact(
    entries: tuple[_RegistryEntry, ...],
    providers: tuple[str, ...],
    model_name: str,
) -> _RegistryEntry | None:
    for entry in entries:
        if entry.provider in providers and _normalize_model_name(entry.model) == model_name:
            return entry
    return None


def _find_alias(
    entries: tuple[_RegistryEntry, ...],
    providers: tuple[str, ...],
    model_name: str,
) -> _RegistryEntry | None:
    for entry in entries:
        if entry.provider not in providers:
            continue
        if model_name in {_normalize_model_name(alias) for alias in entry.aliases}:
            return entry
    return None


def _find_family(
    entries: tuple[_RegistryEntry, ...],
    providers: tuple[str, ...],
    model_name: str,
) -> _RegistryEntry | None:
    candidates = sorted(
        (entry for entry in entries if entry.provider in providers),
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


def _to_public(
    entry: _RegistryEntry,
    *,
    warnings: tuple[str, ...] = (),
) -> ModelLimitEntry:
    return ModelLimitEntry(
        max_input_tokens=entry.max_input_tokens,
        max_output_tokens=entry.max_output_tokens,
        source="registry",
        confidence=entry.confidence,
        warnings=warnings,
    )


def _provider_candidates(provider_class: str) -> tuple[str, ...]:
    normalized = provider_class.strip().lower()
    aliases: dict[str, tuple[str, ...]] = {
        "openai_responses": ("openai_responses", "openai"),
        "azure": ("azure", "openai"),
        "newapi": ("newapi", "openai_compat"),
        "lmstudio": ("lmstudio", "openai_compat"),
    }
    return aliases.get(normalized, (normalized,))


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


def _strip_provider_prefix(model_name: str, provider_names: tuple[str, ...]) -> str:
    if "/" not in model_name:
        return model_name
    prefix, remainder = model_name.split("/", 1)
    normalized_prefix = prefix.strip().lower()
    provider_prefixes = {
        prefix
        for provider_name in provider_names
        for prefix in _PROVIDER_PREFIXES.get(provider_name, (provider_name,))
    }
    if normalized_prefix in provider_prefixes:
        return remainder.removeprefix("models/")
    return model_name


@lru_cache(maxsize=1)
def _load_registry_entries_cached() -> tuple[_RegistryEntry, ...]:
    raw_text = files("ahadiff.llm").joinpath(_MODEL_RESOURCE).read_text(encoding="utf-8")
    raw_payload: object = json.loads(raw_text)
    if not isinstance(raw_payload, dict):
        raise ValueError("model_registry.json must be a JSON object")
    payload = cast("dict[str, Any]", raw_payload)
    if payload.get("schema_version") != 1:
        raise ValueError("model_registry.json must use schema_version=1")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("model_registry.json entries must be a list")
    entries = cast("list[object]", raw_entries)
    return tuple(_parse_entry(item) for item in entries)


def _load_registry_entries() -> tuple[_RegistryEntry, ...]:
    try:
        return _load_registry_entries_cached()
    except (OSError, TypeError, ValueError) as exc:
        _load_registry_entries_cached.cache_clear()
        log.warning("failed to load model registry; using empty registry: %s", exc)
        return ()


cast("Any", _load_registry_entries).cache_clear = _load_registry_entries_cached.cache_clear
cast("Any", _load_registry_entries).cache_info = _load_registry_entries_cached.cache_info


def _parse_entry(item: object) -> _RegistryEntry:
    if not isinstance(item, dict):
        raise ValueError("model registry entry must be an object")
    entry = cast("dict[str, Any]", item)
    if entry.get("mode") != "chat":
        raise ValueError("model registry entry mode must be chat")
    aliases = entry.get("aliases", [])
    if not isinstance(aliases, list):
        raise ValueError("model registry entry aliases must be a list")
    alias_values = cast("list[object]", aliases)
    confidence = entry.get("confidence")
    if confidence != "registry":
        raise ValueError("model registry entry confidence must be registry")
    return _RegistryEntry(
        provider=_required_string(entry, "provider"),
        model=_required_string(entry, "model"),
        max_input_tokens=_optional_int(entry, "max_input_tokens"),
        max_output_tokens=_optional_int(entry, "max_output_tokens"),
        aliases=tuple(str(alias) for alias in alias_values if isinstance(alias, str) and alias),
        confidence=confidence,
    )


def _required_string(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"model registry entry {key} must be a non-empty string")
    return value.lower()


def _optional_int(entry: dict[str, Any], key: str) -> int | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"model registry entry {key} must be a positive int or null")
    return value


__all__ = ["ModelLimitEntry", "lookup_model_limits"]
