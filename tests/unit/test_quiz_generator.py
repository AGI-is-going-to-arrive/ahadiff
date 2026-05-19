from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING, cast

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from ahadiff.claims.extract import write_claim_candidates_jsonl
from ahadiff.claims.schema import ClaimCandidate, VerifiedClaim
from ahadiff.cli import app
from ahadiff.contracts import ClaimRecord, ProviderConfig, QuizChoice, ReviewCard, SourceHunk
from ahadiff.core.config import SecurityConfig
from ahadiff.core.errors import InputError
from ahadiff.lesson.generator import write_lesson_artifacts
from ahadiff.lesson.schemas import LessonCompact, LessonFull, LessonHint
from ahadiff.llm.schemas import ProviderResponse
from ahadiff.llm.structured import schema_spec_for
from ahadiff.quiz import generator as quiz_generator_module
from ahadiff.quiz.generator import (
    QuizArtifactPaths,
    build_quiz_payload,
    generate_cards_for_run,
    generate_quiz_from_run,
    load_quiz_questions,
    write_quiz_questions_jsonl,
)
from ahadiff.quiz.misconception import (
    has_explicit_empty_misconception_cards,
    load_misconception_cards,
)
from ahadiff.quiz.schemas import QuizEvidence, QuizQuestion, parse_quiz_payload

if TYPE_CHECKING:
    from pathlib import Path

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
    def __init__(self, *, include_choices: bool = True) -> None:
        self.include_choices = include_choices
        self.requests: list[ProviderRequest] = []

    @staticmethod
    def _choices_for(expected_answer: str) -> list[dict[str, object]]:
        return [
            {"label": "A", "text": expected_answer, "is_correct": True},
            {"label": "B", "text": "It removes the changed control flow.", "is_correct": False},
            {"label": "C", "text": "It only renames a local symbol.", "is_correct": False},
            {"label": "D", "text": "It proves exponential backoff.", "is_correct": False},
        ]

    def generate(self, request: object) -> object:
        from ahadiff.llm.schemas import ProviderResponse

        self.requests.append(cast("ProviderRequest", request))
        if cast("ProviderRequest", request).prompt_name == "quiz.misconception_card":
            content = json.dumps(
                [
                    {
                        "concept": "retry loop",
                        "misconception": "The diff proves exponential backoff.",
                        "correction": "The diff only proves repeated retry attempts.",
                        "evidence_ref": "src/app.py:2",
                        "severity": "medium",
                        "safety_tags": [],
                    }
                ]
            )
        else:
            questions: list[dict[str, object]] = [
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
                    "expected_answer": "The exception branch now continues to the next attempt.",
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
            if self.include_choices:
                for question in questions:
                    question["choices"] = self._choices_for(str(question["expected_answer"]))
            content = json.dumps({"questions": questions})
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


def _quiz_choice_payloads(
    *,
    correct_labels: tuple[str, ...] = ("A",),
    labels: tuple[str, ...] = ("A", "B", "C", "D"),
    texts: tuple[str, ...] = (
        "It now loops across attempts and continues after exceptions.",
        "It disables retry after the first exception.",
        "It only renames a local variable.",
        "It removes exception handling.",
    ),
) -> list[dict[str, object]]:
    return [
        {"label": label, "text": text, "is_correct": label in correct_labels}
        for label, text in zip(labels, texts, strict=False)
    ]


def _quiz_choice_models(
    *,
    correct_labels: tuple[str, ...] = ("A",),
    labels: tuple[str, ...] = ("A", "B", "C", "D"),
    texts: tuple[str, ...] = (
        "It now loops across attempts and continues after exceptions.",
        "It disables retry after the first exception.",
        "It only renames a local variable.",
        "It removes exception handling.",
    ),
) -> list[QuizChoice]:
    return [
        QuizChoice.model_validate(choice)
        for choice in _quiz_choice_payloads(
            correct_labels=correct_labels,
            labels=labels,
            texts=texts,
        )
    ]


def _quiz_question_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "question_id": "quiz_1",
        "question": "What structural change was added to retry_once?",
        "expected_answer": "It now loops across attempts and continues after exceptions.",
        "source_claims": ["claim_1"],
        "concepts": ["retry loop"],
        "evidence": [{"file": "src/app.py", "line": 2}],
    }
    payload.update(overrides)
    return payload


