from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ahadiff.review.database import connect_review_db

if TYPE_CHECKING:
    from pathlib import Path

_MIN_REVIEWS_FOR_TREND = 3
_IMPROVEMENT_THRESHOLD = 0.2


@dataclass(frozen=True)
class TransferMetrics:
    concept: str
    total_reviews: int
    avg_rating: float
    improving: bool


@dataclass(frozen=True)
class LearningTransferResult:
    total_concepts_reviewed: int
    concepts_improving: int
    concepts_stable: int
    concepts_declining: int
    transfer_rate: float
    metrics: list[TransferMetrics]


def validate_learning_transfer(
    db_path: Path,
    *,
    min_reviews: int = 3,
) -> LearningTransferResult:
    if not db_path.is_file():
        return _empty_result()

    try:
        with connect_review_db(db_path) as conn:
            concept_rows = conn.execute(
                """
                SELECT c.concept, COUNT(rl.id) AS cnt, AVG(rl.rating) AS avg_r
                FROM cards c
                JOIN review_logs rl ON c.id = rl.card_id
                GROUP BY c.concept
                HAVING cnt >= ?
                ORDER BY c.concept
                """,
                (min_reviews,),
            ).fetchall()

            if not concept_rows:
                return _empty_result()

            all_ratings: dict[str, list[int]] = {}
            for concept_row in concept_rows:
                concept = str(concept_row[0])
                rating_rows = conn.execute(
                    """
                    SELECT rl.rating
                    FROM review_logs rl
                    JOIN cards c ON c.id = rl.card_id
                    WHERE c.concept = ?
                    ORDER BY rl.reviewed_at_utc ASC
                    """,
                    (concept,),
                ).fetchall()
                all_ratings[concept] = [int(r[0]) for r in rating_rows]

    except sqlite3.OperationalError:
        return _empty_result()

    metrics: list[TransferMetrics] = []
    improving_count = 0
    stable_count = 0
    declining_count = 0

    for concept_row in concept_rows:
        concept = str(concept_row[0])
        total = int(concept_row[1])
        avg_r = float(concept_row[2]) if concept_row[2] is not None else 0.0

        ratings = all_ratings.get(concept, [])
        improving = _is_improving(ratings)
        declining = _is_declining(ratings)

        if improving:
            improving_count += 1
        elif declining:
            declining_count += 1
        else:
            stable_count += 1

        metrics.append(
            TransferMetrics(
                concept=concept,
                total_reviews=total,
                avg_rating=round(avg_r, 2),
                improving=improving,
            )
        )

    total_concepts = len(metrics)
    return LearningTransferResult(
        total_concepts_reviewed=total_concepts,
        concepts_improving=improving_count,
        concepts_stable=stable_count,
        concepts_declining=declining_count,
        transfer_rate=round(improving_count / total_concepts, 4) if total_concepts > 0 else 0.0,
        metrics=metrics,
    )


def _is_improving(ratings: list[int]) -> bool:
    if len(ratings) < _MIN_REVIEWS_FOR_TREND:
        return False
    mid = len(ratings) // 2
    first_half_avg = sum(ratings[:mid]) / mid
    second_half_avg = sum(ratings[mid:]) / (len(ratings) - mid)
    return second_half_avg > first_half_avg + _IMPROVEMENT_THRESHOLD


def _is_declining(ratings: list[int]) -> bool:
    if len(ratings) < _MIN_REVIEWS_FOR_TREND:
        return False
    mid = len(ratings) // 2
    first_half_avg = sum(ratings[:mid]) / mid
    second_half_avg = sum(ratings[mid:]) / (len(ratings) - mid)
    return second_half_avg < first_half_avg - _IMPROVEMENT_THRESHOLD


def _empty_result() -> LearningTransferResult:
    return LearningTransferResult(
        total_concepts_reviewed=0,
        concepts_improving=0,
        concepts_stable=0,
        concepts_declining=0,
        transfer_rate=0.0,
        metrics=[],
    )


__all__ = ["LearningTransferResult", "TransferMetrics", "validate_learning_transfer"]
