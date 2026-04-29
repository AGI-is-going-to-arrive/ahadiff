from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from .auth import serve_state

if TYPE_CHECKING:
    from starlette.requests import Request


async def get_watch_status(request: Request) -> JSONResponse:
    """GET /api/watch/status — internal/unstable watcher status."""
    serve_state(request)
    watcher = getattr(request.app.state, "file_watcher", None)
    if watcher is None:
        return JSONResponse(
            {
                "enabled": False,
                "running": False,
                "last_trigger_time": None,
                "pending_changes": 0,
            }
        )
    snap = watcher.status()
    return JSONResponse(
        {
            "enabled": True,
            "running": snap["running"],
            "last_trigger_time": snap["last_trigger_time"],
            "pending_changes": snap["pending_changes"],
        }
    )


__all__ = ["get_watch_status"]
