from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts import LocaleResponse, SetLocaleRequest

from .auth import require_write_token, serve_state
from .locale import request_locale
from .lock import serve_repo_write_lock

if TYPE_CHECKING:
    from starlette.requests import Request

    from ahadiff.i18n import Locale

    from .state import ServeState


async def get_locale(request: Request) -> JSONResponse:
    response = LocaleResponse(locale=request_locale(request))
    return JSONResponse(response.model_dump(mode="json"))


async def put_locale(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    update = SetLocaleRequest.model_validate(payload)
    current = serve_state(request)
    await to_thread.run_sync(
        _persist_lang_and_update_state_with_lock,
        request.app.state,
        current,
        update.lang,
    )
    response = JSONResponse(LocaleResponse(locale=update.lang).model_dump(mode="json"))
    response.set_cookie(
        "ahadiff_lang",
        update.lang,
        httponly=False,
        samesite="lax",
    )
    return response


def _persist_lang(state: ServeState, lang: Locale) -> None:
    from ahadiff.core.config import read_config_data, write_config_data

    config_path = state.state_dir.parent / ".ahadiff" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = read_config_data(config_path) if config_path.exists() else {}
    data["lang"] = lang
    write_config_data(config_path, data)


def _persist_lang_and_update_state_with_lock(
    app_state: Any,
    state: ServeState,
    lang: Locale,
) -> None:
    with serve_repo_write_lock(state, command="serve locale update"):
        _persist_lang(state, lang)
        app_state.ahadiff = state.with_locale(lang)


__all__ = ["get_locale", "put_locale"]
