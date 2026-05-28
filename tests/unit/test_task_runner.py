from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest
from anyio.to_thread import run_sync as run_sync_in_thread

from ahadiff.core.task_runner import TaskHandle, TaskRunner, TaskStatus

if TYPE_CHECKING:
    from pathlib import Path


def _run(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def _task_timeout_seconds(runner: TaskRunner) -> float:
    timeout = runner.__dict__["_task_timeout"]
    assert isinstance(timeout, float)
    return timeout


def _default_task_timeout_seconds() -> float:
    import ahadiff.core.task_runner as task_runner_module

    timeout = task_runner_module.__dict__["_DEFAULT_TASK_TIMEOUT_SECONDS"]
    assert isinstance(timeout, float)
    return timeout


def _parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
    return parsed


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


def test_submit_sets_task_timeout_and_deadline_metadata() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1, task_timeout_seconds=60.0)
        release = asyncio.Event()

        async def work(handle: TaskHandle) -> None:
            await release.wait()

        task_id = runner.submit("learn", work, task_timeout_seconds=12.5)
        try:
            # Pending tasks have timeout metadata but no deadline yet.
            info = runner.get_task(task_id)
            assert info is not None
            assert info.timeout_seconds == 12.5
            assert info.status == TaskStatus.PENDING
            assert info.deadline_at is None

            # Once the task acquires the semaphore and transitions to
            # RUNNING, deadline_at is computed from started_at.
            for _ in range(50):
                await asyncio.sleep(0.01)
                info = runner.get_task(task_id)
                assert info is not None
                if info.status == TaskStatus.RUNNING:
                    break
            assert info is not None
            assert info.status == TaskStatus.RUNNING
            timeout_seconds = info.timeout_seconds
            deadline_at = info.deadline_at
            started_at_str = info.started_at
            assert timeout_seconds is not None
            assert timeout_seconds == 12.5
            assert isinstance(deadline_at, str)
            assert isinstance(started_at_str, str)

            started_at = _parse_utc_datetime(started_at_str)
            deadline = _parse_utc_datetime(deadline_at)
            assert abs((deadline - started_at).total_seconds() - timeout_seconds) <= 0.5
        finally:
            release.set()
            await asyncio.sleep(0.05)

    _run(_inner())


def test_pending_task_has_no_deadline() -> None:
    """C1: deadline_at must reflect actual run start, not submit time.

    A queued (PENDING) task waiting on a saturated semaphore has no
    meaningful deadline yet — deadline_at must be None until the task
    transitions to RUNNING.
    """

    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1, task_timeout_seconds=60.0)
        release_first = asyncio.Event()
        first_running = asyncio.Event()

        async def first_work(handle: TaskHandle) -> None:
            first_running.set()
            await release_first.wait()

        async def queued_work(handle: TaskHandle) -> None:
            return None

        first_id = runner.submit("learn", first_work, task_timeout_seconds=30.0)
        await first_running.wait()
        queued_id = runner.submit("learn", queued_work, task_timeout_seconds=12.5)
        try:
            # Give the event loop a turn so _run_task can run up to the
            # semaphore acquire for the queued task.
            await asyncio.sleep(0.05)
            queued_info = runner.get_task(queued_id)
            assert queued_info is not None
            assert queued_info.status == TaskStatus.PENDING
            assert queued_info.deadline_at is None
            assert queued_info.timeout_seconds == 12.5
            assert queued_info.started_at is None
        finally:
            release_first.set()
            # Drain to completion.
            for _ in range(100):
                await asyncio.sleep(0.01)
                first_info = runner.get_task(first_id)
                queued_info = runner.get_task(queued_id)
                if (
                    first_info is not None
                    and queued_info is not None
                    and first_info.status == TaskStatus.COMPLETED
                    and queued_info.status == TaskStatus.COMPLETED
                ):
                    break

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

            return await run_sync_in_thread(_sync_job)

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


# ---------------------------------------------------------------------------
# Phase 6B: timeout, error_code, elapsed_seconds
# ---------------------------------------------------------------------------


