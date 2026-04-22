from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ahadiff.contracts import ProviderCapabilities

from ..provider import AdapterBase
from ..schemas import ProviderRequest, ProviderResponse

if TYPE_CHECKING:
    import httpx


class AnthropicAdapter(AdapterBase):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_stream=True,
            supports_json_mode=False,
            supports_tool_use=True,
            supports_temperature=True,
            supports_rate_limit_headers=False,
            supports_context_probe=False,
            tokenizer_estimation="tiktoken",
            api_family="anthropic",
            api_family_version="2023-06-01",
            provider_kind="anthropic",
        )

    def build_request(
        self,
        request: ProviderRequest,
        *,
        api_key: str | None,
    ) -> tuple[str, str, dict[str, str], dict[str, Any]]:
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if api_key:
            headers["x-api-key"] = api_key
        default_max_tokens = self.config.probed_max_context or 4096
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.effective_payload()}],
            "max_tokens": request.max_output_tokens or max(256, min(4096, default_max_tokens // 4)),
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        url = f"{self.config.base_url.rstrip('/')}/v1/messages"
        return "POST", url, headers, payload

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
