from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ahadiff.contracts import ProviderCapabilities

from ..probe_limits import safe_positive_int
from ..provider import AdapterBase
from ..schemas import ProbeContextResult, ProviderRequest, ProviderResponse
from ._capability_overrides import apply_capability_overrides
from .structured import openai_json_schema_format
from .thinking import reject_unsupported_thinking

if TYPE_CHECKING:
    import httpx

_CONTEXT_PROBE_TOTAL_FIELDS = (
    "max_context_tokens",
    "context_window",
    "max_context_length",
    "max_tokens",
)
_CONTEXT_PROBE_INPUT_FIELDS = ("max_input_tokens",)
_CONTEXT_PROBE_OUTPUT_FIELDS = ("max_output_tokens",)


def _context_probe_metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    return cast("dict[str, Any]", metadata)


def _first_positive_probe_limit(
    mappings: tuple[dict[str, Any], ...],
    field_names: tuple[str, ...],
) -> int | None:
    for mapping in mappings:
        for field_name in field_names:
            value = safe_positive_int(mapping.get(field_name))
            if value is not None:
                return value
    return None


class OpenAIChatAdapter(AdapterBase):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return apply_capability_overrides(
            ProviderCapabilities(
                supports_stream=True,
                supports_json_mode=True,
                supports_json_object_mode=True,
                supports_native_json_schema=True,
                supports_schema_name=True,
                supports_schema_strict_flag=True,
                supports_tool_use=True,
                supports_temperature=True,
                supports_rate_limit_headers=True,
                supports_context_probe=True,
                tokenizer_estimation="tiktoken",
                api_family="openai",
                api_family_version="v1",
                provider_kind="openai_chat",
            ),
            self.config.capability_overrides,
        )

    def build_request(
        self,
        request: ProviderRequest,
        *,
        api_key: str | None,
    ) -> tuple[str, str, dict[str, str], dict[str, Any]]:
        reject_unsupported_thinking(self.config.provider_class, request.thinking_level)
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.effective_payload()}],
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        native_format = openai_json_schema_format(request, capabilities=self.capabilities)
        if native_format is not None:
            payload["response_format"] = native_format
        elif request.response_format in {"json", "json_schema"} and (
            self.capabilities.supports_json_object_mode
        ):
            payload["response_format"] = {"type": "json_object"}
        base = self.config.base_url.rstrip("/")
        prefix = base if base.endswith("/v1") else f"{base}/v1"
        url = f"{prefix}/chat/completions"
        return "POST", url, headers, payload

    def parse_response(self, response: httpx.Response) -> ProviderResponse:
        payload = response.json()
        choice = payload["choices"][0]
        message = choice.get("message", {})
        usage = payload.get("usage", {})
        content = str(message.get("content") or "")
        if not content:
            content = str(message.get("reasoning_content") or "")
        return ProviderResponse(
            content=content,
            model_id=str(payload.get("model", self.config.model_name)),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            finish_reason=choice.get("finish_reason"),
            request_id=response.headers.get("x-request-id"),
            raw_json=payload,
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
        prefix = base if base.endswith("/v1") else f"{base}/v1"
        return "GET", f"{prefix}/models", headers

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
            metadata = _context_probe_metadata(typed_item)
            probe_sources = (metadata, typed_item)
            max_context_tokens = _first_positive_probe_limit(
                probe_sources,
                _CONTEXT_PROBE_TOTAL_FIELDS,
            )
            max_input_tokens = _first_positive_probe_limit(
                probe_sources,
                _CONTEXT_PROBE_INPUT_FIELDS,
            )
            max_output_tokens = _first_positive_probe_limit(
                probe_sources,
                _CONTEXT_PROBE_OUTPUT_FIELDS,
            )
            if (
                max_context_tokens is None
                and max_input_tokens is None
                and max_output_tokens is None
            ):
                continue
            return ProbeContextResult(
                max_context_tokens=max_context_tokens,
                max_input_tokens=max_input_tokens,
                max_output_tokens=max_output_tokens,
                source="live",
            )
        return None
