from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from . import run_source as run_source_contract
from . import serve_stats as serve_stats_contract

ProviderClass: TypeAlias = run_source_contract.ProviderClass
ThinkingLevel: TypeAlias = run_source_contract.ThinkingLevel
ProviderSummary: TypeAlias = serve_stats_contract.ProviderSummary

ProviderAlias = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"),
]
ProviderMaxOutputTokens = Annotated[StrictInt, Field(ge=1, le=1_000_000)]


def _empty_provider_warnings() -> list[dict[str, object]]:
    return []


class ProviderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: ProviderAlias
    provider_class: ProviderClass
    model_name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key_env: str = Field(min_length=1, max_length=128)
    max_output_tokens: ProviderMaxOutputTokens | None = None
    thinking_level: ThinkingLevel | None = None
    model_limits_name: str | None = Field(default=None, min_length=1, max_length=200)


class ProviderUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_class: ProviderClass | None = None
    model_name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    api_key_env: str | None = Field(default=None, min_length=1, max_length=128)
    max_output_tokens: ProviderMaxOutputTokens | None = None
    thinking_level: ThinkingLevel | None = None
    model_limits_name: str | None = Field(default=None, min_length=1, max_length=200)


class ProviderMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updated: bool
    provider: ProviderSummary
    warnings: list[dict[str, object]] = Field(default_factory=_empty_provider_warnings)


class ModelLimitsPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_class: ProviderClass
    model_name: str = Field(min_length=1, max_length=200)
    model_limits_name: str | None = Field(default=None, min_length=1, max_length=200)


class ModelLimitsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str | None = None
    provider_class: ProviderClass
    model_name: str
    max_context_tokens: int | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    max_context_known: bool
    max_input_known: bool
    max_output_known: bool
    context_policy: (
        Literal[
            "shared_pool",
            "split_envelope",
            "route_specific",
            "local_runtime",
        ]
        | None
    )
    source: Literal["live", "registry", "default", "mixed"]
    confidence: Literal["high", "medium", "low"] | None
    warnings: list[dict[str, object]]
    thinking: dict[str, object]


class ProviderDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: bool
    alias: ProviderAlias


class ProviderProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False


class ProviderProbeSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    alias: ProviderAlias
    status: Literal["submitted"] = "submitted"
    poll_url: str


__all__ = [
    "ModelLimitsPreviewRequest",
    "ModelLimitsResponse",
    "ProviderAlias",
    "ProviderCreateRequest",
    "ProviderDeleteResponse",
    "ProviderMutationResponse",
    "ProviderProbeRequest",
    "ProviderProbeSubmitResponse",
    "ProviderUpdateRequest",
]
