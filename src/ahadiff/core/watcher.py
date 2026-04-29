"""Filesystem watcher for incremental learn regeneration.

Uses the ``watchdog`` library (optional dependency) to monitor repository
files and trigger a callback when tracked files change.
"""

from __future__ import annotations

import fnmatch
import importlib
import importlib.util
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.core.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

_DEFAULT_DEBOUNCE_SECONDS = 2.0
_DEFAULT_COOLDOWN_SECONDS = 30.0
_BUILTIN_IGNORE_PATTERNS: tuple[str, ...] = (
    ".git",
    ".ahadiff",
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "node_modules",
    ".venv",
)


def is_watchdog_available() -> bool:
    return importlib.util.find_spec("watchdog") is not None


@dataclass(frozen=True)
class WatcherConfig:
    debounce_seconds: float = _DEFAULT_DEBOUNCE_SECONDS
    cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS
    ignore_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class WatchEvent:
    changed_paths: frozenset[str]
    timestamp: float


class FileWatcher:
    """Watch a directory for file changes with debouncing and cooldown.

    Requires the ``watchdog`` optional dependency.
    """

    def __init__(
        self,
        watch_path: Path,
        *,
        on_change: Callable[[WatchEvent], None],
        config: WatcherConfig | None = None,
    ) -> None:
        if not is_watchdog_available():
            raise ConfigError(
                "watchdog is not installed; install with: pip install ahadiff[watchdog]"
            )
        resolved = watch_path.resolve()
        if not resolved.is_dir():
            raise ConfigError(f"watch path is not a directory: {resolved}")
        self._watch_path = resolved
        self._on_change = on_change
        self._config = config or WatcherConfig()
        self._observer: Any = None
        self._pending_paths: set[str] = set()
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._callback_gate = threading.RLock()
        self._timer: threading.Timer | None = None
        self._last_trigger_time: float = 0.0
        self._stopped = threading.Event()
        self._ignore_patterns = _BUILTIN_IGNORE_PATTERNS + self._config.ignore_patterns

    @property
    def is_running(self) -> bool:
        return self._observer is not None and not self._stopped.is_set()

    def _should_ignore(self, path: str) -> bool:
        try:
            resolved = Path(path).resolve()
            rel = str(resolved.relative_to(self._watch_path))
        except (ValueError, OSError):
            return True
        if ".." in Path(rel).parts:
            return True
        parts = Path(rel).parts
        for pattern in self._ignore_patterns:
            if any(fnmatch.fnmatch(part, pattern) for part in parts):
                return True
            if fnmatch.fnmatch(rel, pattern):
                return True
        return False

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._observer is not None:
                raise ConfigError("watcher is already running")

            events_module = cast("Any", importlib.import_module("watchdog.events"))
            observers_module = cast("Any", importlib.import_module("watchdog.observers"))
            file_system_event_handler: type[Any] = events_module.FileSystemEventHandler
            observer_class: type[Any] = observers_module.Observer

            watcher_ref = self

            class _Handler(file_system_event_handler):  # type: ignore[misc, valid-type]
                def on_any_event(self, event: Any) -> None:
                    if watcher_ref._stopped.is_set():
                        return
                    if event.is_directory:
                        return
                    src_path = getattr(event, "src_path", None)
                    if src_path is None:
                        return
                    if watcher_ref._should_ignore(src_path):
                        return
                    with watcher_ref._lock:
                        if watcher_ref._stopped.is_set():
                            return
                        watcher_ref._pending_paths.add(src_path)
                        watcher_ref._schedule_trigger()

            self._stopped.clear()
            with self._lock:
                self._pending_paths.clear()
                self._last_trigger_time = 0.0
            observer = observer_class()
            observer.schedule(_Handler(), str(self._watch_path), recursive=True)
            observer.daemon = True
            observer.start()
            self._observer = observer
            log.info("file watcher started: %s", self._watch_path)

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stopped.set()
            with self._lock:
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
                self._pending_paths.clear()
                self._last_trigger_time = 0.0
            observer = self._observer
            if observer is not None:
                observer.stop()
                observer.join(timeout=5.0)
                if not observer.is_alive():
                    self._observer = None
                else:
                    log.warning("watchdog observer did not stop within timeout")
            with self._callback_gate:
                pass
            log.info("file watcher stopped")

    def _schedule_trigger(self) -> None:
        """Must be called while holding self._lock."""
        if self._stopped.is_set():
            return
        if self._timer is not None:
            self._timer.cancel()
        timer = threading.Timer(self._config.debounce_seconds, self._trigger)
        timer.daemon = True
        timer.start()
        self._timer = timer

    def _trigger(self) -> None:
        if self._stopped.is_set():
            return
        now = time.monotonic()
        with self._lock:
            if self._stopped.is_set():
                self._timer = None
                return
            elapsed = now - self._last_trigger_time
            if elapsed < self._config.cooldown_seconds:
                remaining = self._config.cooldown_seconds - elapsed
                if self._stopped.is_set():
                    self._timer = None
                    return
                timer = threading.Timer(remaining, self._trigger)
                timer.daemon = True
                timer.start()
                self._timer = timer
                return
            paths = frozenset(self._pending_paths)
            self._pending_paths.clear()
            self._last_trigger_time = now
            self._timer = None

        if not paths:
            return

        with self._callback_gate:
            if self._stopped.is_set():
                return
            event = WatchEvent(changed_paths=paths, timestamp=now)
            try:
                self._on_change(event)
            except Exception:
                log.exception("watcher callback failed for %d changed files", len(paths))

    def _drain_pending(self) -> frozenset[str]:
        with self._lock:
            paths = frozenset(self._pending_paths)
            self._pending_paths.clear()
            return paths


__all__ = [
    "FileWatcher",
    "WatchEvent",
    "WatcherConfig",
    "is_watchdog_available",
]
