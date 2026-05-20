from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ahadiff.contracts import ProviderCapabilities

    from ..schemas import ProviderRequest
else:
    ProviderCapabilities = Any
    ProviderRequest = Any

_SCHEMA_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


def schema_name_for_request(request: ProviderRequest) -> str:
    schema_id = request.output_schema_id or "ahadiff_output"
    schema_version = request.output_schema_version or "1"
    raw_name = f"{schema_id}_v{schema_version}"
    normalized = _SCHEMA_NAME_RE.sub("_", raw_name).strip("_")
    return (normalized or "ahadiff_output")[:64]


def native_schema_for_request(request: ProviderRequest) -> dict[str, Any] | None:
    if request.response_format != "json_schema":
        return None
    if request.enforcement_mode != "native_json_schema":
        return None
    if request.output_schema is None:
        return None
    return dict(request.output_schema)


def _openai_schema_payload(
    request: ProviderRequest,
    schema: dict[str, Any],
    *,
    capabilities: ProviderCapabilities,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema": schema}
    if capabilities.supports_schema_name:
        payload["name"] = schema_name_for_request(request)
    if capabilities.supports_schema_strict_flag:
        payload["strict"] = True
    return payload


def openai_json_schema_format(
    request: ProviderRequest,
    *,
    capabilities: ProviderCapabilities,
) -> dict[str, Any] | None:
    if not capabilities.supports_native_json_schema:
        return None
    schema = native_schema_for_request(request)
    if schema is None:
        return None
    return {
        "type": "json_schema",
        "json_schema": _openai_schema_payload(request, schema, capabilities=capabilities),
    }


def responses_text_format(
    request: ProviderRequest,
    *,
    capabilities: ProviderCapabilities,
) -> dict[str, Any] | None:
    if not capabilities.supports_native_json_schema:
        return None
    schema = native_schema_for_request(request)
    if schema is None:
        return None
    return {
        "format": {
            "type": "json_schema",
            **_openai_schema_payload(request, schema, capabilities=capabilities),
        },
    }


def gemini_response_format(
    request: ProviderRequest,
    *,
    capabilities: ProviderCapabilities,
) -> dict[str, Any] | None:
    schema = (
        native_schema_for_request(request) if capabilities.supports_native_json_schema else None
    )
    if schema is not None:
        return {"responseMimeType": "application/json", "responseSchema": schema}
    if request.response_format in {"json", "json_schema"}:
        return {"responseMimeType": "application/json"}
    return None


__all__ = [
    "gemini_response_format",
    "native_schema_for_request",
    "openai_json_schema_format",
    "responses_text_format",
    "schema_name_for_request",
]
