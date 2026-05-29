"""POST/PUT/DELETE /api/providers and /api/providers/{alias}/probe endpoints.

CRUD operations on the per-repo ``[providers.<alias>]`` table inside
``.ahadiff/config.toml``.  Probe submits an async ``provider_probe:<alias>``
task to the ``TaskRunner`` and persists probe metadata only if the provider
core fields did not change while the probe was running.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import httpx
from anyio import to_thread
from pydantic import ValidationError
from starlette.responses import JSONResponse

from ahadiff.contracts import ErrorCode
from ahadiff.contracts.run_source import ProviderConfig
from ahadiff.contracts.serve_providers import (
    ModelLimitsPreviewRequest,
    ModelLimitsResponse,
    ProviderCreateRequest,
    ProviderDeleteResponse,
    ProviderMutationResponse,
    ProviderProbeSubmitResponse,
    ProviderUpdateRequest,
)
from ahadiff.core import config as config_module
from ahadiff.core.config import (
    SecurityConfig,
    clear_provider_probe_fields,
    local_hosts_for_privacy_mode,
    mask_provider_base_url_for_display,
    normalize_provider_base_url,
    provider_core_fingerprint,
    read_config_data,
    resolve_provider_api_key,
    validate_provider_alias,
    validate_provider_base_url,
    validate_repo_api_key_env_name,
    write_config_data,
)
from ahadiff.core.errors import ConfigError, ProviderError, SafetyError
from ahadiff.core.ids import make_event_id
from ahadiff.core.task_runner import TaskStatus
from ahadiff.llm import provider as provider_module
from ahadiff.llm.adapters.thinking import thinking_policy_for
from ahadiff.llm.cost import resolve_model_limits
from ahadiff.llm.probe import probe_provider
from ahadiff.safety.audit import append_audit_record

from ._errors import error_response
from .auth import require_write_token, serve_state
from .lock import serve_repo_write_lock
from .routes_stats import provider_summary_from_mapping

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from ahadiff.core.task_runner import TaskHandle
    from ahadiff.llm.schemas import ProbeReport

    from .state import ServeState


_CORE_FIELDS = ("provider_class", "model_name", "base_url", "api_key_env")
_LIMIT_IDENTITY_FIELDS = (*_CORE_FIELDS, "model_limits_name")
_PROBE_RESULT_FIELDS = (
    "probed_max_context",
    "probed_max_input_tokens",
    "probed_max_output_tokens",
    "probed_limits_source",
    "probed_tpm",
    "probed_rpm",
    "probe_timestamp",
)
_MAX_PENDING_PROVIDER_PROBE_TASKS = 1
_MAX_GLOBAL_PENDING_PROBE_TASKS = 3
_MODEL_DISCOVERY_RESPONSE_BYTE_CAP = 1_048_576
_MODEL_DISCOVERY_TIMEOUT_SECONDS = 5.0
_UNTRUSTED_CLAMP_POLICIES = {"route_specific", "local_runtime"}


class _ProviderBaseUrlError(Exception):
    pass


class _ProviderFieldError(Exception):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_path(state: ServeState) -> Path:
    """Return the path to the per-repo ``.ahadiff/config.toml``."""
    return state.state_dir.parent / ".ahadiff" / "config.toml"


def _read_providers_table(config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(full_data, providers_table)``; both are mutable dict copies."""
    data: dict[str, Any] = read_config_data(config_path) if config_path.exists() else {}
    raw_providers = data.get("providers")
    if raw_providers is None:
        providers: dict[str, Any] = {}
        data["providers"] = providers
        return data, providers
    if not isinstance(raw_providers, dict):
        raise ConfigError("config key [providers] must be a table")
    providers = cast("dict[str, Any]", raw_providers)
    return data, providers


