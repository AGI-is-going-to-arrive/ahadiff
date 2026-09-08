from __future__ import annotations

import re
import unicodedata
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
    "document",
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
    "openai_compat",
]
TokenizerEstimation: TypeAlias = Literal["tiktoken", "char_div_4", "probe_cached"]
ThinkingLevel: TypeAlias = Literal[
    "none", "minimal", "low", "medium", "high", "xhigh", "max", "enabled"
]
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
ProviderLimitsSource: TypeAlias = Literal["live", "registry", "default", "fallback"]
_PROVIDER_CAPABILITY_OVERRIDE_FIELDS = frozenset(get_args(ProviderCapabilityOverride))
COMPARE_FILE_MAX_BYTES = 256 * 1024
COMPARE_FILES_MAX_BYTES = 2 * COMPARE_FILE_MAX_BYTES
_WINDOWS_DEVICE_NAME = re.compile(r"^(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)", re.I)


class CompareFileInput(BaseModel):
    """A browser-selected text file, held in memory until capture redacts it."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=255)
    content: str = Field(repr=False)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value)
        if (
            value != value.strip()
            or value.endswith(".")
            or value.casefold() in {".", "..", ".git", ".ahadiff"}
            or not value.isprintable()
            or any(char in value for char in '/\\:<>"|?*')
            or _WINDOWS_DEVICE_NAME.match(value)
        ):
            raise ValueError("file name must be a portable basename, not a path")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("file name must be valid Unicode") from None
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("file content must be text, not binary")
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            raise ValueError("file content must be valid Unicode") from None
        if size > COMPARE_FILE_MAX_BYTES:
            raise ValueError(f"file content exceeds {COMPARE_FILE_MAX_BYTES} UTF-8 bytes")
        return value


class DocumentInput(CompareFileInput):
    """One explicitly selected Markdown document; never an implicit diff."""

    @field_validator("name")
    @classmethod
    def validate_markdown_name(cls, value: str) -> str:
        if not value.casefold().endswith((".md", ".markdown")):
            raise ValueError("document input must be a Markdown file (.md or .markdown)")
        return value


class SnapshotProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    snapshot_id: str = Field(pattern=r"^snap_[0-9a-f]{32}$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_scope: Literal["sanitized_utf8_nfc_lf"]
    name: str = Field(min_length=1, max_length=80)
    file_name: str
    sanitized: bool

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        return CompareFileInput(name=value, content="").name


REVIEW_CONTEXT_MAX_BYTES = 8 * 1024


def validate_review_context(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("review context must be UTF-8 text without NUL")
    if any(unicodedata.category(char) == "Cc" and char not in "\t\r\n" for char in value):
        raise ValueError("review context contains unsupported control characters")
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    try:
        size = len(normalized.encode("utf-8"))
        raw_size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise ValueError("review context must be valid Unicode") from None
    if size > REVIEW_CONTEXT_MAX_BYTES or raw_size > REVIEW_CONTEXT_MAX_BYTES:
        raise ValueError("review context exceeds 8192 UTF-8 bytes")
    return normalized if normalized.strip() else None


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
    probed_max_input_tokens: int | None = None
    probed_max_output_tokens: int | None = None
    probed_limits_source: ProviderLimitsSource | None = None
    model_limits_name: str | None = None
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
    "COMPARE_FILE_MAX_BYTES",
    "COMPARE_FILES_MAX_BYTES",
    "CompareFileInput",
    "DocumentInput",
    "SnapshotProvenance",
    "REVIEW_CONTEXT_MAX_BYTES",
    "validate_review_context",
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
    "ProviderLimitsSource",
    "ThinkingLevel",
    "empty_degraded_flags",
]