def test_task_timeout_triggers_failure() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2, task_timeout_seconds=0.1)

        async def slow_work(handle: TaskHandle) -> None:
            await asyncio.sleep(10)

        task_id = runner.submit("slow", slow_work)
        await asyncio.sleep(0.5)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.error_code == "timeout"
        assert "timeout" in (info.error or "")

    _run(_inner())


def test_submit_uses_per_task_timeout_override_for_thread_backed_work(
    tmp_path: Path,
) -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2, task_timeout_seconds=60.0)
        started = threading.Event()
        release = threading.Event()
        handle_ref: list[TaskHandle] = []
        artifact_path = tmp_path / "finished.txt"

        async def thread_work(handle: TaskHandle) -> str:
            handle_ref.append(handle)

            def _sync_job() -> str:
                started.set()
                release.wait(timeout=1.0)
                if not handle.is_cancelled():
                    artifact_path.write_text("finished\n", encoding="utf-8")
                return "done"

            return await run_sync_in_thread(_sync_job)

        task_id = runner.submit("learn", thread_work, task_timeout_seconds=0.05)
        deadline = asyncio.get_running_loop().time() + 1.0
        while not started.is_set() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        assert started.is_set()

        await asyncio.sleep(0.15)
        failed = runner.get_task(task_id)
        assert failed is not None
        assert failed.status == TaskStatus.FAILED
        assert failed.error_code == "timeout"
        assert len(handle_ref) == 1
        assert handle_ref[0].is_cancelled() is True
        assert not artifact_path.exists()

        release.set()
        await asyncio.sleep(0.1)

        still_failed = runner.get_task(task_id)
        assert still_failed is not None
        assert still_failed.status == TaskStatus.FAILED
        assert still_failed.result is None
        assert not artifact_path.exists()

    _run(_inner())


