#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"

if SRC_DIR.is_dir():
    sys.path.insert(0, str(SRC_DIR))


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _measure(operation: Any, *, iterations: int) -> dict[str, Any]:
    samples_ms: list[float] = []
    last_result_count = 0

    operation()
    for _ in range(iterations):
        started = time.perf_counter()
        result = operation()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        last_result_count = len(result)
        samples_ms.append(elapsed_ms)

    return {
        "iterations": iterations,
        "mean_ms": round(statistics.fmean(samples_ms), 3),
        "min_ms": round(min(samples_ms), 3),
        "p50_ms": round(_percentile(samples_ms, 0.50), 3),
        "p95_ms": round(_percentile(samples_ms, 0.95), 3),
        "result_count": last_result_count,
    }


def main() -> dict[str, Any]:
    try:
        from ahadiff.contracts import ResultEvent, ReviewCard
        from ahadiff.review.database import (
            import_cards_from_jsonl,
            initialize_review_db,
            list_due_cards,
            load_finalized_ratchet_history_page,
            load_result_events_page,
            sync_result_event,
        )
    except Exception as exc:
        return {
            "benchmark": "sqlite_queries",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "status": "skipped",
        }

    with tempfile.TemporaryDirectory(prefix="ahadiff-sqlite-bench-") as temp_dir:
        temp_root = Path(temp_dir)
        db_path = temp_root / "review.sqlite"
        cards_path = temp_root / "cards.jsonl"
        initialize_review_db(db_path)

        card_count = 500
        cards = [
            ReviewCard(
                card_id=f"card-{index:04d}",
                concept=f"concept-{index % 25}",
                run_id=f"run-{index % 20:02d}",
                source_ref=f"source-{index % 10:02d}",
                fsrs_state="{}",
                file_id=f"file-{index % 15:02d}",
                display_path=f"src/module_{index % 15:02d}.py",
                hunk_id=f"hunk-{index:04d}",
                hunk_hash=f"hash-{index:04d}",
                symbol=f"symbol_{index % 40:02d}",
            )
            for index in range(card_count)
        ]
        cards_path.write_text(
            "".join(json.dumps(card.model_dump(mode="json")) + "\n" for card in cards),
            encoding="utf-8",
        )
        inserted_cards = import_cards_from_jsonl(db_path, cards_path)

        event_count = 1000
        ratchet_statuses = ("baseline", "keep", "keep_final")
        finalized_event_ids: list[str] = []
        for index in range(event_count):
            status = ratchet_statuses[index % len(ratchet_statuses)]
            event_id = f"018f0f52-91c0-7abc-8123-{index:012d}"
            finalized_event_ids.append(event_id)
            event = ResultEvent(
                event_id=event_id,
                run_id=f"run-{index % 50:02d}",
                event_type="learn",
                timestamp=f"2026-04-24T00:{index % 60:02d}:{index % 60:02d}Z",
                source_ref=f"source-{index % 10:02d}",
                base_ref=None,
                prompt_version="prompt123",
                eval_bundle_version="eval123",
                rubric_version="rubric-v1",
                overall=70.0 + float(index % 25),
                verdict="PASS",
                status=status,
                weakest_dim="evidence",
                note_json=None,
            )
            sync_result_event(db_path, event)

        now_utc = datetime.now(UTC) + timedelta(days=365)
        operations = {
            "list_due_cards": _measure(
                lambda: list_due_cards(db_path, now_utc=now_utc, limit=100),
                iterations=100,
            ),
            "load_result_events_page": _measure(
                lambda: load_result_events_page(db_path, limit=100),
                iterations=100,
            ),
            "load_finalized_ratchet_history_page": _measure(
                lambda: load_finalized_ratchet_history_page(
                    db_path,
                    finalized_event_ids=finalized_event_ids,
                    statuses=ratchet_statuses,
                    limit=100,
                ),
                iterations=100,
            ),
        }

    return {
        "benchmark": "sqlite_queries",
        "operations": operations,
        "seed": {
            "cards_inserted": inserted_cards,
            "events_inserted": event_count,
        },
        "status": "ok",
        "working_directory": str(REPO_ROOT),
    }


if __name__ == "__main__":
    try:
        _emit(main())
    except Exception as exc:  # pragma: no cover - defensive JSON fallback
        _emit(
            {
                "benchmark": "sqlite_queries",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "status": "error",
            }
        )
