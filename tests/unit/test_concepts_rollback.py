from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ahadiff.core.errors import InputError
from ahadiff.review.database import (
    initialize_review_db,
    upsert_concepts_batch,
)
from ahadiff.wiki.concepts import (
    rollback_concepts_to_jsonl,
    verify_concepts_consistency,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_entry(term_key: str, concept: str | None = None) -> dict[str, object]:
    name = concept or term_key
    return {
        "term_key": term_key,
        "concept": name,
        "term": name,
        "display_name": name,
        "lang": "en",
        "aliases": [],
        "source_refs": ["abc123"],
        "branch_hint": "main",
        "introduced_by_run": "run-1",
        "updated_by_runs": ["run-1"],
        "related_claims": [],
        "file_refs": ["src/foo.py"],
        "graphify_node_id": None,
    }


# ---------------------------------------------------------------------------
# rollback_concepts_to_jsonl
# ---------------------------------------------------------------------------


class TestRollbackConceptsToJsonl:
    def test_normal_export(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        jsonl_path = tmp_path / "concepts.jsonl"
        initialize_review_db(db_path)
        entries = [_make_entry("alpha"), _make_entry("beta"), _make_entry("gamma")]
        upsert_concepts_batch(db_path, entries)

        count = rollback_concepts_to_jsonl(db_path, jsonl_path)

        assert count == 3
        assert jsonl_path.exists()
        lines = [json.loads(line) for line in jsonl_path.read_text("utf-8").strip().splitlines()]
        assert len(lines) == 3
        exported_keys = {line["term_key"] for line in lines}
        assert exported_keys == {"alpha", "beta", "gamma"}

    def test_empty_table(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        jsonl_path = tmp_path / "concepts.jsonl"
        initialize_review_db(db_path)

        count = rollback_concepts_to_jsonl(db_path, jsonl_path)

        assert count == 0
        assert jsonl_path.exists()
        assert jsonl_path.read_text("utf-8").strip() == ""

    def test_db_not_found(self, tmp_path: Path) -> None:
        db_path = tmp_path / "missing.sqlite"
        jsonl_path = tmp_path / "concepts.jsonl"

        with pytest.raises(InputError, match="review.sqlite not found"):
            rollback_concepts_to_jsonl(db_path, jsonl_path)

    def test_rejects_jsonl_outside_db_parent(self, tmp_path: Path) -> None:
        db_dir = tmp_path / "repo" / ".ahadiff"
        db_dir.mkdir(parents=True)
        db_path = db_dir / "review.sqlite"
        initialize_review_db(db_path)
        upsert_concepts_batch(db_path, [_make_entry("alpha")])

        outside_path = tmp_path / "elsewhere" / "concepts.jsonl"

        with pytest.raises(InputError, match="must be under"):
            rollback_concepts_to_jsonl(db_path, outside_path)

    def test_rejects_symlinked_jsonl_path(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        initialize_review_db(db_path)
        upsert_concepts_batch(db_path, [_make_entry("alpha")])

        real_file = tmp_path / "real_concepts.jsonl"
        real_file.write_text("", encoding="utf-8")
        symlink_path = tmp_path / "concepts.jsonl"
        symlink_path.symlink_to(real_file)

        with pytest.raises(InputError, match="must not be a symlink"):
            rollback_concepts_to_jsonl(db_path, symlink_path)

    def test_excludes_db_only_keys(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        jsonl_path = tmp_path / "concepts.jsonl"
        initialize_review_db(db_path)
        upsert_concepts_batch(db_path, [_make_entry("delta")])

        rollback_concepts_to_jsonl(db_path, jsonl_path)

        lines = [json.loads(line) for line in jsonl_path.read_text("utf-8").strip().splitlines()]
        assert len(lines) == 1
        assert "created_at_utc" not in lines[0]
        assert "updated_at_utc" not in lines[0]

    def test_atomic_write_no_partial(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        jsonl_path = tmp_path / "concepts.jsonl"
        jsonl_path.write_text("old content\n", encoding="utf-8")
        initialize_review_db(db_path)
        upsert_concepts_batch(db_path, [_make_entry("epsilon")])

        rollback_concepts_to_jsonl(db_path, jsonl_path)

        content = jsonl_path.read_text("utf-8").strip()
        assert "old content" not in content
        lines = content.splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["term_key"] == "epsilon"

    def test_overwrites_existing_jsonl(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        jsonl_path = tmp_path / "concepts.jsonl"
        jsonl_path.write_text(
            json.dumps({"term_key": "stale", "concept": "stale"}) + "\n",
            encoding="utf-8",
        )
        initialize_review_db(db_path)
        upsert_concepts_batch(db_path, [_make_entry("fresh")])

        count = rollback_concepts_to_jsonl(db_path, jsonl_path)

        assert count == 1
        lines = [json.loads(line) for line in jsonl_path.read_text("utf-8").strip().splitlines()]
        assert len(lines) == 1
        assert lines[0]["term_key"] == "fresh"


# ---------------------------------------------------------------------------
# verify_concepts_consistency
# ---------------------------------------------------------------------------


class TestVerifyConceptsConsistency:
    def test_consistent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        jsonl_path = tmp_path / "concepts.jsonl"
        initialize_review_db(db_path)
        entries = [_make_entry("alpha"), _make_entry("beta")]
        upsert_concepts_batch(db_path, entries)
        jsonl_path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8",
        )

        ok, issues = verify_concepts_consistency(db_path, jsonl_path)

        assert ok is True
        assert issues == []

    def test_sqlite_has_extra(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        jsonl_path = tmp_path / "concepts.jsonl"
        initialize_review_db(db_path)
        upsert_concepts_batch(db_path, [_make_entry("alpha"), _make_entry("beta")])
        jsonl_path.write_text(
            json.dumps(_make_entry("alpha")) + "\n",
            encoding="utf-8",
        )

        ok, issues = verify_concepts_consistency(db_path, jsonl_path)

        assert ok is False
        assert any("count mismatch" in msg for msg in issues)
        assert any("only in SQLite" in msg for msg in issues)

    def test_jsonl_has_extra(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        jsonl_path = tmp_path / "concepts.jsonl"
        initialize_review_db(db_path)
        upsert_concepts_batch(db_path, [_make_entry("alpha")])
        jsonl_path.write_text(
            "\n".join(json.dumps(e) for e in [_make_entry("alpha"), _make_entry("beta")]) + "\n",
            encoding="utf-8",
        )

        ok, issues = verify_concepts_consistency(db_path, jsonl_path)

        assert ok is False
        assert any("count mismatch" in msg for msg in issues)
        assert any("only in JSONL" in msg for msg in issues)

    def test_both_empty(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        jsonl_path = tmp_path / "concepts.jsonl"
        initialize_review_db(db_path)
        jsonl_path.write_text("", encoding="utf-8")

        ok, issues = verify_concepts_consistency(db_path, jsonl_path)

        assert ok is True
        assert issues == []

    def test_both_missing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "missing.sqlite"
        jsonl_path = tmp_path / "missing.jsonl"

        ok, issues = verify_concepts_consistency(db_path, jsonl_path)

        assert ok is True
        assert issues == []

    def test_only_jsonl_exists(self, tmp_path: Path) -> None:
        db_path = tmp_path / "missing.sqlite"
        jsonl_path = tmp_path / "concepts.jsonl"
        jsonl_path.write_text(
            json.dumps(_make_entry("alpha")) + "\n",
            encoding="utf-8",
        )

        ok, issues = verify_concepts_consistency(db_path, jsonl_path)

        assert ok is False
        assert any("count mismatch" in msg for msg in issues)

    def test_only_sqlite_exists(self, tmp_path: Path) -> None:
        db_path = tmp_path / "review.sqlite"
        jsonl_path = tmp_path / "missing.jsonl"
        initialize_review_db(db_path)
        upsert_concepts_batch(db_path, [_make_entry("alpha")])

        ok, issues = verify_concepts_consistency(db_path, jsonl_path)

        assert ok is False
        assert any("count mismatch" in msg for msg in issues)
