from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ahadiff.core.errors import SafetyError
from ahadiff.safety.ignore import (
    escape_html_text,
    escape_json_text,
    escape_terminal_text,
    is_ignored_path,
    load_ignore_matcher,
    resolve_safe_path,
)

if TYPE_CHECKING:
    from pathlib import Path


def _init_git_repo(root: Path) -> None:
    (root / ".git").mkdir()


def test_load_ignore_matcher_filters_repo_relative_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiffignore").write_text("build/\n*.secret\n", encoding="utf-8")

    matcher = load_ignore_matcher(repo_root)

    assert is_ignored_path("build/output.txt", matcher) is True
    assert is_ignored_path("notes.secret", matcher) is True
    assert is_ignored_path("src/app.py", matcher) is False


def test_resolve_safe_path_rejects_repo_escape(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(SafetyError, match="path escapes repo root"):
        resolve_safe_path(repo_root, "../outside.txt")


def test_resolve_safe_path_allows_symlinked_repo_alias_ancestors(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not available on this platform")

    real_parent = tmp_path / "private"
    repo_root = real_parent / "repo"
    repo_root.mkdir(parents=True)
    _init_git_repo(repo_root)
    target = repo_root / "tracked.txt"
    target.write_text("x", encoding="utf-8")

    alias_parent = tmp_path / "alias"
    os.symlink(real_parent, alias_parent)

    resolved = resolve_safe_path(repo_root, alias_parent / "repo" / "tracked.txt")

    assert resolved == target


def test_resolve_safe_path_rejects_symlink_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    symlink = repo_root / "link.txt"
    symlink.symlink_to(outside)

    with pytest.raises(SafetyError, match="symlink paths are not allowed"):
        resolve_safe_path(repo_root, symlink)


def test_resolve_safe_path_rejects_fifo_when_available(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo is not available on this platform")

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    fifo_path = repo_root / "named.pipe"
    os.mkfifo(fifo_path)

    with pytest.raises(SafetyError, match="special files are not allowed"):
        resolve_safe_path(repo_root, fifo_path)


def test_escape_helpers_handle_html_json_and_terminal_sequences() -> None:
    assert escape_html_text("<script>") == "&lt;script&gt;"
    assert escape_json_text('line"\n') == '"line\\"\\n"'
    escaped = escape_terminal_text("\x1b[31malert\x1b[0m😀")
    assert "\x1b" not in escaped
    assert "\\x1b" in escaped
    assert "\\U0001f600" in escaped
