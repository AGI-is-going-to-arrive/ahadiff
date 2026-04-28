from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ahadiff.contracts import ReviewCard
from ahadiff.lesson.transfer import validate_learning_transfer
from ahadiff.review.database import connect_review_db, import_cards_from_jsonl

if TYPE_CHECKING:
    from pathlib import Path


def _make_card(concept: str) -> ReviewCard:
    return ReviewCard(
        card_id=f"card-{concept}",
        concept=concept,
        run_id="run-1",
        source_ref="abc1234",
        fsrs_state="{}",
        file_id="file-app",
        display_path="src/app.py",
        hunk_id="hunk-1",
        hunk_hash="deadbeefcafe",
    )


def _write_cards_jsonl(path: Path, cards: list[ReviewCard]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(c.model_dump(mode="json")) + "\n" for c in cards),
        encoding="utf-8",
    )


def _setup_db_with_reviews(
    tmp_path: Path,
    concept_ratings: dict[str, list[int]],
) -> Path:
    db_path = tmp_path / "review.sqlite"
    cards_path = tmp_path / "cards.jsonl"
    cards = [_make_card(concept) for concept in concept_ratings]
    _write_cards_jsonl(cards_path, cards)
    import_cards_from_jsonl(db_path, cards_path)

    with connect_review_db(db_path) as conn:
        for concept, ratings in concept_ratings.items():
            card_id = f"card-{concept}"
            base_time = datetime(2026, 1, 1, tzinfo=UTC)
            for i, rating in enumerate(ratings):
                reviewed_at = base_time + timedelta(days=i)
                conn.execute(
                    """
                    INSERT INTO review_logs (
                        card_id, rating, reviewed_at_utc,
                        elapsed_days, scheduled_days, state
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (card_id, rating, reviewed_at.isoformat(), float(i), 1.0, "Review"),
                )
        conn.commit()
    return db_path


def test_transfer_empty_db(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    result = validate_learning_transfer(db_path)
    assert result.total_concepts_reviewed == 0
    assert result.transfer_rate == 0.0


def test_transfer_nonexistent_db(tmp_path: Path) -> None:
    result = validate_learning_transfer(tmp_path / "none.sqlite")
    assert result.total_concepts_reviewed == 0


def test_transfer_insufficient_reviews(tmp_path: Path) -> None:
    db_path = _setup_db_with_reviews(tmp_path, {"loops": [3, 3]})
    result = validate_learning_transfer(db_path, min_reviews=3)
    assert result.total_concepts_reviewed == 0


def test_transfer_improving_concept(tmp_path: Path) -> None:
    db_path = _setup_db_with_reviews(tmp_path, {"closures": [1, 1, 2, 3, 4, 4]})
    result = validate_learning_transfer(db_path, min_reviews=3)
    assert result.total_concepts_reviewed == 1
    assert result.concepts_improving == 1
    assert result.transfer_rate == 1.0
    assert result.metrics[0].improving is True


def test_transfer_declining_concept(tmp_path: Path) -> None:
    db_path = _setup_db_with_reviews(tmp_path, {"pointers": [4, 4, 3, 1, 1, 1]})
    result = validate_learning_transfer(db_path, min_reviews=3)
    assert result.concepts_declining == 1
    assert result.metrics[0].improving is False


def test_transfer_stable_concept(tmp_path: Path) -> None:
    db_path = _setup_db_with_reviews(tmp_path, {"arrays": [3, 3, 3, 3, 3, 3]})
    result = validate_learning_transfer(db_path, min_reviews=3)
    assert result.concepts_stable == 1


def test_transfer_three_reviews_can_still_show_improving_trend(tmp_path: Path) -> None:
    db_path = _setup_db_with_reviews(tmp_path, {"closures": [1, 2, 3]})
    result = validate_learning_transfer(db_path, min_reviews=3)
    assert result.total_concepts_reviewed == 1
    assert result.concepts_improving == 1
    assert result.metrics[0].improving is True


def test_transfer_three_reviews_can_still_show_declining_trend(tmp_path: Path) -> None:
    db_path = _setup_db_with_reviews(tmp_path, {"pointers": [3, 2, 1]})
    result = validate_learning_transfer(db_path, min_reviews=3)
    assert result.total_concepts_reviewed == 1
    assert result.concepts_declining == 1
    assert result.metrics[0].improving is False


def test_transfer_mixed(tmp_path: Path) -> None:
    db_path = _setup_db_with_reviews(
        tmp_path,
        {
            "improving": [1, 1, 2, 3, 4, 4],
            "stable": [3, 3, 3, 3, 3, 3],
            "declining": [4, 4, 3, 1, 1, 1],
        },
    )
    result = validate_learning_transfer(db_path, min_reviews=3)
    assert result.total_concepts_reviewed == 3
    assert result.concepts_improving == 1
    assert result.concepts_stable == 1
    assert result.concepts_declining == 1
    assert abs(result.transfer_rate - (1 / 3)) < 0.01
