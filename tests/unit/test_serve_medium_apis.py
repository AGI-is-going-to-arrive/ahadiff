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
        assert resp.status_code == 403

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

    def test_requires_auth(self, tmp_path: Path) -> None:
        client = _client(tmp_path / ".ahadiff")
        resp = client.get("/api/concepts/weak")
        assert resp.status_code == 403

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
        assert len(body["concepts"]) > 0
        first = body["concepts"][0]
        assert "card_id" in first
        assert "concept" in first
        assert "stability" in first
        assert "difficulty" in first


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
        assert resp.status_code == 403

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
        assert resp.status_code == 403

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
        assert body["models"] == [
            {
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
        assert resp.json()["error"] == "usage database is unavailable"


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
        assert resp.status_code == 403

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
        assert [entry["i"] for entry in body["entries"]] == [1, 2]

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
        assert resp.status_code == 403

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
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_cards_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id TEXT PRIMARY KEY,
            concept TEXT NOT NULL,
            stability REAL DEFAULT 0.4,
            difficulty REAL DEFAULT 0.3,
            scaffolding_level TEXT DEFAULT 'full',
            display_path TEXT DEFAULT '',
            card_state TEXT DEFAULT 'active'
        )
        """
    )
    conn.execute(
        "INSERT INTO cards"
        " (id, concept, stability, difficulty, scaffolding_level, display_path, card_state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("card-1", "closures", 0.2, 0.8, "full", "concepts/closures", "active"),
    )
    conn.execute(
        "INSERT INTO cards"
        " (id, concept, stability, difficulty, scaffolding_level, display_path, card_state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("card-2", "generators", 0.5, 0.4, "hint", "concepts/generators", "active"),
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
    conn.execute(
        "INSERT INTO review_logs (card_id, rating, reviewed_at_utc) VALUES (?, ?, ?)",
        ("card-1", 3.0, "2026-04-01T10:00:00Z"),
    )
    conn.execute(
        "INSERT INTO review_logs (card_id, rating, reviewed_at_utc) VALUES (?, ?, ?)",
        ("card-1", 4.0, "2026-04-02T10:00:00Z"),
    )
    conn.execute(
        "INSERT INTO review_logs (card_id, rating, reviewed_at_utc) VALUES (?, ?, ?)",
        ("card-2", 2.0, "2026-04-01T10:00:00Z"),
    )
    conn.commit()
    conn.close()
