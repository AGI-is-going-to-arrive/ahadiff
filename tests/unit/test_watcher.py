"""Tests for core/watcher.py (Phase 6A)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from ahadiff import cli as cli_module
from ahadiff.core.errors import ConfigError
from ahadiff.core.watcher import (
    FileWatcher,
    WatcherConfig,
    WatchEvent,
    is_watchdog_available,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestIsWatchdogAvailable:
    def test_returns_bool(self) -> None:
        result = is_watchdog_available()
        assert isinstance(result, bool)

    def test_returns_false_when_import_fails(self) -> None:
        with patch("importlib.util.find_spec", return_value=None):
            assert is_watchdog_available() is False


class TestWatcherConfig:
    def test_defaults(self) -> None:
        config = WatcherConfig()
        assert config.debounce_seconds == 2.0
        assert config.cooldown_seconds == 30.0
        assert config.ignore_patterns == ()

    def test_custom_values(self) -> None:
        config = WatcherConfig(
            debounce_seconds=0.5,
            cooldown_seconds=10.0,
            ignore_patterns=("*.log", "build"),
        )
        assert config.debounce_seconds == 0.5
        assert config.cooldown_seconds == 10.0
        assert config.ignore_patterns == ("*.log", "build")

    def test_frozen(self) -> None:
        config = WatcherConfig()
        with pytest.raises(AttributeError):
            config.debounce_seconds = 5.0  # type: ignore[misc]


class TestWatchEvent:
    def test_fields(self) -> None:
        event = WatchEvent(
            changed_paths=frozenset({"a.py", "b.py"}),
            timestamp=123.456,
        )
        assert len(event.changed_paths) == 2
        assert event.timestamp == 123.456

    def test_frozen(self) -> None:
        event = WatchEvent(changed_paths=frozenset(), timestamp=0.0)
        with pytest.raises(AttributeError):
            event.timestamp = 1.0  # type: ignore[misc]


class TestFileWatcherInit:
    def test_raises_when_watchdog_not_available(self, tmp_path: Path) -> None:
        with (
            patch("ahadiff.core.watcher.is_watchdog_available", return_value=False),
            pytest.raises(ConfigError, match="watchdog is not installed"),
        ):
            FileWatcher(tmp_path, on_change=lambda _: None)

    def test_raises_for_nonexistent_path(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        with (
            patch("ahadiff.core.watcher.is_watchdog_available", return_value=True),
            pytest.raises(ConfigError, match="not a directory"),
        ):
            FileWatcher(missing, on_change=lambda _: None)

    def test_raises_for_file_path(self, tmp_path: Path) -> None:
        filepath = tmp_path / "file.txt"
        filepath.write_text("content")
        with (
            patch("ahadiff.core.watcher.is_watchdog_available", return_value=True),
            pytest.raises(ConfigError, match="not a directory"),
        ):
            FileWatcher(filepath, on_change=lambda _: None)

    def test_accepts_valid_directory(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            assert not watcher.is_running


class TestFileWatcherIgnorePatterns:
    def test_ignores_git_directory(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            assert watcher._should_ignore(str(tmp_path / ".git" / "objects" / "abc"))

    def test_ignores_ahadiff_directory(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            assert watcher._should_ignore(str(tmp_path / ".ahadiff" / "review.sqlite"))

    def test_ignores_pycache(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            assert watcher._should_ignore(str(tmp_path / "__pycache__" / "mod.pyc"))

    def test_ignores_pyc_files(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            assert watcher._should_ignore(str(tmp_path / "module.pyc"))

    def test_ignores_node_modules(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            assert watcher._should_ignore(str(tmp_path / "node_modules" / "pkg" / "index.js"))

    def test_does_not_ignore_source_files(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            assert not watcher._should_ignore(str(tmp_path / "src" / "app.py"))

    def test_custom_ignore_patterns(self, tmp_path: Path) -> None:
        config = WatcherConfig(ignore_patterns=("*.log", "build"))
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None, config=config)
            assert watcher._should_ignore(str(tmp_path / "output.log"))
            assert watcher._should_ignore(str(tmp_path / "build" / "dist.js"))
            assert not watcher._should_ignore(str(tmp_path / "src" / "main.py"))

    def test_custom_nested_ignore_pattern_accepts_windows_separator(self, tmp_path: Path) -> None:
        config = WatcherConfig(ignore_patterns=(r"src\generated\*",))
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None, config=config)
            assert watcher._should_ignore(str(tmp_path / "src" / "generated" / "client.py"))
            assert not watcher._should_ignore(str(tmp_path / "src" / "main.py"))

    def test_ignores_path_outside_watch_root(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            assert watcher._should_ignore("/some/other/path/file.py")

    def test_ignores_ds_store(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            assert watcher._should_ignore(str(tmp_path / ".DS_Store"))

    def test_ignores_venv(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            assert watcher._should_ignore(str(tmp_path / ".venv" / "lib" / "site.py"))


class TestFileWatcherEventPaths:
    def test_move_event_includes_dest_path(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            event = SimpleNamespace(
                src_path=str(tmp_path / "old.py"),
                dest_path=str(tmp_path / "new.py"),
            )
            assert watcher._changed_event_paths(event) == (
                str(tmp_path / "old.py"),
                str(tmp_path / "new.py"),
            )

    def test_move_event_keeps_non_ignored_dest_path(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            event = SimpleNamespace(
                src_path=str(tmp_path / ".ahadiff" / "tmp.py"),
                dest_path=str(tmp_path / "src" / "main.py"),
            )
            assert watcher._changed_event_paths(event) == (str(tmp_path / "src" / "main.py"),)


class TestFileWatcherDrainPending:
    def test_drain_returns_and_clears(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            watcher._pending_paths.add("a.py")
            watcher._pending_paths.add("b.py")
            drained = watcher._drain_pending()
            assert drained == frozenset({"a.py", "b.py"})
            assert watcher._drain_pending() == frozenset()


class TestFileWatcherTrigger:
    def test_trigger_calls_on_change(self, tmp_path: Path) -> None:
        received: list[WatchEvent] = []
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=lambda e: received.append(e),
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            watcher._pending_paths.add(str(tmp_path / "file.py"))
            watcher._trigger()
            assert len(received) == 1
            assert str(tmp_path / "file.py") in received[0].changed_paths

    def test_trigger_empty_pending_does_nothing(self, tmp_path: Path) -> None:
        received: list[WatchEvent] = []
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=lambda e: received.append(e),
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            watcher._trigger()
            assert len(received) == 0

    def test_trigger_respects_cooldown(self, tmp_path: Path) -> None:
        received: list[WatchEvent] = []
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=lambda e: received.append(e),
                config=WatcherConfig(cooldown_seconds=100.0),
            )
            watcher._pending_paths.add("a.py")
            watcher._last_trigger_time = time.monotonic()
            watcher._trigger()
            assert len(received) == 0

    def test_trigger_clears_pending(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=lambda _: None,
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            watcher._pending_paths.add("a.py")
            watcher._trigger()
            assert len(watcher._pending_paths) == 0

    def test_trigger_does_not_raise_on_callback_error(self, tmp_path: Path) -> None:
        def bad_callback(_event: WatchEvent) -> None:
            raise RuntimeError("boom")

        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=bad_callback,
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            watcher._pending_paths.add("a.py")
            watcher._trigger()

    def test_trigger_skipped_when_stopped(self, tmp_path: Path) -> None:
        received: list[WatchEvent] = []
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=lambda e: received.append(e),
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            watcher._pending_paths.add("a.py")
            watcher._stopped.set()
            watcher._trigger()
            assert len(received) == 0

    def test_stop_prevents_callback_waiting_on_gate(self, tmp_path: Path) -> None:
        received: list[WatchEvent] = []

        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=lambda e: received.append(e),
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            watcher._callback_gate.acquire()

            stop_thread = threading.Thread(target=watcher.stop)
            stop_thread.start()
            stop_thread.join(timeout=0.5)

            watcher._callback_gate.release()
            stop_thread.join(timeout=2.0)

            assert not stop_thread.is_alive()
            assert received == []

    def test_trigger_does_not_block_when_callback_gate_busy(self, tmp_path: Path) -> None:
        received: list[WatchEvent] = []

        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=lambda e: received.append(e),
                config=WatcherConfig(debounce_seconds=60.0, cooldown_seconds=0.0),
            )
            watcher._pending_paths.add("a.py")
            watcher._callback_gate.acquire()

            trigger_thread = threading.Thread(target=watcher._trigger)
            trigger_thread.start()
            trigger_thread.join(timeout=0.5)

            assert not trigger_thread.is_alive()
            assert watcher._drain_pending() == frozenset({"a.py"})
            assert received == []

            watcher.stop()
            watcher._callback_gate.release()


class TestFileWatcherStartStop:
    @pytest.mark.skipif(not is_watchdog_available(), reason="watchdog not installed")
    def test_start_and_stop(self, tmp_path: Path) -> None:
        watcher = FileWatcher(
            tmp_path,
            on_change=lambda _: None,
            config=WatcherConfig(debounce_seconds=0.1),
        )
        watcher.start()
        assert watcher.is_running
        watcher.stop()
        assert not watcher.is_running

    @pytest.mark.skipif(not is_watchdog_available(), reason="watchdog not installed")
    def test_double_start_raises(self, tmp_path: Path) -> None:
        watcher = FileWatcher(tmp_path, on_change=lambda _: None)
        watcher.start()
        try:
            with pytest.raises(ConfigError, match="already running"):
                watcher.start()
        finally:
            watcher.stop()

    @pytest.mark.skipif(not is_watchdog_available(), reason="watchdog not installed")
    def test_detects_file_change(self, tmp_path: Path) -> None:
        received: list[WatchEvent] = []
        barrier = threading.Event()

        def on_change(event: WatchEvent) -> None:
            received.append(event)
            barrier.set()

        watcher = FileWatcher(
            tmp_path,
            on_change=on_change,
            config=WatcherConfig(debounce_seconds=0.1, cooldown_seconds=0.0),
        )
        watcher.start()
        try:
            (tmp_path / "test_file.py").write_text("hello")
            barrier.wait(timeout=5.0)
            assert len(received) >= 1
        finally:
            watcher.stop()


class TestWatchLearnRunner:
    def test_retriggers_after_change_queued_during_run(self) -> None:
        first_started = threading.Event()
        finish_first = threading.Event()
        second_done = threading.Event()
        run_lock = threading.Lock()
        run_count = 0

        def run_learn() -> None:
            nonlocal run_count
            with run_lock:
                run_count += 1
                current = run_count
            if current == 1:
                first_started.set()
                assert finish_first.wait(timeout=2.0)
            else:
                second_done.set()

        runner = cli_module._WatchLearnRunner(run_learn)
        runner.request(WatchEvent(changed_paths=frozenset({"a.py"}), timestamp=1.0))
        assert first_started.wait(timeout=2.0)

        started = time.monotonic()
        runner.request(WatchEvent(changed_paths=frozenset({"b.py"}), timestamp=2.0))
        assert time.monotonic() - started < 0.5

        finish_first.set()
        assert second_done.wait(timeout=2.0)
        runner.stop()
        with run_lock:
            assert run_count == 2
