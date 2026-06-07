"""Tests for /api/stats, /api/review/heatmap, /api/export/results,
/api/providers, and /api/serve/status endpoints."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path

import ahadiff.serve.routes_runs as routes_runs_module
import ahadiff.serve.routes_stats as routes_stats_module
from ahadiff.contracts.serve_stats import (
    HeatmapEntry,
    HelpfulnessAggregateDTO,
    LearningEffectivenessResponse,
    ProvidersResponse,
    ServeStatusResponse,
    StatsResponse,
    TransferConceptDTO,
    UsageModelSummary,
    UsageResponse,
)
from ahadiff.review.database import count_concepts, initialize_review_db, upsert_concept
from ahadiff.serve import ServeState, create_app


def _client(
    state_dir: Path,
    *,
    token: str = "test-token",
    locale: Literal["en", "zh-CN"] = "en",
    started_at: float = 0.0,
) -> TestClient:
    app = create_app(
        ServeState(state_dir=state_dir, token=token, locale=locale, started_at=started_at)
    )
    return TestClient(app, base_url="http://localhost:8765")


_AUTH = {"X-AhaDiff-Token": "test-token"}


# ---------------------------------------------------------------------------
# Helper: seed a minimal review.sqlite
# ---------------------------------------------------------------------------


def _seed_review_db(db_path: Path, *, reviews: int = 0, events: int = 0) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            reviewed_at_utc TEXT NOT NULL,
            elapsed_days REAL NOT NULL,
            scheduled_days REAL NOT NULL,
            state TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS result_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            base_ref TEXT,
            prompt_version TEXT NOT NULL,
            eval_bundle_version TEXT NOT NULL,
            rubric_version TEXT,
            overall REAL NOT NULL,
            verdict TEXT NOT NULL,
            status TEXT NOT NULL,
            weakest_dim TEXT NOT NULL,
            note_json TEXT
        )
        """
    )
    for i in range(reviews):
        conn.execute(
            """
            INSERT INTO review_logs (card_id, rating, reviewed_at_utc,
                                     elapsed_days, scheduled_days, state)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (f"card_{i}", 3, f"2026-04-{10 + (i % 20):02d}T12:00:00Z", 1.0, 1.0, "review"),
        )
    for i in range(events):
        conn.execute(
            """
            INSERT INTO result_events (event_id, run_id, event_type, timestamp,
                                       source_ref, base_ref, prompt_version,
                                       eval_bundle_version, rubric_version,
                                       overall, verdict, status, weakest_dim,
                                       note_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"evt_{i}",
                f"run_{i:032x}",
                "score",
                f"2026-04-{10 + (i % 20):02d}T12:00:00Z",
                "abc123",
                "def456",
                "v1",
                "v1",
                "v1",
                75.0 + i,
                "pass",
                "keep_final",
                "accuracy" if i % 2 == 0 else "evidence",
                None,
            ),
        )
    conn.commit()
    conn.close()


def _sqlite_artifact_hashes(db_path: Path) -> dict[str, str]:
    suffixes = ("", "-wal", "-shm", "-journal")
    hashes: dict[str, str] = {}
    for suffix in suffixes:
        path = db_path.with_name(db_path.name + suffix)
        if path.exists():
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


# ---------------------------------------------------------------------------
# /api/stats
# ---------------------------------------------------------------------------


def _valid_stats_payload() -> dict[str, object]:
    return {
        "total_runs": 1,
        "total_lessons": 1,
        "total_quizzes": 1,
        "total_concepts": 2,
        "total_claims": 3,
        "total_reviews": 4,
        "avg_overall_score": 82.5,
        "weakest_dimensions": ["evidence"],
        "last_run_at": "2026-04-10T12:00:00Z",
    }


def test_stats_response_contract_rejects_extra_negative_and_non_finite_values() -> None:
    assert (
        StatsResponse.model_validate(
            {**_valid_stats_payload(), "avg_overall_score": None}
        ).avg_overall_score
        is None
    )

    for patch in (
        {"total_runs": -1},
        {"total_runs": True},
        {"total_runs": "1"},
        {"avg_overall_score": float("nan")},
        {"avg_overall_score": float("inf")},
        {"avg_overall_score": True},
        {"avg_overall_score": "82.5"},
        {"unexpected": True},
    ):
        with pytest.raises(ValidationError):
            StatsResponse.model_validate({**_valid_stats_payload(), **patch})


