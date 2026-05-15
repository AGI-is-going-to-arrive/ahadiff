from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any, TypeGuard, cast, get_args
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ahadiff.contracts import ProviderClass, ThinkingLevel
from ahadiff.i18n import normalize_locale_preference

from .errors import ConfigError
from .paths import find_repo_root, find_workspace_root, global_config_dir

Scalar = str | int | float | bool | tuple[str, ...]
NestedConfig = dict[str, "Scalar | NestedConfig"]
_PRIVACY_MODES = {"strict_local", "redacted_remote", "explicit_remote"}
_LOCALE_PREFERENCE_KEYS = {"lang", "llm.prompt_lang", "llm.output_lang"}
_CAPTURE_SYMBOL_EXTRACTORS = {"auto", "builtin", "tree_sitter"}
_CAPTURE_FILE_RANKINGS = {"learning_value", "changed_lines", "path"}
_POSITIVE_INT_KEYS = {
    "capture.max_files",
    "capture.hard_limit",
    "capture.max_patch_bytes",
    "llm.claim_extraction_output_cap",
    "llm.lesson_full_output_cap",
    "llm.lesson_hint_output_cap",
    "llm.lesson_compact_output_cap",
    "llm.quiz_generation_output_cap",
    "llm.misconception_cards_output_cap",
}
_QUIZ_QUESTION_COUNT_RANGE = (1, 10)
_SAFE_PROVIDER_API_KEY_ENVS = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "AZURE_OPENAI_API_KEY",
    }
)
_AHADIFF_PROVIDER_API_KEY_ENV_PATTERN = re.compile(r"^AHADIFF_[A-Z0-9_]*$")
_ENV_VAR_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SUPPORTED_PROVIDER_CLASSES = frozenset(cast("tuple[str, ...]", get_args(ProviderClass)))
_THINKING_LEVELS = frozenset(cast("tuple[str, ...]", get_args(ThinkingLevel)))
DEFAULT_CONFIG: dict[str, Any] = {
    "lang": "auto",
    "privacy_mode": "strict_local",
    "capture": {
        "max_files": 30,
        "hard_limit": 3000,
        "max_patch_bytes": 5_000_000,
        "symbol_extractor": "auto",
        "file_ranking": "learning_value",
    },
    "llm": {
        "generate_provider": "",
        "generate_model": "gpt-5.4-mini",
        "judge_provider": "",
        "judge_model": "gpt-5.4-mini",
        "max_concurrent": 3,
        "request_timeout_seconds": 30,
        "retry_attempts": 3,
        "input_token_budget": 200_000,
        "output_token_budget": 50_000,
        "claim_extraction_output_cap": 16_000,
        "lesson_full_output_cap": 24_000,
        "lesson_hint_output_cap": 3_000,
        "lesson_compact_output_cap": 2_500,
        "quiz_generation_output_cap": 6_000,
        "misconception_cards_output_cap": 3_000,
        "prompt_lang": "auto",
        "output_lang": "auto",
    },
    "pricing": {
        "openrouter_enabled": True,
        "openrouter_models_url": "https://openrouter.ai/api/v1/models",
        "openrouter_refresh_seconds": 3600,
    },
    "provider": {
        "qps_limit": 3,
        "circuit_failure_threshold": 5,
        "circuit_cooldown": 60,
    },
    "learn": {
        "learnability_threshold": 0.3,
        "desired_retention": 0.9,
    },
    "quiz": {
        "quiz_question_count": 3,
    },
    "serve": {
        "port": 8765,
        "bind_host": "127.0.0.1",
        "no_browser": False,
    },
    "security": {
        "allow_exact": [],
        "allow_paths": [],
        "suppress_rules": [],
        "local_hosts": [],
    },
    "challenge": {
        "enabled": False,
    },
}

_SENSITIVE_KEY_PATTERN = re.compile(r"(api_key|secret|password|token)", re.IGNORECASE)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{12,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
)
_TOML_BARE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class ResolvedSetting:
    key: str
    value: Scalar
    source: str


@dataclass(frozen=True)
class ConfigConflict:
    key: str
    winner: str
    shadowed: tuple[str, ...]


@dataclass(frozen=True)
class ConfigSnapshot:
    values: dict[str, Any]
    resolved: dict[str, ResolvedSetting]
    repo_config_path: Path
    global_config_path: Path
    repo_unknown_keys: tuple[str, ...]
    global_unknown_keys: tuple[str, ...]
    repo_sensitive_keys: tuple[str, ...]
    precedence_conflicts: tuple[ConfigConflict, ...]


@dataclass(frozen=True)
class SecurityConfig:
    allow_exact: tuple[str, ...] = ()
    allow_paths: tuple[str, ...] = ()
    suppress_rules: tuple[str, ...] = ()
    local_hosts: tuple[str, ...] = ()
    strict_local_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelPriceOverride:
    input_per_million_usd: float
    output_per_million_usd: float
    request_per_call_usd: float | None = None


