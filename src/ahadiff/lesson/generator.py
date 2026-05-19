from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from ahadiff.contracts import PrivacyMode, ProviderConfig, compute_runtime_eval_bundle_version
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.i18n import prompt_language_instruction
from ahadiff.llm import (
    DEFAULT_OUTPUT_TOKEN_BUDGET,
    ProviderRequest,
    generate_with_validation_retry,
    make_provider,
)
from ahadiff.llm.structured import schema_spec_for, structured_request_kwargs
from ahadiff.safety.ignore import AllowlistPolicy
from ahadiff.safety.redact import redaction_pipeline

from .schemas import (
    LessonCompact,
    LessonFull,
    LessonHint,
    extract_json_object_candidates,
    parse_lesson_payload,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from ahadiff.core.config import SecurityConfig
    from ahadiff.llm.schemas import EnforcementMode

LessonVariant = Literal["full", "hint", "compact"]
_VALID_PRIVACY_MODES = frozenset({"strict_local", "redacted_remote", "explicit_remote"})
_PROMPT_FILENAMES: dict[LessonVariant, str] = {
    "full": "lesson_generate.md",
    "hint": "lesson_hint.md",
    "compact": "lesson_compact.md",
}
_PROMPT_NAMES: dict[LessonVariant, str] = {
    "full": "lesson.generate",
    "hint": "lesson.hint",
    "compact": "lesson.compact",
}
_VARIANT_TITLES: dict[LessonVariant, str] = {
    "full": "Full lesson",
    "hint": "Hint lesson",
    "compact": "Compact lesson",
}
_VARIANT_OUTPUT_CAPS: dict[LessonVariant, int] = {
    "full": 24_000,
    "hint": 3000,
    "compact": 2500,
}
_VARIANT_SCHEMA_NAMES: dict[LessonVariant, str] = {
    "full": "lesson_full.v1",
    "hint": "lesson_hint.v1",
    "compact": "lesson_compact.v1",
}
_VARIANT_SCHEMAS: dict[
    LessonVariant,
    type[LessonFull] | type[LessonHint] | type[LessonCompact],
] = {
    "full": LessonFull,
    "hint": LessonHint,
    "compact": LessonCompact,
}


class _BudgetKwargs(TypedDict, total=False):
    input_token_budget: int
    output_token_budget: int


@dataclass(frozen=True)
class RedactedRunBundle:
    run_id: str
    run_path: Path
    workspace_root: Path
    metadata: dict[str, Any]
    patch_text: str
    line_map_text: str
    symbols_text: str
    claims_text: str
    privacy_mode: PrivacyMode


@dataclass(frozen=True)
class LessonArtifactPaths:
    lesson_dir: Path
    full_path: Path
    hint_path: Path
    compact_path: Path
    misconception_path: Path
    not_proven_path: Path


def load_redacted_run_bundle(
    *,
    run_id: str,
    run_path: Path,
    workspace_root: Path,
) -> RedactedRunBundle:
    metadata = _load_run_json(run_path / "metadata.json")
    claims_text = _read_required_text(run_path / "claims.jsonl")
    return RedactedRunBundle(
        run_id=run_id,
        run_path=run_path,
        workspace_root=workspace_root,
        metadata=metadata,
        patch_text=_read_required_text(run_path / "patch.diff"),
        line_map_text=_read_required_text(run_path / "line_map.json"),
        symbols_text=_read_required_text(run_path / "symbols.json"),
        claims_text=claims_text,
        privacy_mode=_privacy_mode_from_metadata(metadata),
    )


def generate_lesson(
    *,
    bundle: RedactedRunBundle,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    output_lang: str = "en",
    client: httpx.Client | None = None,
    request_timeout_seconds: int = 30,
    max_concurrent: int = 3,
    qps_limit: int = 3,
    retry_attempts: int = 3,
    privacy_mode: PrivacyMode | None = None,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
    output_token_cap: int | None = None,
    structured_output_mode: EnforcementMode = "json_object",
    structured_validation_retries: int = 0,
) -> LessonFull:
    payload = _generate_variant_payload(
        variant="full",
        bundle=bundle,
        provider_config=provider_config,
        api_key=api_key,
        security_config=security_config,
        output_lang=output_lang,
        client=client,
        request_timeout_seconds=request_timeout_seconds,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        privacy_mode=privacy_mode,
        input_token_budget=input_token_budget,
        output_token_budget=output_token_budget,
        output_token_cap=output_token_cap,
        structured_output_mode=structured_output_mode,
        structured_validation_retries=structured_validation_retries,
    )
    parsed = _parse_lesson_payload_with_fallbacks(payload, schema=LessonFull, bundle=bundle)
    lesson = cast("LessonFull", parsed)
    if not lesson.walkthrough_tldr.strip():
        lesson = lesson.model_copy(update={"walkthrough_tldr": lesson.tl_dr})
    return lesson


def generate_hint(
    *,
    bundle: RedactedRunBundle,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    output_lang: str = "en",
    client: httpx.Client | None = None,
    request_timeout_seconds: int = 30,
    max_concurrent: int = 3,
    qps_limit: int = 3,
    retry_attempts: int = 3,
    privacy_mode: PrivacyMode | None = None,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
    output_token_cap: int | None = None,
    structured_output_mode: EnforcementMode = "json_object",
    structured_validation_retries: int = 0,
) -> LessonHint:
    payload = _generate_variant_payload(
        variant="hint",
        bundle=bundle,
        provider_config=provider_config,
        api_key=api_key,
        security_config=security_config,
        output_lang=output_lang,
        client=client,
        request_timeout_seconds=request_timeout_seconds,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        privacy_mode=privacy_mode,
        input_token_budget=input_token_budget,
        output_token_budget=output_token_budget,
        output_token_cap=output_token_cap,
        structured_output_mode=structured_output_mode,
        structured_validation_retries=structured_validation_retries,
    )
    parsed = _parse_lesson_payload_with_fallbacks(payload, schema=LessonHint, bundle=bundle)
    return cast("LessonHint", parsed)


def generate_compact(
    *,
    bundle: RedactedRunBundle,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    output_lang: str = "en",
    client: httpx.Client | None = None,
    request_timeout_seconds: int = 30,
    max_concurrent: int = 3,
    qps_limit: int = 3,
    retry_attempts: int = 3,
    privacy_mode: PrivacyMode | None = None,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
    output_token_cap: int | None = None,
    structured_output_mode: EnforcementMode = "json_object",
    structured_validation_retries: int = 0,
) -> LessonCompact:
    payload = _generate_variant_payload(
        variant="compact",
        bundle=bundle,
        provider_config=provider_config,
        api_key=api_key,
        security_config=security_config,
        output_lang=output_lang,
        client=client,
        request_timeout_seconds=request_timeout_seconds,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        privacy_mode=privacy_mode,
        input_token_budget=input_token_budget,
        output_token_budget=output_token_budget,
        output_token_cap=output_token_cap,
        structured_output_mode=structured_output_mode,
        structured_validation_retries=structured_validation_retries,
    )
    parsed = _parse_lesson_payload_with_fallbacks(payload, schema=LessonCompact, bundle=bundle)
    return cast("LessonCompact", parsed)


def _parse_lesson_payload_with_fallbacks(
    payload: str,
    *,
    schema: type[LessonFull] | type[LessonHint] | type[LessonCompact],
    bundle: RedactedRunBundle,
) -> LessonFull | LessonHint | LessonCompact:
    try:
        return cast(
            "LessonFull | LessonHint | LessonCompact",
            parse_lesson_payload(payload, schema=schema),
        )
    except Exception as original_exc:
        last_error: Exception = original_exc

    fallback_sources = _fallback_sources_from_claims_text(bundle.claims_text)
    fallback_claims = _fallback_claim_texts_from_claims_text(bundle.claims_text)
    fallback_concepts = _fallback_concepts_from_claims_text(bundle.claims_text)
    for candidate in extract_json_object_candidates(payload):
        repaired = _repair_lesson_candidate(
            candidate,
            schema=schema,
            fallback_sources=fallback_sources,
            fallback_claims=fallback_claims,
            fallback_concepts=fallback_concepts,
        )
        try:
            return schema.model_validate(repaired)
        except Exception as exc:
            last_error = exc
    raise last_error


def _repair_lesson_candidate(
    candidate: Mapping[str, Any],
    *,
    schema: type[LessonFull] | type[LessonHint] | type[LessonCompact],
    fallback_sources: list[str],
    fallback_claims: list[str],
    fallback_concepts: list[str],
) -> dict[str, Any]:
    repaired: dict[str, Any] = dict(candidate)
    sections = _lesson_sections(candidate)
    if "sources" in schema.model_fields and not _lesson_list(repaired.get("sources")):
        repaired["sources"] = fallback_sources
    if schema is LessonFull:
        _ensure_walkthrough_tldr(repaired)
        _ensure_lesson_list(
            repaired,
            "what_changed",
            sections=sections,
            aliases=("what_changed", "what changed", "changes", "changed", "summary"),
            fallback=fallback_claims,
        )
        _ensure_lesson_list(
            repaired,
            "why",
            sections=sections,
            aliases=("why", "why it matters", "rationale", "reason"),
            fallback=["The verified claims define the learning boundary for this diff."],
        )
        _ensure_lesson_list(
            repaired,
            "walkthrough",
            sections=sections,
            aliases=("walkthrough", "code walkthrough", "implementation", "details"),
            fallback=["Review the cited source hunks in order and keep claims tied to evidence."],
        )
        _ensure_lesson_list(
            repaired,
            "claims",
            sections=sections,
            aliases=("claims", "verified claims", "evidence claims"),
            fallback=fallback_claims,
        )
        _ensure_lesson_list(
            repaired,
            "concepts",
            sections=sections,
            aliases=("concepts", "key concepts", "learning concepts"),
            fallback=fallback_concepts,
        )
        _ensure_lesson_list(
            repaired,
            "not_proven",
            sections=sections,
            aliases=("not_proven", "not proven", "limitations", "gaps"),
            fallback=["No high-risk unproven claims were shipped in this lesson."],
        )
        if not _lesson_list(repaired.get("misconceptions")):
            repaired["misconceptions"] = []
        if not _lesson_list(repaired.get("quiz")):
            repaired["quiz"] = _fallback_full_lesson_quiz(repaired)
    elif schema is LessonHint:
        _ensure_lesson_list(
            repaired,
            "key_points",
            sections=sections,
            aliases=("key_points", "key points", "points", "summary"),
            fallback=fallback_claims,
        )
        _ensure_lesson_list(
            repaired,
            "claims",
            sections=sections,
            aliases=("claims", "verified claims"),
            fallback=fallback_claims,
        )
        if not _lesson_list(repaired.get("watch_fors")):
            repaired["watch_fors"] = []
    elif schema is LessonCompact:
        headline = str(repaired.get("headline") or repaired.get("tl_dr") or "").strip()
        if headline:
            repaired["headline"] = headline
        _ensure_lesson_list(
            repaired,
            "summary",
            sections=sections,
            aliases=("summary", "what changed", "changes", "key points"),
            fallback=fallback_claims,
        )
        _ensure_lesson_list(
            repaired,
            "concepts",
            sections=sections,
            aliases=("concepts", "key concepts"),
            fallback=fallback_concepts,
        )
    return {key: value for key, value in repaired.items() if key in schema.model_fields}


def _ensure_walkthrough_tldr(repaired: dict[str, Any]) -> None:
    walkthrough_tldr = str(repaired.get("walkthrough_tldr") or "").strip()
    if walkthrough_tldr:
        repaired["walkthrough_tldr"] = walkthrough_tldr
        return
    tl_dr = str(repaired.get("tl_dr") or "").strip()
    if tl_dr:
        repaired["walkthrough_tldr"] = tl_dr


def _lesson_sections(candidate: Mapping[str, Any]) -> dict[str, list[str]]:
    raw_sections = candidate.get("sections")
    sections: dict[str, list[str]] = {}
    if isinstance(raw_sections, Mapping):
        for key, value in cast("Mapping[object, object]", raw_sections).items():
            values = _lesson_list(value)
            if values:
                sections[_lesson_key(str(key))] = values
    elif isinstance(raw_sections, list):
        for raw_item in cast("list[object]", raw_sections):
            if not isinstance(raw_item, Mapping):
                continue
            item = cast("Mapping[str, object]", raw_item)
            title = _first_text_value(item, ("title", "heading", "name", "key", "section"))
            if not title:
                continue
            values = _lesson_list(
                item.get("items")
                or item.get("bullets")
                or item.get("points")
                or item.get("content")
                or item.get("text")
            )
            if values:
                sections[_lesson_key(title)] = values
    return sections


def _ensure_lesson_list(
    repaired: dict[str, Any],
    field_name: str,
    *,
    sections: Mapping[str, list[str]],
    aliases: tuple[str, ...],
    fallback: list[str],
) -> None:
    existing = _lesson_list(repaired.get(field_name))
    if existing:
        repaired[field_name] = existing
        return
    for alias in aliases:
        values = _lesson_list(repaired.get(alias))
        if values:
            repaired[field_name] = values
            return
        values = sections.get(_lesson_key(alias))
        if values:
            repaired[field_name] = values
            return
    repaired[field_name] = fallback


def _lesson_list(value: object) -> list[str]:
    if isinstance(value, str):
        line = value.strip()
        return [line] if line else []
    if not isinstance(value, list | tuple):
        return []
    values: list[str] = []
    for item in cast("list[object] | tuple[object, ...]", value):
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, Mapping):
            text = _first_text_value(
                cast("Mapping[str, object]", item),
                ("text", "content", "summary", "claim", "question"),
            )
        else:
            text = str(item).strip()
        if text:
            values.append(text)
    return values


