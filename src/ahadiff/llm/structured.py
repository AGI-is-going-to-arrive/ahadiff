from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict

from ahadiff.core.errors import InputError

if TYPE_CHECKING:
    from ahadiff.llm.schemas import EnforcementMode, RequestFormat

ProviderSchemaTarget = Literal[
    "openai_chat",
    "openai_responses",
    "azure",
    "openai_compat",
    "gemini",
    "anthropic",
    "ollama",
]


@dataclass(frozen=True)
class OutputSchemaSpec:
    schema_id: str
    schema_version: str
    json_schema: dict[str, Any]
    schema_hash: str
    pydantic_model: type[BaseModel] | None = None


_PROVIDER_TARGETS: dict[str, ProviderSchemaTarget] = {
    "openai": "openai_chat",
    "openai_chat": "openai_chat",
    "openai_responses": "openai_responses",
    "azure": "azure",
    "openai_compat": "openai_compat",
    "gemini": "gemini",
    "anthropic": "anthropic",
    "ollama": "ollama",
    "lmstudio": "openai_compat",
    "newapi": "openai_compat",
}

_STRUCTURED_RESPONSE_FORMATS: dict[EnforcementMode, RequestFormat] = {
    "prompt_contract": "text",
    "json_object": "json",
    "native_json_schema": "json_schema",
    "strict_tool": "json_schema",
}

_UNSUPPORTED_OR_RISKY_SCHEMA_KEYS = frozenset(
    {
        "default",
        "description",
        "enum",
        "example",
        "examples",
        "const",
        "pattern",
        "format",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "title",
        "patternProperties",
        "unevaluatedProperties",
        "propertyNames",
        "minProperties",
        "maxProperties",
        "unevaluatedItems",
        "contains",
        "minContains",
        "maxContains",
        "minItems",
        "maxItems",
        "uniqueItems",
        "allOf",
        "not",
        "dependentRequired",
        "dependentSchemas",
        "if",
        "then",
        "else",
    }
)


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def schema_hash(schema: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(schema).encode("utf-8")).hexdigest()


def schema_spec_for(name: str) -> OutputSchemaSpec:
    registry = _registry()
    try:
        return registry[name]
    except KeyError as exc:
        raise InputError(f"unknown output schema: {name}") from exc


def normalize_schema_for_provider(
    spec: OutputSchemaSpec,
    *,
    provider_kind: str,
) -> dict[str, Any]:
    if provider_kind not in _PROVIDER_TARGETS:
        raise InputError(f"unknown provider schema target: {provider_kind}")
    target = _PROVIDER_TARGETS[provider_kind]
    cloned = cast("dict[str, Any]", json.loads(canonical_json(spec.json_schema)))
    if target == "gemini":
        return _normalize_gemini_schema(cloned)
    if target == "openai_compat":
        cloned = _inline_json_schema_refs(cloned)
    strict_openai_subset = target in {
        "openai_chat",
        "openai_responses",
        "azure",
        "openai_compat",
    }
    normalized = _normalize_schema_node(cloned, strict_openai_subset=strict_openai_subset)
    if target == "openai_compat":
        return cast("dict[str, Any]", _expand_nullable_type_arrays(normalized))
    return normalized


def _inline_json_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    raw_defs = schema.get("$defs")
    defs = cast("dict[str, Any]", raw_defs) if isinstance(raw_defs, dict) else {}
    return cast("dict[str, Any]", _inline_json_schema_refs_node(schema, defs=defs, seen=()))


def _inline_json_schema_refs_node(
    value: Any,
    *,
    defs: dict[str, Any],
    seen: tuple[str, ...],
) -> Any:
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return [_inline_json_schema_refs_node(item, defs=defs, seen=seen) for item in items]
    if not isinstance(value, dict):
        return value

    value_map = cast("dict[str, Any]", value)
    ref = value_map.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        ref_name = ref.rsplit("/", 1)[-1]
        ref_schema = defs.get(ref_name)
        if isinstance(ref_schema, dict) and ref_name not in seen:
            merged = {
                **cast("dict[str, Any]", ref_schema),
                **{key: child for key, child in value_map.items() if key != "$ref"},
            }
            return _inline_json_schema_refs_node(
                merged,
                defs=defs,
                seen=(*seen, ref_name),
            )

    return {
        key: _inline_json_schema_refs_node(child, defs=defs, seen=seen)
        for key, child in value_map.items()
        if key != "$defs"
    }


