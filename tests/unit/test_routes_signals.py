from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from starlette.testclient import TestClient

from ahadiff.contracts import (
    HelpfulnessRequest,
    MarkWrongRequest,
    QuizAnswerRequest,
    QuizChoice,
    ReviewCard,
    ReviewSignalRequest,
)
from ahadiff.review.database import (
    connect_review_db,
    import_cards_from_jsonl,
    initialize_review_db,
)
from ahadiff.serve.app import create_app
from ahadiff.serve.state import ServeState

if TYPE_CHECKING:
    from pathlib import Path


_AUTH = {"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"}
_ORIGIN = {"origin": "http://localhost:8765"}


def _client(
    state_dir: Path,
    *,
    token: str = "test-token",
    locale: Literal["en", "zh-CN"] = "en",
) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token=token, locale=locale))
    return TestClient(app, base_url="http://localhost:8765")


def _quiz_choices(correct_text: str = "Retry loop") -> list[QuizChoice]:
    return [
        QuizChoice(label="A", text=correct_text, is_correct=True),
        QuizChoice(label="B", text="It removes exception handling.", is_correct=False),
        QuizChoice(label="C", text="It disables retry behavior.", is_correct=False),
        QuizChoice(label="D", text="It changes only comments.", is_correct=False),
    ]


def _review_card(
    card_id: str,
    *,
    answer_mode: Literal["open", "multiple_choice"] = "open",
) -> ReviewCard:
    answer = "Retry loop"
    return ReviewCard(
        card_id=card_id,
        concept="retry loop",
        run_id="run-1",
        source_ref="abc1234",
        fsrs_state="{}",
        file_id="file-app",
        display_path="src/app.py",
        hunk_id=f"hunk-{card_id}",
        hunk_hash=f"deadbeef{card_id}",
        symbol="retry_once",
        question="What changed?",
        answer=answer,
        answer_mode=answer_mode,
        choices=_quiz_choices(answer) if answer_mode == "multiple_choice" else None,
    )


def _write_review_cards(db_path: Path, cards_path: Path, cards: list[ReviewCard]) -> None:
    cards_path.parent.mkdir(parents=True, exist_ok=True)
    cards_path.write_text(
        "".join(json.dumps(card.model_dump(mode="json"), sort_keys=True) + "\n" for card in cards),
        encoding="utf-8",
    )
    assert import_cards_from_jsonl(db_path, cards_path) == len(cards)


def _seed_review_cards(state_dir: Path, cards: list[ReviewCard]) -> Path:
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    _write_review_cards(db_path, state_dir / "runs" / "run-1" / "quiz" / "cards.jsonl", cards)
    return db_path


