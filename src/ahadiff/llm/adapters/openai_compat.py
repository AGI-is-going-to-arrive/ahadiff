from __future__ import annotations

from ahadiff.contracts import ProviderCapabilities

from ._capability_overrides import apply_capability_overrides
from .openai import OpenAIChatAdapter


class OpenAICompatAdapter(OpenAIChatAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return apply_capability_overrides(
            self._base_capabilities(),
            self.config.capability_overrides,
        )

    def _base_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_stream=True,
            supports_json_mode=True,
            supports_json_object_mode=True,
            supports_native_json_schema=False,
            supports_schema_name=True,
            supports_schema_strict_flag=True,
            structured_output_notes=("backend-dependent",),
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
