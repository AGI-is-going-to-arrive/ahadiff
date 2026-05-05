from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from ahadiff.contracts import ProviderClass, ProviderConfig
from ahadiff.core.config import SecurityConfig
from ahadiff.core.errors import ProviderError, SafetyError
from ahadiff.llm import ProviderRequest, make_provider
from ahadiff.llm.provider import reset_provider_runtime_state

if TYPE_CHECKING:
    from pathlib import Path


_DEFAULT_BASE_URL = "http://127.0.0.1:8318/v1/chat/completions"
_DEFAULT_MODELS = "gpt-5.3-codex-spark,gpt-5.4-mini"
_PROVIDER_PRIORITY: tuple[ProviderClass, ...] = ("openai_responses", "openai")


@dataclass(frozen=True)
class LiveJudgeError:
    provider_class: ProviderClass
    model: str
    message: str


@dataclass(frozen=True)
class LiveJudgeSuccess:
    provider_class: ProviderClass
    model: str
    verdict: str
    errors: tuple[LiveJudgeError, ...]


def _live_settings() -> tuple[str, str, tuple[str, ...]]:
    if os.environ.get("AHADIFF_LIVE_LLM_JUDGE") != "1":
        pytest.skip("set AHADIFF_LIVE_LLM_JUDGE=1 to run the live LLM judge test")
        raise AssertionError("unreachable")
    api_key = os.environ.get("AHADIFF_LIVE_LLM_API_KEY") or os.environ.get(
        "AHADIFF_PROVIDER_API_KEY"
    )
    if not api_key:
        pytest.skip("set AHADIFF_LIVE_LLM_API_KEY or AHADIFF_PROVIDER_API_KEY")
        raise AssertionError("unreachable")
    models = tuple(
        model.strip()
        for model in os.environ.get("AHADIFF_LIVE_LLM_MODELS", _DEFAULT_MODELS).split(",")
        if model.strip()
    )
    if not models:
        pytest.fail("AHADIFF_LIVE_LLM_MODELS did not contain any model names")
    return os.environ.get("AHADIFF_LIVE_LLM_BASE_URL", _DEFAULT_BASE_URL), api_key, models


def _normalize_openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    for suffix in (
        "/v1/chat/completions",
        "/chat/completions",
        "/v1/responses",
        "/responses",
    ):
        if normalized.endswith(suffix):
            trimmed = normalized[: -len(suffix)]
            if trimmed:
                return trimmed
    return normalized


def _configured_context_window(model: str) -> int:
    if model == "gpt-5.4-mini":
        return 256_000
    return 1_000_000


def _provider_config(provider_class: ProviderClass, *, base_url: str, model: str) -> ProviderConfig:
    return ProviderConfig(
        provider_class=provider_class,
        model_name=model,
        base_url=_normalize_openai_base_url(base_url),
        api_key_env="AHADIFF_LIVE_LLM_API_KEY",
        probed_max_context=_configured_context_window(model),
    )


def _judge_request(model: str) -> ProviderRequest:
    diff = "\n".join(
        [
            "diff --git a/example.py b/example.py",
            "@@",
            "+def answer() -> int:",
            "+    return 2",
        ]
    )
    return ProviderRequest(
        prompt_name="live_llm_judge",
        prompt_fingerprint="live-llm-judge-v1",
        prompt_version="live-llm-judge-v1",
        eval_bundle_version="live-eval-bundle-v1",
        model=model,
        payload_text=(
            "You are AhaDiff's live LLM judge. Return only JSON with keys "
            '"verdict" and "rationale". Use verdict PASS if the claim is supported, '
            "otherwise FAIL.\n\n"
            f"Diff evidence:\n{diff}\n\n"
            "Claim: example.py adds answer(), and answer() returns 2."
        ),
        diff_content=diff,
        source_ref="live_llm_judge_fixture",
        output_lang="en",
        privacy_mode="strict_local",
        redaction_config="none",
        max_output_tokens=160,
        response_format="json",
    )


def _parse_judge_payload(content: str) -> dict[str, object]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start : end + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("judge response must be a JSON object")
    return cast("dict[str, object]", parsed)


def _run_live_judge(
    *,
    provider_class: ProviderClass,
    model: str,
    base_url: str,
    api_key: str,
    tmp_path: Path,
) -> str:
    with make_provider(
        _provider_config(provider_class, base_url=base_url, model=model),
        api_key=api_key,
        security_config=SecurityConfig(),
        workspace_root=tmp_path,
        retry_attempts=0,
        request_timeout_seconds=90,
        max_concurrent=1,
        qps_limit=0,
        execution_origin="live_test",
    ) as provider:
        response = provider.generate(_judge_request(model))
    payload = _parse_judge_payload(response.content)
    verdict = payload.get("verdict")
    if not isinstance(verdict, str):
        raise ValueError("judge response is missing a string verdict")
    return verdict


def _run_first_available_judge(
    *,
    models: tuple[str, ...],
    base_url: str,
    api_key: str,
    tmp_path: Path,
) -> LiveJudgeSuccess:
    reset_provider_runtime_state()
    errors: list[LiveJudgeError] = []
    for model in models:
        for provider_class in _PROVIDER_PRIORITY:
            try:
                verdict = _run_live_judge(
                    provider_class=provider_class,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    tmp_path=tmp_path,
                )
            except (ProviderError, SafetyError, ValueError, json.JSONDecodeError) as exc:
                errors.append(
                    LiveJudgeError(
                        provider_class=provider_class,
                        model=model,
                        message=str(exc),
                    )
                )
                continue
            return LiveJudgeSuccess(
                provider_class=provider_class,
                model=model,
                verdict=verdict,
                errors=tuple(errors),
            )
    pytest.fail(
        "no configured live LLM judge endpoint succeeded:\n"
        + "\n".join(f"- {error.model}/{error.provider_class}: {error.message}" for error in errors)
    )


def test_live_llm_judge_prefers_responses_and_falls_back_to_available_model(
    tmp_path: Path,
) -> None:
    base_url, api_key, models = _live_settings()

    result = _run_first_available_judge(
        models=models,
        base_url=base_url,
        api_key=api_key,
        tmp_path=tmp_path,
    )

    assert result.verdict == "PASS"
    assert result.provider_class in _PROVIDER_PRIORITY
    assert result.model in models
    if result.model != models[0]:
        assert any(error.model == models[0] for error in result.errors)
