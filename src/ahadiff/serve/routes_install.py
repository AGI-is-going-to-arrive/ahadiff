"""GET /api/install/targets endpoint."""

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.install.base import InstallContext
from ahadiff.install.registry import available_targets, get_target

if TYPE_CHECKING:
    from starlette.requests import Request

    from .state import ServeState

log = logging.getLogger(__name__)


def _detect_all_targets(state: ServeState) -> list[dict[str, Any]]:
    repo_root = state.state_dir.parent
    try:
        context = InstallContext(repo_root=repo_root)
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for name in available_targets():
        entry: dict[str, Any] = {
            "name": name,
            "detected": False,
            "platform_supported": True,
            "description": "",
        }
        try:
            target = get_target(name)
            entry["detected"] = target.detect(context)
        except NotImplementedError:
            entry["platform_supported"] = False
        except (TimeoutError, subprocess.TimeoutExpired):
            entry["detected"] = False
        except Exception:
            entry["detected"] = False
        results.append(entry)

    return results


async def get_install_targets(request: Request) -> JSONResponse:
    from .auth import serve_state

    state: ServeState = serve_state(request)
    targets = await to_thread.run_sync(_detect_all_targets, state)
    return JSONResponse({"targets": targets})
