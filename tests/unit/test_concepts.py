from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import ahadiff.wiki.concepts as concepts_module
from ahadiff.core.errors import InputError
from ahadiff.quiz.schemas import QuizEvidence, QuizQuestion
from ahadiff.review.database import (
    count_concepts,
    initialize_review_db,
    load_commit_ancestry,
    load_concepts_from_db,
    upsert_concept,
)
from ahadiff.wiki.concepts import (
    append_concepts,
    compute_term_key,
    export_concepts_from_db,
    load_concepts_page,
    load_concepts_page_from_storage,
    load_visible_concepts,
    parse_jsonl_concepts_cursor,
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, timeout=30)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        timeout=30,
    )


def _commit_file(path: Path, name: str, content: str, message: str) -> str:
    target = path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=path, check=True, timeout=30)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=path,
        check=True,
        capture_output=True,
        timeout=30,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    ).stdout.strip()


def test_append_concepts_writes_run_local_file_for_non_git_inputs(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = workspace_root / ".ahadiff" / "runs" / "run_local"
    run_path.mkdir(parents=True)
    questions = (
        QuizQuestion(
            question="What changed?",
            expected_answer="The helper now retries.",
            source_claims=["claim_1"],
            concepts=["retry loop"],
            evidence=[QuizEvidence(file="src/app.py", line=2)],
        ),
    )

    concepts_path = append_concepts(
        workspace_root=workspace_root,
        run_path=run_path,
        run_id="run_local",
        source_kind="patch_file",
        source_ref="sha256:deadbeef",
        questions=questions,
    )

    assert concepts_path is not None
    assert concepts_path == run_path / "concepts_local.jsonl"
    assert concepts_path.exists()
    [entry] = concepts_path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(entry)
    assert payload["term_key"] == "retry-loop"
    assert payload["term"] == "retry loop"
    assert payload["display_name"] == "retry loop"
    assert payload["lang"] == "en"
    assert payload["aliases"] == []
    assert not (workspace_root / ".ahadiff" / "concepts.jsonl").exists()


def test_append_concepts_links_graphify_nodes_for_git_inputs(tmp_path: Path) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    _init_git_repo(workspace_root)
    head_sha = _commit_file(workspace_root, "src/app.py", "value = 1\n", "base")
    graph_dir = workspace_root / ".ahadiff" / "graphify"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "node-retry-loop",
                        "label": "retry loop",
                        "kind": "function",
                        "file_path": "src/app.py",
                    }
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )
    run_path = workspace_root / ".ahadiff" / "runs" / "run_git"
    run_path.mkdir(parents=True)
    questions = (
        QuizQuestion(
            question="What changed?",
            expected_answer="The helper now retries.",
            source_claims=["claim_1"],
            concepts=["retry loop"],
            evidence=[QuizEvidence(file="src/app.py", line=1)],
        ),
    )

    concepts_path = append_concepts(
        workspace_root=workspace_root,
        run_path=run_path,
        run_id="run_git",
        source_kind="git_ref",
        source_ref=head_sha,
        questions=questions,
    )

    assert concepts_path is not None
    [payload] = [
        json.loads(line)
        for line in concepts_path.read_text(encoding="utf-8").splitlines()
    ]
    assert payload["graphify_node_id"] == "node-retry-loop"
    [db_payload] = load_concepts_from_db(workspace_root / ".ahadiff" / "review.sqlite")
    assert db_payload["graphify_node_id"] == "node-retry-loop"


def test_compute_term_key_supports_cjk_terms() -> None:
    assert compute_term_key("重试策略") == "u-91cd-8bd5-7b56-7565"
    assert compute_term_key("依赖注入 DI") != compute_term_key("DI")
    assert compute_term_key("Δ retry") != compute_term_key("retry")


