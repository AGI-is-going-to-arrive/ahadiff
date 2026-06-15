from __future__ import annotations

from urllib.parse import urlparse

_DEEPSEEK_API_HOST = "api.deepseek.com"


def is_deepseek_base_url(base_url: str) -> bool:
    try:
        host = (urlparse(base_url.strip()).hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    return host == _DEEPSEEK_API_HOST


def normalize_deepseek_model_name(model_name: str) -> str:
    normalized = model_name.strip().lower()
    if normalized.endswith(":free"):
        normalized = normalized.removesuffix(":free")
    if normalized.startswith("models/"):
        normalized = normalized.removeprefix("models/")
    if normalized.startswith("deepseek/"):
        normalized = normalized.removeprefix("deepseek/")
    return normalized


def is_deepseek_model_name(model_name: str) -> bool:
    normalized = normalize_deepseek_model_name(model_name)
    return normalized.startswith("deepseek-")


def is_deepseek_v4_thinking_model_name(model_name: str) -> bool:
    normalized = normalize_deepseek_model_name(model_name)
    return normalized.startswith("deepseek-v4-")


def is_deepseek_reasoning_model_name(model_name: str) -> bool:
    normalized = normalize_deepseek_model_name(model_name)
    return normalized == "deepseek-reasoner" or is_deepseek_v4_thinking_model_name(normalized)


def is_deepseek_provider_target(base_url: str, model_name: str) -> bool:
    return is_deepseek_base_url(base_url) or is_deepseek_model_name(model_name)


__all__ = [
    "is_deepseek_base_url",
    "is_deepseek_model_name",
    "is_deepseek_provider_target",
    "is_deepseek_reasoning_model_name",
    "is_deepseek_v4_thinking_model_name",
    "normalize_deepseek_model_name",
]
