from __future__ import annotations

import asyncio
import pathlib as _pathlib
import threading
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from _thread import LockType as ThreadLock
    from pathlib import Path

    from ahadiff.core.task_runner import TaskRunner
else:
    Path = _pathlib.Path
    ThreadLock = Any
    TaskRunner = Any


@dataclass(frozen=True)
class ServeState:
    state_dir: Path
    token: str
    locale: Literal["en", "zh-CN"] = "en"
    cli_lang: str | None = None
    config_lang: str | None = None
    bind_host: str = "127.0.0.1"
    port: int = 8765
    write_lock: asyncio.Lock | None = None
    repo_lock_path: Path | None = None
    thread_write_lock: ThreadLock | None = None
    started_at: float = 0.0
    task_runner: TaskRunner | None = None

    @property
    def runs_dir(self) -> Path:
        return self.state_dir / "runs"

    @property
    def review_db_path(self) -> Path:
        return self.state_dir / "review.sqlite"

    def with_runtime_lock(self) -> ServeState:
        if (
            self.write_lock is not None
            and self.repo_lock_path is not None
            and self.thread_write_lock is not None
            and self.task_runner is not None
        ):
            return self

        from ahadiff.core.task_runner import TaskRunner as _TaskRunner

        return replace(
            self,
            write_lock=self.write_lock or asyncio.Lock(),
            repo_lock_path=self.repo_lock_path or self.state_dir / "ahadiff.lock",
            thread_write_lock=self.thread_write_lock or threading.Lock(),
            started_at=self.started_at or time.monotonic(),
            task_runner=self.task_runner or _TaskRunner(),
        )

    def with_locale(self, locale: Literal["en", "zh-CN"]) -> ServeState:
        return replace(self, locale=locale)


__all__ = ["ServeState"]
