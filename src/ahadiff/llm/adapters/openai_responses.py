from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ahadiff.contracts import ProviderCapabilities

from ..provider import AdapterBase
from ..schemas import ProviderRequest, ProviderResponse

if TYPE_CHECKING:
    import httpx


class OpenAIResponsesAdapter(AdapterBase):
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
            provider_kind="openai_responses",
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
        if request.response_format == "json":
            payload["text"] = {"format": {"type": "json_object"}}
        url = f"{self.config.base_url.rstrip('/')}/v1/responses"
        return "POST", url, headers, payload

    def parse_response(self, response: httpx.Response) -> ProviderResponse:
        payload = response.json()
        usage = payload.get("usage", {})
        output_text = payload.get("output_text")
        if output_text is None:
            output_text = "".join(
                item.get("text", "")
                for item in payload.get("output", [])
                for content in item.get("content", [])
                for item in [content]
                if content.get("type") in {"output_text", "text"}
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
