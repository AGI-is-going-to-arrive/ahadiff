from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from ahadiff.contracts import LocaleResponse, SetLocaleRequest
from ahadiff.i18n import Locale, resolve_locale

from .auth import require_write_token, serve_state

if TYPE_CHECKING:
    from starlette.requests import Request


async def get_locale(request: Request) -> JSONResponse:
    response = LocaleResponse(locale=_resolve_request_locale(request))
    return JSONResponse(response.model_dump(mode="json"))


async def put_locale(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    update = SetLocaleRequest.model_validate(payload)
    current = serve_state(request)
    assert current.write_lock is not None
    async with current.write_lock:
        request.app.state.ahadiff = current.__class__(
            state_dir=current.state_dir,
            token=current.token,
            locale=update.lang,
            bind_host=current.bind_host,
            port=current.port,
            write_lock=current.write_lock,
        )
    response = JSONResponse(LocaleResponse(locale=update.lang).model_dump(mode="json"))
    response.set_cookie(
        "ahadiff_lang",
        update.lang,
        httponly=False,
        samesite="lax",
    )
    return response


def _resolve_request_locale(request: Request) -> Locale:
    return resolve_locale(
        cookie_lang=request.cookies.get("ahadiff_lang"),
        accept_language=request.headers.get("accept-language"),
        config_lang=serve_state(request).locale,
    )


__all__ = ["get_locale", "put_locale"]
