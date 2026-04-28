from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts import (
    HelpfulnessRequest,
    MarkWrongRequest,
    QuizAnswerRequest,
    ReviewSignalRequest,
)
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.review.database import (
    initialize_review_db,
    insert_learning_signal,
    make_uuid7,
    record_card_review_once,
)
from ahadiff.review.signal import mark_claim_wrong

from .auth import require_write_token, serve_state
from .lock import serve_repo_write_lock

if TYPE_CHECKING:
    from starlette.requests import Request

    from ahadiff.review.schemas import ReviewUpdate

    from .state import ServeState


async def mark_wrong(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    body = MarkWrongRequest.model_validate(payload)
    state = serve_state(request)
    inserted = await to_thread.run_sync(_mark_wrong_sync, state, body)
    return JSONResponse({"inserted": inserted})


async def srs_review(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    body = ReviewSignalRequest.model_validate(payload)
    state = serve_state(request)
    update = await to_thread.run_sync(_srs_review_sync, state, body)
    if update is None:
        return JSONResponse({"inserted": False})
    return JSONResponse({"inserted": True, "review": update.__dict__})


async def quiz_answer(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    body = QuizAnswerRequest.model_validate(payload)
    state = serve_state(request)
    inserted = await to_thread.run_sync(_quiz_answer_sync, state, body)
    return JSONResponse({"inserted": inserted})


async def helpfulness(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    body = HelpfulnessRequest.model_validate(payload)
    state = serve_state(request)
    inserted = await to_thread.run_sync(_helpfulness_sync, state, body)
    return JSONResponse({"inserted": inserted})


def _mark_wrong_sync(state: ServeState, body: MarkWrongRequest) -> bool:
    with serve_repo_write_lock(state, command="serve mark-wrong"):
        initialize_review_db(state.review_db_path)
        return mark_claim_wrong(
            db_path=state.review_db_path,
            claim_id=body.claim_id,
            idempotency_key=body.idempotency_key,
        )


def _srs_review_sync(state: ServeState, body: ReviewSignalRequest) -> ReviewUpdate | None:
    with serve_repo_write_lock(state, command="serve srs-review"):
        initialize_review_db(state.review_db_path)
        return record_card_review_once(
            state.review_db_path,
            card_id=body.card_id,
            answer=body.answer,
            idempotency_key=body.idempotency_key,
            peeked_this_session=body.peeked_this_session,
        )


def _quiz_answer_sync(state: ServeState, body: QuizAnswerRequest) -> bool:
    with serve_repo_write_lock(state, command="serve quiz-answer"):
        initialize_review_db(state.review_db_path)
        return insert_learning_signal(
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


def _helpfulness_sync(state: ServeState, body: HelpfulnessRequest) -> bool:
    with serve_repo_write_lock(state, command="serve helpfulness"):
        initialize_review_db(state.review_db_path)
        return insert_learning_signal(
            state.review_db_path,
            event_id=make_uuid7(),
            idempotency_key=body.idempotency_key,
            signal_type="helpfulness",
            payload={
                "target_kind": body.target_kind,
                "target_id": body.target_id,
                "payload": _normalized_payload(body.payload),
            },
        )


def _normalized_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise InputError(
            "helpfulness payload must be JSON-serializable and use finite numbers"
        ) from exc
    normalized = safe_json_loads(encoded)
    if not isinstance(normalized, dict):
        raise InputError("helpfulness payload must be a JSON object")
    return cast("dict[str, Any]", normalized)


__all__ = ["helpfulness", "mark_wrong", "quiz_answer", "srs_review"]