def test_load_quiz_questions_keeps_legacy_open_answer_rows(tmp_path: Path) -> None:
    quiz_path = tmp_path / "quiz.jsonl"
    quiz_path.write_text(
        json.dumps(_quiz_question_payload(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    loaded = load_quiz_questions(quiz_path)

    assert len(loaded) == 1
    assert loaded[0].question == "What structural change was added to retry_once?"
    assert loaded[0].expected_answer == (
        "It now loops across attempts and continues after exceptions."
    )
    assert loaded[0].answer_mode == "open"
    assert loaded[0].choices is None


def test_parse_quiz_payload_keeps_legacy_open_answer_rows_when_choices_not_required() -> None:
    parsed = parse_quiz_payload(json.dumps({"questions": [_quiz_question_payload()]}))

    assert len(parsed.questions) == 1
    assert parsed.questions[0].quiz_kind == "recall"
    assert parsed.questions[0].answer_mode == "open"
    assert parsed.questions[0].choices is None


def test_parse_quiz_payload_accepts_transfer_quiz_kind() -> None:
    parsed = parse_quiz_payload(
        json.dumps({"questions": [_quiz_question_payload(quiz_kind="transfer")]})
    )

    assert parsed.questions[0].quiz_kind == "transfer"


def test_quiz_question_rejects_unknown_quiz_kind() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion.model_validate(_quiz_question_payload(quiz_kind="memory"))


def test_parse_quiz_payload_require_choices_rejects_open_answer_rows() -> None:
    with pytest.raises((ValidationError, ValueError)):
        parse_quiz_payload(
            json.dumps({"questions": [_quiz_question_payload()]}),
            require_choices=True,
        )


def test_quiz_question_infers_multiple_choice_when_choices_are_present() -> None:
    question = QuizQuestion.model_validate(_quiz_question_payload(choices=_quiz_choice_payloads()))

    assert question.answer_mode == "multiple_choice"
    assert question.choices is not None
    assert [choice.label for choice in question.choices] == ["A", "B", "C", "D"]


def test_parse_quiz_payload_accepts_multiple_choice_rows_when_choices_are_required() -> None:
    parsed = parse_quiz_payload(
        json.dumps({"questions": [_quiz_question_payload(choices=_quiz_choice_payloads())]}),
        require_choices=True,
    )

    assert parsed.questions[0].answer_mode == "multiple_choice"
    assert parsed.questions[0].choices is not None


def test_parse_quiz_payload_accepts_unclosed_fenced_json_block() -> None:
    payload = "```json\n" + json.dumps(
        {"questions": [_quiz_question_payload(choices=_quiz_choice_payloads())]}
    )

    parsed = parse_quiz_payload(payload, require_choices=True)

    assert parsed.questions[0].question == "What structural change was added to retry_once?"


def test_parse_quiz_payload_recovers_truncated_questions_array() -> None:
    first_question = json.dumps(_quiz_question_payload(choices=_quiz_choice_payloads()))
    payload = f'{{"questions":[{first_question},{{"question":"This second question was truncated",'

    parsed = parse_quiz_payload(payload, require_choices=True)

    assert len(parsed.questions) == 1
    assert parsed.questions[0].question == "What structural change was added to retry_once?"


@pytest.mark.parametrize(
    "trailing_fragment",
    [
        ', {"question": "The second question mentions {retry} and then truncates',
        ', {"quest',
        ",",
    ],
)
def test_parse_quiz_payload_recovers_first_question_before_truncated_tail(
    trailing_fragment: str,
) -> None:
    first_question = json.dumps(_quiz_question_payload(choices=_quiz_choice_payloads()))
    payload = f'{{"questions":[{first_question}{trailing_fragment}'

    parsed = parse_quiz_payload(payload, require_choices=True)

    assert len(parsed.questions) == 1
    assert parsed.questions[0].choices is not None


def test_parse_quiz_payload_skips_empty_object_mixed_with_real_content() -> None:
    payload = "```json\n{}\n```\n\n" + json.dumps(
        {"questions": [_quiz_question_payload(choices=_quiz_choice_payloads())]}
    )

    parsed = parse_quiz_payload(payload, require_choices=True)

    assert parsed.questions[0].source_claims == ["claim_1"]


def test_parse_quiz_payload_unwraps_reasoning_model_output_key() -> None:
    payload = '<think>{"questions":[]}</think>\n' + json.dumps(
        {"output": {"questions": [_quiz_question_payload(choices=_quiz_choice_payloads())]}}
    )

    parsed = parse_quiz_payload(payload, require_choices=True)

    assert parsed.questions[0].expected_answer == (
        "It now loops across attempts and continues after exceptions."
    )


def test_parse_quiz_payload_unwraps_escaped_output_string() -> None:
    payload = json.dumps(
        {
            "output": json.dumps(
                {"questions": [_quiz_question_payload(choices=_quiz_choice_payloads())]}
            )
        }
    )

    parsed = parse_quiz_payload(payload, require_choices=True)

    assert parsed.questions[0].question == "What structural change was added to retry_once?"


def test_parse_quiz_payload_unwraps_openai_responses_envelope() -> None:
    payload = json.dumps(
        {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "questions": [
                                        _quiz_question_payload(choices=_quiz_choice_payloads())
                                    ]
                                }
                            ),
                        }
                    ]
                }
            ]
        }
    )

    parsed = parse_quiz_payload(payload, require_choices=True)

    assert parsed.questions[0].source_claims == ["claim_1"]