def test_submit_if_capacity_blocks_thread_backed_task_while_timeout_is_draining() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2, task_timeout_seconds=60.0)
        started = threading.Event()
        release = threading.Event()

        async def thread_work(handle: TaskHandle) -> str:
            del handle

            def _sync_job() -> str:
                started.set()
                release.wait(timeout=1.0)
                return "done"

            return await run_sync_in_thread(_sync_job)

        task_id = runner.submit(
            "learn",
            thread_work,
            task_timeout_seconds=0.05,
            thread_backed=True,
        )
        deadline = asyncio.get_running_loop().time() + 1.0
        while not started.is_set() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        assert started.is_set()

        await asyncio.sleep(0.15)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.error_code == "timeout"
        assert (
            runner.submit_if_capacity(
                "learn",
                thread_work,
                max_pending=1,
                thread_backed=True,
            )
            is None
        )

        release.set()
        deadline = asyncio.get_running_loop().time() + 1.0
        while (
            task_id in runner.__dict__["_draining_tasks"]
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.sleep(0.01)

        next_task_id = runner.submit_if_capacity(
            "learn",
            thread_work,
            max_pending=1,
            thread_backed=True,
        )
        assert isinstance(next_task_id, str)
        runner.cancel_task(next_task_id)
        await asyncio.sleep(0.1)

    _run(_inner())


def test_shutdown_keeps_thread_backed_worker_tracked_until_it_finishes(tmp_path: Path) -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1, task_timeout_seconds=60.0)
        started = threading.Event()
        release = threading.Event()
        artifact_path = tmp_path / "finished-after-shutdown.txt"

        async def thread_work(handle: TaskHandle) -> str:
            del handle

            def _sync_job() -> str:
                started.set()
                release.wait(timeout=1.0)
                artifact_path.write_text("done\n", encoding="utf-8")
                return "done"

            return await run_sync_in_thread(_sync_job)

        task_id = runner.submit("learn", thread_work, thread_backed=True)
        assert await run_sync_in_thread(lambda: started.wait(timeout=1.0))

        await runner.shutdown(timeout=0.05)

        assert task_id in runner.__dict__["_draining_tasks"]
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.CANCELLED

        release.set()
        deadline = asyncio.get_running_loop().time() + 1.0
        while (
            task_id in runner.__dict__["_draining_tasks"]
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.sleep(0.01)

        assert task_id not in runner.__dict__["_draining_tasks"]
        assert artifact_path.exists()

    _run(_inner())


def test_shutdown_does_not_untrack_already_draining_thread_worker(tmp_path: Path) -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1, task_timeout_seconds=60.0)
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        artifact_path = tmp_path / "finished-after-drain-shutdown.txt"

        async def thread_work(handle: TaskHandle) -> str:
            del handle

            def _sync_job() -> str:
                started.set()
                release.wait(timeout=1.0)
                artifact_path.write_text("done\n", encoding="utf-8")
                finished.set()
                return "done"

            return await run_sync_in_thread(_sync_job)

        task_id = runner.submit(
            "learn",
            thread_work,
            task_timeout_seconds=0.05,
            thread_backed=True,
        )
        assert await run_sync_in_thread(lambda: started.wait(timeout=1.0))
        await asyncio.sleep(0.15)

        assert task_id in runner.__dict__["_draining_tasks"]
        await runner.shutdown(timeout=0.05)

        assert task_id in runner.__dict__["_draining_tasks"]
        assert finished.is_set() is False
        assert not artifact_path.exists()

        release.set()
        deadline = asyncio.get_running_loop().time() + 1.0
        while (
            task_id in runner.__dict__["_draining_tasks"]
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.sleep(0.01)

        assert task_id not in runner.__dict__["_draining_tasks"]
        assert finished.is_set() is True
        assert artifact_path.exists()

    _run(_inner())


def test_thread_backed_draining_task_keeps_global_concurrency_slot() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1, task_timeout_seconds=60.0)
        first_started = threading.Event()
        release_first = threading.Event()
        second_started = asyncio.Event()

        async def thread_work(handle: TaskHandle) -> str:
            del handle

            def _sync_job() -> str:
                first_started.set()
                release_first.wait(timeout=1.0)
                return "done"

            return await run_sync_in_thread(_sync_job)

        async def second_work(handle: TaskHandle) -> str:
            del handle
            second_started.set()
            return "second"

        first_task_id = runner.submit(
            "learn",
            thread_work,
            task_timeout_seconds=0.05,
            thread_backed=True,
        )
        assert await run_sync_in_thread(lambda: first_started.wait(timeout=1.0))
        await asyncio.sleep(0.15)

        second_task_id = runner.submit("index", second_work)
        await asyncio.sleep(0.1)

        first_info = runner.get_task(first_task_id)
        second_info = runner.get_task(second_task_id)
        assert first_info is not None
        assert first_info.status == TaskStatus.FAILED
        assert second_info is not None
        assert second_info.status == TaskStatus.PENDING
        assert not second_started.is_set()

        release_first.set()
        await asyncio.wait_for(second_started.wait(), timeout=1.0)

        deadline = asyncio.get_running_loop().time() + 1.0
        completed = runner.get_task(second_task_id)
        while (
            completed is not None
            and completed.status != TaskStatus.COMPLETED
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.sleep(0.01)
            completed = runner.get_task(second_task_id)

        assert completed is not None
        assert completed.status == TaskStatus.COMPLETED

    _run(_inner())


def test_draining_thread_backed_task_keeps_timeout_failure_on_success() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2, task_timeout_seconds=60.0)
        started = threading.Event()
        release = threading.Event()

        async def thread_work(handle: TaskHandle) -> str:
            del handle

            def _sync_job() -> str:
                started.set()
                release.wait(timeout=2.0)
                return "pipeline-ok"

            return await run_sync_in_thread(_sync_job)

        task_id = runner.submit(
            "learn",
            thread_work,
            task_timeout_seconds=0.05,
            thread_backed=True,
        )
        assert await run_sync_in_thread(lambda: started.wait(timeout=1.0))
        await asyncio.sleep(0.15)

        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.error_code == "timeout"

        release.set()
        await asyncio.sleep(0.3)

        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.result is None
        assert info.error is not None
        assert info.error_code == "timeout"

    _run(_inner())


