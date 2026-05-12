from __future__ import annotations

import json
from typing import TYPE_CHECKING

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
from ahadiff.core.errors import InputError
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
    assert blocked.status_code >= 400
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
    assert blocked.status_code >= 400
    after = client.get("/api/challenge/guard-2", headers=_AUTH)
    assert after.json()["state"]["stage"] == "challenge"


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