def test_parse_quiz_payload_prefers_final_valid_json_after_echoed_schema() -> None:
    echoed_schema = {
        "questions": [
            _quiz_question_payload(
                question="SCHEMA EXAMPLE SHOULD NOT WIN",
                choices=_quiz_choice_payloads(),
            )
        ]
    }
    final_answer = {"questions": [_quiz_question_payload(choices=_quiz_choice_payloads())]}
    payload = (
        "The schema shape is:\n"
        "```json\n"
        f"{json.dumps(echoed_schema)}\n"
        "```\n\n"
        "The final JSON is:\n"
        "```json\n"
        f"{json.dumps(final_answer)}\n"
        "```"
    )

    parsed = parse_quiz_payload(payload, require_choices=True)

    assert parsed.questions[0].question == "What structural change was added to retry_once?"


def test_parse_quiz_payload_accepts_valid_array_root() -> None:
    parsed = parse_quiz_payload(
        json.dumps([_quiz_question_payload(choices=_quiz_choice_payloads())]),
        require_choices=True,
    )

    assert parsed.questions[0].question == "What structural change was added to retry_once?"


def test_parse_quiz_payload_rejects_missing_required_fields() -> None:
    with pytest.raises(ValueError):
        parse_quiz_payload(json.dumps({"questions": [{"question": "Missing fields."}]}))


def test_parse_quiz_payload_rejects_bad_evidence_line() -> None:
    with pytest.raises(ValidationError):
        parse_quiz_payload(
            json.dumps(
                {
                    "questions": [
                        _quiz_question_payload(
                            choices=_quiz_choice_payloads(),
                            evidence=[{"file": "src/app.py", "line": 0}],
                        )
                    ]
                }
            ),
            require_choices=True,
        )


@pytest.mark.parametrize(
    "choices",
    [
        _quiz_choice_payloads(texts=("correct", "wrong", "wrong")),
        _quiz_choice_payloads(
            labels=("A", "B", "C", "D", "A"),
            texts=("correct", "wrong 1", "wrong 2", "wrong 3", "wrong 4"),
        ),
    ],
)
def test_quiz_question_rejects_wrong_choice_count(
    choices: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError):
        QuizQuestion.model_validate(_quiz_question_payload(choices=choices))


