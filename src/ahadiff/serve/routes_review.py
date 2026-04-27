from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts import DueReviewCardResponse, ReviewRateRequest
from ahadiff.review.database import initialize_review_db, list_due_cards, record_card_review_once

from .auth import require_write_token, serve_state
from .lock import serve_repo_write_lock

if TYPE_CHECKING:
    from starlette.requests import Request

    from ahadiff.review.schemas import DueReviewCard, ReviewUpdate

    from .state import ServeState
else:
    Request = Any
    DueReviewCard = Any
    ReviewUpdate = Any
    ServeState = Any


async def get_review_queue(request: Request) -> JSONResponse:
    state = serve_state(request)
    cards = await to_thread.run_sync(_review_queue_sync, state)
    return JSONResponse(
        {
            "cards": [
                DueReviewCardResponse(**card.__dict__).model_dump(mode="json") for card in cards
            ]
        }
    )


async def post_review_rate(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    body = ReviewRateRequest.model_validate(payload)
    state = serve_state(request)
    update = await to_thread.run_sync(_review_rate_sync, state, body)
    if update is None:
        # TODO(v0.2): record_card_review_once stores card_id/answer in learning_signals,
        # but duplicate keys are still treated as replay without comparing that payload.
        return JSONResponse({"inserted": False})
    return JSONResponse({"inserted": True, "review": update.__dict__})


def _review_rate_sync(state: ServeState, body: ReviewRateRequest) -> ReviewUpdate | None:
    with serve_repo_write_lock(state, command="serve review-rate"):
        initialize_review_db(state.review_db_path)
        return record_card_review_once(
            state.review_db_path,
            card_id=body.card_id,
            answer=body.answer,
            idempotency_key=body.idempotency_key,
        )


def _review_queue_sync(state: ServeState) -> tuple[DueReviewCard, ...]:
    if not state.review_db_path.exists():
        return ()
    return tuple(list_due_cards(state.review_db_path))


__all__ = ["get_review_queue", "post_review_rate"]
