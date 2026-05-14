from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from ahadiff import cli as cli_module
from ahadiff.claims.extract import write_claim_candidates_jsonl
from ahadiff.claims.schema import ClaimCandidate, VerifiedClaim
from ahadiff.cli import app
from ahadiff.contracts import ClaimRecord, ProviderConfig, SourceHunk
from ahadiff.core.config import SecurityConfig
from ahadiff.core.errors import InputError
from ahadiff.eval.results import load_result_events, review_db_path_for_run
from ahadiff.git.line_map import build_line_map, serialize_line_map_payload
from ahadiff.git.parser import parse_unified_diff
from ahadiff.git.symbols import extract_symbols, serialize_symbols_payload
from ahadiff.lesson.generator import (
    LessonArtifactPaths,
    build_lesson_payload,
    generate_lessons_from_run,
    load_lesson_prompt,
    load_redacted_run_bundle,
    write_lesson_artifacts,
)
from ahadiff.lesson.scaffolding import compute_scaffolding_level
from ahadiff.lesson.schemas import LessonCompact, LessonFull, LessonHint, parse_lesson_payload
from ahadiff.llm.schemas import ProviderRequest, ProviderResponse
from ahadiff.quiz.generator import QuizArtifactPaths, write_quiz_questions_jsonl
from ahadiff.quiz.schemas import QuizEvidence, QuizQuestion

_RUNNER = CliRunner()