def _build_summary(
    state: ServeState,
    alias: str,
    provider_data: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a JSON-ready ProviderSummary dict via the canonical helper."""
    del state  # unused; ServeState is accepted for symmetry with other helpers
    raw_role = provider_data.get("role")
    role = str(raw_role) if isinstance(raw_role, str) and raw_role else None
    summary = provider_summary_from_mapping(alias, provider_data, role=role)
    if summary is None:
        return None
    return summary.model_dump(mode="json")


def _clean_optional_provider_text(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise _ProviderFieldError(f"{field_name} must be a non-empty string")
    return stripped


def _validate_provider_api_key_env(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _ProviderFieldError("api_key_env must be a non-empty string")
    try:
        validate_repo_api_key_env_name(value)
    except ConfigError as exc:
        raise _ProviderFieldError(f"api_key_env: {exc}") from exc
    return value


def _error(message: str, *, status: int) -> JSONResponse:
    code = ErrorCode.INPUT_BAD_FIELD
    if status == 404:
        code = (
            ErrorCode.PROVIDER_NOT_FOUND if message == "provider_not_found" else ErrorCode.NOT_FOUND
        )
    elif status >= 500:
        code = ErrorCode.INTERNAL_ERROR
    return error_response(code, message, status=status)


def _provider_base_url_error(prefix: str, base_url: str) -> str:
    safe_base_url = config_module._safe_url_repr(base_url)  # pyright: ignore[reportPrivateUsage]
    if safe_base_url == base_url.strip():
        return prefix
    return f"{prefix}: {safe_base_url}"


def _validation_error(exc: ValidationError, *, status: int = 422) -> JSONResponse:
    return error_response(
        ErrorCode.INPUT_VALIDATION,
        "validation_error",
        status=status,
        details={"errors": exc.errors(include_context=False, include_input=False)},
    )


def _invalid_alias_response(alias: str) -> JSONResponse | None:
    try:
        validate_provider_alias(alias)
    except ConfigError:
        return _error("invalid_alias", status=400)
    return None


def _provider_allowed_local_hosts(data: Mapping[str, object]) -> tuple[str, ...]:
    security_obj = data.get("security")
    if not isinstance(security_obj, Mapping):
        return ()
    security = cast("Mapping[str, object]", security_obj)
    hosts: list[str] = []
    for key in ("local_hosts", "strict_local_hosts"):
        raw_hosts = security.get(key)
        if isinstance(raw_hosts, list | tuple):
            host_items = cast("list[object] | tuple[object, ...]", raw_hosts)
            hosts.extend(item for item in host_items if isinstance(item, str))
    return tuple(hosts)


def _security_string_tuple(security: Mapping[str, object], key: str) -> tuple[str, ...]:
    raw_value = security.get(key)
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list | tuple):
        raise ConfigError(f"security.{key} must be an array of strings")
    items = cast("list[object] | tuple[object, ...]", raw_value)
    if not all(isinstance(item, str) for item in items):
        raise ConfigError(f"security.{key} must be an array of strings")
    return tuple(cast("tuple[str, ...]", tuple(items)))


def _security_config_from_data(data: Mapping[str, object]) -> SecurityConfig:
    raw_security = data.get("security", {})
    if raw_security is None:
        return SecurityConfig()
    if not isinstance(raw_security, Mapping):
        raise ConfigError("config key [security] must be a table")
    security = cast("Mapping[str, object]", raw_security)
    return SecurityConfig(
        allow_exact=_security_string_tuple(security, "allow_exact"),
        allow_paths=_security_string_tuple(security, "allow_paths"),
        suppress_rules=_security_string_tuple(security, "suppress_rules"),
        local_hosts=_security_string_tuple(security, "local_hosts"),
        strict_local_hosts=_security_string_tuple(security, "strict_local_hosts"),
    )


_DEFAULT_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _normalize_and_validate_base_url(
    base_url: str,
    *,
    provider_class: str,
    data: Mapping[str, object],
) -> str:
    normalized = normalize_provider_base_url(base_url, provider_class=provider_class)
    try:
        validate_provider_base_url(
            normalized,
            allowed_local_hosts=(
                *_provider_allowed_local_hosts(data),
                *_DEFAULT_LOCAL_HOSTS,
            ),
        )
    except ConfigError as exc:
        raise _ProviderBaseUrlError(str(exc)) from exc
    return normalized


def _append_provider_audit_event(
    state: ServeState,
    *,
    event_type: str,
    alias: str,
    provider_data: Mapping[str, Any],
) -> None:
    record = {
        "event_id": make_event_id(),
        "schema_version": 1,
        "event_type": event_type,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "alias": alias,
        "provider_class": str(provider_data.get("provider_class") or ""),
        "model_name": str(provider_data.get("model_name") or ""),
        "base_url": mask_provider_base_url_for_display(str(provider_data.get("base_url") or "")),
    }
    append_audit_record(state.state_dir / "audit.jsonl", record)


def _provider_required_str(provider_data: Mapping[str, Any], field_name: str) -> str:
    value = provider_data.get(field_name)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"provider {field_name} must be a non-empty string")
    return value


def _provider_optional_str(provider_data: Mapping[str, Any], field_name: str) -> str | None:
    value = provider_data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"provider {field_name} must be a non-empty string")
    return value


def _provider_config_for_limits(provider_data: Mapping[str, Any]) -> ProviderConfig:
    payload: dict[str, object] = {
        "provider_class": provider_data.get("provider_class"),
        "model_name": provider_data.get("model_name"),
        "base_url": provider_data.get("base_url") or "http://127.0.0.1",
        "api_key_env": provider_data.get("api_key_env") or "AHADIFF_PROVIDER_API_KEY",
    }
    for field_name in (
        "max_output_tokens",
        "thinking_level",
        "probed_max_context",
        "probed_tpm",
        "probed_rpm",
        "probed_max_input_tokens",
        "probed_max_output_tokens",
        "probed_limits_source",
        "model_limits_name",
        "probe_timestamp",
    ):
        value = provider_data.get(field_name)
        if value is not None:
            payload[field_name] = value
    return ProviderConfig.model_validate(payload)


def _append_limit_warning(
    warnings: list[dict[str, object]],
    code: str,
    *,
    params: dict[str, object] | None = None,
) -> None:
    warning: dict[str, object] = {"code": code}
    if params:
        warning["params"] = params
    if warning not in warnings:
        warnings.append(warning)


def _structured_limit_warnings(
    *,
    context_policy: str | None,
    confidence: str | None,
    max_context_known: bool,
    max_input_known: bool,
    max_output_known: bool,
    raw_warnings: tuple[str, ...],
) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    if not max_context_known or not max_input_known or not max_output_known:
        _append_limit_warning(
            warnings,
            "provider_limits.default_fallback",
            params={
                "max_context_known": max_context_known,
                "max_input_known": max_input_known,
                "max_output_known": max_output_known,
            },
        )
    if context_policy == "local_runtime":
        _append_limit_warning(warnings, "provider_limits.local_runtime")
    if context_policy == "route_specific":
        _append_limit_warning(warnings, "provider_limits.route_specific")
    if confidence == "low":
        _append_limit_warning(warnings, "provider_limits.low_confidence")
    for _raw_warning in raw_warnings:
        _append_limit_warning(warnings, "provider_limits.registry_warning")
    return warnings


def _public_limit_value(value: int | None, *, known: bool) -> int | None:
    if not known:
        return None
    return value


def _thinking_metadata(provider_class: str, model_name: str) -> dict[str, object]:
    policy = thinking_policy_for(provider_class, model_name)
    supported = bool(policy["supported"])
    return {
        **policy,
        "supported": supported,
    }


def build_model_limits_response(
    *,
    alias: str | None,
    provider_data: Mapping[str, Any],
    model_name_override: str | None = None,
) -> ModelLimitsResponse | None:
    provider_snapshot = dict(provider_data)
    if model_name_override is not None and model_name_override.strip():
        provider_snapshot["model_name"] = model_name_override.strip()
        provider_snapshot.pop("model_limits_name", None)
    try:
        config = _provider_config_for_limits(provider_snapshot)
    except ValidationError:
        return None
    limits = resolve_model_limits(
        config.provider_class,
        config.model_name,
        config,
    )
    return ModelLimitsResponse(
        alias=alias,
        provider_class=config.provider_class,
        model_name=config.model_name,
        max_context_tokens=_public_limit_value(
            limits.max_context_tokens,
            known=limits.max_context_known,
        ),
        max_input_tokens=_public_limit_value(
            limits.max_input_tokens,
            known=limits.max_input_known,
        ),
        max_output_tokens=_public_limit_value(
            limits.max_output_tokens,
            known=limits.max_output_known,
        ),
        max_context_known=limits.max_context_known,
        max_input_known=limits.max_input_known,
        max_output_known=limits.max_output_known,
        context_policy=cast("Any", limits.context_policy),
        source=limits.source,
        confidence=cast("Any", limits.confidence),
        warnings=_structured_limit_warnings(
            context_policy=limits.context_policy,
            confidence=limits.confidence,
            max_context_known=limits.max_context_known,
            max_input_known=limits.max_input_known,
            max_output_known=limits.max_output_known,
            raw_warnings=limits.warnings,
        ),
        thinking=_thinking_metadata(config.provider_class, config.model_name),
    )


def _trusted_max_output_limit(limits: Any) -> int | None:
    if not limits.max_output_known:
        return None
    if limits.max_output_tokens is None:
        return None
    if limits.context_policy in _UNTRUSTED_CLAMP_POLICIES:
        return None
    if limits.confidence == "low":
        return None
    return int(limits.max_output_tokens)


def _apply_max_output_policy(provider_data: dict[str, Any]) -> list[dict[str, object]]:
    requested = provider_data.get("max_output_tokens")
    if requested is None:
        return []
    if isinstance(requested, bool) or not isinstance(requested, int):
        return []
    try:
        config = _provider_config_for_limits(provider_data)
    except ValidationError:
        return []
    limits = resolve_model_limits(config.provider_class, config.model_name, config)
    trusted_limit = _trusted_max_output_limit(limits)
    if trusted_limit is not None:
        if requested <= trusted_limit:
            return []
        provider_data["max_output_tokens"] = trusted_limit
        return [
            {
                "code": "provider_limits.max_output_clamped",
                "params": {
                    "requested": requested,
                    "clamped_to": trusted_limit,
                    "source": limits.output_source,
                    "max_output_known": limits.max_output_known,
                },
            }
        ]
    return [
        {
            "code": "provider_limits.unverified_override",
            "params": {
                "requested": requested,
                "source": limits.output_source,
                "max_output_known": limits.max_output_known,
                "context_policy": limits.context_policy,
                "confidence": limits.confidence,
            },
        }
    ]


def _probe_report_result(
    *,
    alias: str,
    report: ProbeReport,
    persisted: bool,
    stale: bool,
) -> dict[str, Any]:
    rate_limits = asdict(report.rate_limits) if report.rate_limits is not None else None
    notes = list(report.notes)
    if stale:
        notes.append("provider config changed before probe results could be persisted")
    return {
        "alias": alias,
        "provider_name": report.provider_name,
        "connectivity_ok": report.connectivity_ok,
        "transport_target": report.transport_target,
        "context_window_source": report.context_window_source,
        "config": report.config.model_dump(mode="json"),
        "capabilities": report.capabilities.model_dump(mode="json"),
        "rate_limits": rate_limits,
        "notes": notes,
        "persisted": persisted,
        "stale": stale,
    }


def _provider_probe_failed_result(alias: str) -> dict[str, Any]:
    return {
        "alias": alias,
        "connectivity_ok": False,
        "error_code": "provider_probe_failed",
        "error": "provider probe failed",
        "persisted": False,
        "stale": False,
        "notes": ["provider probe failed"],
    }


def _persist_probe_result_if_current(
    *,
    state: ServeState,
    config_path: Path,
    alias: str,
    expected_fingerprint: str,
    report: ProbeReport,
) -> bool:
    with serve_repo_write_lock(state, command="serve provider probe persist"):
        data, providers = _read_providers_table(config_path)
        current = providers.get(alias)
        if not isinstance(current, dict):
            return False
        current_typed = cast("dict[str, Any]", current)
        if provider_core_fingerprint(current_typed) != expected_fingerprint:
            return False

        updated_provider = dict(current_typed)
        clear_provider_probe_fields(updated_provider)
        for field_name in _PROBE_RESULT_FIELDS:
            value = getattr(report.config, field_name)
            if value is not None:
                updated_provider[field_name] = value
        providers[alias] = updated_provider
        write_config_data(config_path, data)
        _append_provider_audit_event(
            state,
            event_type="provider_probe",
            alias=alias,
            provider_data=updated_provider,
        )
        return True


# ---------------------------------------------------------------------------
# POST /api/providers
# ---------------------------------------------------------------------------


async def create_provider(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)

    try:
        raw_payload = cast("object", await request.json())
    except Exception:
        return _error("invalid_json", status=400)
    if not isinstance(raw_payload, dict):
        return _error("body_must_be_object", status=400)
    payload = cast("dict[str, object]", raw_payload)
    raw_alias = payload.get("alias")
    if isinstance(raw_alias, str):
        alias_error = _invalid_alias_response(raw_alias)
        if alias_error is not None:
            return alias_error

    try:
        body = ProviderCreateRequest.model_validate(payload)
    except ValidationError as exc:
        return _validation_error(exc)
    try:
        model_limits_name = _clean_optional_provider_text(
            body.model_limits_name,
            field_name="model_limits_name",
        )
        api_key_env = _validate_provider_api_key_env(body.api_key_env)
    except _ProviderFieldError as exc:
        return _error(str(exc), status=422)

    config_path = _config_path(state)

    def _persist() -> tuple[bool, dict[str, Any] | None, list[dict[str, object]]]:
        with serve_repo_write_lock(state, command="serve provider create"):
            data, providers = _read_providers_table(config_path)
            if body.alias in providers:
                return False, None, []
            normalized_base_url = _normalize_and_validate_base_url(
                body.base_url,
                provider_class=body.provider_class,
                data=data,
            )
            new_provider: dict[str, Any] = {
                "provider_class": body.provider_class,
                "model_name": body.model_name,
                "base_url": normalized_base_url,
                "api_key_env": api_key_env,
            }
            if body.max_output_tokens is not None:
                new_provider["max_output_tokens"] = body.max_output_tokens
            if body.thinking_level is not None:
                new_provider["thinking_level"] = body.thinking_level
            if model_limits_name is not None:
                new_provider["model_limits_name"] = model_limits_name
            warnings = _apply_max_output_policy(new_provider)
            providers[body.alias] = new_provider
            write_config_data(config_path, data)
            _append_provider_audit_event(
                state,
                event_type="provider_create",
                alias=body.alias,
                provider_data=new_provider,
            )
            return True, dict(new_provider), warnings

    try:
        created, persisted, warnings = await to_thread.run_sync(_persist)
    except _ProviderBaseUrlError as exc:
        return _error(f"base_url: {exc}", status=422)
    except _ProviderFieldError as exc:
        return _error(str(exc), status=422)
    except ConfigError as exc:
        return _error(str(exc), status=500)
    if not created or persisted is None:
        return _error("provider_alias_conflict", status=409)

    summary = _build_summary(state, body.alias, persisted)
    if summary is None:
        return _error("provider_summary_unavailable", status=500)
    return JSONResponse(
        ProviderMutationResponse.model_validate(
            {"updated": True, "provider": summary, "warnings": warnings}
        ).model_dump(mode="json"),
        status_code=201,
    )


# ---------------------------------------------------------------------------
# GET /api/providers/{alias}/model-limits
# POST /api/providers/model-limits/preview
# ---------------------------------------------------------------------------


async def get_provider_model_limits(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    alias = str(request.path_params.get("alias", ""))
    if not alias:
        return _error("alias_required", status=422)
    alias_error = _invalid_alias_response(alias)
    if alias_error is not None:
        return alias_error

    config_path = _config_path(state)

    def _load_provider() -> dict[str, Any] | None:
        _data, providers = _read_providers_table(config_path)
        raw_provider = providers.get(alias)
        if not isinstance(raw_provider, dict):
            return None
        return dict(cast("dict[str, Any]", raw_provider))

    try:
        provider_data = await to_thread.run_sync(_load_provider)
    except ConfigError as exc:
        return _error(str(exc), status=500)
    if provider_data is None:
        return _error("provider_not_found", status=404)

    response = build_model_limits_response(alias=alias, provider_data=provider_data)
    if response is None:
        return _error("provider_limits_unavailable", status=500)
    return JSONResponse(response.model_dump(mode="json"))


async def preview_provider_model_limits(request: Request) -> JSONResponse:
    require_write_token(request)
    try:
        raw_payload = cast("object", await request.json())
    except Exception:
        return _error("invalid_json", status=400)
    if not isinstance(raw_payload, dict):
        return _error("body_must_be_object", status=400)
    try:
        body = ModelLimitsPreviewRequest.model_validate(raw_payload)
    except ValidationError as exc:
        return _validation_error(exc)
    try:
        model_limits_name = _clean_optional_provider_text(
            body.model_limits_name,
            field_name="model_limits_name",
        )
    except _ProviderFieldError as exc:
        return _error(str(exc), status=422)

    provider_data: dict[str, Any] = {
        "provider_class": body.provider_class,
        "model_name": body.model_name,
    }
    if model_limits_name is not None:
        provider_data["model_limits_name"] = model_limits_name
    response = build_model_limits_response(alias=None, provider_data=provider_data)
    if response is None:
        return _error("provider_limits_unavailable", status=500)
    return JSONResponse(response.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# PUT /api/providers/{alias}
# ---------------------------------------------------------------------------


async def update_provider(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    alias = str(request.path_params.get("alias", ""))
    if not alias:
        return _error("alias_required", status=422)
    alias_error = _invalid_alias_response(alias)
    if alias_error is not None:
        return alias_error

    try:
        raw_payload = cast("object", await request.json())
    except Exception:
        return _error("invalid_json", status=400)
    if not isinstance(raw_payload, dict):
        return _error("body_must_be_object", status=400)

    try:
        body = ProviderUpdateRequest.model_validate(raw_payload)
    except ValidationError as exc:
        return _validation_error(exc)

    fields_set = set(body.model_fields_set)
    update_payload = body.model_dump(exclude_none=True)
    if "model_limits_name" in update_payload:
        try:
            update_payload["model_limits_name"] = _clean_optional_provider_text(
                cast("str", update_payload["model_limits_name"]),
                field_name="model_limits_name",
            )
        except _ProviderFieldError as exc:
            return _error(str(exc), status=422)
    clear_fields: set[str] = set()
    if "max_output_tokens" in fields_set and body.max_output_tokens is None:
        clear_fields.add("max_output_tokens")
    if "model_limits_name" in fields_set and body.model_limits_name is None:
        clear_fields.add("model_limits_name")
    masked_key = update_payload.get("api_key_env")
    if isinstance(masked_key, str) and "****" in masked_key:
        del update_payload["api_key_env"]
    elif "api_key_env" in update_payload:
        try:
            update_payload["api_key_env"] = _validate_provider_api_key_env(
                update_payload["api_key_env"]
            )
        except _ProviderFieldError as exc:
            return _error(str(exc), status=422)
    if not update_payload and not clear_fields:
        return _error("at_least_one_field_required", status=422)

    config_path = _config_path(state)

    def _persist() -> tuple[bool, dict[str, Any] | None, list[dict[str, object]]]:
        with serve_repo_write_lock(state, command="serve provider update"):
            data, providers = _read_providers_table(config_path)
            existing = providers.get(alias)
            if not isinstance(existing, dict):
                return False, None, []
            existing_typed = cast("dict[str, Any]", existing)
            updated_provider: dict[str, Any] = dict(existing_typed)
            safe_update = {
                k: v
                for k, v in update_payload.items()
                if not (k == "api_key_env" and isinstance(v, str) and "****" in v)
            }
            updated_provider.update(safe_update)
            for field_name in clear_fields:
                updated_provider.pop(field_name, None)
            updated_provider["api_key_env"] = _validate_provider_api_key_env(
                updated_provider.get("api_key_env")
            )
            # Recompute base_url normalization if either base_url or
            # provider_class changed (so suffix stripping stays aligned).
            if "base_url" in update_payload or "provider_class" in update_payload:
                provider_class = str(updated_provider.get("provider_class", ""))
                base_url = str(updated_provider.get("base_url", ""))
                if base_url:
                    updated_provider["base_url"] = _normalize_and_validate_base_url(
                        base_url,
                        provider_class=provider_class,
                        data=data,
                    )
            # Clear stale probe results when the provider identity or registry
            # model override changes; old live probe limits belong to the old identity.
            limit_identity_changed = any(
                field in update_payload or field in clear_fields for field in _LIMIT_IDENTITY_FIELDS
            )
            if limit_identity_changed:
                clear_provider_probe_fields(updated_provider)
            warnings = _apply_max_output_policy(updated_provider)
            providers[alias] = updated_provider
            write_config_data(config_path, data)
            _append_provider_audit_event(
                state,
                event_type="provider_update",
                alias=alias,
                provider_data=updated_provider,
            )
            return True, dict(updated_provider), warnings

    try:
        updated, persisted, warnings = await to_thread.run_sync(_persist)
    except _ProviderBaseUrlError as exc:
        return _error(f"base_url: {exc}", status=422)
    except _ProviderFieldError as exc:
        return _error(str(exc), status=422)
    except ConfigError as exc:
        return _error(str(exc), status=500)
    if not updated or persisted is None:
        return _error("provider_not_found", status=404)

    summary = _build_summary(state, alias, persisted)
    if summary is None:
        return _error("provider_summary_unavailable", status=500)
    return JSONResponse(
        ProviderMutationResponse.model_validate(
            {"updated": True, "provider": summary, "warnings": warnings}
        ).model_dump(mode="json")
    )


# ---------------------------------------------------------------------------
# DELETE /api/providers/{alias}
# ---------------------------------------------------------------------------


async def delete_provider(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    alias = str(request.path_params.get("alias", ""))
    if not alias:
        return _error("alias_required", status=422)
    alias_error = _invalid_alias_response(alias)
    if alias_error is not None:
        return alias_error

    config_path = _config_path(state)

    def _persist() -> tuple[bool, dict[str, Any] | None]:
        with serve_repo_write_lock(state, command="serve provider delete"):
            data, providers = _read_providers_table(config_path)
            existing = providers.get(alias)
            if not isinstance(existing, dict):
                return False, None
            existing_typed = cast("dict[str, Any]", existing)
            providers.pop(alias)
            write_config_data(config_path, data)
            _append_provider_audit_event(
                state,
                event_type="provider_delete",
                alias=alias,
                provider_data=existing_typed,
            )
            return True, dict(existing_typed)

    try:
        deleted, _persisted = await to_thread.run_sync(_persist)
    except ConfigError as exc:
        return _error(str(exc), status=500)
    if not deleted:
        return _error("provider_not_found", status=404)

    return JSONResponse(
        ProviderDeleteResponse.model_validate({"deleted": True, "alias": alias}).model_dump(
            mode="json"
        )
    )


# ---------------------------------------------------------------------------
# POST /api/providers/{alias}/probe
# ---------------------------------------------------------------------------


async def probe_provider_route(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    alias = str(request.path_params.get("alias", ""))
    if not alias:
        return _error("alias_required", status=422)
    alias_error = _invalid_alias_response(alias)
    if alias_error is not None:
        return alias_error

    runner = state.task_runner
    if runner is None:
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            "task_runner_unavailable",
            status=503,
        )

    config_path = _config_path(state)

    def _load_provider() -> tuple[dict[str, Any], SecurityConfig] | None:
        data, providers = _read_providers_table(config_path)
        candidate = providers.get(alias)
        if not isinstance(candidate, dict):
            return None
        candidate_typed = cast("dict[str, Any]", candidate)
        return dict(candidate_typed), _security_config_from_data(data)

    try:
        loaded = await to_thread.run_sync(_load_provider)
    except ConfigError as exc:
        return _error(str(exc), status=500)
    if loaded is None:
        return _error("provider_not_found", status=404)

    provider_snapshot, security_config = loaded
    try:
        _validate_provider_api_key_env(provider_snapshot.get("api_key_env"))
    except _ProviderFieldError as exc:
        return _error(str(exc), status=422)
    start_fingerprint = provider_core_fingerprint(provider_snapshot)
    workspace_root = state.state_dir.parent

    async def _probe_task(_handle: TaskHandle) -> dict[str, Any]:
        try:
            provider_class = _provider_required_str(provider_snapshot, "provider_class")
            model_name = _provider_required_str(provider_snapshot, "model_name")
            model_limits_name = _provider_optional_str(provider_snapshot, "model_limits_name")
            base_url = _provider_required_str(provider_snapshot, "base_url")
            api_key_env = _validate_provider_api_key_env(provider_snapshot.get("api_key_env"))
            validate_provider_base_url(
                base_url,
                allowed_local_hosts=(
                    *local_hosts_for_privacy_mode(security_config, "explicit_remote"),
                    *local_hosts_for_privacy_mode(security_config, "strict_local"),
                    *_DEFAULT_LOCAL_HOSTS,
                ),
            )
            api_key = resolve_provider_api_key(api_key_env)

            report = await to_thread.run_sync(
                lambda: probe_provider(
                    provider_name=alias,
                    provider_class=provider_class,
                    model_name=model_name,
                    model_limits_name=model_limits_name,
                    base_url=base_url,
                    api_key=api_key,
                    api_key_env=api_key_env,
                    workspace_root=workspace_root,
                    security_config=security_config,
                    persist_result=False,
                )
            )
        except (ProviderError, ConfigError):
            return _provider_probe_failed_result(alias)
        except Exception:
            return _provider_probe_failed_result(alias)

        persisted = await to_thread.run_sync(
            lambda: _persist_probe_result_if_current(
                state=state,
                config_path=config_path,
                alias=alias,
                expected_fingerprint=start_fingerprint,
                report=report,
            )
        )
        return _probe_report_result(
            alias=alias,
            report=report,
            persisted=persisted,
            stale=not persisted,
        )

    global_probe_count = sum(
        1
        for info in runner.list_tasks()
        if info.task_type.startswith("provider_probe:")
        and info.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
    )
    if global_probe_count >= _MAX_GLOBAL_PENDING_PROBE_TASKS:
        return error_response(
            ErrorCode.RATE_LIMITED,
            "too_many_pending_provider_probe_tasks",
            status=503,
        )

    task_id = runner.submit_if_capacity(
        f"provider_probe:{alias}",
        _probe_task,
        max_pending=_MAX_PENDING_PROVIDER_PROBE_TASKS,
        thread_backed=True,
    )
    if task_id is None:
        return error_response(
            ErrorCode.RATE_LIMITED,
            "too_many_pending_provider_probe_tasks",
            status=503,
        )
    return JSONResponse(
        ProviderProbeSubmitResponse(
            task_id=task_id,
            alias=alias,
            poll_url=f"/api/tasks/{task_id}",
        ).model_dump(mode="json"),
        status_code=202,
    )


async def _read_capped_models_response_body(response: httpx.Response) -> bytes:
    body = bytearray()
    total_bytes = 0
    async for chunk in response.aiter_bytes(chunk_size=65_536):
        total_bytes += len(chunk)
        if total_bytes > _MODEL_DISCOVERY_RESPONSE_BYTE_CAP:
            raise ProviderError(
                "provider models response exceeded byte cap "
                f"({_MODEL_DISCOVERY_RESPONSE_BYTE_CAP} bytes)"
            )
        body.extend(chunk)
    return bytes(body)


async def _fetch_provider_models_payload(
    *,
    base_url: str,
    provider_class: str,
    api_key: str | None,
    allowed_local_hosts: tuple[str, ...] = (),
) -> Any:
    stripped_base_url = base_url.strip()
    try:
        validated_base_url = validate_provider_base_url(
            stripped_base_url,
            allowed_local_hosts=allowed_local_hosts,
        )
    except ConfigError as exc:
        raise ValueError(
            _provider_base_url_error("invalid provider base_url", stripped_base_url)
        ) from exc

    models_url = _build_models_url(validated_base_url, provider_class)
    headers: dict[str, str] = {"Accept-Encoding": "identity"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request_url = models_url
    stream_extensions: dict[str, Any] | None = None
    try:
        request_target = provider_module.transport_target_for_base_url(
            models_url,
            local_hosts=allowed_local_hosts,
        )
        if request_target == "remote":
            pinned_ip = provider_module.validate_remote_url(models_url)
            if pinned_ip is not None:
                request_url, original_host, sni_hostname = provider_module._pin_url_to_ip(  # pyright: ignore[reportPrivateUsage]
                    models_url,
                    pinned_ip,
                )
                headers["Host"] = original_host
                if sni_hostname is not None:
                    stream_extensions = {"sni_hostname": sni_hostname.encode("ascii")}
        elif request_target != "local":
            raise SafetyError(f"unknown provider transport target {request_target!r}")
    except SafetyError as exc:
        raise ValueError(
            _provider_base_url_error("provider base_url is not allowed", stripped_base_url)
        ) from exc

    async with (
        httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=_MODEL_DISCOVERY_TIMEOUT_SECONDS,
        ) as client,
        client.stream(
            "GET",
            request_url,
            headers=headers,
            extensions=stream_extensions,
        ) as response,
    ):
        if response.is_redirect:
            raise ProviderError("provider redirects are not allowed")
        response.raise_for_status()
        raw_body = await _read_capped_models_response_body(response)
        buffered_headers = httpx.Headers(
            [
                (key, value)
                for key, value in response.headers.raw
                if key.lower() not in (b"content-encoding", b"transfer-encoding")
            ]
        )
        buffered_response = httpx.Response(
            response.status_code,
            headers=buffered_headers,
            content=raw_body,
            request=response.request,
            extensions=response.extensions,
        )
    return buffered_response.json()


async def discover_models(request: Request) -> JSONResponse:
    """POST /api/providers/discover-models — discover models from any base_url + api_key."""
    from .auth import require_write_token

    require_write_token(request)
    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON", status=400)
    if not isinstance(body, dict):
        return _error("expected JSON object", status=400)
    body_data = cast("dict[str, object]", body)

    base_url = body_data.get("base_url", "")
    api_key = body_data.get("api_key", "")
    provider_class = body_data.get("provider_class", "openai")
    if not isinstance(base_url, str) or not base_url.strip():
        return _error("base_url is required", status=400)

    state = serve_state(request)
    config_path = _config_path(state)

    def _load_allowed_local_hosts() -> tuple[str, ...]:
        data = read_config_data(config_path) if config_path.exists() else {}
        return (*_provider_allowed_local_hosts(data), *_DEFAULT_LOCAL_HOSTS)

    try:
        allowed_local_hosts = await to_thread.run_sync(_load_allowed_local_hosts)
    except ConfigError as exc:
        return _error(str(exc), status=500)

    try:
        payload = await _fetch_provider_models_payload(
            base_url=base_url,
            provider_class=str(provider_class),
            api_key=api_key if isinstance(api_key, str) and api_key else None,
            allowed_local_hosts=allowed_local_hosts,
        )
    except ValueError as exc:
        return _error(f"Failed to fetch models: {exc}", status=400)
    except Exception as exc:
        return _error(f"Failed to fetch models: {type(exc).__name__}", status=502)

    model_ids = _extract_model_ids(payload, str(provider_class))
    return JSONResponse({"models": sorted(model_ids)})


async def fetch_provider_models(request: Request) -> JSONResponse:
    """GET /api/providers/{alias}/models — discover models from remote API."""
    from .auth import require_write_token, serve_state

    require_write_token(request)
    alias = request.path_params["alias"]
    state = serve_state(request)
    config_path = _config_path(state)

    def _load() -> tuple[dict[str, Any], tuple[str, ...]] | None:
        data, providers = _read_providers_table(config_path)
        raw = providers.get(alias)
        if not isinstance(raw, dict):
            return None
        allowed_local_hosts = (*_provider_allowed_local_hosts(data), *_DEFAULT_LOCAL_HOSTS)
        return dict(cast("dict[str, Any]", raw)), allowed_local_hosts

    try:
        loaded = await to_thread.run_sync(_load)
    except ConfigError as exc:
        return _error(str(exc), status=500)
    if loaded is None:
        return _error("provider_not_found", status=404)

    provider_data, allowed_local_hosts = loaded
    base_url = provider_data.get("base_url", "")
    api_key_env = provider_data.get("api_key_env", "")
    provider_class = provider_data.get("provider_class", "openai")

    try:
        api_key_env = _validate_provider_api_key_env(api_key_env)
        api_key = resolve_provider_api_key(api_key_env)
    except _ProviderFieldError as exc:
        return _error(str(exc), status=422)
    except Exception:
        return _error("Failed to resolve API key", status=400)

    try:
        payload = await _fetch_provider_models_payload(
            base_url=str(base_url),
            provider_class=str(provider_class),
            api_key=api_key,
            allowed_local_hosts=allowed_local_hosts,
        )
    except ValueError as exc:
        return _error(f"Failed to fetch models: {exc}", status=400)
    except httpx.HTTPStatusError as exc:
        return _error(f"Models endpoint returned {exc.response.status_code}", status=502)
    except Exception as exc:
        return _error(f"Failed to fetch models: {type(exc).__name__}", status=502)

    model_ids = _extract_model_ids(payload, str(provider_class))
    return JSONResponse({"models": sorted(model_ids)})


async def save_provider_models(request: Request) -> JSONResponse:
    """PUT /api/providers/{alias}/models — save selected available_models."""
    from .auth import require_write_token, serve_state

    require_write_token(request)
    alias = request.path_params["alias"]
    state = serve_state(request)
    config_path = _config_path(state)

    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON", status=400)
    if not isinstance(body, dict):
        return _error("expected JSON object", status=400)
    body_data = cast("dict[str, object]", body)
    models = body_data.get("models")
    if not isinstance(models, list):
        return _error("models must be a list of non-empty strings", status=400)
    model_items = cast("list[object]", models)
    if not all(isinstance(item, str) and item.strip() for item in model_items):
        return _error("models must be a list of non-empty strings", status=400)
    if len(model_items) > 100:
        return _error("too many models (max 100)", status=400)

    cleaned = list(dict.fromkeys(cast("str", item).strip() for item in model_items))

    def _persist() -> dict[str, Any] | None:
        with serve_repo_write_lock(state, command="serve save-provider-models"):
            data, providers = _read_providers_table(config_path)
            raw = providers.get(alias)
            if not isinstance(raw, dict):
                return None
            raw["available_models"] = tuple(cleaned)
            write_config_data(config_path, data)
            return dict(cast("dict[str, Any]", raw))

    try:
        result = await to_thread.run_sync(_persist)
    except ConfigError as exc:
        return _error(str(exc), status=500)
    if result is None:
        return _error("provider_not_found", status=404)

    summary = provider_summary_from_mapping(alias, result)
    if summary is None:
        return _error("failed to build summary", status=500)
    return JSONResponse(summary.model_dump(mode="json"))


def _build_models_url(base_url: str, provider_class: str) -> str:
    """Build the /models endpoint URL for the given provider."""
    url = base_url.rstrip("/")
    if provider_class == "ollama":
        return f"{url}/api/tags"
    if url.endswith("/v1"):
        return f"{url}/models"
    return f"{url}/v1/models"


def _extract_model_ids(payload: Any, provider_class: str) -> list[str]:
    """Extract model IDs from provider-specific response format."""
    if not isinstance(payload, dict):
        return []
    payload_mapping = cast("Mapping[str, object]", payload)
    if provider_class == "ollama":
        models = payload_mapping.get("models", [])
        if not isinstance(models, list):
            return []
        model_items = cast("list[object]", models)
        return [
            str(model_mapping["name"])
            for model in model_items
            if isinstance(model, dict)
            and isinstance((model_mapping := cast("Mapping[str, object]", model)).get("name"), str)
            and model_mapping["name"]
        ]
    data = payload_mapping.get("data", [])
    if not isinstance(data, list):
        return []
    data_items = cast("list[object]", data)
    return [
        str(model_mapping["id"])
        for model in data_items
        if isinstance(model, dict)
        and isinstance((model_mapping := cast("Mapping[str, object]", model)).get("id"), str)
        and model_mapping["id"]
    ]


__all__ = [
    "build_model_limits_response",
    "create_provider",
    "delete_provider",
    "discover_models",
    "fetch_provider_models",
    "get_provider_model_limits",
    "preview_provider_model_limits",
    "probe_provider_route",
    "save_provider_models",
    "update_provider",
]
