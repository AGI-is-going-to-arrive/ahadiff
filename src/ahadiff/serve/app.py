from __future__ import annotations

from json import JSONDecodeError
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

from ahadiff.contracts import AuthTokenResponse
from ahadiff.core.errors import AhaDiffError, InputError

from .auth import serve_state
from .middleware import LoopbackGuardMiddleware
from .routes_locale import get_locale, put_locale
from .routes_runs import (
    get_claims,
    get_concepts,
    get_diff,
    get_lesson,
    get_quiz,
    get_ratchet_history,
    get_run,
    get_run_concepts,
    list_runs,
)
from .routes_signals import helpfulness, mark_wrong, quiz_answer, srs_review
from .static import mount_viewer_static

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from .state import ServeState


def create_app(state: ServeState, *, viewer_dist: Path | None = None) -> Starlette:
    runtime_state = state.with_runtime_lock()
    app = Starlette(
        debug=False,
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/api/auth/token", auth_token, methods=["GET"]),
            Route("/api/locale", get_locale, methods=["GET"]),
            Route("/api/locale", put_locale, methods=["PUT"]),
            Route("/api/runs", list_runs, methods=["GET"]),
            Route("/api/run/{run_id}", get_run, methods=["GET"]),
            Route("/api/run/{run_id}/lesson", get_lesson, methods=["GET"]),
            Route("/api/run/{run_id}/claims", get_claims, methods=["GET"]),
            Route("/api/run/{run_id}/quiz", get_quiz, methods=["GET"]),
            Route("/api/run/{run_id}/diff", get_diff, methods=["GET"]),
            Route("/api/run/{run_id}/concepts", get_run_concepts, methods=["GET"]),
            Route("/api/concepts", get_concepts, methods=["GET"]),
            Route("/api/ratchet/history", get_ratchet_history, methods=["GET"]),
            Route("/api/signals/mark-wrong", mark_wrong, methods=["POST"]),
            Route("/api/signals/quiz-answer", quiz_answer, methods=["POST"]),
            Route("/api/signals/srs-review", srs_review, methods=["POST"]),
            Route("/api/signals/helpfulness", helpfulness, methods=["POST"]),
            Route(
                "/api/{rest_of_path:path}",
                api_not_found,
                methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
            ),
        ],
        exception_handlers={
            AhaDiffError: _handled_error,
            InputError: _handled_error,
            JSONDecodeError: _handled_error,
            PermissionError: _permission_error,
            ValidationError: _validation_error,
            HTTPException: _http_error,
        },
    )
    app.state.ahadiff = runtime_state
    app.add_middleware(LoopbackGuardMiddleware)
    mount_viewer_static(app, viewer_dist=viewer_dist)
    return app


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def auth_token(request: Request) -> JSONResponse:
    state = serve_state(request)
    return JSONResponse(AuthTokenResponse(token=state.token).model_dump(mode="json"))


async def api_not_found(request: Request) -> JSONResponse:
    return JSONResponse({"error": "not_found", "path": request.url.path}, status_code=404)


async def _handled_error(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)


async def _permission_error(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=403)


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ValidationError):
        return JSONResponse({"error": exc.errors()}, status_code=422)
    return JSONResponse({"error": str(exc)}, status_code=422)


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    status_code = exc.status_code if isinstance(exc, HTTPException) else 500
    detail: Any = exc.detail if isinstance(exc, HTTPException) else str(exc)
    return JSONResponse({"error": detail}, status_code=status_code)


__all__ = ["create_app"]
