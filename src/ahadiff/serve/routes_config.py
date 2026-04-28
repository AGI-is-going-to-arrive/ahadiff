"""GET /api/config and GET /api/doctor endpoints."""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request

    from .state import ServeState

log = logging.getLogger(__name__)


def _object_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in cast("dict[object, object]", value).items()}


def _provider_key_status(providers: object) -> dict[str, str]:
    import os

    statuses: dict[str, str] = {}
    for provider_name, raw_provider in _object_mapping(providers).items():
        provider_values = _object_mapping(raw_provider)
        api_key_env = provider_values.get("api_key_env")
        if isinstance(api_key_env, str) and api_key_env:
            statuses[provider_name] = "configured" if os.environ.get(api_key_env) else "missing"
    return statuses


def _add_legacy_llm_key_status(key_status: dict[str, str], api_key_env: object) -> None:
    if not isinstance(api_key_env, str) or not api_key_env:
        return
    import os

    key_status.setdefault("llm", "configured" if os.environ.get(api_key_env) else "missing")


def _safe_config_snapshot(state: ServeState) -> dict[str, Any]:
    from ahadiff.core.config import load_config

    try:
        cfg = load_config(state.state_dir.parent)
    except Exception:
        return {}

    values = getattr(cfg, "values", None)
    if isinstance(values, dict):
        snapshot_values = _object_mapping(cast("object", values))
        llm_values = _object_mapping(snapshot_values.get("llm"))
        serve_values = _object_mapping(snapshot_values.get("serve"))
        result: dict[str, Any] = {
            "lang": snapshot_values.get("lang"),
            "privacy_mode": snapshot_values.get("privacy_mode"),
            "generate_model": llm_values.get("generate_model"),
            "judge_model": llm_values.get("judge_model"),
            "serve_port": serve_values.get("port"),
        }
        api_key_env = llm_values.get("api_key_env")
        providers = snapshot_values.get("providers")
    else:
        result = {}
        result["lang"] = getattr(cfg, "lang", None)
        result["privacy_mode"] = getattr(cfg, "privacy_mode", None)

        llm = getattr(cfg, "llm", None)
        result["generate_model"] = getattr(llm, "generate_model", None) if llm else None
        result["judge_model"] = getattr(llm, "judge_model", None) if llm else None

        serve = getattr(cfg, "serve", None)
        result["serve_port"] = getattr(serve, "port", None) if serve else None
        api_key_env = getattr(llm, "api_key_env", None) if llm else None
        providers = getattr(cfg, "providers", None)

    key_status = _provider_key_status(providers)
    _add_legacy_llm_key_status(key_status, api_key_env)
    result["key_status"] = key_status

    return result


def _run_doctor_checks(state: ServeState) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    repo_root = state.state_dir.parent
    ahadiff_dir = repo_root / ".ahadiff"
    checks.append(
        {
            "name": "repo_root",
            "status": "pass" if ahadiff_dir.is_dir() else "fail",
            "message": ".ahadiff/ exists" if ahadiff_dir.is_dir() else ".ahadiff/ not found",
        }
    )

    sqlite_ver = sqlite3.sqlite_version
    checks.append(
        {
            "name": "sqlite_version",
            "status": "pass",
            "message": f"SQLite {sqlite_ver}",
        }
    )

    try:
        from ahadiff.core.config import load_config

        load_config(repo_root)
        checks.append(
            {
                "name": "config_valid",
                "status": "pass",
                "message": "Config loaded successfully",
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": "config_valid",
                "status": "fail",
                "message": f"Config error: {type(exc).__name__}",
            }
        )

    review_db = state.state_dir / "review.sqlite"
    checks.append(
        {
            "name": "review_db",
            "status": "pass" if review_db.is_file() else "warn",
            "message": "review.sqlite present"
            if review_db.is_file()
            else "review.sqlite not found",
        }
    )

    return checks


async def get_config(request: Request) -> JSONResponse:
    from .auth import serve_state

    state: ServeState = serve_state(request)
    snapshot = await to_thread.run_sync(_safe_config_snapshot, state)
    return JSONResponse(snapshot)


async def get_doctor(request: Request) -> JSONResponse:
    from .auth import serve_state

    state: ServeState = serve_state(request)
    checks = await to_thread.run_sync(_run_doctor_checks, state)
    return JSONResponse({"checks": checks})


_ALLOWED_CONFIG_LANG = frozenset({"en", "zh-CN"})


async def put_config(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    payload: Any = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse({"error": "expected JSON object", "status": 400}, status_code=400)

    body = cast("dict[str, Any]", payload)
    allowed_keys: set[str] = {"lang"}
    unknown: set[str] = set(body.keys()) - allowed_keys
    if unknown:
        return JSONResponse(
            {"error": f"unknown config keys: {sorted(unknown)}", "status": 400},
            status_code=400,
        )

    if "lang" in body:
        lang: str = str(body["lang"])
        if lang not in _ALLOWED_CONFIG_LANG:
            return JSONResponse(
                {"error": f"lang must be one of {sorted(_ALLOWED_CONFIG_LANG)}", "status": 400},
                status_code=400,
            )
        state = serve_state(request)
        assert state.write_lock is not None
        async with state.write_lock:
            request.app.state.ahadiff = state.with_locale(lang)  # type: ignore[arg-type]

    return JSONResponse({"updated": True, "scope": "session"})
