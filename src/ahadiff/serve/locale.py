from __future__ import annotations

from typing import TYPE_CHECKING

from ahadiff.i18n import Locale, resolve_locale

from .auth import serve_state

if TYPE_CHECKING:
    from starlette.requests import Request


def request_locale(request: Request) -> Locale:
    state = serve_state(request)
    return resolve_locale(
        cookie_lang=request.cookies.get("ahadiff_lang"),
        accept_language=request.headers.get("accept-language"),
        cli_lang=state.cli_lang,
        config_lang=state.config_lang or state.locale,
    )


__all__ = ["request_locale"]
