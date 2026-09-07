from __future__ import annotations

import re
from typing import TypedDict
from urllib.parse import urlsplit

from ahadiff.core.errors import ProviderError


class ThinkingPolicy(TypedDict):
    supported: bool
    accepted_levels: tuple[str, ...]
    payload_mode: str
    warnings: tuple[str, ...]


_EFFORT_LEVELS = ("low", "medium", "high")
_EXTENDED_LEVELS = (*_EFFORT_LEVELS, "xhigh", "max")
_BUDGETS = {"low": 1024, "medium": 4096, "high": 8192}
_CHAT_PROVIDERS = frozenset({"openai", "openai_compat", "newapi"})
_OPENAI_PROVIDERS = _CHAT_PROVIDERS | {"openai_responses", "azure"}
_NAMESPACES = frozenset(
    {
        "openai",
        "anthropic",
        "google",
        "x-ai",
        "deepseek",
        "z-ai",
        "moonshotai",
        "minimax",
        "qwen",
        "meta",
    }
)
_GLM_HOSTS = frozenset({"api.z.ai", "open.bigmodel.cn"})
_QWEN_HOSTS = frozenset(
    {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com"}
)
_MINIMAX_HOSTS = frozenset({"api.minimax.io", "api.minimax.chat", "api.minimaxi.com"})
_MOONSHOT_HOSTS = frozenset({"api.moonshot.ai", "api.moonshot.cn"})


def normalize_thinking_level(level: str | None) -> str | None:
    """An omitted level preserves the provider default; `none` explicitly disables it."""
    return level.strip().lower() or None if level is not None else None


def _model_id(model_name: str) -> str:
    name = model_name.strip().lower().removeprefix("models/")
    namespace, separator, identifier = name.partition("/")
    if separator and namespace in _NAMESPACES:
        name = identifier
    return re.sub(r"-\d{4}-\d{2}-\d{2}$", "", name)


def _host(base_url: str | None) -> str:
    try:
        return (urlsplit(base_url or "").hostname or "").rstrip(".").lower()
    except ValueError:
        return ""


def _policy(
    payload_mode: str = "unsupported",
    accepted_levels: tuple[str, ...] = (),
    *,
    warnings: tuple[str, ...] = (),
) -> ThinkingPolicy:
    return {
        "supported": bool(accepted_levels),
        "accepted_levels": accepted_levels,
        "payload_mode": payload_mode,
        "warnings": warnings,
    }


def _openai_levels(model: str) -> tuple[str, ...]:
    # https://developers.openai.com/api/docs/guides/reasoning
    # Keep explicit model families: future names must not inherit unverified controls.
    if model in {"gpt-5.6", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"}:
        return ("none", *_EXTENDED_LEVELS)
    if model == "gpt-6-astra":
        return _EXTENDED_LEVELS
    if model in {"gpt-5.2", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5"}:
        return ("none", *_EFFORT_LEVELS, "xhigh")
    if model == "gpt-5.1":
        return ("none", *_EFFORT_LEVELS)
    if model in {"gpt-5", "gpt-5-mini", "gpt-5-nano"}:
        return ("minimal", *_EFFORT_LEVELS)
    if model in {"o1", "o3", "o3-mini", "o4-mini"}:
        return _EFFORT_LEVELS
    if model == "gpt-5-pro":
        return ("high",)
    if model in {"gpt-5.2-pro", "gpt-5.4-pro", "gpt-5.5-pro"}:
        return ("medium", "high", "xhigh")
    return ()


def _anthropic_policy(model: str) -> ThinkingPolicy:
    # https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting
    # https://platform.claude.com/docs/en/build-with-claude/effort
    model = re.sub(r"-\d{8}$", "", model).replace(".", "-")
    if model in {"claude-fable-5", "claude-fable-5-1", "claude-mythos-5", "claude-mythos-5-1"}:
        return _policy(
            "thinking.adaptive+output_config.effort",
            _EXTENDED_LEVELS,
            warnings=("thinking_always_on",),
        )
    if model in {"claude-opus-5", "claude-sonnet-5", "claude-opus-4-7", "claude-opus-4-8"}:
        return _policy("thinking.adaptive+output_config.effort", ("none", *_EXTENDED_LEVELS))
    if model in {"claude-opus-4-6", "claude-sonnet-4-6"}:
        return _policy("thinking.adaptive+output_config.effort", ("none", *_EFFORT_LEVELS, "max"))
    if model == "claude-mythos-preview":
        return _policy(
            "thinking.adaptive+output_config.effort",
            (*_EFFORT_LEVELS, "max"),
            warnings=("thinking_always_on",),
        )
    if model.removesuffix("-latest") in {
        "claude-3-7-sonnet",
        "claude-sonnet-4",
        "claude-opus-4",
        "claude-opus-4-1",
        "claude-sonnet-4-5",
        "claude-opus-4-5",
        "claude-haiku-4-5",
    }:
        return _policy(
            "thinking.budget_tokens",
            ("none", *_EFFORT_LEVELS),
            warnings=("thinking_budget_mapping",),
        )
    return _policy()


def _gemini_policy(model: str) -> ThinkingPolicy:
    # https://ai.google.dev/gemini-api/docs/generate-content/thinking
    if re.fullmatch(r"gemini-2\.5-pro(?:-preview(?:-\d{2}-\d{2})?)?", model):
        return _policy(
            "thinkingConfig.thinkingBudget",
            _EFFORT_LEVELS,
            warnings=("thinking_always_on", "thinking_budget_mapping"),
        )
    if re.fullmatch(r"gemini-2\.5-flash(?:-lite)?(?:-preview(?:-\d{2}-\d{2})?)?", model):
        return _policy(
            "thinkingConfig.thinkingBudget",
            ("none", *_EFFORT_LEVELS),
            warnings=("thinking_budget_mapping",),
        )
    if re.fullmatch(r"gemini-(?:3\.1-pro|3\.[78]-flash)(?:-preview)?", model):
        return _policy(
            "thinkingConfig.thinkingLevel", _EFFORT_LEVELS, warnings=("thinking_always_on",)
        )
    if model in {"gemini-3-pro-preview", "gemini-3-pro"}:
        return _policy(
            "thinkingConfig.thinkingLevel", ("low", "high"), warnings=("thinking_always_on",)
        )
    if re.fullmatch(r"gemini-(?:3-flash|3\.[56]-flash|3\.[15]-flash-lite)(?:-preview)?", model):
        return _policy(
            "thinkingConfig.thinkingLevel",
            ("minimal", *_EFFORT_LEVELS),
            warnings=("thinking_minimal_not_off",),
        )
    if model in {"gemini-3.1-flash-lite-image", "gemini-3.1-flash-lite-image-preview"}:
        return _policy(
            "thinkingConfig.thinkingLevel",
            ("minimal", "high"),
            warnings=("thinking_minimal_not_off",),
        )
    return _policy()


def _native_chat_policy(provider: str, model: str, host: str) -> ThinkingPolicy | None:
    if host == "api.deepseek.com" and model in {
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-v4-flash-vision-exp",
        "deepseek-v4-flash-0731",
        "deepseek-v4-pro-0813",
    }:
        levels = ("none", "low", "high", "max")
        if provider in _CHAT_PROVIDERS:
            return _policy("deepseek.thinking", levels)
        if provider == "openai_responses":
            return _policy("reasoning.effort", levels)
        if provider == "anthropic":
            return _policy("thinking.enabled+output_config.effort", levels)
    if host in _MINIMAX_HOSTS and provider in _CHAT_PROVIDERS | {"anthropic"}:
        # MiniMax M3 defaults differ by protocol; omission must stay omission.
        if model == "minimax-m3":
            return _policy(
                "thinking.adaptive_toggle", ("none", "enabled"), warnings=("thinking_toggle_only",)
            )
        if model in {"minimax-m2", "minimax-m2.1", "minimax-m2.5", "minimax-m2.7"}:
            return _policy(warnings=("thinking_always_on",))
    if provider in _CHAT_PROVIDERS:
        if host in _GLM_HOSTS:
            if model in {"glm-5.3", "glm-5.3-flash"}:
                return _policy(
                    "thinking.enabled+reasoning_effort",
                    ("low", "high", "max"),
                    warnings=("thinking_always_on",),
                )
            if model == "glm-5.2":
                return _policy("thinking.enabled+reasoning_effort", ("none", "high", "max"))
            if model in {
                "glm-5",
                "glm-5.1",
                "glm-4.5",
                "glm-4.5-air",
                "glm-4.6",
                "glm-4.7",
                "glm-4.7-flash",
            }:
                return _policy(
                    "thinking.enabled_toggle",
                    ("none", "enabled"),
                    warnings=("thinking_toggle_only",),
                )
        if host in _MOONSHOT_HOSTS and model == "kimi-k3":
            return _policy(
                "reasoning_effort", ("low", "high", "max"), warnings=("thinking_always_on",)
            )
    if host in _QWEN_HOSTS and re.fullmatch(r"qwen3\.8-(?:max(?:-0902)?|flash-next|27b)", model):
        if provider in _CHAT_PROVIDERS:
            return _policy("enable_thinking+reasoning_effort", ("none", "low", "medium", "xhigh"))
        if provider == "openai_responses":
            return _policy(
                "enable_thinking", ("none", "enabled"), warnings=("thinking_toggle_only",)
            )
    return None


def _openrouter_policy(model_name: str) -> ThinkingPolicy:
    """OpenRouter has its own contract; native vendor effort names are not interchangeable.

    Verified 2026-09-07 against /api/v1/models reasoning metadata and
    https://openrouter.ai/docs/guides/best-practices/reasoning-tokens.
    """
    identifier = model_name.strip().lower()
    model = _model_id(identifier)
    levels: tuple[str, ...] = ()
    if identifier.startswith("openai/"):
        levels = _openai_levels(model)
    elif identifier.startswith("anthropic/"):
        policy = _anthropic_policy(model)
        if policy["payload_mode"] == "thinking.adaptive+output_config.effort":
            levels = policy["accepted_levels"]
        elif policy["payload_mode"] == "thinking.budget_tokens":
            return _policy(
                "openrouter.reasoning.max_tokens",
                policy["accepted_levels"],
                warnings=("thinking_budget_mapping",),
            )
    elif identifier.startswith("google/"):
        policy = _gemini_policy(model)
        if policy["payload_mode"] == "thinkingConfig.thinkingBudget":
            return _policy(
                "openrouter.reasoning.max_tokens",
                policy["accepted_levels"],
                warnings=policy["warnings"],
            )
        if policy["payload_mode"] == "thinkingConfig.thinkingLevel":
            return _policy(
                "openrouter.reasoning.effort",
                policy["accepted_levels"],
                warnings=policy["warnings"],
            )
    elif identifier in {"deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-pro", "z-ai/glm-5.2"}:
        levels = ("none", "high", "xhigh")
    elif identifier in {
        "deepseek/deepseek-v4-flash-0731",
        "deepseek/deepseek-v4-pro-0813",
        "deepseek/deepseek-v4-flash-vision-exp",
    }:
        levels = ("none", "low", "high", "max")
    elif identifier in {"z-ai/glm-5.3", "z-ai/glm-5.3-flash", "moonshotai/kimi-k3"}:
        levels = ("low", "high", "max")
    elif identifier in {"x-ai/grok-4.6", "x-ai/grok-4.5", "x-ai/grok-4.3"}:
        levels = {
            "grok-4.6": (*_EFFORT_LEVELS, "xhigh"),
            "grok-4.5": _EFFORT_LEVELS,
            "grok-4.3": ("none", *_EFFORT_LEVELS),
        }[model]
    elif identifier == "qwen/qwen3.8-max":
        levels = ("minimal", *_EFFORT_LEVELS, "xhigh")
    elif identifier == "qwen/qwen3.8-27b":
        levels = ("none", "low", "medium", "xhigh")
    elif identifier == "qwen/qwen3.8-2.4t-a95b":
        levels = ("low", "medium", "xhigh")
    elif identifier in {"minimax/minimax-m3", "qwen/qwen3.8-flash", "z-ai/glm-5", "z-ai/glm-5.1"}:
        return _policy(
            "openrouter.reasoning.enabled", ("none", "enabled"), warnings=("thinking_toggle_only",)
        )
    elif identifier in {
        "meta/muse-spark-1.1",
        "meta/muse-spark-1.2",
        "meta/muse-spark-1.2-contributor",
    }:
        levels = ("minimal", *_EFFORT_LEVELS, "xhigh")
    if not levels:
        return _policy()
    return _policy(
        "openrouter.reasoning.effort",
        levels,
        warnings=("thinking_always_on",) if "none" not in levels else (),
    )


def thinking_policy_for(
    provider_class: str,
    model_name: str,
    *,
    base_url: str | None = None,
    model_limits_name: str | None = None,
) -> ThinkingPolicy:
    provider = provider_class.strip().lower()
    model = _model_id(model_name)
    if _host(base_url) == "openrouter.ai" and provider in _CHAT_PROVIDERS:
        return _openrouter_policy(model_name)
    native = _native_chat_policy(provider, model, _host(base_url))
    if native is not None:
        return native
    if provider == "anthropic":
        return _anthropic_policy(model)
    if provider == "gemini":
        return _gemini_policy(model)
    if provider == "ollama":
        family = model.split(":", 1)[0]
        if family in {"gpt-oss", "gpt-oss-20b", "gpt-oss-120b"}:
            return _policy("think:string", _EFFORT_LEVELS, warnings=("thinking_always_on",))
        if family in {"qwen3", "deepseek-r1", "deepseek-v3.1"}:
            return _policy("think:boolean", ("none", "enabled"), warnings=("thinking_toggle_only",))
        return _policy()
    if provider in _OPENAI_PROVIDERS:
        profile_warning: tuple[str, ...] = ()
        if provider == "azure" and model_limits_name:
            model = _model_id(model_limits_name)
            profile_warning = ("azure_thinking_uses_model_profile",)
        levels = _openai_levels(model)
        if levels:
            mode = "reasoning.effort" if provider == "openai_responses" else "reasoning_effort"
            warnings = profile_warning
            if "none" not in levels:
                warnings += ("thinking_always_on",)
            if provider in {"openai_compat", "newapi"}:
                warnings += ("compatible_endpoint_thinking_unverified",)
            return _policy(mode, levels, warnings=warnings)
        if provider in _CHAT_PROVIDERS | {"openai_responses"}:
            if model in {"muse-spark-1.3", "muse-spark-1.3-contributor"}:
                levels = ("minimal", *_EFFORT_LEVELS, "xhigh")
                if model == "muse-spark-1.3":
                    levels += ("max",)
                mode = "reasoning.effort" if provider == "openai_responses" else "reasoning_effort"
                return _policy(mode, levels, warnings=("thinking_always_on",))
            if model == "grok-4.3":
                mode = "reasoning.effort" if provider == "openai_responses" else "reasoning_effort"
                return _policy(mode, ("none", *_EFFORT_LEVELS))
        if provider == "openai_responses":
            if model == "grok-4.6":
                return _policy(
                    "reasoning.effort", (*_EFFORT_LEVELS, "xhigh"), warnings=("thinking_always_on",)
                )
            if model == "grok-4.5":
                return _policy("reasoning.effort", _EFFORT_LEVELS, warnings=("thinking_always_on",))
            if model in {"grok-4.20-multi-agent", "grok-4.20-multi-agent-0309"}:
                return _policy(
                    "reasoning.effort",
                    (*_EFFORT_LEVELS, "xhigh"),
                    warnings=("thinking_controls_agent_count",),
                )
    return _policy()


def reject_unsupported_thinking(
    provider_class: str,
    level: str | None,
    *,
    model_name: str = "",
    base_url: str | None = None,
    model_limits_name: str | None = None,
) -> None:
    effective = normalize_thinking_level(level)
    if effective is None:
        return
    policy = thinking_policy_for(
        provider_class, model_name, base_url=base_url, model_limits_name=model_limits_name
    )
    if effective not in policy["accepted_levels"]:
        allowed = ", ".join(policy["accepted_levels"]) or "provider default only"
        raise ProviderError(
            f"{provider_class} model {model_name!r} does not support thinking_level={level!r}; "
            f"allowed: {allowed}"
        )


def thinking_payload_for(
    provider_class: str,
    model_name: str,
    level: str | None,
    *,
    base_url: str | None = None,
    model_limits_name: str | None = None,
) -> dict[str, object]:
    reject_unsupported_thinking(
        provider_class,
        level,
        model_name=model_name,
        base_url=base_url,
        model_limits_name=model_limits_name,
    )
    effective = normalize_thinking_level(level)
    if effective is None:
        return {}
    mode = thinking_policy_for(
        provider_class, model_name, base_url=base_url, model_limits_name=model_limits_name
    )["payload_mode"]
    if mode == "reasoning.effort":
        return {"reasoning": {"effort": effective}}
    if mode == "reasoning_effort":
        return {"reasoning_effort": effective}
    if mode == "openrouter.reasoning.effort":
        return {"reasoning": {"effort": effective}}
    if mode == "openrouter.reasoning.enabled":
        return {"reasoning": {"enabled": effective == "enabled"}}
    if mode == "openrouter.reasoning.max_tokens":
        if effective == "none":
            return {"reasoning": {"enabled": False}}
        return {"reasoning": {"max_tokens": _BUDGETS[effective]}}
    if mode == "thinking.adaptive+output_config.effort":
        if effective == "none":
            return {"thinking": {"type": "disabled"}}
        return {"thinking": {"type": "adaptive"}, "output_config": {"effort": effective}}
    if mode == "thinking.budget_tokens":
        thinking: dict[str, object] = {"type": "disabled"}
        if effective != "none":
            thinking = {"type": "enabled", "budget_tokens": _BUDGETS[effective]}
        return {"thinking": thinking}
    if mode in {
        "deepseek.thinking",
        "thinking.enabled+reasoning_effort",
        "thinking.enabled+output_config.effort",
    }:
        if effective == "none":
            return {"thinking": {"type": "disabled"}}
        effort_key = (
            "output_config" if mode.endswith("output_config.effort") else "reasoning_effort"
        )
        return {
            "thinking": {"type": "enabled"},
            effort_key: {"effort": effective} if effort_key == "output_config" else effective,
        }
    if mode in {"thinking.adaptive_toggle", "thinking.enabled_toggle"}:
        enabled_type = "adaptive" if mode == "thinking.adaptive_toggle" else "enabled"
        return {"thinking": {"type": "disabled" if effective == "none" else enabled_type}}
    if mode in {"enable_thinking", "enable_thinking+reasoning_effort"}:
        payload: dict[str, object] = {"enable_thinking": effective != "none"}
        if effective != "none" and mode.endswith("reasoning_effort"):
            payload["reasoning_effort"] = effective
        return payload
    if mode == "thinkingConfig.thinkingBudget":
        return {
            "thinkingConfig": {"thinkingBudget": 0 if effective == "none" else _BUDGETS[effective]}
        }
    if mode == "thinkingConfig.thinkingLevel":
        return {"thinkingConfig": {"thinkingLevel": effective}}
    if mode == "think:string":
        return {"think": effective}
    if mode == "think:boolean":
        return {"think": effective == "enabled"}
    raise ProviderError(f"unsupported thinking payload mode: {mode}")


def uses_openai_completion_tokens(model_name: str) -> bool:
    return bool(_openai_levels(_model_id(model_name)))


def chat_completion_token_key(provider_class: str, model_name: str, base_url: str) -> str:
    if uses_openai_completion_tokens(model_name):
        return "max_completion_tokens"
    policy = thinking_policy_for(provider_class, model_name, base_url=base_url)
    if policy["payload_mode"] == "enable_thinking+reasoning_effort" or (
        _host(base_url) in _MINIMAX_HOSTS and _model_id(model_name) == "minimax-m3"
    ):
        return "max_completion_tokens"
    return "max_tokens"


def minimum_thinking_output_tokens(
    provider_class: str, model_name: str, level: str | None, *, base_url: str | None = None
) -> int | None:
    effective = normalize_thinking_level(level)
    policy = thinking_policy_for(provider_class, model_name, base_url=base_url)
    if effective in _BUDGETS and policy["payload_mode"] in {
        "thinking.budget_tokens",
        "openrouter.reasoning.max_tokens",
        "thinkingConfig.thinkingBudget",
    }:
        return _BUDGETS[effective] + 1
    return None


def supports_request_temperature(
    provider_class: str,
    model_name: str,
    level: str | None,
    *,
    base_url: str | None = None,
    model_limits_name: str | None = None,
) -> bool:
    provider = provider_class.strip().lower()
    model = _model_id(
        model_limits_name if provider == "azure" and model_limits_name else model_name
    )
    effective = normalize_thinking_level(level)
    if provider in _OPENAI_PROVIDERS and _openai_levels(model):
        # Sampling is documented with thinking disabled for older GPT-5.1 through 5.5.
        # Newer families have no verified support, so do not send this optional control.
        return model != "gpt-6-astra" and not model.startswith("gpt-5.6") and effective == "none"
    if provider in _CHAT_PROVIDERS and _host(base_url) in _MOONSHOT_HOSTS and model == "kimi-k3":
        return False
    if _host(base_url) == "api.deepseek.com" and model.startswith("deepseek-v4-"):
        return effective == "none"
    if provider == "anthropic":
        policy = thinking_policy_for(provider, model_name, base_url=base_url)
        if policy["payload_mode"].startswith("thinking.adaptive"):
            return False
        if policy["payload_mode"] == "thinking.budget_tokens":
            return effective in {None, "none"}
    return True
