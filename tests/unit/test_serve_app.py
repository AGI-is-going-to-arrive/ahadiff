from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, cast

from starlette.testclient import TestClient

from ahadiff.contracts import ResultEvent, ReviewCard
from ahadiff.eval.results import finalized_artifact_digest
from ahadiff.review.database import import_cards_from_jsonl, initialize_review_db, sync_result_event
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from pathlib import Path


def _client(
    state_dir: Path,
    *,
    token: str = "test-token",
    locale: Literal["en", "zh-CN"] = "en",
) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token=token, locale=locale))
    return TestClient(app, base_url="http://localhost:8765")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _event(
    run_id: str,
    *,
    status: str = "keep",
    source_ref: str = "abc1234",
    event_id: str | None = None,
) -> ResultEvent:
    return ResultEvent(
        event_id=event_id or f"018f0f52-91c0-7abc-8123-{run_id[-1]:0>12}",
        run_id=run_id,
        event_type="learn",
        timestamp=f"2026-04-24T00:00:0{run_id[-1]}Z",
        source_ref=source_ref,
        base_ref="base1234",
        prompt_version="prompt123",
        eval_bundle_version="eval123",
        rubric_version="rubric-v1",
        overall=88.0,
        verdict="PASS",
        status=cast("Any", status),
        weakest_dim="evidence",
        note_json=None,
    )


def _write_run(state_dir: Path, run_id: str, *, finalized: bool = True) -> Path:
    run_path = state_dir / "runs" / run_id
    run_path.mkdir(parents=True, exist_ok=True)
    _write_json(
        run_path / "metadata.json",
        {
            "run_id": run_id,
            "source_kind": "git_ref",
            "source_ref": "abc1234",
            "capability_level": 2,
            "degraded_flags": {"diff_clipped": True},
        },
    )
    (run_path / "patch.diff").write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
    (run_path / "claims.jsonl").write_text('{"claim_id":"claim-1"}\n', encoding="utf-8")
    lesson_dir = run_path / "lesson"
    lesson_dir.mkdir()
    (lesson_dir / "lesson.full.md").write_text("full lesson\n", encoding="utf-8")
    (lesson_dir / "lesson.hint.md").write_text("hint lesson\n", encoding="utf-8")
    (lesson_dir / "lesson.compact.md").write_text("compact lesson\n", encoding="utf-8")
    quiz_dir = run_path / "quiz"
    quiz_dir.mkdir()
    (quiz_dir / "quiz.jsonl").write_text('{"question":"What changed?"}\n', encoding="utf-8")
    if finalized:
        artifact_count, checksum = finalized_artifact_digest(run_path)
        _write_json(
            run_path / "finalized.json",
            {
                "run_id": run_id,
                "event_id": f"018f0f52-91c0-7abc-8123-{run_id[-1]:0>12}",
                "finalized_at": f"2026-04-24T00:00:0{run_id[-1]}Z",
                "artifact_count": artifact_count,
                "checksum": checksum,
                "status": "keep",
            },
        )
    return run_path


