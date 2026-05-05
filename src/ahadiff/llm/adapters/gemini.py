from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ahadiff.contracts import ProviderCapabilities

from ..provider import AdapterBase
from ..schemas import ProviderRequest, ProviderResponse
from .thinking import gemini_thinking_level

if TYPE_CHECKING:
    import httpx


class GeminiAdapter(AdapterBase):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_stream=False,
            supports_json_mode=True,
            supports_tool_use=False,
            supports_temperature=True,
            supports_rate_limit_headers=False,
            supports_context_probe=True,
            tokenizer_estimation="char_div_4",
            api_family="gemini",
            api_family_version="v1beta",
            provider_kind="gemini",
        )

    def build_request(
        self,
        request: ProviderRequest,
        *,
        api_key: str | None,
    ) -> tuple[str, str, dict[str, str], dict[str, Any]]:
        headers = {"content-type": "application/json"}
        if api_key:
            headers["x-goog-api-key"] = api_key
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": request.effective_payload()}]}],
        }
        generation_config: dict[str, Any] = {}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_output_tokens
        thinking = gemini_thinking_level(request.thinking_level)
        if thinking is not None:
            generation_config["thinkingConfig"] = {"thinkingLevel": thinking}
        if generation_config:
            payload["generationConfig"] = generation_config
        url = f"{self.config.base_url.rstrip('/')}/v1beta/models/{request.model}:generateContent"
        return "POST", url, headers, payload

    def parse_response(self, response: httpx.Response) -> ProviderResponse:
        payload = response.json()
        candidate = payload["candidates"][0]
        content = candidate.get("content", {})
        text = "".join(part.get("text", "") for part in content.get("parts", []))
        usage = payload.get("usageMetadata", {})
        return ProviderResponse(
            content=text,
            model_id=self.config.model_name,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
            finish_reason=candidate.get("finishReason"),
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
            headers["x-goog-api-key"] = api_key
        return "GET", f"{self.config.base_url.rstrip('/')}/v1beta/models/{model_name}", headers

    def parse_context_probe(self, response: httpx.Response, *, model_name: str) -> int | None:
        payload = response.json()
        value = payload.get("inputTokenLimit") or payload.get("contextWindow")
        return None if value is None else int(value)