@pytest.mark.parametrize(
    "choices",
    [
        _quiz_choice_payloads(correct_labels=()),
        _quiz_choice_payloads(correct_labels=("A", "B")),
    ],
)
def test_quiz_question_rejects_zero_or_multiple_correct_choices(
    choices: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError):
        QuizQuestion.model_validate(_quiz_question_payload(choices=choices))


@pytest.mark.parametrize(
    "choices",
    [
        _quiz_choice_payloads(labels=("A", "B", "D", "C")),
        _quiz_choice_payloads(labels=("A", "B", "B", "D")),
        [
            {"label": "A", "text": "correct", "is_correct": True},
            {"label": "B", "text": "wrong 1", "is_correct": False},
            {"label": "C", "text": "wrong 2", "is_correct": False},
            {"text": "wrong 3", "is_correct": False},
        ],
    ],
)
def test_quiz_question_rejects_missing_duplicate_or_unordered_choice_labels(
    choices: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError):
        QuizQuestion.model_validate(_quiz_question_payload(choices=choices))


def test_quiz_question_rejects_duplicate_choice_text_casefolded() -> None:
    choices = _quiz_choice_payloads(
        texts=(
            "It now loops across attempts and continues after exceptions.",
            " it now loops across attempts and continues after exceptions. ",
            "It only renames a local variable.",
            "It removes exception handling.",
        )
    )

    with pytest.raises(ValidationError):
        QuizQuestion.model_validate(_quiz_question_payload(choices=choices))


def test_quiz_question_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion.model_validate(_quiz_question_payload(unexpected="blocked"))


def test_generate_quiz_from_run_writes_expected_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_quiz")
    fake_provider = _FakeQuizProvider()
    progress_messages: list[str] = []

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
        on_sub_progress=progress_messages.append,
    )

    assert isinstance(artifacts, QuizArtifactPaths)
    assert artifacts.quiz_path.exists()
    assert artifacts.misconception_path is not None
    assert artifacts.misconception_path.exists()
    loaded = load_quiz_questions(artifacts.quiz_path)
    misconceptions = load_misconception_cards(artifacts.misconception_path)
    assert len(loaded) == 3
    assert len(misconceptions) == 1
    assert misconceptions[0].run_id == "run_quiz"
    assert questions[0].question_id is not None
    assert loaded[0].answer_mode == "multiple_choice"
    assert loaded[0].choices is not None
    assert [choice.label for choice in loaded[0].choices] == ["A", "B", "C", "D"]
    assert loaded[0].source_claims == ["run_quiz-claim-1"]
    assert fake_provider.requests
    assert [request.prompt_name for request in fake_provider.requests] == [
        "quiz.generate",
        "quiz.misconception_card",
    ]
    assert [request.max_output_tokens for request in fake_provider.requests] == [6000, 3000]
    assert "Write 3 questions" in fake_provider.requests[0].payload_text
    assert progress_messages == [
        "Generating quiz questions (1/2)",
        "Generating misconception cards (2/2)",
    ]
    assert "Simplified Chinese (zh-CN)" in fake_provider.requests[0].payload_text


def test_quiz_generation_attaches_structured_schema_metadata_for_both_prompts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_quiz_schema")
    fake_provider = _FakeQuizProvider()

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeQuizProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.quiz.generator.make_provider", fake_provider_factory)

    generate_quiz_from_run(
        run_id="run_quiz_schema",
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
        structured_output_mode="native_json_schema",
        structured_validation_retries=1,
    )

    expected = [
        ("quiz.generate", "quiz_generate.v1", 6000),
        ("quiz.misconception_card", "quiz_misconception_card.v1", 3000),
    ]
    assert len(fake_provider.requests) == 2
    for request, (prompt_name, schema_name, max_tokens) in zip(
        fake_provider.requests,
        expected,
        strict=True,
    ):
        spec = schema_spec_for(schema_name)
        assert request.prompt_name == prompt_name
        assert request.max_output_tokens == max_tokens
        assert request.response_format == "json_schema"
        assert request.enforcement_mode == "native_json_schema"
        assert request.output_schema_id == spec.schema_id
        assert request.output_schema_version == spec.schema_version
        assert request.output_schema_hash == spec.schema_hash
        assert request.output_schema is not None


