from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from ahadiff.contracts import ProviderCapabilities

from ..provider import AdapterBase
from ..schemas import ProviderRequest, ProviderResponse
from ._capability_overrides import apply_capability_overrides
from .structured import openai_json_schema_format
from .thinking import normalize_thinking_level

if TYPE_CHECKING:
    import httpx


class AzureOpenAIAdapter(AdapterBase):
    """Azure deployments should set model_limits_name for registry limit lookup.

    Deployment names may differ from base model names, so live context probing stays disabled.
    """

    DEFAULT_API_VERSION = "2024-10-21"

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
                supports_context_probe=False,
                tokenizer_estimation="tiktoken",
                api_family="openai",
                api_family_version="2024-10-21",
                provider_kind="azure",
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
        v1_compat = self._is_v1_compat()
        if api_key:
            if v1_compat:
                headers["authorization"] = f"Bearer {api_key}"
            else:
                headers["api-key"] = api_key
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": request.effective_payload()}],
            "stream": False,
        }
        if v1_compat:
            payload["model"] = request.model
        thinking = normalize_thinking_level(request.thinking_level)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            token_key = "max_completion_tokens" if thinking != "none" else "max_tokens"
            payload[token_key] = request.max_output_tokens
        if thinking != "none":
            payload["reasoning_effort"] = thinking
        native_format = openai_json_schema_format(request, capabilities=self.capabilities)
        if native_format is not None:
            payload["response_format"] = native_format
        elif request.response_format in {"json", "json_schema"} and (
            self.capabilities.supports_json_object_mode
        ):
            payload["response_format"] = {"type": "json_object"}
        url = self._build_url(request.model)
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

    def _build_url(self, deployment: str) -> str:
        parsed = urlsplit(self.config.base_url)
        base_path = parsed.path.rstrip("/")
        if base_path.endswith("/v1"):
            path = f"{base_path}/chat/completions"
            return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))
        query = parse_qs(parsed.query, keep_blank_values=True)
        api_version = query.get("api-version", [self.DEFAULT_API_VERSION])[-1]
        query["api-version"] = [api_version]
        if "/deployments" not in base_path:
            base_path = f"{base_path}/deployments"
        path = f"{base_path}/{deployment}/chat/completions"
        return urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(query, doseq=True), ""))

    def _is_v1_compat(self) -> bool:
        return self.config.base_url.rstrip("/").endswith("/v1")
