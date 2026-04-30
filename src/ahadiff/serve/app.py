from __future__ import annotations

import contextlib
import logging
from json import JSONDecodeError
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

from ahadiff.contracts import AuthTokenResponse
from ahadiff.core.errors import AhaDiffError, InputError

from .auth import require_token_bootstrap_request, serve_state
from .middleware import LoopbackGuardMiddleware
from .routes_audit import get_audit
from .routes_config import get_config, get_doctor, put_config
from .routes_export import get_export_results
from .routes_graph import get_graph_status
from .routes_install import get_install_targets
from .routes_learn import post_learn
from .routes_locale import get_locale, put_locale
from .routes_review import get_review_mastery, get_review_queue, get_weak_concepts, post_review_rate
from .routes_runs import (
    get_claims,
    get_concepts,
    get_diff,
    get_lesson,
    get_misconceptions,
    get_quiz,
    get_ratchet_history,
    get_run,
    get_run_concepts,
    list_runs,
)
from .routes_search import search_api
from .routes_signals import helpfulness, mark_wrong, quiz_answer, srs_review
from .routes_stats import (
    get_learning_effectiveness,
    get_providers,
    get_review_heatmap,
    get_serve_status,
    get_spec_alignment,
    get_stats,
    get_usage,
)
from .routes_tasks import cancel_task, get_task, list_tasks, task_progress_sse
from .routes_watch import get_watch_status
from .static import mount_viewer_static

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from starlette.requests import Request

    from .state import ServeState


_log = logging.getLogger(__name__)


def create_app(state: ServeState, *, viewer_dist: Path | None = None) -> Starlette:
    runtime_state = state.with_runtime_lock()

    @contextlib.asynccontextmanager
    async def _lifespan(_app: Starlette) -> AsyncGenerator[None]:
        yield
        runner = getattr(runtime_state, "task_runner", None)
        if runner is not None:
            try:
                await runner.shutdown(timeout=5.0)
            except Exception:
                _log.debug("task runner shutdown error", exc_info=True)
        watcher = getattr(runtime_state, "file_watcher", None)
        if watcher is not None:
            try:
                watcher.stop()
            except Exception:
                _log.debug("file watcher stop error", exc_info=True)

    app = Starlette(
        debug=False,
        lifespan=_lifespan,
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/api/auth/token", auth_token, methods=["GET", "POST"]),
            Route("/api/locale", get_locale, methods=["GET"]),
            Route("/api/locale", put_locale, methods=["PUT"]),
            Route("/api/runs", list_runs, methods=["GET"]),
            Route("/api/run/{run_id}", get_run, methods=["GET"]),
            Route("/api/run/{run_id}/lesson", get_lesson, methods=["GET"]),
            Route("/api/run/{run_id}/claims", get_claims, methods=["GET"]),
            Route("/api/run/{run_id}/quiz", get_quiz, methods=["GET"]),
            Route("/api/run/{run_id}/misconceptions", get_misconceptions, methods=["GET"]),
            Route("/api/run/{run_id}/diff", get_diff, methods=["GET"]),
            Route("/api/run/{run_id}/concepts", get_run_concepts, methods=["GET"]),
            Route("/api/concepts", get_concepts, methods=["GET"]),
            Route("/api/ratchet/history", get_ratchet_history, methods=["GET"]),
            Route("/api/review/queue", get_review_queue, methods=["GET"]),
            Route("/api/review/rate", post_review_rate, methods=["POST"]),
            Route("/api/search", search_api, methods=["GET"]),
            Route("/api/concepts/weak", get_weak_concepts, methods=["GET"]),
            Route("/api/review/mastery", get_review_mastery, methods=["GET"]),
            Route("/api/usage", get_usage, methods=["GET"]),
            Route("/api/audit", get_audit, methods=["GET"]),
            Route("/api/spec/alignment", get_spec_alignment, methods=["GET"]),
            Route("/api/config", get_config, methods=["GET"]),
            Route("/api/config", put_config, methods=["PUT"]),
            Route("/api/doctor", get_doctor, methods=["GET"]),
            Route("/api/install/targets", get_install_targets, methods=["GET"]),
            Route("/api/stats", get_stats, methods=["GET"]),
            Route("/api/review/heatmap", get_review_heatmap, methods=["GET"]),
            Route("/api/export/results", get_export_results, methods=["GET"]),
            Route("/api/providers", get_providers, methods=["GET"]),
            Route("/api/serve/status", get_serve_status, methods=["GET"]),
            Route("/api/stats/learning", get_learning_effectiveness, methods=["GET"]),
            Route("/api/signals/mark-wrong", mark_wrong, methods=["POST"]),
            Route("/api/signals/quiz-answer", quiz_answer, methods=["POST"]),
            Route("/api/signals/srs-review", srs_review, methods=["POST"]),
            Route("/api/signals/helpfulness", helpfulness, methods=["POST"]),
            Route("/api/graph/status", get_graph_status, methods=["GET"]),
            Route("/api/learn", post_learn, methods=["POST"]),
            Route("/api/tasks", list_tasks, methods=["GET"]),
            Route("/api/tasks/{task_id}", get_task, methods=["GET"]),
            Route("/api/tasks/{task_id}/cancel", cancel_task, methods=["POST"]),
            Route("/api/tasks/{task_id}/progress", task_progress_sse, methods=["GET"]),
            Route("/api/watch/status", get_watch_status, methods=["GET"]),
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
    # Every mutating route separately requires X-AhaDiff-Token so ambient browser state
    # or a discovered localhost port is not enough to perform writes against the repo DB.
    require_token_bootstrap_request(request)
    state = serve_state(request)
    return JSONResponse(AuthTokenResponse(token=state.token).model_dump(mode="json"))


async def api_not_found(request: Request) -> JSONResponse:
    return JSONResponse(
        {"error": "not_found", "status": 404, "path": request.url.path},
        status_code=404,
    )


async def _handled_error(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"error": str(exc), "status": 400}, status_code=400)


async def _permission_error(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"error": str(exc), "status": 403}, status_code=403)


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ValidationError):
        return JSONResponse(
            {"error": exc.errors(include_context=False, include_input=False), "status": 422},
            status_code=422,
        )
    return JSONResponse({"error": str(exc), "status": 422}, status_code=422)


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    status_code = exc.status_code if isinstance(exc, HTTPException) else 500
    detail: Any = exc.detail if isinstance(exc, HTTPException) else str(exc)
    return JSONResponse({"error": detail, "status": status_code}, status_code=status_code)


__all__ = ["create_app"]
