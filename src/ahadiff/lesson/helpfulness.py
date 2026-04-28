from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from ahadiff.core.json_util import safe_json_loads
from ahadiff.review.database import connect_review_db

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Literal


@dataclass(frozen=True)
class HelpfulnessAggregate:
    target_kind: str
    target_id: str
    signal_count: int
    positive_count: int
    negative_count: int
    helpfulness_score: float


class _Accumulator:
    __slots__ = ("total", "positive", "negative")

    def __init__(self) -> None:
        self.total = 0
        self.positive = 0
        self.negative = 0


def aggregate_helpfulness(
    db_path: Path,
    *,
    target_kind: Literal["file", "section"] | None = None,
) -> list[HelpfulnessAggregate]:
    if not db_path.is_file():
        return []

    try:
        with connect_review_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM learning_signals
                WHERE signal_type = 'helpfulness'
                ORDER BY created_at ASC
                """
            ).fetchall()
    except sqlite3.OperationalError:
        return []

    buckets: dict[tuple[str, str], _Accumulator] = {}
    for row in rows:
        payload = _safe_parse_payload(row[0])
        if payload is None:
            continue

        kind = payload.get("target_kind", "file")
        if not isinstance(kind, str):
            continue
        if target_kind is not None and kind != target_kind:
            continue

        tid = payload.get("target_id", "")
        if not isinstance(tid, str) or not tid:
            continue

        positive = _extract_positive(payload.get("payload"))

        key = (kind, tid)
        acc = buckets.get(key)
        if acc is None:
            acc = _Accumulator()
            buckets[key] = acc
        if positive is True:
            acc.total += 1
            acc.positive += 1
        elif positive is False:
            acc.total += 1
            acc.negative += 1

    results: list[HelpfulnessAggregate] = []
    for (kind, tid), acc in sorted(buckets.items()):
        if acc.total == 0:
            continue
        score = acc.positive / acc.total
        results.append(
            HelpfulnessAggregate(
                target_kind=kind,
                target_id=tid,
                signal_count=acc.total,
                positive_count=acc.positive,
                negative_count=acc.negative,
                helpfulness_score=round(score, 4),
            )
        )
    return results


def _safe_parse_payload(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = safe_json_loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return cast("dict[str, object]", parsed)


def _extract_positive(payload: object) -> bool | None:
    if not isinstance(payload, dict):
        return None
    inner = cast("dict[str, object]", payload)
    helpful = inner.get("helpful")
    if isinstance(helpful, bool):
        return helpful
    return None


__all__ = ["HelpfulnessAggregate", "aggregate_helpfulness"]
