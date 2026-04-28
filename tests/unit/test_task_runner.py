from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, cast

import anyio
import pytest

from ahadiff.core.task_runner import TaskHandle, TaskRunner, TaskStatus

if TYPE_CHECKING:
    from pathlib import Path


def _run(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def test_submit_and_complete() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)

        async def work(handle: TaskHandle) -> str:
            return "done"

        task_id = runner.submit("test", work)
        await asyncio.sleep(0.1)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.COMPLETED
        assert info.result == "done"
        assert info.completed_at is not None
        assert info.started_at is not None

    _run(_inner())


def test_progress_updates() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)
        barrier = asyncio.Event()

        async def work(handle: TaskHandle) -> None:
            handle.update_progress(1, 10, "step 1")
            barrier.set()
            await asyncio.sleep(0.05)

        task_id = runner.submit("test", work)
        await barrier.wait()
        info = runner.get_task(task_id)
        assert info is not None
        assert info.progress.current == 1
        assert info.progress.total == 10
        assert info.progress.message == "step 1"
        await asyncio.sleep(0.1)

    _run(_inner())


def test_to_thread_run_sync_progress_cancel_and_result_integration(tmp_path: Path) -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1)
        started = threading.Event()
        release = threading.Event()
        artifact_path = tmp_path / "should-not-exist.txt"

        async def cancellable_work(handle: TaskHandle) -> dict[str, str]:
            def _sync_job() -> dict[str, str]:
                handle.update_progress(1, 10, "thread-started")
                started.set()
                release.wait(timeout=1.0)
                if handle.is_cancelled():
                    raise AhaDiffError("cancelled")
                artifact_path.write_text("finished\n", encoding="utf-8")
                return {"run_id": "thread-run"}

            return await anyio.to_thread.run_sync(_sync_job)

        task_id = runner.submit("learn", cancellable_work)
        deadline = asyncio.get_running_loop().time() + 1.0
        while not started.is_set() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        assert started.is_set()

        running = runner.get_task(task_id)
        assert running is not None
        assert running.progress.current == 1
        assert running.progress.total == 10
        assert running.progress.message == "thread-started"

        assert runner.cancel_task(task_id) is True
        await asyncio.sleep(0.05)

        cancelling = runner.get_task(task_id)
        assert cancelling is not None
        assert cancelling.status == TaskStatus.RUNNING
        assert cancelling.result is None

        release.set()
        await asyncio.sleep(0.05)

        cancelled = runner.get_task(task_id)
        assert cancelled is not None
        assert cancelled.status == TaskStatus.CANCELLED
        assert cancelled.result is None
        assert not artifact_path.exists()

    from ahadiff.core.errors import AhaDiffError

    _run(_inner())


def test_cancel_task() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)
        started = asyncio.Event()

        async def work(handle: TaskHandle) -> None:
            started.set()
            while not handle.is_cancelled():
                await asyncio.sleep(0.01)

        task_id = runner.submit("test", work)
        await started.wait()
        assert runner.cancel_task(task_id) is True
        await asyncio.sleep(0.1)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.CANCELLED

    _run(_inner())


def test_cancel_nonexistent() -> None:
    runner = TaskRunner(max_concurrent=2)
    assert runner.cancel_task("nonexistent") is False


def test_cancel_completed_task() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)

        async def work(handle: TaskHandle) -> str:
            return "ok"

        task_id = runner.submit("test", work)
        await asyncio.sleep(0.1)
        assert runner.cancel_task(task_id) is False

    _run(_inner())


def test_cancel_queued_task_cleans_async_task_and_factory() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1)
        gate = asyncio.Event()

        async def blocking_work(handle: TaskHandle) -> None:
            await gate.wait()

        async def queued_work(handle: TaskHandle) -> None:
            raise AssertionError("cancelled queued task should never run")

        runner.submit("block", blocking_work)
        queued_id = runner.submit("queued", queued_work)
        await asyncio.sleep(0.05)

        assert runner.cancel_task(queued_id) is True
        await asyncio.sleep(0.05)

        info = runner.get_task(queued_id)
        assert info is not None
        assert info.status == TaskStatus.CANCELLED
        async_tasks = cast("dict[str, object]", runner.__dict__["_async_tasks"])
        coro_factories = cast("dict[str, object]", runner.__dict__["_coro_factories"])
        assert queued_id not in async_tasks
        assert queued_id not in coro_factories

        gate.set()
        await asyncio.sleep(0.05)

    _run(_inner())


def test_max_concurrent_limit() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)
        gate = asyncio.Event()

        async def blocking_work(handle: TaskHandle) -> None:
            await gate.wait()

        async def quick_work(handle: TaskHandle) -> None:
            pass

        runner.submit("block", blocking_work)
        runner.submit("block", blocking_work)
        id3 = runner.submit("quick", quick_work)

        await asyncio.sleep(0.1)

        info3 = runner.get_task(id3)
        assert info3 is not None
        assert info3.status == TaskStatus.PENDING

        gate.set()
        await asyncio.sleep(0.1)

        info3 = runner.get_task(id3)
        assert info3 is not None
        assert info3.status == TaskStatus.COMPLETED

    _run(_inner())


