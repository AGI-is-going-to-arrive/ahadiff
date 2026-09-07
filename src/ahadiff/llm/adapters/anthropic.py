from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from ahadiff.contracts import ProviderCapabilities

from ..probe_limits import safe_positive_int
from ..provider import AdapterBase
from ..schemas import ProbeContextResult, ProviderRequest, ProviderResponse
from ._capability_overrides import apply_capability_overrides
from .thinking import supports_request_temperature, thinking_payload_for

if TYPE_CHECKING:
    import httpx

_JSON_OBJECT_SYSTEM_INSTRUCTION = (
    "Return a single valid JSON object only. Do not include markdown fences, prose, "
    "or any text outside the JSON object."
)
_CONTEXT_PROBE_TOTAL_FIELDS = ("max_context_tokens", "context_window", "max_context_length")


def _first_positive_probe_limit(
    mapping: dict[str, Any],
    field_names: tuple[str, ...],
) -> int | None:
    for field_name in field_names:
        value = safe_positive_int(mapping.get(field_name))
        if value is not None:
            return value
    return None


class AnthropicAdapter(AdapterBase):
    def prepare_request(self, request: ProviderRequest) -> ProviderRequest:
        request = super().prepare_request(request)
        if request.max_output_tokens is not None:
            return request
        context_limit = self.config.probed_max_context or 4096
        return replace(request, max_output_tokens=max(256, min(4096, context_limit // 4)))

    @property
    def capabilities(self) -> ProviderCapabilities:
        return apply_capability_overrides(
            ProviderCapabilities(
                supports_stream=True,
                supports_json_mode=False,
                supports_json_object_mode=True,
                supports_native_json_schema=False,
                supports_tool_use=True,
                supports_temperature=True,
                supports_rate_limit_headers=False,
                supports_context_probe=True,
                tokenizer_estimation="tiktoken",
                api_family="anthropic",
                api_family_version="2023-06-01",
                provider_kind="anthropic",
            ),
            self.config.capability_overrides,
            blocked_fields=frozenset({"supports_native_json_schema"}),
        )

    def build_request(
        self,
        request: ProviderRequest,
        *,
        api_key: str | None,
    ) -> tuple[str, str, dict[str, str], dict[str, Any]]:
        request = self.prepare_request(request)
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if api_key:
            headers["x-api-key"] = api_key
        thinking_payload = thinking_payload_for(
            "anthropic", request.model, request.thinking_level, base_url=self.config.base_url
        )
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.effective_payload()}],
            "max_tokens": request.max_output_tokens,
        }
        if request.response_format == "json" or request.enforcement_mode == "json_object":
            payload["system"] = _JSON_OBJECT_SYSTEM_INSTRUCTION
        payload.update(thinking_payload)
        if request.temperature is not None and supports_request_temperature(
            "anthropic", request.model, request.thinking_level, base_url=self.config.base_url
        ):
            payload["temperature"] = request.temperature
        base = self.config.base_url.rstrip("/")
        prefix = base if base.endswith("/v1") else f"{base}/v1"
        url = f"{prefix}/messages"
        return "POST", url, headers, payload

    def build_context_probe_request(
        self,
        *,
        api_key: str | None,
        model_name: str,
    ) -> tuple[str, str, dict[str, str]] | None:
        headers = {"anthropic-version": "2023-06-01"}
        if api_key:
            headers["x-api-key"] = api_key
        base = self.config.base_url.rstrip("/")
        prefix = base if base.endswith("/v1") else f"{base}/v1"
        model_path = quote(model_name, safe="")
        return "GET", f"{prefix}/models/{model_path}", headers

    def parse_context_probe(
        self,
        response: httpx.Response,
        *,
        model_name: str,
    ) -> ProbeContextResult | None:
        data = response.json()
        if not isinstance(data, dict):
            return None
        data_mapping = cast("dict[str, Any]", data)
        context_limit = _first_positive_probe_limit(data_mapping, _CONTEXT_PROBE_TOTAL_FIELDS)
        input_limit = safe_positive_int(data_mapping.get("max_input_tokens"))
        output_limit = safe_positive_int(data_mapping.get("max_tokens"))
        if context_limit is None and input_limit is None and output_limit is None:
            return None
        return ProbeContextResult(
            max_context_tokens=context_limit,
            max_input_tokens=input_limit,
            max_output_tokens=output_limit,
            source="live",
        )

    def parse_response(self, response: httpx.Response) -> ProviderResponse:
        payload = response.json()
        usage = payload.get("usage", {})
        text = "".join(item.get("text", "") for item in payload.get("content", []))
        return ProviderResponse(
            content=text,
            model_id=str(payload.get("model", self.config.model_name)),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            finish_reason=payload.get("stop_reason"),
            request_id=response.headers.get("x-request-id"),
            raw_json=payload,
        )
