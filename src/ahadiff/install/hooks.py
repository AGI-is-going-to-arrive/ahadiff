from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from ahadiff.core.errors import InputError

from .base import (
    InstallAction,
    InstallContext,
)
from .common import plan_for, repo_path
from .template_loader import render_template


class HooksTarget:
    name = "hooks"

    def detect(self, context: InstallContext) -> bool:
        return any(
            f"# AHADIFF:BEGIN target={self.name}" in path.read_text(encoding="utf-8")
            for path in self._hook_paths(context)
            if path.exists()
        )

    def preview(self, context: InstallContext) -> str:
        _ensure_posix_hooks_supported()
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        _ensure_posix_hooks_supported()
        _ensure_git_repo(context)
        post_commit, pre_push = self._hook_paths(context)
        _append_hook_section(
            post_commit,
            self.name,
            render_template("post_commit_hook.sh.j2"),
        )
        _append_hook_section(
            pre_push,
            self.name,
            render_template("pre_push_hook.sh.j2"),
        )
        return [post_commit, pre_push]

    def uninstall(self, context: InstallContext) -> list[Path]:
        removed: list[Path] = []
        for path in self._hook_paths(context):
            if _remove_hook_section(path, self.name):
                removed.append(path)
        return removed

    def _plan(self, context: InstallContext):
        post_commit, pre_push = self._hook_paths(context)
        return plan_for(
            self.name,
            "Install non-blocking AhaDiff git hook reminders.",
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
    if path.exists():
        original = path.read_text(encoding="utf-8")
        pattern = _hook_pattern(target)
        if pattern.search(original):
            content = pattern.sub(section.strip(), original, count=1)
        else:
            separator = "\n\n" if original and not original.endswith("\n\n") else ""
            content = f"{original}{separator}{section}"
    else:
        content = f"#!/bin/sh\n\n{section}"
    temp_path = path.with_name(f".{path.name}.ahadiff.tmp")
    temp_path.write_text(content if content.endswith("\n") else f"{content}\n", encoding="utf-8")
    temp_path.replace(path)
    path.chmod(path.stat().st_mode | 0o111)


def _remove_hook_section(path: Path, target: str) -> bool:
    if not path.exists():
        return False
    original = path.read_text(encoding="utf-8")
    updated, count = _hook_pattern(target).subn("\n", original)
    if count == 0:
        return False
    if updated.strip():
        temp_path = path.with_name(f".{path.name}.ahadiff.tmp")
        temp_path.write_text(updated.strip() + "\n", encoding="utf-8")
        temp_path.replace(path)
    else:
        path.unlink()
    return True


def _hook_pattern(target: str) -> re.Pattern[str]:
    return re.compile(
        rf"\n?# AHADIFF:BEGIN target={re.escape(target)}.*?"
        rf"# AHADIFF:END\n?",
        re.DOTALL,
    )


def _ensure_git_repo(context: InstallContext) -> None:
    _git_path(context, "hooks")


def _ensure_posix_hooks_supported() -> None:
    if sys.platform == "win32":
        raise InputError("hooks target is POSIX-shell only in v0.1; Windows is not supported yet")


def _git_path(context: InstallContext, relative: str) -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", relative],
            cwd=context.repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InputError("hooks target requires a git repository") from exc
    raw_path = Path(result.stdout.strip())
    return raw_path if raw_path.is_absolute() else repo_path(context, raw_path.as_posix())
