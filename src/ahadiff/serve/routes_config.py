"""GET /api/config and GET /api/doctor endpoints."""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request

    from .state import ServeState

log = logging.getLogger(__name__)


def _safe_config_snapshot(state: ServeState) -> dict[str, Any]:
    from ahadiff.core.config import load_config

    try:
        cfg = load_config(state.state_dir.parent)
    except Exception:
        return {}

    result: dict[str, Any] = {}
    result["lang"] = getattr(cfg, "lang", None)
    result["privacy_mode"] = getattr(cfg, "privacy_mode", None)

    llm = getattr(cfg, "llm", None)
    result["generate_model"] = getattr(llm, "generate_model", None) if llm else None
    result["judge_model"] = getattr(llm, "judge_model", None) if llm else None

    serve = getattr(cfg, "serve", None)
    result["serve_port"] = getattr(serve, "port", None) if serve else None

    key_status: dict[str, str] = {}
    if llm:
        api_key_env = getattr(llm, "api_key_env", None)
        if api_key_env:
            import os

            key_status["llm"] = "configured" if os.environ.get(api_key_env) else "missing"
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
