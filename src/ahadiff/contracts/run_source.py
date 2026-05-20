from __future__ import annotations

from typing import Literal, TypeAlias, get_args

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

SourceKind: TypeAlias = Literal[
    "git_ref",
    "git_staged",
    "git_staged_unstaged",
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
    "ollama",
    "lmstudio",
]
TokenizerEstimation: TypeAlias = Literal["tiktoken", "char_div_4", "probe_cached"]
ThinkingLevel: TypeAlias = Literal["none", "low", "medium", "high"]
DegradedFlagsMap: TypeAlias = dict[DegradedFlag, bool]
ProviderCapabilityOverride: TypeAlias = Literal[
    "supports_stream",
    "supports_json_mode",
    "supports_json_object_mode",
    "supports_native_json_schema",
    "supports_schema_name",
    "supports_schema_strict_flag",
    "supports_tool_use",
    "supports_temperature",
    "supports_rate_limit_headers",
    "supports_context_probe",
]
_PROVIDER_CAPABILITY_OVERRIDE_FIELDS = frozenset(get_args(ProviderCapabilityOverride))


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
    max_output_tokens: int | None = None
    thinking_level: ThinkingLevel | None = None
    probed_max_context: int | None = None
    probed_tpm: int | None = None
    probed_rpm: int | None = None
    probe_timestamp: str | None = None
    capability_overrides: dict[str, StrictBool] | None = None

    @field_validator("capability_overrides")
    @classmethod
    def validate_capability_overrides(
        cls,
        value: dict[str, StrictBool] | None,
    ) -> dict[str, StrictBool] | None:
        if value is None:
            return None
        unknown = sorted(set(value) - _PROVIDER_CAPABILITY_OVERRIDE_FIELDS)
        if unknown:
            allowed = ", ".join(sorted(_PROVIDER_CAPABILITY_OVERRIDE_FIELDS))
            raise ValueError(
                "capability_overrides keys must be ProviderCapabilities boolean fields "
                f"({allowed}); got {', '.join(unknown)}"
            )
        return value


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supports_stream: bool
    supports_json_mode: bool
    supports_json_object_mode: bool = False
    supports_native_json_schema: bool = False
    supports_strict_tool_use: bool = False
    supports_schema_name: bool = False
    supports_schema_strict_flag: bool = False
    structured_output_notes: tuple[str, ...] = ()
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
    "ProviderCapabilityOverride",
    "TokenizerEstimation",
    "RunSource",
    "ProviderConfig",
    "ProviderCapabilities",
    "AllowlistPolicy",
    "DegradedFlagsMap",
    "ThinkingLevel",
    "empty_degraded_flags",
]
