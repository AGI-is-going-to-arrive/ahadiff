from __future__ import annotations

import asyncio
import time
from collections import deque
from contextlib import suppress
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from ahadiff.contracts import ErrorCode

from ._errors import error_response

if TYPE_CHECKING:
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.requests import Request

_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}
_MAX_BODY_BYTES = 1_048_576  # 1 MiB
_WRITE_GUARD_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_JSON_BODY_METHODS = {"POST", "PUT", "PATCH"}
_CORS_ALLOWED_METHODS = {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}
_CORS_ALLOW_METHODS = "GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE"
_CORS_ALLOWED_REQUEST_HEADERS = {"content-type", "x-ahadiff-token"}
_CORS_ALLOW_HEADERS = "Content-Type, X-AhaDiff-Token"
_CORS_MAX_AGE_SECONDS = "600"
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'sha256-34OjdQcdg9PbE7u8eV4uQikDSGeuXXSEvz634GZp/gc='; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'; "
    "object-src 'none'"
)
_PROXY_TRACE_HEADERS = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-proto",
        "x-real-ip",
    }
)


class LoopbackGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        state = getattr(request.app.state, "ahadiff", None)
        expected_port = _expected_port(state)
        if _has_proxy_trace_headers(request):
            return _error_response(ErrorCode.INPUT_BAD_FIELD, "proxy_headers_not_allowed")
        if not _is_allowed_host(request.headers.get("host", ""), expected_port=expected_port):
            return _error_response(ErrorCode.INPUT_BAD_FIELD, "host_not_allowed")
        origin = request.headers.get("origin")
        cors_origin = (
            origin
            if origin is not None and _is_allowed_origin(origin, expected_port=expected_port)
            else None
        )
        if _is_cors_preflight(request):
            if origin is not None and not _is_allowed_preflight_origin(
                origin,
                expected_port=expected_port,
            ):
                return _error_response(ErrorCode.LOOPBACK_DENIED, "origin_not_allowed")
            if not _is_allowed_preflight_method(
                request.headers.get("access-control-request-method")
            ):
                return _error_response(
                    ErrorCode.INPUT_BAD_FIELD,
                    "method_not_allowed",
                    status_code=405,
                )
            if not _are_allowed_preflight_headers(
                request.headers.get("access-control-request-headers")
            ):
                return _error_response(ErrorCode.INPUT_BAD_FIELD, "headers_not_allowed")
            assert origin is not None
            return _preflight_response(origin)
        if request.method in _WRITE_GUARD_METHODS:
            referer = request.headers.get("referer")
            if origin is None and referer is None:
                return _error_response(ErrorCode.LOOPBACK_DENIED, "origin_or_referer_required")
            if origin is not None and not _is_allowed_origin(origin, expected_port=expected_port):
                return _error_response(ErrorCode.LOOPBACK_DENIED, "origin_not_allowed")
            if referer is not None and not _is_allowed_origin(referer, expected_port=expected_port):
                return _error_response(ErrorCode.LOOPBACK_DENIED, "referer_not_allowed")
        if request.method in _JSON_BODY_METHODS:
            has_body = _declares_request_body(request)
            if has_body and not _is_json_content_type(request.headers.get("content-type", "")):
                return _error_response(
                    ErrorCode.INPUT_BAD_FIELD,
                    "unsupported_media_type",
                    status_code=415,
                    cors_origin=cors_origin,
                )
            content_length = request.headers.get("content-length")
            if (
                content_length is not None
                and content_length.isdigit()
                and int(content_length) > _MAX_BODY_BYTES
            ):
                return _error_response(
                    ErrorCode.RUN_ARTIFACT_TOO_LARGE,
                    "payload_too_large",
                    cors_origin=cors_origin,
                )
            if has_body and not await _cache_limited_body(request):
                return _error_response(
                    ErrorCode.RUN_ARTIFACT_TOO_LARGE,
                    "payload_too_large",
                    cors_origin=cors_origin,
                )
        response = await call_next(request)
        if cors_origin is not None:
            _apply_cors_headers(response, cors_origin)
        return _apply_security_headers(response)


def _error_response(
    code: ErrorCode,
    error: str,
    *,
    status_code: int | None = None,
    cors_origin: str | None = None,
) -> Response:
    response = error_response(code, error, status=status_code)
    if cors_origin is not None:
        _apply_cors_headers(response, cors_origin)
    return _apply_security_headers(response)


def _preflight_response(origin: str) -> Response:
    response = Response(status_code=204)
    _apply_cors_headers(response, origin)
    response.headers["Access-Control-Allow-Methods"] = _CORS_ALLOW_METHODS
    response.headers["Access-Control-Allow-Headers"] = _CORS_ALLOW_HEADERS
    response.headers["Access-Control-Max-Age"] = _CORS_MAX_AGE_SECONDS
    return _apply_security_headers(response)


def _apply_security_headers(response: Response) -> Response:
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


def _apply_cors_headers(response: Response, origin: str) -> None:
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    _add_vary_origin(response)


