from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

Locale = Literal["en", "zh-CN"]
LocalePreference = Literal["auto", "en", "zh-CN"]


@dataclass(frozen=True)
class _AcceptedLocale:
    order: int
    quality: float
    locale: Locale


def normalize_locale(value: str | None) -> Locale | None:
    if value is None:
        return None
    normalized = _normalize_token(value)
    if normalized == "en" or normalized.startswith("en-"):
        return "en"
    if normalized in {"zh", "zh-cn", "zh-hans"}:
        return "zh-CN"
    if normalized.startswith("zh-cn-") or normalized.startswith("zh-hans-"):
        return "zh-CN"
    return None


def normalize_locale_preference(value: str | None) -> LocalePreference | None:
    if value is None:
        return None
    normalized = _normalize_token(value)
    if normalized == "auto":
        return "auto"
    locale = normalize_locale(normalized)
    if locale is None:
        return None
    return locale


def locale_from_accept_language(value: str | None) -> Locale | None:
    if not value:
        return None
    accepted: list[_AcceptedLocale] = []
    for order, item in enumerate(value.split(",")):
        parts = [part.strip() for part in item.split(";")]
        locale = normalize_locale(parts[0])
        if locale is None:
            continue
        quality = _accept_quality(parts[1:])
        if quality <= 0:
            continue
        accepted.append(_AcceptedLocale(order=order, quality=quality, locale=locale))
    if accepted:
        selected = max(accepted, key=lambda item: (item.quality, -item.order))
        return selected.locale
    return None


def resolve_locale(
    *,
    cookie_lang: str | None = None,
    accept_language: str | None = None,
    cli_lang: str | None = None,
    config_lang: str | None = None,
    env: Mapping[str, str] | None = None,
    default: Locale = "en",
) -> Locale:
    cookie_locale = normalize_locale(cookie_lang)
    if cookie_locale is not None:
        return cookie_locale
    accepted_locale = locale_from_accept_language(accept_language)
    if accepted_locale is not None:
        return accepted_locale
    cli_locale = _explicit_preference_locale(cli_lang)
    if cli_locale is not None:
        return cli_locale
    config_locale = _explicit_preference_locale(config_lang)
    if config_locale is not None:
        return config_locale
    env_map = os.environ if env is None else env
    env_locale = normalize_locale(env_map.get("AHADIFF_LANG"))
    if env_locale is not None:
        return env_locale
    env_locale = normalize_locale(env_map.get("LANG"))
    return env_locale or default


def prompt_language_instruction(locale: str) -> str:
    normalized = normalize_locale(locale) or "en"
    if normalized == "zh-CN":
        return "Write all user-facing learning content in Simplified Chinese (zh-CN)."
    return "Write all user-facing learning content in English."


def _explicit_preference_locale(value: str | None) -> Locale | None:
    preference = normalize_locale_preference(value)
    if preference is None or preference == "auto":
        return None
    return preference


def _normalize_token(value: str) -> str:
    token = value.strip().replace("_", "-").casefold()
    if "." in token:
        token = token.split(".", 1)[0]
    return token


def _accept_quality(params: list[str]) -> float:
    for param in params:
        if not param.startswith("q="):
            continue
        try:
            return float(param[2:])
        except ValueError:
            return 0.0
    return 1.0


__all__ = [
    "Locale",
    "LocalePreference",
    "locale_from_accept_language",
    "normalize_locale",
    "normalize_locale_preference",
    "prompt_language_instruction",
    "resolve_locale",
]
