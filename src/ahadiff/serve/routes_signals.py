from __future__ import annotations

import json
from datetime import UTC, datetime
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
    connect_review_db,
    import_cards_from_runs,
    initialize_review_db,
    insert_learning_signal,
    make_uuid7,
    record_card_review_once,
)
from ahadiff.review.signal import mark_claim_wrong

from .auth import require_write_token, serve_state
from .config_runtime import configured_desired_retention
from .lock import serve_repo_write_lock
from .routes_quiz import load_presentable_questions

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from ahadiff.quiz.schemas import QuizQuestion
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
        dr = configured_desired_retention(state)
        try:
            return record_card_review_once(
                state.review_db_path,
                card_id=body.card_id,
                answer=body.answer,
                idempotency_key=body.idempotency_key,
                peeked_this_session=body.peeked_this_session,
                selected_choice_label=body.selected_choice_label,
                desired_retention=dr,
            )
        except InputError as exc:
            if "active review card does not exist" not in str(exc):
                raise
        import_cards_from_runs(
            state.review_db_path,
            state.state_dir,
            desired_retention=dr,
            on_error=lambda _p, _e: None,
        )
        return record_card_review_once(
            state.review_db_path,
            card_id=body.card_id,
            answer=body.answer,
            idempotency_key=body.idempotency_key,
            peeked_this_session=body.peeked_this_session,
            selected_choice_label=body.selected_choice_label,
            desired_retention=dr,
        )


def _quiz_answer_sync(state: ServeState, body: QuizAnswerRequest) -> bool:
    with serve_repo_write_lock(state, command="serve quiz-answer"):
        initialize_review_db(state.review_db_path)
        question = None
        if body.run_id is not None:
            question = next(
                (
                    q
                    for q in load_presentable_questions(state, body.run_id)
                    if q.question_id == body.quiz_id
                ),
                None,
            )
            if question is None:
                raise InputError("quiz question does not exist")
        return record_quiz_attempt(state.review_db_path, body, question)


def quiz_signal_payload(
    body: QuizAnswerRequest, question: QuizQuestion | None = None
) -> dict[str, object]:
    """Validate identity/feedback and keep active exercise answers out of storage."""
    if body.quiz_id.startswith("quiz_exercise_") and (
        body.run_id is None or body.exercise_kind is None
    ):
        raise InputError("active exercise signals require run and exercise metadata")
    if question is not None and question.question_id != body.quiz_id:
        raise InputError("quiz identity does not match")
    if body.exercise_kind is not None or (question is not None and question.exercise_kind):
        if question is None or question.exercise_kind != body.exercise_kind:
            raise InputError("exercise kind does not match the quiz artifact")
        if body.feedback_kind != "semantic_self_assessment" or body.correct is not None:
            raise InputError("active exercises require semantic self-assessment")
        if body.self_assessment is None or body.error_type is None:
            raise InputError("active exercises require an assessment and error type")
        if (body.self_assessment == "independent") != (body.error_type == "none"):
            raise InputError("assessment and error type do not agree")
        if body.selected_choice_label is not None:
            raise InputError("active exercises do not accept choices")
        practice_payload: dict[str, object] = {
            "quiz_id": body.quiz_id,
            "run_id": body.run_id,
            "correct": None,
            "exercise_kind": question.exercise_kind,
            "feedback_kind": "semantic_self_assessment",
            "self_assessment": body.self_assessment,
            "error_type": body.error_type,
        }
        if question.scenario_kind is not None:
            practice_payload["scenario_kind"] = question.scenario_kind
        return practice_payload
    if body.self_assessment is not None or body.error_type is not None:
        raise InputError("semantic assessment requires a supported active exercise")
    payload: dict[str, object] = {
        "quiz_id": body.quiz_id,
        "choice": body.choice,
        "correct": body.correct,
    }
    if body.selected_choice_label is not None:
        payload["selected_choice_label"] = body.selected_choice_label
    if question is not None:
        payload["run_id"] = body.run_id
        if question.answer_mode == "multiple_choice":
            selected = next(
                (c for c in question.choices or () if c.label == body.selected_choice_label), None
            )
            if selected is None:
                raise InputError("select a valid quiz choice")
            payload.update(
                choice=selected.label, correct=selected.is_correct, feedback_kind="choice_check"
            )
        else:
            # Text comparison is local feedback, never an executed or semantic proof.
            payload.update(choice="", correct=None, feedback_kind="reference_comparison")
    elif body.feedback_kind is not None or body.attempt_kind is not None:
        raise InputError("feedback metadata requires a quiz artifact")
    return payload


def record_quiz_attempt(
    db_path: Path, body: QuizAnswerRequest, question: QuizQuestion | None = None
) -> bool:
    """Called inside the existing repo write lock; CLI uses the same signal contract."""
    payload = quiz_signal_payload(body, question)
    if question is not None and question.exercise_kind is not None:
        with connect_review_db(db_path) as connection:
            existing = connection.execute(
                "SELECT signal_type, payload_json FROM learning_signals WHERE idempotency_key = ?",
                (body.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["signal_type"]) != "quiz_answer":
                    raise InputError("idempotency key already used by another learning signal")
                saved = safe_json_loads(str(existing["payload_json"]))
                if not isinstance(saved, dict):
                    raise InputError("invalid existing learning signal")
                saved_payload = cast("dict[str, object]", saved)
                comparable = {
                    k: v
                    for k, v in saved_payload.items()
                    if k not in {"attempt_kind", "elapsed_seconds"}
                }
                if comparable != payload:
                    raise InputError(
                        "idempotency key already used with different learning signal payload"
                    )
                return False
            previous = connection.execute(
                """SELECT created_at FROM learning_signals
                   WHERE signal_type = 'quiz_answer'
                     AND CASE WHEN json_valid(payload_json)
                         THEN json_extract(payload_json, '$.quiz_id') END = ?
                     AND CASE WHEN json_valid(payload_json)
                         THEN json_extract(payload_json, '$.run_id') END = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (body.quiz_id, body.run_id),
            ).fetchone()
        payload["attempt_kind"] = (
            "unseen_variant" if question.scenario_kind == "new_variant" else "initial"
        )
        if previous is not None:
            try:
                earlier = datetime.fromisoformat(str(previous["created_at"]).replace("Z", "+00:00"))
                elapsed = max(0, int((datetime.now(UTC) - earlier).total_seconds()))
            except (ValueError, TypeError, OverflowError):
                elapsed = 0
            payload["elapsed_seconds"] = elapsed
            payload["attempt_kind"] = "delayed_recall" if elapsed >= 86_400 else "initial"
    return insert_learning_signal(
        db_path,
        event_id=make_uuid7(),
        idempotency_key=body.idempotency_key,
        signal_type="quiz_answer",
        payload=payload,
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
