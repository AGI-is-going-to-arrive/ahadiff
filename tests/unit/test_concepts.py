from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import ahadiff.wiki.concepts as concepts_module
from ahadiff.quiz.schemas import QuizEvidence, QuizQuestion
from ahadiff.wiki.concepts import (
    append_concepts,
    compute_term_key,
    load_concepts_page,
    load_visible_concepts,
)

if TYPE_CHECKING:
    import pytest


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
    assert calls == [head_sha]
