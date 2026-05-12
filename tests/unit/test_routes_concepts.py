"""Tests for GET /api/concepts/ledger endpoint."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from ahadiff.review.database import connect_review_db, initialize_review_db
from ahadiff.serve.app import create_app
from ahadiff.serve.state import ServeState

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


_AUTH = {"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"}


def _client(state_dir: Path) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token="test-token", locale="en"))
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


def _init_repo_with_head(tmp_path: Path) -> tuple[Path, str]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "AhaDiff Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "src/foo.py")
    _git(tmp_path, "commit", "-qm", "initial", "--no-gpg-sign")
    return tmp_path / ".ahadiff", _git(tmp_path, "rev-parse", "HEAD")


def _write_concepts(state_dir: Path, entries: Sequence[Mapping[str, object]]) -> None:
    state_dir.mkdir(exist_ok=True)
    concepts_path = state_dir / "concepts.jsonl"
    concepts_path.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )


def test_concepts_ledger_empty(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/concepts/ledger", headers=_AUTH)

    assert response.status_code == 200
    assert response.json() == {"entries": [], "next_cursor": None, "total_count": 0}


def test_concepts_ledger_with_data(tmp_path: Path) -> None:
    state_dir, head_sha = _init_repo_with_head(tmp_path)
    entries = [
        {
            "term_key": "concept_1",
            "concept": "concept_1",
            "term": "concept_1",
            "display_name": "Concept One",
            "lang": "en",
            "aliases": ["Concept 1"],
            "source_refs": [head_sha],
            "branch_hint": "main",
            "introduced_by_run": "run-1",
            "updated_by_runs": ["run-1"],
            "related_claims": ["c1"],
            "file_refs": ["src/foo.py"],
            "graphify_node_id": None,
        },
        {
            "term_key": "concept_2",
            "concept": "concept_2",
            "display_name": "Concept Two",
            "source_refs": [head_sha],
            "updated_by_runs": ["run-2"],
            "related_claims": [],
            "file_refs": [],
        },
    ]
    _write_concepts(state_dir, entries)
    client = _client(state_dir)

    response = client.get("/api/concepts/ledger", headers=_AUTH)

    assert response.status_code == 200
    data = response.json()
    assert data["next_cursor"] is None
    assert data["total_count"] == 2
    assert [entry["term_key"] for entry in data["entries"]] == ["concept_1", "concept_2"]
    assert data["entries"][0] == {
        "term_key": "concept_1",
        "concept": "concept_1",
        "display_name": "Concept One",
        "source_refs": [head_sha],
        "updated_by_runs": ["run-1"],
        "related_claims": ["c1"],
        "file_refs": ["src/foo.py"],
    }


def test_concepts_ledger_pagination(tmp_path: Path) -> None:
    state_dir, head_sha = _init_repo_with_head(tmp_path)
    _write_concepts(
        state_dir,
        [
            {
                "term_key": f"concept_{index}",
                "concept": f"concept_{index}",
                "display_name": f"Concept {index}",
                "source_refs": [head_sha],
                "updated_by_runs": [f"run-{index}"],
                "related_claims": [],
                "file_refs": [],
            }
            for index in range(5)
        ],
    )
    client = _client(state_dir)

    first = client.get("/api/concepts/ledger?limit=2", headers=_AUTH).json()
    second = client.get(
        f"/api/concepts/ledger?limit=2&cursor={first['next_cursor']}",
        headers=_AUTH,
    ).json()

    assert first["next_cursor"] == "2"
    assert [entry["term_key"] for entry in first["entries"]] == ["concept_0", "concept_1"]
    assert second["next_cursor"] == "4"
    assert [entry["term_key"] for entry in second["entries"]] == ["concept_2", "concept_3"]
    assert second["total_count"] == 5


def test_concepts_ledger_run_filter(tmp_path: Path) -> None:
    state_dir, head_sha = _init_repo_with_head(tmp_path)
    _write_concepts(
        state_dir,
        [
            {
                "term_key": "concept_1",
                "concept": "concept_1",
                "display_name": "Concept One",
                "source_refs": [head_sha],
                "updated_by_runs": ["run-1"],
                "related_claims": ["c1"],
                "file_refs": ["src/foo.py"],
            },
            {
                "term_key": "concept_2",
                "concept": "concept_2",
                "display_name": "Concept Two",
                "source_refs": [head_sha],
                "updated_by_runs": ["run-2"],
                "related_claims": [],
                "file_refs": [],
            },
        ],
    )
    client = _client(state_dir)

    response = client.get("/api/concepts/ledger?run=run-1", headers=_AUTH)

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 1
    assert [entry["term_key"] for entry in data["entries"]] == ["concept_1"]


def test_concepts_ledger_includes_health_status_from_db(tmp_path: Path) -> None:
    state_dir, head_sha = _init_repo_with_head(tmp_path)
    _write_concepts(
        state_dir,
        [
            {
                "term_key": "concept_1",
                "concept": "concept_1",
                "display_name": "Concept One",
                "source_refs": [head_sha],
                "updated_by_runs": ["run-1"],
                "related_claims": ["c1"],
                "file_refs": ["src/foo.py"],
            }
        ],
    )
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    with connect_review_db(db_path) as connection:
        connection.execute(
            """
            INSERT INTO concept_status (
                term_key, health_status, refcount, updated_at_utc
            ) VALUES (?, ?, ?, ?)
            """,
            ("concept_1", "contradicted", 0, "2026-05-12T00:00:00Z"),
        )
    client = _client(state_dir)

    response = client.get("/api/concepts/ledger", headers=_AUTH)

    assert response.status_code == 200
    data = response.json()
    assert data["entries"][0]["health_status"] == "contradicted"


def test_concepts_ledger_401_without_token(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/concepts/ledger")

    assert response.status_code == 401