def test_stats_related_contracts_reject_negative_counts_and_non_finite_floats() -> None:
    with pytest.raises(ValidationError):
        HeatmapEntry.model_validate({"date": "2026-04-10", "review_count": -1, "avg_rating": 3.0})
    with pytest.raises(ValidationError):
        HeatmapEntry.model_validate(
            {"date": "2026-04-10", "review_count": 1, "avg_rating": float("inf")}
        )
    with pytest.raises(ValidationError):
        UsageModelSummary.model_validate(
            {
                "provider_class": "openai",
                "model_id": "gpt",
                "call_count": 1,
                "total_input_tokens": 1,
                "total_output_tokens": 1,
                "total_cost_usd": float("nan"),
            }
        )
    with pytest.raises(ValidationError):
        UsageResponse.model_validate(
            {
                "models": [],
                "total_calls": -1,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_usd": 0.0,
                "cache_hits": 0,
                "cache_misses": 0,
            }
        )
    with pytest.raises(ValidationError):
        ServeStatusResponse.model_validate(
            {
                "version": "0.1.0",
                "uptime_seconds": float("inf"),
                "review_db_exists": False,
                "runs_count": 0,
            }
        )
    with pytest.raises(ValidationError):
        HelpfulnessAggregateDTO.model_validate(
            {
                "target_kind": "section",
                "target_id": "s1",
                "signal_count": 1,
                "positive_count": 1,
                "negative_count": 0,
                "helpfulness_score": float("nan"),
            }
        )
    with pytest.raises(ValidationError):
        TransferConceptDTO.model_validate(
            {"concept": "dto", "total_reviews": -1, "avg_rating": 3.0, "improving": True}
        )
    with pytest.raises(ValidationError):
        LearningEffectivenessResponse.model_validate(
            {
                "total_concepts_reviewed": 0,
                "concepts_improving": 0,
                "concepts_stable": 0,
                "concepts_declining": 0,
                "transfer_rate": float("nan"),
                "helpfulness": [],
                "transfer_metrics": [],
            }
        )


