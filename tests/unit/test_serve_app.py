from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

import ahadiff.serve.lock as serve_lock_module
import ahadiff.serve.middleware as middleware_module
import ahadiff.serve.routes_locale as routes_locale_module
import ahadiff.serve.routes_review as routes_review_module
import ahadiff.serve.routes_runs as routes_runs_module
from ahadiff.contracts import ResultEvent, ReviewCard, RunArtifactEnvelope
from ahadiff.eval.results import finalized_artifact_digest
from ahadiff.git.repo import repo_write_lock
from ahadiff.review.database import (
    connect_review_db,
    import_cards_from_jsonl,
    initialize_review_db,
    load_finalized_ratchet_history_page,
    load_result_event_by_run_and_id,
    load_result_events_page,
    sync_result_event,
    upsert_concept,
)
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator


@pytest.fixture(autouse=True)
def _clear_capability_level_warning_runs() -> Generator[None]:  # pyright: ignore[reportUnusedFunction]
    routes_runs_module._CAPABILITY_LEVEL_WARNING_RUNS.clear()  # pyright: ignore[reportPrivateUsage]
    yield
    routes_runs_module._CAPABILITY_LEVEL_WARNING_RUNS.clear()  # pyright: ignore[reportPrivateUsage]


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
    timestamp: str | None = None,
    note_json: str | None = None,
) -> ResultEvent:
    return ResultEvent(
        event_id=event_id or f"018f0f52-91c0-7abc-8123-{run_id[-1]:0>12}",
        run_id=run_id,
        event_type="learn",
        timestamp=timestamp or f"2026-04-24T00:00:0{run_id[-1]}Z",
        source_ref=source_ref,
        base_ref="base1234",
        prompt_version="prompt123",
        eval_bundle_version="eval123",
        rubric_version="rubric-v1",
        overall=88.0,
        verdict="PASS",
        status=cast("Any", status),
        weakest_dim="evidence",
        note_json=note_json,
    )


