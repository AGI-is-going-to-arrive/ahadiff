from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.contracts import compute_runtime_eval_bundle_version
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import atomic_write_state_text
from ahadiff.safety.ignore import resolve_safe_path_from_root

from .rubric import load_rubric

if TYPE_CHECKING:
    import httpx

    from ahadiff.contracts import PrivacyMode, ProviderConfig
    from ahadiff.core.config import SecurityConfig

SPEC_ALIGNMENT_ARTIFACT = "spec_alignment"
SPEC_ALIGNMENT_SCHEMA = "ahadiff.spec_alignment"
SPEC_ALIGNMENT_FILENAME = "spec_alignment.json"
_SEMANTIC_REVIEW_PROMPT_FILENAME = "spec_semantic_alignment.md"
_SEMANTIC_REVIEW_OUTPUT_TOKEN_CAP = 2_400
_MAX_SPEC_BYTES = 512 * 1024
_MAX_REQUIREMENTS = 100
_MAX_REQUIREMENT_CHARS = 500
_MAX_SEMANTIC_RATIONALE_CHARS = 600
_MAX_SEMANTIC_LIMITATIONS = 8
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_JSON_FENCE_RE = re.compile(
    r"```(?P<lang>[^\r\n`]*)\r?\n(?P<body>[\s\S]*?)```",
    re.IGNORECASE,
)
_SEMANTIC_CLASSIFICATIONS = frozenset({"implemented", "partial", "missing", "unknown", "violated"})
_STRONG_REQUIREMENT_WORDS = {
    "must",
    "required",
    "require",
    "shall",
    "forbid",
    "forbidden",
    "never",
    "禁止",
    "必须",
    "务必",
    "需要",
    "不得",
}
_MEDIUM_REQUIREMENT_WORDS = {
    "should",
    "support",
    "supports",
    "ensure",
    "保证",
    "支持",
    "应",
}


@dataclass(frozen=True)
class SpecSource:
    path: Path
    display_path: str
    text: str
    digest: str
    byte_count: int


@dataclass(frozen=True)
class SpecDimension:
    score: float
    reason: str
    applicable: bool


@dataclass(frozen=True)
class SemanticReviewProvider:
    provider: str
    model: str