def test_quiz_generation_retries_then_preserves_quiz_jsonl_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_quiz_retry")
    fake_provider = _FakeQuizProvider()
    quiz_attempts = 0

    def fake_generate(request: object) -> object:
        nonlocal quiz_attempts
        req = cast("ProviderRequest", request)
        fake_provider.requests.append(req)
        if req.prompt_name == "quiz.generate":
            quiz_attempts += 1
            question = _quiz_question_payload(source_claims=["run_quiz_retry-claim-1"])
            if quiz_attempts == 1:
                return ProviderResponse(
                    content=json.dumps({"questions": [question]}),
                    model_id="gpt-5.4-mini",
                    input_tokens=10,
                    output_tokens=20,
                )
            question["choices"] = _quiz_choice_payloads()
            return ProviderResponse(
                content=json.dumps({"questions": [question]}),
                model_id="gpt-5.4-mini",
                input_tokens=10,
                output_tokens=20,
            )
        return _FakeQuizProvider.generate(fake_provider, req)

    fake_provider.generate = fake_generate  # type: ignore[method-assign]

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeQuizProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.quiz.generator.make_provider", fake_provider_factory)

    artifacts, questions = generate_quiz_from_run(
        run_id="run_quiz_retry",
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
        structured_output_mode="native_json_schema",
        structured_validation_retries=1,
    )

    quiz_requests = [
        request for request in fake_provider.requests if request.prompt_name == "quiz.generate"
    ]
    assert len(quiz_requests) == 2
    retry_feedback = quiz_requests[1].payload_text.split("The previous response", 1)[1]
    assert "quiz_generate.v1" in retry_feedback
    assert "diff --git" not in retry_feedback
    assert '"properties"' not in retry_feedback
    assert len(questions) == 1
    assert len(artifacts.quiz_path.read_text(encoding="utf-8").splitlines()) == 1


def test_misconception_generation_retries_invalid_nonempty_payload_then_preserves_jsonl_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_quiz_misconception_retry")
    fake_provider = _FakeQuizProvider()
    misconception_attempts = 0

    def fake_generate(request: object) -> object:
        nonlocal misconception_attempts
        req = cast("ProviderRequest", request)
        if req.prompt_name != "quiz.misconception_card":
            return _FakeQuizProvider.generate(fake_provider, req)
        fake_provider.requests.append(req)
        misconception_attempts += 1
        if misconception_attempts == 1:
            content = json.dumps({"cards": [{"concept": "retry loop"}]})
        else:
            content = json.dumps(
                {
                    "cards": [
                        {
                            "concept": "retry loop",
                            "misconception": "The diff proves exponential backoff.",
                            "correction": "The diff only proves repeated retry attempts.",
                            "evidence_ref": "src/app.py:2",
                            "severity": "medium",
                            "safety_tags": [],
                        }
                    ]
                }
            )
        return ProviderResponse(
            content=content,
            model_id="gpt-5.4-mini",
            input_tokens=10,
            output_tokens=20,
        )

    fake_provider.generate = fake_generate  # type: ignore[method-assign]

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeQuizProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.quiz.generator.make_provider", fake_provider_factory)

    artifacts, _questions = generate_quiz_from_run(
        run_id="run_quiz_misconception_retry",
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
        structured_output_mode="native_json_schema",
        structured_validation_retries=1,
    )

    misconception_requests = [
        request
        for request in fake_provider.requests
        if request.prompt_name == "quiz.misconception_card"
    ]
    assert len(misconception_requests) == 2
    retry_feedback = misconception_requests[1].payload_text.split("The previous response", 1)[1]
    assert "quiz_misconception_card.v1" in retry_feedback
    assert artifacts.misconception_path is not None
    cards = load_misconception_cards(artifacts.misconception_path)
    assert len(cards) == 1
    assert cards[0].run_id == "run_quiz_misconception_retry"


