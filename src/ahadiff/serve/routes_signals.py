from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from ahadiff.contracts import (
    HelpfulnessRequest,
    MarkWrongRequest,
    QuizAnswerRequest,
    ReviewSignalRequest,
)
from ahadiff.review.database import (
    initialize_review_db,
    insert_learning_signal,
    make_uuid7,
    record_card_review_once,
)
from ahadiff.review.signal import mark_claim_wrong

from .auth import require_write_token, serve_state

if TYPE_CHECKING:
    from starlette.requests import Request


async def mark_wrong(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    body = MarkWrongRequest.model_validate(payload)
    state = serve_state(request)
    assert state.write_lock is not None
    async with state.write_lock:
        initialize_review_db(state.review_db_path)
        inserted = mark_claim_wrong(
            db_path=state.review_db_path,
            claim_id=body.claim_id,
            idempotency_key=body.idempotency_key,
        )
    return JSONResponse({"inserted": inserted})


async def srs_review(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    body = ReviewSignalRequest.model_validate(payload)
    state = serve_state(request)
    assert state.write_lock is not None
    async with state.write_lock:
        initialize_review_db(state.review_db_path)
        update = record_card_review_once(
            state.review_db_path,
            card_id=body.card_id,
            answer=body.answer,
            idempotency_key=body.idempotency_key,
        )
        if update is None:
            return JSONResponse({"inserted": False})
    return JSONResponse({"inserted": True, "review": update.__dict__})


async def quiz_answer(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    body = QuizAnswerRequest.model_validate(payload)
    state = serve_state(request)
    assert state.write_lock is not None
    async with state.write_lock:
        initialize_review_db(state.review_db_path)
        inserted = insert_learning_signal(
            state.review_db_path,
            event_id=make_uuid7(),
            idempotency_key=body.idempotency_key,
            signal_type="quiz_answer",
            payload={
                "quiz_id": body.quiz_id,
                "choice": body.choice,
                "correct": body.correct,
            },
        )
    return JSONResponse({"inserted": inserted})


async def helpfulness(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    body = HelpfulnessRequest.model_validate(payload)
    state = serve_state(request)
    assert state.write_lock is not None
    async with state.write_lock:
        initialize_review_db(state.review_db_path)
        inserted = insert_learning_signal(
            state.review_db_path,
            event_id=make_uuid7(),
            idempotency_key=body.idempotency_key,
            signal_type="helpfulness",
            payload={
                "target_kind": body.target_kind,
                "target_id": body.target_id,
                "payload": json.loads(json.dumps(body.payload)),
            },
        )
    return JSONResponse({"inserted": inserted})


__all__ = ["helpfulness", "mark_wrong", "quiz_answer", "srs_review"]