def test_healthz_and_loopback_host_guard(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    assert client.get("/healthz").json() == {"ok": True}
    blocked = client.get("/healthz", headers={"host": "evil.example"})

    assert blocked.status_code == 400
    assert blocked.json()["error"] == "host_not_allowed"


def test_origin_guard_rejects_non_loopback_write_origin(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.put(
        "/api/locale",
        headers={"origin": "https://evil.example", "X-AhaDiff-Token": "test-token"},
        json={"lang": "zh-CN"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "origin_not_allowed"


def test_write_routes_require_token(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    denied = client.put(
        "/api/locale",
        headers={"origin": "http://localhost:8765"},
        json={"lang": "zh-CN"},
    )
    accepted = client.put(
        "/api/locale",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={"lang": "zh-CN"},
    )

    assert denied.status_code == 403
    assert accepted.status_code == 200
    assert client.get("/api/locale").json() == {"locale": "zh-CN"}


def test_locale_resolves_cookie_accept_language_and_serve_state(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff", locale="zh-CN")

    from_state = client.get("/api/locale")
    from_accept_language = client.get("/api/locale", headers={"accept-language": "en-AU,en;q=0.9"})
    from_cookie = client.get(
        "/api/locale",
        headers={"accept-language": "en"},
        cookies={"ahadiff_lang": "zh-CN"},
    )

    assert from_state.json() == {"locale": "zh-CN"}
    assert from_accept_language.json() == {"locale": "en"}
    assert from_cookie.json() == {"locale": "zh-CN"}


def test_write_routes_require_loopback_origin_or_referer(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    missing = client.put(
        "/api/locale",
        headers={"X-AhaDiff-Token": "test-token"},
        json={"lang": "zh-CN"},
    )
    wrong_port = client.put(
        "/api/locale",
        headers={"origin": "http://localhost:9999", "X-AhaDiff-Token": "test-token"},
        json={"lang": "zh-CN"},
    )
    referer = client.put(
        "/api/locale",
        headers={"referer": "http://127.0.0.1:8765/app", "X-AhaDiff-Token": "test-token"},
        json={"lang": "zh-CN"},
    )

    assert missing.status_code == 403
    assert missing.json()["error"] == "origin_or_referer_required"
    assert wrong_port.status_code == 403
    assert wrong_port.json()["error"] == "origin_not_allowed"
    assert referer.status_code == 200


def test_runs_only_expose_finalized_runs_and_artifacts(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    _write_run(state_dir, "run-1", finalized=True)
    _write_run(state_dir, "run-2", finalized=False)
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    sync_result_event(state_dir / "review.sqlite", _event("run-2"))
    client = _client(state_dir)

    runs = client.get("/api/runs").json()["runs"]
    detail = client.get("/api/run/run-1").json()
    hidden = client.get("/api/run/run-2")
    lesson = client.get("/api/run/run-1/lesson?level=compact").json()

    assert [run["run_id"] for run in runs] == ["run-1"]
    assert detail["run_id"] == "run-1"
    assert detail["source_kind"] == "git_ref"
    assert detail["degraded_flags"] == {"diff_clipped": True}
    assert hidden.status_code == 400
    assert lesson == {"run_id": "run-1", "artifact_type": "lesson", "content": "compact lesson\n"}


def test_artifact_routes_require_finalized_marker_event_match(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=True)
    artifact_count, checksum = finalized_artifact_digest(run_path)
    _write_json(
        run_path / "finalized.json",
        {
            "run_id": "run-1",
            "event_id": "018f0f52-91c0-7abc-8123-999999999999",
            "finalized_at": "2026-04-24T00:00:01Z",
            "artifact_count": artifact_count,
            "checksum": checksum,
            "status": "keep",
        },
    )
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1/lesson")

    assert response.status_code == 400
    assert "finalized result event does not exist" in response.json()["error"]


def test_legacy_finalized_marker_without_digest_is_hidden(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=True)
    _write_json(
        run_path / "finalized.json",
        {
            "run_id": "run-1",
            "event_id": "018f0f52-91c0-7abc-8123-000000000001",
            "status": "keep",
        },
    )
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    assert client.get("/api/runs").json() == {"runs": []}
    response = client.get("/api/run/run-1")

    assert response.status_code == 400
    assert "finalized marker is invalid" in response.json()["error"]


def test_finalized_marker_checksum_mismatch_is_hidden(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=True)
    (run_path / "patch.diff").write_text("diff changed after finalization\n", encoding="utf-8")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    assert client.get("/api/runs").json() == {"runs": []}
    response = client.get("/api/run/run-1/lesson")

    assert response.status_code == 400
    assert "finalized marker is invalid" in response.json()["error"]


def test_symlink_artifact_invalidates_finalized_run(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=True)
    lesson_path = run_path / "lesson" / "lesson.full.md"
    lesson_path.unlink()
    lesson_path.symlink_to("/etc/hosts")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    assert client.get("/api/runs").json() == {"runs": []}
    response = client.get("/api/run/run-1/lesson")

    assert response.status_code == 400
    assert "finalized marker is invalid" in response.json()["error"]


def test_malformed_finalized_marker_is_hidden_without_500(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=True)
    (run_path / "finalized.json").write_text("{not-json\n", encoding="utf-8")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    assert client.get("/api/runs").json() == {"runs": []}
    response = client.get("/api/run/run-1")

    assert response.status_code == 400
    assert "finalized marker is invalid" in response.json()["error"]


def test_run_detail_uses_finalized_marker_event_not_newer_unfinalized_event(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    _write_run(state_dir, "run-1", finalized=True)
    sync_result_event(
        state_dir / "review.sqlite",
        _event("run-1", event_id="018f0f52-91c0-7abc-8123-000000000001"),
    )
    sync_result_event(
        state_dir / "review.sqlite",
        _event(
            "run-1",
            status="targeted_verify",
            event_id="018f0f52-91c0-7abc-8123-000000000099",
        ),
    )
    client = _client(state_dir)

    detail = client.get("/api/run/run-1").json()
    runs = client.get("/api/runs").json()["runs"]

    assert detail["status"] == "keep"
    assert runs[0]["status"] == "keep"


def test_runs_source_kind_filter_and_ratchet_history(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    _write_run(state_dir, "run-1", finalized=True)
    _write_run(state_dir, "run-2", finalized=True)
    _write_json(
        state_dir / "runs" / "run-2" / "metadata.json",
        {
            "run_id": "run-2",
            "source_kind": "patch_file",
            "source_ref": "sha256:fixture",
            "capability_level": 1,
            "degraded_flags": {},
        },
    )
    sync_result_event(state_dir / "review.sqlite", _event("run-1", status="keep"))
    sync_result_event(
        state_dir / "review.sqlite",
        _event("run-2", status="non_ratcheted", source_ref="sha256:fixture"),
    )
    client = _client(state_dir)

    filtered = client.get("/api/runs?source_kind=git_ref").json()["runs"]
    history = client.get("/api/ratchet/history").json()["history"]

    assert [run["run_id"] for run in filtered] == ["run-1"]
    assert [entry["run_id"] for entry in history] == ["run-1"]


def test_mark_wrong_signal_is_idempotent(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    payload = {"claim_id": "claim-1", "idempotency_key": "mark:claim-1:wrong"}

    first = client.post(
        "/api/signals/mark-wrong",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json=payload,
    )
    second = client.post(
        "/api/signals/mark-wrong",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json=payload,
    )

    assert first.json() == {"inserted": True}
    assert second.json() == {"inserted": False}


def test_srs_review_records_card_review(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    cards_path = state_dir / "runs" / "run-1" / "quiz" / "cards.jsonl"
    card = ReviewCard(
        card_id="card-1",
        concept="retry loop",
        run_id="run-1",
        source_ref="abc1234",
        fsrs_state="{}",
        file_id="file-app",
        display_path="src/app.py",
        hunk_id="hunk-1",
        hunk_hash="deadbeefcafe",
        symbol="retry_once",
    )
    cards_path.parent.mkdir(parents=True, exist_ok=True)
    cards_path.write_text(json.dumps(card.model_dump(mode="json")) + "\n", encoding="utf-8")
    assert import_cards_from_jsonl(db_path, cards_path) == 1
    client = _client(state_dir)

    response = client.post(
        "/api/signals/srs-review",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={"card_id": "card-1", "answer": "hard", "idempotency_key": "review-1"},
    )
    duplicate = client.post(
        "/api/signals/srs-review",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={"card_id": "card-1", "answer": "hard", "idempotency_key": "review-1"},
    )

    assert response.status_code == 200
    assert response.json()["inserted"] is True
    assert response.json()["review"]["card_id"] == "card-1"
    assert response.json()["review"]["rating"] == 2
    assert duplicate.json() == {"inserted": False}


def test_malformed_origin_is_rejected_without_500(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.put(
        "/api/locale",
        headers={"origin": "http://localhost:bad", "X-AhaDiff-Token": "test-token"},
        json={"lang": "zh-CN"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "origin_not_allowed"


def test_viewer_static_serves_spa_fallback_without_viewer_source_changes(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    viewer_dist = tmp_path / "viewer" / "dist"
    viewer_dist.mkdir(parents=True)
    (viewer_dist / "index.html").write_text("<h1>AhaDiff</h1>\n", encoding="utf-8")
    app = create_app(ServeState(state_dir=state_dir, token="test-token"), viewer_dist=viewer_dist)
    client = TestClient(app, base_url="http://localhost:8765")

    root = client.get("/")
    nested = client.get("/dashboard")

    assert root.status_code == 200
    assert nested.status_code == 200
    assert "AhaDiff" in nested.text


def test_failed_srs_review_does_not_poison_idempotency_key(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    client = _client(state_dir)
    payload = {"card_id": "card-1", "answer": "hard", "idempotency_key": "review-1"}

    missing_card = client.post(
        "/api/signals/srs-review",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json=payload,
    )
    card = ReviewCard(
        card_id="card-1",
        concept="retry loop",
        run_id="run-1",
        source_ref="abc1234",
        fsrs_state="{}",
        file_id="file-app",
        display_path="src/app.py",
        hunk_id="hunk-1",
        hunk_hash="deadbeefcafe",
        symbol="retry_once",
    )
    cards_path = state_dir / "runs" / "run-1" / "quiz" / "cards.jsonl"
    cards_path.parent.mkdir(parents=True, exist_ok=True)
    cards_path.write_text(json.dumps(card.model_dump(mode="json")) + "\n", encoding="utf-8")
    assert import_cards_from_jsonl(db_path, cards_path) == 1
    retry = client.post(
        "/api/signals/srs-review",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json=payload,
    )

    assert missing_card.status_code == 400
    assert retry.status_code == 200
    assert retry.json()["inserted"] is True
