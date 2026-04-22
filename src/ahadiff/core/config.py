from __future__ import annotations

import json
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeGuard, cast

if TYPE_CHECKING:
    from pathlib import Path

from .errors import ConfigError
from .paths import find_repo_root, global_config_dir, repo_config_path

Scalar = str | int | float | bool | tuple[str, ...]
NestedConfig = dict[str, "Scalar | NestedConfig"]
_PRIVACY_MODES = {"strict_local", "redacted_remote", "explicit_remote"}
_SECURITY_KEYS = frozenset({"allow_exact", "allow_paths", "suppress_rules"})

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
    },
}

_SENSITIVE_KEY_PATTERN = re.compile(r"(api_key|secret|password|token)", re.IGNORECASE)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{12,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
)


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
    if not isinstance(_FLAT_DEFAULTS[key], tuple)
}


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


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
    scalars = {key: value for key, value in data.items() if not isinstance(value, Mapping)}
    tables = {
        key: cast("Mapping[str, Any]", value)
        for key, value in data.items()
        if isinstance(value, Mapping)
    }

    for key, value in scalars.items():
        lines.append(f"{key} = {_render_scalar(value)}")

    for key, value in tables.items():
        if lines:
            lines.append("")
        lines.append(f"[{key}]")
        for child_key, child_value in value.items():
            if isinstance(child_value, Mapping):
                raise ConfigError("nested tables deeper than one level are not supported yet")
            lines.append(f"{child_key} = {_render_scalar(child_value)}")

    return "\n".join(lines) + "\n"


def write_default_config(config_path: Path, *, overwrite: bool = False) -> Path:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists() and not overwrite:
        return config_path
    config_path.write_text(_render_toml(DEFAULT_CONFIG), encoding="utf-8")
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
    unknown = tuple(sorted(key for key in flattened if key not in _FLAT_DEFAULTS))
    normalized: dict[str, Scalar] = {}
    for key, value in flattened.items():
        if key not in _FLAT_DEFAULTS:
            continue
        normalized[key] = _coerce_value(key, value, _FLAT_DEFAULTS[key])
    return flattened, normalized, unknown


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


def load_config(
    repo_root: Path | None = None,
    *,
    cli_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> ConfigSnapshot:
    env_map = os.environ if env is None else env
    root = find_repo_root(repo_root)
    repo_path = repo_config_path(root)
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
    for key in _KNOWN_KEYS:
        for layer_name in ("env", "cli", "repo", "global", "default"):
            layer_values = layers[layer_name]
            if key not in layer_values:
                continue
            source = _layer_source_label(layer_name, key, repo_path, global_path)
            resolved[key] = ResolvedSetting(key=key, value=layer_values[key], source=source)
            break

    precedence_conflicts: list[ConfigConflict] = []
    for key in _KNOWN_KEYS:
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
    root = find_repo_root(repo_root)
    config_path = repo_config_path(root)
    if not config_path.exists():
        return SecurityConfig()

    data = _read_toml(config_path)
    security = data.get("security", {})
    if security == {}:
        return SecurityConfig()
    if not isinstance(security, Mapping):
        raise ConfigError("[security] must be a TOML table")

    security_mapping = cast("Mapping[str, Any]", security)
    unknown = sorted(set(security_mapping) - _SECURITY_KEYS)
    if unknown:
        raise ConfigError(f"unsupported [security] keys: {', '.join(unknown)}")

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
    )


__all__ = [
    "DEFAULT_CONFIG",
    "ConfigConflict",
    "ConfigSnapshot",
    "ResolvedSetting",
    "SecurityConfig",
    "iter_resolved_settings",
    "load_config",
    "load_security_config",
    "resolve_effective",
    "write_default_config",
]
