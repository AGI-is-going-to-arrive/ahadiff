# pyright: reportReturnType=false
from __future__ import annotations

import importlib
import os
import sqlite3
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import pytest

from ahadiff.core import paths as paths_module
from ahadiff.core import sqlite_util, windows_sqlite
from ahadiff.core.config import write_provider_env_var
from ahadiff.core.errors import ConfigError, InputError

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _reparse_stat(mode: int) -> SimpleNamespace:
    return SimpleNamespace(st_mode=mode, st_file_attributes=FILE_ATTRIBUTE_REPARSE_POINT)


def _supports_symlinks(tmp_path: Path) -> bool:
    target = tmp_path / "_probe_target"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "_probe_link"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        return False
    finally:
        if link.exists() or link.is_symlink():
            link.unlink()
        target.unlink()
    return True


def _no_sqlite_fd_path(_fd: int | None) -> Path | None:
    return None


def _force_windows_without_fd_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlite_util.sys, "platform", "win32")
    monkeypatch.setattr(sqlite_util.os, "supports_dir_fd", set[object]())
    monkeypatch.setattr(sqlite_util, "_sqlite_proc_fd_path", _no_sqlite_fd_path)


def test_safe_sqlite_connect_rejects_leaf_reparse_point_on_windows(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    db_path.write_bytes(b"")
    real_lstat = sqlite_util.os.lstat

    def fake_lstat(path: str | Path) -> os.stat_result:  # type: ignore[return-value]
        if Path(path) == db_path:
            return _reparse_stat(stat.S_IFREG | 0o600)
        return real_lstat(path)  # type: ignore[arg-type]

    with (
        mock.patch.object(sqlite_util.sys, "platform", "win32"),
        mock.patch.object(sqlite_util.os, "lstat", side_effect=fake_lstat),
        pytest.raises(PermissionError, match="NTFS reparse point"),
    ):
        sqlite_util.safe_sqlite_connect(db_path)


@pytest.mark.skipif(os.name == "nt", reason="native Windows has safe handle-based creation")
def test_safe_sqlite_connect_missing_database_without_native_handles_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    _force_windows_without_fd_bound(monkeypatch)

    with pytest.raises(PermissionError, match="native Windows handle support"):
        sqlite_util.safe_sqlite_connect(db_path)

    assert not db_path.exists()


def test_windows_create_retains_directory_guards_through_sqlite_pragmas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "new.sqlite"
    guard = mock.Mock(spec=windows_sqlite.WindowsDirectoryGuard)
    opened_fds: list[int] = []
    real_connect = sqlite_util.sqlite3.connect
    guarded_statements: list[str] = []

    def fake_native_create(path: Path) -> tuple[int, windows_sqlite.WindowsDirectoryGuard]:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        opened_fds.append(fd)
        return fd, guard

    class RecordingConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            guard.close.assert_not_called()
            guarded_statements.append(sql)
            return super().execute(sql, parameters)

    def recording_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return real_connect(*args, **kwargs, factory=RecordingConnection)

    _force_windows_without_fd_bound(monkeypatch)
    monkeypatch.setattr(windows_sqlite, "create_windows_sqlite_file", fake_native_create)
    monkeypatch.setattr(sqlite_util.sqlite3, "connect", recording_connect)

    connection = sqlite_util.safe_sqlite_connect(db_path, journal_mode="WAL", foreign_keys=True)
    connection.close()

    assert "PRAGMA journal_mode = WAL" in guarded_statements
    assert "PRAGMA foreign_keys = ON" in guarded_statements
    guard.close.assert_called_once()
    with pytest.raises(OSError):
        os.fstat(opened_fds[0])


def test_windows_create_releases_directory_guards_when_sqlite_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "new.sqlite"
    guard = mock.Mock(spec=windows_sqlite.WindowsDirectoryGuard)
    opened_fds: list[int] = []

    def fake_native_create(path: Path) -> tuple[int, windows_sqlite.WindowsDirectoryGuard]:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        opened_fds.append(fd)
        return fd, guard

    def failed_connect(*_args: Any, **_kwargs: Any) -> sqlite3.Connection:
        raise sqlite3.OperationalError("test open failure")

    _force_windows_without_fd_bound(monkeypatch)
    monkeypatch.setattr(windows_sqlite, "create_windows_sqlite_file", fake_native_create)
    monkeypatch.setattr(sqlite_util.sqlite3, "connect", failed_connect)

    with pytest.raises(sqlite3.OperationalError, match="test open failure"):
        sqlite_util.safe_sqlite_connect(db_path)

    guard.close.assert_called_once()
    with pytest.raises(OSError):
        os.fstat(opened_fds[0])


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows handle APIs")
def test_native_windows_create_reopen_and_wal_with_unicode_paths(tmp_path: Path) -> None:
    parent = tmp_path / "space 中文 😀"
    parent.mkdir()
    db_path = parent / "学习 😀.sqlite"

    connection = sqlite_util.safe_sqlite_connect(db_path, journal_mode="WAL")
    try:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.execute("INSERT INTO marker VALUES(?)", ("learned",))
        connection.commit()
    finally:
        connection.close()

    connection = sqlite_util.safe_sqlite_connect(db_path, journal_mode="WAL")
    try:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("learned",)
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    finally:
        connection.close()


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows handle APIs")
def test_native_windows_create_collision_preserves_existing_file(tmp_path: Path) -> None:
    db_path = tmp_path / "existing.sqlite"
    db_path.write_bytes(b"existing data")

    fd, guard = windows_sqlite.create_windows_sqlite_file(db_path)
    try:
        assert os.read(fd, 64) == b"existing data"
        assert os.fstat(fd).st_ino == db_path.stat().st_ino
    finally:
        os.close(fd)
        guard.close()

    assert db_path.read_bytes() == b"existing data"


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows path semantics")
@pytest.mark.parametrize("component", ["NUL.sqlite", "CON", "COM1.db", "file:stream", "db."])
def test_native_windows_create_rejects_ambiguous_win32_names(
    tmp_path: Path,
    component: str,
) -> None:
    with pytest.raises(PermissionError, match="unambiguous local Windows path"):
        windows_sqlite.create_windows_sqlite_file(tmp_path / component)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows sharing semantics")
@pytest.mark.parametrize("ancestor", [False, True])
def test_native_windows_create_blocks_parent_and_ancestor_swap_before_leaf_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ancestor: bool,
) -> None:
    ancestor_path = tmp_path / "ancestor"
    parent = ancestor_path / "db-parent"
    parent.mkdir(parents=True)
    protected = ancestor_path if ancestor else parent
    outside = tmp_path / "outside"
    outside.mkdir()
    db_path = parent / "new.sqlite"
    api_class = windows_sqlite._WindowsFileApi  # pyright: ignore[reportPrivateUsage]
    original_open = api_class.open
    attempted = False

    def swapping_open(
        api: Any,
        name: str,
        *,
        parent: int | None,
        directory: bool,
        create: bool = False,
    ) -> int:
        nonlocal attempted
        if create:
            attempted = True
            with pytest.raises(PermissionError):
                protected.rename(outside / "stolen")
        return original_open(api, name, parent=parent, directory=directory, create=create)

    monkeypatch.setattr(api_class, "open", swapping_open)
    connection = sqlite_util.safe_sqlite_connect(db_path)
    connection.close()

    assert attempted
    assert db_path.exists()
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows sharing semantics")
def test_native_windows_file_and_parent_remain_locked_during_sqlite_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "db-parent"
    parent.mkdir()
    db_path = parent / "new.sqlite"
    original_connect = sqlite_util.sqlite3.connect
    attempted = False

    def swapping_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        nonlocal attempted
        attempted = True
        with pytest.raises(PermissionError):
            db_path.rename(parent / "stolen.sqlite")
        with pytest.raises(PermissionError):
            parent.rename(tmp_path / "stolen-parent")
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite_util.sqlite3, "connect", swapping_connect)
    connection = sqlite_util.safe_sqlite_connect(db_path)
    connection.close()

    assert attempted
    db_path.unlink()
    parent.rmdir()


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows handle APIs")
def test_native_windows_fd_conversion_failure_releases_all_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "db-parent"
    parent.mkdir()
    db_path = parent / "new.sqlite"

    def failed_open_osfhandle(_handle: int, _flags: int) -> int:
        raise OSError("test fd conversion failure")

    monkeypatch.setattr(importlib.import_module("msvcrt"), "open_osfhandle", failed_open_osfhandle)

    with pytest.raises(OSError, match="test fd conversion failure"):
        windows_sqlite.create_windows_sqlite_file(db_path)

    # Rename/delete would fail if either the leaf or directory handles leaked.
    db_path.unlink()
    parent.rename(tmp_path / "moved-parent")