def write_spec_alignment_artifact(
    *,
    run_path: Path,
    workspace_root: Path,
    spec_path: Path,
) -> dict[str, Any]:
    source = read_spec_source(workspace_root=workspace_root, spec_path=spec_path)
    requirements = _extract_requirements(source.text)
    claims = _load_claim_payloads(run_path / "claims.jsonl")
    patch_text = _read_optional_text(run_path / "patch.diff")
    scored = _classify_requirements(requirements, claims=claims, patch_text=patch_text)
    summary = {
        "implemented": sum(1 for item in scored if item["classification"] == "implemented"),
        "partial": sum(1 for item in scored if item["classification"] == "partial"),
        "missing": sum(1 for item in scored if item["classification"] == "missing"),
        "unknown": sum(1 for item in scored if item["classification"] == "unknown"),
    }
    score = _score_requirements(scored)
    confidence = _aggregate_confidence(scored)
    payload: dict[str, Any] = {
        "artifact": SPEC_ALIGNMENT_ARTIFACT,
        "schema": SPEC_ALIGNMENT_SCHEMA,
        "schema_version": 1,
        "applicability": "applicable",
        "status": "scored",
        "eval_bundle_version": compute_runtime_eval_bundle_version(),
        "rubric_version": load_rubric().rubric_version,
        "spec_source": {
            "path": source.display_path,
            "ref": source.display_path,
            "sha256": source.digest,
            "bytes": source.byte_count,
        },
        "spec_digest": source.digest,
        "requirements": scored,
        "summary": summary,
        "score": score,
        "max_score": 10.0,
        "confidence": confidence,
        "matcher": {
            "mode": "deterministic_structured",
            "claim_count": len(claims),
            "uses_code_anchors": True,
            "uses_patch_added_lines": True,
            "detects_forbidden_additions": True,
        },
        "known_limitations": [
            "Deterministic structured matcher; it does not execute code or call an LLM.",
            (
                "Evidence is limited to verified/weak claims, code anchors, "
                "and captured diff additions."
            ),
            "Requirement severity is inferred from wording and may need human review.",
        ],
    }
    atomic_write_state_text(
        run_path / SPEC_ALIGNMENT_FILENAME,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    return payload


def run_semantic_alignment_review_for_run(
    *,
    run_path: Path,
    workspace_root: Path,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    privacy_mode: PrivacyMode,
    output_lang: str,
    request_timeout_seconds: int,
    max_concurrent: int,
    qps_limit: int,
    retry_attempts: int,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Append an optional evidence-bound semantic review to spec_alignment.json.

    The deterministic matcher remains the artifact baseline. This function only
    adds a semantic reviewer signal and a conservative adjusted score when the
    caller explicitly opts in.
    """
    artifact_path = run_path / SPEC_ALIGNMENT_FILENAME
    try:
        artifact = _load_spec_artifact(artifact_path)
    except Exception as exc:
        raise InputError("semantic spec review requires a readable spec_alignment.json") from exc

    prompt_text = load_semantic_alignment_prompt()
    prompt_digest = _sha256_short(prompt_text)
    payload_text = build_semantic_alignment_payload(
        prompt_text=prompt_text,
        run_path=run_path,
        deterministic_artifact=artifact,
    )
    input_digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    redacted_payload_text = None
    findings = ()
    if privacy_mode == "redacted_remote":
        from ahadiff.safety.redact import AllowlistPolicy, redaction_pipeline

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

    try:
        from ahadiff.llm.cost import DEFAULT_INPUT_TOKEN_BUDGET, DEFAULT_OUTPUT_TOKEN_BUDGET
        from ahadiff.llm.provider import make_provider
        from ahadiff.llm.schemas import ProviderRequest

        with make_provider(
            provider_config,
            api_key=api_key,
            security_config=security_config,
            workspace_root=workspace_root,
            client=client,
            max_concurrent=max_concurrent,
            qps_limit=qps_limit,
            retry_attempts=retry_attempts,
            request_timeout_seconds=request_timeout_seconds,
            input_token_budget=input_token_budget or DEFAULT_INPUT_TOKEN_BUDGET,
            output_token_budget=output_token_budget or DEFAULT_OUTPUT_TOKEN_BUDGET,
            execution_origin="semantic_alignment_judge",
        ) as provider:
            response = provider.generate(
                ProviderRequest(
                    prompt_name="eval.semantic_alignment",
                    prompt_fingerprint=prompt_digest,
                    prompt_version=prompt_digest,
                    eval_bundle_version=str(
                        artifact.get("eval_bundle_version") or compute_runtime_eval_bundle_version()
                    ),
                    model=provider_config.model_name,
                    payload_text=payload_text,
                    diff_content=_semantic_diff_content(run_path),
                    source_ref=_semantic_source_ref(run_path),
                    output_lang=output_lang,
                    privacy_mode=privacy_mode,
                    redacted_payload_text=redacted_payload_text,
                    redaction_config="semantic_alignment",
                    response_format="json",
                    enforcement_mode="json_object",
                    max_output_tokens=_semantic_review_output_tokens(
                        provider_config=provider_config,
                        output_token_budget=output_token_budget,
                    ),
                    thinking_level=provider_config.thinking_level,
                    findings=findings,
                )
            )
        semantic_review = parse_semantic_alignment_output(
            response.content,
            deterministic_artifact=artifact,
            provider=SemanticReviewProvider(
                provider=provider_config.provider_class,
                model=response.model_id,
            ),
            prompt_digest=prompt_digest,
            input_digest=input_digest,
            usage={
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "finish_reason": response.finish_reason,
                "request_id": response.request_id,
            },
        )
    except Exception as exc:
        semantic_review = _semantic_degraded_review(
            provider=SemanticReviewProvider(
                provider=provider_config.provider_class,
                model=provider_config.model_name,
            ),
            prompt_digest=prompt_digest,
            input_digest=input_digest,
            reason=_semantic_degradation_reason(exc),
        )

    merged = merge_semantic_review_into_artifact(artifact, semantic_review)
    atomic_write_state_text(
        artifact_path,
        json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return merged


def mark_semantic_alignment_review_degraded(
    *,
    run_path: Path,
    provider_name: str,
    model_name: str,
    reason: str,
) -> dict[str, Any]:
    artifact_path = run_path / SPEC_ALIGNMENT_FILENAME
    artifact = _load_spec_artifact(artifact_path)
    review = _semantic_degraded_review(
        provider=SemanticReviewProvider(provider=provider_name, model=model_name),
        prompt_digest="unavailable",
        input_digest="unavailable",
        reason=reason,
    )
    merged = merge_semantic_review_into_artifact(artifact, review)
    atomic_write_state_text(
        artifact_path,
        json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return merged


def build_semantic_alignment_payload(
    *,
    prompt_text: str,
    run_path: Path,
    deterministic_artifact: dict[str, Any],
) -> str:
    review_input: dict[str, object] = {
        "spec_source": deterministic_artifact.get("spec_source"),
        "spec_digest": deterministic_artifact.get("spec_digest"),
        "deterministic_result": _deterministic_result_payload(deterministic_artifact),
        "requirements": _semantic_requirement_inputs(deterministic_artifact),
        "claim_evidence": _semantic_claim_inputs(run_path, deterministic_artifact),
        "patch_evidence": _semantic_patch_inputs(run_path, deterministic_artifact),
        "output_contract": {
            "requirements": [
                {
                    "id": "REQ-001",
                    "classification": "implemented|partial|missing|unknown|violated",
                    "confidence": 0.0,
                    "rationale": "short evidence-bound rationale",
                    "evidence_refs": [],
                }
            ],
            "limitations": ["optional limitation"],
        },
    }
    return "\n\n".join(
        (
            prompt_text.strip(),
            "## Semantic alignment review input\n```json\n"
            + json.dumps(review_input, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n```",
        )
    )


def load_semantic_alignment_prompt() -> str:
    from importlib.resources import files

    prompt_path = Path(__file__).resolve().parents[3] / "prompts" / _SEMANTIC_REVIEW_PROMPT_FILENAME
    if prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8")
    try:
        package_prompt = files("ahadiff").joinpath("prompts", _SEMANTIC_REVIEW_PROMPT_FILENAME)
        return package_prompt.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise InputError(f"missing prompt resource: {_SEMANTIC_REVIEW_PROMPT_FILENAME}") from exc


def parse_semantic_alignment_output(
    content: str,
    *,
    deterministic_artifact: dict[str, Any],
    provider: SemanticReviewProvider,
    prompt_digest: str,
    input_digest: str,
    usage: dict[str, object] | None = None,
) -> dict[str, Any]:
    payload = _load_semantic_json_object(content)
    raw_requirements = payload.get("requirements")
    if not isinstance(raw_requirements, list):
        raise InputError("semantic alignment output is missing requirements list")
    deterministic_requirements = _deterministic_requirements_by_id(deterministic_artifact)
    reviewed: list[dict[str, Any]] = []
    seen: set[str] = set()
    degraded = False
    degradation_reasons: list[str] = []
    for raw_item in cast("list[object]", raw_requirements):
        if not isinstance(raw_item, dict):
            degraded = True
            degradation_reasons.append("semantic requirement item was not an object")
            continue
        item = _semantic_requirement_review(
            cast("dict[str, Any]", raw_item),
            deterministic_requirements=deterministic_requirements,
        )
        if item is None:
            degraded = True
            degradation_reasons.append("semantic requirement referenced unknown id")
            continue
        reviewed.append(item)
        seen.add(str(item["id"]))
    for requirement_id in sorted(set(deterministic_requirements) - seen):
        degraded = True
        reviewed.append(
            _omitted_semantic_requirement_review(
                deterministic_requirements[requirement_id],
                requirement_id=requirement_id,
            )
        )
    aggregate = _semantic_aggregate(reviewed)
    limitations = _semantic_limitations(payload.get("limitations"))
    if degraded:
        limitations.append("Semantic review output omitted or malformed one or more requirements.")
    return {
        "enabled": True,
        "provider": provider.provider,
        "model": provider.model,
        "prompt_digest": prompt_digest,
        "input_digest": input_digest,
        "requirements": reviewed,
        "aggregate": aggregate,
        "degraded": degraded,
        "degradation_reason": "; ".join(dict.fromkeys(degradation_reasons)) if degraded else None,
        "limitations": limitations,
        "usage": usage or {},
    }


def merge_semantic_review_into_artifact(
    artifact: dict[str, Any],
    semantic_review: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(artifact)
    deterministic_score = _finite_score(artifact.get("score"), max_score=10.0)
    raw_summary = artifact.get("summary")
    deterministic_summary: dict[str, Any] = (
        cast("dict[str, Any]", raw_summary) if isinstance(raw_summary, dict) else {}
    )
    merged.setdefault(
        "deterministic_result",
        {
            "score": deterministic_score,
            "summary": deterministic_summary,
            "matcher": artifact.get("matcher"),
        },
    )
    adjusted_score, adjustment_reason = _adjusted_semantic_score(
        deterministic_score=deterministic_score,
        deterministic_artifact=artifact,
        semantic_review=semantic_review,
    )
    merged["semantic_review"] = semantic_review
    merged["semantic_adjustment"] = {
        "policy": "conservative_evidence_bound",
        "score": adjusted_score,
        "delta": round(adjusted_score - deterministic_score, 2),
        "reason": adjustment_reason,
    }
    merged["score"] = adjusted_score
    if semantic_review.get("degraded") is True:
        limitations = list(cast("list[object]", merged.get("known_limitations", [])))
        limitations.append(
            "Semantic review degraded; deterministic structured result was retained."
        )
        merged["known_limitations"] = [str(item) for item in limitations]
    return merged


def read_spec_source(*, workspace_root: Path, spec_path: Path) -> SpecSource:
    target = _resolve_repo_local_spec_path(workspace_root=workspace_root, spec_path=spec_path)
    data = _read_regular_spec_file(target)
    display_path = _display_path(workspace_root, target)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError("--against-spec must be valid UTF-8") from exc
    return SpecSource(
        path=target,
        display_path=display_path,
        text=text,
        digest=hashlib.sha256(data).hexdigest(),
        byte_count=len(data),
    )


def spec_source_reference(*, workspace_root: Path, spec_path: Path) -> dict[str, Any]:
    source = read_spec_source(workspace_root=workspace_root, spec_path=spec_path)
    return {
        "path": source.display_path,
        "ref": source.display_path,
        "sha256": source.digest,
        "bytes": source.byte_count,
    }


def dimension_score_from_artifact(
    *,
    run_path: Path | None,
    metadata: dict[str, Any] | Any,
) -> SpecDimension:
    if run_path is None:
        return SpecDimension(
            score=0.0,
            reason="not applicable: no run path available for spec_alignment artifact",
            applicable=False,
        )
    artifact_path = run_path / SPEC_ALIGNMENT_FILENAME
    if artifact_path.exists():
        try:
            payload = _load_spec_artifact(artifact_path)
            score = _finite_score(payload.get("score"), max_score=10.0)
            raw_summary = payload.get("summary")
            summary = cast("dict[Any, Any]", raw_summary) if isinstance(raw_summary, dict) else {}
            return SpecDimension(
                score=score,
                reason=(
                    "spec_alignment.json "
                    f"implemented={_int_summary(summary, 'implemented')} "
                    f"partial={_int_summary(summary, 'partial')} "
                    f"missing={_int_summary(summary, 'missing')} "
                    f"unknown={_int_summary(summary, 'unknown')}"
                ),
                applicable=True,
            )
        except Exception:
            return SpecDimension(
                score=0.0,
                reason="spec_alignment artifact unreadable; scored as zero",
                applicable=True,
            )
    metadata_map = cast("dict[str, Any]", metadata) if isinstance(metadata, dict) else {}
    source_detail = metadata_map.get("source_detail")
    if isinstance(source_detail, dict) and any(
        key in source_detail for key in ("against_spec", "spec_path", "spec_ref")
    ):
        return SpecDimension(
            score=0.0,
            reason="spec reference present but spec_alignment.json is missing",
            applicable=True,
        )
    return SpecDimension(
        score=0.0,
        reason="not applicable: no spec constraint attached to this run",
        applicable=False,
    )


def _resolve_repo_local_spec_path(*, workspace_root: Path, spec_path: Path) -> Path:
    raw = str(spec_path)
    if "://" in raw:
        raise InputError("--against-spec only accepts a local repo file path")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise InputError("--against-spec contains control characters")
    if spec_path.is_absolute():
        root = workspace_root.resolve(strict=False)
        resolved = spec_path.resolve(strict=False)
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise InputError("--against-spec must stay inside the workspace") from exc
        return resolve_safe_path_from_root(workspace_root, relative)
    return resolve_safe_path_from_root(workspace_root, spec_path)


def _read_regular_spec_file(path: Path) -> bytes:
    try:
        path_stat = os.lstat(path)
    except OSError as exc:
        raise InputError("--against-spec file is unreadable") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError("--against-spec file must not be a symlink")
    if _has_windows_reparse_point(path_stat):
        raise InputError("--against-spec file must not be a Windows reparse point or junction")
    if getattr(path_stat, "st_nlink", 1) > 1:
        raise InputError("--against-spec file must not be a hardlink")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise InputError("--against-spec file is unreadable") from exc
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise InputError("--against-spec file must be a regular file")
        if _has_windows_reparse_point(file_stat):
            raise InputError("--against-spec file must not be a Windows reparse point or junction")
        if getattr(file_stat, "st_nlink", 1) > 1:
            raise InputError("--against-spec file must not be a hardlink")
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError("--against-spec file changed during validation")
        if file_stat.st_size > _MAX_SPEC_BYTES:
            raise InputError(f"--against-spec exceeds {_MAX_SPEC_BYTES} bytes")
        return os.read(fd, _MAX_SPEC_BYTES + 1)
    finally:
        os.close(fd)


def _has_windows_reparse_point(path_stat: object) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _display_path(workspace_root: Path, path: Path) -> str:
    try:
        return path.relative_to(workspace_root.resolve(strict=False)).as_posix()
    except ValueError:
        return path.name


def _extract_requirements(spec_text: str) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    in_code = False
    paragraph: list[str] = []
    for raw_line in spec_text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped:
            _flush_paragraph(paragraph, requirements)
            continue
        item = _extract_requirement_line(stripped)
        if item is not None:
            _flush_paragraph(paragraph, requirements)
            requirements.append(item)
        else:
            paragraph.append(stripped)
        if len(requirements) >= _MAX_REQUIREMENTS:
            break
    if len(requirements) < _MAX_REQUIREMENTS:
        _flush_paragraph(paragraph, requirements)
    return requirements[:_MAX_REQUIREMENTS]


def _extract_requirement_line(line: str) -> dict[str, Any] | None:
    match = re.match(r"^(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)(.+)$", line)
    if not match:
        return None
    text = _normalize_requirement_text(match.group(1))
    if not text:
        return None
    return _requirement_payload(text)


def _flush_paragraph(paragraph: list[str], requirements: list[dict[str, Any]]) -> None:
    if not paragraph or len(requirements) >= _MAX_REQUIREMENTS:
        paragraph.clear()
        return
    text = _normalize_requirement_text(" ".join(paragraph))
    paragraph.clear()
    if not text:
        return
    lowered = text.lower()
    requirement_words = (*_STRONG_REQUIREMENT_WORDS, *_MEDIUM_REQUIREMENT_WORDS)
    if any(word in lowered or word in text for word in requirement_words):
        requirements.append(_requirement_payload(text))


def _requirement_payload(text: str) -> dict[str, Any]:
    return {
        "id": f"REQ-{0:03d}",
        "text": text[:_MAX_REQUIREMENT_CHARS],
        "severity": _infer_severity(text),
    }


def _normalize_requirement_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" -\t")


def _infer_severity(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered or word in text for word in _STRONG_REQUIREMENT_WORDS):
        return "high"
    if any(word in lowered or word in text for word in _MEDIUM_REQUIREMENT_WORDS):
        return "medium"
    return "low"


def _classify_requirements(
    requirements: list[dict[str, Any]],
    *,
    claims: list[dict[str, Any]],
    patch_text: str,
) -> list[dict[str, Any]]:
    if not requirements:
        return [
            {
                "id": "REQ-001",
                "text": "No explicit requirements were extracted from the spec.",
                "classification": "unknown",
                "severity": "low",
                "evidence_refs": [],
                "confidence": 0.0,
                "reason": "Spec did not contain parseable bullet, numbered, or modal requirements.",
            }
        ]
    scored: list[dict[str, Any]] = []
    for index, requirement in enumerate(requirements, start=1):
        text = str(requirement["text"])
        req_tokens = _tokens(text)
        best_claim, best_claim_ratio = _best_claim_match(req_tokens, claims)
        patch_tokens = _tokens(_patch_added_text(patch_text))
        patch_ratio = _overlap_ratio(req_tokens, patch_tokens)
        patch_evidence = _patch_anchor_evidence(text, patch_text)
        forbidden = _is_forbidden_requirement(text)
        evidence_refs = list(patch_evidence)
        if best_claim is not None:
            evidence_refs.extend(_claim_evidence_refs(best_claim))
        classification, confidence, reason = _classification(
            req_tokens=req_tokens,
            best_claim_ratio=best_claim_ratio,
            patch_ratio=patch_ratio,
            patch_evidence=patch_evidence,
            forbidden=forbidden,
            has_claim_evidence=bool(evidence_refs),
            has_claims=bool(claims),
        )
        scored.append(
            {
                "id": f"REQ-{index:03d}",
                "text": text,
                "classification": classification,
                "severity": requirement.get("severity", "low"),
                "evidence_refs": evidence_refs,
                "confidence": confidence,
                "reason": reason,
            }
        )
    return scored


def _classification(
    *,
    req_tokens: set[str],
    best_claim_ratio: float,
    patch_ratio: float,
    patch_evidence: list[dict[str, Any]],
    forbidden: bool,
    has_claim_evidence: bool,
    has_claims: bool,
) -> tuple[str, float, str]:
    if not req_tokens:
        return "unknown", 0.0, "Requirement has no comparable lexical tokens."
    if forbidden and any(item.get("type") == "patch_forbidden" for item in patch_evidence):
        return (
            "missing",
            0.85,
            "Forbidden requirement anchor was added in the captured diff.",
        )
    if any(item.get("type") == "patch" for item in patch_evidence):
        return (
            "implemented",
            0.82,
            "Captured diff added all required code anchors.",
        )
    if best_claim_ratio >= 0.38 and has_claim_evidence:
        return (
            "implemented",
            min(0.95, 0.65 + best_claim_ratio),
            "Verified claim overlaps requirement.",
        )
    if best_claim_ratio >= 0.24 or patch_ratio >= 0.18:
        return (
            "partial",
            min(0.75, 0.45 + max(best_claim_ratio, patch_ratio)),
            ("Captured diff overlaps requirement but evidence is incomplete."),
        )
    if not has_claims:
        return "unknown", 0.2, "No claim evidence is available for this requirement."
    return "missing", 0.55, "No matching claim or diff evidence was found."


def _tokens(text: str) -> set[str]:
    return {
        _normalize_token(token)
        for token in re.findall(r"[A-Za-z0-9_]{3,}|[\u4e00-\u9fff]", text)
        if len(token.strip()) > 0
    }


def _normalize_token(token: str) -> str:
    lowered = token.lower()
    if len(lowered) > 5 and lowered.endswith("ies"):
        return f"{lowered[:-3]}y"
    if len(lowered) > 5 and lowered.endswith(("ing", "ers")):
        return lowered[:-3]
    if len(lowered) > 4 and lowered.endswith(("ed", "es")):
        return lowered[:-2]
    if len(lowered) > 4 and lowered.endswith("s"):
        return lowered[:-1]
    return lowered


def _best_claim_match(
    req_tokens: set[str],
    claims: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float]:
    best_claim: dict[str, Any] | None = None
    best_ratio = 0.0
    for claim in claims:
        status = str(claim.get("status", "")).lower()
        if status not in {"verified", "weak"}:
            continue
        ratio = _overlap_ratio(req_tokens, _tokens(str(claim.get("text", ""))))
        if ratio > best_ratio:
            best_ratio = ratio
            best_claim = claim
    return best_claim, best_ratio


def _overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left:
        return 0.0
    return len(left & right) / len(left)


def _is_forbidden_requirement(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered or marker in text
        for marker in (
            "must not",
            "do not",
            "should not",
            "never",
            "forbid",
            "forbidden",
            "不得",
            "禁止",
            "不要",
            "不可",
        )
    )


def _requirement_anchors(text: str) -> list[str]:
    anchors: list[str] = []
    anchors.extend(match.strip() for match in re.findall(r"`([^`]{1,120})`", text))
    anchors.extend(
        match.strip()
        for match in re.findall(
            r"(?:--[A-Za-z0-9][A-Za-z0-9_-]*|[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+|[A-Za-z0-9_.-]+\.(?:json|md|py|ts|tsx|js|jsx|toml|yaml|yml))",
            text,
        )
    )
    result: list[str] = []
    seen: set[str] = set()
    for anchor in anchors:
        normalized = anchor.strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result[:10]


def _patch_anchor_evidence(text: str, patch_text: str) -> list[dict[str, Any]]:
    anchors = _requirement_anchors(text)
    if not anchors:
        return []
    added_by_file = _patch_added_lines_by_file(patch_text)
    if not added_by_file:
        return []
    matched_by_file: list[dict[str, Any]] = []
    required = {anchor.lower(): anchor for anchor in anchors}
    for file_path, lines in added_by_file.items():
        matched: dict[str, list[int]] = {}
        for line_no, line_text in lines:
            lowered = line_text.lower()
            for lowered_anchor, anchor in required.items():
                if lowered_anchor in lowered:
                    matched.setdefault(anchor, []).append(line_no)
        if matched:
            matched_by_file.append(
                {
                    "type": "patch_forbidden" if _is_forbidden_requirement(text) else "patch",
                    "file": file_path,
                    "lines": sorted({line for values in matched.values() for line in values})[:10],
                    "anchors": [anchor for anchor in anchors if anchor in matched],
                    "side": "new",
                }
            )
    if not matched_by_file:
        return []
    all_matched = {
        anchor for item in matched_by_file for anchor in cast("list[str]", item.get("anchors", []))
    }
    if _is_forbidden_requirement(text):
        return matched_by_file[:5]
    return matched_by_file[:5] if all(anchor in all_matched for anchor in anchors) else []


def _patch_added_text(patch_text: str) -> str:
    return "\n".join(
        line[1:]
        for line in patch_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def _patch_added_lines_by_file(patch_text: str) -> dict[str, list[tuple[int, str]]]:
    added: dict[str, list[tuple[int, str]]] = {}
    current_file: str | None = None
    new_line: int | None = None
    for raw_line in patch_text.splitlines():
        if raw_line.startswith("+++ "):
            current_file = _normalize_patch_file_token(raw_line[4:].strip())
            new_line = None
            continue
        if raw_line.startswith("@@"):
            new_line = _parse_new_hunk_start(raw_line)
            continue
        if current_file is None or current_file == "/dev/null" or new_line is None:
            continue
        if raw_line.startswith("+"):
            added.setdefault(current_file, []).append((new_line, raw_line[1:]))
            new_line += 1
        elif raw_line.startswith("-"):
            continue
        else:
            new_line += 1
    return added


def _normalize_patch_file_token(token: str) -> str:
    stripped = token.strip().strip('"')
    if stripped == "/dev/null":
        return stripped
    if stripped.startswith("b/"):
        return stripped[2:]
    if stripped.startswith("a/"):
        return stripped[2:]
    return stripped


def _parse_new_hunk_start(line: str) -> int | None:
    match = re.search(r"\+(\d+)(?:,\d+)?", line)
    if match is None:
        return None
    return int(match.group(1))


def _claim_evidence_refs(claim: dict[str, Any] | None) -> list[dict[str, Any]]:
    if claim is None:
        return []
    refs: list[dict[str, Any]] = []
    hunks = claim.get("source_hunks")
    if isinstance(hunks, list):
        for raw_hunk in cast("list[object]", hunks[:5]):
            if not isinstance(raw_hunk, dict):
                continue
            hunk = cast("dict[str, Any]", raw_hunk)
            refs.append(
                {
                    "type": "claim",
                    "claim_id": str(claim.get("claim_id", "")),
                    "file": str(hunk.get("file", "")),
                    "start": hunk.get("start"),
                    "end": hunk.get("end"),
                    "side": hunk.get("side"),
                }
            )
    return refs


def _score_requirements(requirements: list[dict[str, Any]]) -> float:
    possible = 0.0
    earned = 0.0
    for requirement in requirements:
        weight = _severity_weight(str(requirement.get("severity", "low")))
        possible += weight
        classification = requirement.get("classification")
        if classification == "implemented":
            earned += weight
        elif classification == "partial":
            earned += weight * 0.5
        elif classification == "unknown":
            earned += weight * 0.2
    if possible <= 0:
        return 0.0
    return round(10.0 * earned / possible, 2)


def _severity_weight(severity: str) -> float:
    if severity == "high":
        return 1.25
    if severity == "medium":
        return 1.0
    return 0.75


def _aggregate_confidence(requirements: list[dict[str, Any]]) -> float:
    if not requirements:
        return 0.0
    values = [float(item.get("confidence", 0.0)) for item in requirements]
    return round(sum(values) / len(values), 3)


def _load_claim_payloads(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    claims: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw_line.strip():
            continue
        try:
            payload = safe_json_loads(raw_line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            claims.append(cast("dict[str, Any]", payload))
    return claims


def _read_optional_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _load_spec_artifact(path: Path) -> dict[str, Any]:
    payload = safe_json_loads(_read_regular_artifact_text(path))
    if not isinstance(payload, dict):
        raise ValueError("spec_alignment artifact must be an object")
    payload_map = cast("dict[str, Any]", payload)
    if payload_map.get("artifact") != SPEC_ALIGNMENT_ARTIFACT:
        raise ValueError("spec_alignment artifact has unexpected artifact type")
    if payload_map.get("schema") != SPEC_ALIGNMENT_SCHEMA:
        raise ValueError("spec_alignment artifact has unexpected schema")
    return payload_map


def _semantic_review_output_tokens(
    *,
    provider_config: ProviderConfig,
    output_token_budget: int | None,
) -> int:
    limits = [_SEMANTIC_REVIEW_OUTPUT_TOKEN_CAP]
    if output_token_budget is not None and output_token_budget > 0:
        limits.append(output_token_budget)
    provider_max = provider_config.max_output_tokens
    if provider_max is not None and provider_max > 0:
        limits.append(provider_max)
    return min(limits)


def _semantic_source_ref(run_path: Path) -> str:
    metadata = _read_optional_json_object(run_path / "metadata.json")
    source_ref = metadata.get("source_ref")
    return source_ref if isinstance(source_ref, str) else run_path.name


def _semantic_diff_content(run_path: Path) -> str:
    patch = _read_optional_text(run_path / "patch.diff")
    return patch[:200_000]


def _deterministic_result_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": _finite_score(artifact.get("score"), max_score=10.0),
        "max_score": _finite_score(artifact.get("max_score"), max_score=10.0),
        "summary": artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {},
        "confidence": _finite_confidence(artifact.get("confidence")),
        "matcher": artifact.get("matcher") if isinstance(artifact.get("matcher"), dict) else {},
        "known_limitations": (
            artifact.get("known_limitations")
            if isinstance(artifact.get("known_limitations"), list)
            else []
        ),
    }


def _semantic_requirement_inputs(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    requirements = artifact.get("requirements")
    if not isinstance(requirements, list):
        return []
    result: list[dict[str, Any]] = []
    for raw_item in cast("list[object]", requirements)[:_MAX_REQUIREMENTS]:
        if not isinstance(raw_item, dict):
            continue
        item = cast("dict[str, Any]", raw_item)
        result.append(
            {
                "id": str(item.get("id", "")),
                "text": str(item.get("text", ""))[:_MAX_REQUIREMENT_CHARS],
                "classification": str(item.get("classification", "unknown")),
                "severity": str(item.get("severity", "low")),
                "confidence": _finite_confidence(item.get("confidence")),
                "reason": str(item.get("reason", ""))[:300],
                "evidence_refs": _semantic_evidence_refs(item.get("evidence_refs")),
            }
        )
    return result


def _semantic_claim_inputs(
    run_path: Path,
    deterministic_artifact: dict[str, Any],
) -> list[dict[str, Any]]:
    required_claim_ids = {
        str(ref.get("claim_id"))
        for requirement in _semantic_requirement_inputs(deterministic_artifact)
        for ref in cast("list[dict[str, Any]]", requirement.get("evidence_refs", []))
        if ref.get("claim_id")
    }
    result: list[dict[str, Any]] = []
    for claim in _load_claim_payloads(run_path / "claims.jsonl"):
        claim_id = str(claim.get("claim_id", ""))
        if required_claim_ids and claim_id not in required_claim_ids:
            continue
        result.append(
            {
                "claim_id": claim_id,
                "status": str(claim.get("status", "")),
                "text": str(claim.get("text", ""))[:600],
                "source_hunks": _semantic_source_hunks(claim.get("source_hunks")),
            }
        )
        if len(result) >= 30:
            break
    return result


def _semantic_patch_inputs(
    run_path: Path,
    deterministic_artifact: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence_files = {
        str(ref.get("file"))
        for requirement in _semantic_requirement_inputs(deterministic_artifact)
        for ref in cast("list[dict[str, Any]]", requirement.get("evidence_refs", []))
        if ref.get("file")
    }
    added_by_file = _patch_added_lines_by_file(_read_optional_text(run_path / "patch.diff"))
    result: list[dict[str, Any]] = []
    for file_path, lines in added_by_file.items():
        if evidence_files and file_path not in evidence_files:
            continue
        result.append(
            {
                "file": file_path,
                "added_lines": [
                    {"line": line_no, "text": text[:300]} for line_no, text in lines[:30]
                ],
            }
        )
        if len(result) >= 20:
            break
    return result


def _semantic_source_hunks(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for raw_hunk in cast("list[object]", value[:8]):
        if not isinstance(raw_hunk, dict):
            continue
        hunk = cast("dict[str, Any]", raw_hunk)
        result.append(
            {
                "file": str(hunk.get("file", "")),
                "start": hunk.get("start"),
                "end": hunk.get("end"),
                "side": hunk.get("side"),
            }
        )
    return result


def _semantic_evidence_refs(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for raw_ref in cast("list[object]", value[:8]):
        if not isinstance(raw_ref, dict):
            continue
        ref = cast("dict[str, Any]", raw_ref)
        normalized: dict[str, Any] = {"type": str(ref.get("type", ""))}
        for key in ("claim_id", "file", "side"):
            raw_value = ref.get(key)
            if isinstance(raw_value, str):
                normalized[key] = raw_value
        for key in ("start", "end"):
            raw_value = ref.get(key)
            if isinstance(raw_value, int) and not isinstance(raw_value, bool):
                normalized[key] = raw_value
        raw_lines = ref.get("lines")
        if isinstance(raw_lines, list):
            normalized["lines"] = [
                item
                for item in cast("list[object]", raw_lines[:10])
                if isinstance(item, int) and not isinstance(item, bool) and item >= 0
            ]
        raw_anchors = ref.get("anchors")
        if isinstance(raw_anchors, list):
            normalized["anchors"] = [
                str(item)[:120]
                for item in cast("list[object]", raw_anchors[:10])
                if isinstance(item, str)
            ]
        result.append(normalized)
    return result


def _load_semantic_json_object(content: str) -> dict[str, Any]:
    for text in _semantic_text_candidates(content.strip()):
        try:
            payload = safe_json_loads(text)
        except (json.JSONDecodeError, ValueError):
            continue
        for candidate in _semantic_object_candidates(payload):
            if isinstance(candidate.get("requirements"), list):
                return candidate
    raise InputError("semantic alignment output must be a JSON object with requirements")


def _semantic_text_candidates(content: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for match in _JSON_FENCE_RE.finditer(content):
        language = (match.group("lang") or "").strip().casefold()
        if language and language != "json":
            continue
        candidates.append(match.group("body").strip())
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end >= start:
        candidates.append(content[start : end + 1])
    candidates.append(content)
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def _semantic_object_candidates(value: object) -> tuple[dict[str, Any], ...]:
    candidates: list[dict[str, Any]] = []
    if isinstance(value, dict):
        value_map = cast("dict[str, Any]", value)
        candidates.append(value_map)
        for key in ("output", "data", "result", "response"):
            nested = value_map.get(key)
            if isinstance(nested, dict | list):
                candidates.extend(_semantic_object_candidates(cast("object", nested)))
            elif isinstance(nested, str):
                try:
                    candidates.extend(_semantic_object_candidates(safe_json_loads(nested)))
                except (json.JSONDecodeError, ValueError):
                    continue
        output_text = value_map.get("output_text")
        if isinstance(output_text, str):
            with contextlib.suppress(json.JSONDecodeError, ValueError):
                candidates.extend(_semantic_object_candidates(safe_json_loads(output_text)))
    elif isinstance(value, list):
        for item in cast("list[object]", value):
            candidates.extend(_semantic_object_candidates(item))
    return tuple(candidates)


def _deterministic_requirements_by_id(artifact: dict[str, Any]) -> dict[str, dict[str, Any]]:
    requirements = artifact.get("requirements")
    if not isinstance(requirements, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for raw_item in cast("list[object]", requirements):
        if not isinstance(raw_item, dict):
            continue
        item = cast("dict[str, Any]", raw_item)
        requirement_id = str(item.get("id", ""))
        if requirement_id:
            result[requirement_id] = item
    return result


def _semantic_requirement_review(
    raw_item: dict[str, Any],
    *,
    deterministic_requirements: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    requirement_id = str(raw_item.get("id", ""))
    deterministic = deterministic_requirements.get(requirement_id)
    if deterministic is None:
        return None
    classification = str(raw_item.get("classification", "unknown")).strip().lower()
    if classification not in _SEMANTIC_CLASSIFICATIONS:
        classification = "unknown"
    confidence = _finite_confidence(raw_item.get("confidence"))
    rationale = str(raw_item.get("rationale") or raw_item.get("reason") or "").strip()
    if not rationale:
        rationale = "Semantic reviewer did not provide a rationale."
    deterministic_refs = cast("object", deterministic.get("evidence_refs"))
    evidence_refs = _bound_semantic_evidence_refs(
        raw_item.get("evidence_refs"),
        deterministic_refs=deterministic_refs,
    )
    if classification in {"implemented", "partial", "violated"} and not evidence_refs:
        classification = "unknown"
        confidence = min(confidence, 0.35)
        rationale = (
            rationale[:_MAX_SEMANTIC_RATIONALE_CHARS]
            + " No deterministic evidence reference was bound, so the semantic result is unknown."
        )
    deterministic_classification = str(deterministic.get("classification", "unknown"))
    return {
        "id": requirement_id,
        "classification": classification,
        "confidence": confidence,
        "rationale": rationale[:_MAX_SEMANTIC_RATIONALE_CHARS],
        "evidence_refs": evidence_refs,
        "disagreement_with_deterministic": _semantic_disagrees(
            deterministic_classification,
            classification,
        ),
    }


def _bound_semantic_evidence_refs(
    value: object,
    *,
    deterministic_refs: object,
) -> list[dict[str, Any]]:
    deterministic = _semantic_evidence_refs(deterministic_refs)
    allowed = {_canonical_json(ref): ref for ref in deterministic}
    if not isinstance(value, list) or not allowed:
        return []
    result: list[dict[str, Any]] = []
    for ref in _semantic_evidence_refs(cast("list[object]", value)):
        canonical = _canonical_json(ref)
        allowed_ref = allowed.get(canonical)
        if allowed_ref is not None and canonical not in {_canonical_json(item) for item in result}:
            result.append(allowed_ref)
    return result


def _omitted_semantic_requirement_review(
    deterministic: dict[str, Any],
    *,
    requirement_id: str,
) -> dict[str, Any]:
    return {
        "id": requirement_id,
        "classification": "unknown",
        "confidence": 0.0,
        "rationale": "Semantic reviewer omitted this deterministic requirement.",
        "evidence_refs": [],
        "disagreement_with_deterministic": _semantic_disagrees(
            str(deterministic.get("classification", "unknown")),
            "unknown",
        ),
    }


def _semantic_disagrees(deterministic_classification: str, semantic_classification: str) -> bool:
    if semantic_classification == "unknown":
        return deterministic_classification not in {"unknown", ""}
    if semantic_classification == "violated":
        return deterministic_classification != "missing"
    return deterministic_classification != semantic_classification


def _semantic_aggregate(requirements: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"implemented": 0, "partial": 0, "missing": 0, "unknown": 0, "violated": 0}
    confidences: list[float] = []
    risk_flags: list[str] = []
    for item in requirements:
        classification = str(item.get("classification", "unknown"))
        if classification not in counts:
            classification = "unknown"
        counts[classification] += 1
        confidences.append(_finite_confidence(item.get("confidence")))
        if item.get("disagreement_with_deterministic") is True:
            risk_flags.append("deterministic_semantic_disagreement")
        if classification == "violated":
            risk_flags.append("semantic_forbidden_violation")
    return {
        "implemented": counts["implemented"],
        "partial": counts["partial"],
        "missing": counts["missing"],
        "unknown": counts["unknown"],
        "violated": counts["violated"],
        "confidence": (round(sum(confidences) / len(confidences), 3) if confidences else 0.0),
        "risk_flags": sorted(set(risk_flags)),
    }


def _semantic_limitations(value: object) -> list[str]:
    defaults = [
        "Semantic review is not a proof and does not replace deterministic evidence.",
        "Rationales are reviewer explanations, not factual evidence.",
    ]
    if not isinstance(value, list):
        return defaults
    result = defaults[:]
    for raw_item in cast("list[object]", value[:_MAX_SEMANTIC_LIMITATIONS]):
        if isinstance(raw_item, str) and raw_item.strip():
            result.append(raw_item.strip()[:300])
    return list(dict.fromkeys(result))[:_MAX_SEMANTIC_LIMITATIONS]


def _semantic_degraded_review(
    *,
    provider: SemanticReviewProvider,
    prompt_digest: str,
    input_digest: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "provider": provider.provider,
        "model": provider.model,
        "prompt_digest": prompt_digest,
        "input_digest": input_digest,
        "requirements": [],
        "aggregate": {
            "implemented": 0,
            "partial": 0,
            "missing": 0,
            "unknown": 0,
            "violated": 0,
            "confidence": 0.0,
            "risk_flags": ["semantic_review_degraded"],
        },
        "degraded": True,
        "degradation_reason": reason[:500],
        "limitations": _semantic_limitations([]),
        "usage": {},
    }


def _semantic_degradation_reason(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__
    return f"semantic alignment review degraded: {message}"


def _adjusted_semantic_score(
    *,
    deterministic_score: float,
    deterministic_artifact: dict[str, Any],
    semantic_review: dict[str, Any],
) -> tuple[float, str]:
    if semantic_review.get("degraded") is True:
        return deterministic_score, "semantic review degraded; deterministic score retained"
    deterministic_requirements = _deterministic_requirements_by_id(deterministic_artifact)
    semantic_requirements = semantic_review.get("requirements")
    if not isinstance(semantic_requirements, list):
        return deterministic_score, "semantic review malformed; deterministic score retained"
    penalty = 0.0
    reasons: list[str] = []
    for raw_item in cast("list[object]", semantic_requirements):
        if not isinstance(raw_item, dict):
            continue
        item = cast("dict[str, Any]", raw_item)
        requirement_id = str(item.get("id", ""))
        deterministic = deterministic_requirements.get(requirement_id)
        if deterministic is None:
            continue
        classification = str(item.get("classification", "unknown"))
        confidence = _finite_confidence(item.get("confidence"))
        raw_evidence_refs = item.get("evidence_refs")
        evidence_refs = (
            cast("list[object]", raw_evidence_refs) if isinstance(raw_evidence_refs, list) else []
        )
        has_evidence = len(evidence_refs) > 0
        deterministic_classification = str(deterministic.get("classification", "unknown"))
        weight = _severity_weight(str(deterministic.get("severity", "low")))
        text = str(deterministic.get("text", ""))
        if (
            classification == "violated"
            and _is_forbidden_requirement(text)
            and has_evidence
            and confidence >= 0.7
        ):
            penalty += 4.0 * weight
            reasons.append(f"{requirement_id}: semantic reviewer found forbidden violation")
        elif (
            deterministic_classification == "implemented"
            and classification in {"missing", "violated"}
            and has_evidence
            and confidence >= 0.75
        ):
            penalty += 1.5 * weight
            reasons.append(f"{requirement_id}: semantic reviewer disagreed with implementation")
    if penalty <= 0:
        return deterministic_score, "semantic review recorded; deterministic score retained"
    adjusted = round(max(0.0, deterministic_score - min(6.0, penalty)), 2)
    return adjusted, "; ".join(reasons[:4])


def _read_optional_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = safe_json_loads(_read_optional_text(path))
    except (json.JSONDecodeError, ValueError):
        return {}
    return cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _finite_confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    score = float(value)
    if not math.isfinite(score):
        return 0.0
    return round(max(0.0, min(1.0, score)), 3)


def _read_regular_artifact_text(path: Path) -> str:
    try:
        path_stat = os.lstat(path)
    except OSError as exc:
        raise ValueError("spec_alignment artifact is unreadable") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise ValueError("spec_alignment artifact must not be a symlink")
    if _has_windows_reparse_point(path_stat):
        raise ValueError("spec_alignment artifact must not be a Windows reparse point")
    if getattr(path_stat, "st_nlink", 1) > 1:
        raise ValueError("spec_alignment artifact must not be a hardlink")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise ValueError("spec_alignment artifact is unreadable") from exc
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("spec_alignment artifact must be a regular file")
        if _has_windows_reparse_point(file_stat):
            raise ValueError("spec_alignment artifact must not be a Windows reparse point")
        if getattr(file_stat, "st_nlink", 1) > 1:
            raise ValueError("spec_alignment artifact must not be a hardlink")
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise ValueError("spec_alignment artifact changed during validation")
        if file_stat.st_size > _MAX_SPEC_BYTES:
            raise ValueError("spec_alignment artifact is too large")
        data = os.read(fd, _MAX_SPEC_BYTES + 1)
        if len(data) > _MAX_SPEC_BYTES:
            raise ValueError("spec_alignment artifact is too large")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("spec_alignment artifact must be valid UTF-8") from exc
    finally:
        os.close(fd)


def _finite_score(value: object, *, max_score: float) -> float:
    if not isinstance(value, int | float):
        return 0.0
    score = float(value)
    if score != score or score in {float("inf"), float("-inf")}:
        return 0.0
    return round(max(0.0, min(max_score, score)), 2)


def _int_summary(summary: dict[Any, Any], key: str) -> int:
    value = summary.get(key)
    return value if isinstance(value, int) and value >= 0 else 0
