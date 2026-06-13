"""Optional Graphify CLI detection and invocation."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, Any

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
    command = [exe, "update", str(workspace_root)]
    try:
        with subprocess.Popen(
            command,
            cwd=str(workspace_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_detached_subprocess_kwargs(),
        ) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _terminate_graphify_process(process, force=True)
                with suppress(subprocess.TimeoutExpired):
                    process.communicate(timeout=5)
                log.warning("graphify update timed out after %ds", timeout)
                return False
        if process.returncode != 0:
            log.warning(
                "graphify update failed (exit %d): %s",
                process.returncode,
                (stderr or stdout or "")[:500],
            )
            return False
        log.info("graphify update completed successfully")
        return True
    except OSError as exc:
        log.warning("graphify update failed: %s", exc)
        return False


def _detached_subprocess_kwargs() -> dict[str, Any]:
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": creationflags}
    return {"start_new_session": True}


def _terminate_graphify_process(process: subprocess.Popen[str], *, force: bool) -> None:
    if process.poll() is not None:
        return
    if sys.platform.startswith("win"):
        with suppress(OSError):
            if force:
                process.kill()
            else:
                process.terminate()
        return

    signum = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        return
    except OSError:
        with suppress(OSError):
            if force:
                process.kill()
            else:
                process.terminate()