@dataclass(frozen=True)
class PricingSettings:
    openrouter_enabled: bool = True
    openrouter_models_url: str = "https://openrouter.ai/api/v1/models"
    openrouter_refresh_seconds: int = 3600
    model_overrides: dict[str, ModelPriceOverride] = field(
        default_factory=lambda: dict[str, ModelPriceOverride]()
    )


def _is_string_sequence(value: object) -> TypeGuard[list[str] | tuple[str, ...]]:
    if not isinstance(value, list | tuple):
        return False
    items = cast("list[object] | tuple[object, ...]", value)
    return all(isinstance(item, str) for item in items)


def _flatten_mapping(data: Mapping[str, Any], prefix: str = "") -> dict[str, Scalar]:
    flattened: dict[str, Scalar] = {}
    for key, value in data.items():
        dotted_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping):
            flattened.update(_flatten_mapping(cast("Mapping[str, Any]", value), dotted_key))
            continue
        if _is_string_sequence(value):
            flattened[dotted_key] = tuple(value)
            continue
        if not isinstance(value, str | int | float | bool):
            message = f"{dotted_key} must be a scalar TOML value, got {type(value).__name__}"
            raise ConfigError(message)
        flattened[dotted_key] = value
    return flattened


def _actual_type_name(value: Any) -> str:
    if isinstance(value, Mapping):
        return "table"
    if isinstance(value, list | tuple):
        return "array"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def _expected_type_name(expected: Scalar) -> str:
    if isinstance(expected, bool):
        return "bool"
    if isinstance(expected, tuple):
        return "array of strings"
    if isinstance(expected, int) and not isinstance(expected, bool):
        return "int"
    if isinstance(expected, float):
        return "float"
    return "str"


def _nest_mapping(flattened: Mapping[str, Scalar]) -> dict[str, Any]:
    nested: dict[str, Any] = {}
    for dotted_key, value in flattened.items():
        cursor = nested
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return nested


def _coerce_bool(raw_value: str, *, key: str) -> bool:
    lowered = raw_value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{key} expects a boolean-compatible env value, got {raw_value!r}")


def _coerce_value(
    key: str,
    value: Any,
    expected: Scalar,
    *,
    coerce_strings: bool = True,
) -> Scalar:
    if key in _LOCALE_PREFERENCE_KEYS:
        if not isinstance(value, str):
            raise ConfigError(f"{key} expects str, got {type(value).__name__}")
        preference = normalize_locale_preference(value)
        if preference is None:
            raise ConfigError(f"{key} must be one of auto, en, zh-CN, got {value!r}")
        return preference
    if key == "privacy_mode":
        if not isinstance(value, str):
            raise ConfigError(f"{key} expects str, got {type(value).__name__}")
        if value not in _PRIVACY_MODES:
            allowed = ", ".join(sorted(_PRIVACY_MODES))
            raise ConfigError(f"{key} must be one of {allowed}, got {value!r}")
        return value
    if key == "capture.symbol_extractor":
        if not isinstance(value, str):
            raise ConfigError(f"{key} expects str, got {type(value).__name__}")
        if value not in _CAPTURE_SYMBOL_EXTRACTORS:
            allowed = ", ".join(sorted(_CAPTURE_SYMBOL_EXTRACTORS))
            raise ConfigError(f"{key} must be one of {allowed}, got {value!r}")
        return value
    if key == "capture.file_ranking":
        if not isinstance(value, str):
            raise ConfigError(f"{key} expects str, got {type(value).__name__}")
        if value not in _CAPTURE_FILE_RANKINGS:
            allowed = ", ".join(sorted(_CAPTURE_FILE_RANKINGS))
            raise ConfigError(f"{key} must be one of {allowed}, got {value!r}")
        return value
    if isinstance(expected, bool):
        if isinstance(value, bool):
            return value
        if coerce_strings and isinstance(value, str):
            return _coerce_bool(value, key=key)
        raise ConfigError(f"{key} expects bool, got {type(value).__name__}")
    if isinstance(expected, tuple):
        if _is_string_sequence(value):
            return tuple(value)
        if coerce_strings and isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        raise ConfigError(f"{key} expects an array of strings, got {type(value).__name__}")
    if isinstance(expected, int) and not isinstance(expected, bool):
        coerced: int
        if isinstance(value, int) and not isinstance(value, bool):
            coerced = value
        elif coerce_strings and isinstance(value, str):
            try:
                coerced = int(value)
            except ValueError as exc:
                raise ConfigError(f"{key} expects int, got {value!r}") from exc
        else:
            raise ConfigError(f"{key} expects int, got {type(value).__name__}")
        if key == "quiz.quiz_question_count":
            lo, hi = _QUIZ_QUESTION_COUNT_RANGE
            if coerced < lo or coerced > hi:
                raise ConfigError(f"{key} must be between {lo} and {hi}")
            return coerced
        if key in _POSITIVE_INT_KEYS and coerced < 1:
            raise ConfigError(f"{key} must be >= 1")
        return coerced
    if isinstance(expected, float):
        parsed_float: float
        if isinstance(value, int | float) and not isinstance(value, bool):
            parsed_float = float(value)
        elif coerce_strings and isinstance(value, str):
            try:
                parsed_float = float(value)
            except ValueError as exc:
                raise ConfigError(f"{key} expects float, got {value!r}") from exc
        else:
            raise ConfigError(f"{key} expects float, got {type(value).__name__}")
        if key == "learn.learnability_threshold":
            if not math.isfinite(parsed_float):
                raise ConfigError(f"{key} must be a finite number")
            if parsed_float < 0.0 or parsed_float > 1.0:
                raise ConfigError(f"{key} must be between 0.0 and 1.0")
        if key == "learn.desired_retention":
            if not math.isfinite(parsed_float):
                raise ConfigError(f"{key} must be a finite number")
            if parsed_float < 0.7 or parsed_float > 0.99:
                raise ConfigError(f"{key} must be between 0.7 and 0.99")
        return parsed_float
    if isinstance(value, str):
        return value
    raise ConfigError(f"{key} expects str, got {type(value).__name__}")


