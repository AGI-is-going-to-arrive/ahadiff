# pyright: reportReturnType=false
from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from ahadiff.core import paths as paths_module
from ahadiff.core import sqlite_util
from ahadiff.core.errors import InputError

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


def test_safe_sqlite_connect_missing_database_without_dir_fd_fails_without_fd_bound_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "review.sqlite"
    monkeypatch.setattr(sqlite_util.os, "supports_dir_fd", set[object]())
    monkeypatch.setattr(sqlite_util, "_sqlite_proc_fd_path", _no_sqlite_fd_path)

    for _ in range(2):
        with pytest.raises(PermissionError, match="fd-bound open support"):
            sqlite_util.safe_sqlite_connect(db_path)
        assert not db_path.exists()


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

    with pytest.raises(PermissionError, match="parent changed|symlink"):
        sqlite_util.safe_sqlite_connect(db_path)

    assert swapped
    outside_db = outside / "review.sqlite"
    if outside_db.exists():
        assert not outside_db.read_bytes().startswith(b"SQLite format 3")


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
