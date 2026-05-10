from __future__ import annotations

import hmac
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from ahadiff.contracts import ErrorCode
from ahadiff.core.errors import AhaDiffError, InputError

from .state import ServeState

if TYPE_CHECKING:
    from starlette.requests import Request

WRITE_TOKEN_HEADER = "X-AhaDiff-Token"
_LOOPBACK_BOOTSTRAP_HOSTS = {"localhost", "127.0.0.1", "::1"}


class AuthRequiredError(AhaDiffError):
    """Raised when a protected local write route is missing a valid token."""

    code = ErrorCode.AUTH_REQUIRED


def serve_state(request: Request) -> ServeState:
    state = getattr(request.app.state, "ahadiff", None)
    if not isinstance(state, ServeState):
        raise InputError("serve state is not initialized")
    return state


def require_write_token(request: Request) -> None:
    state = serve_state(request)
    supplied = request.headers.get(WRITE_TOKEN_HEADER)
    if not supplied or not hmac.compare_digest(supplied, state.token):
        raise AuthRequiredError("write route requires a valid X-AhaDiff-Token header")


def require_token_bootstrap_request(request: Request) -> None:
    """Allow token bootstrap only from same-origin browser requests."""
    state = serve_state(request)
    if _has_same_origin_bootstrap_signal(request, expected_port=state.port):
        return
    raise AuthRequiredError("auth token bootstrap requires a same-origin browser request")


def _has_same_origin_bootstrap_signal(request: Request, *, expected_port: int | None) -> bool:
    sec_fetch_site = request.headers.get("sec-fetch-site")
    if sec_fetch_site is not None and sec_fetch_site.strip().lower() == "same-origin":
        return True
    for header_name in ("origin", "referer"):
        value = request.headers.get(header_name)
        if value is not None and _is_loopback_origin(value, expected_port=expected_port):
            return True
    return False


def _is_loopback_origin(value: str, *, expected_port: int | None) -> bool:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in _LOOPBACK_BOOTSTRAP_HOSTS
        and (expected_port is None or port == expected_port)
    )


__all__ = [
    "AuthRequiredError",
    "WRITE_TOKEN_HEADER",
    "require_token_bootstrap_request",
    "require_write_token",
    "serve_state",
]
