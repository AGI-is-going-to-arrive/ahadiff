from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ahadiff.core.errors import InputError, SafetyError
from ahadiff.safety.ignore import (
    escape_html_text,
    escape_json_text,
    escape_terminal_text,
    is_ignored_path,
    load_ignore_matcher,
    resolve_safe_path,
    resolve_safe_path_from_root,
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


def test_load_ignore_matcher_rejects_symlink_ignore_file(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not available on this platform")

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    outside = tmp_path / "outside-ignore"
    outside.write_text("secret.txt\n", encoding="utf-8")
    try:
        os.symlink(outside, repo_root / ".ahadiffignore")
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(SafetyError, match=r"\.ahadiffignore must not be a symlink"):
        load_ignore_matcher(repo_root)


def test_load_ignore_matcher_rejects_oversized_ignore_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiffignore").write_bytes(b"x" * 1_000_001)

    with pytest.raises(SafetyError, match=r"\.ahadiffignore exceeds 1000000 bytes"):
        load_ignore_matcher(repo_root)


def test_load_ignore_matcher_rejects_hardlinked_ignore_file(tmp_path: Path) -> None:
    if not hasattr(os, "link"):
        pytest.skip("hardlinks are not available on this platform")

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    outside = tmp_path / "outside-ignore"
    outside.write_text("secret.txt\n", encoding="utf-8")
    try:
        os.link(outside, repo_root / ".ahadiffignore")
    except OSError as exc:
        pytest.skip(f"hardlink creation unavailable: {exc}")

    with pytest.raises(SafetyError, match=r"\.ahadiffignore must not be a hardlink"):
        load_ignore_matcher(repo_root)


def test_load_ignore_matcher_rejects_special_ignore_file(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo is not available on this platform")

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    try:
        os.mkfifo(repo_root / ".ahadiffignore")
    except OSError as exc:
        pytest.skip(f"fifo creation unavailable: {exc}")

    with pytest.raises(SafetyError, match=r"\.ahadiffignore must be a regular file"):
        load_ignore_matcher(repo_root)


def test_resolve_safe_path_rejects_repo_escape(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(SafetyError, match="path escapes repo root"):
        resolve_safe_path(repo_root, "../outside.txt")


def test_resolve_safe_path_rejects_absolute_path_outside_repo(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(SafetyError, match="path is outside repo root"):
        resolve_safe_path_from_root(repo_root, outside)


@pytest.mark.parametrize(
    "candidate",
    [
        ".ahadiff/.env",
        ".ahadiff/runs/run-1/metadata.json",
        ".git/config",
        "nested/.git/config",
    ],
)
def test_resolve_safe_path_rejects_internal_state_components(
    tmp_path: Path,
    candidate: str,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    target = repo_root / candidate
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret\n", encoding="utf-8")

    with pytest.raises(InputError, match="capture input may not read"):
        resolve_safe_path_from_root(repo_root, candidate)


@pytest.mark.parametrize(
    "candidate",
    [
        ".AHADIFF/.env",
        ".Ahadiff/.env",
        ".Git/config",
        "nested/.GIT/config",
        ".ahadiff./.env",
        ".ahadiff /.env",
        ".AHADIFF./.env",
        ".git./config",
    ],
)
def test_resolve_safe_path_rejects_internal_state_case_variants(
    tmp_path: Path,
    candidate: str,
) -> None:
    # A case-variant of .ahadiff/.git must not bypass the internal-state guard: on a
    # case-insensitive filesystem (macOS APFS / Windows NTFS) ".AHADIFF/.env" aliases the
    # real ".ahadiff/.env" and would otherwise leak provider secrets into capture.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir(exist_ok=True)
    (repo_root / ".ahadiff" / ".env").write_text("AHADIFF_X_KEY=sk-secret123\n", encoding="utf-8")

    with pytest.raises(InputError, match="capture input may not read"):
        resolve_safe_path_from_root(repo_root, candidate)


@pytest.mark.parametrize("candidate", ["change.diff", "SPEC.md", "src/.gitkeep"])
def test_resolve_safe_path_allows_normal_repo_relative_files(
    tmp_path: Path,
    candidate: str,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    target = repo_root / candidate
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ok\n", encoding="utf-8")

    assert resolve_safe_path_from_root(repo_root, candidate) == target.resolve()


@pytest.mark.parametrize("candidate", ["C:secret.txt", "C:/repo/secret.txt", "//server/share/x"])
def test_resolve_safe_path_rejects_windows_drive_and_unc_syntax(
    tmp_path: Path,
    candidate: str,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    with pytest.raises(SafetyError, match="Windows drive or UNC syntax"):
        resolve_safe_path_from_root(repo_root, candidate)


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
    try:
        os.symlink(real_parent, alias_parent)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

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
