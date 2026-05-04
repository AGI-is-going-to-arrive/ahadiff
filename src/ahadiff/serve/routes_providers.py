"""POST/PUT/DELETE /api/providers and /api/providers/{alias}/probe endpoints.

CRUD operations on the per-repo ``[providers.<alias>]`` table inside
``.ahadiff/config.toml``.  Probe submits an async ``provider_probe:<alias>``
task to the ``TaskRunner``; the actual probe execution is intentionally
left as a TODO stub so that contracts and CRUD can land first.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from pydantic import ValidationError
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_providers import (
    ProviderCreateRequest,
    ProviderDeleteResponse,
    ProviderMutationResponse,
    ProviderUpdateRequest,
)
from ahadiff.core.config import (
    clear_provider_probe_fields,
    mask_provider_base_url_for_display,
    normalize_provider_base_url,
    read_config_data,
    validate_provider_alias,
    validate_provider_base_url,
    validate_repo_api_key_env_name,
    write_config_data,
)
from ahadiff.core.errors import ConfigError
from ahadiff.core.ids import make_event_id
from ahadiff.safety.audit import append_audit_record

from .auth import require_write_token, serve_state
from .lock import serve_repo_write_lock
from .routes_stats import provider_summary_from_mapping

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from .state import ServeState


_CORE_FIELDS = ("provider_class", "model_name", "base_url", "api_key_env")


class _ProviderBaseUrlError(Exception):
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


def _error(message: str, *, status: int) -> JSONResponse:
    return JSONResponse({"error": message, "status": status}, status_code=status)


def _validation_error(exc: ValidationError, *, status: int = 422) -> JSONResponse:
    return JSONResponse(
        {"error": exc.errors(include_context=False, include_input=False), "status": status},
        status_code=status,
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
            allowed_local_hosts=_provider_allowed_local_hosts(data),
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
        "base_url": mask_provider_base_url_for_display(
            str(provider_data.get("base_url") or "")
        ),
    }
    append_audit_record(state.state_dir / "audit.jsonl", record)


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
        validate_repo_api_key_env_name(body.api_key_env)
    except ConfigError as exc:
        return _error(str(exc), status=422)

    config_path = _config_path(state)

    def _persist() -> tuple[bool, dict[str, Any] | None]:
        with serve_repo_write_lock(state, command="serve provider create"):
            data, providers = _read_providers_table(config_path)
            if body.alias in providers:
                return False, None
            normalized_base_url = _normalize_and_validate_base_url(
                body.base_url,
                provider_class=body.provider_class,
                data=data,
            )
            new_provider: dict[str, Any] = {
                "provider_class": body.provider_class,
                "model_name": body.model_name,
                "base_url": normalized_base_url,
                "api_key_env": body.api_key_env,
            }
            providers[body.alias] = new_provider
            write_config_data(config_path, data)
            _append_provider_audit_event(
                state,
                event_type="provider_create",
                alias=body.alias,
                provider_data=new_provider,
            )
            return True, dict(new_provider)

    try:
        created, persisted = await to_thread.run_sync(_persist)
    except _ProviderBaseUrlError as exc:
        return _error(f"base_url: {exc}", status=422)
    except ConfigError as exc:
        return _error(str(exc), status=500)
    if not created or persisted is None:
        return _error("provider_alias_conflict", status=409)

    summary = _build_summary(state, body.alias, persisted)
    if summary is None:
        return _error("provider_summary_unavailable", status=500)
    return JSONResponse(
        ProviderMutationResponse.model_validate(
            {"updated": True, "provider": summary}
        ).model_dump(mode="json"),
        status_code=201,
    )


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

    update_payload = body.model_dump(exclude_none=True)
    if not update_payload:
        return _error("at_least_one_field_required", status=422)

    if "api_key_env" in update_payload:
        try:
            validate_repo_api_key_env_name(str(update_payload["api_key_env"]))
        except ConfigError as exc:
            return _error(str(exc), status=422)

    config_path = _config_path(state)

    def _persist() -> tuple[bool, dict[str, Any] | None]:
        with serve_repo_write_lock(state, command="serve provider update"):
            data, providers = _read_providers_table(config_path)
            existing = providers.get(alias)
            if not isinstance(existing, dict):
                return False, None
            existing_typed = cast("dict[str, Any]", existing)
            updated_provider: dict[str, Any] = dict(existing_typed)
            updated_provider.update(update_payload)
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
            # Clear stale probe results when any core identity field changed.
            core_changed = any(field in update_payload for field in _CORE_FIELDS)
            if core_changed:
                clear_provider_probe_fields(updated_provider)
            providers[alias] = updated_provider
            write_config_data(config_path, data)
            _append_provider_audit_event(
                state,
                event_type="provider_update",
                alias=alias,
                provider_data=updated_provider,
            )
            return True, dict(updated_provider)

    try:
        updated, persisted = await to_thread.run_sync(_persist)
    except _ProviderBaseUrlError as exc:
        return _error(f"base_url: {exc}", status=422)
    except ConfigError as exc:
        return _error(str(exc), status=500)
    if not updated or persisted is None:
        return _error("provider_not_found", status=404)

    summary = _build_summary(state, alias, persisted)
    if summary is None:
        return _error("provider_summary_unavailable", status=500)
    return JSONResponse(
        ProviderMutationResponse.model_validate(
            {"updated": True, "provider": summary}
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
        ProviderDeleteResponse.model_validate(
            {"deleted": True, "alias": alias}
        ).model_dump(mode="json")
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

    config_path = _config_path(state)

    def _load_provider() -> dict[str, Any] | None:
        _data, providers = _read_providers_table(config_path)
        candidate = providers.get(alias)
        if not isinstance(candidate, dict):
            return None
        candidate_typed = cast("dict[str, Any]", candidate)
        return dict(candidate_typed)

    try:
        provider_snapshot = await to_thread.run_sync(_load_provider)
    except ConfigError as exc:
        return _error(str(exc), status=500)
    if provider_snapshot is None:
        return _error("provider_not_found", status=404)

    return _error("provider_probe_not_implemented", status=501)


__all__ = [
    "create_provider",
    "delete_provider",
    "probe_provider_route",
    "update_provider",
]
