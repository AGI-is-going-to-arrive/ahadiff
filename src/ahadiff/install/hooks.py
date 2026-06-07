from __future__ import annotations

import errno
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.git.repo import git_clean_env

from .base import (
    InstallAction,
    InstallContext,
)
from .common import plan_for, repo_path
from .template_loader import render_template

_VALID_HOOK_NAMES = frozenset(
    {
        "pre_learn",
        "post_learn",
        "pre_improve",
        "post_improve",
        "pre_review",
        "post_review",
    }
)
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_GIT_TIMEOUT_SECONDS = 30

HOOKS_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "pre_learn": {"type": "array", "items": {"type": "string"}},
        "post_learn": {"type": "array", "items": {"type": "string"}},
        "pre_improve": {"type": "array", "items": {"type": "string"}},
        "post_improve": {"type": "array", "items": {"type": "string"}},
        "pre_review": {"type": "array", "items": {"type": "string"}},
        "post_review": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def load_hooks(state_dir: Path) -> dict[str, list[str]]:
    hooks_path = state_dir / "hooks.json"
    try:
        raw = _read_text_no_follow(hooks_path)
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    try:
        data: Any = safe_json_loads(raw)
    except (TypeError, ValueError) as exc:
        raise InputError(f"hooks.json is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        return {}
    parsed = cast("dict[str, Any]", data)
    return validate_hooks(parsed)


def _read_text_no_follow(path: Path, description: str = "hooks.json") -> str:
    content, _ = _read_text_with_stat_no_follow(path, description)
    return content


def _read_text_with_stat_no_follow(
    path: Path,
    description: str,
) -> tuple[str, os.stat_result]:
    path_stat = path.lstat()
    if stat.S_ISLNK(path_stat.st_mode):
        raise OSError(errno.ELOOP, f"refusing to follow {description} symlink", str(path))
    if _has_windows_reparse_point(path_stat):
        raise OSError(errno.ELOOP, f"refusing to follow {description} reparse point", str(path))
    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError(errno.EINVAL, f"{description} must be a regular file", str(path))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    try:
        opened_stat = os.fstat(fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise OSError(errno.EINVAL, f"{description} must be a regular file", str(path))
        if _has_windows_reparse_point(opened_stat):
            raise OSError(errno.ELOOP, f"refusing to follow {description} reparse point", str(path))
        if (opened_stat.st_dev, opened_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise OSError(errno.ELOOP, f"{description} changed during validation", str(path))
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as handle:
            fd = -1
            return handle.read(), path_stat
    finally:
        if fd != -1:
            os.close(fd)


def _has_windows_reparse_point(path_stat: os.stat_result) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def validate_hooks(hooks: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, value in hooks.items():
        if key not in _VALID_HOOK_NAMES:
            raise InputError(f"Unknown hook name: {key!r}")
        if not isinstance(value, list):
            raise InputError(f"Hook {key!r} must be an array of strings")
        entries = cast("list[Any]", value)
        checked: list[str] = []
        for entry in entries:
            if not isinstance(entry, str):
                raise InputError(f"Hook {key!r} contains non-string item: {entry!r}")
            checked.append(entry)
        result[key] = checked
    return result


@dataclass(frozen=True)
class HookContext:
    hook_name: str
    tool_name: str
    repo_path: str
    state_dir: str
    run_id: str | None = None


def build_hook_context(
    hook_name: str,
    tool_name: str,
    repo_path_val: Path,
    state_dir: Path,
    run_id: str | None = None,
) -> HookContext:
    return HookContext(
        hook_name=hook_name,
        tool_name=tool_name,
        repo_path=str(repo_path_val),
        state_dir=str(state_dir),
        run_id=run_id,
    )


class HooksTarget:
    name = "hooks"

    def detect(self, context: InstallContext) -> bool:
        if sys.platform == "win32":
            return False
        marker = f"# AHADIFF:BEGIN target={self.name}"
        for path in self._hook_paths(context):
            try:
                content = _read_text_no_follow(path, "git hook")
            except FileNotFoundError:
                continue
            except OSError:
                continue
            if marker in content:
                return True
        return False

    def preview(self, context: InstallContext) -> str:
        _ensure_posix_hooks_supported()
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        _ensure_posix_hooks_supported()
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        _ensure_posix_hooks_supported()
        _ensure_git_repo(context)
        post_commit, pre_push = self._hook_paths(context)
        # Auto-learn v1 semantics:
        # - Concurrent commits rely on the per-repo write lock; the second in-flight
        #   learn fails fast into .ahadiff/hooks.log instead of blocking the commit.
        # - The normal learnability gate still applies to background hook learns.
        # - SQLite runtime gate failures fail fast and are written to hooks.log.
        post_commit_template = (
            "post_commit_hook_auto.sh.j2" if context.auto_learn else "post_commit_hook.sh.j2"
        )
        _append_hook_section(
            post_commit,
            self.name,
            render_template(post_commit_template),
        )
        _append_hook_section(
            pre_push,
            self.name,
            render_template("pre_push_hook.sh.j2"),
        )
        return [post_commit, pre_push]

    def uninstall(self, context: InstallContext) -> list[Path]:
        _ensure_posix_hooks_supported()
        removed: list[Path] = []
        for path in self._hook_paths(context):
            if _remove_hook_section(path, self.name):
                removed.append(path)
        return removed

    def _plan(self, context: InstallContext):
        post_commit, pre_push = self._hook_paths(context)
        summary = (
            "Install non-blocking AhaDiff git hooks with auto-learn after commits."
            if context.auto_learn
            else "Install non-blocking AhaDiff git hook reminders."
        )
        return plan_for(
            self.name,
            summary,
            [
                InstallAction(post_commit, "merge-section"),
                InstallAction(pre_push, "merge-section"),
            ],
        )

    def _hook_paths(self, context: InstallContext) -> tuple[Path, Path]:
        return (
            _git_path(context, "hooks/post-commit"),
            _git_path(context, "hooks/pre-push"),
        )


def _append_hook_section(path: Path, target: str, section: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    original_mode: int | None = None
    try:
        original, path_stat = _read_text_with_stat_no_follow(path, "git hook")
        original_mode = stat.S_IMODE(path_stat.st_mode)
        existing_hook = True
    except FileNotFoundError:
        original = ""
        existing_hook = False
    if existing_hook:
        pattern = _hook_pattern(target)
        if pattern.search(original):
            content = pattern.sub(
                lambda match: _hook_replacement(match, section),
                original,
                count=1,
            )
        else:
            separator = "\n\n" if original and not original.endswith("\n\n") else ""
            content = f"{original}{separator}{section}"
    else:
        content = f"#!/bin/sh\n\n{section}"
    _atomic_write_hook_text(path, content, original_mode)
    if not existing_hook:
        path.chmod(stat.S_IMODE(path.lstat().st_mode) | 0o111)


def _remove_hook_section(path: Path, target: str) -> bool:
    try:
        original, path_stat = _read_text_with_stat_no_follow(path, "git hook")
    except FileNotFoundError:
        return False
    original_mode = stat.S_IMODE(path_stat.st_mode)
    updated, count = _hook_pattern(target).subn("\n", original)
    if count == 0:
        return False
    if updated.strip():
        _atomic_write_hook_text(path, updated.strip(), original_mode)
    else:
        path.unlink()
    return True


def _atomic_write_hook_text(path: Path, content: str, original_mode: int | None) -> None:
    temp_path: Path | None = None
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.ahadiff.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        try:
            if original_mode is not None:
                os.fchmod(handle.fileno(), original_mode)
            handle.write(content if content.endswith("\n") else f"{content}\n")
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    try:
        temp_path.replace(path)
        if original_mode is not None:
            path.chmod(original_mode)
    finally:
        temp_path.unlink(missing_ok=True)


def _hook_pattern(target: str) -> re.Pattern[str]:
    return re.compile(
        rf"\n?# AHADIFF:BEGIN target={re.escape(target)}.*?"
        rf"# AHADIFF:END\n?",
        re.DOTALL,
    )


def _hook_replacement(match: re.Match[str], section: str) -> str:
    prefix = "\n" if match.group(0).startswith("\n") else ""
    return f"{prefix}{section.strip()}"


def _ensure_git_repo(context: InstallContext) -> None:
    _git_path(context, "hooks")


def _ensure_posix_hooks_supported() -> None:
    if sys.platform == "win32":
        raise InputError("hooks target is POSIX-shell only and is not supported on Windows")


def _git_executable() -> str:
    """Locate the git executable on PATH.

    Raises ``InputError`` when git is missing so callers surface an
    actionable error instead of an opaque OSError.
    """

    git_path = shutil.which("git")
    if git_path is None:
        raise InputError("git executable not found on PATH; install git and ensure it is on PATH")
    return git_path


def _git_path(context: InstallContext, relative: str) -> Path:
    try:
        result = subprocess.run(
            [_git_executable(), "rev-parse", "--git-path", relative],
            cwd=context.repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            env=git_clean_env(),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise InputError("hooks target requires a git repository") from exc
    raw_path = Path(result.stdout.rstrip("\r\n"))
    hook_path = raw_path if raw_path.is_absolute() else repo_path(context, raw_path.as_posix())
    return _validate_git_hook_path(context, hook_path)


def _validate_git_hook_path(context: InstallContext, hook_path: Path) -> Path:
    resolved_hook_path = hook_path.resolve(strict=False)
    repo_root = context.repo_root.resolve(strict=False)
    if resolved_hook_path.is_relative_to(repo_root):
        return hook_path
    git_dir = _absolute_git_dir(context)
    if resolved_hook_path.is_relative_to(git_dir):
        return hook_path
    git_common_dir = _git_common_dir(context)
    if resolved_hook_path.is_relative_to(git_common_dir):
        return hook_path
    raise InputError("resolved git hook path must stay within the repository root or git directory")


def _absolute_git_dir(context: InstallContext) -> Path:
    return _git_directory_path(context, "--absolute-git-dir")


def _git_common_dir(context: InstallContext) -> Path:
    return _git_directory_path(context, "--git-common-dir")


def _git_directory_path(context: InstallContext, option: str) -> Path:
    try:
        result = subprocess.run(
            [_git_executable(), "rev-parse", option],
            cwd=context.repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            env=git_clean_env(),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise InputError("hooks target requires a git repository") from exc
    raw_path = Path(result.stdout.rstrip("\r\n"))
    path = raw_path if raw_path.is_absolute() else repo_path(context, raw_path.as_posix())
    return path.resolve(strict=False)
