from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from typer.testing import CliRunner

from ahadiff.claims.extract import write_claim_candidates_jsonl
from ahadiff.claims.schema import ClaimCandidate, VerifiedClaim
from ahadiff.cli import app
from ahadiff.contracts import ClaimRecord, ProviderConfig, ReviewCard, SourceHunk
from ahadiff.core.config import SecurityConfig
from ahadiff.lesson.generator import write_lesson_artifacts
from ahadiff.lesson.schemas import LessonCompact, LessonFull, LessonHint
from ahadiff.quiz.generator import (
    QuizArtifactPaths,
    build_quiz_payload,
    generate_cards_for_run,
    generate_quiz_from_run,
    load_quiz_questions,
    write_quiz_questions_jsonl,
)
from ahadiff.quiz.schemas import QuizEvidence, QuizQuestion

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from ahadiff.llm.schemas import ProviderRequest

_RUNNER = CliRunner()


def _write_quiz_run_artifacts(workspace_root: Path, run_id: str) -> Path:
    run_path = workspace_root / ".ahadiff" / "runs" / run_id
    run_path.mkdir(parents=True)
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,6 @@
-def retry_once():
-    return 1
+def retry_once():
+    for attempt in range(3):
+        try:
+            return attempt
+        except Exception:
+            continue
"""
    metadata = {
        "run_id": run_id,
        "source_kind": "git_ref",
        "source_ref": "abc1234",
        "capability_level": 3,
        "degraded_flags": {},
        "privacy_mode": "strict_local",
        "learnability": {"score": 0.8},
    }
    (run_path / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text(patch, encoding="utf-8")
    (run_path / "line_map.json").write_text(
        json.dumps(
            {
                "artifact": "line_map",
                "schema": "ahadiff.line_map",
                "schema_version": 1,
                "files": [
                    {
                        "change_kind": "modified",
                        "display_path": "src/app.py",
                        "file_id": "file_app",
                        "path_identity_key": "src/app.py",
                        "old_path": "src/app.py",
                        "new_path": "src/app.py",
                        "hunks": [
                            {
                                "added_lines": [1, 2, 3, 4, 5, 6],
                                "change_kind": "modified",
                                "context_new_lines": [],
                                "context_old_lines": [],
                                "deleted_lines": [1, 2],
                                "display_path": "src/app.py",
                                "file_id": "file_app",
                                "hunk_hash": "deadbeef1234",
                                "hunk_id": "hunk_retry",
                                "new_end": 6,
                                "new_start": 1,
                                "old_end": 2,
                                "old_start": 1,
                                "section_header": "def retry_once():",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_path / "symbols.json").write_text(
        json.dumps(
            {
                "schema": "ahadiff.symbols",
                "schema_version": 1,
                "symbols": [
                    {
                        "path": "src/app.py",
                        "qualified_name": "retry_once",
                        "kind": "function",
                        "range": {"start": 1, "end": 6},
                        "selection_range": {"start": 1, "end": 1},
                        "parent": None,
                        "touched_lines": [1, 2, 3, 4, 5, 6],
                        "hunk_ids": ["hunk_retry"],
                        "hunk_hash": "deadbeef1234",
                        "change_kind": None,
                        "extractor": "python_ast",
                        "confidence": "high",
                        "error": None,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_path / "claims.jsonl").write_text(
        json.dumps(
            {
                "claim_id": f"{run_id}-claim-1",
                "run_id": run_id,
                "text": "The retry helper now loops across attempts.",
                "status": "verified",
                "confidence": "high",
                "source_hunks": [{"file": "src/app.py", "start": 1, "end": 6, "side": "new"}],
                "symbols": ["retry_once"],
                "negative_evidence": [],
                "extractor": "python_ast",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    lesson_dir = run_path / "lesson"
    lesson_dir.mkdir()
    (lesson_dir / "lesson.full.md").write_text("Full lesson\n", encoding="utf-8")
    return run_path


class _FakeQuizProvider:
    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    def generate(self, request: object) -> object:
        from ahadiff.llm.schemas import ProviderResponse

        self.requests.append(cast("ProviderRequest", request))
        content = json.dumps(
            {
                "questions": [
                    {
                        "question": "What structural change was added to retry_once?",
                        "expected_answer": (
                            "It now loops across attempts and continues after exceptions."
                        ),
                        "source_claims": ["run_quiz-claim-1"],
                        "concepts": ["retry loop"],
                        "evidence": [{"file": "src/app.py", "line": 2}],
                        "explanation": "The loop is the new teaching surface.",
                    },
                    {
                        "question": "Which branch is new in the helper?",
                        "expected_answer": (
                            "The exception branch now continues to the next attempt."
                        ),
                        "source_claims": ["run_quiz-claim-1"],
                        "concepts": ["exception handling"],
                        "evidence": [{"file": "src/app.py", "line": 5}],
                    },
                    {
                        "question": "What should you not overclaim from this diff?",
                        "expected_answer": "The diff does not prove backoff or reliability gains.",
                        "source_claims": ["run_quiz-claim-1"],
                        "concepts": ["evidence boundary"],
                        "evidence": [{"file": "src/app.py", "line": 2}],
                    },
                ]
            }
        )
        return ProviderResponse(
            content=content,
            model_id="gpt-5.4-mini",
            input_tokens=10,
            output_tokens=20,
        )

    def close(self) -> None:
        return None


def _sample_lessons() -> tuple[LessonFull, LessonHint, LessonCompact]:
    return (
        LessonFull(
            tl_dr="The retry helper now loops and handles transient failures.",
            what_changed=["retry_once now iterates across attempts."],
            why=["The diff adds a retry-oriented control-flow path."],
            walkthrough=["Read the new for-loop and exception handling path first."],
            claims=["The helper now loops over attempts."],
            concepts=["Retries re-run an operation after a failure."],
            misconceptions=["This does not prove exponential backoff was added."],
            not_proven=["The diff does not prove runtime reliability improved."],
            quiz=["Why is the exception branch part of the teaching surface?"],
            sources=["src/app.py:new:1-6"],
        ),
        LessonHint(
            tl_dr="Remember the new retry loop and exception branch.",
            key_points=["Focus on the added for-loop."],
            watch_fors=["Do not overclaim reliability or backoff semantics."],
            claims=["The helper loops over attempts."],
            sources=["src/app.py:new:1-6"],
        ),
        LessonCompact(
            headline="Retry loop reminder",
            summary=["Loop over attempts, then continue on exception."],
            concepts=["retry loop"],
            sources=["src/app.py:new:1-6"],
        ),
    )


def test_generate_quiz_from_run_writes_expected_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_quiz")
    fake_provider = _FakeQuizProvider()

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeQuizProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.quiz.generator.make_provider", fake_provider_factory)

    artifacts, questions = generate_quiz_from_run(
        run_id="run_quiz",
        run_path=run_path,
        workspace_root=workspace_root,
        provider_config=ProviderConfig(
            provider_class="openai",
            model_name="gpt-5.4-mini",
            base_url="http://127.0.0.1:8318",
            api_key_env="AHADIFF_PROVIDER_API_KEY",
        ),
        api_key=None,
        security_config=SecurityConfig(),
        output_lang="zh-CN",
    )

    assert isinstance(artifacts, QuizArtifactPaths)
    assert artifacts.quiz_path.exists()
    loaded = load_quiz_questions(artifacts.quiz_path)
    assert len(loaded) == 3
    assert questions[0].question_id is not None
    assert loaded[0].source_claims == ["run_quiz-claim-1"]
    assert fake_provider.requests
    assert "Simplified Chinese (zh-CN)" in fake_provider.requests[0].payload_text


def test_quiz_payload_includes_requested_output_language(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_quiz_lang")
    metadata = json.loads((run_path / "metadata.json").read_text(encoding="utf-8"))

    payload = build_quiz_payload(
        prompt_text="Prompt contract",
        metadata=metadata,
        lesson_text="Lesson",
        claims_text=(run_path / "claims.jsonl").read_text(encoding="utf-8"),
        patch_text=(run_path / "patch.diff").read_text(encoding="utf-8"),
        line_map_text=(run_path / "line_map.json").read_text(encoding="utf-8"),
        symbols_text=(run_path / "symbols.json").read_text(encoding="utf-8"),
        output_lang="zh-CN",
    )

    assert "## Output language" in payload
    assert "Simplified Chinese (zh-CN)" in payload


def test_generate_cards_for_run_writes_review_cards(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_cards")
    questions = (
        QuizQuestion(
            question_id="quiz_1",
            question="What changed?",
            expected_answer="The helper now retries.",
            source_claims=["run_cards-claim-1"],
            concepts=["retry loop"],
            evidence=[QuizEvidence(file="src/app.py", line=2)],
        ),
    )

    cards_path = generate_cards_for_run(
        run_path=run_path,
        questions=questions,
        verdict="PASS",
    )

    assert cards_path is not None
    payload = cards_path.read_text(encoding="utf-8").strip()
    card = ReviewCard.model_validate_json(payload)
    assert card.concept == "retry loop"
    assert card.file_id == "file_app"
    assert card.hunk_id == "hunk_retry"
    assert card.symbol == "retry_once"


def test_generate_cards_for_run_skips_fail_verdict(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_fail_cards")
    questions = (
        QuizQuestion(
            question="What changed?",
            expected_answer="The helper now retries.",
            source_claims=["run_fail_cards-claim-1"],
            concepts=["retry loop"],
            evidence=[QuizEvidence(file="src/app.py", line=2)],
        ),
    )

    cards_path = generate_cards_for_run(
        run_path=run_path,
        questions=questions,
        verdict="FAIL",
    )

    assert cards_path is None
    assert not (run_path / "quiz" / "cards.jsonl").exists()


def test_quiz_cli_runs_questions_and_scores_answers(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = workspace_root / ".ahadiff" / "runs" / "run_cli_quiz"
    run_path.mkdir(parents=True)
    quiz_path = run_path / "quiz" / "quiz.jsonl"
    questions = (
        QuizQuestion(
            question_id="quiz_1",
            question="What changed?",
            expected_answer="The helper now retries.",
            source_claims=["claim_1"],
            concepts=["retry loop"],
            evidence=[QuizEvidence(file="src/app.py", line=2)],
        ),
    )
    write_quiz_questions_jsonl(quiz_path, questions)

    result = _RUNNER.invoke(
        app(),
        ["quiz", "run_cli_quiz", "--repo-root", str(workspace_root)],
        input="The helper now retries.\n",
    )

    assert result.exit_code == 0
    assert "Question 1" in result.stdout
    assert "Score" in result.stdout
    assert "1/1" in result.stdout


def test_learn_command_writes_quiz_cards_and_local_concepts_for_patch_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    patch_path = workspace_root / "sample.patch"
    patch_path.write_text(
        """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
