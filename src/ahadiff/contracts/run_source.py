from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

SourceKind: TypeAlias = Literal[
    "git_ref",
    "git_staged",
    "git_unstaged",
    "git_since",
    "patch_file",
    "patch_stdin",
    "file_compare",
]
DegradedFlag: TypeAlias = Literal[
    "diff_clipped",
    "binary_only",
    "file_count_exceeded",
    "token_exceeded",
]
PrivacyMode: TypeAlias = Literal["strict_local", "redacted_remote", "explicit_remote"]
ProviderClass: TypeAlias = Literal[
    "openai",
    "openai_responses",
    "gemini",
    "anthropic",
    "azure",
    "newapi",
    "cherryin",
    "ollama",
]
TokenizerEstimation: TypeAlias = Literal["tiktoken", "char_div_4", "probe_cached"]
DegradedFlagsMap: TypeAlias = dict[DegradedFlag, bool]


def empty_degraded_flags() -> DegradedFlagsMap:
    return {}


class RunSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: SourceKind
    source_ref: str
    capability_level: Literal[1, 2, 3]
    degraded_flags: DegradedFlagsMap = Field(default_factory=empty_degraded_flags)


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_class: ProviderClass
    model_name: str
    base_url: str
    api_key_env: str
    probed_max_context: int | None = None
    probed_tpm: int | None = None
    probed_rpm: int | None = None
    supports_temperature: bool | None = None
    probe_timestamp: str | None = None


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supports_stream: bool
    supports_json_mode: bool
    supports_tool_use: bool
    supports_temperature: bool
    supports_rate_limit_headers: bool
    supports_context_probe: bool
    tokenizer_estimation: TokenizerEstimation
    api_family: str
    api_family_version: str
    provider_kind: str


class AllowlistPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    builtin_hard_block: bool = True
    soft_detect_suppressible: bool = True
    supported_match_kinds: tuple[Literal["exact", "hash", "path_scope"], ...] = (
        "exact",
        "hash",
        "path_scope",
    )
    allowlist_digest: str | None = None


__all__ = [
    "SourceKind",
    "DegradedFlag",
    "PrivacyMode",
    "ProviderClass",
    "TokenizerEstimation",
    "RunSource",
    "ProviderConfig",
    "ProviderCapabilities",
    "AllowlistPolicy",
    "DegradedFlagsMap",
    "empty_degraded_flags",
]
