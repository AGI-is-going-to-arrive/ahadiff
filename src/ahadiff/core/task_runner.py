from __future__ import annotations

import asyncio
import logging
import math
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, SupportsFloat, SupportsIndex, cast

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
    step_started_at: str = ""


@dataclass
class TaskInfo:
    task_id: str
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    progress: TaskProgress = field(default_factory=TaskProgress)
    result: Any = None
    error: str | None = None
    error_code: str | None = None
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    timeout_seconds: float | None = None
    deadline_at: str | None = None


class TaskHandle:
    def __init__(self, task_id: str, runner: TaskRunner, loop: asyncio.AbstractEventLoop) -> None:
        self._task_id = task_id
        self._runner = runner
        self._loop = loop
        self._cancelled = False

    def update_progress(self, current: int, total: int, message: str = "") -> None:
        try:
            self._loop.call_soon_threadsafe(
                self._runner.apply_progress_update,
                self._task_id,
                current,
                total,
                message,
            )
        except RuntimeError:
            # The loop may already be closed while a worker thread is unwinding.
            return

    def is_cancelled(self) -> bool:
        return self._cancelled

    def mark_cancelled(self) -> None:
        self._cancelled = True


_MAX_COMPLETED_HISTORY = 100
_MAX_ARCHIVED_LOOKUP = 32


_DEFAULT_TASK_TIMEOUT_SECONDS = 1800.0
_DEFAULT_TASK_TIMEOUT_ENV = "AHADIFF_DEFAULT_TASK_TIMEOUT_SECONDS"
_MAX_TASK_TIMEOUT_SECONDS = 86400.0 * 7  # 7 days max, prevents overflow in datetime arithmetic
_TaskTimeoutValue = str | bytes | bytearray | SupportsFloat | SupportsIndex

log = logging.getLogger(__name__)
_REDACTED_TASK_ERROR = "task failed; error details were redacted"
_PATCH_ERROR_MARKERS = ("diff --git", "--- a/", "+++ b/", "\n--- ", "\n+++ ", "\n@@ ", "@@ -")


