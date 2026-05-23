from __future__ import annotations

import re
from typing import Any

from ahadiff.core.errors import ProviderError

_ACCEPTED_THINKING_LEVELS = ("low", "medium", "high")
_ANTHROPIC_BUDGETS: dict[str, int] = {
    "low": 1024,
    "medium": 4096,
    "high": 8192,
}

_GEMINI_LEVELS: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
}
_ANTHROPIC_OPUS_VERSION_RE = re.compile(r"(?:^|/)claude-opus-(\d+)(?:[-.](\d+))?")


def normalize_thinking_level(level: str | None) -> str:
    return level.strip().lower() if level else "none"


def thinking_policy_for(provider_class: str, model_name: str) -> dict[str, object]:
    provider = provider_class.strip().lower()
    if provider == "anthropic":
        if _is_anthropic_adaptive_effort_model(model_name):
            return _policy(
                True,
                "thinking.effort",
                warnings=("anthropic_adaptive_thinking_effort_only",),
            )
        return _policy(True, "thinking.budget_tokens")
    if provider == "azure":
        return _policy(True, "reasoning_effort+max_completion_tokens")
    if provider == "openai_responses":
        return _policy(True, "reasoning.effort")
    if provider == "gemini":
        return _policy(True, "thinkingConfig.thinkingLevel")
    if provider == "ollama":
        return _policy(
            True,
            "think:string" if _is_ollama_gpt_oss_model(model_name) else "think:boolean",
            warnings=()
            if _is_ollama_gpt_oss_model(model_name)
            else ("ollama_thinking_unverified",),
        )
    return _policy(False, "unsupported", accepted_levels=())


def _policy(
    supported: bool,
    payload_mode: str,
    *,
    accepted_levels: tuple[str, ...] = _ACCEPTED_THINKING_LEVELS,
    warnings: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "supported": supported,
        "accepted_levels": accepted_levels if supported else (),
        "payload_mode": payload_mode,
        "warnings": warnings,
    }


def reject_unsupported_thinking(provider_class: str, level: str | None) -> None:
    if normalize_thinking_level(level) != "none":
        raise ProviderError(f"{provider_class} does not support thinking_level={level!r}")


def anthropic_budget_tokens(level: str | None) -> int | None:
    effective = normalize_thinking_level(level)
    return _ANTHROPIC_BUDGETS.get(effective)


def anthropic_thinking_config(level: str | None, model_name: str) -> dict[str, Any] | None:
    effective = normalize_thinking_level(level)
    if effective == "none":
        return None
    policy = thinking_policy_for("anthropic", model_name)
    if policy["payload_mode"] == "thinking.effort":
        return {"type": "enabled", "effort": effective}
    budget = anthropic_budget_tokens(effective)
    if budget is None:
        return None
    return {"type": "enabled", "budget_tokens": budget}


def gemini_thinking_level(level: str | None) -> str | None:
    effective = normalize_thinking_level(level)
    return _GEMINI_LEVELS.get(effective)


def ollama_think_value(level: str | None, model_name: str) -> bool | str:
    effective = normalize_thinking_level(level)
    if effective == "none":
        return False
    policy = thinking_policy_for("ollama", model_name)
    if policy["payload_mode"] == "think:string":
        return effective
    return True


def _is_ollama_gpt_oss_model(model_name: str) -> bool:
    return "gpt-oss" in model_name.strip().lower()


def _is_anthropic_adaptive_effort_model(model_name: str) -> bool:
    normalized = model_name.strip().lower()
    match = _ANTHROPIC_OPUS_VERSION_RE.search(normalized)
    if match is None:
        return False
    major = int(match.group(1))
    minor = int(match.group(2) or "0")
    return (major, minor) >= (4, 7)