def test_safe_sqlite_connect_existing_database_without_dir_fd_allows_windows_path_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    db_path.write_bytes(b"")
    _force_windows_without_fd_bound(monkeypatch)

    connection = sqlite_util.safe_sqlite_connect(db_path)
    try:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.execute("INSERT INTO marker VALUES('ok')")
        connection.commit()
    finally:
        connection.close()

    connection = sqlite_util.safe_sqlite_connect(db_path)
    try:
        value = connection.execute("SELECT value FROM marker").fetchone()[0]
    finally:
        connection.close()

    assert value == "ok"


@pytest.mark.skipif(not hasattr(sqlite_util.os, "symlink"), reason="requires symlink support")
def test_safe_sqlite_connect_windows_path_connect_still_rejects_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.sqlite"
    target.touch()
    db_path = tmp_path / "review.sqlite"
    try:
        db_path.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    _force_windows_without_fd_bound(monkeypatch)

    with pytest.raises(PermissionError, match="symlink"):
        sqlite_util.safe_sqlite_connect(db_path)


@pytest.mark.skipif(not hasattr(sqlite_util.os, "link"), reason="requires hardlink support")
def test_safe_sqlite_connect_windows_path_connect_still_rejects_hardlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.sqlite"
    target.touch()
    db_path = tmp_path / "review.sqlite"
    try:
        sqlite_util.os.link(target, db_path)
    except OSError as exc:
        pytest.skip(f"hardlink creation failed: {exc}")
    _force_windows_without_fd_bound(monkeypatch)

    with pytest.raises(PermissionError, match="hardlinked database path"):
        sqlite_util.safe_sqlite_connect(db_path)