class TestGetStats:
    def test_happy_path_empty(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/stats", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_runs"] == 0
        assert body["total_lessons"] == 0
        assert body["total_quizzes"] == 0
        assert body["total_concepts"] == 0
        assert body["total_claims"] == 0
        assert body["total_reviews"] == 0
        assert body["avg_overall_score"] is None
        assert body["weakest_dimensions"] == []
        assert body["last_run_at"] is None

    def test_happy_path_with_data(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()

        # Create runs with artifacts
        runs_dir = state_dir / "runs"
        runs_dir.mkdir()
        run1 = runs_dir / "run_00000000000000000000000000000001"
        run1.mkdir()
        (run1 / "finalized.json").write_text("{}", encoding="utf-8")
        (run1 / "lesson").mkdir()
        (run1 / "lesson" / "lesson.full.md").write_text("lesson")
        (run1 / "quiz").mkdir()
        (run1 / "quiz" / "quiz.jsonl").write_text("{}")
        (run1 / "claims.jsonl").write_text("{}")

        # concepts
        (state_dir / "concepts.jsonl").write_text('{"id":"c1"}\n{"id":"c2"}\n')

        # review db
        _seed_review_db(state_dir / "review.sqlite", reviews=5, events=3)

        client = _client(state_dir)
        resp = client.get("/api/stats", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_runs"] == 1
        assert body["total_lessons"] == 1
        assert body["total_quizzes"] == 1
        assert body["total_claims"] == 1
        assert body["total_concepts"] == 2
        assert body["total_reviews"] == 5
        assert body["avg_overall_score"] is not None
        assert isinstance(body["weakest_dimensions"], list)
        assert body["last_run_at"] is not None

    def test_stats_exclude_improve_run_events_from_source_diff_score_aggregates(
        self,
        tmp_path: Path,
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        db_path = state_dir / "review.sqlite"
        initialize_review_db(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                """
                INSERT INTO result_events (event_id, run_id, event_type, timestamp,
                                           source_ref, base_ref, prompt_version,
                                           eval_bundle_version, rubric_version,
                                           overall, verdict, status, weakest_dim,
                                           note_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "evt_baseline",
                        "run_" + "1" * 32,
                        "learn",
                        "2026-04-10T12:00:00Z",
                        "abc123",
                        "def456",
                        "v1",
                        "v1",
                        "v1",
                        80.0,
                        "PASS",
                        "baseline",
                        "accuracy",
                        None,
                    ),
                    (
                        "evt_improve",
                        "run_" + "2" * 32,
                        "improve_run",
                        "2026-04-11T12:00:00Z",
                        "abc123",
                        "def456",
                        "v1",
                        "v1",
                        "v1",
                        100.0,
                        "PASS",
                        "keep",
                        "evidence",
                        None,
                    ),
                ],
            )

        client = _client(state_dir)
        resp = client.get("/api/stats", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["avg_overall_score"] == 80.0
        assert body["weakest_dimensions"] == ["accuracy"]
        assert body["last_run_at"] == "2026-04-10T12:00:00Z"

    def test_stats_exclude_improve_run_directories_from_artifact_counts(
        self,
        tmp_path: Path,
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        db_path = state_dir / "review.sqlite"
        initialize_review_db(db_path)
        runs_dir = state_dir / "runs"
        runs_dir.mkdir()
        run_ids = {
            "learn": "run_" + "1" * 32,
            "improve": "run_" + "2" * 32,
        }
        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                """
                INSERT INTO result_events (event_id, run_id, event_type, timestamp,
                                           source_ref, base_ref, prompt_version,
                                           eval_bundle_version, rubric_version,
                                           overall, verdict, status, weakest_dim,
                                           note_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "evt_learn_artifacts",
                        run_ids["learn"],
                        "learn",
                        "2026-04-10T12:00:00Z",
                        "abc123",
                        "def456",
                        "v1",
                        "v1",
                        "v1",
                        80.0,
                        "PASS",
                        "baseline",
                        "accuracy",
                        None,
                    ),
                    (
                        "evt_improve_artifacts",
                        run_ids["improve"],
                        "improve_run",
                        "2026-04-11T12:00:00Z",
                        "abc123",
                        "def456",
                        "v1",
                        "v1",
                        "v1",
                        100.0,
                        "PASS",
                        "keep",
                        "evidence",
                        None,
                    ),
                ],
            )
        for label, run_id in run_ids.items():
            run_dir = runs_dir / run_id
            run_dir.mkdir()
            event_id = "evt_learn_artifacts" if label == "learn" else "evt_improve_artifacts"
            (run_dir / "finalized.json").write_text(
                json.dumps({"run_id": run_id, "event_id": event_id}),
                encoding="utf-8",
            )
            lesson_dir = run_dir / "lesson"
            lesson_dir.mkdir()
            (lesson_dir / "lesson.full.md").write_text("lesson", encoding="utf-8")
            quiz_dir = run_dir / "quiz"
            quiz_dir.mkdir()
            (quiz_dir / "quiz.jsonl").write_text("{}\n", encoding="utf-8")
            (run_dir / "claims.jsonl").write_text("{}\n", encoding="utf-8")

        client = _client(state_dir)
        resp = client.get("/api/stats", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_runs"] == 1
        assert body["total_lessons"] == 1
        assert body["total_quizzes"] == 1
        assert body["total_claims"] == 1

    def test_spec_alignment_excludes_improve_run_events(
        self,
        tmp_path: Path,
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        db_path = state_dir / "review.sqlite"
        initialize_review_db(db_path)
        runs_dir = state_dir / "runs"
        runs_dir.mkdir()
        rows = [
            (
                "evt_learn_spec",
                "run_" + "1" * 32,
                "learn",
                "2026-04-10T12:00:00Z",
                8.0,
            ),
            (
                "evt_improve_spec",
                "run_" + "2" * 32,
                "improve_run",
                "2026-04-11T12:00:00Z",
                2.0,
            ),
        ]
        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                """
                INSERT INTO result_events (event_id, run_id, event_type, timestamp,
                                           source_ref, base_ref, prompt_version,
                                           eval_bundle_version, rubric_version,
                                           overall, verdict, status, weakest_dim,
                                           note_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        event_id,
                        run_id,
                        event_type,
                        timestamp,
                        "abc123",
                        "def456",
                        "v1",
                        "v1",
                        "v1",
                        80.0,
                        "PASS",
                        "keep",
                        "accuracy",
                        None,
                    )
                    for event_id, run_id, event_type, timestamp, _score in rows
                ],
            )
        for event_id, run_id, _event_type, _timestamp, score in rows:
            run_dir = runs_dir / run_id
            run_dir.mkdir()
            (run_dir / "finalized.json").write_text(
                json.dumps({"run_id": run_id, "event_id": event_id}),
                encoding="utf-8",
            )
            (run_dir / "spec_alignment.json").write_text(
                json.dumps(
                    {
                        "artifact": "spec_alignment",
                        "schema": "ahadiff.spec_alignment",
                        "schema_version": 1,
                        "score": score,
                        "summary": {
                            "implemented": 1 if score > 5 else 0,
                            "partial": 0,
                            "missing": 0 if score > 5 else 1,
                            "unknown": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )

        client = _client(state_dir)
        resp = client.get("/api/spec/alignment", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_evaluated"] == 1
        assert body["alignment_score"] == 8.0
        assert body["implemented"] == 1
        assert body["missing"] == 0

    def test_total_concepts_uses_sqlite_and_falls_back_to_jsonl_when_stale(
        self,
        tmp_path: Path,
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        db_path = state_dir / "review.sqlite"
        initialize_review_db(db_path)
        upsert_concept(
            db_path,
            term_key="db-only",
            concept="db only",
            run_id="run_db",
            source_ref="abc123",
            branch_hint="main",
            related_claims=(),
            file_refs=(),
        )
        (state_dir / "concepts.jsonl").write_text(
            '{"term_key":"jsonl-1","concept":"jsonl 1"}\n'
            '{"term_key":"jsonl-2","concept":"jsonl 2"}\n',
            encoding="utf-8",
        )

        client = _client(state_dir)
        resp = client.get("/api/stats", headers=_AUTH)

        assert resp.status_code == 200
        assert resp.json()["total_concepts"] == 2

    def test_empty_sqlite_without_review_tables_returns_zero_stats(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        sqlite3.connect(state_dir / "review.sqlite").close()
        client = _client(state_dir)

        resp = client.get("/api/stats", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_reviews"] == 0
        assert body["avg_overall_score"] is None
        assert body["weakest_dimensions"] == []

    def test_stats_returns_500_on_unexpected_review_db_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        (state_dir / "review.sqlite").write_text("placeholder", encoding="utf-8")

        def fail_connect(*_args: object, **_kwargs: object) -> object:
            raise sqlite3.OperationalError("disk I/O error")

        def _zero_concepts(*_a: object, **_kw: object) -> int:
            return 0

        monkeypatch.setattr(routes_stats_module, "_count_concepts", _zero_concepts)
        monkeypatch.setattr(routes_stats_module, "connect_review_db", fail_connect)
        client = _client(state_dir)

        resp = client.get("/api/stats", headers=_AUTH)

        assert resp.status_code == 500
        assert resp.json()["error_code"] == "STORAGE_REVIEW_DB"
        assert resp.json()["error"] == "review_database_unavailable"

    def test_stats_ignores_unfinalized_run_directories(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        runs_dir = state_dir / "runs"
        runs_dir.mkdir()

        finalized_run = runs_dir / "run_00000000000000000000000000000001"
        finalized_run.mkdir()
        (finalized_run / "finalized.json").write_text("{}", encoding="utf-8")
        (finalized_run / "quiz").mkdir()
        (finalized_run / "quiz" / "quiz.jsonl").write_text("{}")

        pending_run = runs_dir / "run_00000000000000000000000000000002"
        pending_run.mkdir()
        (pending_run / "quiz").mkdir()
        (pending_run / "quiz" / "quiz.jsonl").write_text("{}")

        client = _client(state_dir)
        resp = client.get("/api/stats", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_runs"] == 1
        assert body["total_quizzes"] == 1

    def test_auth_required(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/stats")

        assert resp.status_code == 401

    def test_wrong_token(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/stats", headers={"X-AhaDiff-Token": "wrong"})

        assert resp.status_code == 401

    def test_uses_anyio_threadpool(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        calls: list[str] = []

        async def recording_run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
            del kwargs
            calls.append(getattr(func, "__name__", repr(func)))
            return func(*args)

        monkeypatch.setattr(routes_stats_module.to_thread, "run_sync", recording_run_sync)
        client = _client(state_dir)
        client.get("/api/stats", headers=_AUTH)

        assert "_build_stats" in calls


# ---------------------------------------------------------------------------
# /api/review/heatmap
# ---------------------------------------------------------------------------


class TestGetReviewHeatmap:
    def test_happy_path_empty(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/review/heatmap", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert "entries" in body
        assert body["entries"] == []

    def test_happy_path_with_data(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        _seed_review_db(state_dir / "review.sqlite", reviews=10)

        client = _client(state_dir)
        resp = client.get("/api/review/heatmap", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["entries"], list)
        assert len(body["entries"]) > 0
        entry = body["entries"][0]
        assert "date" in entry
        assert "review_count" in entry
        assert "avg_rating" in entry

    def test_empty_sqlite_without_review_logs_returns_empty_entries(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        sqlite3.connect(state_dir / "review.sqlite").close()
        client = _client(state_dir)

        resp = client.get("/api/review/heatmap", headers=_AUTH)

        assert resp.status_code == 200
        assert resp.json()["entries"] == []

    def test_review_heatmap_returns_500_on_unexpected_db_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        (state_dir / "review.sqlite").write_text("placeholder", encoding="utf-8")

        def fail_connect(*_args: object, **_kwargs: object) -> object:
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(routes_stats_module, "connect_review_db", fail_connect)
        client = _client(state_dir)

        resp = client.get("/api/review/heatmap", headers=_AUTH)

        assert resp.status_code == 500
        assert resp.json()["error_code"] == "STORAGE_REVIEW_DB"
        assert resp.json()["error"] == "review_database_unavailable"

    def test_date_range_params(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        _seed_review_db(state_dir / "review.sqlite", reviews=10)

        client = _client(state_dir)
        resp = client.get(
            "/api/review/heatmap?from=2026-04-10&to=2026-04-15",
            headers=_AUTH,
        )

        assert resp.status_code == 200
        body = resp.json()
        for entry in body["entries"]:
            assert "2026-04-10" <= entry["date"] <= "2026-04-15"

    def test_invalid_date_uses_defaults(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get(
            "/api/review/heatmap?from=bad-date&to=also-bad",
            headers=_AUTH,
        )

        assert resp.status_code == 200

    def test_auth_required(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/review/heatmap")

        assert resp.status_code == 401

    def test_max_span_clamped(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        # Span > 730 days should be clamped
        resp = client.get(
            "/api/review/heatmap?from=2020-01-01&to=2026-04-28",
            headers=_AUTH,
        )

        assert resp.status_code == 200

    def test_reversed_large_span_is_still_clamped_to_730_days(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        db_path = state_dir / "review.sqlite"
        _seed_review_db(db_path)
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                INSERT INTO review_logs (
                    card_id,
                    rating,
                    reviewed_at_utc,
                    elapsed_days,
                    scheduled_days,
                    state
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("old-card", 3, "2023-01-01T12:00:00Z", 1.0, 1.0, "review"),
            )
            conn.execute(
                """
                INSERT INTO review_logs (
                    card_id,
                    rating,
                    reviewed_at_utc,
                    elapsed_days,
                    scheduled_days,
                    state
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("recent-card", 3, "2025-01-01T12:00:00Z", 1.0, 1.0, "review"),
            )
            conn.commit()

        client = _client(state_dir)
        resp = client.get(
            "/api/review/heatmap?from=2026-04-28&to=2020-01-01",
            headers=_AUTH,
        )

        assert resp.status_code == 200
        dates = [entry["date"] for entry in resp.json()["entries"]]
        assert "2023-01-01" not in dates
        assert "2025-01-01" in dates


# ---------------------------------------------------------------------------
# /api/export/results
# ---------------------------------------------------------------------------


class TestGetExportResults:
    def test_happy_path(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        _seed_review_db(state_dir / "review.sqlite", events=3)

        client = _client(state_dir)
        resp = client.get("/api/export/results", headers=_AUTH)

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/tab-separated-values")
        lines = resp.text.strip().split("\n")
        assert len(lines) == 4  # header + 3 rows
        header = lines[0].split("\t")
        assert "run_id" in header
        assert "overall" in header

    def test_tsv_content_disposition(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        _seed_review_db(state_dir / "review.sqlite", events=1)

        client = _client(state_dir)
        resp = client.get("/api/export/results", headers=_AUTH)

        assert "results.tsv" in resp.headers.get("content-disposition", "")

    def test_auth_required(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        _seed_review_db(state_dir / "review.sqlite", events=1)

        client = _client(state_dir)
        resp = client.get("/api/export/results")

        assert resp.status_code == 401

    def test_empty_db_returns_header_only(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        _seed_review_db(state_dir / "review.sqlite", events=0)

        client = _client(state_dir)
        resp = client.get("/api/export/results", headers=_AUTH)

        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        assert len(lines) == 1  # header only

    def test_truly_empty_sqlite_returns_header_only(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        sqlite3.connect(state_dir / "review.sqlite").close()

        client = _client(state_dir)
        resp = client.get("/api/export/results", headers=_AUTH)

        assert resp.status_code == 200
        assert resp.text == (
            "timestamp\trun_id\tsource_ref\tbase_ref\tprompt_version\trubric_version\t"
            "overall\tverdict\tstatus\tweakest_dim\tnote_json\n"
        )

    def test_json_export_format(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        _seed_review_db(state_dir / "review.sqlite", events=2)
        client = _client(state_dir)

        resp = client.get("/api/export/results?format=json", headers=_AUTH)

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert "results.json" in resp.headers.get("content-disposition", "")
        data = resp.json()
        assert data["format"] == "json"
        assert len(data["results"]) == 2
        assert data["results"][0]["run_id"].startswith("run_")
        assert "overall" in data["results"][0]

    def test_json_export_empty_sqlite_returns_empty_results(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        sqlite3.connect(state_dir / "review.sqlite").close()
        client = _client(state_dir)

        resp = client.get("/api/export/results?format=json", headers=_AUTH)

        assert resp.status_code == 200
        assert resp.json() == {"format": "json", "results": []}

    def test_rejects_unknown_export_format(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/export/results?format=csv", headers=_AUTH)

        assert resp.status_code == 400
        assert resp.json()["error_code"] == "EXPORT_FORMAT_UNSUPPORTED"
        assert resp.json()["status"] == 400
        assert "export format must be 'tsv' or 'json'" in resp.json()["error"]

    def test_export_results_does_not_write_review_sqlite(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        db_path = state_dir / "review.sqlite"
        _seed_review_db(db_path, events=2)
        before = _sqlite_artifact_hashes(db_path)

        client = _client(state_dir)
        resp = client.get("/api/export/results", headers=_AUTH)

        assert resp.status_code == 200
        assert _sqlite_artifact_hashes(db_path) == before

    def test_formula_injection_escaped(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        db = state_dir / "review.sqlite"
        initialize_review_db(db)
        from ahadiff.review.database import connect_review_db

        with connect_review_db(db) as conn:
            conn.execute(
                """
                INSERT INTO result_events (event_id, run_id, event_type, timestamp,
                    source_ref, base_ref, prompt_version, eval_bundle_version,
                    rubric_version, overall, verdict, status, weakest_dim, note_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "evt_inject",
                    "run_" + "a" * 32,
                    "score",
                    "2026-04-28T12:00:00Z",
                    "abc123",
                    "def456",
                    "v1",
                    "v1",
                    "v1",
                    80.0,
                    "pass",
                    "finalized",
                    "accuracy",
                    '=CMD("calc")',
                ),
            )

        client = _client(state_dir)
        resp = client.get("/api/export/results", headers=_AUTH)

        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        for line in lines[1:]:
            cells = line.split("\t")
            for cell in cells:
                assert not cell.startswith("="), f"formula injection not escaped: {cell}"
                assert not cell.startswith("+"), f"formula injection not escaped: {cell}"


# ---------------------------------------------------------------------------
# /api/concepts
# ---------------------------------------------------------------------------


class TestGetConcepts:
    def test_uses_visible_concepts_without_writing_sqlite(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        db_path = state_dir / "review.sqlite"
        initialize_review_db(db_path)
        concepts_jsonl = state_dir / "concepts.jsonl"
        concepts_jsonl.write_text(
            '{"term_key":"jsonl-only","concept":"jsonl only","source_refs":["abc123"]}\n',
            encoding="utf-8",
        )
        (state_dir.parent / ".git").write_text("gitdir: test\n", encoding="utf-8")

        def fake_visible_concepts(
            *,
            workspace_root: Path,
            head_ref: str = "HEAD",
        ) -> tuple[dict[str, object], ...]:
            assert workspace_root == state_dir.parent
            assert head_ref == "HEAD"
            return (
                {
                    "term_key": "visible-only",
                    "concept": "visible only",
                    "source_refs": ["abc123"],
                },
            )

        monkeypatch.setattr(routes_runs_module, "load_visible_concepts", fake_visible_concepts)
        client = _client(state_dir)
        resp = client.get("/api/concepts")

        assert resp.status_code == 200
        lines = resp.json()["content"].splitlines()
        assert [json.loads(line)["term_key"] for line in lines] == ["visible-only"]
        assert count_concepts(db_path) == 0

    def test_jsonl_fallback_rejects_non_integer_cursor(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        (state_dir / "concepts.jsonl").write_text(
            '{"term_key":"term-1","concept":"term 1"}\n',
            encoding="utf-8",
        )

        client = _client(state_dir)
        resp = client.get("/api/concepts?cursor=not-an-int")

        assert resp.status_code == 400
        assert "must be an integer" in resp.json()["error"]


# ---------------------------------------------------------------------------
# /api/providers
# ---------------------------------------------------------------------------


class TestGetProviders:
    def test_happy_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()

        from dataclasses import dataclass

        @dataclass
        class _FakeConfig:
            values: dict[str, object]
            resolved: dict[str, object]
            repo_config_path: Path
            global_config_path: Path
            repo_unknown_keys: tuple[str, ...] = ()
            global_unknown_keys: tuple[str, ...] = ()
            repo_sensitive_keys: tuple[str, ...] = ()
            precedence_conflicts: tuple[object, ...] = ()

        def _mock_load_config(*_a: Any, **_kw: Any) -> _FakeConfig:
            return _FakeConfig(
                values={
                    "llm": {
                        "generate_model": "gpt-5.4-mini",
                        "judge_model": "gpt-5.4",
                    },
                    "providers": {
                        "gen": {
                            "provider_class": "openai",
                            "model_name": "gpt-5.4-mini",
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "OPENAI_API_KEY",
                        },
                        "judge": {
                            "provider_class": "openai",
                            "model_name": "gpt-5.4",
                            "base_url": "https://api.example.com/v1",
                            "api_key_env": "OPENAI_API_KEY",
                        },
                    },
                },
                resolved={},
                repo_config_path=state_dir / "config.toml",
                global_config_path=state_dir / "global-config.toml",
            )

        monkeypatch.setattr(
            "ahadiff.serve.routes_stats.routes_stats_module"
            if False
            else "ahadiff.core.config.load_config",
            _mock_load_config,
        )

        client = _client(state_dir)
        resp = client.get("/api/providers", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert "providers" in body
        providers = cast("list[dict[str, object]]", body["providers"])
        ProvidersResponse.model_validate(body)
        assert isinstance(providers, list)
        assert len(providers) == 2
        names = {p["model_name"] for p in providers}
        assert "gpt-5.4-mini" in names
        assert "gpt-5.4" in names

    def test_no_config_returns_empty(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()

        client = _client(state_dir)
        resp = client.get("/api/providers", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert "providers" in body
        # May be empty if no config.toml exists

    def test_reads_configured_provider_aliases(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()

        from dataclasses import dataclass

        @dataclass
        class _FakeConfig:
            values: dict[str, object]
            resolved: dict[str, object]
            repo_config_path: Path
            global_config_path: Path
            repo_unknown_keys: tuple[str, ...] = ()
            global_unknown_keys: tuple[str, ...] = ()
            repo_sensitive_keys: tuple[str, ...] = ()
            precedence_conflicts: tuple[object, ...] = ()

        def _mock_load_config(*_a: Any, **_kw: Any) -> _FakeConfig:
            return _FakeConfig(
                values={
                    "providers": {
                        "demo": {
                            "provider_class": "openai",
                            "model_name": "gpt-5.4-mini",
                            "base_url": "https://demo.example.com/v1",
                            "api_key_env": "AHADIFF_DEMO_KEY",
                            "probed_max_context": 200000,
                            "probed_tpm": 1000,
                            "probed_rpm": 60,
                            "probe_timestamp": "2026-04-28T00:00:00Z",
                        },
                        "judge": {
                            "provider_class": "anthropic",
                            "model_name": "claude-sonnet-4-6",
                            "base_url": "https://judge.example.com/v1",
                            "api_key_env": "AHADIFF_JUDGE_KEY",
                        },
                    }
                },
                resolved={},
                repo_config_path=state_dir / "config.toml",
                global_config_path=state_dir / "global-config.toml",
            )

        monkeypatch.setattr("ahadiff.core.config.load_config", _mock_load_config)
        monkeypatch.setenv("AHADIFF_DEMO_KEY", "secret")
        monkeypatch.delenv("AHADIFF_JUDGE_KEY", raising=False)
        client = _client(state_dir)

        resp = client.get("/api/providers", headers=_AUTH)

        assert resp.status_code == 200
        providers = cast("list[dict[str, object]]", resp.json()["providers"])
        assert len(providers) == 2
        assert providers[0]["alias"] == "demo"
        assert providers[0]["provider_class"] == "openai"
        assert providers[0]["provider_kind"] == "openai"
        assert providers[0]["api_family"] == "openai"
        assert providers[0]["key_status"] == "configured"
        assert providers[0]["model_name"] == "gpt-5.4-mini"
        assert providers[0]["probed"] is True
        assert providers[0]["probed_max_context"] == 200000
        assert providers[0]["probed_tpm"] == 1000
        assert providers[0]["probed_rpm"] == 60
        assert providers[1]["provider_class"] == "anthropic"
        assert providers[1]["key_status"] == "missing"
        assert providers[1]["probed"] is False

    def test_auth_required(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/providers")

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /api/serve/status
# ---------------------------------------------------------------------------


class TestGetServeStatus:
    def test_no_auth_needed(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/serve/status")

        assert resp.status_code == 200

    def test_returns_version(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/serve/status")

        body = resp.json()
        assert "version" in body
        from ahadiff import __version__

        assert body["version"] == __version__

    def test_returns_uptime(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/serve/status")

        body = resp.json()
        assert "uptime_seconds" in body
        assert isinstance(body["uptime_seconds"], int | float)
        assert body["uptime_seconds"] >= 0

    def test_uptime_uses_state_started_at(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        monkeypatch.setattr(routes_stats_module.time, "monotonic", lambda: 150.0)
        client = _client(state_dir, started_at=100.0)

        resp = client.get("/api/serve/status")

        assert resp.status_code == 200
        assert resp.json()["uptime_seconds"] == 50.0

    def test_does_not_expose_repo_path(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/serve/status")

        body = resp.json()
        assert "repo_path" not in body

    def test_review_db_exists_false(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        client = _client(state_dir)

        resp = client.get("/api/serve/status")

        body = resp.json()
        assert body["review_db_exists"] is False

    def test_review_db_exists_true(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        _seed_review_db(state_dir / "review.sqlite")

        client = _client(state_dir)
        resp = client.get("/api/serve/status")

        body = resp.json()
        assert body["review_db_exists"] is True

    def test_runs_count(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        runs_dir = state_dir / "runs"
        runs_dir.mkdir()
        finalized_1 = runs_dir / "run_00000000000000000000000000000001"
        finalized_1.mkdir()
        (finalized_1 / "finalized.json").write_text("{}", encoding="utf-8")
        finalized_2 = runs_dir / "run_00000000000000000000000000000002"
        finalized_2.mkdir()
        (finalized_2 / "finalized.json").write_text("{}", encoding="utf-8")
        (runs_dir / "run_00000000000000000000000000000003").mkdir()

        client = _client(state_dir)
        resp = client.get("/api/serve/status")

        body = resp.json()
        assert body["runs_count"] == 2

    def test_uses_anyio_threadpool(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir()
        calls: list[str] = []

        async def recording_run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
            del kwargs
            calls.append(getattr(func, "__name__", repr(func)))
            return func(*args)

        monkeypatch.setattr(routes_stats_module.to_thread, "run_sync", recording_run_sync)
        client = _client(state_dir)
        client.get("/api/serve/status")

        assert "_build_serve_status" in calls
