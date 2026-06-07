"""Read-only helpers for improve preflight.

These helpers MUST NOT mutate filesystem, git state, locks, or worktrees.
They are intended to back the GET /api/improve/preflight endpoint and any
analogous read-only diagnostics. Each helper degrades silently to ``None`` /
``False`` rather than raising, so the preflight endpoint can always render a
useful payload even when git is missing or the repo is in an unusual state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ahadiff.core.errors import AhaDiffError, InputError
from ahadiff.git.repo import run_git

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "assert_prompt_tuning_source_checkout",
    "current_branch",
    "current_head",
    "prompt_tuning_missing_head_paths",
    "prompts_are_dirty",
]

_GIT_TIMEOUT_SECONDS = 10
_PROMPT_TUNING_SOURCE_CHECKOUT_ERROR = (
    "prompt-tuning improve only runs inside an ahadiff source checkout; "
    "use `ahadiff improve-run <run_id>` to regenerate a lesson"
)


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


def prompt_tuning_missing_head_paths(repo_root: Path) -> tuple[str, ...]:
    """Return mutable prompt paths that are absent from repo HEAD."""
    from .program import mutable_prompt_names

    missing: list[str] = []
    for filename in mutable_prompt_names():
        for relative_path in (
            f"prompts/{filename}",
            f"src/ahadiff/prompts/{filename}",
        ):
            if not _head_path_exists(repo_root, relative_path):
                missing.append(relative_path)
    return tuple(missing)


def assert_prompt_tuning_source_checkout(repo_root: Path) -> None:
    """Fail fast when prompt-tuning improve is invoked outside AhaDiff source."""
    if prompt_tuning_missing_head_paths(repo_root):
        raise AhaDiffError(_PROMPT_TUNING_SOURCE_CHECKOUT_ERROR)


def _head_path_exists(repo_root: Path, relative_path: str) -> bool:
    try:
        result = run_git(
            repo_root,
            "cat-file",
            "-e",
            f"HEAD:{relative_path}",
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (InputError, OSError):
        return False
    return result.returncode == 0