@pytest.mark.skipif(os.name == "nt", reason="native Windows has safe handle-based creation")
def test_safe_sqlite_connect_missing_database_without_dir_fd_rejects_parent_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _supports_symlinks(tmp_path):
        pytest.skip("symlinks unsupported on this platform")
    parent = tmp_path / "db-parent"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    db_path = parent / "review.sqlite"
    real_open = sqlite_util.os.open
    swapped = False

    def swapping_open(path: str | Path, flags: int, mode: int = 0o777, /) -> int:
        nonlocal swapped
        if not swapped and Path(path) == db_path:
            real_parent = parent.with_name("db-parent-real")
            parent.rename(real_parent)
            parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_open(path, flags, mode)

    monkeypatch.setattr(sqlite_util.os, "supports_dir_fd", set[object]())
    monkeypatch.setattr(sqlite_util.os, "open", swapping_open)
    monkeypatch.setattr(sqlite_util, "_sqlite_proc_fd_path", _no_sqlite_fd_path)

    with pytest.raises(PermissionError, match="fd-bound open support"):
        sqlite_util.safe_sqlite_connect(db_path)

    assert swapped is False
    assert not (outside / "review.sqlite").exists()


def test_safe_sqlite_connect_windows_path_connect_rejects_parent_aba_without_sidecar_churn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    db_path.write_bytes(b"")
    _force_windows_without_fd_bound(monkeypatch)
    original_parent_state = sqlite_util._parent_directory_state  # pyright: ignore[reportPrivateUsage]
    parent_state_calls = 0

    def fake_parent_directory_state(
        path: Path,
    ) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        nonlocal parent_state_calls
        identity, token = original_parent_state(path)
        if Path(path) == db_path and token is not None:
            parent_state_calls += 1
            # Each pathname open is followed by another rename-and-restore:
            # a fresh capture cannot make a continually ambiguous open safe.
            revision = parent_state_calls // 2
            return identity, (token[0] + revision, token[1] + revision)
        return identity, token

    monkeypatch.setattr(
        sqlite_util,
        "_parent_directory_state",
        fake_parent_directory_state,
    )

    def unchanged_sidecar_state(_path: Path) -> tuple[tuple[str, tuple[int, int] | None], ...]:
        return (("-wal", None), ("-shm", None), ("-journal", None))

    monkeypatch.setattr(
        sqlite_util,
        "_sqlite_sidecar_state",
        unchanged_sidecar_state,
    )

    with pytest.raises(PermissionError, match="database path changed during open"):
        sqlite_util.safe_sqlite_connect(db_path)

    assert parent_state_calls == 2 * sqlite_util._OPEN_VERIFICATION_RETRIES  # pyright: ignore[reportPrivateUsage]