def _learning_signal_row(db_path: Path, idempotency_key: str) -> tuple[str, dict[str, Any]]:
    with connect_review_db(db_path) as connection:
        row = connection.execute(
            """
            SELECT signal_type, payload_json
            FROM learning_signals
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
    assert row is not None
    payload = cast("dict[str, Any]", json.loads(str(row["payload_json"])))
    return str(row["signal_type"]), payload


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/signals/mark-wrong",
            {"claim_id": "claim-1", "idempotency_key": "mark:claim-1:wrong"},
        ),
        (
            "/api/signals/quiz-answer",
            {"quiz_id": "q1", "choice": "A", "correct": True, "idempotency_key": "quiz-1"},
        ),
        (
            "/api/signals/srs-review",
            {"card_id": "card-1", "answer": "hard", "idempotency_key": "srs-1"},
        ),
        (
            "/api/signals/helpfulness",
            {"target_id": "section-1", "payload": {"rating": 5}, "idempotency_key": "help-1"},
        ),
    ],
)
def test_signal_endpoints_without_token_return_403(
    tmp_path: Path,
    path: str,
    payload: dict[str, object],
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.post(path, headers=_ORIGIN, json=payload)

    assert response.status_code == 401


def test_mark_wrong_signal_valid_submission(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    payload = MarkWrongRequest(
        claim_id="claim-1",
        idempotency_key="mark:claim-1:wrong",
    ).model_dump(mode="json")

    first = client.post("/api/signals/mark-wrong", headers=_AUTH, json=payload)
    second = client.post("/api/signals/mark-wrong", headers=_AUTH, json=payload)

    assert first.status_code == 200
    assert first.json() == {"inserted": True}
    assert second.status_code == 200
    assert second.json() == {"inserted": False}
    signal_type, signal_payload = _learning_signal_row(
        state_dir / "review.sqlite",
        "mark:claim-1:wrong",
    )
    assert signal_type == "mark_wrong"
    assert signal_payload == {"claim_id": "claim-1"}


def test_quiz_answer_signal_valid_submission(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    payload = QuizAnswerRequest(
        quiz_id="q1",
        choice="Retry loop answer text",
        correct=False,
        selected_choice_label="B",
        idempotency_key="quiz:run-1:q1",
    ).model_dump(mode="json")

    first = client.post("/api/signals/quiz-answer", headers=_AUTH, json=payload)
    second = client.post("/api/signals/quiz-answer", headers=_AUTH, json=payload)

    assert first.status_code == 200
    assert first.json() == {"inserted": True}
    assert second.status_code == 200
    assert second.json() == {"inserted": False}
    signal_type, signal_payload = _learning_signal_row(
        state_dir / "review.sqlite",
        "quiz:run-1:q1",
    )
    assert signal_type == "quiz_answer"
    assert signal_payload == {
        "choice": "Retry loop answer text",
        "correct": False,
        "quiz_id": "q1",
        "selected_choice_label": "B",
    }


def test_srs_review_signal_valid_submission(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = _seed_review_cards(state_dir, [_review_card("card-1")])
    client = _client(state_dir)
    payload = ReviewSignalRequest(
        card_id="card-1",
        answer="hard",
        idempotency_key="review-1",
    ).model_dump(mode="json")

    first = client.post("/api/signals/srs-review", headers=_AUTH, json=payload)
    second = client.post("/api/signals/srs-review", headers=_AUTH, json=payload)

    assert first.status_code == 200
    assert first.json()["inserted"] is True
    assert first.json()["review"]["card_id"] == "card-1"
    assert first.json()["review"]["rating"] == 2
    assert second.status_code == 200
    assert second.json() == {"inserted": False}
    signal_type, signal_payload = _learning_signal_row(db_path, "review-1")
    assert signal_type == "srs_review"
    assert signal_payload == {
        "answer": "hard",
        "card_id": "card-1",
        "peeked_this_session": False,
    }


def test_helpfulness_signal_valid_submission(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    payload = HelpfulnessRequest(
        target_kind="section",
        target_id="  run-1  :  intro  ",
        payload={"rating": 5, "section_id": "sec-intro"},
        idempotency_key="help:run-1:intro",
    ).model_dump(mode="json")

    first = client.post("/api/signals/helpfulness", headers=_AUTH, json=payload)
    second = client.post("/api/signals/helpfulness", headers=_AUTH, json=payload)

    assert first.status_code == 200
    assert first.json() == {"inserted": True}
    assert second.status_code == 200
    assert second.json() == {"inserted": False}
    signal_type, signal_payload = _learning_signal_row(
        state_dir / "review.sqlite",
        "help:run-1:intro",
    )
    assert signal_type == "helpfulness"
    assert signal_payload == {
        "target_kind": "section",
        "target_id": "run-1:intro",
        "payload": {"rating": 5, "section_id": "sec-intro"},
    }


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        ("/api/signals/mark-wrong", {"idempotency_key": "mark-missing"}, "claim_id"),
        (
            "/api/signals/quiz-answer",
            {"choice": "A", "correct": True, "idempotency_key": "quiz-missing"},
            "quiz_id",
        ),
        (
            "/api/signals/srs-review",
            {"answer": "hard", "idempotency_key": "srs-missing"},
            "card_id",
        ),
        (
            "/api/signals/helpfulness",
            {"payload": {"rating": 5}, "idempotency_key": "help-missing"},
            "target_id",
        ),
    ],
)
def test_signal_endpoints_missing_required_fields_return_422(
    tmp_path: Path,
    path: str,
    payload: dict[str, object],
    field: str,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.post(path, headers=_AUTH, json=payload)

    assert response.status_code == 422
    body = response.json()
    errors = body.get("details", {}).get("errors", body.get("error"))
    assert isinstance(errors, list)
    assert errors[0]["loc"] == [field]


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        (
            "/api/signals/mark-wrong",
            {"claim_id": "", "idempotency_key": "mark-empty"},
            "claim_id",
        ),
        (
            "/api/signals/quiz-answer",
            {
                "quiz_id": "q1",
                "choice": "A",
                "correct": "not-a-bool",
                "idempotency_key": "quiz-bad-type",
            },
            "correct",
        ),
        (
            "/api/signals/srs-review",
            {"card_id": "card-1", "answer": "medium", "idempotency_key": "srs-bad"},
            "answer",
        ),
        (
            "/api/signals/helpfulness",
            {"target_id": "section-1", "payload": "bad", "idempotency_key": "help-bad"},
            "payload",
        ),
    ],
)
def test_signal_endpoints_invalid_payloads_return_422(
    tmp_path: Path,
    path: str,
    payload: dict[str, object],
    field: str,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.post(path, headers=_AUTH, json=payload)

    assert response.status_code == 422
    body = response.json()
    errors = body.get("details", {}).get("errors", body.get("error"))
    assert isinstance(errors, list)
    assert errors[0]["loc"] == [field]
