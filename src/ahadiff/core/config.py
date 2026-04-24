from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeGuard, cast

from ahadiff.i18n import normalize_locale_preference

from .errors import ConfigError
from .paths import find_repo_root, find_workspace_root, global_config_dir

Scalar = str | int | float | bool | tuple[str, ...]
NestedConfig = dict[str, "Scalar | NestedConfig"]
_PRIVACY_MODES = {"strict_local", "redacted_remote", "explicit_remote"}
_LOCALE_PREFERENCE_KEYS = {"lang", "llm.prompt_lang", "llm.output_lang"}
DEFAULT_CONFIG: dict[str, Any] = {
    "lang": "auto",
    "privacy_mode": "strict_local",
    "capture": {
        "max_files": 50,
        "hard_limit": 5000,
        "max_patch_bytes": 10_000_000,
    },
    "llm": {
        "generate_model": "gpt-5.4-mini",
        "judge_model": "gpt-5.4-mini",
        "max_concurrent": 3,
        "request_timeout_seconds": 30,
        "retry_attempts": 3,
        "input_token_budget": 200_000,
        "output_token_budget": 50_000,
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


def _coerce_value(key: str, value: Any, expected: Scalar) -> Scalar:
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
    if isinstance(expected, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return _coerce_bool(value, key=key)
        raise ConfigError(f"{key} expects bool, got {type(value).__name__}")
    if isinstance(expected, tuple):
        if _is_string_sequence(value):
            return tuple(value)
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        raise ConfigError(f"{key} expects an array of strings, got {type(value).__name__}")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError as exc:
                raise ConfigError(f"{key} expects int, got {value!r}") from exc
        raise ConfigError(f"{key} expects int, got {type(value).__name__}")
    if isinstance(expected, float):
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError as exc:
                raise ConfigError(f"{key} expects float, got {value!r}") from exc
        raise ConfigError(f"{key} expects float, got {type(value).__name__}")
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
        "probed_max_context",
        "probed_tpm",
        "probed_rpm",
        "supports_temperature",
        "probe_timestamp",
    }
)
_DYNAMIC_PROVIDER_FIELD_DEFAULTS: dict[str, Scalar] = {
    "provider_class": "",
    "model_name": "",
    "base_url": "",
    "api_key_env": "",
    "probed_max_context": 0,
    "probed_tpm": 0,
    "probed_rpm": 0,
    "supports_temperature": False,
    "probe_timestamp": "",
}
_MODEL_PRICING_DYNAMIC_FIELDS: dict[str, Scalar] = {
    "pricing.input_per_million_usd": 0.0,
    "pricing.output_per_million_usd": 0.0,
    "pricing.request_per_call_usd": 0.0,
}


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


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


def _flatten_config_file(
    path: Path,
) -> tuple[dict[str, Scalar], dict[str, Scalar], tuple[str, ...]]:
    data = _read_toml(path)
    flattened = _flatten_mapping(data)
    unknown = tuple(sorted(key for key in flattened if not _is_supported_key(key)))
    normalized: dict[str, Scalar] = {}
    for key, value in flattened.items():
        if key in _FLAT_DEFAULTS:
            normalized[key] = _coerce_value(key, value, _FLAT_DEFAULTS[key])
            continue
        dynamic_field = _dynamic_provider_field(key)
        if dynamic_field is not None:
            normalized[key] = _coerce_value(
                key,
                value,
                _DYNAMIC_PROVIDER_FIELD_DEFAULTS[dynamic_field],
            )
            continue
        model_pricing_field = _dynamic_model_pricing_field(key)
        if model_pricing_field is None:
            continue
        normalized[key] = _coerce_value(
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


def _is_sensitive_key(key: str, value: Scalar) -> bool:
    lowered = key.lower()
    if lowered.endswith("_env") or lowered.endswith("_env_var"):
        return False
    if _SENSITIVE_KEY_PATTERN.search(key):
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

    repo_flattened, repo_values, repo_unknown = _flatten_config_file(repo_path)
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
        local_hosts=_coerce_string_sequence(
            "security.local_hosts", security_mapping.get("local_hosts")
        ),
    )


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
    "ConfigConflict",
    "ConfigSnapshot",
    "ModelPriceOverride",
    "PricingSettings",
    "ResolvedSetting",
    "SecurityConfig",
    "iter_resolved_settings",
    "load_config",
    "read_config_data",
    "load_workspace_pricing_settings",
    "load_workspace_config",
    "load_security_config",
    "load_workspace_security_config",
    "resolve_effective",
    "write_config_data",
    "write_default_config",
]