def test_windows_path_connect_parent_change_keeps_sidecar_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    db_path.write_bytes(b"")
    file_stat = db_path.stat()
    state = sqlite_util._OpenVerificationState(  # pyright: ignore[reportPrivateUsage]
        expected_identity=(file_stat.st_dev, file_stat.st_ino),
        existing_path=True,
        path_change_token=(3, 4),
        parent_identity=(11, 22),
        parent_change_token=(1, 2),
        sidecar_state=(("-wal", None), ("-shm", None), ("-journal", None)),
        nofollow_fd=123,
        windows_path_name_connect_without_fd_bound=True,
    )

    def changed_parent_token(_path: Path) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        return (11, 22), (9, 10)

    def changed_sidecar_state(_path: Path) -> tuple[tuple[str, tuple[int, int] | None], ...]:
        return (("-wal", (31, 41)), ("-shm", None), ("-journal", None))

    monkeypatch.setattr(sqlite_util, "_parent_directory_state", changed_parent_token)
    monkeypatch.setattr(sqlite_util, "_sqlite_sidecar_state", changed_sidecar_state)

    with pytest.raises(sqlite_util._RetryOpenVerification):  # pyright: ignore[reportPrivateUsage]
        sqlite_util._verify_parent_directory_unchanged(db_path, state)  # pyright: ignore[reportPrivateUsage]


def test_windows_path_connect_parent_identity_change_is_not_sidecar_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    db_path.write_bytes(b"")
    state = sqlite_util._OpenVerificationState(  # pyright: ignore[reportPrivateUsage]
        expected_identity=(101, 202),
        existing_path=True,
        path_change_token=(3, 4),
        parent_identity=(11, 22),
        parent_change_token=(1, 2),
        sidecar_state=(("-wal", None), ("-shm", None), ("-journal", None)),
        nofollow_fd=123,
        windows_path_name_connect_without_fd_bound=True,
    )

    def changed_parent_identity(
        _path: Path,
    ) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        return (12, 23), (9, 10)

    def changed_sidecar_state(_path: Path) -> tuple[tuple[str, tuple[int, int] | None], ...]:
        return (("-wal", (31, 41)), ("-shm", None), ("-journal", None))

    monkeypatch.setattr(sqlite_util, "_parent_directory_state", changed_parent_identity)
    monkeypatch.setattr(sqlite_util, "_sqlite_sidecar_state", changed_sidecar_state)

    with pytest.raises(PermissionError, match="database path changed during open"):
        sqlite_util._verify_parent_directory_unchanged(db_path, state)  # pyright: ignore[reportPrivateUsage]


def test_windows_path_connect_rejects_unknown_fd_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    db_path.write_bytes(b"")
    state = sqlite_util._OpenVerificationState(  # pyright: ignore[reportPrivateUsage]
        expected_identity=(0, 0),
        existing_path=True,
        nofollow_fd=123,
        windows_path_name_connect_without_fd_bound=True,
    )

    def unknown_identity_fstat(_fd: int) -> SimpleNamespace:
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_dev=0, st_ino=0, st_nlink=1)

    monkeypatch.setattr(sqlite_util.sys, "platform", "win32")
    monkeypatch.setattr(sqlite_util.os, "fstat", unknown_identity_fstat)

    with pytest.raises(PermissionError, match="database path identity unavailable"):
        sqlite_util._verify_nofollow_fd_identity(db_path, state)  # pyright: ignore[reportPrivateUsage]


