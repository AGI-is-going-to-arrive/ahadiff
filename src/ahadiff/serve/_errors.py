from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse

from ahadiff.contracts import ERROR_STATUS, ErrorCode, ErrorPayload


def error_response(
    code: ErrorCode,
    message: str,
    *,
    status: int | None = None,
    details: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    status_code = status if status is not None else ERROR_STATUS.get(code, 500)
    payload: ErrorPayload = {
        "error_code": code.value,
        "error": message,
        "status": status_code,
    }
    if details is not None:
        payload["details"] = details
    response_payload: dict[str, Any] = dict(payload)
    if extra is not None:
        response_payload.update(extra)
    return JSONResponse(response_payload, status_code=status_code)


__all__ = ["error_response"]
