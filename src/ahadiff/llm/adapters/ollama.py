from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from ahadiff.contracts import ProviderCapabilities

from ..probe_limits import safe_positive_int
from ..provider import AdapterBase
from ..schemas import ProbeContextResult, ProviderRequest, ProviderResponse
from ._capability_overrides import apply_capability_overrides
from .structured import native_schema_for_request
from .thinking import normalize_thinking_level

if TYPE_CHECKING:
    import httpx


class OllamaAdapter(AdapterBase):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return apply_capability_overrides(
            ProviderCapabilities(
                supports_stream=True,
                supports_json_mode=True,
                supports_json_object_mode=True,
                supports_native_json_schema=True,
                supports_tool_use=False,
                supports_temperature=True,
                supports_rate_limit_headers=False,
                supports_context_probe=True,
                tokenizer_estimation="char_div_4",
                api_family="ollama",
                api_family_version="v1",
                provider_kind="ollama",
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
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.effective_payload()}],
            "stream": False,
            "think": normalize_thinking_level(request.thinking_level) != "none",
        }
        if request.temperature is not None:
            payload["options"] = {"temperature": request.temperature}
        schema = (
            native_schema_for_request(request)
            if self.capabilities.supports_native_json_schema
            else None
        )
        if schema is not None:
            payload["format"] = schema
        elif request.response_format in {"json", "json_schema"} and (
            self.capabilities.supports_json_object_mode
        ):
            payload["format"] = "json"
        url = f"{self.config.base_url.rstrip('/')}/api/chat"
        return "POST", url, headers, payload

    def parse_response(self, response: httpx.Response) -> ProviderResponse:
        payload = response.json()
        message = payload.get("message", {})
        content = str(message.get("content") or "")
        if not content:
            content = str(message.get("reasoning_content") or "")
        return ProviderResponse(
            content=content,
            model_id=str(payload.get("model", self.config.model_name)),
            input_tokens=int(payload.get("prompt_eval_count", 0)),
            output_tokens=int(payload.get("eval_count", 0)),
            finish_reason=payload.get("done_reason"),
            request_id=response.headers.get("x-request-id"),
            raw_json=payload,
        )

    def build_context_probe_request(
        self,
        *,
        api_key: str | None,
        model_name: str,
    ) -> tuple[str, str, dict[str, str], bytes]:
        headers = {"content-type": "application/json"}
        body = json.dumps({"name": model_name}, separators=(",", ":")).encode("utf-8")
        return "POST", f"{self.config.base_url.rstrip('/')}/api/show", headers, body

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
        model_info = payload_mapping.get("model_info", {})
        architecture_context = _parse_model_info_context_length(model_info)
        num_ctx = _parse_parameters_num_ctx(payload_mapping.get("parameters"))
        if architecture_context is not None and num_ctx is not None:
            context_length = min(architecture_context, num_ctx)
        else:
            context_length = architecture_context or num_ctx
        if context_length is None:
            return None
        warnings: tuple[str, ...] = ()
        if (
            architecture_context is not None
            and num_ctx is not None
            and num_ctx < architecture_context
        ):
            warnings = (
                "ollama_num_ctx_below_architecture_context_length:"
                f"{num_ctx}<{architecture_context}",
            )
        return ProbeContextResult(
            max_context_tokens=context_length,
            max_input_tokens=None,
            max_output_tokens=None,
            source="live",
            warnings=warnings,
        )


def _parse_model_info_context_length(model_info: object) -> int | None:
    if not isinstance(model_info, dict):
        return None
    typed_model_info = cast("dict[str, Any]", model_info)
    values = [value for key, value in typed_model_info.items() if key.endswith(".context_length")]
    return _max_positive_int(values)


def _parse_parameters_num_ctx(parameters: object) -> int | None:
    if not isinstance(parameters, str):
        return None
    parts = parameters.replace("=", " ").split()
    for index, part in enumerate(parts[:-1]):
        if part == "num_ctx":
            return _positive_int_text_or_none(parts[index + 1])
    return None


def _max_positive_int(values: list[Any]) -> int | None:
    parsed = [_positive_int_or_none(value) for value in values]
    positive = [value for value in parsed if value is not None]
    return max(positive, default=None)


def _positive_int_or_none(value: object) -> int | None:
    return safe_positive_int(value)


def _positive_int_text_or_none(value: str) -> int | None:
    if not value.isdecimal():
        return None
    return safe_positive_int(int(value))