-value = 1
+value = 2
+print(value)
""",
        encoding="utf-8",
    )

    def fake_runtime_provider(
        *args: object, **kwargs: object
    ) -> tuple[ProviderConfig, None, str, bool]:
        return (
            ProviderConfig(
                provider_class="openai",
                model_name="gpt-5.4-mini",
                base_url="http://127.0.0.1:8318",
                api_key_env="AHADIFF_PROVIDER_API_KEY",
            ),
            None,
            "local",
            True,
        )

    def fake_extract_claims(
        *args: object, **kwargs: object
    ) -> tuple[Path, tuple[ClaimCandidate, ...]]:
        output_path = cast("Path", kwargs["output_path"])
        run_id = cast("str", kwargs["run_id"])
        candidates = (
            ClaimCandidate(
                claim_id=f"{run_id}-claim-1",
                run_id=run_id,
                text="The module now prints the updated value.",
                source_hunks=[SourceHunk(file="src/app.py", start=1, end=2, side="new")],
                symbols=["print"],
            ),
        )
        return write_claim_candidates_jsonl(output_path, candidates), candidates

    def fake_lessons(*args: object, **kwargs: object) -> object:
        run_path = cast("Path", kwargs["run_path"])
        full, hint, compact = _sample_lessons()
        return write_lesson_artifacts(run_path=run_path, full=full, hint=hint, compact=compact)

    def fake_verify(*args: object, **kwargs: object) -> tuple[VerifiedClaim, ...]:
        run_id = cast("tuple[ClaimCandidate, ...]", args[0])[0].run_id
        return (
            VerifiedClaim(
                record=ClaimRecord(
                    claim_id=f"{run_id}-claim-1",
                    run_id=run_id,
                    text="The module now prints the updated value.",
                    status="verified",
                    confidence="high",
                    source_hunks=[SourceHunk(file="src/app.py", start=1, end=2, side="new")],
                    symbols=[],
                    negative_evidence=[],
                    extractor="section_header",
                )
            ),
        )

    def fake_quiz(
        *args: object, **kwargs: object
    ) -> tuple[QuizArtifactPaths, tuple[QuizQuestion, ...]]:
        run_path = cast("Path", kwargs["run_path"])
        questions = (
            QuizQuestion(
                question_id="quiz_1",
                question="What changed?",
                expected_answer="The module now prints the updated value.",
                source_claims=[f"{cast('str', kwargs['run_id'])}-claim-1"],
                concepts=["stdout update"],
                evidence=[QuizEvidence(file="src/app.py", line=2)],
            ),
        )
        quiz_path = run_path / "quiz" / "quiz.jsonl"
        write_quiz_questions_jsonl(quiz_path, questions)
        return QuizArtifactPaths(quiz_dir=quiz_path.parent, quiz_path=quiz_path), questions

    monkeypatch.setattr("ahadiff.cli._resolve_runtime_provider", fake_runtime_provider)
    monkeypatch.setattr("ahadiff.cli.extract_claim_candidates_from_run", fake_extract_claims)
    monkeypatch.setattr("ahadiff.cli.verify_claim_candidates", fake_verify)
    monkeypatch.setattr("ahadiff.cli.generate_lessons_from_run", fake_lessons)
    monkeypatch.setattr("ahadiff.cli.generate_quiz_from_run", fake_quiz)

    result = _RUNNER.invoke(
        app(),
        ["learn", "--patch", str(patch_path), "--repo-root", str(workspace_root), "--force-learn"],
    )

    assert result.exit_code == 0
    runs = sorted((workspace_root / ".ahadiff" / "runs").iterdir())
    assert len(runs) == 1
    run_path = runs[0]
    assert (run_path / "quiz" / "quiz.jsonl").exists()
    assert (run_path / "quiz" / "cards.jsonl").exists()
    assert (run_path / "concepts_local.jsonl").exists()
    assert "Quiz" in result.stdout
    assert "Cards" in result.stdout
    assert "Concepts" in result.stdout
