from __future__ import annotations

from ahadiff.contracts import ProviderCapabilities

from .openai import OpenAIChatAdapter


class OpenAICompatAdapter(OpenAIChatAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_stream=True,
            supports_json_mode=True,
            supports_tool_use=True,
            supports_temperature=True,
            supports_rate_limit_headers=True,
            supports_context_probe=True,
            tokenizer_estimation="tiktoken",
            api_family="openai",
            api_family_version="v1",
            provider_kind="openai_compat",
        )


__all__ = ["OpenAICompatAdapter"]