def test_error_code_classification() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=8)

        cases = [
            ("config_error", "invalid provider configuration: bad model"),
            ("claim_error", "claim extraction failed: parse error"),
            ("lesson_error", "lesson generation failed: LLM timeout"),
            ("network_error", "connection refused: api.example.com"),
            ("internal_error", "unexpected thing happened"),
            ("internal_error", "failed at http://example.com/api"),
            ("internal_error", ""),
        ]
        ids: list[tuple[str, str]] = []
        for expected_code, error_msg in cases:

            async def failing(handle: TaskHandle, msg: str = error_msg) -> None:
                raise RuntimeError(msg)

            tid = runner.submit("test", failing)
            ids.append((tid, expected_code))

        await asyncio.sleep(0.5)
        for tid, expected_code in ids:
            info = runner.get_task(tid)
            assert info is not None
            assert info.status == TaskStatus.FAILED
            assert info.error_code == expected_code, (
                f"expected {expected_code}, got {info.error_code} for error={info.error}"
            )

    _run(_inner())


def test_error_code_is_none_on_success() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)

        async def work(handle: TaskHandle) -> str:
            return "ok"

        task_id = runner.submit("test", work)
        await asyncio.sleep(0.1)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.COMPLETED
        assert info.error is None
        assert info.error_code is None

    _run(_inner())


def test_task_info_has_error_code_field() -> None:
    from ahadiff.core.task_runner import TaskInfo

    info = TaskInfo(task_id="test", task_type="test")
    assert info.error_code is None


def test_task_runner_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AHADIFF_DEFAULT_TASK_TIMEOUT_SECONDS", raising=False)
    runner = TaskRunner(max_concurrent=1)
    assert _task_timeout_seconds(runner) == _default_task_timeout_seconds()


def test_task_runner_default_timeout_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AHADIFF_DEFAULT_TASK_TIMEOUT_SECONDS", "12.5")
    runner = TaskRunner(max_concurrent=1)
    assert _task_timeout_seconds(runner) == 12.5


def test_task_runner_invalid_env_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AHADIFF_DEFAULT_TASK_TIMEOUT_SECONDS", "not-a-number")
    with pytest.raises(ValueError, match="AHADIFF_DEFAULT_TASK_TIMEOUT_SECONDS"):
        TaskRunner(max_concurrent=1)


def test_task_runner_custom_timeout() -> None:
    runner = TaskRunner(max_concurrent=1, task_timeout_seconds=30.0)
    assert _task_timeout_seconds(runner) == 30.0


def test_submit_rejects_invalid_per_task_timeout() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=1)

        async def work(handle: TaskHandle) -> None:
            return None

        with pytest.raises(ValueError, match="positive"):
            runner.submit("bad-timeout", work, task_timeout_seconds=0)

    _run(_inner())


def test_task_runner_rejects_zero_timeout() -> None:
    with pytest.raises(ValueError, match="positive"):
        TaskRunner(max_concurrent=1, task_timeout_seconds=0)


def test_task_runner_rejects_negative_timeout() -> None:
    with pytest.raises(ValueError, match="positive"):
        TaskRunner(max_concurrent=1, task_timeout_seconds=-1)


def test_task_runner_rejects_non_finite_timeout() -> None:
    with pytest.raises(ValueError, match="finite"):
        TaskRunner(max_concurrent=1, task_timeout_seconds=float("inf"))


def test_task_internal_timeout_not_classified_as_scheduler_timeout() -> None:
    """A TimeoutError raised by the task itself (e.g., httpx) should not be
    classified as a scheduler timeout."""

    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2, task_timeout_seconds=60)

        async def internal_timeout(handle: TaskHandle) -> None:
            raise TimeoutError("socket timeout from dependency")

        task_id = runner.submit("test", internal_timeout)
        await asyncio.sleep(0.2)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.error_code != "timeout"
        assert info.error == "socket timeout from dependency"

    _run(_inner())