def test_list_tasks() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)
        assert runner.list_tasks() == []

        async def work(handle: TaskHandle) -> None:
            pass

        runner.submit("a", work)
        runner.submit("b", work)
        await asyncio.sleep(0.1)
        tasks = runner.list_tasks()
        assert len(tasks) == 2
        types = {t.task_type for t in tasks}
        assert types == {"a", "b"}

    _run(_inner())


def test_get_nonexistent() -> None:
    runner = TaskRunner(max_concurrent=2)
    assert runner.get_task("does-not-exist") is None


def test_task_failure() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)

        async def failing(handle: TaskHandle) -> None:
            raise ValueError("something broke")

        task_id = runner.submit("fail", failing)
        await asyncio.sleep(0.1)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.error == "something broke"
        assert info.completed_at is not None

    _run(_inner())


def test_direct_asyncio_cancel_marks_task_cancelled() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1)
        started = asyncio.Event()
        task_ref: asyncio.Future[asyncio.Task[None]] = asyncio.Future()

        async def work(handle: TaskHandle) -> None:
            started.set()
            current = asyncio.current_task()
            assert current is not None
            task_ref.set_result(current)
            await asyncio.sleep(10)

        task_id = runner.submit("cancel-me", work)
        await started.wait()
        (await task_ref).cancel()
        await asyncio.sleep(0.05)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.CANCELLED
        assert info.completed_at is not None

    _run(_inner())


def test_prune_drops_oldest_completed_first_and_keeps_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1)
        task_ids: list[str] = []

        async def work(handle: TaskHandle) -> str:
            return "done"

        for _ in range(3):
            task_ids.append(runner.submit("done", work))
            await asyncio.sleep(0.05)

        visible_ids = [task.task_id for task in runner.list_tasks()]
        assert len(visible_ids) == 2
        assert task_ids[0] not in visible_ids
        assert visible_ids == task_ids[1:]

        pruned = runner.get_task(task_ids[0])
        assert pruned is not None
        assert pruned.status == TaskStatus.COMPLETED

    monkeypatch.setattr("ahadiff.core.task_runner._MAX_COMPLETED_HISTORY", 2)
    monkeypatch.setattr("ahadiff.core.task_runner._MAX_ARCHIVED_LOOKUP", 4)
    _run(_inner())


def test_pin_task_prevents_prune_until_unpinned(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1)

        async def work(handle: TaskHandle) -> str:
            return "done"

        task_a = runner.submit("done", work)
        await asyncio.sleep(0.05)
        assert runner.pin_task(task_a) is True

        task_b = runner.submit("done", work)
        await asyncio.sleep(0.05)

        visible_ids = [task.task_id for task in runner.list_tasks()]
        assert visible_ids == [task_a, task_b]

        runner.unpin_task(task_a)
        await asyncio.sleep(0)

        visible_ids = [task.task_id for task in runner.list_tasks()]
        assert visible_ids == [task_b]
        archived = runner.get_task(task_a)
        assert archived is not None
        assert archived.status == TaskStatus.COMPLETED

    monkeypatch.setattr("ahadiff.core.task_runner._MAX_COMPLETED_HISTORY", 1)
    monkeypatch.setattr("ahadiff.core.task_runner._MAX_ARCHIVED_LOOKUP", 4)
    _run(_inner())


def test_pinned_archived_task_survives_archived_lookup_eviction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1)
        task_ids: list[str] = []

        async def work(handle: TaskHandle) -> str:
            return "done"

        for _ in range(4):
            task_ids.append(runner.submit("done", work))
            await asyncio.sleep(0.05)

        archived_id = task_ids[0]
        assert runner.pin_task(archived_id) is True

        for _ in range(3):
            runner.submit("done", work)
            await asyncio.sleep(0.05)

        pinned_archived = runner.get_task(archived_id)
        assert pinned_archived is not None
        assert pinned_archived.status == TaskStatus.COMPLETED

        runner.unpin_task(archived_id)
        runner.submit("done", work)
        await asyncio.sleep(0.05)

        assert runner.get_task(archived_id) is None

    monkeypatch.setattr("ahadiff.core.task_runner._MAX_COMPLETED_HISTORY", 2)
    monkeypatch.setattr("ahadiff.core.task_runner._MAX_ARCHIVED_LOOKUP", 2)
    _run(_inner())


def test_submit_requires_running_loop() -> None:
    runner = TaskRunner(max_concurrent=1)

    async def work(handle: TaskHandle) -> None:
        return None

    with pytest.raises(RuntimeError, match="running event loop"):
        runner.submit("no-loop", work)
