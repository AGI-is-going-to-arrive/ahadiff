from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, cast

import pytest

from ahadiff.core.errors import InputError
from ahadiff.llm import ProviderRequest, ProviderResponse
from ahadiff.llm.structured import (
    OutputSchemaSpec,
    normalize_schema_for_provider,
    schema_hash,
    schema_spec_for,
    structured_request_kwargs,
)
from ahadiff.llm.validation_retry import (
    build_validation_retry_feedback,
    generate_with_validation_retry,
)


def test_schema_hash_is_stable_for_claim_candidates() -> None:
    spec = schema_spec_for("claim_candidates.v1")

    assert spec.schema_id == "claim_candidates"
    assert spec.schema_version == "1"
    assert spec.schema_hash.startswith("sha256:")
    assert schema_hash(spec.json_schema) == spec.schema_hash


def test_schema_registry_rejects_unknown_schema() -> None:
    with pytest.raises(InputError, match="unknown output schema"):
        schema_spec_for("missing.v1")


@pytest.mark.parametrize(
    "schema_name",
    [
        "claim_candidates.v1",
        "lesson_full.v1",
        "lesson_hint.v1",
        "lesson_compact.v1",
        "quiz_generate.v1",
        "quiz_misconception_card.v1",
    ],
)
def test_registered_schemas_are_object_roots(schema_name: str) -> None:
    spec = schema_spec_for(schema_name)

    assert spec.json_schema["type"] == "object"
    assert schema_hash(spec.json_schema) == spec.schema_hash


@pytest.mark.parametrize(
    "provider_kind",
    [
        "openai_chat",
        "openai_responses",
        "azure",
        "openai_compat",
        "gemini",
        "anthropic",
        "ollama",
        "lmstudio",
        "newapi",
    ],
)
def test_provider_normalizers_strip_sensitive_schema_hints(provider_kind: str) -> None:
    base_spec = schema_spec_for("quiz_generate.v1")
    schema = json.loads(json.dumps(base_spec.json_schema))
    schema["description"] = "SECRET_DESC"
    schema["properties"]["sentinel"] = {
        "type": "string",
        "description": "SECRET_FIELD",
        "enum": ["SECRET_ENUM"],
        "const": "SECRET_CONST",
    }
    spec = replace(
        base_spec,
        json_schema=schema,
        schema_hash=schema_hash(schema),
    )

    normalized = normalize_schema_for_provider(spec, provider_kind=provider_kind)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True)

    assert normalized["type"] == ("OBJECT" if provider_kind == "gemini" else "object")
    assert '"default"' not in encoded
    assert '"examples"' not in encoded
    assert '"example"' not in encoded
    assert '"pattern"' not in encoded
    assert "SECRET_DESC" not in encoded
    assert "SECRET_FIELD" not in encoded
    assert "SECRET_ENUM" not in encoded
    assert "SECRET_CONST" not in encoded
    assert schema_hash(spec.json_schema) == spec.schema_hash


@pytest.mark.parametrize(
    "provider_kind",
    [
        "openai_chat",
        "openai_responses",
        "azure",
        "openai_compat",
        "lmstudio",
        "newapi",
    ],
)
def test_openai_compatible_normalizer_uses_strict_required_object_subset(
    provider_kind: str,
) -> None:
    normalized = normalize_schema_for_provider(
        schema_spec_for("claim_candidates.v1"),
        provider_kind=provider_kind,
    )
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    if provider_kind in {"openai_compat", "lmstudio", "newapi"}:
        claim_schema = normalized["properties"]["claims"]["items"]
    else:
        claim_schema = normalized["$defs"]["ClaimCandidate"]

    assert '"title"' not in encoded
    assert set(normalized["required"]) == set(normalized["properties"])
    assert set(claim_schema["required"]) == set(claim_schema["properties"])
    if provider_kind in {"openai_compat", "lmstudio", "newapi"}:
        assert claim_schema["properties"]["extractor"]["anyOf"] == [
            {"type": "string"},
            {"type": "null"},
        ]
        assert '"$defs"' not in encoded
        assert '"$ref"' not in encoded
    else:
        assert claim_schema["properties"]["extractor"]["type"] == ["string", "null"]


def test_gemini_normalizer_uses_response_schema_subset_without_refs() -> None:
    normalized = normalize_schema_for_provider(
        schema_spec_for("quiz_generate.v1"),
        provider_kind="gemini",
    )
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    question_schema = normalized["properties"]["questions"]["items"]

    assert '"$defs"' not in encoded
    assert '"$ref"' not in encoded
    assert '"additionalProperties"' not in encoded
    assert normalized["type"] == "OBJECT"
    assert normalized["properties"]["questions"]["type"] == "ARRAY"
    assert question_schema["type"] == "OBJECT"
    assert question_schema["properties"]["choices"]["nullable"] is True
    assert question_schema["properties"]["evidence"]["items"]["type"] == "OBJECT"


