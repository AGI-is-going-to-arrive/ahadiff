from __future__ import annotations

from ahadiff.core.errors import ProviderError

_ANTHROPIC_BUDGETS: dict[str, int] = {
    "low": 1024,
    "medium": 4096,
    "high": 8192,
}

_GEMINI_LEVELS: dict[str, str] = {
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
}


def normalize_thinking_level(level: str | None) -> str:
    return level if level else "none"


def reject_unsupported_thinking(provider_class: str, level: str | None) -> None:
    if normalize_thinking_level(level) != "none":
        raise ProviderError(f"{provider_class} does not support thinking_level={level!r}")


def anthropic_budget_tokens(level: str | None) -> int | None:
    effective = normalize_thinking_level(level)
    return _ANTHROPIC_BUDGETS.get(effective)


def gemini_thinking_level(level: str | None) -> str | None:
    effective = normalize_thinking_level(level)
    return _GEMINI_LEVELS.get(effective)
