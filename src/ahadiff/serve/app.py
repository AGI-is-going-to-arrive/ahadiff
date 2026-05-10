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

from ahadiff.contracts import AuthTokenResponse, ErrorCode
from ahadiff.core.errors import AhaDiffError, InputError

from ._errors import error_response
from .auth import require_token_bootstrap_request, serve_state
from .middleware import LoopbackGuardMiddleware, RequestTimeoutMiddleware, WriteRateLimitMiddleware
from .routes_audit import get_audit
from .routes_config import get_config, get_doctor, put_config
from .routes_db import post_db_check
from .routes_export import get_export_results
from .routes_graph import get_concept_graph, get_graph_status, post_graph_refresh
from .routes_improve import get_improve_preflight
from .routes_install import (
    get_install_targets,
    install_target,
    preview_install_target,
    uninstall_target,
)
from .routes_learn import post_learn, post_learn_estimate
from .routes_locale import get_locale, put_locale
from .routes_providers import (
    create_provider,
    delete_provider,
    discover_models,
    fetch_provider_models,
    probe_provider_route,
    save_provider_models,
    update_provider,
)
from .routes_review import (
    get_review_mastery,
    get_review_queue,
    get_weak_concepts,
    post_review_queue_state,
    post_review_rate,
)
from .routes_runs import (
    get_claims,
    get_concepts,
    get_concepts_ledger,
    get_diff,
    get_judge,
    get_lesson,
    get_misconceptions,
    get_quiz,
    get_ratchet_history,
    get_run,
    get_run_concepts,
    get_score,
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

_HTTP_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.INPUT_BAD_FIELD,
    401: ErrorCode.AUTH_REQUIRED,
    403: ErrorCode.LOOPBACK_DENIED,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.INPUT_BAD_FIELD,
    408: ErrorCode.REQUEST_TIMEOUT,
    413: ErrorCode.RUN_ARTIFACT_TOO_LARGE,
    415: ErrorCode.INPUT_BAD_FIELD,
    422: ErrorCode.INPUT_VALIDATION,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL_ERROR,
    502: ErrorCode.PROVIDER_TRANSPORT,
    503: ErrorCode.REQUEST_TIMEOUT,
    504: ErrorCode.REQUEST_TIMEOUT,
}

_GENERIC_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INTERNAL_ERROR: "internal_error",
    ErrorCode.STORAGE_REVIEW_DB: "review_database_unavailable",
    ErrorCode.STORAGE_USAGE_DB: "usage_database_unavailable",
    ErrorCode.STORAGE_FS: "local_storage_unavailable",
    ErrorCode.PROVIDER_TRANSPORT: "provider_transport_error",
    ErrorCode.PROVIDER_HTTP: "provider_http_error",
}


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
            Route("/api/run/{run_id}/score", get_score, methods=["GET"]),
            Route("/api/run/{run_id}/judge", get_judge, methods=["GET"]),
            Route("/api/run/{run_id}/concepts", get_run_concepts, methods=["GET"]),
            Route("/api/concepts/ledger", get_concepts_ledger, methods=["GET"]),
            Route("/api/concepts", get_concepts, methods=["GET"]),
            Route("/api/ratchet/history", get_ratchet_history, methods=["GET"]),
            Route("/api/improve/preflight", get_improve_preflight, methods=["GET"]),
            Route("/api/review/queue", get_review_queue, methods=["GET"]),
            Route("/api/review/rate", post_review_rate, methods=["POST"]),
            Route("/api/review/queue-state", post_review_queue_state, methods=["POST"]),
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
            Route("/api/install/{target}/preview", preview_install_target, methods=["POST"]),
            Route("/api/install/{target}", install_target, methods=["POST"]),
            Route("/api/install/{target}/uninstall", uninstall_target, methods=["POST"]),
            Route("/api/stats", get_stats, methods=["GET"]),
            Route("/api/review/heatmap", get_review_heatmap, methods=["GET"]),
            Route("/api/export/results", get_export_results, methods=["GET"]),
            Route("/api/providers", get_providers, methods=["GET"]),
            Route("/api/providers", create_provider, methods=["POST"]),
            Route("/api/providers/discover-models", discover_models, methods=["POST"]),
            Route("/api/providers/{alias}/probe", probe_provider_route, methods=["POST"]),
            Route("/api/providers/{alias}/models", fetch_provider_models, methods=["GET"]),
            Route("/api/providers/{alias}/models", save_provider_models, methods=["PUT"]),
            Route("/api/providers/{alias}", update_provider, methods=["PUT"]),
            Route("/api/providers/{alias}", delete_provider, methods=["DELETE"]),
            Route("/api/serve/status", get_serve_status, methods=["GET"]),
            Route("/api/stats/learning", get_learning_effectiveness, methods=["GET"]),
            Route("/api/signals/mark-wrong", mark_wrong, methods=["POST"]),
            Route("/api/signals/quiz-answer", quiz_answer, methods=["POST"]),
            Route("/api/signals/srs-review", srs_review, methods=["POST"]),
            Route("/api/signals/helpfulness", helpfulness, methods=["POST"]),
            Route("/api/graph/status", get_graph_status, methods=["GET"]),
            Route("/api/graph/concepts", get_concept_graph, methods=["GET"]),
            Route("/api/graph/refresh", post_graph_refresh, methods=["POST"]),
            Route("/api/db/check", post_db_check, methods=["POST"]),
            Route("/api/learn", post_learn, methods=["POST"]),
            Route("/api/learn/estimate", post_learn_estimate, methods=["POST"]),
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
    app.add_middleware(WriteRateLimitMiddleware)
    app.add_middleware(LoopbackGuardMiddleware)
    app.add_middleware(RequestTimeoutMiddleware)
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
    return error_response(
        ErrorCode.NOT_FOUND,
        "not_found",
        details={"path": request.url.path},
    )


async def _handled_error(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, AhaDiffError):
        return error_response(
            exc.code,
            _public_error_message(exc.code, str(exc)),
            details=exc.details or None,
        )
    if isinstance(exc, JSONDecodeError):
        return error_response(ErrorCode.INPUT_INVALID_JSON, "invalid_json")
    return error_response(ErrorCode.INTERNAL_ERROR, _GENERIC_MESSAGES[ErrorCode.INTERNAL_ERROR])


async def _permission_error(_request: Request, exc: Exception) -> JSONResponse:
    del exc
    return error_response(ErrorCode.STORAGE_FS, _GENERIC_MESSAGES[ErrorCode.STORAGE_FS])


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ValidationError):
        return error_response(
            ErrorCode.INPUT_VALIDATION,
            "validation_error",
            details={"errors": exc.errors(include_context=False, include_input=False)},
        )
    return error_response(ErrorCode.INPUT_VALIDATION, str(exc))


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    status_code = exc.status_code if isinstance(exc, HTTPException) else 500
    detail: Any = exc.detail if isinstance(exc, HTTPException) else str(exc)
    code = _HTTP_TO_CODE.get(status_code, ErrorCode.INTERNAL_ERROR)
    message = detail if isinstance(detail, str) else str(detail)
    return error_response(code, _public_error_message(code, message), status=status_code)


def _public_error_message(code: ErrorCode, message: str) -> str:
    if code in _GENERIC_MESSAGES:
        return _GENERIC_MESSAGES[code]
    if code is ErrorCode.LOCK_CONFLICT:
        return "another_ahadiff_process_is_running"
    return message or code.value.lower()


__all__ = ["create_app"]
