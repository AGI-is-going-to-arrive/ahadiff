from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.types import Scope


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def mount_viewer_static(app: Starlette, *, viewer_dist: Path | None) -> None:
    if viewer_dist is None or not viewer_dist.is_dir():
        return
    app.mount("/", SpaStaticFiles(directory=viewer_dist, html=True), name="viewer")


__all__ = ["SpaStaticFiles", "mount_viewer_static"]
