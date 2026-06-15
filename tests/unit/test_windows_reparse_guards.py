# pyright: reportReturnType=false
from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

import pytest

from ahadiff.core import paths as paths_module
from ahadiff.core import sqlite_util
from ahadiff.core.config import write_provider_env_var
from ahadiff.core.errors import ConfigError, InputError

if TYPE_CHECKING:
    import os

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


def test_safe_sqlite_connect_missing_database_without_dir_fd_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    _force_windows_without_fd_bound(monkeypatch)

    with pytest.raises(PermissionError, match="fd-bound open support"):
        sqlite_util.safe_sqlite_connect(db_path)

    assert not db_path.exists()


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
    db_path.symlink_to(target)
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
            if parent_state_calls == 1:
                return identity, token
            return identity, (token[0] + 1, token[1] + 1)
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


def test_windows_path_connect_parent_change_keeps_sidecar_retry(
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
