from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ahadiff.contracts import ProviderCapabilities

from ..probe_limits import safe_positive_int
from ..schemas import ProbeContextResult
from ._capability_overrides import apply_capability_overrides
from .openai import OpenAIChatAdapter

if TYPE_CHECKING:
    import httpx

_CONTEXT_PROBE_FIELDS = ("max_model_len", "context_window", "max_context_length", "max_tokens")


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

    def parse_context_probe(
        self, response: httpx.Response, *, model_name: str
    ) -> ProbeContextResult | None:
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        payload_mapping = cast("dict[str, Any]", payload)
        data = payload_mapping.get("data")
        if not isinstance(data, list):
            return None
        data_items = cast("list[object]", data)
        for item in data_items:
            if not isinstance(item, dict):
                continue
            typed_item = cast("dict[str, Any]", item)
            if typed_item.get("id") != model_name:
                continue
            for field_name in _CONTEXT_PROBE_FIELDS:
                value = safe_positive_int(typed_item.get(field_name))
                if value is None:
                    continue
                return ProbeContextResult(
                    max_context_tokens=value,
                    max_input_tokens=None,
                    max_output_tokens=None,
                    source="live",
                )
        return None


__all__ = ["OpenAICompatAdapter"]
