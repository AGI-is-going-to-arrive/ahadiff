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
