from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import pytest

from ahadiff.claims.extract import parse_claim_candidates_text
from ahadiff.contracts import ProviderClass, ProviderConfig
from ahadiff.core.config import SecurityConfig
from ahadiff.lesson.schemas import LessonCompact, parse_lesson_payload
from ahadiff.llm import ProviderRequest, make_provider
from ahadiff.llm.provider import reset_provider_runtime_state
from ahadiff.llm.structured import structured_request_kwargs
from ahadiff.quiz.schemas import parse_quiz_payload

if TYPE_CHECKING:
    from pathlib import Path

    from ahadiff.contracts import PrivacyMode
    from ahadiff.llm.schemas import EnforcementMode


SmokeKind = Literal["claims", "quiz", "compact_lesson"]


@dataclass(frozen=True)
class StructuredLiveCase:
    name: str
    provider_class: ProviderClass
    enabled_env: str
    model_env: str
    default_model: str | None
    base_url_env: str
    default_base_url: str | None
    api_key_envs: tuple[str, ...]
    schema_name: str
    smoke_kind: SmokeKind
    max_output_tokens: int = 640
    enforcement_mode: EnforcementMode = "native_json_schema"
    privacy_mode: PrivacyMode = "strict_local"


_CASES: tuple[StructuredLiveCase, ...] = (
    StructuredLiveCase(
        name="lmstudio_claims",
        provider_class="lmstudio",
        enabled_env="AHADIFF_LIVE_STRUCTURED_LMSTUDIO",
        model_env="AHADIFF_LIVE_STRUCTURED_LMSTUDIO_MODEL",
        default_model=None,
        base_url_env="AHADIFF_LIVE_STRUCTURED_LMSTUDIO_BASE_URL",
        default_base_url="http://127.0.0.1:1234/v1",
        api_key_envs=(),
        schema_name="claim_candidates.v1",
        smoke_kind="claims",
    ),
    StructuredLiveCase(
        name="ollama_claims",
        provider_class="ollama",
        enabled_env="AHADIFF_LIVE_STRUCTURED_OLLAMA",
        model_env="AHADIFF_LIVE_STRUCTURED_OLLAMA_MODEL",
        default_model=None,
        base_url_env="AHADIFF_LIVE_STRUCTURED_OLLAMA_BASE_URL",
        default_base_url="http://127.0.0.1:11434",
        api_key_envs=(),
        schema_name="claim_candidates.v1",
        smoke_kind="claims",
    ),
    StructuredLiveCase(
        name="openai_chat_claims",
        provider_class="openai",
        enabled_env="AHADIFF_LIVE_STRUCTURED_OPENAI",
        model_env="AHADIFF_LIVE_STRUCTURED_OPENAI_MODEL",
        default_model=None,
        base_url_env="AHADIFF_LIVE_STRUCTURED_OPENAI_BASE_URL",
        default_base_url=None,
        api_key_envs=(
            "AHADIFF_LIVE_STRUCTURED_OPENAI_API_KEY",
            "OPENAI_API_KEY",
            "AHADIFF_PROVIDER_API_KEY",
        ),
        schema_name="claim_candidates.v1",
        smoke_kind="claims",
    ),
    StructuredLiveCase(
        name="gemini_quiz",
        provider_class="gemini",
        enabled_env="AHADIFF_LIVE_STRUCTURED_GEMINI",
        model_env="AHADIFF_LIVE_STRUCTURED_GEMINI_MODEL",
        default_model=None,
        base_url_env="AHADIFF_LIVE_STRUCTURED_GEMINI_BASE_URL",
        default_base_url="https://generativelanguage.googleapis.com",
        api_key_envs=(
            "AHADIFF_LIVE_STRUCTURED_GEMINI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
        ),
        schema_name="quiz_generate.v1",
        smoke_kind="quiz",
        privacy_mode="explicit_remote",
    ),
    StructuredLiveCase(
        name="anthropic_compact_lesson",
        provider_class="anthropic",
        enabled_env="AHADIFF_LIVE_STRUCTURED_ANTHROPIC",
        model_env="AHADIFF_LIVE_STRUCTURED_ANTHROPIC_MODEL",
        default_model=None,
        base_url_env="AHADIFF_LIVE_STRUCTURED_ANTHROPIC_BASE_URL",
        default_base_url=None,
        api_key_envs=(
            "AHADIFF_LIVE_STRUCTURED_ANTHROPIC_API_KEY",
            "ANTHROPIC_API_KEY",
        ),
        schema_name="lesson_compact.v1",
        smoke_kind="compact_lesson",
    ),
)


def _first_env(names: tuple[str, ...]) -> tuple[str, str] | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return name, value
    return None


