"""Read-only helpers for improve preflight.

These helpers MUST NOT mutate filesystem, git state, locks, or worktrees.
They are intended to back the GET /api/improve/preflight endpoint and any
analogous read-only diagnostics. Each helper degrades silently to ``None`` /
``False`` rather than raising, so the preflight endpoint can always render a
useful payload even when git is missing or the repo is in an unusual state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ahadiff.core.errors import InputError
from ahadiff.git.repo import run_git

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["current_branch", "current_head", "prompts_are_dirty"]

_GIT_TIMEOUT_SECONDS = 10


def current_branch(repo_root: Path) -> str | None:
    """Return the current branch name (``HEAD`` for detached) or ``None`` on failure."""
    try:
        result = run_git(
            repo_root,
            "rev-parse",
            "--abbrev-ref",
            "HEAD",
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (InputError, OSError):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def current_head(repo_root: Path) -> str | None:
    """Return the current HEAD SHA (40 hex) or ``None`` if git is unavailable."""
    try:
        result = run_git(
            repo_root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            "HEAD",
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (InputError, OSError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def prompts_are_dirty(repo_root: Path) -> bool:
    """Return True if mutable prompt files have any git-visible local changes."""
    args = [
        "status",
        "--porcelain",
        "--",
        "prompts",
        "src/ahadiff/prompts",
    ]
    try:
        result = run_git(
            repo_root,
            *args,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (InputError, OSError):
        return False
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())