def test_load_visible_concepts_filters_by_git_ancestry(tmp_path: Path) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    _init_git_repo(workspace_root)
    base_sha = _commit_file(workspace_root, "src/app.py", "value = 1\n", "base")
    head_sha = _commit_file(workspace_root, "src/app.py", "value = 2\nprint(value)\n", "head")
    run_path = workspace_root / ".ahadiff" / "runs" / "run_git"
    run_path.mkdir(parents=True)
    questions = (
        QuizQuestion(
            question="What changed?",
            expected_answer="The module now prints the updated value.",
            source_claims=["claim_1"],
            concepts=["stdout update"],
            evidence=[QuizEvidence(file="src/app.py", line=2)],
        ),
    )

    concepts_path = append_concepts(
        workspace_root=workspace_root,
        run_path=run_path,
        run_id="run_git",
        source_kind="git_ref",
        source_ref=head_sha,
        questions=questions,
    )

    assert concepts_path is not None
    assert concepts_path == workspace_root / ".ahadiff" / "concepts.jsonl"
    assert concepts_path.exists()
    visible_at_head = load_visible_concepts(workspace_root=workspace_root, head_ref="HEAD")
    visible_at_base = load_visible_concepts(workspace_root=workspace_root, head_ref=base_sha)

    assert len(visible_at_head) == 1
    assert visible_at_head[0]["concept"] == "stdout update"
    assert visible_at_base == ()


