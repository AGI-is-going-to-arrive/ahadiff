from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from ahadiff.contracts import (
    DueReviewCardResponse,
    ErrorCode,
    ReviewMasteryResponse,
    ReviewQueueStateRequest,
    ReviewQueueStateResponse,
    ReviewRateRequest,
    WeakConceptsResponse,
)
from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.paths import validate_run_id
from ahadiff.review.database import (
    connect_review_db,
    import_cards_from_runs,
    initialize_review_db,
    list_due_cards,
    record_card_review_once,
    set_card_queue_state,
)

from .auth import require_write_token, serve_state
from .config_runtime import configured_desired_retention
from .lock import serve_repo_write_lock
from .routes_quiz import load_presentable_questions
from .routes_runs import finalized_marker_is_valid

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from ahadiff.core.card_sources import CardSourceDetails
    from ahadiff.quiz.schemas import QuizQuestion
    from ahadiff.review.schemas import DueReviewCard, ReviewUpdate

    from .state import ServeState
else:
    Request = Any
    DueReviewCard = Any
    ReviewUpdate = Any
    ServeState = Any


_REVIEW_QUEUE_TARGET_LIMIT = 20
_REVIEW_QUEUE_SCAN_BATCH_SIZE = 50
_REVIEW_QUEUE_MAX_SCAN = 1000


async def get_review_queue(request: Request) -> JSONResponse:
    state = serve_state(request)
    cards = await to_thread.run_sync(_review_queue_sync, state)
    payload = await to_thread.run_sync(_review_queue_projection, state, cards)
    return JSONResponse({"cards": payload})


def _review_queue_projection(
    state: ServeState, cards: tuple[DueReviewCard, ...]
) -> list[dict[str, Any]]:
    """Exercise metadata lives in the immutable quiz artifact, not new DB columns."""
    sources_by_run: dict[str, dict[str, CardSourceDetails] | None] = {}
    by_run: dict[str, dict[str, QuizQuestion]] = {}
    projected: list[dict[str, Any]] = []
    for card in cards:
        if card.run_id not in sources_by_run:
            sources_by_run[card.run_id] = _review_source_cards(state, card.run_id)
        sources = sources_by_run[card.run_id]
        if not _review_source_identity_matches(card, sources):
            continue
        source = sources.get(card.card_id) if sources is not None else None
        if source is None and card.run_id not in by_run:
            try:
                by_run[card.run_id] = {
                    q.review_card_id: q
                    for q in load_presentable_questions(state, card.run_id)
                    if q.review_card_id
                }
            except (InputError, StorageError, OSError, ValueError, HTTPException):
                by_run[card.run_id] = {}
        question = by_run.get(card.run_id, {}).get(card.card_id)
        reference = source if source is not None else question
        if card.card_id.startswith("card_exercise_") and (
            reference is None or reference.exercise_kind is None
        ):
            # This opaque ID survives a lost/corrupt artifact without a DB migration.
            # Never fall back to the DB's reference answer for a new exercise.
            continue
        values = dict(card.__dict__)
        if source is not None:
            values.update(
                question=source.question,
                answer=source.answer,
                answer_mode=source.answer_mode,
                choices=source.choices,
                source_anchors=source.source_anchors,
            )
        elif question is not None:
            values["source_anchors"] = question.source_anchors
        if reference is not None and reference.exercise_kind is not None:
            values.update(
                question_id=reference.question_id,
                exercise_kind=reference.exercise_kind,
                question=reference.question,
                answer=None,
                choices=None,
                answer_mode="open",
                source_anchors=[],
                concept="",
                display_path="",
                symbol=None,
                source_ref=None,
            )
        projected.append(DueReviewCardResponse(**values).model_dump(mode="json"))
    return projected


def _review_source_cards(state: ServeState, run_id: str) -> dict[str, CardSourceDetails] | None:
    from ahadiff.core.card_sources import load_card_sources

    try:
        return load_card_sources(state.state_dir, run_id)
    except (InputError, StorageError, OSError, ValueError, HTTPException):
        # None means a declared source is invalid; an empty mapping is the
        # legacy contract and must remain distinct from validation failure.
        return None


def _review_source_identity_matches(
    card: DueReviewCard, sources: dict[str, CardSourceDetails] | None
) -> bool:
    if sources is None:
        return False
    source = sources.get(card.card_id)
    if source is not None:
        return card.source_ref == source.source_ref
    return not sources and not (card.source_ref or "").startswith("document:")


