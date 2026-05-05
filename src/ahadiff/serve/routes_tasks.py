from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal, cast, get_args

from starlette.responses import JSONResponse, StreamingResponse

from ahadiff.contracts.serve_runtime import (
    RecoveryHint,
    TaskCancelResponse,
    TaskErrorCode,
    TaskInfoResponse,
    TaskListResponse,
    TaskProgressEvent,
    TaskResultSummary,
)
from ahadiff.core.task_runner import TaskStatus

from .auth import require_write_token, serve_state

if TYPE_CHECKING:
    from starlette.requests import Request


_USER_FACING_ERROR_MESSAGES = {
    "network_error": "Network connection failed. Check your internet and try again.",
    "timeout": "Task timed out. Try again or increase the timeout.",
    "config_error": "Configuration error. Check your provider settings.",
    "permission_error": "Permission denied. Check file or directory permissions.",
    "claim_error": "Failed to extract or verify claims from the diff.",
    "lesson_error": "Failed to generate lesson content.",
    "quiz_error": "Failed to generate quiz content.",
    "learnability_error": "Diff was not suitable for learning.",
    "cancelled": "Task was cancelled.",
    "internal_error": "Internal error occurred.",
}

_GENERIC_FALLBACK_MESSAGE = "An unexpected error occurred."

_RECOVERY_HINTS: dict[TaskErrorCode, RecoveryHint] = {
    "network_error": "retry",
    "timeout": "retry",
    "lesson_error": "retry",
    "quiz_error": "retry",
    "config_error": "check_config",
    "permission_error": "check_permissions",
    "learnability_error": "dismiss",
    "claim_error": "retry",
    "cancelled": "none",
    "internal_error": "none",
}
_TASK_ERROR_CODES = frozenset(cast("tuple[str, ...]", get_args(TaskErrorCode)))

_PATH_PATTERN = re.compile(
    r"(?:"
    r"[A-Za-z]:[/\\]"  # drive-letter absolute
    r"|[/\\]{2}"  # UNC \\server
    r"|[/\\]"  # POSIX absolute
    r"|\.\.(?:[/\\])"  # relative traversal ../
    r")[\w.\-]+(?:[/\\][\w.\-]+)*"
)
_URL_HOST_PATTERN = re.compile(r"https?://[^\s/]+")
_MAX_WARNING_LEN = 200


def _sanitize_warning(raw: str) -> str:
    sanitized = _PATH_PATTERN.sub("<path>", raw)
    sanitized = _URL_HOST_PATTERN.sub("<url>", sanitized)
    if len(sanitized) > _MAX_WARNING_LEN:
        sanitized = sanitized[:_MAX_WARNING_LEN] + "…"
    return sanitized


def _task_runner(request: Request) -> Any:
    state = serve_state(request)
    runner = getattr(state, "task_runner", None)
    if runner is None:
        return None
    return runner


def _pin_task(runner: Any, task_id: str) -> bool:
    pin_task = getattr(runner, "pin_task", None)
    if not callable(pin_task):
        return False
    return bool(pin_task(task_id))


def _unpin_task(runner: Any, task_id: str) -> None:
    unpin_task = getattr(runner, "unpin_task", None)
    if callable(unpin_task):
        unpin_task(task_id)


