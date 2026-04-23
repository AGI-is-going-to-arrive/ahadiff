from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from starlette.responses import JSONResponse

from ahadiff.contracts import LocaleResponse, SetLocaleRequest

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
    return JSONResponse(LocaleResponse(locale=update.lang).model_dump(mode="json"))


def _resolve_request_locale(request: Request) -> Literal["en", "zh-CN"]:
    cookie_locale = _normalize_locale(request.cookies.get("ahadiff_lang"))
    if cookie_locale is not None:
        return cookie_locale
    accepted_locale = _locale_from_accept_language(request.headers.get("accept-language"))
    if accepted_locale is not None:
        return accepted_locale
    return serve_state(request).locale


def _locale_from_accept_language(value: str | None) -> Literal["en", "zh-CN"] | None:
    if not value:
        return None
    for item in value.split(","):
        locale = _normalize_locale(item.split(";", 1)[0].strip())
        if locale is not None:
            return locale
    return None


def _normalize_locale(value: str | None) -> Literal["en", "zh-CN"] | None:
    if value is None:
        return None
    normalized = value.strip().replace("_", "-").casefold()
    if normalized == "en" or normalized.startswith("en-"):
        return "en"
    if normalized in {"zh-cn", "zh-hans"} or normalized.startswith("zh-hans-"):
        return "zh-CN"
    if normalized == "zh" or normalized.startswith("zh-"):
        return "zh-CN"
    return None


__all__ = ["get_locale", "put_locale"]
