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
    from collections.abc import Callable
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

    def test_directory_move_event_is_not_discarded(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=lambda _: None,
                config=WatcherConfig(debounce_seconds=60.0),
            )
            event = SimpleNamespace(
                is_directory=True,
                src_path=str(tmp_path / "old_pkg"),
                dest_path=str(tmp_path / "new_pkg"),
            )

            try:
                watcher._handle_fs_event(event)

                assert watcher._drain_pending() == frozenset(
                    {
                        str(tmp_path / "old_pkg"),
                        str(tmp_path / "new_pkg"),
                    }
                )
            finally:
                watcher.stop()


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

    def test_failure_threshold_hit_after_consecutive_failures(self, tmp_path: Path) -> None:
        from ahadiff.core.watcher import _FAILURE_LOG_THRESHOLD

        def bad_callback(_event: WatchEvent) -> None:
            raise RuntimeError("fail")

        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=bad_callback,
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            for i in range(_FAILURE_LOG_THRESHOLD):
                watcher._pending_paths.add(f"file{i}.py")
                watcher._trigger()
            status = watcher.status()
            assert status["failure_threshold_hit"] is True
            assert status["consecutive_failures"] == _FAILURE_LOG_THRESHOLD
            assert status["total_failures"] == _FAILURE_LOG_THRESHOLD
            assert isinstance(status["last_error"], str)

    def test_failure_counter_auto_resets_and_retries(self, tmp_path: Path) -> None:
        received: list[WatchEvent] = []

        def callback(e: WatchEvent) -> None:
            received.append(e)

        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=callback,
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            with watcher._lock:
                watcher._failure_threshold_hit = True
                watcher._consecutive_failures = 5
            watcher._pending_paths.add("retry.py")
            watcher._trigger()
            assert len(received) == 1
            assert watcher.status()["failure_threshold_hit"] is False
            assert watcher.status()["consecutive_failures"] == 0

    def test_failure_count_resets(self, tmp_path: Path) -> None:
        def bad_callback(_event: WatchEvent) -> None:
            raise RuntimeError("fail")

        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=bad_callback,
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            watcher._pending_paths.add("a.py")
            watcher._trigger()
            assert watcher.status()["consecutive_failures"] == 1
            watcher.reset_failure_count()
            assert watcher.status()["consecutive_failures"] == 0
            assert watcher.status()["failure_threshold_hit"] is False

    def test_success_resets_consecutive_failures(self, tmp_path: Path) -> None:
        call_count = 0

        def mixed_callback(_event: WatchEvent) -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("fail")

        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=mixed_callback,
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            watcher._pending_paths.add("a.py")
            watcher._trigger()
            watcher._pending_paths.add("b.py")
            watcher._trigger()
            assert watcher.status()["consecutive_failures"] == 2
            watcher._pending_paths.add("c.py")
            watcher._trigger()
            assert watcher.status()["consecutive_failures"] == 0
            assert watcher.status()["total_failures"] == 2
            assert watcher.status()["total_triggers"] == 3

    def test_status_includes_error_tracking_fields(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=lambda e: None,
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            status = watcher.status()
            assert "consecutive_failures" in status
            assert "total_triggers" in status
            assert "total_failures" in status
            assert "last_error" in status
            assert "failure_threshold_hit" in status

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

    def test_stop_completes_after_callback_gate_released(self, tmp_path: Path) -> None:
        received: list[WatchEvent] = []

        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=lambda e: received.append(e),
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            watcher._callback_gate.acquire()

            stop_done = threading.Event()

            def do_stop() -> None:
                watcher.stop(timeout=1.0)
                stop_done.set()

            stop_thread = threading.Thread(target=do_stop)
            stop_thread.start()
            time.sleep(0.05)

            watcher._callback_gate.release()
            assert stop_done.wait(timeout=3.0), "stop() did not complete"
            stop_thread.join(timeout=1.0)

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

    def test_stop_does_not_block_indefinitely_when_callback_hangs(self, tmp_path: Path) -> None:
        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(
                tmp_path,
                on_change=lambda _: None,
                config=WatcherConfig(cooldown_seconds=0.0),
            )
            watcher._callback_gate.acquire()

            stop_thread = threading.Thread(target=lambda: watcher.stop(timeout=0.3))
            stop_thread.start()
            stop_thread.join(timeout=2.0)

            assert not stop_thread.is_alive(), "stop() blocked indefinitely"
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

    def test_stop_timeout_marks_watcher_non_restartable(self, tmp_path: Path) -> None:
        class _HungObserver:
            def stop(self) -> None:
                return None

            def join(self, timeout: float | None = None) -> None:
                return None

            def is_alive(self) -> bool:
                return True

        with patch("ahadiff.core.watcher.is_watchdog_available", return_value=True):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            watcher._observer = _HungObserver()
            watcher.stop()

            status = watcher.status()
            assert status["running"] is False
            assert status["stop_timed_out"] is True
            assert status["restartable"] is False

            with pytest.raises(ConfigError, match="did not stop cleanly"):
                watcher.start()

    def test_dead_observer_is_not_reported_as_running_and_can_restart(self, tmp_path: Path) -> None:
        class _DeadObserver:
            def is_alive(self) -> bool:
                return False

        started_observers: list[object] = []

        class _FakeObserver:
            def schedule(self, *args: object, **kwargs: object) -> None:
                del args, kwargs

            def start(self) -> None:
                started_observers.append(self)

            def stop(self) -> None:
                return None

            def join(self, timeout: float | None = None) -> None:
                del timeout

            def is_alive(self) -> bool:
                return False

        def _fake_import_module(name: str) -> SimpleNamespace:
            if name == "watchdog.events":
                return SimpleNamespace(FileSystemEventHandler=object)
            if name == "watchdog.observers":
                return SimpleNamespace(Observer=_FakeObserver)
            raise AssertionError(f"unexpected module import: {name}")

        with (
            patch("ahadiff.core.watcher.is_watchdog_available", return_value=True),
            patch("ahadiff.core.watcher.importlib.import_module", _fake_import_module),
        ):
            watcher = FileWatcher(tmp_path, on_change=lambda _: None)
            watcher._observer = _DeadObserver()

            status = watcher.status()
            assert status["running"] is False
            assert status["restartable"] is True
            assert status["stop_timed_out"] is False

            watcher.start()
            assert len(started_observers) == 1
            watcher.stop()

    def test_cli_stop_status_does_not_report_timeout_as_clean_stop(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        messages: list[str] = []

        class _Console:
            def print(self, message: str) -> None:
                messages.append(message)

        monkeypatch.setattr(cli_module, "console", _Console())

        cli_module._print_watcher_stop_status(
            SimpleNamespace(status=lambda: {"stop_timed_out": True})
        )

        assert messages == [
            "[yellow]Watcher stop timed out; observer may still be running[/yellow]"
        ]


class TestWatchLearnRunner:
    def _wait_until(self, predicate: Callable[[], bool], *, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    def test_retriggers_after_change_queued_during_run(self) -> None:
        first_started = threading.Event()
        finish_first = threading.Event()
        second_done = threading.Event()
        run_lock = threading.Lock()
        run_count = 0

        def run_learn() -> bool:
            nonlocal run_count
            with run_lock:
                run_count += 1
                current = run_count
            if current == 1:
                first_started.set()
                assert finish_first.wait(timeout=2.0)
            else:
                second_done.set()
            return True

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

    def test_stop_clears_running_state_when_learn_hangs(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def run_learn() -> bool:
            started.set()
            release.wait()
            return True

        runner = cli_module._WatchLearnRunner(run_learn, run_timeout_seconds=10.0)
        runner.request(WatchEvent(changed_paths=frozenset({"a.py"}), timestamp=1.0))
        assert started.wait(timeout=2.0)

        runner.stop()

        assert self._wait_until(lambda: not runner._running)
        assert runner._retrigger_pending is False
        release.set()

    def test_timeout_allows_later_request_after_hung_learn(self) -> None:
        first_started = threading.Event()
        release_first = threading.Event()
        second_done = threading.Event()
        run_lock = threading.Lock()
        run_count = 0

        def run_learn() -> bool:
            nonlocal run_count
            with run_lock:
                run_count += 1
                current = run_count
            if current == 1:
                first_started.set()
                release_first.wait()
            else:
                second_done.set()
            return True

        runner = cli_module._WatchLearnRunner(run_learn, run_timeout_seconds=0.05)
        runner.request(WatchEvent(changed_paths=frozenset({"a.py"}), timestamp=1.0))
        assert first_started.wait(timeout=2.0)
        assert self._wait_until(lambda: not runner._running)

        runner.request(WatchEvent(changed_paths=frozenset({"b.py"}), timestamp=2.0))

        assert second_done.wait(timeout=2.0)
        runner.stop()
        release_first.set()
        with run_lock:
            assert run_count == 2
