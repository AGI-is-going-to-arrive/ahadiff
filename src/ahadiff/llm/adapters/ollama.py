from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ahadiff.contracts import ProviderCapabilities

from ..provider import AdapterBase
from ..schemas import ProviderRequest, ProviderResponse
from .thinking import normalize_thinking_level

if TYPE_CHECKING:
    import httpx


class OllamaAdapter(AdapterBase):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_stream=True,
            supports_json_mode=False,
            supports_tool_use=False,
            supports_temperature=True,
            supports_rate_limit_headers=False,
            supports_context_probe=False,
            tokenizer_estimation="char_div_4",
            api_family="ollama",
            api_family_version="v1",
            provider_kind="ollama",
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