_FLAT_DEFAULTS = _flatten_mapping(DEFAULT_CONFIG)
_KNOWN_KEYS = tuple(sorted(_FLAT_DEFAULTS))
_ENV_KEY_MAP = {
    key: f"AHADIFF_{key.replace('.', '_').upper()}"
    for key in _KNOWN_KEYS
    if key != "lang" and not isinstance(_FLAT_DEFAULTS[key], tuple)
}
_PROVIDER_DYNAMIC_FIELDS = frozenset(
    {
        "provider_class",
        "model_name",
        "base_url",
        "api_key_env",
        "max_output_tokens",
        "thinking_level",
        "probed_max_context",
        "probed_tpm",
        "probed_rpm",
        "probe_timestamp",
    }
)
_DYNAMIC_PROVIDER_FIELD_DEFAULTS: dict[str, Scalar] = {
    "provider_class": "",
    "model_name": "",
    "base_url": "",
    "api_key_env": "",
    "max_output_tokens": 0,
    "thinking_level": "",
    "probed_max_context": 0,
    "probed_tpm": 0,
    "probed_rpm": 0,
    "probe_timestamp": "",
}
PROVIDER_STALE_PROBE_FIELDS: tuple[str, ...] = (
    "probed_max_context",
    "probed_tpm",
    "probed_rpm",
    "probe_timestamp",
)
_PROVIDER_CORE_FIELDS: tuple[str, ...] = (
    "provider_class",
    "model_name",
    "base_url",
    "api_key_env",
)
_PROVIDER_ALIAS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_PROVIDER_BASE_URL_TRIM_SUFFIXES: tuple[str, ...] = (
    "/v1/chat/completions",
    "/chat/completions",
    "/v1/responses",
    "/responses",
)
_PROVIDER_BASE_URL_TRIM_CLASSES: frozenset[str] = frozenset(
    {"openai", "openai_responses", "newapi", "lmstudio"}
)
_PROVIDER_METADATA_HOSTS = frozenset(
    {"169.254.169.254", "metadata.google.internal", "metadata.azure.com", "fd00:ec2::254"}
)
_PROVIDER_LOCALHOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_PROVIDER_RFC1918_NETWORKS = tuple(
    ip_network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_PROVIDER_SENSITIVE_QUERY_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|password|token|credential)",
    re.IGNORECASE,
)


def validate_provider_alias(alias: str) -> str:
    if not _PROVIDER_ALIAS_PATTERN.fullmatch(alias):
        raise ConfigError("provider alias must match ^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    return alias


def normalize_provider_base_url(base_url: str, *, provider_class: str) -> str:
    raw = base_url.strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw.rstrip("/")
    if not parsed.scheme or not parsed.netloc or parsed.hostname is None:
        return raw.rstrip("/")

    scheme = parsed.scheme.lower()
    host = _normalize_provider_host(parsed.hostname)
    netloc = _format_provider_host_for_netloc(host)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None and not _is_default_provider_port(scheme, port):
        netloc = f"{netloc}:{port}"
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0]
        netloc = f"{userinfo}@{netloc}"

    path = "" if parsed.path == "/" else parsed.path
    if provider_class not in _PROVIDER_BASE_URL_TRIM_CLASSES:
        return urlunsplit((scheme, netloc, path, parsed.query, parsed.fragment))
    path_for_suffix = path[:-1] if path.endswith("/") else path
    for suffix in _PROVIDER_BASE_URL_TRIM_SUFFIXES:
        if path_for_suffix.endswith(suffix):
            path = path_for_suffix[: -len(suffix)] or ""
            break
    return urlunsplit((scheme, netloc, path, parsed.query, parsed.fragment))


def _safe_url_repr(base_url: str) -> str:
    """Mask URL for error messages to prevent secret leakage."""
    try:
        return mask_provider_base_url_for_display(base_url)
    except Exception:
        return "<invalid-url>"


