from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ahadiff.contracts import ProviderCapabilities

from ..provider import AdapterBase
from ..schemas import ProviderRequest, ProviderResponse

if TYPE_CHECKING:
    import httpx


class OpenAIChatAdapter(AdapterBase):
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
            provider_kind="openai_chat",
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
            "messages": [{"role": "user", "content": request.effective_payload()}],
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        url = f"{self.config.base_url.rstrip('/')}/v1/chat/completions"
        return "POST", url, headers, payload

    def parse_response(self, response: httpx.Response) -> ProviderResponse:
        payload = response.json()
        choice = payload["choices"][0]
        message = choice.get("message", {})
        usage = payload.get("usage", {})
        return ProviderResponse(
            content=str(message.get("content", "")),
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
        return "GET", f"{self.config.base_url.rstrip('/')}/v1/models", headers

    def parse_context_probe(self, response: httpx.Response, *, model_name: str) -> int | None:
        payload = response.json()
        for item in payload.get("data", []):
            if item.get("id") != model_name:
                continue
            value = item.get("context_window") or item.get("max_tokens")
            if value is not None:
                return int(value)
        return None
