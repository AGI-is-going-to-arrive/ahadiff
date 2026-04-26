from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from ahadiff.git.repo import repo_write_lock

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .state import ServeState


@contextmanager
def serve_repo_write_lock(state: ServeState, *, command: str) -> Iterator[None]:
    assert state.repo_lock_path is not None
    assert state.thread_write_lock is not None
    with repo_write_lock(state.repo_lock_path, command=command), state.thread_write_lock:
        yield


__all__ = ["serve_repo_write_lock"]
