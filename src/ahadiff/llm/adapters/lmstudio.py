from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..probe_limits import safe_positive_int
from ..schemas import ProbeContextResult
from ._capability_overrides import apply_capability_overrides
from .openai_compat import OpenAICompatAdapter

if TYPE_CHECKING:
    import httpx

    from ahadiff.contracts import ProviderCapabilities


class LMStudioAdapter(OpenAICompatAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return apply_capability_overrides(
            self._base_capabilities().model_copy(
                update={
                    "supports_native_json_schema": True,
                    "structured_output_notes": ("lm-studio-structured-output",),
                }
            ),
            self.config.capability_overrides,
        )

    def build_context_probe_request(
        self,
        *,
        api_key: str | None,
        model_name: str,
    ) -> tuple[str, str, dict[str, str]] | None:
        headers: dict[str, str] = {}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        base = self.config.base_url.rstrip("/")
        if base.endswith("/api/v1"):
            url = f"{base}/models"
        elif base.endswith("/v1"):
            url = f"{base[:-3]}/api/v1/models"
        else:
            url = f"{base}/api/v1/models"
        return "GET", url, headers

    def parse_context_probe(
        self,
        response: httpx.Response,
        *,
        model_name: str,
    ) -> ProbeContextResult | None:
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        payload_mapping = cast("dict[str, Any]", payload)
        items = payload_mapping.get("models")
        if not isinstance(items, list):
            items = payload_mapping.get("data")
        if not isinstance(items, list):
            return None
        item_values = cast("list[object]", items)
        for item in item_values:
            if not isinstance(item, dict):
                continue
            typed_item = cast("dict[str, Any]", item)
            if not self._model_matches(typed_item, model_name):
                continue
            context_length = self._loaded_context_length(typed_item)
            if context_length is None:
                context_length = safe_positive_int(typed_item.get("max_context_length"))
            if context_length is None:
                return None
            return ProbeContextResult(
                max_context_tokens=context_length,
                max_input_tokens=None,
                max_output_tokens=None,
                source="live",
            )
        return None

    @staticmethod
    def _model_matches(item: dict[str, Any], model_name: str) -> bool:
        candidates = (
            item.get("id"),
            item.get("name"),
            item.get("model"),
            item.get("path"),
        )
        return any(
            str(candidate) == model_name for candidate in candidates if candidate is not None
        )

    @classmethod
    def _loaded_context_length(cls, item: dict[str, Any]) -> int | None:
        loaded_instances = item.get("loaded_instances")
        if not isinstance(loaded_instances, list) or not loaded_instances:
            return None
        first = cast("object", loaded_instances[0])
        if not isinstance(first, dict):
            return None
        first_mapping = cast("dict[str, Any]", first)
        config = first_mapping.get("config")
        if not isinstance(config, dict):
            return None
        config_mapping = cast("dict[str, Any]", config)
        return safe_positive_int(config_mapping.get("context_length"))
