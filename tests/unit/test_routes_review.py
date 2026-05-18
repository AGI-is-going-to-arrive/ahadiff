from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from starlette.testclient import TestClient

from ahadiff.contracts import (
    QuizChoice,
    ReviewCard,
    ReviewQueueStateRequest,
    ReviewRateRequest,
)
from ahadiff.review.database import (
    connect_review_db,
    import_cards_from_jsonl,
    initialize_review_db,
    normalize_due_card_count,
    normalize_due_card_float,
    normalize_due_card_last_rating,
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
    concept: str = "retry loop",
    answer_mode: Literal["open", "multiple_choice"] = "open",
) -> ReviewCard:
    answer = "Retry loop"
    return ReviewCard(
        card_id=card_id,
        concept=concept,
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


def _write_cards_artifact(cards_path: Path, cards: list[ReviewCard]) -> None:
    cards_path.parent.mkdir(parents=True, exist_ok=True)
    cards_path.write_text(
        "".join(json.dumps(card.model_dump(mode="json"), sort_keys=True) + "\n" for card in cards),
        encoding="utf-8",
    )


def _seed_review_cards(state_dir: Path, cards: list[ReviewCard]) -> Path:
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    _write_review_cards(db_path, state_dir / "runs" / "run-1" / "quiz" / "cards.jsonl", cards)
    return db_path


def _learning_signal_payload(db_path: Path, idempotency_key: str) -> dict[str, Any]:
    with connect_review_db(db_path) as connection:
        row = connection.execute(
            "SELECT payload_json FROM learning_signals WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
    assert row is not None
    return cast("dict[str, Any]", json.loads(str(row["payload_json"])))


def test_review_queue_without_token_is_public_empty_db(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/review/queue")

    assert response.status_code == 200
    assert response.json() == {"cards": []}


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "post",
            "/api/review/rate",
            {"card_id": "card-1", "answer": "good", "idempotency_key": "rate-1"},
        ),
        ("post", "/api/review/queue-state", {"card_id": "card-1", "state": "archived"}),
        ("get", "/api/concepts/weak", None),
        ("get", "/api/review/mastery", None),
    ],
)
def test_protected_review_endpoints_without_token_return_403(
    tmp_path: Path,
    method: Literal["get", "post"],
    path: str,
    payload: dict[str, object] | None,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    if method == "get":
        response = client.get(path)
    else:
        response = client.post(path, headers=_ORIGIN, json=payload)

    assert response.status_code == 401


def test_review_read_endpoints_with_auth_return_empty_db_state(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    client = _client(state_dir)

    queue = client.get("/api/review/queue", headers=_AUTH)
    weak = client.get("/api/concepts/weak", headers=_AUTH)
    mastery = client.get("/api/review/mastery", headers=_AUTH)

    assert queue.status_code == 200
    assert queue.json() == {"cards": []}
    assert weak.status_code == 200
    assert weak.json() == {"concepts": [], "new_concepts": []}
    assert mastery.status_code == 200
    assert mastery.json() == {"mastery": []}


def test_review_queue_response_includes_fsrs_card_stats(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = _seed_review_cards(
        state_dir,
        [_review_card("card-default"), _review_card("card-stats")],
    )
    with connect_review_db(db_path) as connection:
        connection.execute(
            """
            UPDATE cards
            SET stability = ?, difficulty = ?, reps = ?, lapses = ?, last_rating = ?
            WHERE id = ?
            """,
            (4.5, 6.25, 2, 1, 2, "card-stats"),
        )
    client = _client(state_dir)

    response = client.get("/api/review/queue", headers=_AUTH)

    assert response.status_code == 200
    cards = {card["card_id"]: card for card in response.json()["cards"]}
    stats_card = cards["card-stats"]
    assert stats_card["stability"] == 4.5
    assert stats_card["difficulty"] == 6.25
    assert stats_card["reps"] == 2
    assert stats_card["lapses"] == 1
    assert stats_card["last_rating"] == 2
    assert isinstance(stats_card["stability"], float)
    assert isinstance(stats_card["difficulty"], float)
    assert isinstance(stats_card["reps"], int)
    assert isinstance(stats_card["lapses"], int)
    assert isinstance(stats_card["last_rating"], int)
    default_card = cards["card-default"]
    assert default_card["reps"] == 0
    assert default_card["lapses"] == 0
    assert default_card["last_rating"] is None


def test_review_queue_hides_cards_for_invalid_finalized_runs(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    valid_card = _review_card("card-valid").model_copy(update={"run_id": "run-valid"})
    invalid_card = _review_card("card-invalid").model_copy(update={"run_id": "run-invalid"})
    _write_review_cards(
        db_path,
        state_dir / "runs" / "run-valid" / "quiz" / "cards.jsonl",
        [valid_card, invalid_card],
    )
    invalid_run = state_dir / "runs" / "run-invalid"
    invalid_run.mkdir(parents=True)
    (invalid_run / "finalized.json").write_text(
        json.dumps(
            {
                "artifact_count": 0,
                "checksum": "not-the-current-digest",
                "event_id": "018f0f52-91c0-7abc-8123-000000000000",
                "finalized_at": "2026-04-24T00:00:00Z",
                "run_id": "run-invalid",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.get("/api/review/queue", headers=_AUTH)

    assert response.status_code == 200
    assert [card["card_id"] for card in response.json()["cards"]] == ["card-valid"]


def test_review_queue_hides_cards_with_invalid_run_ids(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = _seed_review_cards(
        state_dir,
        [
            _review_card("card-valid"),
            _review_card("card-bad-run").model_copy(update={"run_id": "../bad"}),
        ],
    )
    client = _client(state_dir)

    response = client.get("/api/review/queue", headers=_AUTH)

    assert response.status_code == 200
    assert [card["card_id"] for card in response.json()["cards"]] == ["card-valid"]
    with connect_review_db(db_path) as connection:
        row = connection.execute(
            "SELECT run_id FROM cards WHERE id = ?",
            ("card-bad-run",),
        ).fetchone()
    assert row["run_id"] == "../bad"


def test_review_queue_hides_cards_with_symlink_finalized_markers(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    valid_card = _review_card("card-valid").model_copy(update={"run_id": "run-valid"})
    symlink_card = _review_card("card-symlink").model_copy(update={"run_id": "run-symlink"})
    _write_review_cards(
        db_path,
        state_dir / "runs" / "run-valid" / "quiz" / "cards.jsonl",
        [valid_card, symlink_card],
    )
    symlink_run = state_dir / "runs" / "run-symlink"
    symlink_run.mkdir(parents=True)
    target = state_dir / "target-finalized.json"
    target.write_text("{}", encoding="utf-8")
    try:
        (symlink_run / "finalized.json").symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    client = _client(state_dir)

    response = client.get("/api/review/queue", headers=_AUTH)

    assert response.status_code == 200
    assert [card["card_id"] for card in response.json()["cards"]] == ["card-valid"]


def test_review_queue_overscans_invalid_finalized_runs_before_valid_cards(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    invalid_cards = [
        _review_card(f"card-invalid-{index:02d}").model_copy(
            update={"run_id": f"run-invalid-{index:02d}"}
        )
        for index in range(20)
    ]
    valid_card = _review_card("card-valid").model_copy(update={"run_id": "run-valid"})
    _write_review_cards(
        db_path,
        state_dir / "runs" / "run-valid" / "quiz" / "cards.jsonl",
        [*invalid_cards, valid_card],
    )
    for card in invalid_cards:
        invalid_run = state_dir / "runs" / card.run_id
        invalid_run.mkdir(parents=True)
        (invalid_run / "finalized.json").write_text(
            json.dumps(
                {
                    "artifact_count": 0,
                    "checksum": "not-the-current-digest",
                    "event_id": f"event-{card.card_id}",
                    "finalized_at": "2026-04-24T00:00:00Z",
                    "run_id": card.run_id,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    client = _client(state_dir)

    response = client.get("/api/review/queue", headers=_AUTH)

    assert response.status_code == 200
    assert [card["card_id"] for card in response.json()["cards"]] == ["card-valid"]


def test_review_queue_sanitizes_invalid_fsrs_card_stats(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = _seed_review_cards(
        state_dir,
        [
            _review_card("card-inf"),
            _review_card("card-negative"),
            _review_card("card-text"),
        ],
    )
    with connect_review_db(db_path) as connection:
        connection.execute(
            """
            UPDATE cards
            SET stability = ?, difficulty = ?, reps = ?, lapses = ?, last_rating = ?
            WHERE id = ?
            """,
            (float("inf"), float("-inf"), 2, 1, 9, "card-inf"),
        )
        connection.execute(
            """
            UPDATE cards
            SET stability = ?, difficulty = ?, reps = ?, lapses = ?, last_rating = ?
            WHERE id = ?
            """,
            (-1.0, -0.5, -3, -2, 0, "card-negative"),
        )
        connection.execute(
            """
            UPDATE cards
            SET stability = ?, difficulty = ?, reps = ?, lapses = ?, last_rating = ?
            WHERE id = ?
            """,
            ("not-a-number", "NaN", "inf", "3.5", "2.5", "card-text"),
        )
    client = _client(state_dir)

    response = client.get("/api/review/queue", headers=_AUTH)

    assert response.status_code == 200
    assert normalize_due_card_float(float("nan")) is None
    assert normalize_due_card_float("not-a-number") is None
    assert normalize_due_card_count(float("inf")) == 0
    assert normalize_due_card_count("3.5") == 0
    assert normalize_due_card_last_rating(float("nan")) is None
    assert normalize_due_card_last_rating("2.5") is None
    cards = {card["card_id"]: card for card in response.json()["cards"]}
    inf_card = cards["card-inf"]
    assert inf_card["stability"] is None
    assert inf_card["difficulty"] is None
    assert inf_card["reps"] == 2
    assert inf_card["lapses"] == 1
    assert inf_card["last_rating"] is None
    negative_card = cards["card-negative"]
    assert negative_card["stability"] is None
    assert negative_card["difficulty"] is None
    assert negative_card["reps"] == 0
    assert negative_card["lapses"] == 0
    assert negative_card["last_rating"] is None
    text_card = cards["card-text"]
    assert text_card["stability"] is None
    assert text_card["difficulty"] is None
    assert text_card["reps"] == 0
    assert text_card["lapses"] == 0
    assert text_card["last_rating"] is None


def test_review_rate_valid_payload_records_review_once(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = _seed_review_cards(state_dir, [_review_card("card-1")])
    client = _client(state_dir)
    payload = ReviewRateRequest(
        card_id="card-1",
        answer="good",
        idempotency_key="review-api-1",
    ).model_dump(mode="json")

    first = client.post("/api/review/rate", headers=_AUTH, json=payload)
    second = client.post("/api/review/rate", headers=_AUTH, json=payload)

    assert first.status_code == 200
    assert first.json()["inserted"] is True
    assert first.json()["review"]["card_id"] == "card-1"
    assert first.json()["review"]["rating"] == 3
    assert second.status_code == 200
    assert second.json() == {"inserted": False}
    with connect_review_db(db_path) as connection:
        review_log_count = connection.execute("SELECT COUNT(*) FROM review_logs").fetchone()[0]
    assert review_log_count == 1
    assert _learning_signal_payload(db_path, "review-api-1")["answer"] == "good"


def test_review_rate_lazy_imports_run_cards_before_rating(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    _write_cards_artifact(
        state_dir / "runs" / "run-1" / "quiz" / "cards.jsonl",
        [_review_card("lazy-card")],
    )
    client = _client(state_dir)
    payload = ReviewRateRequest(
        card_id="lazy-card",
        answer="good",
        idempotency_key="review-lazy-import",
    ).model_dump(mode="json")

    response = client.post("/api/review/rate", headers=_AUTH, json=payload)
    duplicate = client.post("/api/review/rate", headers=_AUTH, json=payload)

    assert response.status_code == 200
    assert response.json()["inserted"] is True
    assert response.json()["review"]["card_id"] == "lazy-card"
    assert duplicate.status_code == 200
    assert duplicate.json() == {"inserted": False}
    with connect_review_db(db_path) as connection:
        review_log_count = connection.execute("SELECT COUNT(*) FROM review_logs").fetchone()[0]
        card_count = connection.execute(
            "SELECT COUNT(*) FROM cards WHERE id = 'lazy-card'"
        ).fetchone()[0]
    assert card_count == 1
    assert review_log_count == 1
    assert _learning_signal_payload(db_path, "review-lazy-import")["answer"] == "good"


def test_review_rate_invalid_payload_returns_422(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.post(
        "/api/review/rate",
        headers=_AUTH,
        json={"card_id": "card-1", "answer": "medium", "idempotency_key": "bad-rate"},
    )

    assert response.status_code == 422
    body = response.json()
    errors = body.get("details", {}).get("errors", body.get("error"))
    assert isinstance(errors, list)
    assert errors[0]["loc"] == ["answer"]


def test_review_rate_valid_payload_for_missing_card_returns_400(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    client = _client(state_dir)
    payload = ReviewRateRequest(
        card_id="missing-card",
        answer="good",
        idempotency_key="review-missing-card",
    ).model_dump(mode="json")

    response = client.post("/api/review/rate", headers=_AUTH, json=payload)

    assert response.status_code == 400
    assert "active review card does not exist" in response.json()["error"]


def test_review_queue_state_valid_transitions_update_cards(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = _seed_review_cards(
        state_dir,
        [_review_card("card-archive"), _review_card("card-suspend")],
    )
    client = _client(state_dir)
    archive = ReviewQueueStateRequest(card_id="card-archive", state="archived").model_dump(
        mode="json"
    )
    suspend = ReviewQueueStateRequest(card_id="card-suspend", state="suspended").model_dump(
        mode="json"
    )

    archived = client.post("/api/review/queue-state", headers=_AUTH, json=archive)
    suspended = client.post("/api/review/queue-state", headers=_AUTH, json=suspend)

    assert archived.status_code == 200
    assert archived.json() == {"card_id": "card-archive", "state": "archived", "updated": True}
    assert suspended.status_code == 200
    assert suspended.json() == {"card_id": "card-suspend", "state": "suspended", "updated": True}
    with connect_review_db(db_path) as connection:
        rows = connection.execute("SELECT id, card_state FROM cards ORDER BY id").fetchall()
        review_log_count = connection.execute("SELECT COUNT(*) FROM review_logs").fetchone()[0]
    assert {row["id"]: row["card_state"] for row in rows} == {
        "card-archive": "archived",
        "card-suspend": "suspended",
    }
    assert review_log_count == 0


def test_review_queue_state_invalid_payload_returns_422(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.post(
        "/api/review/queue-state",
        headers=_AUTH,
        json={"card_id": "card-1", "state": "active"},
    )

    assert response.status_code == 422
    body = response.json()
    errors = body.get("details", {}).get("errors", body.get("error"))
    assert isinstance(errors, list)
    assert errors[0]["loc"] == ["state"]


def test_weak_concepts_and_mastery_with_seeded_reviews(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = _seed_review_cards(
        state_dir,
        [
            _review_card("card-reviewed", concept="reviewed concept"),
            _review_card("card-new", concept="new concept"),
        ],
    )
    client = _client(state_dir)
    payload = ReviewRateRequest(
        card_id="card-reviewed",
        answer="wrong",
        idempotency_key="review-weak-card",
    ).model_dump(mode="json")

    rated = client.post("/api/review/rate", headers=_AUTH, json=payload)
    weak = client.get("/api/concepts/weak", headers=_AUTH)
    mastery = client.get("/api/review/mastery", headers=_AUTH)

    assert rated.status_code == 200
    assert weak.status_code == 200
    weak_body = weak.json()
    assert [item["card_id"] for item in weak_body["concepts"]] == ["card-reviewed"]
    assert [item["card_id"] for item in weak_body["new_concepts"]] == ["card-new"]
    assert mastery.status_code == 200
    assert mastery.json()["mastery"] == [
        {
            "concept": "reviewed concept",
            "review_count": 1,
            "avg_rating": 1.0,
            "last_review": mastery.json()["mastery"][0]["last_review"],
        }
    ]
    with connect_review_db(db_path) as connection:
        signal_count = connection.execute("SELECT COUNT(*) FROM learning_signals").fetchone()[0]
    assert signal_count == 1
