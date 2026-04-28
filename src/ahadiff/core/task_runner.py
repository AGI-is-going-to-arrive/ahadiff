from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskProgress:
    current: int = 0
    total: int = 0
    message: str = ""


@dataclass
class TaskInfo:
    task_id: str
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    progress: TaskProgress = field(default_factory=TaskProgress)
    result: Any = None
    error: str | None = None
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None


class TaskHandle:
    def __init__(self, task_id: str, runner: TaskRunner) -> None:
        self._task_id = task_id
        self._runner = runner
        self._cancelled = False

    def update_progress(self, current: int, total: int, message: str = "") -> None:
        info = self._runner.get_task(self._task_id)
        if info is not None:
            info.progress = TaskProgress(current=current, total=total, message=message)

    def is_cancelled(self) -> bool:
        return self._cancelled

    def mark_cancelled(self) -> None:
        self._cancelled = True


_MAX_COMPLETED_HISTORY = 100
_MAX_ARCHIVED_LOOKUP = 32


class TaskRunner:
    def __init__(self, max_concurrent: int = 2) -> None:
        self._tasks: dict[str, TaskInfo] = {}
        self._handles: dict[str, TaskHandle] = {}
        self._async_tasks: dict[str, asyncio.Task[Any]] = {}
        self._archived_tasks: dict[str, TaskInfo] = {}
        self._pinned_tasks: dict[str, int] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._coro_factories: dict[str, Callable[[TaskHandle], Coroutine[Any, Any, Any]]] = {}

    def submit(
        self,
        task_type: str,
        coro_factory: Callable[[TaskHandle], Coroutine[Any, Any, Any]],
    ) -> str:
        loop = asyncio.get_running_loop()
        task_id = uuid.uuid4().hex[:12]
        info = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            created_at=datetime.now(UTC).isoformat(),
        )
        handle = TaskHandle(task_id, self)
        self._tasks[task_id] = info
        self._handles[task_id] = handle
        self._coro_factories[task_id] = coro_factory
        async_task = loop.create_task(self._run_task(task_id))
        async_task.add_done_callback(lambda _done, tid=task_id: self._on_async_task_done(tid))
        self._async_tasks[task_id] = async_task
        return task_id

    def get_task(self, task_id: str) -> TaskInfo | None:
        return self._tasks.get(task_id) or self._archived_tasks.get(task_id)

    def list_tasks(self) -> list[TaskInfo]:
        return list(self._tasks.values())

    def pin_task(self, task_id: str) -> bool:
        if self.get_task(task_id) is None:
            return False
        self._pinned_tasks[task_id] = self._pinned_tasks.get(task_id, 0) + 1
        return True

    def unpin_task(self, task_id: str) -> None:
        current = self._pinned_tasks.get(task_id)
        if current is None:
            return
        if current <= 1:
            self._pinned_tasks.pop(task_id, None)
        else:
            self._pinned_tasks[task_id] = current - 1
        self._prune_completed()
        self._trim_archived_tasks()

    def cancel_task(self, task_id: str) -> bool:
        handle = self._handles.get(task_id)
        info = self._tasks.get(task_id)
        if handle is None or info is None:
            return False
        if info.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False
        handle.mark_cancelled()
        info.status = TaskStatus.CANCELLED
        info.completed_at = datetime.now(UTC).isoformat()
        async_task = self._async_tasks.get(task_id)
        if async_task is not None and not async_task.done():
            async_task.cancel()
        self._prune_completed()
        return True

    def _prune_completed(self) -> None:
        done_ids = [
            tid
            for tid, info in self._tasks.items()
            if info.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            and self._pinned_tasks.get(tid, 0) == 0
        ]
        excess = len(done_ids) - _MAX_COMPLETED_HISTORY
        if excess <= 0:
            return
        prune_ids = sorted(done_ids, key=lambda tid: self._tasks[tid].created_at)[:excess]
        for tid in prune_ids:
            info = self._tasks.pop(tid, None)
            if info is not None:
                self._archived_tasks[tid] = info
            self._handles.pop(tid, None)
            self._async_tasks.pop(tid, None)
        self._trim_archived_tasks()

    def _trim_archived_tasks(self) -> None:
        while len(self._archived_tasks) > _MAX_ARCHIVED_LOOKUP:
            evict_task_id = next(
                (
                    candidate
                    for candidate in self._archived_tasks
                    if self._pinned_tasks.get(candidate, 0) == 0
                ),
                None,
            )
            if evict_task_id is None:
                return
            self._archived_tasks.pop(evict_task_id, None)

    def _on_async_task_done(self, task_id: str) -> None:
        self._async_tasks.pop(task_id, None)
        self._coro_factories.pop(task_id, None)
        self._prune_completed()

    async def _run_task(self, task_id: str) -> None:
        info = self._tasks.get(task_id)
        handle = self._handles.get(task_id)
        coro_factory = self._coro_factories.pop(task_id, None)
        if info is None or handle is None or coro_factory is None:
            return

        await self._semaphore.acquire()
        try:
            if handle.is_cancelled():
                return

            info.status = TaskStatus.RUNNING
            info.started_at = datetime.now(UTC).isoformat()

            result = await coro_factory(handle)
            if not handle.is_cancelled():
                info.status = TaskStatus.COMPLETED
                info.result = result
                info.completed_at = datetime.now(UTC).isoformat()
        except asyncio.CancelledError:
            handle.mark_cancelled()
            if info.status != TaskStatus.CANCELLED:
                info.status = TaskStatus.CANCELLED
                info.completed_at = datetime.now(UTC).isoformat()
        except Exception as exc:
            if not handle.is_cancelled():
                info.status = TaskStatus.FAILED
                info.error = str(exc)
                info.completed_at = datetime.now(UTC).isoformat()
        finally:
            self._semaphore.release()
            self._prune_completed()


__all__ = [
    "TaskHandle",
    "TaskInfo",
    "TaskProgress",
    "TaskRunner",
    "TaskStatus",
]