def _build_result_summary(result: Any) -> TaskResultSummary | None:
    if not isinstance(result, Mapping):
        return None
    result_map = cast("Mapping[str, object]", result)
    warnings_raw = result_map.get("warnings")
    warnings_items = cast("list[object]", warnings_raw) if isinstance(warnings_raw, list) else []
    warnings = [_sanitize_warning(str(item)) for item in warnings_items]
    overall_raw = result_map.get("overall")
    if isinstance(overall_raw, int | float):
        val = float(overall_raw)
        overall = (
            val
            if val == val and val != float("inf") and val != float("-inf") and 0 <= val <= 100
            else None
        )
    else:
        overall = None
    return TaskResultSummary(
        run_id=_optional_str(result_map.get("run_id")),
        status=_optional_str(result_map.get("status")),
        overall=overall,
        verdict=_optional_str(result_map.get("verdict")),
        warnings=warnings,
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _user_facing_message(error_code: str, raw_error: str) -> str:
    if raw_error and error_code in (
        "config_error", "internal_error",
        "lesson_error", "quiz_error", "claim_error",
    ):
        return _sanitize_warning(raw_error)
    return _USER_FACING_ERROR_MESSAGES.get(error_code, _GENERIC_FALLBACK_MESSAGE)


def _normalize_task_error_code(value: object) -> TaskErrorCode:
    if isinstance(value, str) and value in _TASK_ERROR_CODES:
        return cast("TaskErrorCode", value)
    return "internal_error"


def _serialize_task(info: Any) -> dict[str, Any]:
    raw_result = getattr(info, "result", None)
    try:
        d = asdict(info)
        d.pop("result", None)
    except Exception:
        d = {k: v for k, v in cast("dict[str, Any]", vars(info)).items() if k != "result"}
    d["status"] = info.status.value
    d["result_summary"] = _build_result_summary(raw_result)
    if isinstance(info.error, str):
        code = _normalize_task_error_code(info.error_code)
        d["error_code"] = code
        d["error"] = _user_facing_message(code, info.error)
        d["recovery_hint"] = _RECOVERY_HINTS[code]
    if info.started_at:
        from datetime import UTC, datetime

        try:
            started = datetime.fromisoformat(info.started_at)
            if info.completed_at:
                ended = datetime.fromisoformat(info.completed_at)
            else:
                ended = datetime.now(UTC)
            d["elapsed_seconds"] = round((ended - started).total_seconds(), 1)
        except (ValueError, TypeError):
            pass
    return TaskInfoResponse.model_validate(d).model_dump(mode="json")


def _sse_event(event: Literal["progress", "error"], data: dict[str, Any]) -> str:
    payload = TaskProgressEvent(event=event, data=data).model_dump(mode="json")
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


async def list_tasks(request: Request) -> JSONResponse:
    runner = _task_runner(request)
    if runner is None:
        return JSONResponse({"tasks": []})
    tasks = runner.list_tasks()
    task_dicts = [_serialize_task(t) for t in tasks]
    payload = TaskListResponse.model_validate({"tasks": task_dicts})
    return JSONResponse(payload.model_dump(mode="json"))


async def get_task(request: Request) -> JSONResponse:
    task_id = request.path_params["task_id"]
    runner = _task_runner(request)
    if runner is None:
        return JSONResponse({"error": "not_found", "status": 404}, status_code=404)
    info = runner.get_task(task_id)
    if info is None:
        return JSONResponse({"error": "not_found", "status": 404}, status_code=404)
    payload = TaskInfoResponse.model_validate(_serialize_task(info))
    return JSONResponse(payload.model_dump(mode="json"))


async def cancel_task(request: Request) -> JSONResponse:
    require_write_token(request)
    task_id = request.path_params["task_id"]
    runner = _task_runner(request)
    if runner is None:
        return JSONResponse({"error": "not_found", "status": 404}, status_code=404)
    cancelled = runner.cancel_task(task_id)
    if not cancelled:
        return JSONResponse({"error": "not_found", "status": 404}, status_code=404)
    return JSONResponse(TaskCancelResponse(cancelled=True).model_dump(mode="json"))


async def task_progress_sse(request: Request) -> StreamingResponse:
    task_id = request.path_params["task_id"]
    runner = _task_runner(request)
    pinned = bool(runner is not None and _pin_task(runner, task_id))

    async def event_generator():  # type: ignore[no-untyped-def]
        try:
            if runner is None or not pinned:
                yield _sse_event("error", {"error": "task not found"})
                return
            while True:
                if await request.is_disconnected():
                    return
                info = runner.get_task(task_id)
                if info is None:
                    yield _sse_event("error", {"error": "task not found"})
                    return
                yield _sse_event("progress", _serialize_task(info))
                if info.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    return
                await asyncio.sleep(0.5)
        finally:
            if runner is not None and pinned:
                _unpin_task(runner, task_id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


__all__ = ["cancel_task", "get_task", "list_tasks", "task_progress_sse"]
