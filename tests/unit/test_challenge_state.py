from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import pytest
from starlette.testclient import TestClient

from ahadiff.challenge import (
    ChallengeStage,
    InvalidTransitionError,
    adapt_from_gaps,
    build_challenge,
    create_state,
    is_feature_enabled,
    read_manifest,
    read_state,
    review_attempt,
    write_manifest,
    write_state,
)
from ahadiff.challenge.manifest import MIN_QUALIFYING_OVERALL, ChallengeManifest
from ahadiff.challenge.state import (
    CHALLENGE_ID_PATTERN,
    VALID_TRANSITIONS,
    validate_challenge_id,
)
from ahadiff.core.errors import InputError, StorageError
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from pathlib import Path

_AUTH = {
    "X-AhaDiff-Token": "test-token",
    "Origin": "http://localhost:8765",
}


_CANONICAL_PATCH = """diff --git a/foo.py b/foo.py
index 0000000..1111111 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def foo():
-    return 1
+    return 2
+    # docstring
"""


def _write_qualifying_run(state_dir: Path, run_id: str) -> Path:
    run_path = state_dir / "runs" / run_id
    run_path.mkdir(parents=True)
    (run_path / "score.json").write_text(
        json.dumps({"overall": 88.5, "verdict": "pass"}),
        encoding="utf-8",
    )
    (run_path / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "source_ref": "HEAD~1..HEAD",
                "baseline_sha": "abc123",
                "target_sha": "def456",
                "hunks": [
                    {
                        "file": "foo.py",
                        "new_start": 2,
                        "new_count": 2,
                        "claim_ids": ["claim-1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text(_CANONICAL_PATCH, encoding="utf-8")
    (run_path / "claims.jsonl").write_text(
        json.dumps(
            {
                "claim_id": "claim-1",
                "status": "verified",
                "text": "Returns two",
            }
        )
        + "\n"
        + json.dumps(
            {
                "claim_id": "claim-rejected",
                "status": "rejected",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return run_path


def _write_unqualified_run(state_dir: Path, run_id: str, *, overall: float = 60.0) -> Path:
    run_path = state_dir / "runs" / run_id
    run_path.mkdir(parents=True)
    (run_path / "score.json").write_text(
        json.dumps({"overall": overall, "verdict": "fail"}),
        encoding="utf-8",
    )
    (run_path / "metadata.json").write_text(
        json.dumps({"run_id": run_id, "source_ref": "HEAD"}),
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text("", encoding="utf-8")
    (run_path / "claims.jsonl").write_text("", encoding="utf-8")
    return run_path


def _state_dir(tmp_path: Path) -> Path:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    return state_dir


def test_challenge_id_validation_rejects_traversal() -> None:
    validate_challenge_id("abc-123")
    with pytest.raises(InputError):
        validate_challenge_id("..")
    with pytest.raises(InputError):
        validate_challenge_id(".")
    with pytest.raises(InputError):
        validate_challenge_id("../escape")
    with pytest.raises(InputError):
        validate_challenge_id("path/sep")
    for reserved in ("CON", "AUX.txt", "NUL", "COM1", "LPT9"):
        with pytest.raises(InputError):
            validate_challenge_id(reserved)
    assert CHALLENGE_ID_PATTERN.fullmatch("ok.id_1-2") is not None


def test_state_machine_valid_transitions(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    state = create_state(challenge_id="c1", source_run_id="r1")
    assert state.stage is ChallengeStage.BUILD
    state = state.transition(ChallengeStage.TOUR)
    assert state.stage is ChallengeStage.TOUR
    state = state.transition(ChallengeStage.CHALLENGE)
    state = state.transition(ChallengeStage.REVIEW)
    state = state.transition(ChallengeStage.ADAPT)
    state = state.transition(ChallengeStage.IDLE)
    write_state(state_dir, state)
    persisted = read_state(state_dir, "c1")
    assert persisted.stage is ChallengeStage.IDLE


def test_state_machine_invalid_transitions_are_rejected() -> None:
    state = create_state(challenge_id="c1", source_run_id="r1")
    assert state.stage is ChallengeStage.BUILD
    with pytest.raises(InvalidTransitionError):
        state.transition(ChallengeStage.REVIEW)
    with pytest.raises(InvalidTransitionError):
        state.transition(ChallengeStage.ADAPT)
    with pytest.raises(InvalidTransitionError):
        state.transition(ChallengeStage.CHALLENGE)


def test_abort_returns_idle_from_any_active_stage() -> None:
    state = create_state(challenge_id="c1", source_run_id="r1")
    # BUILD -> abort
    assert state.abort().stage is ChallengeStage.IDLE
    # TOUR -> abort
    state = state.transition(ChallengeStage.TOUR)
    assert state.abort().stage is ChallengeStage.IDLE
    # CHALLENGE -> abort
    state = state.transition(ChallengeStage.CHALLENGE)
    assert state.abort().stage is ChallengeStage.IDLE
    # REVIEW -> abort
    state = state.transition(ChallengeStage.REVIEW)
    assert state.abort().stage is ChallengeStage.IDLE
    # ADAPT -> abort still lands on IDLE (only legal next)
    state = state.transition(ChallengeStage.ADAPT)
    assert state.abort().stage is ChallengeStage.IDLE


def test_valid_transitions_table_is_consistent() -> None:
    for stage in ChallengeStage:
        assert stage in VALID_TRANSITIONS
    assert ChallengeStage.BUILD in VALID_TRANSITIONS[ChallengeStage.IDLE]
    assert ChallengeStage.IDLE in VALID_TRANSITIONS[ChallengeStage.ADAPT]


def test_build_challenge_from_qualifying_run(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(source_run_id="good-run", state_dir=state_dir)
    assert manifest.source_run_id == "good-run"
    assert manifest.baseline_sha == "abc123"
    assert manifest.target_sha == "def456"
    assert manifest.canonical_claim_ids == ["claim-1"]
    assert "foo.py" in manifest.canonical_patch
    assert CHALLENGE_ID_PATTERN.fullmatch(manifest.challenge_id)
    write_manifest(state_dir, manifest)
    persisted = read_manifest(state_dir, manifest.challenge_id)
    assert persisted.canonical_claim_ids == ["claim-1"]
    assert persisted.baseline_sha == "abc123"


def test_build_challenge_from_unqualified_run_is_rejected(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    _write_unqualified_run(state_dir, "bad-run", overall=60.0)
    with pytest.raises(InputError) as excinfo:
        build_challenge(source_run_id="bad-run", state_dir=state_dir)
    assert "does not qualify" in str(excinfo.value)


def test_build_challenge_requires_min_overall(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    run_path = _write_qualifying_run(state_dir, "edge-run")
    (run_path / "score.json").write_text(
        json.dumps({"overall": MIN_QUALIFYING_OVERALL - 0.1, "verdict": "pass"}),
        encoding="utf-8",
    )
    with pytest.raises(InputError):
        build_challenge(source_run_id="edge-run", state_dir=state_dir)


def test_build_challenge_requires_pass_verdict(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    run_path = _write_qualifying_run(state_dir, "caution-run")
    (run_path / "score.json").write_text(
        json.dumps({"overall": 95.0, "verdict": "caution"}),
        encoding="utf-8",
    )
    with pytest.raises(InputError):
        build_challenge(source_run_id="caution-run", state_dir=state_dir)


@pytest.mark.parametrize("overall", ["nan", "inf", "-inf"])
def test_build_challenge_rejects_non_finite_overall(tmp_path: Path, overall: str) -> None:
    state_dir = _state_dir(tmp_path)
    run_path = _write_qualifying_run(state_dir, "nonfinite-run")
    (run_path / "score.json").write_text(
        json.dumps({"overall": overall, "verdict": "pass"}),
        encoding="utf-8",
    )
    with pytest.raises(InputError, match="finite"):
        build_challenge(source_run_id="nonfinite-run", state_dir=state_dir)


@pytest.mark.parametrize("overall_json", ["NaN", "Infinity", "-Infinity", "1e309"])
def test_build_challenge_rejects_non_finite_json_number(
    tmp_path: Path,
    overall_json: str,
) -> None:
    state_dir = _state_dir(tmp_path)
    run_path = _write_qualifying_run(state_dir, "nonfinite-json-run")
    (run_path / "score.json").write_text(
        f'{{"overall": {overall_json}, "verdict": "pass"}}',
        encoding="utf-8",
    )
    with pytest.raises(InputError, match="valid finite JSON"):
        build_challenge(source_run_id="nonfinite-json-run", state_dir=state_dir)


def test_manifest_read_allows_inline_patch_at_patch_limit(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    run_path = _write_qualifying_run(state_dir, "large-patch-run")
    large_patch = (
        "diff --git a/large.py b/large.py\n"
        "--- a/large.py\n"
        "+++ b/large.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n" + ("# padding\n" * 120_000)
    )
    assert len(large_patch.encode("utf-8")) > 1_000_000
    (run_path / "patch.diff").write_text(large_patch, encoding="utf-8")

    manifest = build_challenge(
        source_run_id="large-patch-run",
        state_dir=state_dir,
        challenge_id="large-patch",
    )
    write_manifest(state_dir, manifest)

    persisted = read_manifest(state_dir, "large-patch")
    assert persisted.canonical_patch == large_patch


def test_review_attempt_reports_missing_file(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(source_run_id="good-run", state_dir=state_dir)
    feedback = review_attempt(manifest=manifest, learner_diff="")
    assert feedback["missing_files"] == ["foo.py"]
    assert feedback["gap_claim_ids"] == ["claim-1"]


def test_review_attempt_reports_no_gap_when_diff_matches(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(source_run_id="good-run", state_dir=state_dir)
    feedback = review_attempt(manifest=manifest, learner_diff=_CANONICAL_PATCH)
    assert feedback["missing_files"] == []
    assert feedback["extra_files"] == []
    assert feedback["gap_claim_ids"] == []


def test_review_attempt_reports_extra_files_without_false_gap(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(source_run_id="good-run", state_dir=state_dir)
    extra_patch = """diff --git a/bar.py b/bar.py
--- a/bar.py
+++ b/bar.py
@@ -1,1 +1,1 @@
-old
+new
"""
    feedback = review_attempt(manifest=manifest, learner_diff=_CANONICAL_PATCH + "\n" + extra_patch)
    assert feedback["missing_files"] == []
    assert feedback["extra_files"] == ["bar.py"]
    assert feedback["gap_claim_ids"] == []


def test_review_attempt_detects_missing_hunk_via_manifest_metadata(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(source_run_id="good-run", state_dir=state_dir)
    learner_diff = """diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -10,1 +10,1 @@
-pass
+pass # different region
"""
    feedback = review_attempt(manifest=manifest, learner_diff=learner_diff)
    assert "claim-1" in feedback["gap_claim_ids"]


def test_review_attempt_filters_noncanonical_gap_claim_ids() -> None:
    manifest = ChallengeManifest(
        challenge_id="noncanonical-gap",
        source_run_id="run-gap",
        baseline_sha=None,
        target_sha=None,
        canonical_patch=_CANONICAL_PATCH,
        canonical_claim_ids=["claim-1"],
        hunks=[
            {
                "file": "foo.py",
                "new_start": 2,
                "new_count": 2,
                "claim_ids": ["claim-not-canonical"],
            }
        ],
        created_at_utc="2026-05-12T00:00:00Z",
    )

    feedback = review_attempt(manifest=manifest, learner_diff="")

    assert "claim-not-canonical" not in feedback["gap_claim_ids"]
    assert feedback["gap_claim_ids"] == ["claim-1"]


def test_review_attempt_does_not_drop_mixed_unattributed_missing_hunks() -> None:
    canonical_patch = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,1 +1,1 @@
-old-a
+new-a
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1,1 +1,1 @@
-old-b
+new-b
"""
    learner_diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,1 +1,1 @@
-old-a
+new-a
"""
    manifest = ChallengeManifest(
        challenge_id="mixed-gap",
        source_run_id="run-gap",
        baseline_sha=None,
        target_sha=None,
        canonical_patch=canonical_patch,
        canonical_claim_ids=["claim-a", "claim-b"],
        hunks=[
            {
                "file": "a.py",
                "new_start": 1,
                "new_count": 1,
                "claim_ids": ["claim-a"],
            },
            {
                "file": "b.py",
                "new_start": 1,
                "new_count": 1,
            },
        ],
        created_at_utc="2026-05-12T00:00:00Z",
    )

    feedback = review_attempt(manifest=manifest, learner_diff=learner_diff)

    assert feedback["missing_files"] == ["b.py"]
    assert feedback["gap_claim_ids"] == ["claim-b"]


def test_review_attempt_rejects_oversized_diff(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(source_run_id="good-run", state_dir=state_dir)
    huge = "x" * 6_000_000
    with pytest.raises(InputError):
        review_attempt(manifest=manifest, learner_diff=huge)


def test_adapt_emits_mark_wrong_signals(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    db_path = state_dir / "review.sqlite"
    summary = adapt_from_gaps(
        challenge_id="c1",
        gap_claim_ids=["claim-a", "claim-b", "claim-a"],
        db_path=db_path,
    )
    assert summary["signal_count"] == 2
    assert summary["inserted_claim_ids"] == ["claim-a", "claim-b"]
    # Calling twice is idempotent (no new inserts on second pass).
    second = adapt_from_gaps(
        challenge_id="c1",
        gap_claim_ids=["claim-a", "claim-b"],
        db_path=db_path,
    )
    assert second["signal_count"] == 0
    assert set(second["duplicate_claim_ids"]) == {"claim-a", "claim-b"}


def test_adapt_validates_inputs(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    with pytest.raises(InputError):
        adapt_from_gaps(challenge_id="", gap_claim_ids=[], db_path=db_path)


def test_is_feature_enabled_handles_missing_section() -> None:
    class _Snapshot:
        values = {"learn": {"learnability_threshold": 0.3}}

    assert is_feature_enabled(None) is False
    assert is_feature_enabled(_Snapshot()) is False


def test_is_feature_enabled_handles_explicit_opt_in() -> None:
    class _Snapshot:
        values = {"challenge": {"enabled": True}}

    assert is_feature_enabled(_Snapshot()) is True


def test_routes_return_feature_unavailable_when_disabled(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )
    response = client.post(
        "/api/challenge/build",
        json={"run_id": "some-run"},
        headers=_AUTH,
    )
    assert response.status_code == 501
    body = response.json()
    assert body["error_code"] == "FEATURE_UNAVAILABLE"
    assert body["details"]["feature"] == "challenge"


def test_mutating_routes_require_token_before_feature_probe(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )

    origin_only = {"Origin": "http://localhost:8765"}
    requests = [
        client.post("/api/challenge/build", json={"run_id": "some-run"}, headers=origin_only),
        client.post(
            "/api/challenge/demo/advance",
            json={"target_stage": "tour"},
            headers=origin_only,
        ),
        client.post("/api/challenge/demo/abort", headers=origin_only),
        client.post(
            "/api/challenge/demo/review",
            json={"learner_diff": ""},
            headers=origin_only,
        ),
    ]

    for response in requests:
        assert response.status_code == 401
        assert response.json()["error_code"] == "AUTH_REQUIRED"


def test_routes_full_loop_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")

    from ahadiff.serve import routes_challenge

    class _Snapshot:
        def __init__(self) -> None:
            self.values = {"challenge": {"enabled": True}}

    monkeypatch.setattr(
        routes_challenge,
        "load_serve_config_snapshot",
        lambda _state: _Snapshot(),  # type: ignore[arg-type]
    )

    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )

    build_resp = client.post(
        "/api/challenge/build",
        json={"run_id": "good-run", "challenge_id": "demo-1"},
        headers=_AUTH,
    )
    assert build_resp.status_code == 200, build_resp.text
    payload = build_resp.json()
    assert payload["state"]["challenge_id"] == "demo-1"
    assert payload["state"]["stage"] == "build"
    assert payload["manifest"]["source_run_id"] == "good-run"

    get_resp = client.get("/api/challenge/demo-1", headers=_AUTH)
    assert get_resp.status_code == 200
    assert get_resp.json()["state"]["stage"] == "build"

    advance_resp = client.post(
        "/api/challenge/demo-1/advance",
        json={"target_stage": "tour"},
        headers=_AUTH,
    )
    assert advance_resp.status_code == 200
    assert advance_resp.json()["state"]["stage"] == "tour"

    # Default advance with empty body should follow the canonical order.
    advance_default = client.post(
        "/api/challenge/demo-1/advance",
        content=b"",
        headers=_AUTH,
    )
    assert advance_default.status_code == 200
    assert advance_default.json()["state"]["stage"] == "challenge"

    review_resp = client.post(
        "/api/challenge/demo-1/review",
        json={"learner_diff": ""},
        headers=_AUTH,
    )
    assert review_resp.status_code == 200
    review_body = review_resp.json()
    assert review_body["state"]["stage"] == "idle"
    assert review_body["gap_claim_ids"] == ["claim-1"]
    assert review_body["adapt"]["signal_count"] == 1

    feedback_resp = client.get("/api/challenge/demo-1/feedback", headers=_AUTH)
    assert feedback_resp.status_code == 200
    assert feedback_resp.json()["feedback"]["gap_claim_ids"] == ["claim-1"]


def test_route_rejects_challenge_id_with_trailing_space(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")

    from ahadiff.serve import routes_challenge

    class _Snapshot:
        values = {"challenge": {"enabled": True}}

    monkeypatch.setattr(
        routes_challenge,
        "load_serve_config_snapshot",
        lambda _state: _Snapshot(),  # type: ignore[arg-type]
    )

    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )

    build_resp = client.post(
        "/api/challenge/build",
        json={"run_id": "good-run", "challenge_id": "space-1 "},
        headers=_AUTH,
    )
    assert build_resp.status_code == 400
    assert build_resp.json()["error_code"] == "INPUT_BAD_FIELD"
    assert not (state_dir / "challenges" / "space-1").exists()

    path_resp = client.get("/api/challenge/space-1%20", headers=_AUTH)
    assert path_resp.status_code == 400
    assert path_resp.json()["error_code"] == "INPUT_BAD_FIELD"


def test_route_rejects_rebuild_of_in_flight_challenge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")

    from ahadiff.serve import routes_challenge

    class _Snapshot:
        values = {"challenge": {"enabled": True}}

    monkeypatch.setattr(
        routes_challenge,
        "load_serve_config_snapshot",
        lambda _state: _Snapshot(),  # type: ignore[arg-type]
    )

    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )

    first = client.post(
        "/api/challenge/build",
        json={"run_id": "good-run", "challenge_id": "rebuild-1"},
        headers=_AUTH,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/api/challenge/build",
        json={"run_id": "good-run", "challenge_id": "rebuild-1"},
        headers=_AUTH,
    )
    assert second.status_code == 422
    assert second.json()["error_code"] == "INPUT_VALIDATION"
    assert read_state(state_dir, "rebuild-1").stage is ChallengeStage.BUILD


@pytest.mark.parametrize("overall_json", ["NaN", "Infinity", "-Infinity", "1e309"])
def test_route_rejects_non_finite_score_with_precise_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overall_json: str,
) -> None:
    state_dir = _state_dir(tmp_path)
    run_path = _write_qualifying_run(state_dir, "nonfinite-route-run")
    (run_path / "score.json").write_text(
        f'{{"overall": {overall_json}, "verdict": "pass"}}',
        encoding="utf-8",
    )

    from ahadiff.serve import routes_challenge

    class _Snapshot:
        values = {"challenge": {"enabled": True}}

    monkeypatch.setattr(
        routes_challenge,
        "load_serve_config_snapshot",
        lambda _state: _Snapshot(),  # type: ignore[arg-type]
    )

    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )

    response = client.post(
        "/api/challenge/build",
        json={"run_id": "nonfinite-route-run", "challenge_id": "nonfinite-route"},
        headers=_AUTH,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "INPUT_VALIDATION"
    assert not (state_dir / "challenges" / "nonfinite-route" / "state.json").exists()


def test_review_keeps_challenge_state_if_idle_persist_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(
        source_run_id="good-run",
        state_dir=state_dir,
        challenge_id="review-fail",
    )
    write_manifest(state_dir, manifest)
    challenge_state = (
        create_state(challenge_id="review-fail", source_run_id="good-run")
        .transition(ChallengeStage.TOUR)
        .transition(ChallengeStage.CHALLENGE)
    )
    write_state(state_dir, challenge_state)

    from ahadiff.serve import routes_challenge

    def fail_write_state(_state_dir: Path, _state: object) -> Path:
        raise OSError("simulated state write failure")

    monkeypatch.setattr(routes_challenge, "write_state", fail_write_state)

    serve_state = ServeState(state_dir=state_dir, token="test-token").with_runtime_lock()
    with pytest.raises(OSError, match="simulated state write failure"):
        routes_challenge._review_challenge_sync(  # pyright: ignore[reportPrivateUsage]
            serve_state,
            "review-fail",
            "",
        )

    persisted = read_state(state_dir, "review-fail")
    assert persisted.stage is ChallengeStage.CHALLENGE
    assert serve_state.review_db_path.exists()
    assert (state_dir / "challenges" / "review-fail" / "feedback.json").exists()


def test_review_keeps_challenge_state_if_adapt_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(
        source_run_id="good-run",
        state_dir=state_dir,
        challenge_id="adapt-fail",
    )
    write_manifest(state_dir, manifest)
    challenge_state = (
        create_state(challenge_id="adapt-fail", source_run_id="good-run")
        .transition(ChallengeStage.TOUR)
        .transition(ChallengeStage.CHALLENGE)
    )
    write_state(state_dir, challenge_state)

    from ahadiff.serve import routes_challenge

    def fail_adapt(**_kwargs: object) -> dict[str, object]:
        raise StorageError("simulated adapt failure")

    monkeypatch.setattr(routes_challenge, "adapt_from_gaps", fail_adapt)

    serve_state = ServeState(state_dir=state_dir, token="test-token").with_runtime_lock()
    with pytest.raises(StorageError, match="simulated adapt failure"):
        routes_challenge._review_challenge_sync(  # pyright: ignore[reportPrivateUsage]
            serve_state,
            "adapt-fail",
            "",
        )

    persisted = read_state(state_dir, "adapt-fail")
    assert persisted.stage is ChallengeStage.CHALLENGE
    assert not (state_dir / "challenges" / "adapt-fail" / "feedback.json").exists()


def test_review_keeps_challenge_state_if_feedback_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(
        source_run_id="good-run",
        state_dir=state_dir,
        challenge_id="feedback-fail",
    )
    write_manifest(state_dir, manifest)
    challenge_state = (
        create_state(challenge_id="feedback-fail", source_run_id="good-run")
        .transition(ChallengeStage.TOUR)
        .transition(ChallengeStage.CHALLENGE)
    )
    write_state(state_dir, challenge_state)

    from ahadiff.serve import routes_challenge

    def fail_write_feedback(*_args: object, **_kwargs: object) -> None:
        raise StorageError("simulated feedback write failure")

    monkeypatch.setattr(routes_challenge, "_write_feedback", fail_write_feedback)

    serve_state = ServeState(state_dir=state_dir, token="test-token").with_runtime_lock()
    with pytest.raises(StorageError, match="simulated feedback write failure"):
        routes_challenge._review_challenge_sync(  # pyright: ignore[reportPrivateUsage]
            serve_state,
            "feedback-fail",
            "",
        )

    persisted = read_state(state_dir, "feedback-fail")
    assert persisted.stage is ChallengeStage.CHALLENGE
    assert not (state_dir / "challenges" / "feedback-fail" / "feedback.json").exists()


def test_review_final_state_failure_keeps_challenge_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(
        source_run_id="good-run",
        state_dir=state_dir,
        challenge_id="atomic-fail",
    )
    write_manifest(state_dir, manifest)
    challenge_state = (
        create_state(challenge_id="atomic-fail", source_run_id="good-run")
        .transition(ChallengeStage.TOUR)
        .transition(ChallengeStage.CHALLENGE)
    )
    write_state(state_dir, challenge_state)

    from ahadiff.serve import routes_challenge

    def fail_write_state(_state_dir: Path, _state: object) -> Path:
        raise OSError("simulated final state write failure")

    monkeypatch.setattr(routes_challenge, "write_state", fail_write_state)

    serve_state = ServeState(state_dir=state_dir, token="test-token").with_runtime_lock()
    with pytest.raises(OSError, match="simulated final state write failure"):
        routes_challenge._review_challenge_sync(  # pyright: ignore[reportPrivateUsage]
            serve_state,
            "atomic-fail",
            "",
        )

    persisted = read_state(state_dir, "atomic-fail")
    assert persisted.stage is ChallengeStage.CHALLENGE
    assert (state_dir / "challenges" / "atomic-fail" / "feedback.json").exists()


def test_abort_route_returns_state_to_idle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")

    from ahadiff.serve import routes_challenge

    class _Snapshot:
        values = {"challenge": {"enabled": True}}

    monkeypatch.setattr(
        routes_challenge,
        "load_serve_config_snapshot",
        lambda _state: _Snapshot(),  # type: ignore[arg-type]
    )

    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )
    build_resp = client.post(
        "/api/challenge/build",
        json={"run_id": "good-run", "challenge_id": "abort-1"},
        headers=_AUTH,
    )
    assert build_resp.status_code == 200
    abort_resp = client.post("/api/challenge/abort-1/abort", headers=_AUTH)
    assert abort_resp.status_code == 200
    assert abort_resp.json()["state"]["stage"] == "idle"


def test_challenge_dir_is_inside_state_dir(tmp_path: Path) -> None:
    """Challenges live under .ahadiff/, which is the gitignored state root."""
    from ahadiff.challenge.state import challenge_dir

    state_dir = _state_dir(tmp_path)
    target = challenge_dir(state_dir, "demo")
    assert target.is_relative_to(state_dir)
    assert target.parent.name == "challenges"
    assert target.name == "demo"


def test_build_challenge_rejects_missing_run(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    with pytest.raises(InputError):
        build_challenge(source_run_id="absent", state_dir=state_dir)


def test_state_persist_round_trip(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    state = create_state(challenge_id="round-trip", source_run_id="r1")
    write_state(state_dir, state)
    persisted = read_state(state_dir, "round-trip")
    assert persisted.challenge_id == "round-trip"
    assert persisted.source_run_id == "r1"
    assert persisted.stage is ChallengeStage.BUILD


def test_state_file_rejects_invalid_payload(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    state = create_state(challenge_id="bad", source_run_id="r1")
    write_state(state_dir, state)
    target = state_dir / "challenges" / "bad" / "state.json"
    target.write_text("not json", encoding="utf-8")
    with pytest.raises(InputError):
        read_state(state_dir, "bad")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_state_file_rejects_symlink(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    state = create_state(challenge_id="link-state", source_run_id="r1")
    write_state(state_dir, state)
    state_path = state_dir / "challenges" / "link-state" / "state.json"
    real_path = state_path.with_name("state.real.json")
    state_path.rename(real_path)
    state_path.symlink_to(real_path)

    with pytest.raises(InputError, match="symlink"):
        read_state(state_dir, "link-state")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires FIFO support")
def test_state_file_rejects_fifo(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    state = create_state(challenge_id="fifo-state", source_run_id="r1")
    write_state(state_dir, state)
    state_path = state_dir / "challenges" / "fifo-state" / "state.json"
    state_path.unlink()
    os.mkfifo(state_path)

    with pytest.raises(InputError, match="regular file"):
        read_state(state_dir, "fifo-state")


@pytest.mark.skipif(not hasattr(os, "link"), reason="requires hardlink support")
def test_state_file_rejects_hardlink(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    state = create_state(challenge_id="hardlink-state", source_run_id="r1")
    write_state(state_dir, state)
    state_path = state_dir / "challenges" / "hardlink-state" / "state.json"
    os.link(state_path, state_path.with_name("state.other.json"))

    with pytest.raises(InputError, match="hardlink"):
        read_state(state_dir, "hardlink-state")


def test_state_file_rejects_windows_reparse_attribute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _state_dir(tmp_path)
    state = create_state(challenge_id="reparse-state", source_run_id="r1")
    write_state(state_dir, state)
    state_path = state_dir / "challenges" / "reparse-state" / "state.json"

    from ahadiff.challenge import state as challenge_state_module

    original_lstat = challenge_state_module.os.lstat
    original_stat = original_lstat(state_path)

    class _ReparseStat:
        st_mode = original_stat.st_mode
        st_size = original_stat.st_size
        st_dev = original_stat.st_dev
        st_ino = original_stat.st_ino
        st_nlink = 1
        st_file_attributes = 0x400

    def fake_lstat(path: Any) -> object:
        if os.fspath(path) == os.fspath(state_path):
            return _ReparseStat()
        return original_lstat(path)

    monkeypatch.setattr(challenge_state_module.os, "lstat", fake_lstat)

    with pytest.raises(InputError, match="reparse"):
        read_state(state_dir, "reparse-state")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_state_file_rejects_toctou_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _state_dir(tmp_path)
    state = create_state(challenge_id="swap-state", source_run_id="r1")
    write_state(state_dir, state)
    state_path = state_dir / "challenges" / "swap-state" / "state.json"
    outside = tmp_path / "outside-state.json"
    outside.write_text(state_path.read_text(encoding="utf-8"), encoding="utf-8")

    from ahadiff.challenge import state as challenge_state_module

    original_open = challenge_state_module.os.open
    swapped = False

    def swapping_open(path: Any, flags: int, mode: int = 0o777) -> int:
        nonlocal swapped
        if os.fspath(path) == os.fspath(state_path) and not swapped:
            state_path.unlink()
            state_path.symlink_to(outside)
            swapped = True
        return original_open(path, flags, mode)

    monkeypatch.setattr(challenge_state_module.os, "open", swapping_open)

    with pytest.raises(InputError, match="symlink|changed during validation"):
        read_state(state_dir, "swap-state")
    assert swapped is True


def test_review_attempt_marks_empty_body_overlap_as_gap(tmp_path: Path) -> None:
    """Range overlap alone is not enough — body must show real edit work."""
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(source_run_id="good-run", state_dir=state_dir)
    # learner_diff overlaps the canonical hunk range (lines 1..4 of foo.py),
    # but its body adds an unrelated comment and removes the docstring instead
    # of the canonical "return 1" -> "return 2" change.
    learner_diff = """diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 def foo():
-    return 1
+    return 9999  # totally different change
"""
    feedback = review_attempt(manifest=manifest, learner_diff=learner_diff)
    # foo.py is present, but the canonical hunk's body lines ("return 2" /
    # docstring add) are absent, so it must be reported as a gap.
    assert feedback["missing_files"] == []
    assert feedback["hunk_coverage"][0]["missing_hunks"] == 1
    assert feedback["gap_claim_ids"] == ["claim-1"]


def test_review_attempt_rejects_partial_matching_added_line(tmp_path: Path) -> None:
    """A learner diff must include every canonical added line for the hunk."""
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(source_run_id="good-run", state_dir=state_dir)
    # Reproduce one canonical added line ("    return 2") but omit the second
    # canonical added line. Partial body overlap is still a gap.
    learner_diff = """diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 def foo():
-    return 1
+    return 2
"""
    feedback = review_attempt(manifest=manifest, learner_diff=learner_diff)
    assert feedback["gap_claim_ids"] == ["claim-1"]
    assert feedback["hunk_coverage"][0]["missing_hunks"] == 1


def test_review_attempt_accepts_complete_hunk_body(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")
    manifest = build_challenge(source_run_id="good-run", state_dir=state_dir)
    feedback = review_attempt(manifest=manifest, learner_diff=_CANONICAL_PATCH)
    assert feedback["gap_claim_ids"] == []
    assert feedback["hunk_coverage"][0]["matched_hunks"] == 1


def test_review_attempt_detects_missing_pure_deletion_patch() -> None:
    canonical_patch = """diff --git a/gone.py b/gone.py
deleted file mode 100644
index 1111111..0000000
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def gone():
-    return True
"""
    manifest = ChallengeManifest(
        challenge_id="delete-1",
        source_run_id="run-delete",
        baseline_sha=None,
        target_sha=None,
        canonical_patch=canonical_patch,
        canonical_claim_ids=["claim-delete"],
        hunks=[
            {
                "file": "gone.py",
                "old_start": 1,
                "old_count": 2,
                "new_start": 0,
                "new_count": 0,
                "claim_ids": ["claim-delete"],
            }
        ],
        created_at_utc="2026-05-12T00:00:00Z",
    )
    feedback = review_attempt(manifest=manifest, learner_diff="")
    assert feedback["missing_files"] == ["gone.py"]
    assert feedback["gap_claim_ids"] == ["claim-delete"]


def test_review_attempt_accepts_complete_pure_deletion_patch() -> None:
    canonical_patch = """diff --git a/gone.py b/gone.py
deleted file mode 100644
index 1111111..0000000
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def gone():
-    return True
"""
    manifest = ChallengeManifest(
        challenge_id="delete-2",
        source_run_id="run-delete",
        baseline_sha=None,
        target_sha=None,
        canonical_patch=canonical_patch,
        canonical_claim_ids=["claim-delete"],
        hunks=[
            {
                "file": "gone.py",
                "old_start": 1,
                "old_count": 2,
                "new_start": 0,
                "new_count": 0,
                "claim_ids": ["claim-delete"],
            }
        ],
        created_at_utc="2026-05-12T00:00:00Z",
    )
    feedback = review_attempt(manifest=manifest, learner_diff=canonical_patch)
    assert feedback["missing_files"] == []
    assert feedback["gap_claim_ids"] == []


def test_advance_cannot_skip_review_via_explicit_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHALLENGE → REVIEW must go through POST /review, not POST /advance."""
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")

    from ahadiff.serve import routes_challenge

    class _Snapshot:
        values = {"challenge": {"enabled": True}}

    monkeypatch.setattr(
        routes_challenge,
        "load_serve_config_snapshot",
        lambda _state: _Snapshot(),  # type: ignore[arg-type]
    )

    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )
    build_resp = client.post(
        "/api/challenge/build",
        json={"run_id": "good-run", "challenge_id": "guard-1"},
        headers=_AUTH,
    )
    assert build_resp.status_code == 200, build_resp.text

    # build -> tour -> challenge via explicit advances (those are allowed).
    for stage in ("tour", "challenge"):
        resp = client.post(
            "/api/challenge/guard-1/advance",
            json={"target_stage": stage},
            headers=_AUTH,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"]["stage"] == stage

    # Now from CHALLENGE, attempting to advance straight to REVIEW must fail.
    blocked = client.post(
        "/api/challenge/guard-1/advance",
        json={"target_stage": "review"},
        headers=_AUTH,
    )
    assert blocked.status_code == 422
    # And the persisted stage must still be 'challenge' — no state mutation.
    after = client.get("/api/challenge/guard-1", headers=_AUTH)
    assert after.status_code == 200
    assert after.json()["state"]["stage"] == "challenge"


def test_advance_cannot_skip_review_via_default_next_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default-next advance from CHALLENGE must also be rejected."""
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")

    from ahadiff.serve import routes_challenge

    class _Snapshot:
        values = {"challenge": {"enabled": True}}

    monkeypatch.setattr(
        routes_challenge,
        "load_serve_config_snapshot",
        lambda _state: _Snapshot(),  # type: ignore[arg-type]
    )

    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )
    client.post(
        "/api/challenge/build",
        json={"run_id": "good-run", "challenge_id": "guard-2"},
        headers=_AUTH,
    )
    for stage in ("tour", "challenge"):
        client.post(
            "/api/challenge/guard-2/advance",
            json={"target_stage": stage},
            headers=_AUTH,
        )

    # Empty body would normally fall through to _default_next_stage(CHALLENGE)
    # == REVIEW. The guard must intercept this too.
    blocked = client.post(
        "/api/challenge/guard-2/advance",
        content=b"",
        headers=_AUTH,
    )
    assert blocked.status_code == 422
    after = client.get("/api/challenge/guard-2", headers=_AUTH)
    assert after.json()["state"]["stage"] == "challenge"


def test_advance_rejects_non_object_json_without_mutating_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")

    from ahadiff.serve import routes_challenge

    class _Snapshot:
        values = {"challenge": {"enabled": True}}

    monkeypatch.setattr(
        routes_challenge,
        "load_serve_config_snapshot",
        lambda _state: _Snapshot(),  # type: ignore[arg-type]
    )

    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )
    build_resp = client.post(
        "/api/challenge/build",
        json={"run_id": "good-run", "challenge_id": "bad-body"},
        headers=_AUTH,
    )
    assert build_resp.status_code == 200, build_resp.text

    response = client.post(
        "/api/challenge/bad-body/advance",
        json=[],
        headers=_AUTH,
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "INPUT_BAD_FIELD"
    assert read_state(state_dir, "bad-body").stage is ChallengeStage.BUILD


def test_advance_to_idle_from_challenge_still_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHALLENGE → IDLE remains reachable (this is the no-op-friendly bail)."""
    state_dir = _state_dir(tmp_path)
    _write_qualifying_run(state_dir, "good-run")

    from ahadiff.serve import routes_challenge

    class _Snapshot:
        values = {"challenge": {"enabled": True}}

    monkeypatch.setattr(
        routes_challenge,
        "load_serve_config_snapshot",
        lambda _state: _Snapshot(),  # type: ignore[arg-type]
    )

    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )
    client.post(
        "/api/challenge/build",
        json={"run_id": "good-run", "challenge_id": "guard-3"},
        headers=_AUTH,
    )
    for stage in ("tour", "challenge"):
        client.post(
            "/api/challenge/guard-3/advance",
            json={"target_stage": stage},
            headers=_AUTH,
        )
    bail = client.post(
        "/api/challenge/guard-3/advance",
        json={"target_stage": "idle"},
        headers=_AUTH,
    )
    assert bail.status_code == 200
    assert bail.json()["state"]["stage"] == "idle"
