"""Tests for the read-only GET /api/improve/preflight endpoint.

The endpoint MUST NOT mutate filesystem, git state, locks, or worktrees;
these tests pin the contract (no auth bypass, no absolute paths leaked,
malformed sessions skipped) so a future refactor cannot accidentally
turn it into a write endpoint.
"""

from __future__ import annotations

import json
import platform
import subprocess
from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from ahadiff.serve.app import create_app
from ahadiff.serve.state import ServeState

if TYPE_CHECKING:
    from pathlib import Path

_AUTH = {"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"}


def _client(state_dir: Path, *, token: str = "test-token") -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token=token, locale="en"))
    return TestClient(app, base_url="http://localhost:8765")


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    """Initialize a git repo and return the ``.ahadiff`` state dir (uncreated)."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "AhaDiff Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "src/foo.py")
    _git(tmp_path, "commit", "-qm", "initial", "--no-gpg-sign")
    return tmp_path / ".ahadiff"


def test_improve_preflight_no_db(tmp_path: Path) -> None:
    """Empty state_dir without review.sqlite returns no_finalized_runs."""
    state_dir = _init_repo(tmp_path)
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/improve/preflight", headers=_AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == "no_finalized_runs"
    assert body["anchor_run"] is None
    assert body["baseline_run"] is None
    assert body["target_dimension"] is None
    assert body["target_prompt_file"] is None
    assert body["existing_sessions"] == []
    assert body["phase25_eligible"] is False
    assert body["provider_configured"] is False
    repo_state = body["repo_state"]
    assert "branch" in repo_state
    assert "head_sha" in repo_state
    assert "prompts_dirty" in repo_state
    # mutable_prompts is the canonical 5-prompt set
    assert set(body["mutable_prompts"]) >= {
        "claim_extract.md",
        "lesson_generate.md",
        "lesson_compact.md",
        "lesson_hint.md",
        "quiz_generate.md",
    }


def test_improve_preflight_with_sessions(tmp_path: Path) -> None:
    """Sessions on disk are surfaced in newest-first order."""
    state_dir = _init_repo(tmp_path)
    state_dir.mkdir()
    sessions_dir = state_dir / "improve"
    sessions_dir.mkdir()
    payload = {
        "session_id": "session-1",
        "suite": "default",
        "anchor_run_id": "run-anchor",
        "phase25_attempted": False,
        "rounds_completed": 2,
        "worktree_path": None,
        "created_at": "2026-05-09T00:00:00Z",
        "updated_at": "2026-05-09T01:00:00Z",
        "last_status": "discard",
        "outcome_statuses": ["discard"],
    }
    (sessions_dir / "session-1.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    # Hidden / dotfile sessions must be skipped.
    (sessions_dir / ".hidden.json").write_text("{}", encoding="utf-8")
    # Malformed session: must be skipped, not raise.
    (sessions_dir / "broken.json").write_text("{not json", encoding="utf-8")

    client = _client(state_dir)
    response = client.get("/api/improve/preflight", headers=_AUTH)

    assert response.status_code == 200
    body = response.json()
    sessions = body["existing_sessions"]
    assert len(sessions) == 1
    summary = sessions[0]
    assert summary["session_id"] == "session-1"
    assert summary["rounds_completed"] == 2
    assert summary["last_status"] == "discard"
    assert summary["phase25_attempted"] is False
    assert summary["has_pending_worktree"] is False
    assert summary["updated_at"] == "2026-05-09T01:00:00Z"
    # last_status == "discard" + phase25_attempted == False ⇒ phase25 eligible
    assert body["phase25_eligible"] is True
    assert body["phase25_trigger_reason"] == "latest_session_discarded"


def test_improve_preflight_repo_state(tmp_path: Path) -> None:
    """Repo state surface always includes branch/head_sha/prompts_dirty keys."""
    state_dir = _init_repo(tmp_path)
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/improve/preflight", headers=_AUTH)
    assert response.status_code == 200

    repo_state = response.json()["repo_state"]
    # Branch is whatever ``git init`` chose locally (master or main); just
    # require a non-empty string.
    assert isinstance(repo_state["branch"], str)
    assert repo_state["branch"]
    assert isinstance(repo_state["head_sha"], str)
    assert len(repo_state["head_sha"]) == 40
    assert repo_state["prompts_dirty"] is False


def test_improve_preflight_no_absolute_paths(tmp_path: Path) -> None:
    """Response JSON must not leak absolute filesystem paths.

    This guards against an accidental regression where worktree/path strings
    bleed into the response body. The endpoint contract surfaces only
    ``has_pending_worktree`` (boolean), never the worktree path itself.
    """
    state_dir = _init_repo(tmp_path)
    state_dir.mkdir()
    sessions_dir = state_dir / "improve"
    sessions_dir.mkdir()
    # Session with a worktree_path that points to a real existing dir; the
    # endpoint must surface only the boolean, never the path string.
    fake_worktree = tmp_path / "worktree-leak-canary"
    fake_worktree.mkdir()
    payload = {
        "session_id": "session-with-worktree",
        "suite": "default",
        "anchor_run_id": "run-anchor",
        "phase25_attempted": False,
        "rounds_completed": 1,
        "worktree_path": str(fake_worktree),
        "created_at": "2026-05-09T00:00:00Z",
        "updated_at": "2026-05-09T01:00:00Z",
        "last_status": "keep",
        "outcome_statuses": ["keep"],
    }
    (sessions_dir / "session-with-worktree.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    client = _client(state_dir)
    response = client.get("/api/improve/preflight", headers=_AUTH)
    assert response.status_code == 200

    raw = response.text
    # Forbidden absolute-path roots
    assert "/Users" not in raw
    assert "/home/" not in raw
    assert "/private/var" not in raw
    assert "C:\\" not in raw
    assert "C:/" not in raw
    # The leak canary path itself must never appear.
    assert "worktree-leak-canary" not in raw
    # Sanity: tmp_path components must not leak either. On macOS tmp paths
    # often live under /var/folders/... so guard against the tmp root.
    if platform.system() != "Windows":
        assert str(tmp_path) not in raw

    body = response.json()
    sessions = body["existing_sessions"]
    assert len(sessions) == 1
    # has_pending_worktree should be True since fake_worktree exists; this
    # confirms the boolean was computed without the path crossing the wire.
    assert sessions[0]["has_pending_worktree"] is True


def test_improve_preflight_401(tmp_path: Path) -> None:
    """Missing X-AhaDiff-Token must yield 401."""
    state_dir = _init_repo(tmp_path)
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/improve/preflight")
    assert response.status_code == 401


def test_improve_preflight_wrong_token(tmp_path: Path) -> None:
    """Wrong token must also yield 401 (not 200)."""
    state_dir = _init_repo(tmp_path)
    state_dir.mkdir()
    client = _client(state_dir, token="correct-token")

    response = client.get(
        "/api/improve/preflight",
        headers={"X-AhaDiff-Token": "wrong-token", "origin": "http://localhost:8765"},
    )
    assert response.status_code == 401
