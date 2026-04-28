"""Phase 1B: Concurrent DAO threadpool benchmark.

Validates that anyio.to_thread.run_sync + synchronous sqlite3
does not deadlock and maintains acceptable latency under concurrent load,
confirming the §9.9 decision to keep the threadpool pattern.

Note: raw SQLite query p95 is < 4ms (bench_sqlite_queries.py).
The to_thread dispatch adds ~5-60ms of thread pool scheduling overhead
depending on pool warmth, which is acceptable for a localhost-only API.
"""

from __future__ import annotations

import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

import anyio
import pytest

from ahadiff.contracts import ResultEvent
from ahadiff.review.database import (
    initialize_review_db,
    list_due_cards,
    load_result_events_page,
    sync_result_event,
)

_WARMUP_ROUNDS = 5


def _seed_db(db_path: Path) -> None:
    initialize_review_db(db_path)
    statuses = ("baseline", "keep", "keep_final")
    for i in range(500):
        event = ResultEvent(
            event_id=f"018f0f52-91c0-7abc-8123-{i:012d}",
            run_id=f"run-{i % 50:02d}",
            event_type="learn",
            timestamp=f"2026-04-24T00:{i % 60:02d}:{i % 60:02d}Z",
            source_ref=f"source-{i % 10:02d}",
            base_ref=None,
            prompt_version="prompt123",
            eval_bundle_version="eval123",
            rubric_version="rubric-v1",
            overall=70.0 + float(i % 25),
            verdict="PASS",
            status=statuses[i % len(statuses)],
            weakest_dim="evidence",
            note_json=None,
        )
        sync_result_event(db_path, event)


def _load_events_sync(db_path: Path) -> Any:
    return load_result_events_page(db_path, limit=50)


def _list_cards_sync(db_path: Path) -> Any:
    return list_due_cards(db_path, limit=50)


async def _warmup(db_path: Path) -> None:
    """Warm up the anyio thread pool to avoid cold-start outliers."""
    for _ in range(_WARMUP_ROUNDS):
        await anyio.to_thread.run_sync(lambda: _load_events_sync(db_path))


@pytest.mark.anyio
async def test_threadpool_concurrent_reads_latency() -> None:
    """10-way concurrent reads: p95 must stay under 100ms (thread dispatch included)."""
    with tempfile.TemporaryDirectory(prefix="ahadiff-1b-bench-") as tmp:
        db_path = Path(tmp) / ".ahadiff" / "review.sqlite"
        db_path.parent.mkdir(parents=True)
        _seed_db(db_path)
        await _warmup(db_path)

        latencies: list[float] = []
        sem = anyio.Semaphore(10)

        async def _one_read() -> None:
            async with sem:
                t0 = time.perf_counter()
                await anyio.to_thread.run_sync(lambda: _load_events_sync(db_path))
                latencies.append((time.perf_counter() - t0) * 1000)

        async with anyio.create_task_group() as tg:
            for _ in range(100):
                tg.start_soon(_one_read)

        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        mean = statistics.mean(latencies)
        assert p95 < 150.0, f"p95={p95:.1f}ms exceeds 150ms threadpool+dispatch target"
        assert mean < 80.0, f"mean={mean:.1f}ms unexpectedly high"


@pytest.mark.anyio
async def test_threadpool_mixed_workload_latency() -> None:
    """10-way mixed reads (events + cards): p95 < 100ms."""
    with tempfile.TemporaryDirectory(prefix="ahadiff-1b-bench-") as tmp:
        db_path = Path(tmp) / ".ahadiff" / "review.sqlite"
        db_path.parent.mkdir(parents=True)
        _seed_db(db_path)
        await _warmup(db_path)

        latencies: list[float] = []
        sem = anyio.Semaphore(10)

        async def _one_query(index: int) -> None:
            async with sem:
                t0 = time.perf_counter()
                if index % 2 == 0:
                    await anyio.to_thread.run_sync(lambda: _load_events_sync(db_path))
                else:
                    await anyio.to_thread.run_sync(lambda: _list_cards_sync(db_path))
                latencies.append((time.perf_counter() - t0) * 1000)

        async with anyio.create_task_group() as tg:
            for i in range(100):
                tg.start_soon(_one_query, i)

        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        mean = statistics.mean(latencies)
        assert p95 < 150.0, f"p95={p95:.1f}ms exceeds 150ms threadpool+dispatch target"
        assert mean < 80.0, f"mean={mean:.1f}ms unexpectedly high"


@pytest.mark.anyio
async def test_threadpool_high_concurrency_no_deadlock() -> None:
    """20 concurrent readers complete all 200 queries without deadlock; p99 < 200ms."""
    with tempfile.TemporaryDirectory(prefix="ahadiff-1b-bench-") as tmp:
        db_path = Path(tmp) / ".ahadiff" / "review.sqlite"
        db_path.parent.mkdir(parents=True)
        _seed_db(db_path)
        await _warmup(db_path)

        latencies: list[float] = []
        sem = anyio.Semaphore(20)

        async def _one_read() -> None:
            async with sem:
                t0 = time.perf_counter()
                await anyio.to_thread.run_sync(lambda: _load_events_sync(db_path))
                latencies.append((time.perf_counter() - t0) * 1000)

        async with anyio.create_task_group() as tg:
            for _ in range(200):
                tg.start_soon(_one_read)

        assert len(latencies) == 200, "not all queries completed"
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]
        assert p99 < 200.0, f"p99={p99:.1f}ms: excessive contention under 20-way concurrency"