def test_windows_rejects_unknown_link_count_for_database_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    db_path.write_bytes(b"")
    monkeypatch.setattr(sqlite_util.sys, "platform", "win32")

    with pytest.raises(PermissionError, match="link count unavailable"):
        sqlite_util._reject_hardlink_stat(  # pyright: ignore[reportPrivateUsage]
            db_path,
            cast("Any", SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=0)),
        )


def test_safe_sqlite_connect_rejects_reparse_ancestor_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "state"
    parent.mkdir()
    db_path = parent / "review.sqlite"
    real_lstat = sqlite_util.os.lstat

    def fake_lstat(path: str | Path) -> os.stat_result:  # type: ignore[return-value]
        if Path(path) == parent:
            return _reparse_stat(stat.S_IFDIR | 0o700)
        return real_lstat(path)  # type: ignore[arg-type]

    monkeypatch.setattr(sqlite_util.sys, "platform", "win32")
    monkeypatch.setattr(sqlite_util.os, "lstat", fake_lstat)

    with pytest.raises(PermissionError, match="NTFS reparse point"):
        sqlite_util.safe_sqlite_connect(db_path)


def test_validate_state_dir_path_rejects_reparse_point_on_windows(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    real_lstat = Path.lstat

    def fake_lstat(self: Path) -> object:
        if self == state_dir:
            return _reparse_stat(stat.S_IFDIR | 0o700)
        return real_lstat(self)

    with (
        mock.patch.object(paths_module.sys, "platform", "win32"),
        mock.patch.object(Path, "lstat", fake_lstat),
        pytest.raises(InputError, match="Windows reparse point"),
    ):
        paths_module.validate_state_dir_path(state_dir)


def test_validate_state_path_no_symlinks_rejects_reparse_ancestor_on_windows(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    target_path = state_dir / "runs" / "run-1"
    real_lstat = Path.lstat

    def fake_lstat(self: Path) -> object:
        if self == state_dir:
            return _reparse_stat(stat.S_IFDIR | 0o700)
        return real_lstat(self)

    with (
        mock.patch.object(paths_module.sys, "platform", "win32"),
        mock.patch.object(Path, "lstat", fake_lstat),
        pytest.raises(InputError, match="Windows reparse points"),
    ):
        paths_module.validate_state_path_no_symlinks(target_path)


def test_ensure_state_gitignore_does_not_follow_symlink_without_nofollow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _supports_symlinks(tmp_path):
        pytest.skip("symlink creation unavailable")

    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    outside = tmp_path / "outside-gitignore"
    outside.write_text("outside\n", encoding="utf-8")
    link = state_dir / ".gitignore"
    link.symlink_to(outside)
    monkeypatch.setattr(paths_module.os, "O_NOFOLLOW", 0, raising=False)

    assert paths_module.ensure_state_gitignore(state_dir) == link

    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_write_provider_env_var_rejects_unsafe_state_gitignore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _supports_symlinks(tmp_path):
        pytest.skip("symlink creation unavailable")

    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    outside = tmp_path / "outside-gitignore"
    outside.write_text("outside\n", encoding="utf-8")
    link = state_dir / ".gitignore"
    link.symlink_to(outside)
    monkeypatch.setattr(paths_module.os, "O_NOFOLLOW", 0, raising=False)

    with pytest.raises(ConfigError, match="unsafe state gitignore"):
        write_provider_env_var(state_dir / ".env", "AHADIFF_DEMO_KEY", "redacted-test-key")

    assert not (state_dir / ".env").exists()
    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_ensure_state_gitignore_appends_missing_patterns_to_regular_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    gitignore_path = state_dir / ".gitignore"
    gitignore_path.write_text("# user-owned\n.env\n", encoding="utf-8")
    monkeypatch.setattr(paths_module.os, "O_NOFOLLOW", 0, raising=False)

    assert paths_module.ensure_state_gitignore(state_dir) == gitignore_path

    gitignore_text = gitignore_path.read_text(encoding="utf-8")
    assert gitignore_text.startswith("# user-owned\n.env\n")
    for pattern in (".env.*", "audit.private.jsonl", "*.lock", "*.log"):
        assert pattern in gitignore_text.splitlines()