def _first_text_value(payload: Mapping[str, object], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _lesson_key(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _fallback_full_lesson_quiz(candidate: Mapping[str, Any]) -> list[str]:
    claims = candidate.get("claims")
    if isinstance(claims, list):
        for item in cast("list[object]", claims):
            claim = str(item).strip()
            if claim:
                return [f"What source evidence supports this claim: {claim}"]
    return ["Which source hunk supports the main lesson claim?"]


def _fallback_claim_texts_from_claims_text(claims_text: str) -> list[str]:
    claims: list[str] = []
    for line in claims_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload: object = safe_json_loads(stripped)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(payload, Mapping):
            continue
        payload_map = cast("Mapping[str, object]", payload)
        text = payload_map.get("text")
        if isinstance(text, str) and text.strip():
            claims.append(text.strip())
    return list(dict.fromkeys(claims)) or ["Review the verified claims for this diff."]


def _fallback_concepts_from_claims_text(claims_text: str) -> list[str]:
    concepts: list[str] = []
    for line in claims_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload: object = safe_json_loads(stripped)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(payload, Mapping):
            continue
        payload_map = cast("Mapping[str, object]", payload)
        raw_symbols = payload_map.get("symbols")
        if isinstance(raw_symbols, list):
            for item in cast("list[object]", raw_symbols):
                if isinstance(item, str) and item.strip():
                    concepts.append(item.strip())
    return list(dict.fromkeys(concepts)) or ["evidence-bound diff learning"]


def _fallback_sources_from_claims_text(claims_text: str) -> list[str]:
    refs: list[str] = []
    for line in claims_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload: object = safe_json_loads(stripped)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        payload_map = cast("Mapping[str, object]", payload)
        source_hunks = payload_map.get("source_hunks")
        if not isinstance(source_hunks, list):
            continue
        for hunk in cast("list[object]", source_hunks):
            if not isinstance(hunk, dict):
                continue
            ref = _source_hunk_ref(cast("Mapping[str, object]", hunk))
            if ref:
                refs.append(ref)
    return list(dict.fromkeys(refs)) or ["claims.jsonl"]


def _source_hunk_ref(hunk: Mapping[str, object]) -> str | None:
    path = str(hunk.get("file", "")).strip()
    side = str(hunk.get("side", "new")).strip() or "new"
    start = _source_hunk_int(hunk.get("start"))
    end = _source_hunk_int(hunk.get("end"))
    if start is None or end is None:
        return None
    if not path:
        return None
    return f"{path}:{side}:{start}-{end}"


def _source_hunk_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | str | bytes | bytearray):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def generate_lessons_from_run(
    *,
    run_id: str,
    run_path: Path,
    workspace_root: Path,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    output_lang: str = "en",
    overwrite: bool = False,
    client: httpx.Client | None = None,
    request_timeout_seconds: int = 30,
    max_concurrent: int = 3,
    qps_limit: int = 3,
    retry_attempts: int = 3,
    privacy_mode: PrivacyMode | None = None,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
    lesson_output_token_caps: Mapping[LessonVariant, int] | None = None,
    on_sub_progress: Callable[[str], None] | None = None,
    structured_output_mode: EnforcementMode = "json_object",
    structured_validation_retries: int = 0,
) -> LessonArtifactPaths:
    bundle = load_redacted_run_bundle(
        run_id=run_id,
        run_path=run_path,
        workspace_root=workspace_root,
    )
    if on_sub_progress is not None:
        on_sub_progress("Generating full lesson (1/3)")
    full = generate_lesson(
        bundle=bundle,
        provider_config=provider_config,
        api_key=api_key,
        security_config=security_config,
        output_lang=output_lang,
        client=client,
        request_timeout_seconds=request_timeout_seconds,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        privacy_mode=privacy_mode,
        input_token_budget=input_token_budget,
        output_token_budget=output_token_budget,
        output_token_cap=_output_token_cap_for_variant("full", lesson_output_token_caps),
        structured_output_mode=structured_output_mode,
        structured_validation_retries=structured_validation_retries,
    )
    if on_sub_progress is not None:
        on_sub_progress("Generating hint lesson (2/3)")
    hint = generate_hint(
        bundle=bundle,
        provider_config=provider_config,
        api_key=api_key,
        security_config=security_config,
        output_lang=output_lang,
        client=client,
        request_timeout_seconds=request_timeout_seconds,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        privacy_mode=privacy_mode,
        input_token_budget=input_token_budget,
        output_token_budget=output_token_budget,
        output_token_cap=_output_token_cap_for_variant("hint", lesson_output_token_caps),
        structured_output_mode=structured_output_mode,
        structured_validation_retries=structured_validation_retries,
    )
    if on_sub_progress is not None:
        on_sub_progress("Generating compact lesson (3/3)")
    compact = generate_compact(
        bundle=bundle,
        provider_config=provider_config,
        api_key=api_key,
        security_config=security_config,
        output_lang=output_lang,
        client=client,
        request_timeout_seconds=request_timeout_seconds,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        privacy_mode=privacy_mode,
        input_token_budget=input_token_budget,
        output_token_budget=output_token_budget,
        output_token_cap=_output_token_cap_for_variant("compact", lesson_output_token_caps),
        structured_output_mode=structured_output_mode,
        structured_validation_retries=structured_validation_retries,
    )
    return write_lesson_artifacts(
        run_path=run_path,
        full=full,
        hint=hint,
        compact=compact,
        overwrite=overwrite,
    )


def write_lesson_artifacts(
    *,
    run_path: Path,
    full: LessonFull,
    hint: LessonHint,
    compact: LessonCompact,
    overwrite: bool = False,
) -> LessonArtifactPaths:
    lesson_dir = run_path / "lesson"
    paths = LessonArtifactPaths(
        lesson_dir=lesson_dir,
        full_path=lesson_dir / "lesson.full.md",
        hint_path=lesson_dir / "lesson.hint.md",
        compact_path=lesson_dir / "lesson.compact.md",
        misconception_path=lesson_dir / "misconception.md",
        not_proven_path=lesson_dir / "not_proven.md",
    )
    artifact_texts = {
        paths.full_path: full.render_markdown(),
        paths.hint_path: hint.render_markdown(),
        paths.compact_path: compact.render_markdown(),
        paths.misconception_path: full.render_misconceptions_markdown(),
        paths.not_proven_path: full.render_not_proven_markdown(),
    }
    _validate_lesson_artifact_paths(artifact_texts, overwrite=overwrite)
    staging_root = _temporary_work_dir(run_path, prefix=".lesson-stage.")
    backup_root = _temporary_work_dir(run_path, prefix=".lesson-backup.")
    try:
        staged_lesson_dir = _stage_lesson_artifacts(
            artifact_texts=artifact_texts,
            lesson_dir=lesson_dir,
            staging_root=staging_root,
        )
        _commit_lesson_artifacts(
            lesson_dir=lesson_dir,
            staged_lesson_dir=staged_lesson_dir,
            backup_root=backup_root,
        )
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
        shutil.rmtree(backup_root, ignore_errors=True)
    return paths


def build_lesson_payload(
    *,
    prompt_text: str,
    bundle: RedactedRunBundle,
    variant: LessonVariant,
    output_lang: str = "en",
) -> str:
    prompt_header = f"## Requested Output\nTarget: {_VARIANT_TITLES[variant]}"
    metadata_payload = {
        "run_id": bundle.metadata["run_id"],
        "source_kind": bundle.metadata["source_kind"],
        "source_ref": bundle.metadata["source_ref"],
        "capability_level": bundle.metadata["capability_level"],
        "degraded_flags": bundle.metadata.get("degraded_flags", {}),
        "learnability": bundle.metadata.get("learnability", {}),
    }
    return "\n\n".join(
        (
            prompt_text.strip(),
            prompt_header,
            "## Output language\n" + prompt_language_instruction(output_lang),
            "## Run metadata\n```json\n"
            + json.dumps(metadata_payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n```",
            "## claims.jsonl\n```json\n" + bundle.claims_text.rstrip() + "\n```",
            "## patch.diff\n```diff\n" + bundle.patch_text.rstrip() + "\n```",
            "## line_map.json\n```json\n" + bundle.line_map_text.rstrip() + "\n```",
            "## symbols.json\n```json\n" + bundle.symbols_text.rstrip() + "\n```",
        )
    )


def load_lesson_prompt(variant: LessonVariant) -> str:
    filename = _PROMPT_FILENAMES[variant]
    prompt_path = Path(__file__).resolve().parents[3] / "prompts" / filename
    if prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8")
    try:
        package_prompt = files("ahadiff").joinpath("prompts", filename)
        if package_prompt.is_file():
            return package_prompt.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass
    raise InputError(f"lesson prompt resource is missing: {filename}")


def _generate_variant_payload(
    *,
    variant: LessonVariant,
    bundle: RedactedRunBundle,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    output_lang: str,
    client: httpx.Client | None,
    request_timeout_seconds: int,
    max_concurrent: int,
    qps_limit: int,
    retry_attempts: int,
    privacy_mode: PrivacyMode | None,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
    output_token_cap: int | None = None,
    structured_output_mode: EnforcementMode = "json_object",
    structured_validation_retries: int = 0,
) -> str:
    prompt_text = load_lesson_prompt(variant)
    payload_text = build_lesson_payload(
        prompt_text=prompt_text,
        bundle=bundle,
        variant=variant,
        output_lang=output_lang,
    )
    prompt_fingerprint = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:12]
    resolved_privacy_mode = privacy_mode or bundle.privacy_mode
    redacted_payload_text = None
    findings = ()
    if resolved_privacy_mode == "redacted_remote":
        redaction = redaction_pipeline(
            payload_text,
            policy=AllowlistPolicy(
                allow_exact=security_config.allow_exact,
                allow_paths=security_config.allow_paths,
                suppress_rules=security_config.suppress_rules,
            ),
        )
        redacted_payload_text = redaction.redacted_text
        findings = redaction.findings
    budget_kwargs: _BudgetKwargs = {}
    if input_token_budget is not None:
        budget_kwargs["input_token_budget"] = input_token_budget
    if output_token_budget is not None:
        budget_kwargs["output_token_budget"] = _positive_output_token_value(
            output_token_budget,
            DEFAULT_OUTPUT_TOKEN_BUDGET,
        )
    provider = make_provider(
        provider_config,
        api_key=api_key,
        security_config=security_config,
        workspace_root=bundle.workspace_root,
        client=client,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        request_timeout_seconds=request_timeout_seconds,
        execution_origin=f"lesson_{variant}",
        **budget_kwargs,
    )
    schema_name = _VARIANT_SCHEMA_NAMES[variant]
    schema_spec = schema_spec_for(schema_name)
    schema = _VARIANT_SCHEMAS[variant]
    request = ProviderRequest(
        prompt_name=_PROMPT_NAMES[variant],
        prompt_fingerprint=prompt_fingerprint,
        prompt_version=prompt_fingerprint,
        eval_bundle_version=compute_runtime_eval_bundle_version(),
        model=provider_config.model_name,
        payload_text=payload_text,
        diff_content=bundle.patch_text,
        source_ref=str(bundle.metadata["source_ref"]),
        output_lang=output_lang,
        privacy_mode=resolved_privacy_mode,
        redacted_payload_text=redacted_payload_text,
        findings=findings,
        max_output_tokens=_resolve_request_max_output_tokens(
            provider_config=provider_config,
            output_token_budget=output_token_budget,
            output_token_cap=(
                output_token_cap if output_token_cap is not None else _VARIANT_OUTPUT_CAPS[variant]
            ),
            default_output_token_cap=_VARIANT_OUTPUT_CAPS[variant],
        ),
        thinking_level=provider_config.thinking_level,
        **structured_request_kwargs(
            schema_name=schema_name,
            provider_class=provider_config.provider_class,
            mode=structured_output_mode,
        ),
    )

    def _validate(payload: str) -> str:
        parse_lesson_payload(payload, schema=schema)
        return payload

    def _fallback(payload: str) -> str:
        _parse_lesson_payload_with_fallbacks(payload, schema=schema, bundle=bundle)
        return payload

    try:
        result = generate_with_validation_retry(
            provider=provider,
            request=request,
            schema_spec=schema_spec,
            parse=_validate,
            fallback_parse=_fallback,
            max_validation_retries=structured_validation_retries,
        )
    finally:
        provider.close()
    return result.value


def _output_token_cap_for_variant(
    variant: LessonVariant,
    caps: Mapping[LessonVariant, int] | None,
) -> int:
    if caps is None:
        return _VARIANT_OUTPUT_CAPS[variant]
    return caps.get(variant, _VARIANT_OUTPUT_CAPS[variant])


def _resolve_request_max_output_tokens(
    *,
    provider_config: ProviderConfig,
    output_token_budget: int | None,
    output_token_cap: int,
    default_output_token_cap: int,
) -> int:
    output_budget = _positive_output_token_value(output_token_budget, DEFAULT_OUTPUT_TOKEN_BUDGET)
    cap = output_token_cap if output_token_cap > 0 else default_output_token_cap
    limits = [output_budget, cap]
    if provider_config.max_output_tokens and provider_config.max_output_tokens > 0:
        limits.append(provider_config.max_output_tokens)
    return min(limits)


def _positive_output_token_value(value: int | None, default: int) -> int:
    return value if value is not None and value > 0 else default


def _load_run_json(path: Path) -> dict[str, Any]:
    payload = safe_json_loads(_read_required_text(path))
    if not isinstance(payload, dict):
        raise InputError(f"run artifact must be a JSON object: {path}")
    return cast("dict[str, Any]", payload)


def _read_required_text(path: Path) -> str:
    if not path.exists():
        raise InputError(f"required run artifact is missing: {path}")
    return path.read_text(encoding="utf-8")


def _privacy_mode_from_metadata(metadata: dict[str, Any]) -> PrivacyMode:
    raw_value = metadata.get("privacy_mode", "strict_local")
    if raw_value not in _VALID_PRIVACY_MODES:
        raise InputError(f"unsupported run metadata privacy_mode: {raw_value!r}")
    return cast("PrivacyMode", raw_value)


def _atomic_write_text(path: Path, text: str) -> None:
    temp_path = _temporary_sibling_path(path)
    try:
        temp_path.write_text(text, encoding="utf-8")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _validate_lesson_artifact_paths(
    artifact_texts: dict[Path, str],
    *,
    overwrite: bool,
) -> None:
    if overwrite:
        return
    for path in artifact_texts:
        if path.exists():
            raise InputError(f"refusing to overwrite existing file: {path}")


def _stage_lesson_artifacts(
    *,
    artifact_texts: dict[Path, str],
    lesson_dir: Path,
    staging_root: Path,
) -> Path:
    staged_lesson_dir = staging_root / lesson_dir.name
    staged_lesson_dir.mkdir(parents=True, exist_ok=True)
    for target_path, text in artifact_texts.items():
        staged_path = staged_lesson_dir / target_path.name
        _atomic_write_text(staged_path, text)
    return staged_lesson_dir


def _commit_lesson_artifacts(
    *,
    lesson_dir: Path,
    staged_lesson_dir: Path,
    backup_root: Path,
) -> None:
    backup_dir = backup_root / lesson_dir.name
    try:
        if lesson_dir.exists():
            lesson_dir.replace(backup_dir)
        staged_lesson_dir.replace(lesson_dir)
    except Exception:
        if lesson_dir.exists():
            shutil.rmtree(lesson_dir, ignore_errors=True)
        if backup_dir.exists():
            backup_dir.replace(lesson_dir)
        raise


def _temporary_work_dir(run_path: Path, *, prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=run_path))


def _temporary_sibling_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".lesson.tmp",
        dir=path.parent,
    )
    os.close(fd)
    temp_path = Path(raw_path)
    temp_path.unlink()
    return temp_path


__all__ = [
    "build_lesson_payload",
    "generate_compact",
    "generate_hint",
    "generate_lesson",
    "generate_lessons_from_run",
    "LessonArtifactPaths",
    "load_lesson_prompt",
    "load_redacted_run_bundle",
    "RedactedRunBundle",
    "write_lesson_artifacts",
]
