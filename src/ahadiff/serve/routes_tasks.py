from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal, cast

from starlette.responses import JSONResponse, StreamingResponse

from ahadiff.contracts.serve_runtime import (
    TaskCancelResponse,
    TaskInfoResponse,
    TaskListResponse,
    TaskProgressEvent,
    TaskResultSummary,
)
from ahadiff.core.task_runner import TaskStatus

from .auth import require_write_token, serve_state

if TYPE_CHECKING:
    from starlette.requests import Request


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
    warnings = [str(item) for item in warnings_items]
    overall_raw = result_map.get("overall")
    overall = float(overall_raw) if isinstance(overall_raw, int | float) else None
    return TaskResultSummary(
        run_id=_optional_str(result_map.get("run_id")),
        status=_optional_str(result_map.get("status")),
        overall=overall,
        verdict=_optional_str(result_map.get("verdict")),
        warnings=warnings,
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _serialize_task(info: Any) -> dict[str, Any]:
    d = asdict(info)
    d["status"] = info.status.value
    d["result_summary"] = _build_result_summary(info.result)
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
    task_payloads = [TaskInfoResponse.model_validate(_serialize_task(t)) for t in tasks]
    payload = TaskListResponse(tasks=task_payloads)
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