def structured_request_kwargs(
    *,
    schema_name: str,
    provider_class: str,
    mode: EnforcementMode,
) -> dict[str, Any]:
    if mode not in _STRUCTURED_RESPONSE_FORMATS:
        allowed = ", ".join(sorted(_STRUCTURED_RESPONSE_FORMATS))
        raise InputError(f"structured output mode must be one of {allowed}, got {mode!r}")
    spec = schema_spec_for(schema_name)
    provider_kind = _provider_schema_target(provider_class)
    normalized_schema = normalize_schema_for_provider(spec, provider_kind=provider_kind)
    return {
        "response_format": _STRUCTURED_RESPONSE_FORMATS[mode],
        "output_schema_id": spec.schema_id,
        "output_schema_version": spec.schema_version,
        "output_schema": normalized_schema,
        "output_schema_hash": spec.schema_hash,
        "normalized_output_schema_hash": schema_hash(normalized_schema),
        "enforcement_mode": mode,
    }


def _provider_schema_target(provider_class: str) -> str:
    try:
        return _PROVIDER_TARGETS[provider_class]
    except KeyError as exc:
        raise InputError(f"unknown provider schema target: {provider_class}") from exc


def _normalize_schema_node(value: Any, *, strict_openai_subset: bool) -> Any:
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return [
            _normalize_schema_node(item, strict_openai_subset=strict_openai_subset)
            for item in items
        ]
    if not isinstance(value, dict):
        return value

    value_map = cast("dict[str, Any]", value)
    normalized: dict[str, Any] = {}
    for key, child in value_map.items():
        if key in _UNSUPPORTED_OR_RISKY_SCHEMA_KEYS:
            continue
        normalized[key] = _normalize_schema_node(
            child,
            strict_openai_subset=strict_openai_subset,
        )

    if strict_openai_subset:
        collapsed_nullable = _collapse_nullable_any_of(normalized)
        if collapsed_nullable is not None:
            normalized = collapsed_nullable

    if normalized.get("type") == "object" and "properties" in normalized:
        normalized.setdefault("additionalProperties", False)
        properties = normalized.get("properties")
        if strict_openai_subset and isinstance(properties, dict):
            normalized["required"] = list(cast("dict[str, Any]", properties))
    return normalized


def _collapse_nullable_any_of(schema: dict[str, Any]) -> dict[str, Any] | None:
    raw_any_of = schema.get("anyOf")
    if not isinstance(raw_any_of, list):
        return None
    any_of_items = cast("list[Any]", raw_any_of)
    if len(any_of_items) != 2:
        return None

    null_schema: dict[str, Any] | None = None
    value_schema: dict[str, Any] | None = None
    for item in any_of_items:
        if not isinstance(item, dict):
            return None
        item_map = cast("dict[str, Any]", item)
        if item_map.get("type") == "null":
            null_schema = item_map
        else:
            value_schema = item_map
    if null_schema is None or value_schema is None:
        return None

    value_type = value_schema.get("type")
    if not isinstance(value_type, str):
        return None

    collapsed = {key: child for key, child in schema.items() if key != "anyOf"}
    collapsed.update(value_schema)
    collapsed["type"] = [value_type, "null"]
    return collapsed


def _expand_nullable_type_arrays(value: Any) -> Any:
    if isinstance(value, list):
        return [_expand_nullable_type_arrays(item) for item in cast("list[Any]", value)]
    if not isinstance(value, dict):
        return value

    value_map = {
        key: _expand_nullable_type_arrays(child)
        for key, child in cast("dict[str, Any]", value).items()
    }
    type_value = value_map.get("type")
    if not isinstance(type_value, list):
        return value_map

    type_items = [item for item in cast("list[Any]", type_value) if isinstance(item, str)]
    non_null_types = [item for item in type_items if item != "null"]
    if len(non_null_types) != 1 or len(type_items) == len(non_null_types):
        return value_map

    value_schema = {key: child for key, child in value_map.items() if key != "type"}
    value_schema["type"] = non_null_types[0]
    return {
        "anyOf": [
            value_schema,
            {"type": "null"},
        ]
    }


_GEMINI_TYPE_MAP = {
    "object": "OBJECT",
    "array": "ARRAY",
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
}

_GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "$defs",
        "additionalProperties",
        "anyOf",
        *_UNSUPPORTED_OR_RISKY_SCHEMA_KEYS,
    }
)


def _normalize_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    raw_defs = schema.get("$defs")
    defs = cast("dict[str, Any]", raw_defs) if isinstance(raw_defs, dict) else {}
    return cast("dict[str, Any]", _normalize_gemini_schema_node(schema, defs=defs))


def _normalize_gemini_schema_node(value: Any, *, defs: dict[str, Any]) -> Any:
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return [_normalize_gemini_schema_node(item, defs=defs) for item in items]
    if not isinstance(value, dict):
        return value

    value_map = cast("dict[str, Any]", value)
    ref = value_map.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        ref_name = ref.rsplit("/", 1)[-1]
        ref_schema = defs.get(ref_name)
        if isinstance(ref_schema, dict):
            merged = {
                **cast("dict[str, Any]", ref_schema),
                **{key: child for key, child in value_map.items() if key != "$ref"},
            }
            return _normalize_gemini_schema_node(merged, defs=defs)

    collapsed_nullable = _collapse_nullable_any_of(value_map)
    if collapsed_nullable is not None:
        value_map = collapsed_nullable

    normalized: dict[str, Any] = {}
    for key, child in value_map.items():
        if key in _GEMINI_UNSUPPORTED_SCHEMA_KEYS:
            continue
        normalized[key] = _normalize_gemini_schema_node(child, defs=defs)

    type_value = normalized.get("type")
    if isinstance(type_value, str):
        normalized["type"] = _GEMINI_TYPE_MAP.get(type_value, type_value)
    elif isinstance(type_value, list):
        type_items = [item for item in cast("list[Any]", type_value) if isinstance(item, str)]
        non_null_types = [item for item in type_items if item != "null"]
        if len(non_null_types) == 1 and len(type_items) != len(non_null_types):
            normalized["type"] = _GEMINI_TYPE_MAP.get(non_null_types[0], non_null_types[0])
            normalized["nullable"] = True
    return normalized


def _schema_from_model(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()


def _make_spec(
    name: str,
    version: str,
    model: type[BaseModel],
) -> OutputSchemaSpec:
    json_schema = _schema_from_model(model)
    return OutputSchemaSpec(
        schema_id=name,
        schema_version=version,
        json_schema=json_schema,
        schema_hash=schema_hash(json_schema),
        pydantic_model=model,
    )


def _build_registry() -> dict[str, OutputSchemaSpec]:
    from ahadiff.claims.schema import (
        ClaimCandidate,  # noqa: TC001 - Pydantic needs this at runtime.
    )
    from ahadiff.lesson.schemas import LessonCompact, LessonFull, LessonHint
    from ahadiff.quiz.schemas import QuizSet

    class ClaimCandidatesEnvelope(BaseModel):
        model_config = ConfigDict(extra="forbid")

        claims: list[ClaimCandidate]

    class MisconceptionCardOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")

        concept: str
        misconception: str
        correction: str
        evidence_ref: str
        severity: str
        safety_tags: list[str]

    class MisconceptionCardsEnvelope(BaseModel):
        model_config = ConfigDict(extra="forbid")

        cards: list[MisconceptionCardOutput]

    specs = [
        _make_spec("claim_candidates", "1", ClaimCandidatesEnvelope),
        _make_spec("lesson_full", "1", LessonFull),
        _make_spec("lesson_hint", "1", LessonHint),
        _make_spec("lesson_compact", "1", LessonCompact),
        _make_spec("quiz_generate", "1", QuizSet),
        _make_spec("quiz_misconception_card", "1", MisconceptionCardsEnvelope),
    ]
    return {f"{spec.schema_id}.v{spec.schema_version}": spec for spec in specs}


_registry_cache: dict[str, OutputSchemaSpec] | None = None


def _registry() -> dict[str, OutputSchemaSpec]:
    global _registry_cache  # noqa: PLW0603
    if _registry_cache is None:
        _registry_cache = _build_registry()
    return _registry_cache


__all__ = [
    "OutputSchemaSpec",
    "ProviderSchemaTarget",
    "canonical_json",
    "normalize_schema_for_provider",
    "schema_hash",
    "schema_spec_for",
    "structured_request_kwargs",
]