def test_timeout_marks_handle_cancelled_for_cooperative_stop() -> None:
    """When a task times out, the handle must be marked cancelled so
    threads still running can check is_cancelled() and stop cooperatively."""

    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2, task_timeout_seconds=0.1)
        handle_ref: list[TaskHandle] = []

        async def slow_work(handle: TaskHandle) -> None:
            handle_ref.append(handle)
            await asyncio.sleep(10)

        task_id = runner.submit("slow", slow_work)
        await asyncio.sleep(0.5)

        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.error_code == "timeout"
        assert len(handle_ref) == 1
        assert handle_ref[0].is_cancelled() is True

    _run(_inner())


def test_classify_error_connection_error_isinstance() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)

        async def fail_conn(handle: TaskHandle) -> None:
            raise ConnectionError("arbitrary message without keywords")

        task_id = runner.submit("test", fail_conn)
        await asyncio.sleep(0.2)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.error_code == "network_error"

    _run(_inner())


def test_classify_error_empty_connection_error_is_network() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)

        async def fail_conn(handle: TaskHandle) -> None:
            raise ConnectionError()

        task_id = runner.submit("test", fail_conn)
        await asyncio.sleep(0.2)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.error_code == "network_error"

    _run(_inner())


def test_classify_error_project_error_types() -> None:
    from ahadiff.contracts import ErrorCode
    from ahadiff.core.errors import AhaDiffError, ConfigError, SafetyError, VerificationError

    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=4)

        cases = [
            (ConfigError(), "config_error"),
            (SafetyError(), "permission_error"),
            (VerificationError(), "claim_error"),
            (AhaDiffError(code=ErrorCode.LOCK_CONFLICT), "lock_conflict"),
        ]
        task_ids: list[tuple[str, str]] = []
        for exc, expected_code in cases:

            async def failing(handle: TaskHandle, error: Exception = exc) -> None:
                raise error

            task_ids.append((runner.submit("test", failing), expected_code))

        await asyncio.sleep(0.2)
        for task_id, expected_code in task_ids:
            info = runner.get_task(task_id)
            assert info is not None
            assert info.status == TaskStatus.FAILED
            assert info.error_code == expected_code

    _run(_inner())


def test_classify_error_oserror_not_network() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)

        async def fail_os(handle: TaskHandle) -> None:
            raise OSError("disk full")

        task_id = runner.submit("test", fail_os)
        await asyncio.sleep(0.2)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.error_code == "internal_error"

    _run(_inner())


def test_classify_provider_error_decompression_is_network() -> None:
    from ahadiff.core.errors import ProviderError

    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)

        async def fail_decomp(handle: TaskHandle) -> None:
            raise ProviderError("provider response decompression failed: Error -3")

        task_id = runner.submit("test", fail_decomp)
        await asyncio.sleep(0.2)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.error_code == "network_error"

    _run(_inner())


def test_classify_provider_error_auth_is_config() -> None:
    from ahadiff.core.errors import ProviderError

    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2)

        async def fail_auth(handle: TaskHandle) -> None:
            raise ProviderError("provider authentication failed (HTTP 401)")

        task_id = runner.submit("test", fail_auth)
        await asyncio.sleep(0.2)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.FAILED
        assert info.error_code == "config_error"

    _run(_inner())


def test_cancel_before_timeout_preserves_cancelled() -> None:
    async def _inner() -> None:
        runner = TaskRunner(max_concurrent=2, task_timeout_seconds=0.2)
        started = asyncio.Event()

        async def slow(handle: TaskHandle) -> None:
            started.set()
            await asyncio.sleep(10)

        task_id = runner.submit("test", slow)
        await started.wait()
        assert runner.cancel_task(task_id) is True
        await asyncio.sleep(0.5)
        info = runner.get_task(task_id)
        assert info is not None
        assert info.status == TaskStatus.CANCELLED

    _run(_inner())
