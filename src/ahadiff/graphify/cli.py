"""Optional Graphify CLI detection and invocation."""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)

_GRAPHIFY_UPDATE_TIMEOUT = 120  # seconds


def detect_graphify_cli() -> str | None:
    """Return the path to the graphify executable, or None if not found."""
    return shutil.which("graphify")


def run_graphify_update(workspace_root: Path, *, timeout: int = _GRAPHIFY_UPDATE_TIMEOUT) -> bool:
    """Run ``graphify update <workspace_root>`` to regenerate the graph.

    Returns ``True`` if the update succeeded, ``False`` otherwise.
    Raises no exceptions -- all failures are logged and return ``False``.
    """
    exe = detect_graphify_cli()
    if exe is None:
        log.debug("graphify CLI not found, skipping graph update")
        return False
    try:
        result = subprocess.run(
            [exe, "update", str(workspace_root)],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            log.warning(
                "graphify update failed (exit %d): %s",
                result.returncode,
                result.stderr[:500],
            )
            return False
        log.info("graphify update completed successfully")
        return True
    except subprocess.TimeoutExpired:
        log.warning("graphify update timed out after %ds", timeout)
        return False
    except OSError as exc:
        log.warning("graphify update failed: %s", exc)
        return False
