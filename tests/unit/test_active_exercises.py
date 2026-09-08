from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from ahadiff.contracts import QuizAnswerRequest, ResultEvent, ReviewCard
from ahadiff.eval.results import finalized_artifact_digest
from ahadiff.quiz.schemas import QuizQuestion, parse_quiz_payload
from ahadiff.review.database import (
    connect_review_db,
    import_cards_from_jsonl,
    initialize_review_db,
    sync_result_event,
)
from ahadiff.serve import ServeState, create_app
from ahadiff.serve.routes_signals import record_quiz_attempt

if TYPE_CHECKING:
    from pathlib import Path

_AUTH = {"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"}
_RUN_ID = "run-1"
_EVENT_ID = "018f0f52-91c0-7abc-8123-000000000001"


def _exercise(**overrides: object) -> QuizQuestion:
    payload: dict[str, object] = {
        "question_id": "quiz-practice",
        "review_card_id": "card_exercise_synthetic",
        "question": "Complete this similar example:\nif request_fails:\n    ____",
        "expected_answer": "if request_fails:\n    retry_later()",
        "quiz_kind": "transfer",
        "exercise_kind": "completion",
        "scenario_kind": "new_variant",
        "answer_mode": "open",
        "source_claims": ["claim-retry"],
        "concepts": ["retry loop"],
        "evidence": [{"file": "sample.py", "line": 2}],
        "explanation": "The source supports a bounded retry, not guaranteed success.",
    }
    payload.update(overrides)
    return QuizQuestion.model_validate(payload)


def _choice() -> QuizQuestion:
    return _exercise(
        question_id="quiz-choice",
        review_card_id=None,
        question="Which path retries?",
        exercise_kind=None,
        scenario_kind=None,
        quiz_kind="recall",
        answer_mode="multiple_choice",
        expected_answer="The failed request path",
        choices=[
            {"label": "A", "text": "The failed request path", "is_correct": True},
            {"label": "B", "text": "Only the success path", "is_correct": False},
            {"label": "C", "text": "No request path", "is_correct": False},
            {"label": "D", "text": "Only comments change", "is_correct": False},
        ],
    )


def _write_run(state_dir: Path, questions: list[QuizQuestion], *, card: bool = False) -> Path:
    run = state_dir / "runs" / _RUN_ID
    (run / "quiz").mkdir(parents=True)
    (run / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": _RUN_ID,
                "source_kind": "git_ref",
                "source_ref": "abc1234",
                "content_lang": "en",
                "capability_level": 2,
            }
        ),
        encoding="utf-8",
    )
    (run / "quiz" / "quiz.jsonl").write_text(
        "".join(q.model_dump_json() + "\n" for q in questions), encoding="utf-8"
    )
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    if card:
        q = questions[0]
        review_card = ReviewCard(
            card_id=q.review_card_id or "card_exercise_synthetic",
            concept=q.expected_answer,
            run_id=_RUN_ID,
            source_ref="abc1234",
            fsrs_state="{}",
            file_id="file-sample",
            display_path="sample.py",
            hunk_id="hunk-sample",
            hunk_hash="hash-sample",
            question=q.question,
            answer=q.expected_answer,
            symbol=q.expected_answer,
        )
        card_path = run / "quiz" / "cards.jsonl"
        card_path.write_text(review_card.model_dump_json() + "\n", encoding="utf-8")
        import_cards_from_jsonl(db_path, card_path)
    event = ResultEvent(
        event_id=_EVENT_ID,
        run_id=_RUN_ID,
        event_type="learn",
        timestamp="2026-09-08T00:00:00Z",
        source_ref="abc1234",
        base_ref="base123",
        prompt_version="prompt-v1",
        eval_bundle_version="eval-v1",
        rubric_version="rubric-v1",
        overall=88,
        verdict="PASS",
        status="keep",
        weakest_dim="evidence",
    )
    sync_result_event(db_path, event)
    count, checksum = finalized_artifact_digest(run)
    (run / "finalized.json").write_text(
        json.dumps(
            {
                "run_id": _RUN_ID,
                "event_id": _EVENT_ID,
                "finalized_at": "2026-09-08T00:00:00Z",
                "artifact_count": count,
                "checksum": checksum,
                "status": "keep",
            }
        ),
        encoding="utf-8",
    )
    return run


def _client(state_dir: Path, locale: Literal["en", "zh-CN"] = "en") -> TestClient:
    return TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token", locale=locale)),
        base_url="http://localhost:8765",
    )


