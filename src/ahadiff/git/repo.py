from __future__ import annotations

import collections.abc as _collections_abc
import errno
import os
import pathlib as _pathlib
import stat
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TextIO

import portalocker

from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.paths import find_repo_root

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _has_windows_reparse_point(path_stat: object) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


if TYPE_CHECKING:
    from collections.abc import Iterator
else:
    Iterator = _collections_abc.Iterator

Path = _pathlib.Path

_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


@dataclass(frozen=True)
class GitRepo:
    root: Path
    head_sha: str | None
    head_short_sha: str | None
    head_detached: bool
    current_branch: str | None


@dataclass(frozen=True)
class LockMetadata:
    pid: str | None
    start_time_iso: str | None
    command: str | None


_DEFAULT_GIT_TIMEOUT_SECONDS = 120


def run_git(
    repo_root: Path,
    *args: str,
    input_text: str | None = None,
    check: bool = True,
    timeout: int | None = _DEFAULT_GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    command = ["git", "-c", "core.quotePath=false", "-C", str(repo_root), *args]
    try:
        result = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise InputError(f"git command timed out after {timeout}s: {' '.join(args)}") from exc
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise InputError(message or f"git command failed: {' '.join(args)}")
    return result


def run_git_bytes(
    repo_root: Path,
    *args: str,
    input_bytes: bytes | None = None,
    timeout: int | None = _DEFAULT_GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-c", "core.quotePath=false", "-C", str(repo_root), *args],
            input=input_bytes,
            capture_output=True,
            text=False,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise InputError(f"git command timed out after {timeout}s: {' '.join(args)}") from exc


def open_repo(repo_root: Path | None = None) -> GitRepo:
    root = find_repo_root(repo_root)
    bare_result = run_git(root, "rev-parse", "--is-bare-repository")
    if bare_result.stdout.strip() == "true":
        raise InputError("bare repo is not supported for diff capture")

    head_result = run_git(root, "rev-parse", "--verify", "HEAD", check=False)
    head_sha = head_result.stdout.strip() if head_result.returncode == 0 else None
    head_sha = head_sha or None
    head_short_sha = head_sha[:12] if head_sha else None

    detached_result = run_git(root, "symbolic-ref", "-q", "HEAD", check=False)
    head_detached = detached_result.returncode != 0
    current_branch = None
    if not head_detached:
        branch_result = run_git(root, "branch", "--show-current", check=False)
        current_branch = branch_result.stdout.strip() or None

    return GitRepo(
        root=root,
        head_sha=head_sha,
        head_short_sha=head_short_sha,
        head_detached=head_detached,
        current_branch=current_branch,
    )


def ensure_head_exists(repo: GitRepo) -> str:
    if repo.head_sha is None:
        raise InputError("unborn HEAD is not supported for this input mode")
    return repo.head_sha


def ensure_no_merge_conflicts(repo: GitRepo) -> None:
    conflict_result = run_git(repo.root, "diff", "--name-only", "--diff-filter=U", check=False)
    if conflict_result.returncode == 0 and conflict_result.stdout.strip():
        raise InputError("merge conflicts detected; resolve unmerged paths before learn")


def resolve_ref_range(repo: GitRepo, revision_range: str) -> tuple[str, str]:
    if ".." not in revision_range:
        raise InputError("commit range must use '..' syntax such as HEAD~1..HEAD")

    base_ref, head_ref = revision_range.split("..", 1)
    base_resolved = _resolve_commitish(repo.root, base_ref)
    head_resolved = _resolve_commitish(repo.root, head_ref)
    return base_resolved, head_resolved


def resolve_commitish(repo: GitRepo, revision: str) -> str:
    return _resolve_commitish(repo.root, revision)


def parent_count(repo_root: Path, revision: str) -> int:
    result = run_git(repo_root, "show", "-s", "--format=%P", revision)
    parents = [item for item in result.stdout.strip().split() if item]
    return len(parents)


def first_parent_or_empty_tree(repo_root: Path, revision: str) -> str:
    result = run_git(repo_root, "show", "-s", "--format=%P", revision)
    parents = [item for item in result.stdout.strip().split() if item]
    if not parents:
        if _is_shallow_boundary(repo_root, revision):
            raise InputError(
                "shallow clone boundary reached; fetch more history before using this input mode"
            )
        return _EMPTY_TREE_SHA
    first_parent = parents[0]
    parent_exists = run_git(
        repo_root,
        "cat-file",
        "-e",
        f"{first_parent}^{{commit}}",
        check=False,
    )
    if parent_exists.returncode != 0:
        raise InputError(
            "shallow clone boundary reached; fetch more history before using this input mode"
        )
    return first_parent


def _is_shallow_boundary(repo_root: Path, revision: str) -> bool:
    shallow_state = run_git(repo_root, "rev-parse", "--is-shallow-repository", check=False)
    if shallow_state.returncode != 0 or shallow_state.stdout.strip() != "true":
        return False

    git_dir_result = run_git(repo_root, "rev-parse", "--git-dir", check=False)
    if git_dir_result.returncode != 0:
        return False
    git_dir = Path(git_dir_result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (repo_root / git_dir).resolve()
    shallow_file = git_dir / "shallow"
    if not shallow_file.exists():
        return False
    boundaries = {line.strip() for line in shallow_file.read_text(encoding="utf-8").splitlines()}
    return revision in boundaries


def read_lock_metadata(lock_path: Path) -> LockMetadata:
    if not lock_path.exists():
        return LockMetadata(pid=None, start_time_iso=None, command=None)

    return _lock_metadata_from_text(lock_path.read_text(encoding="utf-8"))


def _lock_metadata_from_text(text: str) -> LockMetadata:
    lines = text.splitlines()
    pid = lines[0] if len(lines) >= 1 and lines[0] else None
    started = lines[1] if len(lines) >= 2 and lines[1] else None
    command = lines[2] if len(lines) >= 3 and lines[2] else None
    return LockMetadata(pid=pid, start_time_iso=started, command=command)


def _read_lock_metadata_from_handle(handle: TextIO) -> LockMetadata:
    handle.seek(0)
    return _lock_metadata_from_text(handle.read())


@contextmanager
def repo_write_lock(lock_path: Path, *, command: str) -> Iterator[Path]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path_stat = lock_path.lstat()
    except FileNotFoundError:
        path_stat = None
    else:
        if stat.S_ISLNK(path_stat.st_mode):
            raise InputError("repo write lock path must not be a symlink")
        if _has_windows_reparse_point(path_stat):
            raise InputError("repo write lock path must not be a Windows reparse point")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(lock_path), flags, 0o644)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError("repo write lock path must not be a symlink") from exc
        raise
    try:
        file_stat = os.fstat(fd)
        path_stat = lock_path.lstat()
        if stat.S_ISLNK(path_stat.st_mode):
            raise InputError("repo write lock path must not be a symlink")
        if _has_windows_reparse_point(file_stat) or _has_windows_reparse_point(path_stat):
            raise InputError("repo write lock path must not be a Windows reparse point")
        if not stat.S_ISREG(file_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise StorageError("repo write lock path must be a regular file")
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError("repo write lock path changed during acquisition")
    except Exception:
        os.close(fd)
        raise
    handle = os.fdopen(fd, "a+", encoding="utf-8")
    try:
        try:
            portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
        except portalocker.exceptions.LockException as exc:
            handle.flush()
            metadata = _read_lock_metadata_from_handle(handle)
            suffix = f" (PID={metadata.pid})" if metadata.pid else ""
            raise StorageError(f"another ahadiff process is already running{suffix}") from exc

        handle.seek(0)
        handle.truncate(0)
        payload = "\n".join(
            (
                str(os.getpid()),
                datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                command,
            )
        )
        handle.write(payload + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        yield lock_path
    finally:
        try:
            portalocker.unlock(handle)
        finally:
            handle.close()


def unlock_repo_write_lock(lock_path: Path) -> bool:
    try:
        lock_lstat = lock_path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(lock_lstat.st_mode):
        raise StorageError("repo write lock path must not be a symlink")
    if _has_windows_reparse_point(lock_lstat):
        raise StorageError("repo write lock path must not be a Windows reparse point")
    if not stat.S_ISREG(lock_lstat.st_mode):
        raise StorageError("repo write lock path must be a regular file")

    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(lock_path), flags)
    except FileNotFoundError:
        return False
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise StorageError("repo write lock path must not be a symlink") from exc
        raise

    handle = os.fdopen(fd, "r+", encoding="utf-8")
    try:
        try:
            portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
        except portalocker.exceptions.LockException as exc:
            raise StorageError("repo write lock is active; refusing to force-remove it") from exc

        file_stat = os.fstat(handle.fileno())
        try:
            path_stat = lock_path.lstat()
        except FileNotFoundError:
            return False
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or (file_stat.st_dev, file_stat.st_ino) != (lock_lstat.st_dev, lock_lstat.st_ino)
            or (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise StorageError("repo write lock changed during force unlock; retry the command")

        handle.seek(0)
        handle.truncate(0)
        handle.flush()
        os.fsync(handle.fileno())
        try:
            lock_path.unlink()
        except FileNotFoundError:
            return True
        except OSError:
            return True
        return True
    finally:
        try:
            portalocker.unlock(handle)
        finally:
            handle.close()


def _resolve_commitish(repo_root: Path, revision: str) -> str:
    result = run_git(repo_root, "rev-parse", "--verify", f"{revision}^{{commit}}", check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise InputError(message or f"unknown commit reference: {revision}")
    return result.stdout.strip()


__all__ = [
    "GitRepo",
    "LockMetadata",
    "ensure_head_exists",
    "ensure_no_merge_conflicts",
    "first_parent_or_empty_tree",
    "open_repo",
    "parent_count",
    "read_lock_metadata",
    "repo_write_lock",
    "resolve_commitish",
    "resolve_ref_range",
    "run_git",
    "run_git_bytes",
    "unlock_repo_write_lock",
]
