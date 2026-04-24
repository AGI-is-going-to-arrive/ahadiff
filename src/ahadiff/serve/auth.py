from __future__ import annotations

import hmac
from typing import TYPE_CHECKING

from ahadiff.core.errors import InputError

from .state import ServeState

if TYPE_CHECKING:
    from starlette.requests import Request

WRITE_TOKEN_HEADER = "X-AhaDiff-Token"


def serve_state(request: Request) -> ServeState:
    state = getattr(request.app.state, "ahadiff", None)
    if not isinstance(state, ServeState):
        raise InputError("serve state is not initialized")
    return state


def require_write_token(request: Request) -> None:
    state = serve_state(request)
    supplied = request.headers.get(WRITE_TOKEN_HEADER)
    if not supplied or not hmac.compare_digest(supplied, state.token):
        raise PermissionError("write route requires a valid X-AhaDiff-Token header")


__all__ = ["WRITE_TOKEN_HEADER", "require_write_token", "serve_state"]
