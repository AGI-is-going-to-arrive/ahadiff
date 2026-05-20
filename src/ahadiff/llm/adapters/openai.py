from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ahadiff.contracts import ProviderCapabilities

from ..provider import AdapterBase
from ..schemas import ProviderRequest, ProviderResponse
from ._capability_overrides import apply_capability_overrides
from .structured import openai_json_schema_format
from .thinking import reject_unsupported_thinking

if TYPE_CHECKING:
    import httpx


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

    def parse_context_probe(self, response: httpx.Response, *, model_name: str) -> int | None:
        payload = response.json()
        for item in payload.get("data", []):
            if item.get("id") != model_name:
                continue
            value = item.get("context_window") or item.get("max_tokens")
            if value is not None:
                return int(value)
        return None
