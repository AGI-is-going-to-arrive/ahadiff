from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_WINDOWS_TRANSIENT_REPLACE_WINERRORS = frozenset({32, 33})
_DEFAULT_REPLACE_ATTEMPTS = 5
_DEFAULT_REPLACE_BACKOFF_SECONDS = 0.02


def _is_windows_transient_replace_error(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) and (
        getattr(exc, "winerror", None) in _WINDOWS_TRANSIENT_REPLACE_WINERRORS
    )


def replace_with_retry(
    source_path: Path,
    destination_path: Path,
    *,
    attempts: int = _DEFAULT_REPLACE_ATTEMPTS,
    backoff_seconds: float = _DEFAULT_REPLACE_BACKOFF_SECONDS,
) -> None:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    for attempt in range(attempts):
        try:
            source_path.replace(destination_path)
            return
        except OSError as exc:
            if not _is_windows_transient_replace_error(exc):
                raise
            if attempt == attempts - 1:
                raise
            time.sleep(backoff_seconds)


__all__ = ["replace_with_retry"]
