from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from ahadiff.contracts import PrivacyMode, ProviderConfig, compute_runtime_eval_bundle_version
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.i18n import prompt_language_instruction
from ahadiff.llm import ProviderRequest, make_provider
from ahadiff.safety.ignore import AllowlistPolicy
from ahadiff.safety.redact import redaction_pipeline

from .schemas import LessonCompact, LessonFull, LessonHint, parse_lesson_payload

if TYPE_CHECKING:
    import httpx

    from ahadiff.core.config import SecurityConfig

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
    )
    parsed = parse_lesson_payload(payload, schema=LessonFull)
    return cast("LessonFull", parsed)


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
    )
    parsed = parse_lesson_payload(payload, schema=LessonHint)
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
    )
    parsed = parse_lesson_payload(payload, schema=LessonCompact)
    return cast("LessonCompact", parsed)


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
) -> LessonArtifactPaths:
    bundle = load_redacted_run_bundle(
        run_id=run_id,
        run_path=run_path,
        workspace_root=workspace_root,
    )
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
    )
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
    )
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
        budget_kwargs["output_token_budget"] = output_token_budget
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
    try:
        response = provider.generate(
            ProviderRequest(
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
                response_format="json",
                max_output_tokens=provider_config.max_output_tokens
                or (4000 if variant == "full" else 1800),
                thinking_level=provider_config.thinking_level,
            )
        )
    finally:
        provider.close()
    return response.content


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
