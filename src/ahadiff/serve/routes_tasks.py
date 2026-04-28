from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse, StreamingResponse

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


def _serialize_task(info: Any) -> dict[str, Any]:
    d = asdict(info)
    d["status"] = info.status.value
    return d


async def list_tasks(request: Request) -> JSONResponse:
    runner = _task_runner(request)
    if runner is None:
        return JSONResponse({"tasks": []})
    tasks = runner.list_tasks()
    return JSONResponse({"tasks": [_serialize_task(t) for t in tasks]})


async def get_task(request: Request) -> JSONResponse:
    task_id = request.path_params["task_id"]
    runner = _task_runner(request)
    if runner is None:
        return JSONResponse({"error": "not_found", "status": 404}, status_code=404)
    info = runner.get_task(task_id)
    if info is None:
        return JSONResponse({"error": "not_found", "status": 404}, status_code=404)
    return JSONResponse(_serialize_task(info))


async def cancel_task(request: Request) -> JSONResponse:
    require_write_token(request)
    task_id = request.path_params["task_id"]
    runner = _task_runner(request)
    if runner is None:
        return JSONResponse({"error": "not_found", "status": 404}, status_code=404)
    cancelled = runner.cancel_task(task_id)
    if not cancelled:
        return JSONResponse({"error": "not_found", "status": 404}, status_code=404)
    return JSONResponse({"cancelled": True})


async def task_progress_sse(request: Request) -> StreamingResponse:
    task_id = request.path_params["task_id"]
    runner = _task_runner(request)
    pinned = bool(runner is not None and _pin_task(runner, task_id))

    async def event_generator():  # type: ignore[no-untyped-def]
        try:
            if runner is None or not pinned:
                yield f"event: error\ndata: {json.dumps({'error': 'task not found'})}\n\n"
                return
            while True:
                if await request.is_disconnected():
                    return
                info = runner.get_task(task_id)
                if info is None:
                    yield f"event: error\ndata: {json.dumps({'error': 'task not found'})}\n\n"
                    return
                yield f"event: progress\ndata: {json.dumps(_serialize_task(info))}\n\n"
                if info.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    return
                await asyncio.sleep(0.5)
        finally:
            if runner is not None and pinned:
                _unpin_task(runner, task_id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


__all__ = ["cancel_task", "get_task", "list_tasks", "task_progress_sse"]