def _write_lesson_run_artifacts(
    workspace_root: Path,
    run_id: str,
    *,
    metadata_overrides: dict[str, object] | None = None,
) -> Path:
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
    before_text = "def retry_once():\n    return 1\n"
    after_text = (
        "def retry_once():\n"
        "    for attempt in range(3):\n"
        "        try:\n"
        "            return attempt\n"
        "        except Exception:\n"
        "            continue\n"
    )
    changed_files = parse_unified_diff(patch)
    line_maps = build_line_map(changed_files)
    symbols = extract_symbols(
        changed_files,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )
    metadata: dict[str, object] = {
        "run_id": run_id,
        "source_kind": "git_ref",
        "source_ref": "abc1234",
        "capability_level": 3,
        "degraded_flags": {},
        "privacy_mode": "strict_local",
        "learnability": {"score": 0.8},
    }
    if metadata_overrides:
        metadata.update(metadata_overrides)
    (run_path / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text(patch, encoding="utf-8")
    (run_path / "line_map.json").write_text(
        json.dumps(serialize_line_map_payload(line_maps), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "symbols.json").write_text(
        json.dumps(serialize_symbols_payload(symbols), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "claims.jsonl").write_text(
        json.dumps(
            {
                "claim_id": f"{run_id}-claim-1",
                "run_id": run_id,
                "text": "The retry helper now loops over attempts.",
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
    return run_path


class _FakeLessonProvider:
    def __init__(self) -> None:
        self.prompt_names: list[str] = []
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        prompt_name = request.prompt_name
        self.prompt_names.append(prompt_name)
        self.requests.append(request)
        if prompt_name == "lesson.generate":
            content = json.dumps(
                {
                    "tl_dr": "The retry helper now loops and handles transient failures.",
                    "what_changed": ["retry_once now iterates across attempts."],
                    "why": ["The diff adds a retry-oriented control-flow path."],
                    "walkthrough": ["Read the new for-loop and exception handling path first."],
                    "claims": ["The helper now loops over attempts."],
                    "concepts": ["Retries re-run an operation after a failure."],
                    "misconceptions": ["This does not prove exponential backoff was added."],
                    "not_proven": ["The diff does not prove runtime reliability improved."],
                    "quiz": ["Why is the exception branch part of the teaching surface?"],
                    "sources": ["src/app.py:new:1-6"],
                }
            )
        elif prompt_name == "lesson.hint":
            content = json.dumps(
                {
                    "tl_dr": "Remember the new retry loop and exception branch.",
                    "key_points": ["Focus on the added for-loop."],
                    "watch_fors": ["Do not overclaim reliability or backoff semantics."],
                    "claims": ["The helper loops over attempts."],
                    "sources": ["src/app.py:new:1-6"],
                }
            )
        else:
            content = json.dumps(
                {
                    "headline": "Retry loop reminder",
                    "summary": ["Loop over attempts, then continue on exception."],
                    "concepts": ["retry loop"],
                    "sources": ["src/app.py:new:1-6"],
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


def _extract_prompt_contract(prompt_text: str) -> dict[str, object]:
    marker = "```json"
    start = prompt_text.index(marker) + len(marker)
    end = prompt_text.index("```", start)
    return cast("dict[str, object]", json.loads(prompt_text[start:end]))


def test_compute_scaffolding_level_uses_fsrs_state_boundaries() -> None:
    assert compute_scaffolding_level(fsrs_state=None) == "full"
    assert (
        compute_scaffolding_level(
            fsrs_state=json.dumps({"state_name": "Learning", "stability_days": 1.0}),
            recent_successes=0,
        )
        == "full"
    )
    assert (
        compute_scaffolding_level(
            fsrs_state=json.dumps({"state_name": "Review", "stability_days": 7.0}),
            recent_successes=1,
        )
        == "hint"
    )
    assert (
        compute_scaffolding_level(
            fsrs_state=json.dumps({"state_name": "Review", "stability_days": 21.0}),
            recent_successes=2,
        )
        == "compact"
    )


def test_generate_lessons_from_run_writes_expected_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_lesson_run_artifacts(workspace_root, "run_lesson")
    fake_provider = _FakeLessonProvider()
    progress_messages: list[str] = []

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeLessonProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.lesson.generator.make_provider", fake_provider_factory)

    paths = generate_lessons_from_run(
        run_id="run_lesson",
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

    assert isinstance(paths, LessonArtifactPaths)
    assert paths.full_path.exists()
    assert paths.hint_path.exists()
    assert paths.compact_path.exists()
    assert paths.misconception_path.exists()
    assert paths.not_proven_path.exists()
    assert "## TL;DR" in paths.full_path.read_text(encoding="utf-8")
    assert "## Misconceptions" in paths.misconception_path.read_text(encoding="utf-8")
    assert "## Not Proven" in paths.not_proven_path.read_text(encoding="utf-8")
    assert fake_provider.prompt_names == [
        "lesson.generate",
        "lesson.hint",
        "lesson.compact",
    ]
    assert fake_provider.requests
    assert [item.max_output_tokens for item in fake_provider.requests] == [24000, 3000, 2500]
    assert all("Simplified Chinese (zh-CN)" in item.payload_text for item in fake_provider.requests)
    assert progress_messages == [
        "Generating full lesson (1/3)",
        "Generating hint lesson (2/3)",
        "Generating compact lesson (3/3)",
    ]
    bundle = load_redacted_run_bundle(
        run_id="run_lesson",
        run_path=run_path,
        workspace_root=workspace_root,
    )
    assert bundle.claims_text


def test_generate_lessons_from_run_fills_missing_full_quiz_and_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_lesson_run_artifacts(workspace_root, "run_lesson_fallback")
    fake_provider = _FakeLessonProvider()

    def fake_generate(request: ProviderRequest) -> ProviderResponse:
        if request.prompt_name != "lesson.generate":
            return _FakeLessonProvider.generate(fake_provider, request)
        fake_provider.prompt_names.append(request.prompt_name)
        fake_provider.requests.append(request)
        return ProviderResponse(
            content=json.dumps(
                {
                    "tl_dr": "The retry helper now loops and handles transient failures.",
                    "what_changed": ["retry_once now iterates across attempts."],
                    "why": ["The diff adds a retry-oriented control-flow path."],
                    "walkthrough": ["Read the new for-loop first."],
                    "claims": ["The helper now loops over attempts."],
                    "concepts": ["Retries re-run an operation after a failure."],
                    "misconceptions": [],
                    "not_proven": ["The diff does not prove runtime reliability improved."],
                }
            ),
            model_id="gpt-5.4-mini",
            input_tokens=10,
            output_tokens=20,
        )

    fake_provider.generate = fake_generate  # type: ignore[method-assign]

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeLessonProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.lesson.generator.make_provider", fake_provider_factory)

    paths = generate_lessons_from_run(
        run_id="run_lesson_fallback",
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

    full_text = paths.full_path.read_text(encoding="utf-8")
    assert "What source evidence supports this claim" in full_text
    assert "src/app.py:new:1-6" in full_text


def test_generate_lessons_from_run_repairs_section_shaped_full_lesson(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_lesson_run_artifacts(workspace_root, "run_lesson_sections")
    fake_provider = _FakeLessonProvider()

    def fake_generate(request: ProviderRequest) -> ProviderResponse:
        if request.prompt_name != "lesson.generate":
            return _FakeLessonProvider.generate(fake_provider, request)
        fake_provider.prompt_names.append(request.prompt_name)
        fake_provider.requests.append(request)
        return ProviderResponse(
            content=json.dumps(
                {
                    "tl_dr": "The retry helper now loops and handles transient failures.",
                    "sections": [
                        {"title": "What Changed", "bullets": ["retry_once now loops."]},
                        {"title": "Why", "bullets": ["The diff changes control flow."]},
                        {"title": "Walkthrough", "bullets": ["Follow the new loop."]},
                        {"title": "Claims", "bullets": ["The helper loops over attempts."]},
                        {"title": "Concepts", "bullets": ["retry_once"]},
                    ],
                    "sources": ["src/app.py:new:1-6"],
                }
            ),
            model_id="gpt-5.5",
            input_tokens=10,
            output_tokens=20,
        )

    fake_provider.generate = fake_generate  # type: ignore[method-assign]

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeLessonProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.lesson.generator.make_provider", fake_provider_factory)

    paths = generate_lessons_from_run(
        run_id="run_lesson_sections",
        run_path=run_path,
        workspace_root=workspace_root,
        provider_config=ProviderConfig(
            provider_class="openai",
            model_name="gpt-5.5",
            base_url="http://127.0.0.1:8318",
            api_key_env="AHADIFF_PROVIDER_API_KEY",
        ),
        api_key=None,
        security_config=SecurityConfig(),
    )

    full_text = paths.full_path.read_text(encoding="utf-8")
    assert "retry_once now loops." in full_text
    assert "What source evidence supports this claim: The helper loops over attempts." in full_text


def test_generate_lessons_from_run_allows_output_token_cap_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_lesson_run_artifacts(workspace_root, "run_lesson_caps")
    fake_provider = _FakeLessonProvider()

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeLessonProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.lesson.generator.make_provider", fake_provider_factory)

    generate_lessons_from_run(
        run_id="run_lesson_caps",
        run_path=run_path,
        workspace_root=workspace_root,
        provider_config=ProviderConfig(
            provider_class="openai",
            model_name="gpt-5.4-mini",
            base_url="http://127.0.0.1:8318",
            api_key_env="AHADIFF_PROVIDER_API_KEY",
            max_output_tokens=2000,
        ),
        api_key=None,
        security_config=SecurityConfig(),
        output_token_budget=5000,
        lesson_output_token_caps={"full": 5000, "hint": 1700, "compact": 1600},
    )

    assert [item.max_output_tokens for item in fake_provider.requests] == [2000, 1700, 1600]


def test_generate_lessons_from_run_ignores_non_positive_output_token_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_lesson_run_artifacts(workspace_root, "run_lesson_non_positive_caps")
    fake_provider = _FakeLessonProvider()

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeLessonProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.lesson.generator.make_provider", fake_provider_factory)

    generate_lessons_from_run(
        run_id="run_lesson_non_positive_caps",
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
        lesson_output_token_caps={"full": 0, "hint": -1, "compact": 0},
    )

    assert [item.max_output_tokens for item in fake_provider.requests] == [24000, 3000, 2500]


def test_hint_and_compact_prompts_match_schema_contracts() -> None:
    project_root = Path(__file__).resolve().parents[2]
    prompt_specs = [
        (
            "lesson_hint.md",
            LessonHint,
            ["`Not Proven`", "`Misconceptions`", "`Quiz`", "`Walkthrough`"],
        ),
        (
            "lesson_compact.md",
            LessonCompact,
            ["`Not Proven`", "`Misconceptions`", "`Quiz`", "safety sections"],
        ),
    ]

    for filename, schema, forbidden_tokens in prompt_specs:
        root_prompt = (project_root / "prompts" / filename).read_text(encoding="utf-8")
        package_prompt = (project_root / "src" / "ahadiff" / "prompts" / filename).read_text(
            encoding="utf-8"
        )
        assert root_prompt == package_prompt
        assert set(_extract_prompt_contract(root_prompt)) == set(schema.model_fields)
        for token in forbidden_tokens:
            assert token not in root_prompt


def test_lesson_payload_includes_requested_output_language(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_lesson_run_artifacts(workspace_root, "run_lang")
    bundle = load_redacted_run_bundle(
        run_id="run_lang",
        run_path=run_path,
        workspace_root=workspace_root,
    )

    payload = build_lesson_payload(
        prompt_text="Prompt contract",
        bundle=bundle,
        variant="full",
        output_lang="zh-CN",
    )

    assert "## Output language" in payload
    assert "Simplified Chinese (zh-CN)" in payload


def test_full_lesson_prompt_is_identical_in_root_and_package() -> None:
    project_root = Path(__file__).resolve().parents[2]
    root_prompt = (project_root / "prompts" / "lesson_generate.md").read_text(encoding="utf-8")
    package_prompt = (
        project_root / "src" / "ahadiff" / "prompts" / "lesson_generate.md"
    ).read_text(encoding="utf-8")

    assert root_prompt == package_prompt


def test_parse_lesson_payload_accepts_preface_and_fenced_json() -> None:
    payload = (
        "Here is the hint lesson.\n\n"
        "```json\n"
        "{\n"
        '  "tl_dr": "Remember the new retry loop and exception branch.",\n'
        '  "key_points": ["Focus on the added for-loop."],\n'
        '  "watch_fors": ["Do not overclaim reliability or backoff semantics."],\n'
        '  "claims": ["The helper loops over attempts."],\n'
        '  "sources": ["src/app.py:new:1-6"]\n'
        "}\n"
        "```\n\n"
        "Use the package only."
    )

    parsed = cast("LessonHint", parse_lesson_payload(payload, schema=LessonHint))

    assert parsed.tl_dr == "Remember the new retry loop and exception branch."
    assert parsed.key_points == ["Focus on the added for-loop."]


def test_parse_lesson_payload_uses_first_candidate_matching_schema() -> None:
    payload = (
        "```python\n"
        '{"note": "example"}\n'
        "```\n\n"
        "```json\n"
        "{\n"
        '  "tl_dr": "Remember the new retry loop and exception branch.",\n'
        '  "key_points": ["Focus on the added for-loop."],\n'
        '  "watch_fors": ["Do not overclaim reliability or backoff semantics."],\n'
        '  "claims": ["The helper loops over attempts."],\n'
        '  "sources": ["src/app.py:new:1-6"]\n'
        "}\n"
        "```"
    )

    parsed = cast("LessonHint", parse_lesson_payload(payload, schema=LessonHint))

    assert parsed.claims == ["The helper loops over attempts."]


def test_parse_lesson_payload_strips_thinking_blocks_before_json() -> None:
    payload = (
        '<think>{"tl_dr":"wrong","key_points":["wrong"]}</think>\n'
        "The final answer is:\n"
        "{\n"
        '  "tl_dr": "Remember the new retry loop and exception branch.",\n'
        '  "key_points": ["Focus on the added for-loop."],\n'
        '  "claims": ["The helper loops over attempts."],\n'
        '  "sources": ["src/app.py:new:1-6"]\n'
        "}"
    )

    parsed = cast("LessonHint", parse_lesson_payload(payload, schema=LessonHint))

    assert parsed.tl_dr == "Remember the new retry loop and exception branch."


def test_parse_lesson_payload_accepts_unfenced_markdown_prose_wrapping_json() -> None:
    payload = (
        "Here is the lesson object you asked for.\n\n"
        "{\n"
        '  "headline": "Retry loop reminder",\n'
        '  "summary": ["Loop over attempts, then continue on exception."],\n'
        '  "concepts": ["retry loop"],\n'
        '  "sources": ["src/app.py:new:1-6"]\n'
        "}\n\n"
        "This is the complete JSON payload."
    )

    parsed = cast("LessonCompact", parse_lesson_payload(payload, schema=LessonCompact))

    assert parsed.headline == "Retry loop reminder"


@pytest.mark.parametrize(
    "trailing_fragment",
    [
        ', "not_proven": ["The output was truncated inside this string',
        ', "misconcep',
        ",",
    ],
)
def test_parse_lesson_payload_recovers_after_complete_pairs_before_truncated_tail(
    trailing_fragment: str,
) -> None:
    payload = (
        "{\n"
        '  "tl_dr": "The retry helper now loops and handles transient failures.",\n'
        '  "what_changed": ["retry_once now iterates across attempts."],\n'
        '  "why": ["The diff adds a retry-oriented control-flow path."],\n'
        '  "walkthrough": ["Read the new for-loop and exception handling path first."],\n'
        '  "claims": ["The helper now loops over attempts."],\n'
        '  "concepts": ["Retries re-run an operation after a failure."],\n'
        '  "quiz": ["Why is the exception branch part of the teaching surface?"],\n'
        '  "sources": ["src/app.py:new:1-6"]'
        f"{trailing_fragment}"
    )

    parsed = cast("LessonFull", parse_lesson_payload(payload, schema=LessonFull))

    assert parsed.tl_dr == "The retry helper now loops and handles transient failures."
    assert parsed.sources == ["src/app.py:new:1-6"]


def test_parse_lesson_payload_skips_empty_object_mixed_with_real_content() -> None:
    payload = (
        "```json\n{}\n```\n\n"
        "```json\n"
        "{\n"
        '  "tl_dr": "Remember the new retry loop and exception branch.",\n'
        '  "key_points": ["Focus on the added for-loop."],\n'
        '  "claims": ["The helper loops over attempts."],\n'
        '  "sources": ["src/app.py:new:1-6"]\n'
        "}\n"
        "```"
    )

    parsed = cast("LessonHint", parse_lesson_payload(payload, schema=LessonHint))

    assert parsed.key_points == ["Focus on the added for-loop."]


def test_parse_lesson_payload_accepts_unclosed_fenced_json_block() -> None:
    payload = (
        "```json\n"
        "{\n"
        '  "headline": "Retry loop reminder",\n'
        '  "summary": ["Loop over attempts, then continue on exception."],\n'
        '  "concepts": ["retry loop"],\n'
        '  "sources": ["src/app.py:new:1-6"]\n'
        "}\n"
    )

    parsed = cast("LessonCompact", parse_lesson_payload(payload, schema=LessonCompact))

    assert parsed.concepts == ["retry loop"]


def test_parse_lesson_payload_unwraps_nested_output_object_from_reasoning_model() -> None:
    payload = json.dumps(
        {
            "output": {
                "tl_dr": "Remember the new retry loop and exception branch.",
                "key_points": ["Focus on the added for-loop."],
                "claims": ["The helper loops over attempts."],
                "sources": ["src/app.py:new:1-6"],
            }
        }
    )

    parsed = cast("LessonHint", parse_lesson_payload(payload, schema=LessonHint))

    assert parsed.claims == ["The helper loops over attempts."]


def test_parse_lesson_payload_unwraps_escaped_output_string() -> None:
    payload = json.dumps(
        {
            "output": json.dumps(
                {
                    "tl_dr": "Remember the new retry loop and exception branch.",
                    "key_points": ["Focus on the added for-loop."],
                    "claims": ["The helper loops over attempts."],
                    "sources": ["src/app.py:new:1-6"],
                }
            )
        }
    )

    parsed = cast("LessonHint", parse_lesson_payload(payload, schema=LessonHint))

    assert parsed.key_points == ["Focus on the added for-loop."]


def test_parse_lesson_payload_unwraps_openai_responses_envelope() -> None:
    payload = json.dumps(
        {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "tl_dr": "Remember the new retry loop and exception branch.",
                                    "key_points": ["Focus on the added for-loop."],
                                    "claims": ["The helper loops over attempts."],
                                    "sources": ["src/app.py:new:1-6"],
                                }
                            ),
                        }
                    ]
                }
            ]
        }
    )

    parsed = cast("LessonHint", parse_lesson_payload(payload, schema=LessonHint))

    assert parsed.sources == ["src/app.py:new:1-6"]


def test_parse_lesson_payload_prefers_final_valid_json_after_echoed_schema() -> None:
    echoed_schema = {
        "tl_dr": "SCHEMA EXAMPLE SHOULD NOT WIN",
        "key_points": ["wrong"],
        "claims": ["wrong"],
        "sources": ["wrong"],
    }
    final_answer = {
        "tl_dr": "Remember the new retry loop and exception branch.",
        "key_points": ["Focus on the added for-loop."],
        "claims": ["The helper loops over attempts."],
        "sources": ["src/app.py:new:1-6"],
    }
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

    parsed = cast("LessonHint", parse_lesson_payload(payload, schema=LessonHint))

    assert parsed.tl_dr == "Remember the new retry loop and exception branch."


def test_parse_lesson_payload_accepts_single_object_array_root() -> None:
    payload = json.dumps(
        [
            {
                "tl_dr": "Remember the new retry loop and exception branch.",
                "key_points": ["Focus on the added for-loop."],
                "claims": ["The helper loops over attempts."],
                "sources": ["src/app.py:new:1-6"],
            }
        ]
    )

    parsed = cast("LessonHint", parse_lesson_payload(payload, schema=LessonHint))

    assert parsed.sources == ["src/app.py:new:1-6"]


def test_parse_lesson_payload_rejects_missing_required_fields() -> None:
    with pytest.raises(ValueError):
        parse_lesson_payload(json.dumps({"tl_dr": "Too short."}), schema=LessonHint)


def test_parse_lesson_payload_rejects_truncated_required_source_marker() -> None:
    payload = (
        "{\n"
        '  "tl_dr": "Remember the new retry loop and exception branch.",\n'
        '  "key_points": ["Focus on the added for-loop."],\n'
        '  "claims": ["The helper loops over attempts."],\n'
        '  "sources": ["src/app.py:new:1-'
    )

    with pytest.raises(ValueError):
        parse_lesson_payload(payload, schema=LessonHint)


def test_write_lesson_artifacts_rejects_overwrite_before_creating_new_files(tmp_path: Path) -> None:
    full, hint, compact = _sample_lessons()
    run_path = tmp_path / "run"
    lesson_dir = run_path / "lesson"
    lesson_dir.mkdir(parents=True)
    existing_path = lesson_dir / "lesson.hint.md"
    existing_path.write_text("existing hint", encoding="utf-8")

    with pytest.raises(InputError, match="refusing to overwrite existing file"):
        write_lesson_artifacts(
            run_path=run_path,
            full=full,
            hint=hint,
            compact=compact,
            overwrite=False,
        )

    assert existing_path.read_text(encoding="utf-8") == "existing hint"
    assert not (lesson_dir / "lesson.full.md").exists()
    assert not (lesson_dir / "lesson.compact.md").exists()
    assert not (lesson_dir / "misconception.md").exists()
    assert not (lesson_dir / "not_proven.md").exists()


def test_write_lesson_artifacts_rolls_back_when_live_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full, hint, compact = _sample_lessons()
    run_path = tmp_path / "run"
    lesson_dir = run_path / "lesson"
    lesson_dir.mkdir(parents=True)
    original_contents = {
        lesson_dir / "lesson.full.md": "old full\n",
        lesson_dir / "lesson.hint.md": "old hint\n",
        lesson_dir / "lesson.compact.md": "old compact\n",
        lesson_dir / "misconception.md": "old misconception\n",
        lesson_dir / "not_proven.md": "old not proven\n",
    }
    for path, text in original_contents.items():
        path.write_text(text, encoding="utf-8")

    real_replace = Path.replace
    failing_target = lesson_dir
    failure_injected = False

    def flaky_replace(self: Path, target: str | Path) -> Path:
        nonlocal failure_injected
        target_path = Path(target)
        if (
            not failure_injected
            and target_path == failing_target
            and self.name == "lesson"
            and self.parent.name.startswith(".lesson-stage.")
        ):
            failure_injected = True
            raise OSError("simulated live replace failure")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    with pytest.raises(OSError, match="simulated live replace failure"):
        write_lesson_artifacts(
            run_path=run_path,
            full=full,
            hint=hint,
            compact=compact,
            overwrite=True,
        )

    assert failure_injected is True
    for path, text in original_contents.items():
        assert path.read_text(encoding="utf-8") == text


def test_load_lesson_prompt_raises_when_prompt_resource_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_is_file(self: Path) -> bool:
        if self.name == "lesson_hint.md":
            return False
        return Path.exists(self)

    class _MissingResource:
        def is_file(self) -> bool:
            return False

    class _MissingFiles:
        def joinpath(self, *parts: str) -> _MissingResource:
            return _MissingResource()

    def fake_files(package: str) -> _MissingFiles:
        return _MissingFiles()

    monkeypatch.setattr("ahadiff.lesson.generator.files", fake_files)
    monkeypatch.setattr(Path, "is_file", fake_is_file)

    with pytest.raises(InputError, match="lesson prompt resource is missing: lesson_hint.md"):
        load_lesson_prompt("hint")


def test_learn_cli_generates_lessons_with_explicit_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    patch_path = workspace_root / "input.patch"
    patch_path.write_text(
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,6 @@\n"
        "-def retry_once():\n"
        "-    return 1\n"
        "+def retry_once():\n"
        "+    for attempt in range(3):\n"
        "+        try:\n"
        "+            return attempt\n"
        "+        except Exception:\n"
        "+            continue\n",
        encoding="utf-8",
    )
    spec_path = workspace_root / "SPEC.md"
    spec_path.write_text("- The retry helper must loop over attempts.\n", encoding="utf-8")
    fake_provider = _FakeLessonProvider()
    captured: dict[str, object] = {}

    def fake_extract_claim_candidates_from_run(**kwargs: object):
        captured["provider_config"] = kwargs["provider_config"]
        output_path = cast("Path", kwargs["output_path"])
        write_claim_candidates_jsonl(
            output_path,
            [
                ClaimCandidate(
                    claim_id="run_cli_claim_1",
                    run_id=str(kwargs["run_id"]),
                    text="The retry helper now loops over attempts.",
                    source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
                    symbols=["retry_once"],
                )
            ],
            overwrite=True,
        )
        return output_path, ()

    def fake_verify_claim_candidates(*args: object, **kwargs: object) -> tuple[VerifiedClaim, ...]:
        return (
            VerifiedClaim(
                record=ClaimRecord(
                    claim_id="run_cli_claim_1",
                    run_id="run_cli_claim_1",
                    text="The retry helper now loops over attempts.",
                    status="verified",
                    confidence="high",
                    source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
                )
            ),
        )

    monkeypatch.setattr(
        cli_module,
        "extract_claim_candidates_from_run",
        fake_extract_claim_candidates_from_run,
    )
    monkeypatch.setattr(cli_module, "verify_claim_candidates", fake_verify_claim_candidates)

    def fake_provider_factory(*args: object, **kwargs: object) -> _FakeLessonProvider:
        return fake_provider

    monkeypatch.setattr("ahadiff.lesson.generator.make_provider", fake_provider_factory)

    def fake_quiz(
        *args: object, **kwargs: object
    ) -> tuple[QuizArtifactPaths, tuple[QuizQuestion, ...]]:
        run_path = cast("Path", kwargs["run_path"])
        questions = (
            QuizQuestion(
                question_id="quiz_1",
                question="What changed?",
                expected_answer="The retry helper now loops over attempts.",
                source_claims=["run_cli_claim_1"],
                concepts=["retry loop"],
                evidence=[QuizEvidence(file="src/app.py", line=2)],
            ),
        )
        quiz_path = run_path / "quiz" / "quiz.jsonl"
        write_quiz_questions_jsonl(quiz_path, questions)
        return QuizArtifactPaths(quiz_dir=quiz_path.parent, quiz_path=quiz_path), questions

    monkeypatch.setattr(cli_module, "generate_quiz_from_run", fake_quiz)

    result = _RUNNER.invoke(
        app(),
        [
            "learn",
            "--patch",
            str(patch_path),
            "--repo-root",
            str(workspace_root),
            "--against-spec",
            "SPEC.md",
            "--base-url",
            "http://127.0.0.1:8318/v1/chat/completions",
            "--model",
            "gpt-5.4-mini",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    run_dirs = sorted((workspace_root / ".ahadiff" / "runs").iterdir())
    assert run_dirs
    lesson_dir = run_dirs[-1] / "lesson"
    assert (run_dirs[-1] / "claims.jsonl").exists()
    assert (lesson_dir / "lesson.full.md").exists()
    assert (lesson_dir / "lesson.hint.md").exists()
    assert (lesson_dir / "lesson.compact.md").exists()
    assert (run_dirs[-1] / "quiz" / "quiz.jsonl").exists()
    spec_alignment = json.loads((run_dirs[-1] / "spec_alignment.json").read_text(encoding="utf-8"))
    assert spec_alignment["schema"] == "ahadiff.spec_alignment"
    assert spec_alignment["spec_source"]["path"] == "SPEC.md"
    assert spec_alignment["requirements"]
    assert (run_dirs[-1] / "score.json").exists()
    provider_config = captured["provider_config"]
    assert isinstance(provider_config, ProviderConfig)
    assert provider_config.base_url == "http://127.0.0.1:8318"
    assert "Lesson" in result.stdout
    events = load_result_events(review_db_path_for_run(run_dirs[-1]))
    assert len(events) == 1
    assert events[0].event_type == "learn"
    assert events[0].note_json is not None
    assert '"learnability"' in events[0].note_json


def test_learn_cli_cleans_claim_artifacts_when_lesson_generation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    patch_path = workspace_root / "input.patch"
    patch_path.write_text(
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,6 @@\n"
        "-def retry_once():\n"
        "-    return 1\n"
        "+def retry_once():\n"
        "+    for attempt in range(3):\n"
        "+        try:\n"
        "+            return attempt\n"
        "+        except Exception:\n"
        "+            continue\n",
        encoding="utf-8",
    )

    def fake_extract_claim_candidates_from_run(**kwargs: object):
        output_path = cast("Path", kwargs["output_path"])
        write_claim_candidates_jsonl(
            output_path,
            [
                ClaimCandidate(
                    claim_id="run_cli_claim_1",
                    run_id=str(kwargs["run_id"]),
                    text="The retry helper now loops over attempts.",
                    source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
                    symbols=["retry_once"],
                )
            ],
            overwrite=True,
        )
        return output_path, ()

    def fake_verify_claim_candidates(*args: object, **kwargs: object) -> tuple[VerifiedClaim, ...]:
        return (
            VerifiedClaim(
                record=ClaimRecord(
                    claim_id="run_cli_claim_1",
                    run_id="run_cli_claim_1",
                    text="The retry helper now loops over attempts.",
                    status="verified",
                    confidence="high",
                    source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
                )
            ),
        )

    class _InvalidLessonProvider:
        def generate(self, request: ProviderRequest) -> ProviderResponse:
            return ProviderResponse(
                content='{"note": "example"}',
                model_id="gpt-5.4-mini",
                input_tokens=10,
                output_tokens=20,
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        cli_module,
        "extract_claim_candidates_from_run",
        fake_extract_claim_candidates_from_run,
    )
    monkeypatch.setattr(cli_module, "verify_claim_candidates", fake_verify_claim_candidates)

    def fake_invalid_provider_factory(*args: object, **kwargs: object) -> _InvalidLessonProvider:
        return _InvalidLessonProvider()

    monkeypatch.setattr("ahadiff.lesson.generator.make_provider", fake_invalid_provider_factory)

    result = _RUNNER.invoke(
        app(),
        [
            "learn",
            "--patch",
            str(patch_path),
            "--repo-root",
            str(workspace_root),
            "--base-url",
            "http://127.0.0.1:8318/v1/chat/completions",
            "--model",
            "gpt-5.4-mini",
        ],
    )

    assert result.exit_code == 1
    run_dirs = sorted((workspace_root / ".ahadiff" / "runs").iterdir())
    assert run_dirs
    run_path = run_dirs[-1]
    assert not (run_path / "claims.raw.jsonl").exists()
    assert not (run_path / "claims.jsonl").exists()
    assert not (run_path / "lesson").exists()
    assert (run_path / "patch.diff").exists()
    assert (run_path / "metadata.json").exists()


def test_learn_cli_skips_generation_for_low_learnability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    patch_path = workspace_root / "input.patch"
    patch_path.write_text(
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1 +1 @@\n"
        '-message = "helo"\n'
        '+message = "hello"\n',
        encoding="utf-8",
    )

    def should_not_run(**kwargs: object):
        raise AssertionError("claims extraction should be skipped for low learnability")

    monkeypatch.setattr(cli_module, "extract_claim_candidates_from_run", should_not_run)

    result = _RUNNER.invoke(
        app(),
        [
            "learn",
            "--patch",
            str(patch_path),
            "--repo-root",
            str(workspace_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    run_dirs = sorted((workspace_root / ".ahadiff" / "runs").iterdir())
    assert run_dirs
    assert not (run_dirs[-1] / "lesson").exists()
    assert "skipped by learnability gate" in result.stdout


def test_learn_cli_skips_lesson_generation_without_verified_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    patch_path = workspace_root / "input.patch"
    patch_path.write_text(
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,6 @@\n"
        "-def retry_once():\n"
        "-    return 1\n"
        "+def retry_once():\n"
        "+    for attempt in range(3):\n"
        "+        try:\n"
        "+            return attempt\n"
        "+        except Exception:\n"
        "+            continue\n",
        encoding="utf-8",
    )

    def fake_extract_claim_candidates_from_run(**kwargs: object):
        output_path = cast("Path", kwargs["output_path"])
        write_claim_candidates_jsonl(
            output_path,
            [
                ClaimCandidate(
                    claim_id="run_cli_claim_1",
                    run_id=str(kwargs["run_id"]),
                    text="The retry helper now loops over attempts.",
                    source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
                    symbols=["retry_once"],
                )
            ],
            overwrite=True,
        )
        return output_path, ()

    def fake_verify_claim_candidates(*args: object, **kwargs: object) -> tuple[VerifiedClaim, ...]:
        return (
            VerifiedClaim(
                record=ClaimRecord(
                    claim_id="run_cli_claim_1",
                    run_id="run_cli_claim_1",
                    text="The retry helper now loops over attempts.",
                    status="not_proven",
                    confidence="low",
                    source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
                )
            ),
        )

    def should_not_run_provider(*args: object, **kwargs: object):
        raise AssertionError("lesson provider should be skipped when no verified claims survive")

    monkeypatch.setattr(
        cli_module,
        "extract_claim_candidates_from_run",
        fake_extract_claim_candidates_from_run,
    )
    monkeypatch.setattr(cli_module, "verify_claim_candidates", fake_verify_claim_candidates)
    monkeypatch.setattr("ahadiff.lesson.generator.make_provider", should_not_run_provider)

    result = _RUNNER.invoke(
        app(),
        [
            "learn",
            "--patch",
            str(patch_path),
            "--repo-root",
            str(workspace_root),
            "--base-url",
            "http://127.0.0.1:8318/v1/chat/completions",
            "--model",
            "gpt-5.4-mini",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    run_dirs = sorted((workspace_root / ".ahadiff" / "runs").iterdir())
    assert run_dirs
    run_path = run_dirs[-1]
    assert (run_path / "claims.jsonl").exists()
    assert not (run_path / "lesson").exists()
    assert not (run_path / "score.json").exists()
    assert "skipped because no verified claims survived verification" in result.stdout
