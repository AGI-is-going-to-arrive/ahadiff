from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ahadiff.contracts import ProviderCapabilities

from ..probe_limits import safe_positive_int
from ..provider import AdapterBase
from ..schemas import ProbeContextResult, ProviderRequest, ProviderResponse
from ._capability_overrides import apply_capability_overrides
from .structured import responses_text_format
from .thinking import normalize_thinking_level

if TYPE_CHECKING:
    import httpx


class OpenAIResponsesAdapter(AdapterBase):
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
                provider_kind="openai_responses",
            ),
            self.config.capability_overrides,
        )

    def build_request(
        self,
        request: ProviderRequest,
        *,
        api_key: str | None,
    ) -> tuple[str, str, dict[str, str], dict[str, Any]]:
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        payload: dict[str, Any] = {
            "model": request.model,
            "input": request.effective_payload(),
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_output_tokens"] = request.max_output_tokens
        thinking = normalize_thinking_level(request.thinking_level)
        if thinking != "none":
            payload["reasoning"] = {"effort": thinking}
        text_format = responses_text_format(request, capabilities=self.capabilities)
        if text_format is not None:
            payload["text"] = text_format
        elif request.response_format in {"json", "json_schema"} and (
            self.capabilities.supports_json_object_mode
        ):
            payload["text"] = {"format": {"type": "json_object"}}
        base = self.config.base_url.rstrip("/")
        prefix = base if base.endswith("/v1") else f"{base}/v1"
        url = f"{prefix}/responses"
        return "POST", url, headers, payload

    def parse_response(self, response: httpx.Response) -> ProviderResponse:
        payload = response.json()
        usage = payload.get("usage", {})
        output_text = payload.get("output_text")
        if output_text is None:
            output_text = "".join(
                content_item.get("text", "")
                for output_item in payload.get("output", [])
                for content_item in output_item.get("content", [])
                if content_item.get("type") in {"output_text", "text"}
            )
        return ProviderResponse(
            content=str(output_text or ""),
            model_id=str(payload.get("model", self.config.model_name)),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            finish_reason=payload.get("status"),
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
            for field_name in ("context_window", "max_tokens"):
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