async def post_review_rate(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    body = ReviewRateRequest.model_validate(payload)
    state = serve_state(request)
    update = await to_thread.run_sync(_review_rate_sync, state, body)
    if update is None:
        return JSONResponse({"inserted": False})
    return JSONResponse({"inserted": True, "review": update.__dict__})


async def post_review_queue_state(request: Request) -> JSONResponse:
    require_write_token(request)
    payload = await request.json()
    body = ReviewQueueStateRequest.model_validate(payload)
    state = serve_state(request)
    await to_thread.run_sync(_review_queue_state_sync, state, body)
    return JSONResponse(
        ReviewQueueStateResponse(
            card_id=body.card_id,
            state=body.state,
        ).model_dump(mode="json")
    )


def _review_rate_sync(state: ServeState, body: ReviewRateRequest) -> ReviewUpdate | None:
    with serve_repo_write_lock(state, command="serve review-rate"):
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


def _review_queue_state_sync(state: ServeState, body: ReviewQueueStateRequest) -> None:
    with serve_repo_write_lock(state, command="serve review-queue-state"):
        initialize_review_db(state.review_db_path)
        set_card_queue_state(
            state.review_db_path,
            card_id=body.card_id,
            state=body.state,
        )


def _review_queue_sync(state: ServeState) -> tuple[DueReviewCard, ...]:
    if not state.review_db_path.exists():
        return ()
    try:
        cards: list[DueReviewCard] = []
        sources_by_run: dict[str, dict[str, CardSourceDetails] | None] = {}
        offset = 0
        while len(cards) < _REVIEW_QUEUE_TARGET_LIMIT and offset < _REVIEW_QUEUE_MAX_SCAN:
            batch_limit = min(_REVIEW_QUEUE_SCAN_BATCH_SIZE, _REVIEW_QUEUE_MAX_SCAN - offset)
            batch = tuple(
                list_due_cards(
                    state.review_db_path,
                    limit=batch_limit,
                    offset=offset,
                )
            )
            if not batch:
                break
            for card in batch:
                if card.run_id not in sources_by_run:
                    sources_by_run[card.run_id] = (
                        None
                        if _run_has_invalid_finalized_marker(state, card.run_id)
                        else _review_source_cards(state, card.run_id)
                    )
                if _review_source_identity_matches(card, sources_by_run[card.run_id]):
                    cards.append(card)
                    if len(cards) >= _REVIEW_QUEUE_TARGET_LIMIT:
                        break
            offset += len(batch)
    except sqlite3.DatabaseError as exc:
        raise StorageError(
            "review database is unavailable",
            code=ErrorCode.STORAGE_REVIEW_DB,
        ) from exc
    return tuple(cards)


def _run_has_invalid_finalized_marker(state: ServeState, run_id: str) -> bool:
    try:
        validate_run_id(run_id)
    except InputError:
        return True

    run_path = state.runs_dir / run_id
    finalized_path = run_path / "finalized.json"
    try:
        marker_exists = finalized_path.exists() or finalized_path.is_symlink()
    except OSError:
        return True
    if not marker_exists:
        return False
    try:
        if run_path.is_symlink() or not run_path.is_dir():
            return True
    except OSError:
        return True
    return not finalized_marker_is_valid(run_path)


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

    def _rows_to_items(rows: list[Any]) -> list[dict[str, Any]]:
        return [
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

    try:
        initialize_review_db(db_path)
        with connect_review_db(db_path) as conn:
            # Truly weak: reviewed at least once but struggling (stability < 30 days)
            weak_rows = conn.execute(
                """
                SELECT id, concept, stability, difficulty, scaffolding_level, display_path
                FROM cards
                WHERE card_state = 'active' AND reps > 0 AND stability < 30.0
                ORDER BY stability ASC, difficulty DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            # New/unreviewed: never reviewed yet
            new_rows = conn.execute(
                """
                SELECT id, concept, stability, difficulty, scaffolding_level, display_path
                FROM cards
                WHERE card_state = 'active' AND reps = 0
                ORDER BY created_at_utc DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise StorageError(
            "review database is unavailable",
            code=ErrorCode.STORAGE_REVIEW_DB,
        ) from exc
    return WeakConceptsResponse.model_validate(
        {
            "concepts": _rows_to_items(weak_rows),
            "new_concepts": _rows_to_items(new_rows),
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
        initialize_review_db(db_path)
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
    except sqlite3.DatabaseError as exc:
        raise StorageError(
            "review database is unavailable",
            code=ErrorCode.STORAGE_REVIEW_DB,
        ) from exc
    return ReviewMasteryResponse.model_validate(
        {
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
    ).model_dump(mode="json")


__all__ = [
    "get_review_mastery",
    "get_review_queue",
    "get_weak_concepts",
    "post_review_queue_state",
    "post_review_rate",
]