def test_generate_quiz_from_run_allows_empty_misconception_cards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_quiz_empty_misconceptions")
    fake_provider = _FakeQuizProvider()

    def fake_generate(request: object) -> object:
        req = cast("ProviderRequest", request)
        if req.prompt_name != "quiz.misconception_card":
            return _FakeQuizProvider.generate(fake_provider, req)
        fake_provider.requests.append(req)
        return ProviderResponse(
            content=json.dumps({"cards": []}),
            model_id="gpt-5.4-mini",
            input_tokens=10,
            output_tokens=20,
        )

    fake_provider.generate = fake_generate  # type: ignore[method-assign]

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeQuizProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.quiz.generator.make_provider", fake_provider_factory)

    artifacts, _questions = generate_quiz_from_run(
        run_id="run_quiz_empty_misconceptions",
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
        structured_output_mode="native_json_schema",
        structured_validation_retries=0,
    )

    misconception_requests = [
        request
        for request in fake_provider.requests
        if request.prompt_name == "quiz.misconception_card"
    ]
    assert len(misconception_requests) == 1
    assert artifacts.misconception_path is not None
    assert artifacts.misconception_path.read_text(encoding="utf-8") == ""
    assert load_misconception_cards(artifacts.misconception_path) == []


def test_misconception_empty_container_does_not_mask_invalid_nonempty_cards() -> None:
    assert has_explicit_empty_misconception_cards('{"cards": []}') is True
    assert has_explicit_empty_misconception_cards('{"cards": [{"concept": "retry"}]}') is False


def test_generate_quiz_from_run_uses_configured_question_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_quiz")
    fake_provider = _FakeQuizProvider()

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeQuizProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.quiz.generator.make_provider", fake_provider_factory)

    generate_quiz_from_run(
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
        question_count=5,
    )

    assert "Write 5 questions" in fake_provider.requests[0].payload_text
    assert "{question_count}" not in fake_provider.requests[0].payload_text


@pytest.mark.parametrize(
    ("provider_max_output_tokens", "expected_max_tokens"),
    [
        (None, [2000, 1200]),
        (1000, [1000, 1000]),
        (0, [2000, 1200]),
    ],
)
def test_generate_quiz_from_run_clamps_output_token_caps_with_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_max_output_tokens: int | None,
    expected_max_tokens: list[int],
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_quiz")
    fake_provider = _FakeQuizProvider()

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeQuizProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.quiz.generator.make_provider", fake_provider_factory)

    generate_quiz_from_run(
        run_id="run_quiz",
        run_path=run_path,
        workspace_root=workspace_root,
        provider_config=ProviderConfig(
            provider_class="openai",
            model_name="gpt-5.4-mini",
            base_url="http://127.0.0.1:8318",
            api_key_env="AHADIFF_PROVIDER_API_KEY",
            max_output_tokens=provider_max_output_tokens,
        ),
        api_key=None,
        security_config=SecurityConfig(),
        output_token_budget=2000,
        quiz_output_token_cap=2500,
        misconception_output_token_cap=1200,
    )

    assert [request.max_output_tokens for request in fake_provider.requests] == expected_max_tokens


def test_generate_quiz_from_run_ignores_non_positive_output_token_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_quiz_non_positive_caps")
    fake_provider = _FakeQuizProvider()

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeQuizProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.quiz.generator.make_provider", fake_provider_factory)

    generate_quiz_from_run(
        run_id="run_quiz_non_positive_caps",
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
        output_token_budget=-1,
        quiz_output_token_cap=0,
        misconception_output_token_cap=-1,
    )

    assert [request.max_output_tokens for request in fake_provider.requests] == [6000, 3000]


