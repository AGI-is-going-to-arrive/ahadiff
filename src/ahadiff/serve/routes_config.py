"""GET /api/config and GET /api/doctor endpoints."""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_app import ConfigResponse, ConfigUpdateResponse
from ahadiff.contracts.serve_doctor import DoctorCheck, DoctorResponse
from ahadiff.core.sqlite_util import safe_sqlite_connect

if TYPE_CHECKING:
    from starlette.requests import Request

    from .state import ServeState

log = logging.getLogger(__name__)


def _empty_config_snapshot() -> dict[str, Any]:
    return {
        "lang": None,
        "privacy_mode": None,
        "generate_model": None,
        "judge_model": None,
        "serve_port": None,
        "key_status": {},
    }


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
        return _empty_config_snapshot()

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


def _doctor_check(
    name: str,
    status: str,
    message: str,
    *,
    category: str,
    details: dict[str, Any] | None = None,
) -> DoctorCheck:
    return DoctorCheck(
        name=name,
        category=category,
        status=cast("Any", status),
        message=message,
        details=details or {},
    )


def _summary_status(checks: list[DoctorCheck]) -> str:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "pass"


def _run_doctor_checks(state: ServeState) -> dict[str, Any]:
    checks: list[DoctorCheck] = []

    repo_root = state.state_dir.parent
    ahadiff_dir = repo_root / ".ahadiff"
    checks.append(
        _doctor_check(
            "repo_root",
            "pass" if ahadiff_dir.is_dir() else "fail",
            ".ahadiff/ exists" if ahadiff_dir.is_dir() else ".ahadiff/ not found",
            category="paths",
            details={"path": ".ahadiff"},
        )
    )
    checks.append(
        _doctor_check(
            "state_dir_path",
            "pass" if state.state_dir.is_dir() else "fail",
            "state directory is accessible"
            if state.state_dir.is_dir()
            else "state directory is missing",
            category="paths",
            details={"name": state.state_dir.name},
        )
    )

    sqlite_ver = sqlite3.sqlite_version
    checks.append(
        _doctor_check(
            "sqlite_version",
            "pass",
            f"SQLite {sqlite_ver}",
            category="runtime",
        )
    )
    checks.append(
        _doctor_check(
            "sqlite_runtime_gate",
            "pass",
            f"SQLite runtime accepted: {sqlite_ver}",
            category="runtime",
        )
    )

    cfg: Any | None = None
    try:
        from ahadiff.core.config import load_config

        cfg = load_config(repo_root)
        checks.append(
            _doctor_check(
                "config_valid",
                "pass",
                "Config loaded successfully",
                category="config",
            )
        )
    except Exception as exc:
        checks.append(
            _doctor_check(
                "config_valid",
                "fail",
                f"Config error: {type(exc).__name__}",
                category="config",
            )
        )

    unknown_keys: list[str] = []
    sensitive_keys: list[str] = []
    precedence_conflicts: list[str] = []
    if cfg is not None:
        for attr in ("repo_unknown_keys", "global_unknown_keys"):
            unknown_keys.extend(str(item) for item in getattr(cfg, attr, ()) or ())
        sensitive_keys.extend(str(item) for item in getattr(cfg, "repo_sensitive_keys", ()) or ())
        precedence_conflicts.extend(
            str(item) for item in getattr(cfg, "precedence_conflicts", ()) or ()
        )
    checks.append(
        _doctor_check(
            "config_unknown_keys",
            "warn" if unknown_keys else "pass",
            "Unknown config keys found" if unknown_keys else "No unknown config keys",
            category="config",
            details={"count": len(unknown_keys), "keys": unknown_keys[:20]},
        )
    )
    checks.append(
        _doctor_check(
            "config_sensitive_keys",
            "fail" if sensitive_keys else "pass",
            "Sensitive config keys found" if sensitive_keys else "No sensitive config keys",
            category="config",
            details={"count": len(sensitive_keys), "keys": sensitive_keys[:20]},
        )
    )
    checks.append(
        _doctor_check(
            "config_precedence_conflicts",
            "warn" if precedence_conflicts else "pass",
            "Config precedence conflicts found"
            if precedence_conflicts
            else "No config precedence conflicts",
            category="config",
            details={"count": len(precedence_conflicts)},
        )
    )

    review_db = state.state_dir / "review.sqlite"
    checks.append(
        _doctor_check(
            "review_db",
            "pass" if review_db.is_file() else "warn",
            "review.sqlite present" if review_db.is_file() else "review.sqlite not found",
            category="storage",
        )
    )
    if review_db.is_file():
        try:
            with safe_sqlite_connect(review_db) as conn:
                row = conn.execute("PRAGMA quick_check").fetchone()
            quick_check_ok = row is not None and row[0] == "ok"
            checks.append(
                _doctor_check(
                    "review_db_quick_check",
                    "pass" if quick_check_ok else "fail",
                    "review.sqlite quick_check ok"
                    if quick_check_ok
                    else "review.sqlite quick_check failed",
                    category="storage",
                )
            )
        except (sqlite3.DatabaseError, OSError):
            checks.append(
                _doctor_check(
                    "review_db_quick_check",
                    "fail",
                    "review.sqlite quick_check failed",
                    category="storage",
                )
            )
    else:
        checks.append(
            _doctor_check(
                "review_db_quick_check",
                "warn",
                "review.sqlite not found",
                category="storage",
            )
        )

    try:
        from ahadiff.core.paths import usage_db_path

        usage_db = usage_db_path()
        checks.append(
            _doctor_check(
                "usage_db",
                "pass" if usage_db.is_file() else "warn",
                "usage.sqlite present" if usage_db.is_file() else "usage.sqlite not found",
                category="storage",
                details={"filename": usage_db.name},
            )
        )
    except Exception:
        checks.append(
            _doctor_check(
                "usage_db",
                "warn",
                "usage.sqlite path unavailable",
                category="storage",
            )
        )

    audit_path = state.state_dir / "audit.jsonl"
    checks.append(
        _doctor_check(
            "audit_file",
            "pass" if audit_path.is_file() else "warn",
            "audit.jsonl present" if audit_path.is_file() else "audit.jsonl not found",
            category="storage",
        )
    )

    return DoctorResponse(
        summary_status=cast("Any", _summary_status(checks)),
        checks=checks,
    ).model_dump(mode="json")


async def get_config(request: Request) -> JSONResponse:
    from .auth import serve_state

    state: ServeState = serve_state(request)
    snapshot = await to_thread.run_sync(_safe_config_snapshot, state)
    return JSONResponse(ConfigResponse.model_validate(snapshot).model_dump(mode="json"))


async def get_doctor(request: Request) -> JSONResponse:
    from .auth import serve_state

    state: ServeState = serve_state(request)
    payload = await to_thread.run_sync(_run_doctor_checks, state)
    return JSONResponse(payload)


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

    return JSONResponse(ConfigUpdateResponse(updated=True, scope="session").model_dump(mode="json"))
