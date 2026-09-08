"""Answer-separated quiz presentation; original artifacts remain explicit exports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from anyio import to_thread
from pydantic import BaseModel, ConfigDict, StrictBool, field_validator
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.quiz.schemas import QuizQuestion

from .auth import require_write_token, serve_state
from .routes_runs import _artifact_payload  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from starlette.requests import Request

    from .state import ServeState


class QuizRevealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    attempted: StrictBool
    selected_choice_label: Literal["A", "B", "C", "D"] | None = None

    @field_validator("attempted")
    @classmethod
    def require_attempt(cls, value: bool) -> bool:
        if not value:
            raise ValueError("attempt the question before revealing the answer")
        return value


def load_presentable_questions(state: ServeState, run_id: str) -> tuple[QuizQuestion, ...]:
    """Read only finalized, bounded artifacts through the existing file guard."""
    payload = _artifact_payload(state, run_id, "quiz/quiz.jsonl", "quiz", not_found_status_code=404)
    if payload.get("_status_code") == 404:
        raise HTTPException(status_code=404, detail="quiz artifact is unavailable")
    questions: list[QuizQuestion] = []
    seen: set[str] = set()
    try:
        for line in str(payload["content"]).splitlines():
            if not line.strip():
                continue
            question = QuizQuestion.model_validate(safe_json_loads(line))
            if not question.question_id or question.question_id in seen:
                raise ValueError("missing or duplicate question identity")
            seen.add(question.question_id)
            questions.append(question)
            if len(questions) > 30:
                raise ValueError("too many questions")
    except (ValueError, TypeError) as exc:
        # Never reflect invalid artifact text (which may contain source data).
        raise InputError("quiz artifact cannot be presented safely") from exc
    return tuple(questions)


def public_question(question: QuizQuestion) -> dict[str, Any]:
    """An allowlist prevents new answer-bearing fields leaking by default."""
    return {
        "question_id": question.question_id,
        "review_card_id": question.review_card_id,
        "question": question.question,
        "quiz_kind": question.quiz_kind,
        "exercise_kind": question.exercise_kind,
        "scenario_kind": question.scenario_kind,
        "answer_mode": question.answer_mode,
        "choices": (
            [{"label": choice.label, "text": choice.text} for choice in question.choices]
            if question.choices
            else None
        ),
    }


async def get_quiz_questions(request: Request) -> JSONResponse:
    state = serve_state(request)
    run_id = str(request.path_params["run_id"])
    questions = await to_thread.run_sync(load_presentable_questions, state, run_id)
    return JSONResponse({"run_id": run_id, "questions": [public_question(q) for q in questions]})


async def reveal_quiz_question(request: Request) -> JSONResponse:
    require_write_token(request)
    body = QuizRevealRequest.model_validate(await request.json())
    state = serve_state(request)
    run_id = str(request.path_params["run_id"])
    question_id = str(request.path_params["question_id"])
    questions = await to_thread.run_sync(load_presentable_questions, state, run_id)
    question = next((q for q in questions if q.question_id == question_id), None)
    if question is None:
        raise InputError("quiz question does not exist")
    correct: bool | None = None
    if question.answer_mode == "multiple_choice":
        selected = next(
            (c for c in question.choices or () if c.label == body.selected_choice_label), None
        )
        if selected is None:
            raise InputError("select a valid choice before revealing the answer")
        correct = selected.is_correct
    elif body.selected_choice_label is not None:
        raise InputError("open questions do not accept a selected choice")
    return JSONResponse(
        {
            "run_id": run_id,
            "question": question.model_dump(mode="json"),
            "correct": correct,
            "feedback_kind": (
                "semantic_self_assessment"
                if question.exercise_kind is not None
                else "choice_check"
                if question.answer_mode == "multiple_choice"
                else "reference_comparison"
            ),
        }
    )


__all__ = ["get_quiz_questions", "load_presentable_questions", "reveal_quiz_question"]
