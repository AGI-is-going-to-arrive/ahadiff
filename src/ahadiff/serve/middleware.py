from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response

_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}


class LoopbackGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        state = getattr(request.app.state, "ahadiff", None)
        expected_port = _expected_port(state)
        if not _is_allowed_host(request.headers.get("host", ""), expected_port=expected_port):
            return JSONResponse({"error": "host_not_allowed"}, status_code=400)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            if origin is None and referer is None:
                return JSONResponse({"error": "origin_or_referer_required"}, status_code=403)
            if origin is not None and not _is_allowed_origin(origin, expected_port=expected_port):
                return JSONResponse({"error": "origin_not_allowed"}, status_code=403)
            if referer is not None and not _is_allowed_origin(referer, expected_port=expected_port):
                return JSONResponse({"error": "referer_not_allowed"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response


def _is_allowed_host(value: str, *, expected_port: int | None) -> bool:
    if not value:
        return False
    host = value.strip()
    if host.startswith("["):
        end = host.find("]")
        hostname = host[1:end] if end != -1 else host
        port = _parse_port(host[end + 1 :] if end != -1 else "")
    else:
        hostname, port = _split_host_port(host)
    return hostname in _ALLOWED_HOSTS and _port_allowed(port, expected_port=expected_port)


def _is_allowed_origin(value: str, *, expected_port: int | None) -> bool:
    parsed = urlparse(value)
    hostname = parsed.hostname
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and hostname in _ALLOWED_HOSTS
        and _port_allowed(port, expected_port=expected_port)
    )


def _split_host_port(value: str) -> tuple[str, int | None]:
    if ":" not in value:
        return value, None
    hostname, raw_port = value.rsplit(":", 1)
    return hostname, _parse_port(raw_port)


def _parse_port(value: str) -> int | None:
    raw_port = value.removeprefix(":")
    if not raw_port:
        return None
    try:
        return int(raw_port)
    except ValueError:
        return None


def _port_allowed(port: int | None, *, expected_port: int | None) -> bool:
    return expected_port is None or port == expected_port


def _expected_port(state: object) -> int | None:
    port = getattr(state, "port", None)
    return port if isinstance(port, int) else None


__all__ = ["LoopbackGuardMiddleware"]