def _assessment(key: str = "assessment-one", /, **overrides: object) -> QuizAnswerRequest:
    values: dict[str, object] = {
        "idempotency_key": key,
        "run_id": _RUN_ID,
        "quiz_id": "quiz-practice",
        "correct": None,
        "exercise_kind": "completion",
        "feedback_kind": "semantic_self_assessment",
        "self_assessment": "independent",
        "error_type": "none",
    }
    values.update(overrides)
    return QuizAnswerRequest.model_validate(values)


def _signals(db: Path) -> list[dict[str, object]]:
    with connect_review_db(db) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM learning_signals ORDER BY created_at"
        ).fetchall()
    return [json.loads(str(row["payload_json"])) for row in rows]


def test_active_exercise_keeps_multiline_and_generated_choice_gate_accepts_it() -> None:
    question = _exercise()
    parsed = parse_quiz_payload(
        json.dumps({"questions": [question.model_dump(mode="json")]}), require_choices=True
    )
    assert parsed.questions[0].question.endswith("\n    ____")
    assert parsed.questions[0].expected_answer.endswith("\n    retry_later()")
    assert _choice().answer_mode == "multiple_choice"
    with pytest.raises(ValueError, match="choices"):
        parse_quiz_payload(
            json.dumps(
                {
                    "questions": [
                        _exercise(exercise_kind=None, scenario_kind=None).model_dump(mode="json")
                    ]
                }
            ),
            require_choices=True,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"quiz_kind": "guided"},
        {"quiz_kind": "recall"},
        {"answer_mode": "multiple_choice"},
        {"evidence": []},
        {"exercise_kind": "run_code"},
        {"exercise_kind": None},
    ],
)
def test_invalid_active_contract_is_rejected(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _exercise(**updates)


@pytest.mark.parametrize("locale", ["en", "zh-CN"])
def test_quiz_public_and_reveal_routes_separate_answers(
    tmp_path: Path, locale: Literal["en", "zh-CN"]
) -> None:
    state_dir = tmp_path / ".ahadiff"
    _write_run(state_dir, [_exercise(), _choice()])
    client = _client(state_dir, locale)
    response = client.get(f"/api/run/{_RUN_ID}/quiz/questions")
    assert response.status_code == 200
    public = response.json()["questions"]
    assert len(public) == 2
    for row in public:
        assert set(row).isdisjoint(
            {
                "expected_answer",
                "explanation",
                "evidence",
                "source_anchors",
                "source_claims",
                "concepts",
            }
        )
        choices = cast("list[dict[str, object]]", row["choices"] or [])
        assert all("is_correct" not in choice for choice in choices)
    assert "retry_later()" not in response.text
    assert (
        client.post(
            f"/api/run/{_RUN_ID}/quiz/quiz-practice/reveal",
            headers={"origin": "http://localhost:8765"},
            json={"attempted": True},
        ).status_code
        == 401
    )
    assert (
        client.post(
            f"/api/run/{_RUN_ID}/quiz/quiz-practice/reveal", json={"attempted": True}
        ).status_code
        == 403
    )
    reveal = client.post(
        f"/api/run/{_RUN_ID}/quiz/quiz-practice/reveal", headers=_AUTH, json={"attempted": True}
    )
    assert reveal.status_code == 200
    assert reveal.json()["correct"] is None
    assert reveal.json()["feedback_kind"] == "semantic_self_assessment"
    assert reveal.json()["question"]["expected_answer"] == _exercise().expected_answer
    assert _signals(state_dir / "review.sqlite") == []
    original = client.get(f"/api/run/{_RUN_ID}/quiz")
    assert original.status_code == 200
    assert "retry_later()" in original.json()["content"]


@pytest.mark.parametrize(
    "body",
    [{"attempted": False}, {"attempted": 1}, {"attempted": True, "answer": "private attempt"}],
)
def test_reveal_rejects_nonattempts_and_free_text_payloads(
    tmp_path: Path, body: dict[str, object]
) -> None:
    state_dir = tmp_path / ".ahadiff"
    _write_run(state_dir, [_exercise()])
    response = _client(state_dir).post(
        f"/api/run/{_RUN_ID}/quiz/quiz-practice/reveal", headers=_AUTH, json=body
    )
    assert response.status_code == 422
    assert "private attempt" not in response.text


def test_choice_reveal_requires_selection_and_recomputes_correctness(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    _write_run(state_dir, [_choice()])
    client = _client(state_dir)
    assert (
        client.post(
            f"/api/run/{_RUN_ID}/quiz/quiz-choice/reveal", headers=_AUTH, json={"attempted": True}
        ).status_code
        == 400
    )
    response = client.post(
        f"/api/run/{_RUN_ID}/quiz/quiz-choice/reveal",
        headers=_AUTH,
        json={"attempted": True, "selected_choice_label": "A"},
    )
    assert response.json()["correct"] is True
    result = client.post(
        "/api/signals/quiz-answer",
        headers=_AUTH,
        json={
            "idempotency_key": "choice-one",
            "run_id": _RUN_ID,
            "quiz_id": "quiz-choice",
            "selected_choice_label": "A",
            "correct": False,
            "choice": "untrusted raw text",
        },
    )
    assert result.status_code == 200
    assert _signals(state_dir / "review.sqlite")[0] == {
        "run_id": _RUN_ID,
        "quiz_id": "quiz-choice",
        "choice": "A",
        "selected_choice_label": "A",
        "correct": True,
        "feedback_kind": "choice_check",
    }


def test_active_signal_saves_only_validated_metadata_and_is_idempotent(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    _write_run(state_dir, [_exercise()])
    body = _assessment(choice="SECRET synthetic learner answer")
    client = _client(state_dir)
    for inserted in (True, False):
        response = client.post(
            "/api/signals/quiz-answer", headers=_AUTH, json=body.model_dump(mode="json")
        )
        assert response.status_code == 200
        assert response.json() == {"inserted": inserted}
    rows = _signals(state_dir / "review.sqlite")
    assert len(rows) == 1
    assert "choice" not in rows[0]
    assert "SECRET" not in json.dumps(rows)
    assert rows[0]["correct"] is None
    assert rows[0]["attempt_kind"] == "unseen_variant"
    assert rows[0]["self_assessment"] == "independent"


@pytest.mark.parametrize(
    "updates",
    [
        {"correct": True},
        {"feedback_kind": "choice_check"},
        {"exercise_kind": "prediction"},
        {"self_assessment": "not_yet", "error_type": "none"},
        {"selected_choice_label": "A"},
        {"run_id": None},
    ],
)
def test_active_signal_rejects_forged_feedback(tmp_path: Path, updates: dict[str, object]) -> None:
    state_dir = tmp_path / ".ahadiff"
    _write_run(state_dir, [_exercise()])
    response = _client(state_dir).post(
        "/api/signals/quiz-answer",
        headers=_AUTH,
        json=_assessment(**updates).model_dump(mode="json"),
    )
    assert response.status_code == 400
    assert _signals(state_dir / "review.sqlite") == []


def test_delayed_recall_is_derived_from_persisted_time_not_client_metadata(tmp_path: Path) -> None:
    db = tmp_path / "review.sqlite"
    initialize_review_db(db)
    question = _exercise(scenario_kind=None)
    assert record_quiz_attempt(db, _assessment(attempt_kind="unseen_variant"), question)
    assert _signals(db)[0]["attempt_kind"] == "initial"
    with connect_review_db(db) as connection:
        connection.execute(
            "UPDATE learning_signals SET created_at = ?",
            ((datetime.now(UTC) - timedelta(hours=25)).isoformat(),),
        )
    assert record_quiz_attempt(db, _assessment("assessment-two", attempt_kind="initial"), question)
    delayed = _signals(db)[1]
    assert delayed["attempt_kind"] == "delayed_recall"
    assert int(str(delayed["elapsed_seconds"])) >= 86400
    assert not record_quiz_attempt(db, _assessment("assessment-two"), question)


def test_active_namespace_cannot_fall_back_to_legacy_raw_signal(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    response = _client(state_dir).post(
        "/api/signals/quiz-answer",
        headers=_AUTH,
        json={
            "idempotency_key": "missing-exercise-metadata",
            "quiz_id": "quiz_exercise_deadbeef",
            "choice": "synthetic private free-form attempt",
            "correct": False,
        },
    )
    assert response.status_code == 400
    assert _signals(state_dir / "review.sqlite") == []


def test_new_exercise_review_queue_hides_answers_and_fails_closed_without_artifacts(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    run = _write_run(state_dir, [_exercise()], card=True)
    client = _client(state_dir)
    response = client.get("/api/review/queue")
    assert response.status_code == 200
    cards = response.json()["cards"]
    assert len(cards) == 1
    assert cards[0]["exercise_kind"] == "completion"
    assert cards[0]["question_id"] == "quiz-practice"
    assert cards[0]["answer"] is None
    assert cards[0]["source_anchors"] == []
    assert cards[0]["concept"] == ""
    assert cards[0]["symbol"] is None
    assert cards[0]["source_ref"] is None
    assert cards[0]["display_path"] == ""
    assert "retry_later()" not in response.text
    (run / "quiz" / "quiz.jsonl").unlink()
    (run / "finalized.json").unlink()
    assert client.get("/api/review/queue").json() == {"cards": []}
