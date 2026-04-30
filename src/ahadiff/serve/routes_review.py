from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts import DueReviewCardResponse, ReviewRateRequest, WeakConceptsResponse
from ahadiff.review.database import (
    connect_review_db,
    initialize_review_db,
    list_due_cards,
    record_card_review_once,
)

from .auth import require_write_token, serve_state
from .lock import serve_repo_write_lock

if TYPE_CHECKING:
    from pathlib import Path

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
            peeked_this_session=body.peeked_this_session,
        )


def _review_queue_sync(state: ServeState) -> tuple[DueReviewCard, ...]:
    if not state.review_db_path.exists():
        return ()
    return tuple(list_due_cards(state.review_db_path))


_MAX_WEAK_CONCEPTS = 100
_MAX_MASTERY = 200


async def get_weak_concepts(request: Request) -> JSONResponse:
    require_write_token(request)
    state: ServeState = serve_state(request)
    raw_limit = request.query_params.get("limit", "20")
    try:
        limit = min(max(int(raw_limit), 1), _MAX_WEAK_CONCEPTS)
    except (ValueError, TypeError):
        limit = 20
    payload = await to_thread.run_sync(lambda: _weak_concepts_sync(state.review_db_path, limit))
    return JSONResponse(payload)


def _weak_concepts_sync(db_path: Path, limit: int) -> dict[str, Any]:
    if not db_path.is_file():
        return WeakConceptsResponse(concepts=[]).model_dump(mode="json")
    try:
        with connect_review_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, concept, stability, difficulty, scaffolding_level, display_path
                FROM cards
                WHERE card_state = 'active'
                ORDER BY stability ASC, difficulty DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.OperationalError:
        return WeakConceptsResponse(concepts=[]).model_dump(mode="json")
    return WeakConceptsResponse.model_validate(
        {
            "concepts": [
                {
                    "card_id": str(row[0]),
                    "concept": str(row[1]),
                    "stability": float(row[2]) if row[2] is not None else 0.0,
                    "difficulty": float(row[3]) if row[3] is not None else 0.0,
                    "scaffolding_level": str(row[4]) if row[4] is not None else "",
                    "display_path": str(row[5]) if row[5] is not None else "",
                }
                for row in rows
            ]
        }
    ).model_dump(mode="json")


async def get_review_mastery(request: Request) -> JSONResponse:
    require_write_token(request)
    state: ServeState = serve_state(request)
    raw_limit = request.query_params.get("limit", "50")
    try:
        limit = min(max(int(raw_limit), 1), _MAX_MASTERY)
    except (ValueError, TypeError):
        limit = 50
    payload = await to_thread.run_sync(lambda: _mastery_sync(state.review_db_path, limit))
    return JSONResponse(payload)


def _mastery_sync(db_path: Path, limit: int) -> dict[str, Any]:
    if not db_path.is_file():
        return {"mastery": []}
    try:
        with connect_review_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT c.concept,
                       COUNT(*) AS review_count,
                       AVG(rl.rating) AS avg_rating,
                       MAX(rl.reviewed_at_utc) AS last_review
                FROM cards c
                JOIN review_logs rl ON c.id = rl.card_id
                WHERE c.card_state = 'active'
                GROUP BY c.concept
                ORDER BY avg_rating ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.OperationalError:
        return {"mastery": []}
    return {
        "mastery": [
            {
                "concept": str(row[0]),
                "review_count": int(row[1]),
                "avg_rating": float(row[2]) if row[2] is not None else None,
                "last_review": str(row[3]) if row[3] is not None else None,
            }
            for row in rows
        ]
    }


__all__ = ["get_review_mastery", "get_review_queue", "get_weak_concepts", "post_review_rate"]