def _coerce_task_timeout_seconds(value: object, *, source: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{source} must be a positive finite number")
    try:
        timeout_seconds = float(cast("_TaskTimeoutValue", value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source} must be a positive finite number") from exc
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError(f"{source} must be a positive finite number")
    if timeout_seconds > _MAX_TASK_TIMEOUT_SECONDS:
        timeout_seconds = _MAX_TASK_TIMEOUT_SECONDS
    return timeout_seconds


def _default_task_timeout_seconds() -> float:
    raw_value = os.environ.get(_DEFAULT_TASK_TIMEOUT_ENV)
    if raw_value is None:
        return _DEFAULT_TASK_TIMEOUT_SECONDS
    return _coerce_task_timeout_seconds(raw_value, source=_DEFAULT_TASK_TIMEOUT_ENV)


def _safe_task_error_message(exc: BaseException) -> str:
    try:
        raw = str(exc)
    except Exception:
        return exc.__class__.__name__
    if any(marker in raw for marker in _PATCH_ERROR_MARKERS):
        return _REDACTED_TASK_ERROR
    return raw


class TaskRunner:
    def __init__(
        self,
        max_concurrent: int = 2,
        task_timeout_seconds: float | None = None,
    ) -> None:
        self._tasks: dict[str, TaskInfo] = {}
        self._handles: dict[str, TaskHandle] = {}
        self._async_tasks: dict[str, asyncio.Task[Any]] = {}
        self._archived_tasks: dict[str, TaskInfo] = {}
        self._pinned_tasks: dict[str, int] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._task_timeout = (
            _default_task_timeout_seconds()
            if task_timeout_seconds is None
            else _coerce_task_timeout_seconds(task_timeout_seconds, source="task_timeout_seconds")
        )
        self._task_timeouts: dict[str, float | None] = {}
        self._thread_backed: dict[str, bool] = {}
        self._coro_factories: dict[str, Callable[[TaskHandle], Coroutine[Any, Any, Any]]] = {}
        self._draining_tasks: dict[str, asyncio.Task[Any]] = {}
        self._redacted_error_messages: dict[str, str] = {}

    def submit(
        self,
        task_type: str,
        coro_factory: Callable[[TaskHandle], Coroutine[Any, Any, Any]],
        *,
        task_timeout_seconds: float | None = None,
        thread_backed: bool = False,
        redact_errors: bool = False,
        redacted_error_message: str | None = None,
    ) -> str:
        return self._submit_unchecked(
            task_type,
            coro_factory,
            task_timeout_seconds=task_timeout_seconds,
            thread_backed=thread_backed,
            redact_errors=redact_errors,
            redacted_error_message=redacted_error_message,
        )

    def submit_if_capacity(
        self,
        task_type: str,
        coro_factory: Callable[[TaskHandle], Coroutine[Any, Any, Any]],
        *,
        max_pending: int,
        task_timeout_seconds: float | None = None,
        thread_backed: bool = False,
        redact_errors: bool = False,
        redacted_error_message: str | None = None,
    ) -> str | None:
        pending_count = sum(
            1
            for task_id, info in self._tasks.items()
            if info.task_type == task_type
            and (
                info.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
                or task_id in self._draining_tasks
            )
        )
        if pending_count >= max_pending:
            return None
        return self._submit_unchecked(
            task_type,
            coro_factory,
            task_timeout_seconds=task_timeout_seconds,
            thread_backed=thread_backed,
            redact_errors=redact_errors,
            redacted_error_message=redacted_error_message,
        )

    def _submit_unchecked(
        self,
        task_type: str,
        coro_factory: Callable[[TaskHandle], Coroutine[Any, Any, Any]],
        *,
        task_timeout_seconds: float | None,
        thread_backed: bool,
        redact_errors: bool,
        redacted_error_message: str | None,
    ) -> str:
        loop = asyncio.get_running_loop()
        task_timeout = (
            self._task_timeout
            if task_timeout_seconds is None
            else _coerce_task_timeout_seconds(task_timeout_seconds, source="task_timeout_seconds")
        )
        task_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC)
        info = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            created_at=now.isoformat(),
            timeout_seconds=task_timeout,
            deadline_at=None,
        )
        handle = TaskHandle(task_id, self, loop)
        self._tasks[task_id] = info
        self._handles[task_id] = handle
        self._task_timeouts[task_id] = task_timeout
        self._thread_backed[task_id] = thread_backed
        self._coro_factories[task_id] = coro_factory
        if redact_errors:
            self._redacted_error_messages[task_id] = redacted_error_message or _REDACTED_TASK_ERROR
        async_task = loop.create_task(self._run_task(task_id))
        async_task.add_done_callback(lambda _: self._on_async_task_done(task_id))
        self._async_tasks[task_id] = async_task
        return task_id

    def apply_progress_update(self, task_id: str, current: int, total: int, message: str) -> None:
        info = self.get_task(task_id)
        if info is not None:
            prev = info.progress
            step_changed = prev.current != current or prev.total != total or prev.message != message
            info.progress = TaskProgress(
                current=current,
                total=total,
                message=message,
                step_started_at=(
                    datetime.now(UTC).isoformat() if step_changed else prev.step_started_at
                ),
            )

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

    async def shutdown(self, *, timeout: float = 5.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        for task_id in list(self._tasks):
            self.cancel_task(task_id)
        pending_async = [task for task in self._async_tasks.values() if not task.done()]
        if pending_async:
            _, still_pending = await asyncio.wait(pending_async, timeout=timeout)
            for task in still_pending:
                task.cancel()
            if still_pending:
                await asyncio.gather(*still_pending, return_exceptions=True)
        remaining = max(0.0, deadline - loop.time())
        draining = [task for task in self._draining_tasks.values() if not task.done()]
        if draining and remaining > 0:
            await asyncio.wait(draining, timeout=remaining)

    def cancel_task(self, task_id: str) -> bool:
        handle = self._handles.get(task_id)
        info = self._tasks.get(task_id)
        if handle is None or info is None:
            return False
        if info.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False
        handle.mark_cancelled()
        async_task = self._async_tasks.get(task_id)
        if info.status == TaskStatus.PENDING and async_task is not None and not async_task.done():
            info.status = TaskStatus.CANCELLED
            info.completed_at = datetime.now(UTC).isoformat()
            async_task.cancel()
            self._prune_completed()
        return True

    def _prune_completed(self) -> None:
        done_ids = [
            tid
            for tid, info in self._tasks.items()
            if info.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            and self._pinned_tasks.get(tid, 0) == 0
            and tid not in self._draining_tasks
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
            self._task_timeouts.pop(tid, None)
            self._thread_backed.pop(tid, None)
            self._redacted_error_messages.pop(tid, None)
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

    @staticmethod
    def _classify_error(exc: Exception) -> str:
        if isinstance(exc, ConnectionError):
            return "network_error"
        if isinstance(exc, PermissionError):
            return "permission_error"
        from ahadiff.contracts import ErrorCode
        from ahadiff.core.errors import (
            AhaDiffError,
            ConfigError,
            ProviderError,
            SafetyError,
            VerificationError,
        )

        if isinstance(exc, AhaDiffError) and exc.code is ErrorCode.LOCK_CONFLICT:
            return "lock_conflict"
        if isinstance(exc, ConfigError):
            return "config_error"
        if isinstance(exc, ProviderError):
            try:
                provider_msg = str(exc).lower()
            except Exception:
                provider_msg = ""
            _transient = (
                "transport",
                "decompression",
                "rate limit",
                "timeout",
                "connection",
                "503",
                "429",
                "retryable status",
            )
            if any(t in provider_msg for t in _transient):
                return "network_error"
            return "config_error"
        if isinstance(exc, SafetyError):
            return "permission_error"
        if isinstance(exc, VerificationError):
            return "claim_error"
        try:
            error_msg = str(exc).lower()
        except Exception:
            return "internal_error"
        if not error_msg:
            return "internal_error"
        if "cancelled" in error_msg:
            return "cancelled"
        if (
            "invalid provider" in error_msg
            or "provider configuration" in error_msg
            or "requires --provider" in error_msg
            or "requires --base-url" in error_msg
        ):
            return "config_error"
        _claim = (
            "claim extraction",
            "claim_extraction",
            "claim verification",
            "references line outside patch",
        )
        if any(k in error_msg for k in _claim):
            return "claim_error"
        if "lesson generation" in error_msg:
            return "lesson_error"
        if "quiz generation" in error_msg:
            return "quiz_error"
        if "learnability" in error_msg:
            return "learnability_error"
        if "permission" in error_msg or "denied" in error_msg:
            return "permission_error"
        _net = ("connection refused", "connection reset", "network error", "transport error")
        if any(t in error_msg for t in _net):
            return "network_error"
        return "internal_error"

    def _task_error_message(self, task_id: str, exc: BaseException) -> str:
        redacted_message = self._redacted_error_messages.get(task_id)
        if redacted_message is not None:
            return redacted_message
        return _safe_task_error_message(exc)

    def _task_error_code(self, task_id: str, exc: Exception) -> str:
        if task_id in self._redacted_error_messages:
            return "internal_error"
        return self._classify_error(exc)

    def _on_async_task_done(self, task_id: str) -> None:
        self._async_tasks.pop(task_id, None)
        self._coro_factories.pop(task_id, None)
        self._task_timeouts.pop(task_id, None)
        if task_id not in self._draining_tasks:
            self._redacted_error_messages.pop(task_id, None)
        self._prune_completed()

    def _on_draining_task_done(self, task_id: str, task: asyncio.Task[Any]) -> None:
        self._draining_tasks.pop(task_id, None)
        self._thread_backed.pop(task_id, None)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if task_id in self._redacted_error_messages:
                exc_type = exc.__class__.__name__[:80]
                log.debug(
                    "background thread-backed redacted task exited after timeout with %s",
                    exc_type,
                )
            else:
                log.debug("background thread-backed task exited after timeout", exc_info=True)
        self._redacted_error_messages.pop(task_id, None)
        self._semaphore.release()
        self._prune_completed()

    async def _run_task(self, task_id: str) -> None:
        info = self._tasks.get(task_id)
        handle = self._handles.get(task_id)
        coro_factory = self._coro_factories.pop(task_id, None)
        if info is None or handle is None or coro_factory is None:
            return

        await self._semaphore.acquire()
        stored_timeout = self._task_timeouts.get(task_id, self._task_timeout)
        task_timeout: float = self._task_timeout if stored_timeout is None else stored_timeout
        timeout_cm: asyncio.Timeout | None = None
        thread_backed = self._thread_backed.get(task_id, False)
        worker_task: asyncio.Task[Any] | None = None
        draining_registered = False
        try:
            if handle.is_cancelled():
                if info.status != TaskStatus.CANCELLED:
                    info.status = TaskStatus.CANCELLED
                    info.completed_at = datetime.now(UTC).isoformat()
                return

            now = datetime.now(UTC)
            info.status = TaskStatus.RUNNING
            info.started_at = now.isoformat()
            info.deadline_at = (now + timedelta(seconds=task_timeout)).isoformat()
            worker_task = asyncio.create_task(coro_factory(handle))

            async with asyncio.timeout(task_timeout) as timeout_cm:
                if thread_backed:
                    result = await asyncio.shield(worker_task)
                else:
                    result = await worker_task

            if handle.is_cancelled():
                info.status = TaskStatus.CANCELLED
                info.completed_at = datetime.now(UTC).isoformat()
            else:
                info.status = TaskStatus.COMPLETED
                info.result = result
                info.completed_at = datetime.now(UTC).isoformat()
        except TimeoutError as timeout_exc:
            if handle.is_cancelled():
                info.status = TaskStatus.CANCELLED
                info.completed_at = datetime.now(UTC).isoformat()
            elif timeout_cm is not None and timeout_cm.expired():
                handle.mark_cancelled()
                info.status = TaskStatus.FAILED
                info.error = self._redacted_error_messages.get(
                    task_id,
                    f"task exceeded {task_timeout}s timeout",
                )
                info.error_code = "timeout"
                info.completed_at = datetime.now(UTC).isoformat()
                if thread_backed and worker_task is not None and not worker_task.done():
                    draining_registered = True
                    self._draining_tasks[task_id] = worker_task
                    worker_task.add_done_callback(
                        lambda completed_task, current_task_id=task_id: self._on_draining_task_done(
                            current_task_id,
                            completed_task,
                        )
                    )
            else:
                info.status = TaskStatus.FAILED
                info.error = (
                    self._task_error_message(task_id, timeout_exc) or "task-internal timeout"
                )
                info.error_code = self._task_error_code(task_id, timeout_exc)
                info.completed_at = datetime.now(UTC).isoformat()
        except asyncio.CancelledError:
            handle.mark_cancelled()
            if thread_backed and worker_task is not None and not worker_task.done():
                draining_registered = True
                self._draining_tasks[task_id] = worker_task
                worker_task.add_done_callback(
                    lambda completed_task, current_task_id=task_id: self._on_draining_task_done(
                        current_task_id,
                        completed_task,
                    )
                )
            if info.status != TaskStatus.CANCELLED:
                info.status = TaskStatus.CANCELLED
                info.completed_at = datetime.now(UTC).isoformat()
        except Exception as exc:
            log.error("task %s failed with %s", task_id, type(exc).__name__)
            if handle.is_cancelled():
                info.status = TaskStatus.CANCELLED
                info.completed_at = datetime.now(UTC).isoformat()
            else:
                info.status = TaskStatus.FAILED
                info.error = self._task_error_message(task_id, exc)
                info.error_code = self._task_error_code(task_id, exc)
                info.completed_at = datetime.now(UTC).isoformat()
        finally:
            if not draining_registered:
                self._semaphore.release()
            self._prune_completed()


__all__ = [
    "TaskHandle",
    "TaskInfo",
    "TaskProgress",
    "TaskRunner",
    "TaskStatus",
]
