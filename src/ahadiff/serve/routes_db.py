"""Database health endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.review.database import CURRENT_SCHEMA_VERSION, check_review_db

from .auth import require_write_token, serve_state
from .lock import serve_repo_write_lock

if TYPE_CHECKING:
    from starlette.requests import Request

    from .state import ServeState


async def post_db_check(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    payload = await to_thread.run_sync(_db_check_sync, state)
    return JSONResponse(payload)


def _db_check_sync(state: ServeState) -> dict[str, Any]:
    with serve_repo_write_lock(state, command="serve db check"):
        check = check_review_db(state.review_db_path, ensure_schema=False)
    healthy = (
        check.schema_version == CURRENT_SCHEMA_VERSION
        and check.quick_check == "ok"
        and check.foreign_key_issues == 0
        and check.event_id_unique
    )
    return {
        "healthy": healthy,
        "schema_version": check.schema_version,
        "quick_check": check.quick_check,
        "event_count": check.event_count,
        "card_count": check.card_count,
    }


__all__ = ["post_db_check"]
