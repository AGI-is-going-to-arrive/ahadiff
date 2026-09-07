from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

if TYPE_CHECKING:
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.types import Scope


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        # Reject Windows UNC/device/drive paths before StaticFiles resolves them.
        # Containment checks after realpath are too late for SMB/NTLM side effects
        # (GHSA-wqp7-x3pw-xc5r). This is a pure lexical check on every platform.
        requested_path = PurePosixPath(path.replace("\\", "/"))
        if (
            requested_path.is_absolute()
            or PureWindowsPath(path).drive
            or ".." in requested_path.parts
            or any(character in path for character in ':<>"|?*')
            or any(ord(character) < 32 for character in path)
            or any(_is_windows_device_name(part) for part in requested_path.parts)
        ):
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def _is_windows_device_name(part: str) -> bool:
    stem = part.rstrip(" .").split(".", 1)[0].rstrip(" ").upper()
    return stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"} or (
        stem.startswith(("COM", "LPT")) and len(stem) == 4 and stem[-1] in "0123456789¹²³"
    )


def _resolve_viewer_dist() -> Path | None:
    env_viewer_dist = os.environ.get("AHADIFF_VIEWER_DIST")
    if env_viewer_dist:
        candidate = _resolve_env_viewer_dist(env_viewer_dist)
        if _is_valid_viewer_dist(candidate):
            return candidate

    try:
        package_webui = files("ahadiff").joinpath("_webui")
        candidate = Path(str(package_webui))
        if _is_valid_viewer_dist(candidate):
            return candidate
    except (FileNotFoundError, ModuleNotFoundError, OSError, TypeError, NotADirectoryError):
        pass

    dev_viewer_dist = _module_source_checkout_viewer_dist()
    if dev_viewer_dist is None:
        return None
    if _is_valid_viewer_dist(dev_viewer_dist):
        return dev_viewer_dist
    return None


def _resolve_env_viewer_dist(value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        return candidate
    try:
        return candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return candidate


def _is_valid_viewer_dist(candidate: Path) -> bool:
    try:
        return (
            candidate.is_absolute() and candidate.is_dir() and (candidate / "index.html").is_file()
        )
    except (OSError, ValueError):
        return False


def _module_source_checkout_viewer_dist() -> Path | None:
    module_path = Path(__file__).resolve()
    parents = module_path.parents
    if len(parents) < 4:
        return None
    if parents[0].name != "serve" or parents[1].name != "ahadiff" or parents[2].name != "src":
        return None
    return parents[3] / "viewer" / "dist"


def mount_viewer_static(app: Starlette, *, viewer_dist: Path | None) -> None:
    """Mount the SPA after API routes so browser paths can fall back to index.html."""
    if viewer_dist is None or not viewer_dist.is_dir():
        return
    app.mount("/", SpaStaticFiles(directory=viewer_dist, html=True), name="viewer")


__all__ = ["SpaStaticFiles", "_resolve_viewer_dist", "mount_viewer_static"]