def test_provider_normalizer_rejects_unknown_provider() -> None:
    with pytest.raises(InputError, match="unknown provider schema target"):
        normalize_schema_for_provider(schema_spec_for("claim_candidates.v1"), provider_kind="weird")


def test_validation_feedback_omits_prompt_diff_and_schema_body() -> None:
    feedback = build_validation_retry_feedback(
        schema_id="quiz_generate",
        schema_version="1",
        errors=[
            {
                "loc": ("questions", 0, "evidence"),
                "type": "missing",
                "msg": "Field required",
            }
        ],
    )

    assert "quiz_generate.v1" in feedback
    assert "questions.0.evidence" in feedback
    assert "diff --git" not in feedback
    assert '"properties"' not in feedback


def test_validation_feedback_redacts_sensitive_error_paths() -> None:
    feedback = build_validation_retry_feedback(
        schema_id="claim_candidates",
        schema_version="1",
        errors=[
            {
                "loc": ("claims", 0, "private_password"),
                "type": "value_error",
                "msg": "Invalid value from /Users/alice/project/.env",
            }
        ],
    )

    assert "private_password" not in feedback
    assert "/Users/alice" not in feedback
    assert "[sensitive path omitted]" in feedback
    assert "[path omitted]" in feedback


def test_structured_request_kwargs_records_normalized_schema_hash() -> None:
    kwargs = structured_request_kwargs(
        schema_name="quiz_generate.v1",
        provider_class="openai",
        mode="native_json_schema",
    )

    assert kwargs["output_schema_hash"] == schema_spec_for("quiz_generate.v1").schema_hash
    assert kwargs["normalized_output_schema_hash"] == schema_hash(kwargs["output_schema"])
    assert kwargs["normalized_output_schema_hash"] != kwargs["output_schema_hash"]


class _RetryProvider:
    def __init__(self, responses: tuple[str, ...]) -> None:
        self.responses = responses
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        index = len(self.requests) - 1
        return ProviderResponse(
            content=self.responses[index],
            model_id="test-model",
            input_tokens=1,
            output_tokens=1,
        )


def _request() -> ProviderRequest:
    return ProviderRequest(
        prompt_name="test",
        prompt_fingerprint="prompt",
        prompt_version="prompt",
        eval_bundle_version="bundle",
        model="test-model",
        payload_text="Return JSON.",
        diff_content="diff",
        source_ref="HEAD",
    )


def test_validation_retry_feedback_omits_raw_provider_output() -> None:
    provider = _RetryProvider(("not json AKIA1234567890", "{}"))

    result = generate_with_validation_retry(
        provider=cast("Any", provider),
        request=_request(),
        schema_spec=OutputSchemaSpec(
            schema_id="claim_candidates",
            schema_version="1",
            json_schema={"type": "object"},
            schema_hash="sha256:test",
        ),
        parse=lambda content: (_ for _ in ()).throw(ValueError(f"bad payload: {content}"))
        if content != "{}"
        else {},
        max_validation_retries=1,
    )

    assert result.value == {}
    assert len(provider.requests) == 2
    retry_payload = provider.requests[1].payload_text
    assert "AKIA1234567890" not in retry_payload
    assert "provider output omitted" in retry_payload


def test_validation_retry_exhaustion_omits_raw_provider_output() -> None:
    provider = _RetryProvider(('{"private_password":"/Users/alice/project/.env"}',))

    with pytest.raises(InputError) as exc_info:
        generate_with_validation_retry(
            provider=cast("Any", provider),
            request=_request(),
            schema_spec=OutputSchemaSpec(
                schema_id="claim_candidates",
                schema_version="1",
                json_schema={"type": "object"},
                schema_hash="sha256:test",
            ),
            parse=lambda content: (_ for _ in ()).throw(ValueError(f"bad payload: {content}")),
            max_validation_retries=0,
        )

    message = str(exc_info.value)
    assert "provider output omitted" in message
    assert "private_password" not in message
    assert "/Users/alice" not in message


def test_validation_retry_preserves_fallback_before_retry() -> None:
    provider = _RetryProvider(("repairable but not strict", "unreachable"))

    result = generate_with_validation_retry(
        provider=cast("Any", provider),
        request=_request(),
        schema_spec=OutputSchemaSpec(
            schema_id="lesson_compact",
            schema_version="1",
            json_schema={"type": "object"},
            schema_hash="sha256:test",
        ),
        parse=lambda _: (_ for _ in ()).throw(ValueError("strict parse failed")),
        fallback_parse=lambda content: {"repaired": content},
        max_validation_retries=1,
    )

    assert result.value == {"repaired": "repairable but not strict"}
    assert result.attempts == 1
    assert len(provider.requests) == 1
