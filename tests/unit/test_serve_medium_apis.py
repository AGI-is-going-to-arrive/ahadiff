from __future__ import annotations

import json
import os
import sqlite3
from typing import TYPE_CHECKING, Literal

import pytest
from starlette.testclient import TestClient

from ahadiff.contracts.serve_runtime import SearchResponse
from ahadiff.core.paths import (
    path_identity_key as _legacy_path_identity_key,
)
from ahadiff.core.paths import (
    workspace_identity_key as _workspace_identity_key,
)
from ahadiff.review.database import initialize_review_db
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_TOKEN = "test-token"
_AUTH = {"X-AhaDiff-Token": _TOKEN}


def _client(
    state_dir: Path,
    *,
    token: str = _TOKEN,
    locale: Literal["en", "zh-CN"] = "en",
) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token=token, locale=locale))
    return TestClient(app, base_url="http://localhost:8765")


# ---------------------------------------------------------------------------
# GET /api/search
# ---------------------------------------------------------------------------


class TestSearchAPI:
    def test_empty_query_returns_empty(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/search", params={"q": ""}, headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        SearchResponse.model_validate(body)
        assert body["results"] == []

    def test_no_db_returns_empty(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/search", params={"q": "hello"}, headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        SearchResponse.model_validate(body)
        assert body["results"] == []

    def test_requires_auth(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/search", params={"q": "test"})
        assert resp.status_code == 401

    def test_limit_capped(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/search", params={"q": "x", "limit": "9999"}, headers=_AUTH)
        assert resp.status_code == 200

    def test_invalid_limit_defaults(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/search", params={"q": "x", "limit": "bad"}, headers=_AUTH)
        assert resp.status_code == 200

    def test_table_filter_without_graph_nodes_does_not_load_graph(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        from ahadiff.serve import routes_search

        def fail_load_graph(_state_dir: Path) -> object | None:
            raise AssertionError("graph should not be loaded")

        monkeypatch.setattr(routes_search, "_load_graph", fail_load_graph)
        client = _client(tmp_path / ".ahadiff")

        resp = client.get(
            "/api/search",
            params={"q": "x", "tables": "concepts"},
            headers=_AUTH,
        )

        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_default_search_defers_graph_load_into_sync_worker(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        from ahadiff.serve import routes_search

        events: list[str] = []

        async def fake_run_sync(func: Callable[[], dict[str, object]]) -> dict[str, object]:
            events.append("run_sync")
            return func()

        def fake_load_graph(_state_dir: Path) -> object | None:
            events.append("load_graph")
            return None

        monkeypatch.setattr(routes_search.to_thread, "run_sync", fake_run_sync)
        monkeypatch.setattr(routes_search, "_load_graph", fake_load_graph)
        client = _client(tmp_path / ".ahadiff")

        resp = client.get("/api/search", params={"q": "x"}, headers=_AUTH)

        assert resp.status_code == 200
        assert events == ["run_sync", "load_graph"]


# ---------------------------------------------------------------------------
# GET /api/concepts/weak
# ---------------------------------------------------------------------------


class TestWeakConcepts:
    def test_no_db_returns_empty(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/concepts/weak", headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["concepts"] == []
        assert body["new_concepts"] == []

    def test_requires_auth(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/concepts/weak")
        assert resp.status_code == 401

    def test_limit_capped_at_100(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/concepts/weak", params={"limit": "500"}, headers=_AUTH)
        assert resp.status_code == 200

    def test_with_cards_data(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        db_path = state_dir / "review.sqlite"
        _setup_cards_db(db_path)
        client = _client(state_dir)
        resp = client.get("/api/concepts/weak", headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        # "concepts" = truly weak (reviewed but struggling, reps > 0)
        assert len(body["concepts"]) > 0
        first = body["concepts"][0]
        assert "card_id" in first
        assert "concept" in first
        assert "stability" in first
        assert "difficulty" in first
        # "new_concepts" = unreviewed (reps = 0)
        assert "new_concepts" in body
        assert len(body["new_concepts"]) > 0
        new_ids = {c["card_id"] for c in body["new_concepts"]}
        weak_ids = {c["card_id"] for c in body["concepts"]}
        # No overlap between weak and new
        assert new_ids.isdisjoint(weak_ids)

    def test_current_schema_corruption_returns_500(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        with sqlite3.connect(state_dir / "review.sqlite") as conn:
            conn.execute("CREATE TABLE result_events (event_id TEXT PRIMARY KEY)")
            conn.execute("PRAGMA user_version=8")
        client = _client(state_dir)

        resp = client.get("/api/concepts/weak", headers=_AUTH)

        assert resp.status_code == 500
        assert resp.json()["error_code"] == "STORAGE_REVIEW_DB"
        assert resp.json()["error"] == "review_database_unavailable"


# ---------------------------------------------------------------------------
# GET /api/review/mastery
# ---------------------------------------------------------------------------


class TestReviewMastery:
    def test_no_db_returns_empty(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/review/mastery", headers=_AUTH)
        assert resp.status_code == 200
        assert resp.json()["mastery"] == []

    def test_requires_auth(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/review/mastery")
        assert resp.status_code == 401

    def test_limit_capped_at_200(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/review/mastery", params={"limit": "9999"}, headers=_AUTH)
        assert resp.status_code == 200

    def test_with_review_data(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        db_path = state_dir / "review.sqlite"
        _setup_cards_and_reviews(db_path)
        client = _client(state_dir)
        resp = client.get("/api/review/mastery", headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["mastery"]) > 0
        first = body["mastery"][0]
        assert "concept" in first
        assert "review_count" in first
        assert "avg_rating" in first

    def test_current_schema_corruption_returns_500(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        with sqlite3.connect(state_dir / "review.sqlite") as conn:
            conn.execute("CREATE TABLE result_events (event_id TEXT PRIMARY KEY)")
            conn.execute("PRAGMA user_version=8")
        client = _client(state_dir)

        resp = client.get("/api/review/mastery", headers=_AUTH)

        assert resp.status_code == 500
        assert resp.json()["error_code"] == "STORAGE_REVIEW_DB"
        assert resp.json()["error"] == "review_database_unavailable"


# ---------------------------------------------------------------------------
# GET /api/usage
# ---------------------------------------------------------------------------


class TestUsage:
    def test_no_usage_db_returns_empty(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        usage_db = tmp_path / "usage.sqlite"
        monkeypatch.setattr("ahadiff.core.paths.usage_db_path", _usage_db_factory(usage_db))
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/usage", headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["models"] == []
        assert body["total_calls"] == 0

    def test_requires_auth(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/usage")
        assert resp.status_code == 401

    def test_usage_reads_llm_usage_rows(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        from ahadiff.llm.usage import UsageRecord, record_usage_event

        usage_db = tmp_path / "usage.sqlite"
        monkeypatch.setattr("ahadiff.core.paths.usage_db_path", _usage_db_factory(usage_db))
        record_usage_event(
            UsageRecord(
                workspace_identity=_workspace_identity_key(tmp_path),
                provider_class="openai",
                api_family="responses",
                api_family_version="v1",
                model_id="gpt-5.4-mini",
                prompt_name="quiz.generate",
                prompt_fingerprint="abc123",
                prompt_version="abc123",
                eval_bundle_version="eval-v1",
                output_lang="en",
                privacy_mode="strict_local",
                source_ref="deadbeef",
                cache_key="cache-key",
                cache_hit=False,
                input_tokens=123,
                output_tokens=45,
                cost_usd=0.67,
                pricing_version="pricing-v1",
                cost_confidence="high",
                execution_origin="quiz_generate",
            ),
            db_path=usage_db,
        )

        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/usage", headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_calls"] == 1
        assert body["total_input_tokens"] == 123
        assert body["total_output_tokens"] == 45
        assert body["total_cost_usd"] == 0.67
        assert body["cache_hits"] == 0
        assert body["cache_misses"] == 1
        assert body["models"] == [
            {
                "provider_class": "openai",
                "model_id": "gpt-5.4-mini",
                "call_count": 1,
                "total_input_tokens": 123,
                "total_output_tokens": 45,
                "total_cost_usd": 0.67,
            }
        ]

    def test_usage_reads_legacy_workspace_identity_rows(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        from ahadiff.llm.usage import UsageRecord, record_usage_event

        usage_db = tmp_path / "usage.sqlite"
        monkeypatch.setattr("ahadiff.core.paths.usage_db_path", _usage_db_factory(usage_db))
        record_usage_event(
            UsageRecord(
                workspace_identity=_legacy_path_identity_key(tmp_path),
                provider_class="openai",
                api_family="responses",
                api_family_version="v1",
                model_id="legacy-model",
                prompt_name="quiz.generate",
                prompt_fingerprint="legacy123",
                prompt_version="legacy123",
                eval_bundle_version="eval-v1",
                output_lang="en",
                privacy_mode="strict_local",
                source_ref="deadbeef",
                cache_key="legacy-cache-key",
                cache_hit=False,
                input_tokens=7,
                output_tokens=3,
                cost_usd=0.11,
                pricing_version="pricing-v1",
                cost_confidence="high",
                execution_origin="quiz_generate",
            ),
            db_path=usage_db,
        )

        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/usage", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_calls"] == 1
        assert body["models"][0]["model_id"] == "legacy-model"

    def test_usage_corrupt_db_returns_500(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        usage_db = tmp_path / "usage.sqlite"
        usage_db.write_text("not a sqlite db", encoding="utf-8")
        monkeypatch.setattr("ahadiff.core.paths.usage_db_path", _usage_db_factory(usage_db))
        client = _client(tmp_path / ".ahadiff")

        resp = client.get("/api/usage", headers=_AUTH)

        assert resp.status_code == 500
        assert resp.json()["error_code"] == "STORAGE_USAGE_DB"
        assert resp.json()["error"] == "usage_database_unavailable"

    def test_usage_invalid_time_filter_returns_400(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        from ahadiff.llm.usage import UsageRecord, record_usage_event

        usage_db = tmp_path / "usage.sqlite"
        monkeypatch.setattr("ahadiff.core.paths.usage_db_path", _usage_db_factory(usage_db))
        record_usage_event(
            UsageRecord(
                workspace_identity=_workspace_identity_key(tmp_path),
                provider_class="openai",
                api_family="responses",
                api_family_version="v1",
                model_id="gpt-5.4-mini",
                prompt_name="quiz.generate",
                prompt_fingerprint="abc123",
                prompt_version="abc123",
                eval_bundle_version="eval-v1",
                output_lang="en",
                privacy_mode="strict_local",
                source_ref="deadbeef",
                cache_key="cache-key",
                cache_hit=False,
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.01,
                pricing_version="pricing-v1",
                cost_confidence="high",
                execution_origin="quiz_generate",
            ),
            db_path=usage_db,
        )
        client = _client(tmp_path / ".ahadiff")

        resp = client.get("/api/usage", params={"from": "not-a-date"}, headers=_AUTH)

        assert resp.status_code == 400
        assert "ISO-8601" in resp.json()["error"]


# ---------------------------------------------------------------------------
# GET /api/audit
# ---------------------------------------------------------------------------


class TestAudit:
    def test_no_file_returns_empty(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        client = _client(state_dir)
        resp = client.get("/api/audit", headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["entries"] == []
        assert body["total"] == 0

    def test_requires_auth(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/audit")
        assert resp.status_code == 401

    def test_with_audit_file(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        audit_path = state_dir / "audit.jsonl"
        lines = [
            json.dumps({"action": "learn", "ts": "2026-01-01T00:00:00Z"}),
            json.dumps({"action": "quiz", "ts": "2026-01-02T00:00:00Z"}),
            json.dumps({"action": "review", "ts": "2026-01-03T00:00:00Z"}),
        ]
        audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        client = _client(state_dir)
        resp = client.get("/api/audit", headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert len(body["entries"]) == 3
        assert [entry["action"] for entry in body["entries"]] == ["review", "quiz", "learn"]

    def test_pagination(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        audit_path = state_dir / "audit.jsonl"
        lines = [json.dumps({"i": i}) for i in range(10)]
        audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        client = _client(state_dir)
        resp = client.get("/api/audit", params={"limit": "3", "offset": "2"}, headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 10
        assert len(body["entries"]) == 3
        assert body["offset"] == 2
        assert body["page"] == 1
        assert body["has_more"] is True
        assert body["next_cursor"] == "5"
        assert [entry["i"] for entry in body["entries"]] == [7, 6, 5]

    def test_page_limit_and_fields_filter(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        audit_path = state_dir / "audit.jsonl"
        lines = [
            json.dumps(
                {
                    "timestamp": f"2026-01-0{i}T00:00:00Z",
                    "event_type": "provider_call",
                    "provider_class": "openai",
                    "model_id": f"model-{i}",
                    "prompt_name": "lesson_generate",
                    "cost_confidence": "estimated",
                    "execution_origin": "serve",
                    "secret": "must-not-pass-filter",
                }
            )
            for i in range(1, 6)
        ]
        audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        client = _client(state_dir)

        resp = client.get(
            "/api/audit",
            params={
                "limit": "2",
                "page": "2",
                "fields": (
                    "timestamp,provider_class,model_id,prompt_name,cost_confidence,execution_origin"
                ),
            },
            headers=_AUTH,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["offset"] == 2
        assert body["page"] == 2
        assert body["fields"] == [
            "timestamp",
            "provider_class",
            "model_id",
            "prompt_name",
            "cost_confidence",
            "execution_origin",
        ]
        assert body["entries"] == [
            {
                "timestamp": "2026-01-03T00:00:00Z",
                "provider_class": "openai",
                "model_id": "model-3",
                "prompt_name": "lesson_generate",
                "cost_confidence": "estimated",
                "execution_origin": "serve",
            },
            {
                "timestamp": "2026-01-02T00:00:00Z",
                "provider_class": "openai",
                "model_id": "model-2",
                "prompt_name": "lesson_generate",
                "cost_confidence": "estimated",
                "execution_origin": "serve",
            },
        ]

    def test_unknown_audit_field_is_rejected(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        (state_dir / "audit.jsonl").write_text("{}\n", encoding="utf-8")
        client = _client(state_dir)

        resp = client.get("/api/audit", params={"fields": "secret"}, headers=_AUTH)

        assert resp.status_code == 400
        assert "unsupported audit fields" in resp.json()["error"]

    def test_malformed_lines_are_skipped_per_line(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        audit_path = state_dir / "audit.jsonl"
        audit_path.write_text('{"i": 1}\n{bad json}\n{"i": 2}\n', encoding="utf-8")
        client = _client(state_dir)
        resp = client.get("/api/audit", headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert [entry["i"] for entry in body["entries"]] == [2, 1]

    def test_limit_capped(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        (state_dir / "audit.jsonl").write_text("{}\n", encoding="utf-8")
        client = _client(state_dir)
        resp = client.get("/api/audit", params={"limit": "9999"}, headers=_AUTH)
        assert resp.status_code == 200

    def test_symlinked_audit_file_rejected(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        external = tmp_path / "external-audit.jsonl"
        external.write_text('{"outside": true}\n', encoding="utf-8")
        (state_dir / "audit.jsonl").symlink_to(external)

        client = _client(state_dir)
        resp = client.get("/api/audit", headers=_AUTH)

        assert resp.status_code == 400
        assert "must not be a symlink" in resp.json()["error"]

    @pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
    def test_symlinked_state_dir_parent_rejected(self, tmp_path: Path) -> None:
        real_repo = tmp_path / "real-repo"
        real_state = real_repo / ".ahadiff"
        real_state.mkdir(parents=True)
        (real_state / "audit.jsonl").write_text('{"outside": true}\n', encoding="utf-8")
        link_repo = tmp_path / "link-repo"
        link_repo.symlink_to(real_repo, target_is_directory=True)

        client = _client(link_repo / ".ahadiff")
        resp = client.get("/api/audit", headers=_AUTH)

        assert resp.status_code == 400
        assert "state path must not contain symlinks" in resp.json()["error"]


# ---------------------------------------------------------------------------
# PUT /api/config
# ---------------------------------------------------------------------------


class TestPutConfig:
    def test_update_lang(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.put(
            "/api/config",
            json={"lang": "zh-CN"},
            headers={**_AUTH, "origin": "http://localhost:8765"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["updated"] is True
        assert body["scope"] == "session"

    def test_requires_auth(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.put(
            "/api/config",
            json={"lang": "en"},
            headers={"origin": "http://localhost:8765"},
        )
        assert resp.status_code == 401

    def test_invalid_lang_rejected(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.put(
            "/api/config",
            json={"lang": "fr"},
            headers={**_AUTH, "origin": "http://localhost:8765"},
        )
        assert resp.status_code == 400

    def test_unknown_key_rejected(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.put(
            "/api/config",
            json={"unknown_key": "value"},
            headers={**_AUTH, "origin": "http://localhost:8765"},
        )
        assert resp.status_code == 400

    def test_learn_desired_retention_round_trips(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        (repo_root / ".git").mkdir(parents=True)
        state_dir = repo_root / ".ahadiff"
        client = _client(state_dir)

        put_resp = client.put(
            "/api/config",
            json={"learn": {"desired_retention": 0.84}},
            headers={**_AUTH, "origin": "http://localhost:8765"},
        )
        get_resp = client.get("/api/config")

        assert put_resp.status_code == 200
        assert get_resp.status_code == 200
        assert get_resp.json()["learn"]["desired_retention"] == 0.84

    @pytest.mark.parametrize("value", [0.7, 0.99])
    def test_learn_desired_retention_accepts_boundaries(
        self,
        tmp_path: Path,
        value: float,
    ) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.put(
            "/api/config",
            json={"learn": {"desired_retention": value}},
            headers={**_AUTH, "origin": "http://localhost:8765"},
        )

        assert resp.status_code == 200

    @pytest.mark.parametrize(
        "payload",
        [
            {"learn": {"desired_retention": 0.5}},
            {"learn": {"desired_retention": 1.0}},
            {"learn": {"desired_retention": True}},
            {"learn": {"desired_retention": "0.84"}},
            {"learn": {"desired_retention": None}},
        ],
    )
    def test_learn_desired_retention_out_of_range_rejected(
        self,
        tmp_path: Path,
        payload: dict[str, object],
    ) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.put(
            "/api/config",
            json=payload,
            headers={**_AUTH, "origin": "http://localhost:8765"},
        )

        assert resp.status_code == 400
        assert "learn.desired_retention" in resp.json()["error"]

    @pytest.mark.parametrize("raw_value", ["NaN", "Infinity"])
    def test_learn_desired_retention_non_finite_rejected(
        self,
        tmp_path: Path,
        raw_value: str,
    ) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.put(
            "/api/config",
            content=f'{{"learn":{{"desired_retention":{raw_value}}}}}'.encode(),
            headers={
                **_AUTH,
                "origin": "http://localhost:8765",
                "content-type": "application/json",
            },
        )

        assert resp.status_code == 400
        assert "learn.desired_retention" in resp.json()["error"]

    @pytest.mark.parametrize("raw_value", ["NaN", "Infinity"])
    def test_learnability_threshold_non_finite_rejected(
        self,
        tmp_path: Path,
        raw_value: str,
    ) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.put(
            "/api/config",
            content=f'{{"learn":{{"learnability_threshold":{raw_value}}}}}'.encode(),
            headers={
                **_AUTH,
                "origin": "http://localhost:8765",
                "content-type": "application/json",
            },
        )

        assert resp.status_code == 400
        assert "learn.learnability_threshold" in resp.json()["error"]

    def test_learn_unknown_nested_key_rejected(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.put(
            "/api/config",
            json={"learn": {"desired_retention": 0.84, "extra": 1}},
            headers={**_AUTH, "origin": "http://localhost:8765"},
        )

        assert resp.status_code == 400
        assert "unknown learn keys" in resp.json()["error"]

    def test_non_object_rejected(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.put(
            "/api/config",
            content=b'"just a string"',
            headers={
                **_AUTH,
                "origin": "http://localhost:8765",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/spec/alignment
# ---------------------------------------------------------------------------


class TestSpecAlignment:
    def test_no_db_returns_empty(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/spec/alignment", headers=_AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["alignment_score"] is None
        assert body["total_evaluated"] == 0
        assert body["recent_trend"] is None

    def test_requires_auth(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/spec/alignment")
        assert resp.status_code == 401

    def test_uses_score_json_spec_alignment_dimension(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        db_path = state_dir / "review.sqlite"
        initialize_review_db(db_path)

        for idx, score in enumerate((2.0, 3.0, 8.0, 9.0)):
            event_id = f"evt_{idx}"
            run_id = f"run_{idx:032x}"
            _insert_result_event(
                db_path,
                event_id=event_id,
                run_id=run_id,
                timestamp=f"2026-04-{10 + idx:02d}T12:00:00Z",
                overall=90.0 - (idx * 10.0),
            )
            _write_score_artifact(
                state_dir,
                run_id=run_id,
                event_id=event_id,
                spec_alignment_score=score,
            )

        client = _client(state_dir)

        resp = client.get("/api/spec/alignment", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["alignment_score"] == 5.5
        assert body["total_evaluated"] == 4
        assert body["recent_trend"] == "improving"

    def test_ignores_result_events_without_valid_spec_alignment_artifact(
        self,
        tmp_path: Path,
    ) -> None:
        state_dir = tmp_path / ".ahadiff"
        state_dir.mkdir(parents=True)
        db_path = state_dir / "review.sqlite"
        initialize_review_db(db_path)
        _insert_result_event(
            db_path,
            event_id="evt_valid",
            run_id="run_00000000000000000000000000000001",
            timestamp="2026-04-10T12:00:00Z",
            overall=10.0,
        )
        _write_score_artifact(
            state_dir,
            run_id="run_00000000000000000000000000000001",
            event_id="evt_valid",
            spec_alignment_score=7.0,
        )
        _insert_result_event(
            db_path,
            event_id="evt_invalid",
            run_id="run_00000000000000000000000000000002",
            timestamp="2026-04-11T12:00:00Z",
            overall=100.0,
        )
        _write_score_artifact(
            state_dir,
            run_id="run_00000000000000000000000000000002",
            event_id="evt_invalid",
            spec_alignment_score=True,
        )

        client = _client(state_dir)

        resp = client.get("/api/spec/alignment", headers=_AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["alignment_score"] == 7.0
        assert body["total_evaluated"] == 1
        assert body["recent_trend"] is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_result_event(
    db_path: Path,
    *,
    event_id: str,
    run_id: str,
    timestamp: str,
    overall: float,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO result_events (
                event_id, run_id, event_type, timestamp, source_ref, base_ref,
                prompt_version, eval_bundle_version, rubric_version, overall,
                verdict, status, weakest_dim, note_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                run_id,
                "score",
                timestamp,
                "abc123",
                "def456",
                "prompt-v1",
                "eval-v1",
                "rubric-v1",
                overall,
                "PASS",
                "keep_final",
                "spec_alignment",
                None,
            ),
        )


def _write_score_artifact(
    state_dir: Path,
    *,
    run_id: str,
    event_id: str,
    spec_alignment_score: object,
) -> None:
    run_path = state_dir / "runs" / run_id
    run_path.mkdir(parents=True)
    (run_path / "score.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "overall": 80.0,
                "dimensions": {
                    "spec_alignment": {
                        "score": spec_alignment_score,
                        "max_score": 10.0,
                        "reason": "test fixture",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (run_path / "finalized.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "event_id": event_id,
                "finalized_at": "2026-04-10T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def _setup_cards_db(db_path: Path) -> None:
    initialize_review_db(db_path)
    _cols = (
        "id, concept, stability, difficulty, scaffolding_level, display_path,"
        " card_state, reps, run_id, fsrs_state, scheduler_version,"
        " due_date, source_ref, file_id, hunk_id, hunk_hash, created_at_utc"
    )
    _defaults = (
        "run-test",
        "{}",
        "v6",
        "2026-01-01",
        "ref",
        "f",
        "h",
        "hh",
        "2026-01-01T00:00:00Z",
    )
    conn = sqlite3.connect(str(db_path))
    # card-1: reviewed (reps > 0) -> goes to "concepts" (weak)
    conn.execute(
        f"INSERT INTO cards ({_cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("card-1", "closures", 0.2, 0.8, "full", "concepts/closures", "active", 3, *_defaults),
    )
    # card-2: reviewed (reps > 0) -> goes to "concepts" (weak)
    conn.execute(
        f"INSERT INTO cards ({_cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("card-2", "generators", 0.5, 0.4, "hint", "concepts/generators", "active", 1, *_defaults),
    )
    # card-3: never reviewed (reps = 0) -> goes to "new_concepts"
    conn.execute(
        f"INSERT INTO cards ({_cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("card-3", "decorators", 0.0, 0.0, "full", "concepts/decorators", "active", 0, *_defaults),
    )
    conn.commit()
    conn.close()


def _usage_db_factory(db_path: Path):
    def _resolve_usage_db_path(
        *, platform: str | None = None, env: Mapping[str, str] | None = None
    ) -> Path:
        del platform, env
        return db_path

    return _resolve_usage_db_path


def _setup_cards_and_reviews(db_path: Path) -> None:
    _setup_cards_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL,
            rating REAL NOT NULL,
            reviewed_at_utc TEXT NOT NULL,
            review_duration REAL DEFAULT 0
        )
        """
    )
    _rl_cols = "card_id, rating, reviewed_at_utc, elapsed_days, scheduled_days, state"
    conn.execute(
        f"INSERT INTO review_logs ({_rl_cols}) VALUES (?, ?, ?, ?, ?, ?)",
        ("card-1", 3, "2026-04-01T10:00:00Z", 0.0, 1.0, "review"),
    )
    conn.execute(
        f"INSERT INTO review_logs ({_rl_cols}) VALUES (?, ?, ?, ?, ?, ?)",
        ("card-1", 4, "2026-04-02T10:00:00Z", 1.0, 3.0, "review"),
    )
    conn.execute(
        f"INSERT INTO review_logs ({_rl_cols}) VALUES (?, ?, ?, ?, ?, ?)",
        ("card-2", 2, "2026-04-01T10:00:00Z", 0.0, 1.0, "review"),
    )
    conn.commit()
    conn.close()