def _write_run(
    state_dir: Path,
    run_id: str,
    *,
    finalized: bool = True,
    content_lang: str = "en",
) -> Path:
    run_path = state_dir / "runs" / run_id
    run_path.mkdir(parents=True, exist_ok=True)
    _write_json(
        run_path / "metadata.json",
        {
            "run_id": run_id,
            "source_kind": "git_ref",
            "source_ref": "abc1234",
            "content_lang": content_lang,
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


def _finalize_run(run_path: Path, run_id: str) -> None:
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


def _write_graphify_metadata(run_path: Path, graphify: dict[str, Any]) -> None:
    metadata = json.loads((run_path / "metadata.json").read_text(encoding="utf-8"))
    metadata["graphify"] = graphify
    _write_json(run_path / "metadata.json", cast("dict[str, Any]", metadata))


def test_healthz_and_loopback_host_guard(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    assert client.get("/healthz").json() == {"ok": True}
    blocked = client.get("/healthz", headers={"host": "evil.example"})

    assert blocked.status_code == 400
    assert blocked.json()["error"] == "host_not_allowed"


def test_loopback_guard_error_responses_include_status(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    cases = (
        (client.get("/healthz", headers={"host": "evil.example"}), "host_not_allowed", 400),
        (
            client.put(
                "/api/locale",
                headers={"X-AhaDiff-Token": "test-token"},
                json={"lang": "zh-CN"},
            ),
            "origin_or_referer_required",
            403,
        ),
        (
            client.put(
                "/api/locale",
                headers={"origin": "https://evil.example", "X-AhaDiff-Token": "test-token"},
                json={"lang": "zh-CN"},
            ),
            "origin_not_allowed",
            403,
        ),
        (
            client.put(
                "/api/locale",
                headers={"referer": "https://evil.example", "X-AhaDiff-Token": "test-token"},
                json={"lang": "zh-CN"},
            ),
            "referer_not_allowed",
            403,
        ),
        (
            client.post(
                "/api/signals/helpfulness",
                headers={
                    "origin": "http://localhost:8765",
                    "X-AhaDiff-Token": "test-token",
                    "content-type": "text/html",
                },
                content=b"{}",
            ),
            "unsupported_media_type",
            415,
        ),
        (
            client.post(
                "/api/signals/helpfulness",
                headers={
                    "origin": "http://localhost:8765",
                    "X-AhaDiff-Token": "test-token",
                    "content-type": "application/json",
                },
                content=b"x" * (1024 * 1024 + 1),
            ),
            "payload_too_large",
            413,
        ),
    )

    for response, error, status in cases:
        assert response.status_code == status
        assert response.json() == {"error": error, "status": status}


def test_proxy_trace_headers_are_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    health = client.get("/healthz", headers={"x-forwarded-for": "203.0.113.10"})
    write = client.put(
        "/api/locale",
        headers={
            "origin": "http://localhost:8765",
            "X-AhaDiff-Token": "test-token",
            "Forwarded": "for=203.0.113.10;proto=http",
        },
        json={"lang": "zh-CN"},
    )

    assert health.status_code == 400
    assert health.json() == {"error": "proxy_headers_not_allowed", "status": 400}
    assert write.status_code == 400
    assert write.json() == {"error": "proxy_headers_not_allowed", "status": 400}


def test_origin_guard_rejects_non_loopback_write_origin(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.put(
        "/api/locale",
        headers={"origin": "https://evil.example", "X-AhaDiff-Token": "test-token"},
        json={"lang": "zh-CN"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "origin_not_allowed"


def test_cors_preflight_allows_loopback_origin_with_headers(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.options(
        "/api/locale",
        headers={
            "origin": "http://localhost:8765",
            "access-control-request-method": "PUT",
            "access-control-request-headers": "X-AhaDiff-Token, Content-Type",
        },
    )

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "http://localhost:8765"
    assert response.headers["access-control-allow-methods"] == (
        "GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE"
    )
    assert response.headers["access-control-allow-headers"] == ("Content-Type, X-AhaDiff-Token")
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["vary"] == "Origin"


def test_cors_preflight_rejects_non_loopback_origin(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.options(
        "/api/locale",
        headers={
            "origin": "https://evil.example",
            "access-control-request-method": "PUT",
            "access-control-request-headers": "X-AhaDiff-Token, Content-Type",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"] == "origin_not_allowed"
    assert "access-control-allow-origin" not in response.headers


def test_cors_actual_response_allows_loopback_origin(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.put(
        "/api/locale",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={"lang": "zh-CN"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8765"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["vary"] == "Origin"


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
    assert accepted.headers["access-control-allow-origin"] == "http://localhost:8765"
    assert accepted.headers["access-control-allow-credentials"] == "true"
    assert "ahadiff_lang=zh-CN" in accepted.headers["set-cookie"]
    assert client.get("/api/locale").json() == {"locale": "zh-CN"}


def test_locale_resolves_cookie_accept_language_and_serve_state(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff", locale="zh-CN")

    from_state = client.get("/api/locale")
    from_accept_language = client.get(
        "/api/locale",
        headers={"accept-language": "en;q=0.1, zh-Hans-CN;q=0.9"},
    )
    client.cookies.set("ahadiff_lang", "zh-CN")
    from_cookie = client.get("/api/locale", headers={"accept-language": "en"})

    assert from_state.json() == {"locale": "zh-CN"}
    assert from_accept_language.json() == {"locale": "zh-CN"}
    assert from_cookie.json() == {"locale": "zh-CN"}


def test_locale_resolver_receives_cli_and_config_lang_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str | None] = {}

    def fake_resolve_locale(**kwargs: str | None) -> Literal["en", "zh-CN"]:
        captured.update(kwargs)
        return "zh-CN"

    monkeypatch.setattr(routes_locale_module, "resolve_locale", fake_resolve_locale)
    app = create_app(
        ServeState(
            state_dir=tmp_path / ".ahadiff",
            token="test-token",
            locale="en",
            cli_lang="zh-CN",
            config_lang="en",
        )
    )
    client = TestClient(app, base_url="http://localhost:8765")

    response = client.get("/api/locale")

    assert response.json() == {"locale": "zh-CN"}
    assert captured["cli_lang"] == "zh-CN"
    assert captured["config_lang"] == "en"


def test_serve_state_locale_update_preserves_runtime_fields(tmp_path: Path) -> None:
    state = ServeState(
        state_dir=tmp_path / ".ahadiff",
        token="token",
        locale="en",
        bind_host="127.0.0.1",
        port=8766,
    ).with_runtime_lock()

    updated = state.with_locale("zh-CN")

    assert updated.locale == "zh-CN"
    assert updated.state_dir == state.state_dir
    assert updated.token == state.token
    assert updated.bind_host == state.bind_host
    assert updated.port == state.port
    assert updated.write_lock is state.write_lock
    assert updated.repo_lock_path == state.repo_lock_path
    assert updated.thread_write_lock is state.thread_write_lock


def test_serve_state_bind_port_and_token_survive_headless_runtime(tmp_path: Path) -> None:
    app = create_app(
        ServeState(
            state_dir=tmp_path / ".ahadiff",
            token="headless-token",
            bind_host="127.0.0.1",
            port=9123,
        )
    )
    client = TestClient(app, base_url="http://127.0.0.1:9123")
    runtime_state = cast("ServeState", app.state.ahadiff)

    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/api/auth/token", headers={"sec-fetch-site": "same-origin"}).json() == {
        "token": "headless-token",
        "expires_at": None,
    }
    assert runtime_state.bind_host == "127.0.0.1"
    assert runtime_state.port == 9123
    assert runtime_state.token == "headless-token"


def test_auth_token_bootstrap_requires_same_origin_browser_signal(tmp_path: Path) -> None:
    app = create_app(
        ServeState(
            state_dir=tmp_path / ".ahadiff",
            token="bootstrap-token",
            bind_host="127.0.0.1",
            port=9123,
        )
    )
    client = TestClient(app, base_url="http://127.0.0.1:9123")

    missing = client.get("/api/auth/token")
    cross_site = client.get("/api/auth/token", headers={"sec-fetch-site": "cross-site"})
    same_origin = client.get("/api/auth/token", headers={"sec-fetch-site": "same-origin"})
    referer = client.get(
        "/api/auth/token",
        headers={"referer": "http://127.0.0.1:9123/app"},
    )

    assert missing.status_code == 403
    assert missing.json()["error"] == "auth token bootstrap requires a same-origin browser request"
    assert cross_site.status_code == 403
    assert same_origin.status_code == 200
    assert same_origin.json()["token"] == "bootstrap-token"
    assert referer.status_code == 200
    assert referer.json()["token"] == "bootstrap-token"


def test_auth_token_bootstrap_accepts_same_origin_post(tmp_path: Path) -> None:
    app = create_app(
        ServeState(
            state_dir=tmp_path / ".ahadiff",
            token="post-bootstrap-token",
            bind_host="127.0.0.1",
            port=9123,
        )
    )
    client = TestClient(app, base_url="http://127.0.0.1:9123")

    allowed = client.post(
        "/api/auth/token",
        headers={"origin": "http://127.0.0.1:9123"},
    )
    blocked = client.post(
        "/api/auth/token",
        headers={"origin": "http://evil.test:9123"},
    )

    assert allowed.status_code == 200
    assert allowed.json() == {"token": "post-bootstrap-token", "expires_at": None}
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "origin_not_allowed"


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


def test_write_routes_allow_https_loopback_origin(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.put(
        "/api/locale",
        headers={"origin": "https://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={"lang": "zh-CN"},
    )

    assert response.status_code == 200
    assert response.json() == {"locale": "zh-CN"}


def test_write_routes_reject_body_larger_than_one_megabyte(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.post(
        "/api/signals/helpfulness",
        headers={
            "origin": "http://localhost:8765",
            "X-AhaDiff-Token": "test-token",
            "content-type": "application/json",
        },
        content=b"x" * (1024 * 1024 + 1),
    )

    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


def test_write_routes_reject_non_json_content_type(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.post(
        "/api/signals/helpfulness",
        headers={
            "origin": "http://localhost:8765",
            "X-AhaDiff-Token": "test-token",
            "content-type": "text/html",
        },
        content=b"{}",
    )

    assert response.status_code == 415
    assert response.json()["error"] == "unsupported_media_type"


def test_write_routes_reject_missing_content_type(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.post(
        "/api/signals/helpfulness",
        headers={
            "origin": "http://localhost:8765",
            "X-AhaDiff-Token": "test-token",
        },
        content=b"{}",
    )

    assert response.status_code == 415
    assert response.json()["error"] == "unsupported_media_type"


def test_runs_only_expose_finalized_runs_and_artifacts(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    _write_run(state_dir, "run-1", finalized=True, content_lang="zh-CN")
    _write_run(state_dir, "run-2", finalized=False)
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    sync_result_event(state_dir / "review.sqlite", _event("run-2"))
    client = _client(state_dir)

    runs = client.get("/api/runs").json()["runs"]
    detail = client.get("/api/run/run-1").json()
    hidden = client.get("/api/run/run-2")
    lesson = client.get("/api/run/run-1/lesson?level=compact").json()

    assert [run["run_id"] for run in runs] == ["run-1"]
    assert runs[0]["content_lang"] == "zh-CN"
    assert detail["run_id"] == "run-1"
    assert detail["content_lang"] == "zh-CN"
    assert detail["source_kind"] == "git_ref"
    assert detail["degraded_flags"] == {"diff_clipped": True}
    assert hidden.status_code == 404
    assert lesson == {
        "run_id": "run-1",
        "artifact_type": "lesson",
        "content": "compact lesson\n",
        "content_lang": "zh-CN",
    }


def test_tmp_run_id_is_filtered_and_rejected_from_artifact_endpoint(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    _write_run(state_dir, "run-1.tmp", finalized=True)
    sync_result_event(state_dir / "review.sqlite", _event("run-1.tmp"))
    client = _client(state_dir)

    runs = client.get("/api/runs").json()["runs"]
    artifact = client.get("/api/run/run-1.tmp/lesson")

    assert runs == []
    assert artifact.status_code in {400, 404}


def test_run_summary_normalizes_invalid_content_lang_to_default(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False, content_lang="fr")
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir, locale="zh-CN")

    runs = client.get("/api/runs").json()["runs"]
    detail = client.get("/api/run/run-1").json()
    lesson = client.get("/api/run/run-1/lesson").json()

    assert [run["run_id"] for run in runs] == ["run-1"]
    assert runs[0]["content_lang"] == "zh-CN"
    assert detail["content_lang"] == "zh-CN"
    assert lesson["content_lang"] == "zh-CN"


def test_run_summary_defaults_capability_level_when_missing(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False)
    metadata = json.loads((run_path / "metadata.json").read_text(encoding="utf-8"))
    metadata.pop("capability_level")
    _write_json(run_path / "metadata.json", cast("dict[str, Any]", metadata))
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    runs = client.get("/api/runs").json()["runs"]

    assert [run["run_id"] for run in runs] == ["run-1"]
    assert runs[0]["capability_level"] == 1


def test_run_artifact_envelope_rejects_non_literal_content_lang() -> None:
    with pytest.raises(ValidationError):
        RunArtifactEnvelope(
            run_id="run-1",
            artifact_type="lesson",
            content="lesson body",
            content_lang=cast("Any", "fr"),
        )


def test_run_artifact_envelope_requires_required_fields() -> None:
    with pytest.raises(ValidationError):
        RunArtifactEnvelope.model_validate(
            {"run_id": "run-1", "artifact_type": "lesson", "content_lang": "en"}
        )


def test_run_detail_projects_graphify_full_from_nested_metadata(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False)
    _write_graphify_metadata(
        run_path,
        {
            "mode": "empty",
            "status": "fresh",
            "notes": ["graph artifact is fresh"],
        },
    )
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    detail = client.get("/api/run/run-1").json()

    assert detail["graphify_mode"] == "full"
    assert detail["graphify_status"] == "fresh"
    assert detail["graphify_notes"] == ["graph artifact is fresh"]


def test_run_detail_projects_graphify_learning_only_from_nested_metadata(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False)
    _write_graphify_metadata(
        run_path,
        {
            "freshness": "stale",
            "notes": ["graph artifact is stale"],
        },
    )
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    detail = client.get("/api/run/run-1").json()

    assert detail["graphify_mode"] == "learning_only"
    assert detail["graphify_status"] == "stale"
    assert detail["graphify_notes"] == ["graph artifact is stale"]


def test_run_detail_ignores_invalid_graphify_status(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False)
    _write_graphify_metadata(run_path, {"status": "invalid"})
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    detail = client.get("/api/run/run-1").json()

    assert detail["graphify_mode"] == "empty"
    assert detail["graphify_status"] is None


def test_run_detail_maps_legacy_source_present_to_stale(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False)
    _write_graphify_metadata(run_path, {"freshness": "source_present"})
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    detail = client.get("/api/run/run-1").json()

    assert detail["graphify_status"] == "stale"
    assert detail["graphify_mode"] == "learning_only"


def test_run_detail_maps_legacy_missing_to_unavailable(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False)
    _write_graphify_metadata(run_path, {"status": "missing"})
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    detail = client.get("/api/run/run-1").json()

    assert detail["graphify_status"] == "unavailable"
    assert detail["graphify_mode"] == "learning_only"


def test_run_detail_projects_graphify_empty_without_nested_metadata(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    _write_run(state_dir, "run-1", finalized=True)
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    detail = client.get("/api/run/run-1").json()

    assert detail["graphify_mode"] == "empty"
    assert detail["graphify_status"] is None
    assert detail["graphify_notes"] is None


def test_artifact_envelopes_include_content_lang_from_run_metadata(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False, content_lang="zh-CN")
    concepts_content = '{"term_key":"retry-loop","display_name":"Retry loop"}\n'
    (run_path / "concepts.jsonl").write_text(concepts_content, encoding="utf-8")
    (run_path / "quiz" / "misconception_cards.jsonl").write_text(
        '{"concept":"retry","misconception":"x","correction":"y","evidence_ref":"src/app.py:1","severity":"low","safety_tags":[],"run_id":"run-1"}\n',
        encoding="utf-8",
    )
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    routes = (
        ("/api/run/run-1/lesson?level=full", "lesson"),
        ("/api/run/run-1/claims", "claims"),
        ("/api/run/run-1/quiz", "quiz"),
        ("/api/run/run-1/misconceptions", "misconceptions"),
        ("/api/run/run-1/diff", "diff"),
        ("/api/run/run-1/concepts", "concepts"),
    )

    for route, artifact_type in routes:
        response = client.get(route)
        payload = response.json()

        assert response.status_code == 200
        assert payload["artifact_type"] == artifact_type
        assert payload["content_lang"] == "zh-CN"

    detail = client.get("/api/run/run-1").json()
    assert "quiz/misconception_cards.jsonl" in detail["artifacts"]


def test_misconceptions_route_returns_404_when_artifact_is_missing(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False)
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1/misconceptions")

    assert response.status_code == 404
    assert response.json()["error"] == "artifact_not_found"


def test_artifact_envelope_uses_none_content_lang_when_metadata_field_missing(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False, content_lang="zh-CN")
    metadata = json.loads((run_path / "metadata.json").read_text(encoding="utf-8"))
    metadata.pop("content_lang")
    _write_json(run_path / "metadata.json", cast("dict[str, Any]", metadata))
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir, locale="zh-CN")

    response = client.get("/api/run/run-1/lesson?level=full")

    assert response.status_code == 200
    assert response.json()["content_lang"] is None


def test_artifact_envelope_uses_none_content_lang_when_metadata_field_null(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False, content_lang="zh-CN")
    metadata = json.loads((run_path / "metadata.json").read_text(encoding="utf-8"))
    metadata["content_lang"] = None
    _write_json(run_path / "metadata.json", cast("dict[str, Any]", metadata))
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir, locale="zh-CN")

    response = client.get("/api/run/run-1/lesson?level=full")

    assert response.status_code == 200
    assert response.json()["content_lang"] is None


def test_artifact_route_returns_413_for_oversized_text_artifact(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False)
    (run_path / "patch.diff").write_text(
        "x" * (routes_runs_module._MAX_TEXT_ARTIFACT_BYTES + 1),  # pyright: ignore[reportPrivateUsage]
        encoding="utf-8",
    )
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1/diff")

    assert response.status_code == 413
    assert response.json()["error"] == "patch.diff exceeds size limit"


def test_get_run_returns_413_for_oversized_json_metadata(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False)
    (run_path / "metadata.json").write_text(
        '{"padding":"' + "x" * routes_runs_module._MAX_JSON_OBJECT_BYTES + '"}\n',  # pyright: ignore[reportPrivateUsage]
        encoding="utf-8",
    )
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1")

    assert response.status_code == 413
    assert response.json()["error"] == "metadata.json exceeds size limit"


def test_concepts_route_returns_413_for_oversized_repo_concepts(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "concepts.jsonl").write_text(
        "x" * (routes_runs_module._MAX_TEXT_ARTIFACT_BYTES + 1),  # pyright: ignore[reportPrivateUsage]
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.get("/api/concepts")

    assert response.status_code == 413
    assert response.json()["error"] == "concepts.jsonl exceeds size limit"


def test_artifact_envelopes_use_none_content_lang_when_metadata_missing(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False)
    (run_path / "metadata.json").unlink()
    (run_path / "concepts.jsonl").write_text(
        '{"term_key":"retry-loop","display_name":"Retry loop"}\n',
        encoding="utf-8",
    )
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir, locale="zh-CN")

    routes = (
        "/api/run/run-1/lesson?level=full",
        "/api/run/run-1/claims",
        "/api/run/run-1/quiz",
        "/api/run/run-1/diff",
        "/api/run/run-1/concepts",
    )

    for route in routes:
        response = client.get(route)
        payload = response.json()

        assert response.status_code == 200
        assert payload["content_lang"] is None


def test_get_run_concepts_returns_content(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=False)
    content = '{"term_key":"retry-loop","display_name":"Retry loop"}\n'
    (run_path / "concepts.jsonl").write_text(content, encoding="utf-8")
    artifact_count, checksum = finalized_artifact_digest(run_path)
    _write_json(
        run_path / "finalized.json",
        {
            "run_id": "run-1",
            "event_id": "018f0f52-91c0-7abc-8123-000000000001",
            "finalized_at": "2026-04-24T00:00:01Z",
            "artifact_count": artifact_count,
            "checksum": checksum,
            "status": "keep",
        },
    )
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1/concepts")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1",
        "artifact_type": "concepts",
        "content": content,
        "content_lang": "en",
    }


def test_get_run_concepts_missing_returns_404(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    _write_run(state_dir, "run-1", finalized=True)
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1/concepts")

    assert response.status_code == 404
    assert response.json()["error"] == "artifact_not_found"


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


def test_load_result_event_by_run_and_id_requires_exact_match(tmp_path: Path) -> None:
    db_path = tmp_path / ".ahadiff" / "review.sqlite"
    event = _event("run-1")
    initialize_review_db(db_path)
    sync_result_event(db_path, event)

    matched = load_result_event_by_run_and_id(
        db_path,
        run_id="run-1",
        event_id=event.event_id,
    )

    assert matched is not None
    assert matched.event_id == event.event_id
    assert matched.run_id == "run-1"
    assert load_result_event_by_run_and_id(db_path, run_id="run-2", event_id=event.event_id) is None
    assert (
        load_result_event_by_run_and_id(db_path, run_id="run-1", event_id="missing-event") is None
    )
    assert (
        load_result_event_by_run_and_id(
            tmp_path / "missing.sqlite",
            run_id="run-1",
            event_id=event.event_id,
        )
        is None
    )


def test_finalized_run_lookup_does_not_use_full_result_event_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    _write_run(state_dir, "run-1", finalized=True)
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    def fail_event_page(*_args: Any, **_kwargs: Any) -> tuple[ResultEvent, ...]:
        raise AssertionError("result_events page scan should not be used for run artifact lookup")

    monkeypatch.setattr(routes_runs_module, "load_result_events_page", fail_event_page)

    detail = client.get("/api/run/run-1")
    lesson = client.get("/api/run/run-1/lesson")

    assert detail.status_code == 200
    assert detail.json()["run_id"] == "run-1"
    assert lesson.status_code == 200
    assert lesson.json()["content"] == "full lesson\n"


def test_run_lists_use_sql_pagination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    for index in range(3):
        run_id = f"run-{index}"
        _write_run(state_dir, run_id, finalized=True)
        sync_result_event(
            db_path,
            _event(
                run_id,
                event_id=f"018f0f52-91c0-7abc-8123-{index:012d}",
                timestamp=f"2026-04-24T00:00:0{index}Z",
            ),
        )
    calls: list[tuple[int, tuple[str, str] | None]] = []

    def recording_page(*args: Any, **kwargs: Any) -> tuple[ResultEvent, ...]:
        calls.append(
            (cast("int", kwargs["limit"]), cast("tuple[str, str] | None", kwargs["before"]))
        )
        return load_result_events_page(*args, **kwargs)

    monkeypatch.setattr(routes_runs_module, "load_result_events_page", recording_page)
    client = _client(state_dir)

    runs = client.get("/api/runs").json()["runs"]

    assert [run["run_id"] for run in runs] == ["run-2", "run-1", "run-0"]
    assert calls == [(routes_runs_module._MAX_LIST_RUNS, None)]  # pyright: ignore[reportPrivateUsage]


def test_run_lists_page_without_full_finalized_directory_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    for index in range(1001):
        run_id = f"run-{index:04d}"
        event_id = f"018f0f52-91c0-7abc-8123-{index:012d}"
        run_path = state_dir / "runs" / run_id
        run_path.mkdir(parents=True)
        _write_json(
            run_path / "metadata.json",
            {
                "run_id": run_id,
                "source_kind": "git_ref",
                "source_ref": f"abc{index:04d}",
                "content_lang": "en",
                "capability_level": 2,
                "degraded_flags": {},
            },
        )
        (run_path / "patch.diff").write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
        artifact_count, checksum = finalized_artifact_digest(run_path)
        timestamp = f"2026-04-24T{index // 3600:02d}:{index // 60 % 60:02d}:{index % 60:02d}Z"
        _write_json(
            run_path / "finalized.json",
            {
                "run_id": run_id,
                "event_id": event_id,
                "finalized_at": timestamp,
                "artifact_count": artifact_count,
                "checksum": checksum,
                "status": "keep",
            },
        )
        sync_result_event(
            db_path,
            _event(
                run_id,
                source_ref=f"abc{index:04d}",
                event_id=event_id,
                timestamp=timestamp,
            ),
        )
    calls: list[int] = []

    runs_dir = state_dir / "runs"

    original_iterdir = Path.iterdir

    def fail_runs_iterdir(self: Path) -> Iterator[Path]:
        if self == runs_dir:
            raise AssertionError("list pagination must not scan all finalized run directories")
        return original_iterdir(self)

    original_load_page = routes_runs_module.load_result_events_page

    def recording_page(*args: Any, **kwargs: Any) -> tuple[ResultEvent, ...]:
        calls.append(cast("int", kwargs["limit"]))
        return original_load_page(*args, **kwargs)

    monkeypatch.setattr(Path, "iterdir", fail_runs_iterdir)
    monkeypatch.setattr(routes_runs_module, "load_result_events_page", recording_page)
    client = _client(state_dir)

    first = client.get("/api/runs?limit=10").json()
    second = client.get(f"/api/runs?limit=10&cursor={first['next_cursor']}").json()

    assert len(first["runs"]) == 10
    assert len(second["runs"]) == 10
    assert first["runs"][0]["run_id"] == "run-1000"
    assert second["runs"][0]["run_id"] == "run-0990"
    assert calls[:2] == [10, 10]


def test_ratchet_history_uses_sql_pagination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    for index in range(3):
        run_id = f"run-{index}"
        _write_run(state_dir, run_id, finalized=True)
        sync_result_event(
            db_path,
            _event(
                run_id,
                event_id=f"018f0f52-91c0-7abc-8123-{index:012d}",
                timestamp=f"2026-04-24T00:00:0{index}Z",
                status="keep",
            ),
        )
    calls: list[tuple[int, tuple[str, str] | None]] = []

    def recording_page(*args: Any, **kwargs: Any) -> tuple[ResultEvent, ...]:
        calls.append(
            (cast("int", kwargs["limit"]), cast("tuple[str, str] | None", kwargs["before"]))
        )
        return load_finalized_ratchet_history_page(*args, **kwargs)

    monkeypatch.setattr(routes_runs_module, "load_finalized_ratchet_history_page", recording_page)
    client = _client(state_dir)

    history = client.get("/api/ratchet/history").json()["history"]

    assert [entry["run_id"] for entry in history] == ["run-2", "run-1", "run-0"]
    assert calls == [(routes_runs_module._MAX_RATCHET_HISTORY, None)]  # pyright: ignore[reportPrivateUsage]


def test_ratchet_history_returns_restricted_note_json(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    _write_run(state_dir, "run-1", finalized=True)
    sync_result_event(
        db_path,
        _event(
            "run-1",
            status="keep",
            note_json=json.dumps(
                {
                    "phase25": True,
                    "phase25_note": "PHASE25: consecutive_discard_count=2",
                    "trigger_reason": "consecutive_discard_count=2",
                    "worktree_path": "/tmp/ahadiff-sensitive-worktree",
                    "target_prompt": "internal prompt text",
                    "stash_ref": "commit-sha",
                },
                sort_keys=True,
            ),
        ),
    )
    client = _client(state_dir)

    entry = client.get("/api/ratchet/history").json()["history"][0]
    detail = client.get("/api/run/run-1").json()
    note = json.loads(entry["note_json"])
    detail_note = json.loads(detail["note_json"])

    assert note == {
        "phase25": True,
        "phase25_note": "PHASE25: consecutive_discard_count=2",
        "trigger_reason": "consecutive_discard_count=2",
    }
    assert detail_note == note


def test_ratchet_history_drops_oversized_or_deep_note_json(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    _write_run(state_dir, "run-1", finalized=True)
    _write_run(state_dir, "run-2", finalized=True)
    sync_result_event(
        db_path,
        _event(
            "run-1",
            status="keep",
            note_json=json.dumps({"phase25_note": "x" * 70_000}),
        ),
    )
    sync_result_event(
        db_path,
        _event(
            "run-2",
            status="keep",
            note_json="[" * 20_000 + "0" + "]" * 20_000,
        ),
    )
    client = _client(state_dir)

    history = client.get("/api/ratchet/history").json()["history"]

    assert {entry["run_id"]: entry["note_json"] for entry in history} == {
        "run-1": None,
        "run-2": None,
    }


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


def test_oversized_finalized_marker_is_hidden_from_list_without_500(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=True)
    (run_path / "finalized.json").write_text(
        '{"padding":"' + "x" * routes_runs_module._MAX_JSON_OBJECT_BYTES + '"}\n',  # pyright: ignore[reportPrivateUsage]
        encoding="utf-8",
    )
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    assert client.get("/api/runs").json() == {"runs": []}
    response = client.get("/api/run/run-1")

    assert response.status_code == 400
    assert "finalized marker is invalid" in response.json()["error"]


def test_malformed_run_metadata_is_hidden_from_list_without_500(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=True)
    (run_path / "metadata.json").write_text("[]\n", encoding="utf-8")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    assert client.get("/api/runs").json() == {"runs": []}
    response = client.get("/api/run/run-1")

    assert response.status_code == 400
    assert "finalized marker is invalid" in response.json()["error"]


def test_non_object_finalized_marker_is_hidden_without_500(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1", finalized=True)
    (run_path / "finalized.json").write_text("[]\n", encoding="utf-8")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    assert client.get("/api/runs").json() == {"runs": []}
    response = client.get("/api/run/run-1")

    assert response.status_code == 400
    assert "finalized marker is invalid" in response.json()["error"]


@pytest.mark.skipif(
    not hasattr(routes_runs_module.os, "symlink")
    or not hasattr(routes_runs_module.os, "O_NOFOLLOW"),
    reason="requires POSIX symlink no-follow support",
)
def test_bounded_finalized_artifact_digest_rejects_symlink_swap_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.core.errors import InputError

    state_dir = tmp_path / ".ahadiff"
    run_path = _write_run(state_dir, "run-1", finalized=False)
    artifact_path = run_path / "artifact.txt"
    artifact_path.write_text("safe artifact\n", encoding="utf-8")
    outside_path = tmp_path / "outside.txt"
    outside_path.write_text("outside\n", encoding="utf-8")
    original_open = routes_runs_module.os.open
    swapped = False

    def swapping_open(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if Path(path) == artifact_path and not swapped:
            swapped = True
            artifact_path.unlink()
            routes_runs_module.os.symlink(outside_path, artifact_path)
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(routes_runs_module.os, "open", swapping_open)

    with pytest.raises(InputError, match="symlink|changed during validation"):
        routes_runs_module._bounded_finalized_artifact_digest(run_path)  # pyright: ignore[reportPrivateUsage]

    assert swapped is True


def test_bounded_finalized_artifact_digest_rejects_reparse_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.core.errors import InputError

    run_path = tmp_path / "run_reparse_dir"
    reparse_dir = run_path / "junction"
    reparse_dir.mkdir(parents=True)
    (reparse_dir / "outside-secret.txt").write_text("outside-secret\n", encoding="utf-8")

    def fake_has_reparse_point(path_stat: object) -> bool:
        return routes_runs_module.stat.S_ISDIR(cast("Any", path_stat).st_mode)

    monkeypatch.setattr(
        routes_runs_module,
        "_has_windows_reparse_point",
        fake_has_reparse_point,
    )

    with pytest.raises(InputError, match="Windows reparse point"):
        routes_runs_module._bounded_finalized_artifact_digest(run_path)  # pyright: ignore[reportPrivateUsage]


def test_symlink_run_directory_is_not_served(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    outside_state_dir = tmp_path / "outside" / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    outside_run_path = _write_run(outside_state_dir, "run-1", finalized=True)
    (state_dir / "runs").mkdir(parents=True)
    (state_dir / "runs" / "run-1").symlink_to(outside_run_path, target_is_directory=True)
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    assert client.get("/api/runs").json() == {"runs": []}
    response = client.get("/api/run/run-1/lesson")

    assert response.status_code == 404
    assert "finalized run does not exist" in response.json()["error"]


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


def test_run_lists_validate_finalized_marker_run_event_binding(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    run_1_path = _write_run(state_dir, "run-1", finalized=False)
    _write_run(state_dir, "run-2", finalized=False)
    run_2_event_id = "018f0f52-91c0-7abc-8123-000000000002"
    artifact_count, checksum = finalized_artifact_digest(run_1_path)
    _write_json(
        run_1_path / "finalized.json",
        {
            "run_id": "run-1",
            "event_id": run_2_event_id,
            "finalized_at": "2026-04-24T00:00:01Z",
            "artifact_count": artifact_count,
            "checksum": checksum,
            "status": "keep",
        },
    )
    sync_result_event(db_path, _event("run-2", event_id=run_2_event_id, status="keep"))
    client = _client(state_dir)

    runs = client.get("/api/runs")
    history = client.get("/api/ratchet/history")

    assert runs.json() == {"runs": []}
    assert history.json() == {"history": []}


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


def test_runs_source_kind_filter_stops_after_max_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    for index in range(1, 4):
        run_id = f"run-{index}"
        _write_run(state_dir, run_id, finalized=True)
        sync_result_event(db_path, _event(run_id, status="keep"))
    original_load_page = routes_runs_module.load_result_events_page
    page_calls = 0

    def spy_load_page(*args: Any, **kwargs: Any) -> tuple[ResultEvent, ...]:
        nonlocal page_calls
        page_calls += 1
        return original_load_page(*args, **kwargs)

    monkeypatch.setattr(routes_runs_module, "_MAX_LIST_RUN_PAGES", 2)
    monkeypatch.setattr(routes_runs_module, "load_result_events_page", spy_load_page)
    client = _client(state_dir)

    response = client.get("/api/runs?source_kind=patch_file&page_size=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runs"] == []
    assert payload["next_cursor"]
    assert page_calls == 2


def test_run_and_ratchet_lists_are_capped_to_newest_500(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    for index in range(505):
        run_id = f"run-{index:03d}"
        event_id = f"018f0f52-91c0-7abc-8123-{index:012d}"
        run_path = state_dir / "runs" / run_id
        run_path.mkdir(parents=True)
        _write_json(
            run_path / "metadata.json",
            {
                "run_id": run_id,
                "source_kind": "git_ref",
                "source_ref": f"abc{index:03d}",
                "content_lang": "en",
                "capability_level": 2,
                "degraded_flags": {},
            },
        )
        (run_path / "patch.diff").write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
        artifact_count, checksum = finalized_artifact_digest(run_path)
        _write_json(
            run_path / "finalized.json",
            {
                "run_id": run_id,
                "event_id": event_id,
                "finalized_at": f"2026-04-24T00:{index // 60:02d}:{index % 60:02d}Z",
                "artifact_count": artifact_count,
                "checksum": checksum,
                "status": "keep",
            },
        )
        sync_result_event(
            db_path,
            _event(
                run_id,
                source_ref=f"abc{index:03d}",
                event_id=event_id,
                timestamp=f"2026-04-24T00:{index // 60:02d}:{index % 60:02d}Z",
            ),
        )
    client = _client(state_dir)

    runs = client.get("/api/runs").json()["runs"]
    history = client.get("/api/ratchet/history").json()["history"]

    assert len(runs) == 500
    assert len(history) == 500
    assert runs[0]["run_id"] == "run-504"
    assert history[0]["run_id"] == "run-504"
    assert runs[-1]["run_id"] == "run-005"
    assert history[-1]["run_id"] == "run-005"


def test_concepts_route_does_not_follow_symlink(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    target = tmp_path / "outside-concepts.jsonl"
    target.write_text('{"concept":"outside"}\n', encoding="utf-8")
    (state_dir / "concepts.jsonl").symlink_to(target)
    client = _client(state_dir)

    assert client.get("/api/concepts").json() == {"artifact_type": "concepts", "content": ""}


def test_concepts_route_supports_limit_and_cursor(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "concepts.jsonl").write_text(
        "".join(
            json.dumps({"term_key": f"term-{index}", "concept": f"term {index}"}) + "\n"
            for index in range(3)
        ),
        encoding="utf-8",
    )
    client = _client(state_dir)

    first = client.get("/api/concepts?limit=2").json()
    second = client.get(f"/api/concepts?limit=2&cursor={first['next_cursor']}").json()

    assert [json.loads(line)["term_key"] for line in first["content"].splitlines()] == [
        "term-0",
        "term-1",
    ]
    assert first["next_cursor"] == "jsonl:3"
    assert [json.loads(line)["term_key"] for line in second["content"].splitlines()] == ["term-2"]
    assert "next_cursor" not in second


def test_concepts_route_reads_db_backed_storage_without_jsonl(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    for index in range(3):
        upsert_concept(
            db_path,
            term_key=f"db-term-{index}",
            concept=f"db term {index}",
            run_id="run-a",
            source_ref="abc123",
            branch_hint=None,
            related_claims=(),
            file_refs=(),
        )
    client = _client(state_dir)

    first = client.get("/api/concepts?limit=2").json()
    second = client.get(f"/api/concepts?limit=2&cursor={first['next_cursor']}").json()

    assert [json.loads(line)["term_key"] for line in first["content"].splitlines()] == [
        "db-term-0",
        "db-term-1",
    ]
    assert first["next_cursor"] == "db:db-term-1"
    assert [json.loads(line)["term_key"] for line in second["content"].splitlines()] == [
        "db-term-2"
    ]
    assert "next_cursor" not in second


def test_concepts_route_reparse_jsonl_uses_db_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    upsert_concept(
        db_path,
        term_key="db-only",
        concept="db only",
        run_id="run-a",
        source_ref="abc123",
        branch_hint=None,
        related_claims=(),
        file_refs=(),
    )
    (state_dir / "concepts.jsonl").write_text(
        json.dumps({"term_key": "blocked-jsonl", "concept": "blocked"}) + "\n",
        encoding="utf-8",
    )

    def _is_reparse(path_stat: object) -> bool:
        del path_stat
        return True

    monkeypatch.setattr(routes_runs_module, "_has_windows_reparse_point", _is_reparse)
    monkeypatch.setattr("ahadiff.core.paths._has_windows_reparse_point", _is_reparse)
    client = _client(state_dir)

    response = client.get("/api/concepts")

    assert response.status_code == 200
    entries = [json.loads(line) for line in response.json()["content"].splitlines()]
    assert [entry["term_key"] for entry in entries] == ["db-only"]


def test_run_routes_use_anyio_threadpool_for_file_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    _write_run(state_dir, "run-1", finalized=True)
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    calls: list[str] = []

    async def recording_run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
        del kwargs
        calls.append(getattr(func, "__name__", repr(func)))
        return func(*args)

    monkeypatch.setattr(routes_runs_module.to_thread, "run_sync", recording_run_sync)
    client = _client(state_dir)

    assert client.get("/api/runs").status_code == 200
    assert client.get("/api/run/run-1").status_code == 200
    assert client.get("/api/run/run-1/lesson").status_code == 200

    assert "_list_runs_payload" in calls
    assert "_run_detail_payload" in calls
    assert any("lambda" in call for call in calls)


def test_read_text_capped_checks_size_from_open_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visible_path = tmp_path / "artifact.txt"
    visible_path.write_text("ok\n", encoding="utf-8")
    original_lstat = routes_runs_module.os.lstat
    grew_after_lstat = False

    def growing_lstat(path: Any) -> Any:
        nonlocal grew_after_lstat
        result = original_lstat(path)
        if Path(cast("str", path)) == visible_path:
            visible_path.write_text("too large\n", encoding="utf-8")
            grew_after_lstat = True
        return result

    monkeypatch.setattr(routes_runs_module.os, "lstat", growing_lstat)
    read_text_capped = cast("Any", routes_runs_module._read_text_capped)  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(routes_runs_module.HTTPException) as exc_info:
        read_text_capped(visible_path, max_bytes=4)

    assert grew_after_lstat is True
    assert exc_info.value.status_code == 413


def test_read_text_capped_rejects_path_swap_after_lstat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.core.errors import InputError

    visible_path = tmp_path / "artifact.txt"
    visible_path.write_text("safe\n", encoding="utf-8")
    outside_path = tmp_path / "outside-secret.txt"
    outside_path.write_text("outside-secret\n", encoding="utf-8")
    original_open = routes_runs_module.os.open

    def fake_open(path: Any, flags: int, mode: int = 0o777) -> int:
        if Path(cast("str", path)) == visible_path:
            return original_open(str(outside_path), flags, mode)
        return original_open(path, flags, mode)

    monkeypatch.setattr(routes_runs_module.os, "open", fake_open)
    read_text_capped = cast("Any", routes_runs_module._read_text_capped)  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(InputError, match="changed during validation"):
        read_text_capped(visible_path, max_bytes=1024)


def test_read_text_capped_rejects_hardlinked_file(tmp_path: Path) -> None:
    if not hasattr(os, "link"):
        pytest.skip("hardlinks unavailable on this platform")

    from ahadiff.core.errors import InputError

    outside_path = tmp_path / "outside-secret.txt"
    outside_path.write_text("outside-secret\n", encoding="utf-8")
    visible_path = tmp_path / "artifact.txt"
    os.link(outside_path, visible_path)

    read_text_capped = cast("Any", routes_runs_module._read_text_capped)  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(InputError, match="hardlink"):
        read_text_capped(visible_path, max_bytes=1024)


@pytest.mark.skipif(
    not hasattr(routes_runs_module.os, "symlink"), reason="requires symlink support"
)
def test_read_text_capped_rejects_symlink_when_open_may_follow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.core.errors import InputError

    target_path = tmp_path / "target.txt"
    target_path.write_text("target\n", encoding="utf-8")
    link_path = tmp_path / "artifact-link.txt"
    routes_runs_module.os.symlink(target_path, link_path)
    original_open = routes_runs_module.os.open
    nofollow_flag = getattr(routes_runs_module.os, "O_NOFOLLOW", 0)

    def following_open(path: Any, flags: int, mode: int = 0o777) -> int:
        if nofollow_flag:
            flags &= ~nofollow_flag
        return original_open(path, flags, mode)

    monkeypatch.setattr(routes_runs_module.os, "open", following_open)
    read_text_capped = routes_runs_module._read_text_capped  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(InputError, match="symlink"):
        read_text_capped(link_path, max_bytes=1024)


@pytest.mark.skipif(
    not hasattr(routes_runs_module.os, "symlink"), reason="requires symlink support"
)
def test_hash_bounded_finalized_artifact_rejects_symlink_when_open_may_follow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.core.errors import InputError

    target_path = tmp_path / "target.txt"
    target_path.write_text("target\n", encoding="utf-8")
    link_path = tmp_path / "artifact-link.txt"
    routes_runs_module.os.symlink(target_path, link_path)
    expected_stat = target_path.stat()
    original_open = routes_runs_module.os.open
    nofollow_flag = getattr(routes_runs_module.os, "O_NOFOLLOW", 0)

    def following_open(path: Any, flags: int, mode: int = 0o777) -> int:
        if nofollow_flag:
            flags &= ~nofollow_flag
        return original_open(path, flags, mode)

    monkeypatch.setattr(routes_runs_module.os, "open", following_open)
    hash_artifact = routes_runs_module._hash_bounded_finalized_artifact  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(InputError, match="symlink"):
        hash_artifact(link_path, "artifact-link.txt", expected_stat)


def test_bounded_finalized_artifact_digest_rejects_hardlinked_artifact(tmp_path: Path) -> None:
    if not hasattr(os, "link"):
        pytest.skip("hardlinks unavailable on this platform")

    from ahadiff.core.errors import InputError

    outside_path = tmp_path / "outside-secret.txt"
    outside_path.write_text("outside-secret\n", encoding="utf-8")
    run_path = tmp_path / "run_hardlink"
    run_path.mkdir()
    artifact_path = run_path / "artifact.txt"
    os.link(outside_path, artifact_path)

    with pytest.raises(InputError, match="hardlinked artifact"):
        routes_runs_module._bounded_finalized_artifact_digest(  # pyright: ignore[reportPrivateUsage]
            run_path
        )


def test_review_queue_uses_anyio_threadpool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    calls: list[str] = []

    async def recording_run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
        del kwargs
        calls.append(getattr(func, "__name__", repr(func)))
        return func(*args)

    monkeypatch.setattr(routes_review_module.to_thread, "run_sync", recording_run_sync)
    client = _client(state_dir)

    assert client.get("/api/review/queue").status_code == 200

    assert calls == ["_review_queue_sync"]


def test_serve_repo_write_lock_follows_thread_then_repo_lock_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class RecordingThreadLock:
        def __enter__(self) -> None:
            events.append("thread_enter")

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb
            events.append("thread_exit")

    @contextmanager
    def fake_repo_write_lock(lock_path: Path, *, command: str) -> Iterator[Path]:
        del command
        events.append("repo_enter")
        yield lock_path
        events.append("repo_exit")

    state = ServeState(
        state_dir=tmp_path / ".ahadiff",
        token="test-token",
        repo_lock_path=tmp_path / ".ahadiff" / "ahadiff.lock",
        thread_write_lock=cast("Any", RecordingThreadLock()),
    )
    monkeypatch.setattr(serve_lock_module, "repo_write_lock", fake_repo_write_lock)

    with serve_lock_module.serve_repo_write_lock(state, command="test"):
        events.append("inside")

    assert events == ["thread_enter", "repo_enter", "inside", "repo_exit", "thread_exit"]


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


def test_signal_write_respects_repo_write_lock(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    payload = {"claim_id": "claim-1", "idempotency_key": "mark:claim-1:wrong"}

    with repo_write_lock(state_dir / "ahadiff.lock", command="db restore"):
        blocked = client.post(
            "/api/signals/mark-wrong",
            headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
            json=payload,
        )

    accepted = client.post(
        "/api/signals/mark-wrong",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json=payload,
    )

    assert blocked.status_code == 400
    assert "another ahadiff process is already running" in blocked.json()["error"]
    assert accepted.status_code == 200
    assert accepted.json() == {"inserted": True}


def test_quiz_answer_signal_validates_dto_and_records_payload(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    payload = {
        "idempotency_key": "quiz:run-1:q1",
        "quiz_id": "q1",
        "choice": "B",
        "correct": True,
    }

    first = client.post(
        "/api/signals/quiz-answer",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json=payload,
    )
    second = client.post(
        "/api/signals/quiz-answer",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json=payload,
    )

    assert first.json() == {"inserted": True}
    assert second.json() == {"inserted": False}
    with connect_review_db(state_dir / "review.sqlite") as connection:
        row = connection.execute(
            "SELECT signal_type, payload_json FROM learning_signals"
        ).fetchone()
    assert row["signal_type"] == "quiz_answer"
    assert json.loads(row["payload_json"]) == {
        "choice": "B",
        "correct": True,
        "quiz_id": "q1",
    }


def test_empty_idempotency_key_is_rejected_before_signal_write(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/signals/mark-wrong",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={"claim_id": "claim-1", "idempotency_key": ""},
    )

    assert response.status_code == 422
    assert response.json()["error"][0]["loc"] == ["idempotency_key"]


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        (
            "/api/signals/mark-wrong",
            {"claim_id": "", "idempotency_key": "mark-empty-claim"},
            "claim_id",
        ),
        (
            "/api/signals/srs-review",
            {"card_id": "", "answer": "hard", "idempotency_key": "review-empty-card"},
            "card_id",
        ),
        (
            "/api/review/rate",
            {"card_id": "", "answer": "good", "idempotency_key": "rate-empty-card"},
            "card_id",
        ),
        (
            "/api/review/queue-state",
            {"card_id": "", "state": "archived"},
            "card_id",
        ),
    ],
)
def test_signal_write_rejects_empty_identifiers_before_db_write(
    tmp_path: Path,
    path: str,
    payload: dict[str, object],
    field: str,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        path,
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"][0]["loc"] == [field]
    assert not (state_dir / "review.sqlite").exists()


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
    with connect_review_db(db_path) as connection:
        payload = connection.execute(
            "SELECT payload_json FROM learning_signals WHERE idempotency_key = 'review-1'"
        ).fetchone()
    assert payload is not None
    assert json.loads(str(payload[0]))["peeked_this_session"] is False


def test_srs_review_rejects_peeked_good_answer(tmp_path: Path) -> None:
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
        json={
            "card_id": "card-1",
            "answer": "good",
            "peeked_this_session": True,
            "idempotency_key": "review-peeked-good",
        },
    )

    assert response.status_code == 400
    assert "peeked cards cannot be reviewed as good or easy" in response.json()["error"]


def test_review_queue_get_is_public_and_rate_requires_token(tmp_path: Path) -> None:
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

    queue = client.get("/api/review/queue")
    denied = client.post(
        "/api/review/rate",
        headers={"origin": "http://localhost:8765"},
        json={"card_id": "card-1", "answer": "good", "idempotency_key": "review-api-1"},
    )
    accepted = client.post(
        "/api/review/rate",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={"card_id": "card-1", "answer": "good", "idempotency_key": "review-api-1"},
    )
    duplicate = client.post(
        "/api/review/rate",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={"card_id": "card-1", "answer": "good", "idempotency_key": "review-api-1"},
    )

    assert queue.status_code == 200
    assert queue.json()["cards"][0]["card_id"] == "card-1"
    assert denied.status_code == 403
    assert "X-AhaDiff-Token" in denied.json()["error"]
    assert accepted.status_code == 200
    assert accepted.json()["inserted"] is True
    assert accepted.json()["review"]["rating"] == 3
    assert duplicate.json() == {"inserted": False}


def test_review_queue_state_updates_card_without_review_log(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    cards_path = state_dir / "runs" / "run-1" / "quiz" / "cards.jsonl"
    card = ReviewCard(
        card_id="card-archive",
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

    denied = client.post(
        "/api/review/queue-state",
        headers={"origin": "http://localhost:8765"},
        json={"card_id": "card-archive", "state": "archived"},
    )
    accepted = client.post(
        "/api/review/queue-state",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={"card_id": "card-archive", "state": "archived"},
    )

    assert denied.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json() == {
        "card_id": "card-archive",
        "state": "archived",
        "updated": True,
    }
    with connect_review_db(db_path) as connection:
        row = connection.execute(
            "SELECT card_state, archived_at_utc FROM cards WHERE id = 'card-archive'"
        ).fetchone()
        log_count = connection.execute("SELECT COUNT(*) FROM review_logs").fetchone()[0]
    assert row["card_state"] == "archived"
    assert row["archived_at_utc"] is not None
    assert log_count == 0


def test_review_rate_rejects_peeked_easy_answer(tmp_path: Path) -> None:
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
        "/api/review/rate",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={
            "card_id": "card-1",
            "answer": "easy",
            "peeked_this_session": True,
            "idempotency_key": "review-api-peeked",
        },
    )

    assert response.status_code == 400
    assert "peeked cards cannot be reviewed as good or easy" in response.json()["error"]


def test_review_queue_returns_empty_on_legacy_db_without_triggering_migration(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    db_path = state_dir / "review.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE result_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL
            )
            """
        )
    client = _client(state_dir)

    queue = client.get("/api/review/queue")

    assert queue.status_code == 200
    assert queue.json() == {"cards": []}
    with sqlite3.connect(db_path) as connection:
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert user_version == 0
    assert "cards" not in tables


def test_malformed_origin_is_rejected_without_500(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.put(
        "/api/locale",
        headers={"origin": "http://localhost:bad", "X-AhaDiff-Token": "test-token"},
        json={"lang": "zh-CN"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "origin_not_allowed"


def test_malformed_json_write_body_returns_400(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.put(
        "/api/locale",
        headers={
            "content-type": "application/json",
            "origin": "http://localhost:8765",
            "X-AhaDiff-Token": "test-token",
        },
        content="{not-json",
    )

    assert response.status_code == 400
    assert "Expecting property name enclosed in double quotes" in response.json()["error"]


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


def test_api_unknown_returns_json_404(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    viewer_dist = tmp_path / "viewer" / "dist"
    viewer_dist.mkdir(parents=True)
    (viewer_dist / "index.html").write_text("<h1>AhaDiff</h1>\n", encoding="utf-8")
    app = create_app(ServeState(state_dir=state_dir, token="test-token"), viewer_dist=viewer_dist)
    client = TestClient(app, base_url="http://localhost:8765")

    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert "application/json" in response.headers["content-type"]
    assert response.json()["error"] == "not_found"
    assert response.json()["path"] == "/api/does-not-exist"


def test_api_unknown_post_returns_json_404(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.post(
        "/api/not-a-real-endpoint",
        headers={"origin": "http://localhost:8765"},
    )

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_helpfulness_signal_records_section_id_and_rating(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    payload = {
        "idempotency_key": "help:run-1:section-1",
        "target_kind": "file",
        "target_id": "section-1",
        "payload": {"rating": 5, "section_id": "sec-intro"},
    }

    first = client.post(
        "/api/signals/helpfulness",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json=payload,
    )
    second = client.post(
        "/api/signals/helpfulness",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json=payload,
    )

    assert first.json() == {"inserted": True}
    assert second.json() == {"inserted": False}
    with connect_review_db(state_dir / "review.sqlite") as connection:
        row = connection.execute(
            "SELECT signal_type, payload_json FROM learning_signals"
        ).fetchone()
    assert row["signal_type"] == "helpfulness"
    assert json.loads(row["payload_json"]) == {
        "target_kind": "file",
        "target_id": "section-1",
        "payload": {"rating": 5, "section_id": "sec-intro"},
    }


def test_helpfulness_signal_invalid_payload(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/signals/helpfulness",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={"idempotency_key": "help:run-1:section-1"},
    )

    assert response.status_code == 422
    assert response.json()["error"][0]["loc"] == ["target_id"]


def test_helpfulness_signal_invalid_section_target_id_returns_422(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/signals/helpfulness",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={
            "idempotency_key": "help:run-1:no-separator",
            "target_kind": "section",
            "target_id": "no_separator",
            "payload": {"helpful": True},
        },
    )

    assert response.status_code == 422
    error = response.json()["error"][0]
    assert "ctx" not in error
    assert "target_id must contain ':'" in error["msg"]


def test_helpfulness_signal_normalizes_section_target_id(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/signals/helpfulness",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={
            "idempotency_key": "help:run-1:intro",
            "target_kind": "section",
            "target_id": "  run1  :  intro  ",
            "payload": {"helpful": True},
        },
    )

    assert response.json() == {"inserted": True}
    with connect_review_db(state_dir / "review.sqlite") as connection:
        row = connection.execute("SELECT payload_json FROM learning_signals").fetchone()
    assert json.loads(row["payload_json"])["target_id"] == "run1:intro"


def test_helpfulness_signal_rejects_non_finite_numbers(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/signals/helpfulness",
        headers={
            "content-type": "application/json",
            "origin": "http://localhost:8765",
            "X-AhaDiff-Token": "test-token",
        },
        content=(
            '{"idempotency_key":"help:run-1:section-1","target_id":"section-1",'
            '"payload":{"rating":NaN}}'
        ),
    )

    assert response.status_code == 400
    assert "finite" in response.json()["error"]


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


def test_middleware_rejects_unsupported_content_type(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.post(
        "/api/signals/mark-wrong",
        headers={
            "content-type": "text/html",
            "origin": "http://localhost:8765",
            "X-AhaDiff-Token": "test-token",
        },
        content="<html></html>",
    )

    assert response.status_code == 415
    assert response.json()["error"] == "unsupported_media_type"


def test_middleware_rejects_oversized_body(tmp_path: Path) -> None:
    client = _client(tmp_path / ".ahadiff")

    response = client.post(
        "/api/signals/mark-wrong",
        headers={
            "content-type": "application/json",
            "content-length": "2000000",
            "origin": "http://localhost:8765",
            "X-AhaDiff-Token": "test-token",
        },
        content='{"claim_id":"claim-1","idempotency_key":"test"}',
    )

    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


def test_middleware_rejects_malformed_ipv6_origin() -> None:
    assert (
        middleware_module._is_allowed_origin(  # pyright: ignore[reportPrivateUsage]
            "http://[::1",
            expected_port=8765,
        )
        is False
    )
    assert (
        middleware_module._is_allowed_preflight_origin(  # pyright: ignore[reportPrivateUsage]
            "http://[::1",
            expected_port=8765,
        )
        is False
    )


def test_middleware_preflight_respects_expected_port() -> None:
    assert (
        middleware_module._is_allowed_preflight_origin(  # pyright: ignore[reportPrivateUsage]
            "http://[::1]:9999",
            expected_port=8765,
        )
        is False
    )
    assert (
        middleware_module._is_allowed_preflight_origin(  # pyright: ignore[reportPrivateUsage]
            "http://[::1]:8765",
            expected_port=8765,
        )
        is True
    )


def test_load_valid_finalized_marker_rejects_non_finite_json(tmp_path: Path) -> None:
    run_path = tmp_path / "run_0123456789abcdef0123456789abcdef"
    run_path.mkdir()
    (run_path / "finalized.json").write_text(
        (
            '{"run_id":"run_0123456789abcdef0123456789abcdef","event_id":"evt-1",'
            '"finalized_at":NaN,"artifact_count":1,"checksum":"abc"}'
        ),
        encoding="utf-8",
    )

    marker = routes_runs_module._load_valid_finalized_marker(  # pyright: ignore[reportPrivateUsage]
        run_path
    )

    assert marker is None


# --- F3 regression: pagination cursor length limit ---


def test_cursor_exceeding_max_length_returns_400(tmp_path: Path) -> None:
    """Overly long cursor values are rejected before touching the DB."""
    client = _client(tmp_path)
    long_cursor = "A" * 600
    response = client.get(f"/api/runs?cursor={long_cursor}")
    assert response.status_code == 400
    assert "maximum length" in response.json()["error"]


# --- 6A: /api/watch/status ---


def test_watch_status_disabled_by_default(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.get("/api/watch/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["running"] is False
    assert data["pending_changes"] == 0
    assert data["restartable"] is True
    assert data["stop_timed_out"] is False
    assert "watch_path" not in data


class _FakeWatcher:
    def status(self) -> dict[str, object]:
        return {
            "running": True,
            "last_trigger_time": 123.0,
            "pending_changes": 2,
            "restartable": False,
            "stop_timed_out": True,
        }


def test_watch_status_with_watcher_attached(tmp_path: Path) -> None:
    app = create_app(ServeState(state_dir=tmp_path, token="t"))
    app.state.file_watcher = _FakeWatcher()

    client = TestClient(app, base_url="http://localhost:8765")
    resp = client.get("/api/watch/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["running"] is True
    assert data["pending_changes"] == 2
    assert data["last_trigger_time"] == 123.0
    assert data["restartable"] is False
    assert data["stop_timed_out"] is True
    assert "watch_path" not in data