def validate_provider_base_url(
    base_url: str,
    *,
    allowed_local_hosts: tuple[str, ...] = (),
) -> str:
    raw = base_url.strip()
    safe_base_url = _safe_url_repr(base_url)
    if raw == "" or any(char.isspace() for char in raw):
        raise ConfigError(f"provider base_url expects valid URL, got {safe_base_url!r}")
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise ConfigError(f"provider base_url expects valid URL, got {safe_base_url!r}") from exc
    if not parsed.scheme or not parsed.netloc or parsed.hostname is None:
        raise ConfigError(f"provider base_url expects valid URL, got {safe_base_url!r}")
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ConfigError(f"provider base_url expects http or https URL, got {safe_base_url!r}")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ConfigError("provider base_url must not include URL userinfo")
    try:
        _port = parsed.port
    except ValueError as exc:
        raise ConfigError(f"provider base_url expects valid port, got {safe_base_url!r}") from exc
    if _provider_query_has_inline_secret(parsed.query):
        raise ConfigError("provider base_url must not include credential query parameters")

    host = _normalize_provider_host(parsed.hostname)
    if host in _PROVIDER_METADATA_HOSTS:
        raise ConfigError("provider base_url points to a blocked metadata host")
    allowed_hosts = {_normalize_provider_host(item) for item in allowed_local_hosts}
    if host in _PROVIDER_LOCALHOSTS:
        if host not in allowed_hosts:
            raise ConfigError("provider base_url local host requires explicit opt-in")
        return raw
    try:
        addr = ip_address(host)
    except ValueError:
        return raw
    if str(addr) in _PROVIDER_METADATA_HOSTS:
        raise ConfigError("provider base_url points to a blocked metadata host")
    if _is_private_provider_ip(addr) and host not in allowed_hosts:
        raise ConfigError("provider base_url private IP literal requires explicit opt-in")
    return raw


def mask_provider_base_url_for_display(base_url: str) -> str:
    try:
        parsed = urlsplit(base_url)
    except ValueError:
        return base_url
    if not parsed.scheme or not parsed.netloc or parsed.hostname is None:
        return base_url
    scheme = parsed.scheme.lower()
    host = _normalize_provider_host(parsed.hostname)
    netloc = _format_provider_host_for_netloc(host)
    with_port = True
    try:
        port = parsed.port
    except ValueError:
        port = None
        with_port = False
    if with_port and port is not None and not _is_default_provider_port(scheme, port):
        netloc = f"{netloc}:{port}"
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        netloc = f"***@{netloc}"
    query = _mask_provider_query(parsed.query)
    return urlunsplit((scheme, netloc, parsed.path, query, parsed.fragment))


def _normalize_provider_host(host: str) -> str:
    return host.strip("[]").rstrip(".").lower()


