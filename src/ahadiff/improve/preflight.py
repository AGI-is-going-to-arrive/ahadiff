"""Read-only helpers for improve preflight.

These helpers MUST NOT mutate filesystem, git state, locks, or worktrees.
They are intended to back the GET /api/improve/preflight endpoint and any
analogous read-only diagnostics. Each helper degrades silently to ``None`` /
``False`` rather than raising, so the preflight endpoint can always render a
useful payload even when git is missing or the repo is in an unusual state.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["current_branch", "current_head", "prompts_are_dirty"]

_GIT_TIMEOUT_SECONDS = 10


def current_branch(repo_root: Path) -> str | None:
    """Return the current branch name (``HEAD`` for detached) or ``None`` on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=repo_root,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def current_head(repo_root: Path) -> str | None:
    """Return the current HEAD SHA (40 hex) or ``None`` if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=repo_root,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def prompts_are_dirty(repo_root: Path) -> bool:
    """Return True if ``prompts/`` has unstaged or staged uncommitted changes.

    ``git diff --quiet`` returns 0 when clean, 1 when dirty. We also re-check
    the index with ``--cached`` so committed-but-staged changes count too.
    """
    if _git_diff_dirty(repo_root, cached=False):
        return True
    return _git_diff_dirty(repo_root, cached=True)


def _git_diff_dirty(repo_root: Path, *, cached: bool) -> bool:
    args = ["git", "diff", "--quiet"]
    if cached:
        args.append("--cached")
    args.extend(["--", "prompts/"])
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            cwd=repo_root,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return result.returncode == 1
