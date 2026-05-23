from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, cast

import pytest
from starlette.testclient import TestClient

from ahadiff.contracts import ResultEvent
from ahadiff.eval.results import finalized_artifact_digest
from ahadiff.review.database import initialize_review_db, sync_result_event
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from pathlib import Path


AUTH = {"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"}


def _client(state_dir: Path, *, token: str = "test-token") -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token=token))
    return TestClient(app, base_url="http://localhost:8765")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _event(run_id: str) -> ResultEvent:
    return ResultEvent(
        event_id=f"018f0f52-91c0-7abc-8123-{run_id[-1]:0>12}",
        run_id=run_id,
        event_type="learn",
        timestamp=f"2026-04-24T00:00:0{run_id[-1]}Z",
        source_ref="abc1234",
        base_ref="base1234",
        prompt_version="prompt123",
        eval_bundle_version="eval123",
        rubric_version="rubric-v1",
        overall=88.0,
        verdict="PASS",
        status=cast("Any", "keep"),
        weakest_dim="evidence",
        note_json=None,
    )


def _write_run(state_dir: Path, run_id: str) -> Path:
    run_path = state_dir / "runs" / run_id
    run_path.mkdir(parents=True, exist_ok=True)
    _write_json(
        run_path / "metadata.json",
        {
            "run_id": run_id,
            "source_kind": "git_ref",
            "source_ref": "abc1234",
            "content_lang": "en",
            "capability_level": 2,
            "degraded_flags": {},
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


def test_get_judge_returns_envelope(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1")
    (run_path / "judge.json").write_text(
        json.dumps({"model_id": "gpt-5.5", "notes": "good"}),
        encoding="utf-8",
    )
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1/judge", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_type"] == "judge"
    assert body["run_id"] == "run-1"
    assert isinstance(body["content"], str)
    parsed = json.loads(body["content"])
    assert parsed["model_id"] == "gpt-5.5"
    assert parsed["notes"] == "good"


def test_score_and_judge_routes_keep_deterministic_score_owner(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1")
    deterministic_score: dict[str, Any] = {
        "overall": 42.0,
        "verdict": "FAIL",
        "hard_gates": {"passed": False, "failed": ["accuracy"]},
        "dimensions": {
            "accuracy": {"score": 4.0, "max_score": 10.0},
            "spec_alignment": {
                "score": 0.0,
                "max_score": 0.0,
                "applicability": "not_applicable",
            },
        },
    }
    advisory_judge: dict[str, Any] = {
        "schema": "ahadiff.judge.v1",
        "model_id": "gpt-5.5",
        "overall": 95.0,
        "verdict": "PASS",
        "advisory": True,
        "dimensions": {
            "accuracy": {"score": 9.5, "max_score": 10.0},
            "spec_alignment": {"score": 10.0, "max_score": 10.0},
        },
    }
    _write_json(run_path / "score.json", deterministic_score)
    _write_json(run_path / "judge.json", advisory_judge)
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    score_response = client.get("/api/run/run-1/score", headers=AUTH)
    judge_response = client.get("/api/run/run-1/judge", headers=AUTH)

    assert score_response.status_code == 200
    score_body = score_response.json()
    assert score_body["artifact_type"] == "score"
    assert score_body["run_id"] == "run-1"
    score_payload = cast("dict[str, Any]", json.loads(cast("str", score_body["content"])))
    assert score_payload == deterministic_score
    assert score_payload["verdict"] == "FAIL"
    assert score_payload["hard_gates"]["passed"] is False

    assert judge_response.status_code == 200
    judge_body = judge_response.json()
    assert judge_body["artifact_type"] == "judge"
    assert judge_body["run_id"] == "run-1"
    judge_payload = cast("dict[str, Any]", json.loads(cast("str", judge_body["content"])))
    assert judge_payload == advisory_judge
    assert judge_payload["verdict"] == "PASS"
    assert judge_payload["overall"] > score_payload["overall"]

    score_after_judge = client.get("/api/run/run-1/score", headers=AUTH)

    assert score_after_judge.status_code == 200
    score_after_payload = cast(
        "dict[str, Any]",
        json.loads(cast("str", score_after_judge.json()["content"])),
    )
    assert score_after_payload["verdict"] == "FAIL"
    assert score_after_payload == deterministic_score


def test_get_judge_404_when_missing(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1")
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1/judge", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["error"] == "artifact_not_found"


def test_run_detail_artifacts_includes_judge(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1")
    (run_path / "judge.json").write_text(
        json.dumps({"model_id": "gpt-5.5"}),
        encoding="utf-8",
    )
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1", headers=AUTH)

    assert response.status_code == 200
    detail = response.json()
    assert "judge.json" in detail["artifacts"]


def test_get_judge_failure_returns_envelope(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1")
    _write_json(
        run_path / "judge_failure.json",
        {
            "schema": "ahadiff.judge_failure.v1",
            "provider_class": "openai_responses",
            "model_name": "gpt-5.5",
            "error_type": "TimeoutError",
            "message": "request timed out",
            "created_at": "2026-04-24T00:00:01Z",
        },
    )
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1/judge-failure", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_type"] == "judge_failure"
    assert body["run_id"] == "run-1"
    parsed = json.loads(body["content"])
    assert parsed["schema"] == "ahadiff.judge_failure.v1"
    assert parsed["error_type"] == "TimeoutError"


def test_get_judge_failure_404_when_missing(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1")
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1/judge-failure", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["error"] == "artifact_not_found"


def test_get_judge_failure_rejects_symlink_after_finalize(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is unavailable on this platform")
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1")
    _write_json(
        run_path / "judge_failure.json",
        {
            "schema": "ahadiff.judge_failure.v1",
            "provider_class": "openai_responses",
            "model_name": "gpt-5.5",
            "error_type": "TimeoutError",
            "message": "request timed out",
            "created_at": "2026-04-24T00:00:01Z",
        },
    )
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    (run_path / "judge_failure.json").unlink()
    target = tmp_path / "outside.json"
    target.write_text("outside secret should not be read\n", encoding="utf-8")
    os.symlink(target, run_path / "judge_failure.json")
    client = _client(state_dir)

    response = client.get("/api/run/run-1/judge-failure", headers=AUTH)

    assert response.status_code != 200
    assert "outside secret should not be read" not in response.text


def test_run_detail_artifacts_includes_judge_failure(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    initialize_review_db(state_dir / "review.sqlite")
    run_path = _write_run(state_dir, "run-1")
    _write_json(
        run_path / "judge_failure.json",
        {
            "schema": "ahadiff.judge_failure.v1",
            "provider_class": "openai_responses",
            "model_name": "gpt-5.5",
            "error_type": "TimeoutError",
            "message": "request timed out",
            "created_at": "2026-04-24T00:00:01Z",
        },
    )
    _finalize_run(run_path, "run-1")
    sync_result_event(state_dir / "review.sqlite", _event("run-1"))
    client = _client(state_dir)

    response = client.get("/api/run/run-1", headers=AUTH)

    assert response.status_code == 200
    detail = response.json()
    assert "judge_failure.json" in detail["artifacts"]