def test_generate_quiz_from_run_rejects_provider_payload_without_choices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_quiz_run_artifacts(workspace_root, "run_quiz")
    fake_provider = _FakeQuizProvider(include_choices=False)

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeQuizProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.quiz.generator.make_provider", fake_provider_factory)

    with pytest.raises(InputError, match="provider output omitted"):
        generate_quiz_from_run(
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
        )
    assert not (run_path / "quiz" / "quiz.jsonl").exists()


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
    loaded = load_quiz_questions(run_path / "quiz" / "quiz.jsonl")
    assert loaded[0].review_card_id == card.card_id


def test_generate_cards_for_run_writes_question_and_answer_to_review_cards(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_cards_question_answer"
    run_path = _write_quiz_run_artifacts(workspace_root, run_id)
    question_text = "What changed in retry_once?"
    expected_answer = "The helper now retries across attempts."
    questions = (
        QuizQuestion(
            question_id="quiz_question_answer",
            question=question_text,
            expected_answer=expected_answer,
            source_claims=[f"{run_id}-claim-1"],
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
    card = ReviewCard.model_validate_json(cards_path.read_text(encoding="utf-8").strip())
    assert card.question == question_text
    assert card.answer == expected_answer
    loaded = load_quiz_questions(run_path / "quiz" / "quiz.jsonl")
    assert loaded[0].question == question_text
    assert loaded[0].expected_answer == expected_answer
    assert loaded[0].review_card_id == card.card_id


@pytest.mark.parametrize(
    ("claim_symbols", "expected_concept"),
    [
        (["retry_once"], "retry_once"),
        ([], "What changed without an explicit concept?"),
    ],
)
def test_generate_cards_for_run_writes_review_card_id_for_concept_fallback(
    tmp_path: Path,
    claim_symbols: list[str],
    expected_concept: str,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_card_fallback_symbol" if claim_symbols else "run_card_fallback_question"
    run_path = _write_quiz_run_artifacts(workspace_root, run_id)
    claim = ClaimRecord(
        claim_id=f"{run_id}-claim-1",
        run_id=run_id,
        text="The retry helper now loops across attempts.",
        status="verified",
        confidence="high",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
        symbols=claim_symbols,
        negative_evidence=[],
        extractor="python_ast",
    )
    (run_path / "claims.jsonl").write_text(
        json.dumps(claim.model_dump(mode="json"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    question_text = "What changed without an explicit concept?"
    questions = (
        QuizQuestion(
            question_id="quiz_fallback",
            question=question_text,
            expected_answer="The helper now retries.",
            source_claims=[claim.claim_id],
            concepts=[],
            evidence=[QuizEvidence(file="src/app.py", line=2)],
        ),
    )

    cards_path = generate_cards_for_run(
        run_path=run_path,
        questions=questions,
        verdict="PASS",
    )

    assert cards_path is not None
    card = ReviewCard.model_validate_json(cards_path.read_text(encoding="utf-8").strip())
    loaded = load_quiz_questions(run_path / "quiz" / "quiz.jsonl")
    expected_digest = hashlib.sha256(
        f"{run_id}::quiz_fallback::{expected_concept}".encode()
    ).hexdigest()[:12]
    expected_card_id = f"card_{expected_digest}"
    assert card.concept == expected_concept
    assert card.card_id == expected_card_id
    assert loaded[0].concepts == []
    assert loaded[0].review_card_id == card.card_id


def test_load_quiz_questions_rejects_oversized_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quiz_path = tmp_path / "quiz.jsonl"
    quiz_path.write_text(
        json.dumps(
            {
                "question_id": "quiz_1",
                "question": "What changed?",
                "expected_answer": "Retries were added.",
                "source_claims": ["claim-1"],
                "concepts": ["retry loop"],
                "evidence": [{"file": "src/app.py", "line": 1}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(quiz_generator_module, "_MAX_RUN_ARTIFACT_TEXT_BYTES", 8)

    with pytest.raises(InputError, match="artifact exceeds size limit"):
        load_quiz_questions(quiz_path)


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


def test_quiz_cli_displays_multiple_choice_labels_and_scores_label_answer(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = workspace_root / ".ahadiff" / "runs" / "run_cli_choice_quiz"
    run_path.mkdir(parents=True)
    quiz_path = run_path / "quiz" / "quiz.jsonl"
    questions = (
        QuizQuestion(
            question_id="quiz_1",
            question="What structural change was added to retry_once?",
            expected_answer="It now loops across attempts and continues after exceptions.",
            source_claims=["claim_1"],
            concepts=["retry loop"],
            evidence=[QuizEvidence(file="src/app.py", line=2)],
            choices=_quiz_choice_models(),
        ),
    )
    write_quiz_questions_jsonl(quiz_path, questions)

    result = _RUNNER.invoke(
        app(),
        ["quiz", "run_cli_choice_quiz", "--repo-root", str(workspace_root)],
        input="A\n",
    )

    assert result.exit_code == 0
    assert "Question 1" in result.stdout
    assert "It now loops across attempts and continues after exceptions." in result.stdout
    assert "It disables retry after the first exception." in result.stdout
    assert "It only renames a local variable." in result.stdout
    assert "It removes exception handling." in result.stdout
    assert "Correct" in result.stdout
    assert "Expected" not in result.stdout
    assert "1/1" in result.stdout


def test_learn_command_writes_quiz_cards_and_local_concepts_for_patch_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / ".ahadiff").mkdir()
    (workspace_root / ".ahadiff" / "config.toml").write_text(
        "[quiz]\nquiz_question_count = 5\n",
        encoding="utf-8",
    )
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
        assert kwargs["question_count"] == 5
        run_path = cast("Path", kwargs["run_path"])
        questions = (
            QuizQuestion(
                question_id="quiz_1",
                question="What changed?",
                expected_answer="The module now prints the updated value.",
                source_claims=[f"{cast('str', kwargs['run_id'])}-claim-1"],
                concepts=["stdout update"],
                evidence=[QuizEvidence(file="src/app.py", line=2)],
                choices=_quiz_choice_models(
                    texts=(
                        "The module now prints the updated value.",
                        "The module now suppresses all stdout.",
                        "The module only changes whitespace.",
                        "The module deletes the value assignment.",
                    )
                ),
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
    review_db_path = workspace_root / ".ahadiff" / "review.sqlite"
    with sqlite3.connect(review_db_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM cards").fetchone()
    assert row == (1,)
    assert "Quiz" in result.stdout
    assert "Cards" in result.stdout
    assert "Concepts" in result.stdout


def test_learn_command_persists_low_learnability_skipped_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    patch_path = workspace_root / "tiny.patch"
    patch_path.write_text(
        """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-value = 1
+value = 2
""",
        encoding="utf-8",
    )

    class _LowLearnability:
        score = 0.1
        threshold = 0.3
        skip_lesson_quiz = True
        forced = False

        def as_metadata(self) -> dict[str, object]:
            return {
                "score": self.score,
                "threshold": self.threshold,
                "skip_lesson_quiz": self.skip_lesson_quiz,
                "forced": self.forced,
                "reasons": ["low_learning_value"],
            }

    def _low_learnability(*args: object, **kwargs: object) -> _LowLearnability:
        del args, kwargs
        return _LowLearnability()

    monkeypatch.setattr("ahadiff.cli.assess_learnability", _low_learnability)

    result = _RUNNER.invoke(
        app(),
        ["learn", "--patch", str(patch_path), "--repo-root", str(workspace_root)],
    )

    assert result.exit_code == 0
    runs = sorted((workspace_root / ".ahadiff" / "runs").iterdir())
    assert len(runs) == 1
    run_path = runs[0]
    assert (run_path / "score.json").exists()
    assert (run_path / "finalized.json").exists()
    review_db_path = workspace_root / ".ahadiff" / "review.sqlite"
    with sqlite3.connect(review_db_path) as connection:
        row = connection.execute(
            "SELECT status, weakest_dim FROM result_events WHERE run_id = ?",
            (run_path.name,),
        ).fetchone()
    assert row == ("non_ratcheted", "learnability")
    assert "skipped by learnability gate" in result.stdout