def _add_vary_origin(response: Response) -> None:
    existing = response.headers.get("Vary")
    if existing is None:
        response.headers["Vary"] = "Origin"
        return
    values = {value.strip().lower() for value in existing.split(",")}
    if "origin" not in values:
        response.headers["Vary"] = f"{existing}, Origin"


async def _cache_limited_body(request: Request) -> bool:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_BODY_BYTES:
            return False
        chunks.append(chunk)
    request._body = b"".join(chunks)  # pyright: ignore[reportPrivateUsage]
    return True


def _has_proxy_trace_headers(request: Request) -> bool:
    return any(request.headers.get(header) is not None for header in _PROXY_TRACE_HEADERS)


def _is_json_content_type(value: str) -> bool:
    media_type = value.split(";", 1)[0].strip().lower()
    return media_type == "application/json"


def _declares_request_body(request: Request) -> bool:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            return int(content_length) > 0
        except ValueError:
            return True
    return "transfer-encoding" in request.headers


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


def _is_cors_preflight(request: Request) -> bool:
    return (
        request.method == "OPTIONS"
        and request.headers.get("origin") is not None
        and request.headers.get("access-control-request-method") is not None
    )


def _is_allowed_preflight_method(value: str | None) -> bool:
    return value is not None and value.strip().upper() in _CORS_ALLOWED_METHODS


def _are_allowed_preflight_headers(value: str | None) -> bool:
    if value is None or not value.strip():
        return True
    headers = [header.strip().lower() for header in value.split(",")]
    return all(header and header in _CORS_ALLOWED_REQUEST_HEADERS for header in headers)


def _is_allowed_origin(value: str, *, expected_port: int | None) -> bool:
    parsed = _parse_origin(value)
    if parsed is None:
        return False
    hostname = parsed.hostname
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and hostname in _ALLOWED_HOSTS
        and _port_allowed(port, expected_port=expected_port)
    )


def _is_allowed_preflight_origin(value: str, *, expected_port: int | None) -> bool:
    parsed = _parse_origin(value)
    if parsed is None:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if port is None:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in _ALLOWED_HOSTS
        and _port_allowed(port, expected_port=expected_port)
    )


def _parse_origin(value: str):
    try:
        return urlparse(value)
    except ValueError:
        return None


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


_RATE_LIMIT_WINDOW_SECONDS = 60.0
_RATE_LIMITS: dict[str, int] = {
    "/api/learn": 10,
}


class WriteRateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding-window rate limiter for expensive write endpoints.

    Only limits paths explicitly listed in ``_RATE_LIMITS``.  Local-first
    design: no per-IP tracking (loopback only).
    """

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._windows: dict[str, deque[tuple[float, int]]] = {}
        self._next_ticket = 0

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in _WRITE_GUARD_METHODS:
            return await call_next(request)
        match = _rate_limit_for_path(request.url.path)
        if match is None:
            return await call_next(request)
        limit, key = match
        now = time.monotonic()
        window = self._windows.setdefault(key, deque())
        cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
        while window and window[0][0] <= cutoff:
            window.popleft()
        if len(window) >= limit:
            remaining = window[0][0] + _RATE_LIMIT_WINDOW_SECONDS - now
            retry_after = max(1, int(remaining + 0.999))
            return _rate_limit_response(retry_after)
        self._next_ticket += 1
        entry = (now, self._next_ticket)
        window.append(entry)
        response = await call_next(request)
        if response.status_code in {401, 403, 404}:
            with suppress(ValueError):
                window.remove(entry)
        return response


def _rate_limit_for_path(path: str) -> tuple[int, str] | None:
    limit = _RATE_LIMITS.get(path)
    if limit is not None:
        return limit, path
    return None


def _rate_limit_response(retry_after: int) -> Response:
    resp = error_response(
        ErrorCode.RATE_LIMITED,
        "rate_limited",
        extra={"retry_after": retry_after},
    )
    resp.headers["Retry-After"] = str(retry_after)
    return _apply_security_headers(resp)


_DEFAULT_REQUEST_TIMEOUT = 30.0
_LONG_REQUEST_TIMEOUT = 600.0
_LONG_TIMEOUT_EXACT_PATHS = frozenset({"/api/graph/refresh"})
_LONG_TIMEOUT_PREFIXES = ("/api/learn", "/api/tasks/")


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Abort requests that exceed a wall-clock deadline.

    Default: 30 s for most endpoints, 600 s for learn/task requests and the
    explicit graph refresh route.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        timeout = _request_timeout_for(request.url.path)
        try:
            async with asyncio.timeout(timeout):
                return await call_next(request)
        except TimeoutError:
            return _error_response(
                ErrorCode.REQUEST_TIMEOUT,
                "request_timeout",
                status_code=504,
            )


def _request_timeout_for(path: str) -> float:
    if path in _LONG_TIMEOUT_EXACT_PATHS:
        return _LONG_REQUEST_TIMEOUT
    for prefix in _LONG_TIMEOUT_PREFIXES:
        if path.startswith(prefix):
            return _LONG_REQUEST_TIMEOUT
    return _DEFAULT_REQUEST_TIMEOUT


__all__ = ["LoopbackGuardMiddleware", "RequestTimeoutMiddleware", "WriteRateLimitMiddleware"]