def _settings(case: StructuredLiveCase) -> tuple[str, str, str, str | None]:
    if (
        os.environ.get("AHADIFF_LIVE_STRUCTURED_OUTPUT") != "1"
        and os.environ.get(case.enabled_env) != "1"
    ):
        pytest.skip(
            "set AHADIFF_LIVE_STRUCTURED_OUTPUT=1 or "
            f"{case.enabled_env}=1 to run this live structured output smoke"
        )
        raise AssertionError("unreachable")

    model = os.environ.get(case.model_env) or case.default_model
    if not model:
        pytest.skip(f"set {case.model_env} to run this live structured output smoke")
        raise AssertionError("unreachable")
    base_url = os.environ.get(case.base_url_env) or case.default_base_url
    if not base_url:
        pytest.skip(f"set {case.base_url_env} to run this live structured output smoke")
        raise AssertionError("unreachable")
    api_key: str | None = None
    api_key_env = ""
    if case.api_key_envs:
        found = _first_env(case.api_key_envs)
        if found is None:
            if not _is_loopback_base_url(base_url):
                pytest.skip("set one of " + ", ".join(case.api_key_envs))
                raise AssertionError("unreachable")
        else:
            api_key_env, api_key = found
    return base_url, model, api_key_env, api_key


def _is_loopback_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    return (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}


def _provider_config(
    case: StructuredLiveCase,
    *,
    base_url: str,
    model: str,
    api_key_env: str,
) -> ProviderConfig:
    return ProviderConfig(
        provider_class=case.provider_class,
        model_name=model,
        base_url=base_url.rstrip("/"),
        api_key_env=api_key_env,
        max_output_tokens=case.max_output_tokens,
        probed_max_context=65_536,
    )


def _request(case: StructuredLiveCase, *, model: str) -> ProviderRequest:
    diff = "diff --git a/a.py b/a.py\n+def add(a, b):\n+    return a + b\n"
    if case.smoke_kind == "quiz":
        prompt = (
            "Return valid JSON only. Create exactly one multiple-choice quiz question "
            "about the diff. Include source_claims, concepts, evidence with file a.py "
            "line 1, and exactly four choices with one correct answer. "
            'Set quiz_kind to "recall"; set answer_mode to "multiple_choice".'
        )
    elif case.smoke_kind == "compact_lesson":
        prompt = (
            "Return valid JSON only. Write a compact lesson. The JSON object must have "
            "headline as a string, summary as an array of strings, concepts as an array "
            'of strings, and sources as an array of strings. Use source "a.py:new:1-2".'
        )
    else:
        prompt = (
            "Return valid JSON only. Extract one concise claim candidate from this diff. "
            'Use run_id "phase72_live_smoke". Use source_hunks with file "a.py", '
            'start 1, end 2, side "new". Use extractor "regex". '
            'The claim text field must be named "text", not "claim".'
        )
    prompt = f"{prompt}\n\nDiff:\n{diff}"
    return ProviderRequest(
        prompt_name=f"live.structured.{case.name}",
        prompt_fingerprint="phase7.2",
        prompt_version="1",
        eval_bundle_version="phase7.2",
        model=model,
        payload_text=prompt,
        diff_content=diff,
        source_ref=f"phase7.2-{case.name}",
        privacy_mode=case.privacy_mode,
        max_output_tokens=case.max_output_tokens,
        temperature=0,
        **structured_request_kwargs(
            schema_name=case.schema_name,
            provider_class=case.provider_class,
            mode=case.enforcement_mode,
        ),
    )


def _validate(case: StructuredLiveCase, content: str) -> None:
    if case.smoke_kind == "quiz":
        quiz = parse_quiz_payload(content, require_choices=True)
        assert len(quiz.questions) == 1
        question = quiz.questions[0]
        assert question.source_claims
        assert question.concepts
        assert question.evidence
        assert any(anchor.file == "a.py" and anchor.line == 1 for anchor in question.evidence)
        assert question.choices is not None
        assert len(question.choices) == 4
        return
    if case.smoke_kind == "compact_lesson":
        lesson = parse_lesson_payload(content, schema=LessonCompact)
        assert isinstance(lesson, LessonCompact)
        assert lesson.headline
        assert lesson.summary
        assert lesson.concepts
        assert any("a.py" in source for source in lesson.sources)
        return
    candidates = parse_claim_candidates_text(content, default_run_id="phase72_live_smoke")
    assert candidates
    assert any(
        hunk.file == "a.py" and hunk.start <= 1 <= hunk.end and hunk.side == "new"
        for candidate in candidates
        for hunk in candidate.source_hunks
    )


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.name)
def test_live_structured_output_smoke(
    case: StructuredLiveCase,
    tmp_path: Path,
) -> None:
    base_url, model, api_key_env, api_key = _settings(case)
    reset_provider_runtime_state()
    with make_provider(
        _provider_config(case, base_url=base_url, model=model, api_key_env=api_key_env),
        api_key=api_key,
        security_config=SecurityConfig(),
        workspace_root=tmp_path,
        retry_attempts=0,
        request_timeout_seconds=120,
        max_concurrent=1,
        qps_limit=0,
        output_token_budget=max(1_000, case.max_output_tokens * 2),
        execution_origin="live_structured_output_smoke",
    ) as provider:
        response = provider.generate(_request(case, model=model))
    _validate(case, response.content)