def _format_provider_host_for_netloc(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _is_default_provider_port(scheme: str, port: int) -> bool:
    return (scheme == "http" and port == 80) or (scheme == "https" and port == 443)


def _is_private_provider_ip(addr: object) -> bool:
    if getattr(addr, "version", None) == 4:
        return any(addr in network for network in _PROVIDER_RFC1918_NETWORKS)
    return bool(getattr(addr, "is_private", False))


def _mask_provider_query(query: str) -> str:
    if not query:
        return query
    pairs = parse_qsl(query, keep_blank_values=True)
    if not pairs:
        return query
    masked = [
        (key, "***" if _PROVIDER_SENSITIVE_QUERY_KEY_PATTERN.search(key) else value)
        for key, value in pairs
    ]
    return urlencode(masked, doseq=True)


def _provider_query_has_inline_secret(query: str) -> bool:
    if not query:
        return False
    return any(
        _PROVIDER_SENSITIVE_QUERY_KEY_PATTERN.search(key) is not None
        for key, _value in parse_qsl(query, keep_blank_values=True)
    )


def clear_provider_probe_fields(provider: dict[str, object]) -> None:
    for field_name in PROVIDER_STALE_PROBE_FIELDS:
        provider.pop(field_name, None)


def provider_core_fingerprint(provider: Mapping[str, object]) -> str:
    payload: dict[str, object] = {}
    for field_name in _PROVIDER_CORE_FIELDS:
        value = provider.get(field_name, "")
        if field_name == "base_url" and isinstance(value, str):
            value = mask_provider_base_url_for_display(value)
        payload[field_name] = value
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


_MODEL_PRICING_DYNAMIC_FIELDS: dict[str, Scalar] = {
    "pricing.input_per_million_usd": 0.0,
    "pricing.output_per_million_usd": 0.0,
    "pricing.request_per_call_usd": 0.0,
}
_KNOWN_TABLE_PATHS = (
    frozenset(
        tuple(key.split(".")[:index])
        for key in _FLAT_DEFAULTS
        for index in range(1, len(key.split(".")))
    )
    | frozenset(tuple(key.split(".")) for key in _MODEL_PRICING_DYNAMIC_FIELDS)
    | {("providers",)}
)


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    _validate_config_table_shapes(data)
    return data


def read_config_data(path: Path) -> dict[str, Any]:
    return _read_toml(path)


def _coerce_string_sequence(key: str, value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not _is_string_sequence(value):
        raise ConfigError(f"{key} must be an array of strings")
    return tuple(value)


def _render_scalar(value: Scalar) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in value) + "]"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_toml(data: Mapping[str, Any]) -> str:
    lines: list[str] = []
    _render_toml_mapping(lines, data, table_path=())
    return "\n".join(lines) + "\n"


def _render_toml_mapping(
    lines: list[str],
    data: Mapping[str, Any],
    *,
    table_path: tuple[str, ...],
) -> None:
    scalars = {key: value for key, value in data.items() if not isinstance(value, Mapping)}
    tables = {
        key: cast("Mapping[str, Any]", value)
        for key, value in data.items()
        if isinstance(value, Mapping)
    }

    if table_path:
        if lines:
            lines.append("")
        rendered_path = ".".join(_render_toml_key(part) for part in table_path)
        lines.append(f"[{rendered_path}]")

    for key, value in scalars.items():
        lines.append(f"{_render_toml_key(key)} = {_render_scalar(value)}")

    for key, value in tables.items():
        _render_toml_mapping(lines, value, table_path=(*table_path, key))


def _render_toml_key(key: str) -> str:
    if _TOML_BARE_KEY_PATTERN.fullmatch(key):
        return key
    return json.dumps(key, ensure_ascii=False)


def write_default_config(config_path: Path, *, overwrite: bool = False) -> Path:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists() and not overwrite:
        return config_path
    return write_config_data(config_path, DEFAULT_CONFIG)


def write_config_data(config_path: Path, data: Mapping[str, Any]) -> Path:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = _render_toml(data)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=config_path.parent,
        prefix=f"{config_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(rendered)
        temp_path = handle.name
    Path(temp_path).replace(config_path)
    return config_path


def _collect_env_overrides(env: Mapping[str, str]) -> dict[str, Scalar]:
    overrides: dict[str, Scalar] = {}
    for key, env_name in _ENV_KEY_MAP.items():
        if env_name in env:
            overrides[key] = _coerce_value(key, env[env_name], _FLAT_DEFAULTS[key])
    return overrides


def _normalize_cli_overrides(cli_overrides: Mapping[str, Any] | None) -> dict[str, Scalar]:
    if cli_overrides is None:
        return {}
    normalized: dict[str, Scalar] = {}
    for key, value in cli_overrides.items():
        if value is None:
            continue
        if key not in _FLAT_DEFAULTS:
            raise ConfigError(f"unsupported CLI override key: {key}")
        normalized[key] = _coerce_value(key, value, _FLAT_DEFAULTS[key])
    return normalized


def _path_expects_table(path: tuple[str, ...]) -> bool:
    if path in _KNOWN_TABLE_PATHS:
        return True
    return len(path) == 2 and path[0] == "providers"


def _expected_scalar_for_path(path: tuple[str, ...]) -> Scalar | None:
    dotted_key = ".".join(path)
    if dotted_key in _FLAT_DEFAULTS:
        return _FLAT_DEFAULTS[dotted_key]
    provider_field = _dynamic_provider_field(dotted_key)
    if provider_field is not None:
        return _DYNAMIC_PROVIDER_FIELD_DEFAULTS[provider_field]
    model_pricing_field = _dynamic_model_pricing_field(dotted_key)
    if model_pricing_field is not None:
        return _MODEL_PRICING_DYNAMIC_FIELDS[model_pricing_field]
    return None


def _validate_config_table_shapes(data: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> None:
    for key, value in data.items():
        path = (*prefix, key)
        dotted_key = ".".join(path)
        expected_scalar = _expected_scalar_for_path(path)
        if expected_scalar is not None and isinstance(value, Mapping):
            expected_type = _expected_type_name(expected_scalar)
            raise ConfigError(f"{dotted_key} expects {expected_type}, got table")
        if _path_expects_table(path) and not isinstance(value, Mapping):
            raise ConfigError(f"{dotted_key} expects table, got {_actual_type_name(value)}")
        if isinstance(value, Mapping):
            _validate_config_table_shapes(cast("Mapping[str, Any]", value), path)


def _coerce_config_file_value(key: str, value: Any, expected: Scalar) -> Scalar:
    return _coerce_value(key, value, expected, coerce_strings=False)


def _validate_provider_dynamic_field(key: str, field_name: str, value: Scalar) -> None:
    if field_name == "provider_class":
        provider_class = cast("str", value)
        if provider_class not in _SUPPORTED_PROVIDER_CLASSES:
            expected = ", ".join(sorted(_SUPPORTED_PROVIDER_CLASSES))
            raise ConfigError(f"{key} must be one of {expected}, got {provider_class!r}")
        return
    if field_name == "thinking_level":
        thinking_level = cast("str", value)
        if thinking_level and thinking_level not in _THINKING_LEVELS:
            allowed = ", ".join(sorted(_THINKING_LEVELS))
            raise ConfigError(f"{key} must be one of {allowed}, got {thinking_level!r}")
        return
    if field_name == "model_name":
        model_name = cast("str", value)
        if model_name.strip() == "":
            raise ConfigError(f"{key} expects non-empty str, got empty string")
        return
    if field_name != "base_url":
        return
    base_url = cast("str", value)
    parsed = urlsplit(base_url)
    if base_url.strip() == "" or any(char.isspace() for char in base_url):
        raise ConfigError(f"{key} expects valid URL, got {base_url!r}")
    if not parsed.scheme or not parsed.netloc:
        raise ConfigError(f"{key} expects valid URL, got {base_url!r}")
    if parsed.scheme not in ("http", "https"):
        raise ConfigError(f"{key} expects http or https URL, got {base_url!r}")


def _flatten_config_file(
    path: Path,
    *,
    validate_repo_provider_env: bool = False,
) -> tuple[dict[str, Scalar], dict[str, Scalar], tuple[str, ...]]:
    data = _read_toml(path)
    flattened = _flatten_mapping(data)
    unknown = tuple(sorted(key for key in flattened if not _is_supported_key(key)))
    normalized: dict[str, Scalar] = {}
    for key, value in flattened.items():
        if key in _FLAT_DEFAULTS:
            normalized[key] = _coerce_config_file_value(key, value, _FLAT_DEFAULTS[key])
            continue
        dynamic_field = _dynamic_provider_field(key)
        if dynamic_field is not None:
            coerced = _coerce_config_file_value(
                key,
                value,
                _DYNAMIC_PROVIDER_FIELD_DEFAULTS[dynamic_field],
            )
            _validate_provider_dynamic_field(key, dynamic_field, coerced)
            if (
                validate_repo_provider_env
                and dynamic_field == "api_key_env"
                and _ENV_VAR_NAME_PATTERN.fullmatch(str(coerced))
            ):
                validate_repo_api_key_env_name(str(coerced))
            normalized[key] = coerced
            continue
        model_pricing_field = _dynamic_model_pricing_field(key)
        if model_pricing_field is None:
            continue
        normalized[key] = _coerce_config_file_value(
            key,
            value,
            _MODEL_PRICING_DYNAMIC_FIELDS[model_pricing_field],
        )
    return flattened, normalized, unknown


def _is_supported_key(key: str) -> bool:
    if key in _FLAT_DEFAULTS:
        return True
    return _dynamic_provider_field(key) is not None or _dynamic_model_pricing_field(key) is not None


def _dynamic_provider_field(key: str) -> str | None:
    parts = key.split(".")
    if len(parts) < 3 or parts[0] != "providers":
        return None
    if any(part == "" for part in parts[1:-1]):
        return None
    field_name = parts[-1]
    if field_name not in _PROVIDER_DYNAMIC_FIELDS:
        return None
    return field_name


def _dynamic_model_pricing_field(key: str) -> str | None:
    for field_name in _MODEL_PRICING_DYNAMIC_FIELDS:
        prefix = f"{field_name}."
        if key.startswith(prefix) and key[len(prefix) :] != "":
            return field_name
    return None


_SENSITIVE_KEY_FALSE_POSITIVES = re.compile(
    r"(token_budget|token_limit|output_tokens|input_tokens|max_tokens)", re.IGNORECASE
)


def _is_sensitive_key(key: str, value: Scalar) -> bool:
    lowered = key.lower()
    if lowered.endswith("_env") or lowered.endswith("_env_var"):
        return False
    if _SENSITIVE_KEY_PATTERN.search(key) and not _SENSITIVE_KEY_FALSE_POSITIVES.search(key):
        return True
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)
    return False


def _repo_sensitive_keys(flattened: Mapping[str, Scalar]) -> tuple[str, ...]:
    return tuple(sorted(key for key, value in flattened.items() if _is_sensitive_key(key, value)))


def _layer_source_label(layer: str, key: str, repo_path: Path, global_path: Path) -> str:
    if layer == "env":
        return f"env:{_ENV_KEY_MAP[key]}"
    if layer == "cli":
        return "cli"
    if layer == "repo":
        return f"repo:{repo_path}"
    if layer == "global":
        return f"global:{global_path}"
    return "default"


def _resolve_config_root(repo_root: Path | None, *, allow_non_git: bool) -> Path:
    if allow_non_git:
        return find_workspace_root(repo_root)
    return find_repo_root(repo_root)


def _load_config_snapshot(
    root: Path,
    *,
    cli_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> ConfigSnapshot:
    env_map = os.environ if env is None else env
    repo_path = root / ".ahadiff" / "config.toml"
    global_path = global_config_dir(env=env_map) / "config.toml"

    repo_flattened, repo_values, repo_unknown = _flatten_config_file(
        repo_path,
        validate_repo_provider_env=True,
    )
    _, global_values, global_unknown = _flatten_config_file(global_path)
    cli_values = _normalize_cli_overrides(cli_overrides)
    env_values = _collect_env_overrides(env_map)

    layers: dict[str, dict[str, Scalar]] = {
        "env": env_values,
        "cli": cli_values,
        "repo": repo_values,
        "global": global_values,
        "default": dict(_FLAT_DEFAULTS),
    }

    resolved: dict[str, ResolvedSetting] = {}
    resolved_keys = sorted(set(_KNOWN_KEYS) | set(repo_values) | set(global_values))
    for key in resolved_keys:
        for layer_name in ("env", "cli", "repo", "global", "default"):
            layer_values = layers[layer_name]
            if key not in layer_values:
                continue
            source = _layer_source_label(layer_name, key, repo_path, global_path)
            resolved[key] = ResolvedSetting(key=key, value=layer_values[key], source=source)
            break

    precedence_conflicts: list[ConfigConflict] = []
    for key in resolved_keys:
        shadowed = [
            _layer_source_label(layer_name, key, repo_path, global_path)
            for layer_name in ("env", "cli", "repo", "global")
            if key in layers[layer_name]
        ]
        if len(shadowed) <= 1:
            continue
        precedence_conflicts.append(
            ConfigConflict(
                key=key,
                winner=resolved[key].source,
                shadowed=tuple(shadowed[1:]),
            )
        )

    values = _nest_mapping({key: item.value for key, item in resolved.items()})
    return ConfigSnapshot(
        values=values,
        resolved=resolved,
        repo_config_path=repo_path,
        global_config_path=global_path,
        repo_unknown_keys=repo_unknown,
        global_unknown_keys=global_unknown,
        repo_sensitive_keys=_repo_sensitive_keys(repo_flattened),
        precedence_conflicts=tuple(precedence_conflicts),
    )


def load_config(
    repo_root: Path | None = None,
    *,
    cli_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> ConfigSnapshot:
    root = _resolve_config_root(repo_root, allow_non_git=False)
    return _load_config_snapshot(root, cli_overrides=cli_overrides, env=env)


def load_workspace_config(
    workspace_root: Path,
    *,
    cli_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> ConfigSnapshot:
    root = _resolve_config_root(workspace_root, allow_non_git=True)
    return _load_config_snapshot(root, cli_overrides=cli_overrides, env=env)


def resolve_effective(
    key: str,
    *,
    snapshot: ConfigSnapshot | None = None,
    repo_root: Path | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedSetting:
    config_snapshot = snapshot or load_config(repo_root, cli_overrides=cli_overrides, env=env)
    try:
        return config_snapshot.resolved[key]
    except KeyError as exc:
        raise ConfigError(f"unknown config key: {key}") from exc


def iter_resolved_settings(snapshot: ConfigSnapshot) -> list[ResolvedSetting]:
    return [snapshot.resolved[key] for key in sorted(snapshot.resolved)]


def load_security_config(repo_root: Path | None = None) -> SecurityConfig:
    snapshot = load_config(repo_root)
    return _security_config_from_snapshot(snapshot)


def load_workspace_security_config(workspace_root: Path) -> SecurityConfig:
    snapshot = load_workspace_config(workspace_root)
    return _security_config_from_snapshot(snapshot)


def load_workspace_pricing_settings(
    workspace_root: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> PricingSettings:
    snapshot = load_workspace_config(workspace_root, env=env)
    pricing_mapping = cast("Mapping[str, Any]", snapshot.values.get("pricing", {}))
    repo_payload = read_config_data(snapshot.repo_config_path)
    global_payload = read_config_data(snapshot.global_config_path)

    global_input = _read_model_pricing_table(
        global_payload,
        table_name="input_per_million_usd",
        source_path=snapshot.global_config_path,
    )
    repo_input = _read_model_pricing_table(
        repo_payload,
        table_name="input_per_million_usd",
        source_path=snapshot.repo_config_path,
    )
    global_output = _read_model_pricing_table(
        global_payload,
        table_name="output_per_million_usd",
        source_path=snapshot.global_config_path,
    )
    repo_output = _read_model_pricing_table(
        repo_payload,
        table_name="output_per_million_usd",
        source_path=snapshot.repo_config_path,
    )
    global_request = _read_model_pricing_table(
        global_payload,
        table_name="request_per_call_usd",
        source_path=snapshot.global_config_path,
    )
    repo_request = _read_model_pricing_table(
        repo_payload,
        table_name="request_per_call_usd",
        source_path=snapshot.repo_config_path,
    )

    merged_input = {**global_input, **repo_input}
    merged_output = {**global_output, **repo_output}
    merged_request = {**global_request, **repo_request}
    model_overrides: dict[str, ModelPriceOverride] = {}

    for model_id in sorted(set(merged_input) | set(merged_output) | set(merged_request)):
        if model_id not in merged_input or model_id not in merged_output:
            raise ConfigError(
                "pricing override for "
                f"{model_id!r} requires both pricing.input_per_million_usd and "
                "pricing.output_per_million_usd"
            )
        model_overrides[model_id] = ModelPriceOverride(
            input_per_million_usd=merged_input[model_id],
            output_per_million_usd=merged_output[model_id],
            request_per_call_usd=merged_request.get(model_id),
        )

    return PricingSettings(
        openrouter_enabled=bool(
            pricing_mapping.get(
                "openrouter_enabled",
                DEFAULT_CONFIG["pricing"]["openrouter_enabled"],
            )
        ),
        openrouter_models_url=str(
            pricing_mapping.get(
                "openrouter_models_url",
                DEFAULT_CONFIG["pricing"]["openrouter_models_url"],
            )
        ),
        openrouter_refresh_seconds=int(
            pricing_mapping.get(
                "openrouter_refresh_seconds",
                DEFAULT_CONFIG["pricing"]["openrouter_refresh_seconds"],
            )
        ),
        model_overrides=model_overrides,
    )


def _security_config_from_snapshot(snapshot: ConfigSnapshot) -> SecurityConfig:
    security_mapping = cast("Mapping[str, Any]", snapshot.values.get("security", {}))
    local_hosts = _coerce_string_sequence(
        "security.local_hosts", security_mapping.get("local_hosts")
    )
    return SecurityConfig(
        allow_exact=_coerce_string_sequence(
            "security.allow_exact", security_mapping.get("allow_exact")
        ),
        allow_paths=_coerce_string_sequence(
            "security.allow_paths", security_mapping.get("allow_paths")
        ),
        suppress_rules=_coerce_string_sequence(
            "security.suppress_rules", security_mapping.get("suppress_rules")
        ),
        local_hosts=local_hosts,
        strict_local_hosts=_global_security_local_hosts(snapshot),
    )


def _global_security_local_hosts(snapshot: ConfigSnapshot) -> tuple[str, ...]:
    global_payload = read_config_data(snapshot.global_config_path)
    raw_security = global_payload.get("security", {})
    if raw_security == {}:
        return ()
    if not isinstance(raw_security, Mapping):
        raise ConfigError(f"{snapshot.global_config_path}: [security] must be a table")
    security_mapping = cast("Mapping[str, Any]", raw_security)
    return _coerce_string_sequence("security.local_hosts", security_mapping.get("local_hosts"))


def local_hosts_for_privacy_mode(
    security_config: SecurityConfig,
    privacy_mode: str,
) -> tuple[str, ...]:
    if privacy_mode == "strict_local":
        return security_config.strict_local_hosts
    return security_config.local_hosts


def validate_repo_api_key_env_name(value: str) -> None:
    if value in _SAFE_PROVIDER_API_KEY_ENVS:
        return
    if _AHADIFF_PROVIDER_API_KEY_ENV_PATTERN.fullmatch(value):
        return
    raise ConfigError(
        "repo provider api_key_env must start with AHADIFF_ or be one of: "
        + ", ".join(sorted(_SAFE_PROVIDER_API_KEY_ENVS))
    )


def resolve_provider_api_key(api_key_env: str) -> str | None:
    """Resolve API key from *api_key_env* value.

    Tries environment variable lookup first; falls back to the raw value
    so callers can store a direct API key instead of an env-var name.
    """
    if not api_key_env:
        return None
    env_value = os.environ.get(api_key_env)
    if env_value:
        return env_value
    return api_key_env


def _read_model_pricing_table(
    payload: Mapping[str, Any],
    *,
    table_name: str,
    source_path: Path,
) -> dict[str, float]:
    raw_pricing = payload.get("pricing", {})
    if raw_pricing == {}:
        return {}
    if not isinstance(raw_pricing, Mapping):
        raise ConfigError(f"{source_path}: [pricing] must be a table")
    pricing = cast("Mapping[str, Any]", raw_pricing)
    raw_table_value = pricing.get(table_name, {})
    if raw_table_value == {}:
        return {}
    if not isinstance(raw_table_value, Mapping):
        raise ConfigError(f"{source_path}: [pricing.{table_name}] must be a table")
    raw_table = cast("Mapping[str, Any]", raw_table_value)

    normalized: dict[str, float] = {}
    for model_id, value in raw_table.items():
        normalized[model_id] = cast(
            "float",
            _coerce_value(
                f"pricing.{table_name}.{model_id}",
                value,
                0.0,
            ),
        )
    return normalized


__all__ = [
    "DEFAULT_CONFIG",
    "PROVIDER_STALE_PROBE_FIELDS",
    "ConfigConflict",
    "ConfigSnapshot",
    "ModelPriceOverride",
    "PricingSettings",
    "ResolvedSetting",
    "SecurityConfig",
    "clear_provider_probe_fields",
    "iter_resolved_settings",
    "load_config",
    "read_config_data",
    "load_workspace_pricing_settings",
    "load_workspace_config",
    "load_security_config",
    "load_workspace_security_config",
    "local_hosts_for_privacy_mode",
    "mask_provider_base_url_for_display",
    "normalize_provider_base_url",
    "provider_core_fingerprint",
    "resolve_effective",
    "resolve_provider_api_key",
    "validate_provider_alias",
    "validate_provider_base_url",
    "validate_repo_api_key_env_name",
    "write_config_data",
    "write_default_config",
]
