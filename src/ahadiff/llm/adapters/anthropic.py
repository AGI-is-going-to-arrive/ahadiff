from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ahadiff.contracts import ProviderCapabilities
from ahadiff.core.errors import ProviderError

from ..provider import AdapterBase
from ..schemas import ProviderRequest, ProviderResponse
from .structured import native_schema_for_request
from .thinking import anthropic_budget_tokens

if TYPE_CHECKING:
    import httpx


class AnthropicAdapter(AdapterBase):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_stream=True,
            supports_json_mode=False,
            supports_native_json_schema=True,
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
        max_tokens = request.max_output_tokens or max(256, min(4096, default_max_tokens // 4))
        budget = anthropic_budget_tokens(request.thinking_level)
        if budget is not None:
            if request.max_output_tokens is not None and request.max_output_tokens <= budget:
                raise ProviderError(
                    f"anthropic thinking requires max_output_tokens > budget_tokens={budget}"
                )
            max_tokens = max(max_tokens, budget + 1)
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.effective_payload()}],
            "max_tokens": max_tokens,
        }
        if budget is not None:
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
        elif request.temperature is not None:
            payload["temperature"] = request.temperature
        schema = native_schema_for_request(request)
        if schema is not None:
            payload["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": schema,
                }
            }
        base = self.config.base_url.rstrip("/")
        prefix = base if base.endswith("/v1") else f"{base}/v1"
        url = f"{prefix}/messages"
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