def test_load_visible_concepts_accepts_valid_short_sha_from_prewarmed_ancestors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    _init_git_repo(workspace_root)
    head_sha = _commit_file(workspace_root, "src/app.py", "value = 1\n", "base")
    concepts_path = workspace_root / ".ahadiff" / "concepts.jsonl"
    concepts_path.parent.mkdir(parents=True)
    concepts_path.write_text(
        json.dumps(
            {
                "term_key": "short-sha",
                "concept": "short sha",
                "source_refs": [head_sha[:12]],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_is_ancestor(_repo_root: Path, source_ref: str, _head_ref: str) -> bool:
        calls.append(source_ref)
        return False

    monkeypatch.setattr(concepts_module, "_is_ancestor", fake_is_ancestor)

    visible = load_visible_concepts(workspace_root=workspace_root, head_ref="HEAD")

    assert [entry["term_key"] for entry in visible] == ["short-sha"]
    assert calls == []


def test_load_visible_concepts_rejects_too_short_sha_prefix_from_prewarmed_ancestors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    _init_git_repo(workspace_root)
    head_sha = _commit_file(workspace_root, "src/app.py", "value = 1\n", "base")
    too_short_prefix = head_sha[:3]
    concepts_path = workspace_root / ".ahadiff" / "concepts.jsonl"
    concepts_path.parent.mkdir(parents=True)
    concepts_path.write_text(
        json.dumps(
            {
                "term_key": "too-short-sha",
                "concept": "too short sha",
                "source_refs": [too_short_prefix],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_is_ancestor(_repo_root: Path, source_ref: str, _head_ref: str) -> bool:
        calls.append(source_ref)
        return False

    monkeypatch.setattr(concepts_module, "_is_ancestor", fake_is_ancestor)

    visible = load_visible_concepts(workspace_root=workspace_root, head_ref="HEAD")

    assert visible == ()
    assert calls == [too_short_prefix]


def test_load_concepts_page_streams_with_line_cursor(tmp_path: Path) -> None:
    concepts_path = tmp_path / "concepts.jsonl"
    concepts_path.write_text(
        "\n".join(
            json.dumps({"term_key": f"term-{index}", "concept": f"term {index}"})
            for index in range(3)
        )
        + "\n",
        encoding="utf-8",
    )

    first_page = load_concepts_page(concepts_path, limit=2)
    second_page = load_concepts_page(
        concepts_path,
        limit=2,
        cursor=int(first_page.next_cursor or "0"),
    )

    assert [entry["term_key"] for entry in first_page.entries] == ["term-0", "term-1"]
    assert first_page.next_cursor == "3"
    assert [entry["term_key"] for entry in second_page.entries] == ["term-2"]
    assert second_page.next_cursor is None


def test_load_concepts_page_from_storage_syncs_jsonl_before_db_read(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    (state_dir / "concepts.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "term_key": f"term-{index}",
                    "concept": f"term {index}",
                    "term": f"term {index}",
                    "display_name": f"term {index}",
                    "lang": "en",
                    "aliases": [],
                    "source_refs": ["abc123"],
                    "branch_hint": "main",
                    "introduced_by_run": "run_a",
                    "updated_by_runs": ["run_a"],
                    "related_claims": [],
                    "file_refs": [],
                }
            )
            + "\n"
            for index in range(2)
        ),
        encoding="utf-8",
    )

    page = load_concepts_page_from_storage(state_dir, limit=10)

    assert [entry["term_key"] for entry in page.entries] == ["term-0", "term-1"]
    assert count_concepts(db_path) == 2


def test_load_concepts_page_from_storage_keeps_jsonl_cursor_on_jsonl_path(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    concepts_path = state_dir / "concepts.jsonl"
    concepts_path.write_text(
        "".join(
            json.dumps({"term_key": f"term-{index}", "concept": f"term {index}"}) + "\n"
            for index in range(3)
        ),
        encoding="utf-8",
    )

    first = load_concepts_page_from_storage(state_dir, limit=2)
    initialize_review_db(state_dir / "review.sqlite")
    second = load_concepts_page_from_storage(state_dir, limit=2, cursor=first.next_cursor)

    assert [entry["term_key"] for entry in first.entries] == ["term-0", "term-1"]
    assert first.next_cursor == "jsonl:3"
    assert [entry["term_key"] for entry in second.entries] == ["term-2"]
    assert second.next_cursor is None


def test_load_concepts_page_from_storage_db_cursor_is_stable(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    for index in range(3):
        upsert_concept(
            db_path,
            term_key=f"term-{index}",
            concept=f"term {index}",
            run_id="run-a",
            source_ref="abc123",
            branch_hint=None,
            related_claims=(),
            file_refs=(),
        )

    first = load_concepts_page_from_storage(state_dir, limit=2)
    second = load_concepts_page_from_storage(state_dir, limit=2, cursor=first.next_cursor)

    assert [entry["term_key"] for entry in first.entries] == ["term-0", "term-1"]
    assert first.next_cursor == "db:term-1"
    assert [entry["term_key"] for entry in second.entries] == ["term-2"]
    assert second.next_cursor is None


def test_load_concepts_page_from_storage_db_cursor_falls_back_to_jsonl(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    (state_dir / "concepts.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "term_key": f"term-{index}",
                    "concept": f"term {index}",
                    "term": f"term {index}",
                    "display_name": f"term {index}",
                    "lang": "en",
                    "aliases": [],
                    "source_refs": ["abc123"],
                    "branch_hint": "main",
                    "introduced_by_run": "run_a",
                    "updated_by_runs": ["run_a"],
                    "related_claims": [],
                    "file_refs": [],
                }
            )
            + "\n"
            for index in range(3)
        ),
        encoding="utf-8",
    )

    first = load_concepts_page_from_storage(state_dir, limit=2)
    db_path.unlink()
    second = load_concepts_page_from_storage(state_dir, limit=2, cursor=first.next_cursor)

    assert first.next_cursor == "db:term-1"
    assert [entry["term_key"] for entry in second.entries] == ["term-2"]
    assert second.next_cursor is None


def test_load_concepts_page_from_storage_rejects_unknown_legacy_db_cursor(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "concepts.jsonl").write_text(
        json.dumps({"term_key": "term-1", "concept": "term 1"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(InputError, match="not compatible"):
        load_concepts_page_from_storage(state_dir, limit=2, cursor="db:missing-term")


def test_export_concepts_from_db_paginates_until_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db_path = state_dir / "review.sqlite"
    db_path.write_text("", encoding="utf-8")
    pages: dict[str | None, tuple[dict[str, object], ...]] = {
        None: (
            {
                "term_key": "term-0",
                "concept": "term 0",
                "created_at_utc": "a",
                "updated_at_utc": "b",
            },
            {
                "term_key": "term-1",
                "concept": "term 1",
                "created_at_utc": "a",
                "updated_at_utc": "b",
            },
        ),
        "term-1": (
            {
                "term_key": "term-2",
                "concept": "term 2",
                "created_at_utc": "a",
                "updated_at_utc": "b",
            },
        ),
    }
    calls: list[tuple[int, str | None]] = []

    def fake_load_concepts_from_db(
        _db_path: Path,
        *,
        limit: int = 100,
        after_term_key: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        calls.append((limit, after_term_key))
        return pages.get(after_term_key, ())

    monkeypatch.setattr(
        "ahadiff.review.database.load_concepts_from_db",
        fake_load_concepts_from_db,
    )

    exported = export_concepts_from_db(state_dir)

    assert exported == state_dir / "concepts.jsonl"
    payloads = [json.loads(line) for line in exported.read_text(encoding="utf-8").splitlines()]
    assert [payload["term_key"] for payload in payloads] == ["term-0", "term-1", "term-2"]
    assert all("created_at_utc" not in payload for payload in payloads)
    assert all("updated_at_utc" not in payload for payload in payloads)
    assert calls == [
        (1000, None),
        (1000, "term-1"),
        (1000, "term-2"),
    ]


def test_parse_jsonl_concepts_cursor_rejects_invalid_values() -> None:
    assert parse_jsonl_concepts_cursor(None) == 0
    assert parse_jsonl_concepts_cursor("3") == 3
    with pytest.raises(InputError, match="must be an integer"):
        parse_jsonl_concepts_cursor("not-an-int")
    with pytest.raises(InputError, match="must be >= 0"):
        parse_jsonl_concepts_cursor("-1")


def test_append_concepts_propagates_sqlite_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    _init_git_repo(workspace_root)
    head_sha = _commit_file(workspace_root, "src/app.py", "value = 1\n", "base")
    run_path = workspace_root / ".ahadiff" / "runs" / "run_git"
    run_path.mkdir(parents=True)
    questions = (
        QuizQuestion(
            question="What changed?",
            expected_answer="The module now stores a value.",
            source_claims=["claim_1"],
            concepts=["value storage"],
            evidence=[QuizEvidence(file="src/app.py", line=1)],
        ),
    )

    def fail_upsert(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("db sync failed")

    monkeypatch.setattr("ahadiff.review.database.upsert_concepts_batch", fail_upsert)

    with pytest.raises(RuntimeError, match="db sync failed"):
        append_concepts(
            workspace_root=workspace_root,
            run_path=run_path,
            run_id="run_git",
            source_kind="git_ref",
            source_ref=head_sha,
            questions=questions,
        )


def test_load_visible_concepts_streams_and_memoizes_ancestry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    _init_git_repo(workspace_root)
    head_sha = _commit_file(workspace_root, "src/app.py", "value = 1\n", "base")
    concepts_path = workspace_root / ".ahadiff" / "concepts.jsonl"
    concepts_path.parent.mkdir(parents=True)
    with concepts_path.open("w", encoding="utf-8") as handle:
        for index in range(10_000):
            handle.write(
                json.dumps(
                    {
                        "term_key": f"term-{index}",
                        "concept": f"term {index}",
                        "source_refs": [head_sha],
                    }
                )
                + "\n"
            )
    calls: list[str] = []

    def fake_is_ancestor(repo_root: Path, source_ref: str, head_ref: str) -> bool:
        assert repo_root == workspace_root
        assert head_ref == "HEAD"
        calls.append(source_ref)
        return True

    def fail_read_text(
        self: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if self == concepts_path:
            raise AssertionError("concepts.jsonl must be streamed, not read_text()")
        return original_read_text(self, encoding=encoding, errors=errors)

    original_read_text = Path.read_text
    monkeypatch.setattr(concepts_module, "_is_ancestor", fake_is_ancestor)
    monkeypatch.setattr(Path, "read_text", fail_read_text)

    visible = load_visible_concepts(workspace_root=workspace_root, head_ref="HEAD")

    assert len(visible) == 10_000
    assert calls == [], "batch ancestry pre-warm should avoid per-ref subprocess calls"


def test_ancestry_cache_fails_closed_after_200_fallback_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    _init_git_repo(workspace_root)
    _commit_file(workspace_root, "src/app.py", "v = 1\n", "init")
    concepts_path = workspace_root / ".ahadiff" / "concepts.jsonl"
    concepts_path.parent.mkdir(parents=True)
    max_checks = 200
    unique_refs = [f"deadbeef{i:04x}00000000000000000000000000" for i in range(max_checks + 10)]
    with concepts_path.open("w", encoding="utf-8") as handle:
        for i, ref in enumerate(unique_refs):
            handle.write(
                json.dumps({"term_key": f"term-{i}", "concept": f"term {i}", "source_refs": [ref]})
                + "\n"
            )
    fallback_calls: list[str] = []

    def fake_is_ancestor(_repo_root: Path, source_ref: str, _head_ref: str) -> bool:
        fallback_calls.append(source_ref)
        return False

    monkeypatch.setattr(concepts_module, "_is_ancestor", fake_is_ancestor)

    visible = load_visible_concepts(workspace_root=workspace_root, head_ref="HEAD")

    assert len(fallback_calls) == max_checks, "must not exceed fallback subprocess budget"
    assert visible == (), "entries beyond fallback budget must fail closed"


def test_load_concepts_page_from_storage_falls_back_to_jsonl_on_db_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db_path = state_dir / "review.sqlite"
    db_path.write_bytes(b"not a valid sqlite database")
    (state_dir / "concepts.jsonl").write_text(
        json.dumps({"term_key": "fallback-term", "concept": "fallback concept"}) + "\n",
        encoding="utf-8",
    )

    page = load_concepts_page_from_storage(state_dir, limit=10)

    assert len(page.entries) == 1
    assert page.entries[0]["term_key"] == "fallback-term"


def test_load_concepts_page_from_storage_empty_when_no_source(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()

    page = load_concepts_page_from_storage(state_dir, limit=10)

    assert page.entries == ()
    assert page.next_cursor is None


def test_sync_jsonl_to_db_is_idempotent(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    (state_dir / "concepts.jsonl").write_text(
        json.dumps(
            {
                "term_key": "idem-term",
                "concept": "idempotent concept",
                "term": "idempotent concept",
                "display_name": "idempotent concept",
                "lang": "en",
                "aliases": ["alias1"],
                "source_refs": ["abc123"],
                "branch_hint": "main",
                "introduced_by_run": "run_a",
                "updated_by_runs": ["run_a"],
                "related_claims": [],
                "file_refs": ["src/app.py"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    page1 = load_concepts_page_from_storage(state_dir, limit=10)
    page2 = load_concepts_page_from_storage(state_dir, limit=10)

    assert count_concepts(db_path) == 1
    assert page1.entries[0]["term_key"] == page2.entries[0]["term_key"]
    assert page1.entries[0]["aliases"] == page2.entries[0]["aliases"]


def test_export_and_reimport_roundtrip(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    db_path = state_dir / "review.sqlite"
    initialize_review_db(db_path)
    original_jsonl = state_dir / "concepts.jsonl"
    entries = [
        {
            "term_key": f"rt-{i}",
            "concept": f"roundtrip {i}",
            "term": f"roundtrip {i}",
            "display_name": f"roundtrip {i}",
            "lang": "en",
            "aliases": [f"alt-{i}"],
            "source_refs": ["sha1"],
            "branch_hint": "main",
            "introduced_by_run": "run_a",
            "updated_by_runs": ["run_a"],
            "related_claims": [],
            "file_refs": [],
        }
        for i in range(3)
    ]
    original_jsonl.write_text(
        "".join(json.dumps(e) + "\n" for e in entries),
        encoding="utf-8",
    )

    load_concepts_page_from_storage(state_dir, limit=100)
    assert count_concepts(db_path) == 3

    exported = export_concepts_from_db(state_dir)
    lines = exported.read_text(encoding="utf-8").splitlines()
    exported_entries = [json.loads(line) for line in lines]
    assert len(exported_entries) == 3
    for i, entry in enumerate(exported_entries):
        assert entry["term_key"] == f"rt-{i}"
        assert entry["aliases"] == [f"alt-{i}"]
        assert "created_at_utc" not in entry


@pytest.mark.skipif(not hasattr(__import__("os"), "mkfifo"), reason="requires FIFO support")
def test_concepts_jsonl_fifo_rejected(tmp_path: Path) -> None:
    import os

    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    fifo_path = state_dir / "concepts.jsonl"
    os.mkfifo(fifo_path)
    page = load_concepts_page_from_storage(state_dir, limit=10)
    assert page.entries == ()


def test_concept_entry_includes_graphify_node_id_field(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = workspace_root / ".ahadiff" / "runs" / "run_local"
    run_path.mkdir(parents=True)
    questions = (
        QuizQuestion(
            question="What changed?",
            expected_answer="A retry loop was added.",
            source_claims=["claim_1"],
            concepts=["retry loop"],
            evidence=[QuizEvidence(file="src/app.py", line=2)],
        ),
    )
    concepts_path = append_concepts(
        workspace_root=workspace_root,
        run_path=run_path,
        run_id="run_local",
        source_kind="patch_file",
        source_ref="sha256:deadbeef",
        questions=questions,
    )
    assert concepts_path is not None
    [entry] = concepts_path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(entry)
    assert "graphify_node_id" in payload
    assert payload["graphify_node_id"] is None


def test_ancestry_prefix_index_resolves_short_sha_without_linear_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.wiki.concepts import _AncestryCache  # pyright: ignore[reportPrivateUsage]

    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    _init_git_repo(workspace_root)
    head_sha = _commit_file(workspace_root, "src/app.py", "v = 1\n", "init")

    cache = _AncestryCache(workspace_root, "HEAD")
    ancestors = cache._ensure_ancestors()  # pyright: ignore[reportPrivateUsage]
    assert head_sha in ancestors

    assert cache._prefix_index is not None  # pyright: ignore[reportPrivateUsage]
    assert head_sha[:8] in cache._prefix_index  # pyright: ignore[reportPrivateUsage]

    fallback_calls: list[str] = []

    def fake_is_ancestor(_repo_root: Path, source_ref: str, _head_ref: str) -> bool:
        fallback_calls.append(source_ref)
        return False

    monkeypatch.setattr(concepts_module, "_is_ancestor", fake_is_ancestor)

    assert cache.is_visible(head_sha[:8]) is True
    assert fallback_calls == []


def test_ancestry_cache_persists_and_reuses_commit_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.wiki.concepts import _AncestryCache  # pyright: ignore[reportPrivateUsage]

    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    _init_git_repo(workspace_root)
    base_sha = _commit_file(workspace_root, "src/app.py", "v = 1\n", "base")
    head_sha = _commit_file(workspace_root, "src/app.py", "v = 2\n", "head")

    cache = _AncestryCache(workspace_root, "HEAD")
    ancestors = cache._ensure_ancestors()  # pyright: ignore[reportPrivateUsage]
    assert {base_sha, head_sha}.issubset(ancestors)
    stored = load_commit_ancestry(
        workspace_root / ".ahadiff" / "review.sqlite",
        head_sha=head_sha,
    )
    assert stored[:2] == (head_sha, base_sha)

    original_run_git = concepts_module.run_git

    def guarded_run_git(repo_root: Path, *args: Any, **kwargs: Any) -> Any:
        if args and args[0] == "rev-list":
            raise AssertionError("cached ancestry should avoid git rev-list")
        return original_run_git(repo_root, *args, **kwargs)

    monkeypatch.setattr(concepts_module, "run_git", guarded_run_git)
    cached = _AncestryCache(workspace_root, "HEAD")
    assert head_sha in cached._ensure_ancestors()  # pyright: ignore[reportPrivateUsage]
    assert cached.is_visible(base_sha[:8]) is True


def test_ancestry_prefix_index_excludes_ambiguous_prefixes() -> None:
    from ahadiff.wiki.concepts import _build_prefix_index  # pyright: ignore[reportPrivateUsage]

    sha_a = "abcdef1234567890abcdef1234567890abcdef12"
    sha_b = "abcdef9999567890abcdef1234567890abcdef12"
    index = _build_prefix_index(frozenset({sha_a, sha_b}))
    assert "abcdef" not in index
    assert sha_a[:20] in index
    assert sha_b[:20] in index
