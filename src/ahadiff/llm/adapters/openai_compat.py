from __future__ import annotations

from ahadiff.contracts import ProviderCapabilities

from .openai import OpenAIChatAdapter


class OpenAICompatAdapter(OpenAIChatAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._apply_capability_overrides(self._base_capabilities())

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

    def _apply_capability_overrides(
        self,
        capabilities: ProviderCapabilities,
    ) -> ProviderCapabilities:
        overrides = self.config.capability_overrides or {}
        if not overrides:
            return capabilities
        bool_fields = {
            key for key, value in capabilities.model_dump().items() if isinstance(value, bool)
        }
        updates = {key: value for key, value in overrides.items() if key in bool_fields}
        if not updates:
            return capabilities
        return capabilities.model_copy(update=updates)


__all__ = ["OpenAICompatAdapter"]
