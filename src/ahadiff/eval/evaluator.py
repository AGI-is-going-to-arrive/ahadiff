from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.claims import load_line_map_records
from ahadiff.contracts import ClaimRecord, compute_runtime_eval_bundle_version
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import path_identity_key
from ahadiff.llm.cost import DEFAULT_INPUT_TOKEN_BUDGET, DEFAULT_OUTPUT_TOKEN_BUDGET

from .deterministic import DimensionScore, build_deterministic_scores
from .gates import HardGateSummary, evaluate_hard_gates
from .rubric import load_rubric

if TYPE_CHECKING:
    from collections.abc import Mapping

    import httpx

    from ahadiff.contracts import PrivacyMode, ProviderConfig
    from ahadiff.core.config import SecurityConfig

    from .rubric import RubricDefinition, RubricDimension

_JSON_FENCE_RE = re.compile(
    r"```(?P<lang>[^\r\n`]*)\r?\n(?P<body>[\s\S]*?)```",
    re.IGNORECASE,
)
_LLM_JUDGE_PROMPT_FILENAME = "eval_judge.md"
_LLM_JUDGE_OUTPUT_TOKEN_CAP = 4_000
_SAFETY_FINDINGS_ARTIFACTS = ("safety_findings.json", "safety_findings.jsonl")


@dataclass(frozen=True)
class ScoreReport:
    run_id: str
    source_ref: str
    source_kind: str
    capability_level: int
    degraded_flags: dict[str, bool]
    overall: float
    verdict: str
    weakest_dim: str
    eval_bundle_version: str
    rubric_version: str
    dimensions: tuple[DimensionScore, ...]
    hard_gates: HardGateSummary
    notes: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "source_ref": self.source_ref,
            "source_kind": self.source_kind,
            "capability_level": self.capability_level,
            "degraded_flags": self.degraded_flags,
            "overall": round(self.overall, 2),
            "verdict": self.verdict,
            "weakest_dim": self.weakest_dim,
            "eval_bundle_version": self.eval_bundle_version,
            "rubric_version": self.rubric_version,
            "dimensions": {item.name: item.as_payload() for item in self.dimensions},
            "hard_gates": self.hard_gates.as_payload(),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class LlmJudgeReport:
    run_id: str
    source_ref: str
    source_kind: str
    model_id: str
    provider_class: str
    prompt_fingerprint: str
    eval_bundle_version: str
    overall: float
    dimensions: tuple[DimensionScore, ...]
    input_tokens: int
    output_tokens: int
    finish_reason: str | None
    request_id: str | None
    notes: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "artifact": "llm_judge",
            "schema_version": 1,
            "run_id": self.run_id,
            "source_ref": self.source_ref,
            "source_kind": self.source_kind,
            "model_id": self.model_id,
            "provider_class": self.provider_class,
            "prompt_fingerprint": self.prompt_fingerprint,
            "eval_bundle_version": self.eval_bundle_version,
            "overall": round(self.overall, 2),
            "dimensions": {item.name: item.as_payload() for item in self.dimensions},
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            },
            "finish_reason": self.finish_reason,
            "request_id": self.request_id,
            "notes": list(self.notes),
        }


def evaluate_run(run_path: Path) -> ScoreReport:
    metadata = _load_json_object(run_path / "metadata.json")
    patch_text = _read_text(run_path / "patch.diff")
    line_maps = load_line_map_records(run_path / "line_map.json")
    claims = _load_claim_records(run_path / "claims.jsonl")
    lesson_artifacts = _load_lesson_artifacts(run_path / "lesson")
    quiz_entries = _load_jsonl_objects(run_path / "quiz" / "quiz.jsonl", required=False)
    rubric = load_rubric()
    deterministic = build_deterministic_scores(
        rubric=rubric,
        metadata=metadata,
        run_path=run_path,
        patch_text=patch_text,
        claims=claims,
        line_maps=line_maps,
        lesson_artifacts=lesson_artifacts,
        quiz_entries=quiz_entries,
    )
    dimension_scores = deterministic.score_lookup()
    safety_findings = _load_safety_findings(run_path)
    hard_gates = evaluate_hard_gates(
        rubric=rubric,
        dimension_scores=dimension_scores,
        claims=claims,
        secret_leak_detected=deterministic.secret_leak_detected,
        injection_unresolved=deterministic.injection_unresolved,
        safety_findings=safety_findings,
    )
    overall = _resolve_overall(deterministic.dimensions)
    verdict = _resolve_verdict(
        overall=overall,
        hard_gates=hard_gates,
        pass_threshold=rubric.pass_threshold,
        caution_threshold=rubric.caution_threshold,
        artifacts_complete=_has_complete_stage3_artifacts(
            claims=claims,
            line_maps=line_maps,
            lesson_artifacts=lesson_artifacts,
            quiz_entries=quiz_entries,
        ),
    )
    weakest_dim = _resolve_weakest_dimension(deterministic.dimensions)
    return ScoreReport(
        run_id=str(metadata["run_id"]),
        source_ref=str(metadata["source_ref"]),
        source_kind=str(metadata["source_kind"]),
        capability_level=int(metadata["capability_level"]),
        degraded_flags=_normalize_degraded_flags(metadata.get("degraded_flags")),
        overall=overall,
        verdict=verdict,
        weakest_dim=weakest_dim,
        eval_bundle_version=compute_runtime_eval_bundle_version(),
        rubric_version=rubric.rubric_version,
        dimensions=deterministic.dimensions,
        hard_gates=hard_gates,
        notes=deterministic.notes,
    )


def run_llm_judge_for_run(
    *,
    run_path: Path,
    workspace_root: Path,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    privacy_mode: PrivacyMode,
    output_lang: str,
    deterministic_report: ScoreReport,
    request_timeout_seconds: int,
    max_concurrent: int,
    qps_limit: int,
    retry_attempts: int,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
    client: httpx.Client | None = None,
    output_path: Path | None = None,
    overwrite: bool = True,
) -> LlmJudgeReport:
    from ahadiff.llm.provider import make_provider
    from ahadiff.llm.schemas import ProviderRequest
    from ahadiff.safety.redact import AllowlistPolicy, redaction_pipeline

    prompt_text = load_llm_judge_prompt()
    prompt_fingerprint = _sha256_short(prompt_text)
    patch_text = _read_text(run_path / "patch.diff")
    payload_text = build_llm_judge_payload(
        prompt_text=prompt_text,
        run_path=run_path,
        deterministic_report=deterministic_report,
    )
    redacted_payload_text = None
    findings = ()
    if privacy_mode == "redacted_remote":
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

    resolved_input_token_budget = input_token_budget or DEFAULT_INPUT_TOKEN_BUDGET
    resolved_output_token_budget = output_token_budget or DEFAULT_OUTPUT_TOKEN_BUDGET

    provider = make_provider(
        provider_config,
        api_key=api_key,
        security_config=security_config,
        workspace_root=workspace_root,
        client=client,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        request_timeout_seconds=request_timeout_seconds,
        input_token_budget=resolved_input_token_budget,
        output_token_budget=resolved_output_token_budget,
        execution_origin="eval_judge",
    )
    try:
        response = provider.generate(
            ProviderRequest(
                prompt_name="eval.judge",
                prompt_fingerprint=prompt_fingerprint,
                prompt_version=prompt_fingerprint,
                eval_bundle_version=deterministic_report.eval_bundle_version,
                model=provider_config.model_name,
                payload_text=payload_text,
                diff_content=patch_text,
                source_ref=deterministic_report.source_ref,
                output_lang=output_lang,
                privacy_mode=privacy_mode,
                redacted_payload_text=redacted_payload_text,
                findings=findings,
                response_format="json",
                max_output_tokens=_resolve_llm_judge_max_output_tokens(
                    provider_config=provider_config,
                    output_token_budget=output_token_budget,
                ),
                thinking_level=provider_config.thinking_level,
            )
        )
    finally:
        provider.close()

    dimensions = parse_llm_judge_output(
        response.content,
        dimension_max_scores={
            dimension.name: dimension.max_score for dimension in deterministic_report.dimensions
        },
    )
    judge_report = LlmJudgeReport(
        run_id=deterministic_report.run_id,
        source_ref=deterministic_report.source_ref,
        source_kind=deterministic_report.source_kind,
        model_id=response.model_id,
        provider_class=provider_config.provider_class,
        prompt_fingerprint=prompt_fingerprint,
        eval_bundle_version=deterministic_report.eval_bundle_version,
        overall=_resolve_overall(dimensions),
        dimensions=dimensions,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        finish_reason=response.finish_reason,
        request_id=response.request_id,
        notes=response.notes,
    )
    judge_output_path = output_path or run_path / "judge.json"
    write_llm_judge_report(judge_output_path, judge_report, overwrite=overwrite)
    return judge_report


def build_llm_judge_payload(
    *,
    prompt_text: str,
    run_path: Path,
    deterministic_report: ScoreReport,
) -> str:
    metadata = _read_text(run_path / "metadata.json")
    claims = _read_optional_text(run_path / "claims.jsonl")
    full_lesson = _read_optional_text(run_path / "lesson" / "lesson.full.md")
    hint_lesson = _read_optional_text(run_path / "lesson" / "lesson.hint.md")
    compact_lesson = _read_optional_text(run_path / "lesson" / "lesson.compact.md")
    quiz = _read_optional_text(run_path / "quiz" / "quiz.jsonl")
    patch = _read_text(run_path / "patch.diff")
    return "\n\n".join(
        (
            prompt_text.strip(),
            "## Run metadata\n```json\n" + metadata.strip() + "\n```",
            "## Patch\n```diff\n" + patch.strip() + "\n```",
            "## Verified claims\n```jsonl\n" + claims.strip() + "\n```",
            "## Lesson full\n```markdown\n" + full_lesson.strip() + "\n```",
            "## Lesson hint\n```markdown\n" + hint_lesson.strip() + "\n```",
            "## Lesson compact\n```markdown\n" + compact_lesson.strip() + "\n```",
            "## Quiz\n```jsonl\n" + quiz.strip() + "\n```",
            "## Deterministic score\n```json\n"
            + json.dumps(
                deterministic_report.to_payload(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n```",
        )
    )


def load_llm_judge_prompt() -> str:
    from importlib.resources import files

    prompt_path = Path(__file__).resolve().parents[3] / "prompts" / _LLM_JUDGE_PROMPT_FILENAME
    if prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8")
    try:
        package_prompt = files("ahadiff").joinpath("prompts", _LLM_JUDGE_PROMPT_FILENAME)
        return package_prompt.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise InputError(f"missing prompt resource: {_LLM_JUDGE_PROMPT_FILENAME}") from exc


def parse_llm_judge_output(
    content: str,
    *,
    rubric: RubricDefinition | None = None,
    dimension_max_scores: Mapping[str, float] | None = None,
) -> tuple[DimensionScore, ...]:
    active_rubric = rubric or load_rubric()
    payload = _load_llm_judge_json_object(content)
    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, dict):
        raise InputError("LLM judge output is missing object-valued dimensions")
    raw_dimension_map = cast("dict[object, object]", raw_dimensions)
    missing = [
        dimension.name
        for dimension in active_rubric.dimensions
        if _llm_judge_dimension_max_score(dimension, dimension_max_scores) > 0.0
        and dimension.name not in raw_dimension_map
    ]
    if missing:
        raise InputError("LLM judge output is missing dimensions: " + ", ".join(missing))

    dimensions: list[DimensionScore] = []
    for dimension in active_rubric.dimensions:
        max_score = _llm_judge_dimension_max_score(dimension, dimension_max_scores)
        if max_score <= 0.0:
            reason = "not applicable in deterministic score"
            if dimension.name in raw_dimension_map:
                _score, parsed_reason = _parse_llm_judge_dimension(
                    raw_dimension_map[dimension.name],
                    name=dimension.name,
                    max_score=float(dimension.max_score),
                )
                reason = f"{reason}; judge reason: {parsed_reason}"
            dimensions.append(
                DimensionScore(
                    name=dimension.name,
                    score=0.0,
                    max_score=0.0,
                    reason=reason,
                )
            )
            continue
        score, reason = _parse_llm_judge_dimension(
            raw_dimension_map[dimension.name],
            name=dimension.name,
            max_score=max_score,
        )
        dimensions.append(
            DimensionScore(
                name=dimension.name,
                score=score,
                max_score=max_score,
                reason=reason,
            )
        )
    return tuple(dimensions)


def write_score_report(path: Path, report: ScoreReport, *, overwrite: bool = False) -> Path:
    if path.exists() and not overwrite:
        raise InputError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling_path(path)
    try:
        temp_path.write_text(
            json.dumps(report.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)
    return path


def write_llm_judge_report(
    path: Path,
    report: LlmJudgeReport,
    *,
    overwrite: bool = False,
) -> Path:
    if path.exists() and not overwrite:
        raise InputError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling_path(path)
    try:
        temp_path.write_text(
            json.dumps(report.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)
    return path


def _load_llm_judge_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    valid_candidates: list[dict[str, Any]] = []
    for payload in _llm_judge_payload_candidates(stripped):
        for candidate in _llm_judge_object_candidates(payload):
            dimensions = candidate.get("dimensions")
            if isinstance(dimensions, dict):
                valid_candidates.append(candidate)
    if valid_candidates:
        return valid_candidates[-1]

    try:
        payload = safe_json_loads(stripped)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid LLM judge JSON: {exc.msg}") from exc
    except ValueError as exc:
        raise InputError(f"invalid LLM judge JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InputError("LLM judge output must decode to a JSON object")
    return cast("dict[str, Any]", payload)


def _llm_judge_payload_candidates(content: str) -> tuple[object, ...]:
    parsed: list[object] = []
    for text in _llm_judge_text_candidates(content):
        decoded = _try_load_llm_judge_json(text)
        if decoded is not None:
            parsed.append(decoded)
        parsed.extend(_decode_embedded_llm_judge_json(text))
    return tuple(parsed)


def _llm_judge_text_candidates(content: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for match in _JSON_FENCE_RE.finditer(content):
        language = (match.group("lang") or "").strip().casefold()
        if language and language != "json":
            continue
        candidates.append(match.group("body").strip())
    candidates.append(content)
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def _try_load_llm_judge_json(text: str) -> object | None:
    try:
        return safe_json_loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _decode_embedded_llm_judge_json(text: str) -> list[object]:
    decoder = json.JSONDecoder(
        parse_constant=_reject_llm_judge_constant,
        parse_float=_parse_finite_llm_judge_float,
    )
    values: list[object] = []
    for index, character in enumerate(text):
        if character not in "{[":
            continue
        try:
            parsed, _end_offset = decoder.raw_decode(text[index:])
        except (json.JSONDecodeError, ValueError):
            continue
        values.append(parsed)
    return values


def _reject_llm_judge_constant(value: str) -> object:
    raise ValueError(f"Disallowed JSON constant: {value!r}")


def _parse_finite_llm_judge_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"Non-finite JSON number: {value!r}")
    return parsed


def _llm_judge_object_candidates(value: object) -> tuple[dict[str, Any], ...]:
    candidates: list[dict[str, Any]] = []
    _append_llm_judge_object_candidates(value, candidates)
    return tuple(candidates)


def _append_llm_judge_object_candidates(
    value: object,
    candidates: list[dict[str, Any]],
) -> None:
    if isinstance(value, dict):
        value_map = cast("dict[str, Any]", value)
        candidates.append(value_map)
        for nested in _llm_judge_nested_sources(value_map):
            _append_llm_judge_object_candidates(nested, candidates)
        return
    if isinstance(value, list):
        for item in cast("list[object]", value):
            _append_llm_judge_object_candidates(item, candidates)


def _llm_judge_nested_sources(value: dict[str, Any]) -> tuple[object, ...]:
    nested_values: list[object] = []
    for key in ("output", "data", "result", "response"):
        nested = value.get(key)
        if isinstance(nested, dict | list):
            nested_values.append(cast("object", nested))
        elif isinstance(nested, str):
            nested_values.extend(_llm_judge_payload_candidates(nested))

    output_text = value.get("output_text")
    if isinstance(output_text, str):
        nested_values.extend(_llm_judge_payload_candidates(output_text))

    output = value.get("output")
    if isinstance(output, list):
        for item in cast("list[object]", output):
            if not isinstance(item, dict):
                continue
            content = cast("dict[str, object]", item).get("content")
            if isinstance(content, list):
                nested_values.extend(_llm_judge_text_fields(cast("list[object]", content)))

    choices = value.get("choices")
    if isinstance(choices, list):
        for raw_choice in cast("list[object]", choices):
            if not isinstance(raw_choice, dict):
                continue
            message = cast("dict[str, object]", raw_choice).get("message")
            if not isinstance(message, dict):
                continue
            content = cast("dict[str, object]", message).get("content")
            if isinstance(content, str):
                nested_values.extend(_llm_judge_payload_candidates(content))

    return tuple(nested_values)


def _llm_judge_text_fields(items: list[object]) -> list[object]:
    parsed: list[object] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        text = cast("dict[str, object]", raw_item).get("text")
        if isinstance(text, str):
            parsed.extend(_llm_judge_payload_candidates(text))
    return parsed


def _parse_llm_judge_dimension(
    raw_dimension: object,
    *,
    name: str,
    max_score: float,
) -> tuple[float, str]:
    if isinstance(raw_dimension, dict):
        raw_dimension_map = cast("dict[object, object]", raw_dimension)
        raw_score = raw_dimension_map.get("score")
        raw_reason = raw_dimension_map.get("reason")
        reason = (
            raw_reason.strip()
            if isinstance(raw_reason, str) and raw_reason.strip()
            else "LLM judge score"
        )
    else:
        raw_score = raw_dimension
        reason = "LLM judge score"

    if isinstance(raw_score, bool) or not isinstance(raw_score, int | float):
        raise InputError(f"LLM judge dimension {name!r} score must be numeric")
    score = float(raw_score)
    if not math.isfinite(score):
        raise InputError(f"LLM judge dimension {name!r} score must be finite")
    if score < 0.0 or score > max_score:
        raise InputError(
            f"LLM judge dimension {name!r} score must be between 0.00 and {max_score:.2f}"
        )
    return round(score, 2), reason


def _llm_judge_dimension_max_score(
    dimension: RubricDimension,
    dimension_max_scores: Mapping[str, float] | None,
) -> float:
    if dimension_max_scores is None:
        return float(dimension.max_score)
    raw_value = dimension_max_scores.get(dimension.name, float(dimension.max_score))
    value = float(raw_value)
    if not math.isfinite(value) or value < 0.0:
        raise InputError(f"LLM judge dimension {dimension.name!r} max_score must be finite")
    if value > float(dimension.max_score):
        raise InputError(f"LLM judge dimension {dimension.name!r} max_score exceeds rubric maximum")
    return value


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = safe_json_loads(_read_text(path))
    except (json.JSONDecodeError, ValueError) as exc:
        raise InputError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InputError(f"expected a JSON object in {path}")
    return cast("dict[str, Any]", payload)


def _read_text(path: Path) -> str:
    if not path.exists():
        raise InputError(f"required run artifact is missing: {path}")
    return path.read_text(encoding="utf-8")


def _read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _resolve_llm_judge_max_output_tokens(
    *,
    provider_config: ProviderConfig,
    output_token_budget: int | None,
) -> int:
    limits = [_LLM_JUDGE_OUTPUT_TOKEN_CAP]
    if output_token_budget is not None and output_token_budget > 0:
        limits.append(output_token_budget)
    provider_max = getattr(provider_config, "max_output_tokens", None)
    if provider_max is not None and provider_max > 0:
        limits.append(int(provider_max))
    return min(limits)


def _load_claim_records(path: Path) -> tuple[ClaimRecord, ...]:
    claims: list[ClaimRecord] = []
    for index, line in enumerate(_read_text(path).splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            claims.append(ClaimRecord.model_validate_json(stripped))
        except Exception as exc:  # pragma: no cover - pydantic message already exercised
            raise InputError(f"invalid claims.jsonl line {index}: {path}") from exc
    if not claims:
        raise InputError(f"claims.jsonl did not contain any records: {path}")
    return tuple(claims)


def _load_lesson_artifacts(lesson_dir: Path) -> dict[str, str]:
    lesson_files = {
        "full": lesson_dir / "lesson.full.md",
        "hint": lesson_dir / "lesson.hint.md",
        "compact": lesson_dir / "lesson.compact.md",
    }
    return {
        key: target.read_text(encoding="utf-8")
        for key, target in lesson_files.items()
        if target.exists()
    }


def _load_jsonl_objects(path: Path, *, required: bool) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        if required:
            raise InputError(f"required run artifact is missing: {path}")
        return ()
    payloads: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = safe_json_loads(stripped)
        except (json.JSONDecodeError, ValueError) as exc:
            raise InputError(f"invalid JSON on line {index}: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise InputError(f"expected a JSON object on line {index}: {path}")
        payloads.append(cast("dict[str, Any]", payload))
    return tuple(payloads)


def _load_safety_findings(run_path: Path) -> tuple[dict[str, Any], ...]:
    findings: list[dict[str, Any]] = []
    for relative_path in _SAFETY_FINDINGS_ARTIFACTS:
        path = run_path / relative_path
        if not path.exists():
            continue
        if path.is_symlink():
            findings.append(_safety_findings_load_failure(path, "symlink artifact rejected"))
            continue
        try:
            stat = path.stat()
        except OSError as exc:
            findings.append(_safety_findings_load_failure(path, f"artifact stat failed: {exc}"))
            continue
        if getattr(stat, "st_nlink", 1) > 1:
            findings.append(_safety_findings_load_failure(path, "hardlinked artifact rejected"))
            continue
        if path.suffix == ".jsonl":
            try:
                findings.extend(_load_jsonl_objects(path, required=False))
            except (InputError, UnicodeDecodeError, OSError) as exc:
                findings.append(_safety_findings_load_failure(path, f"artifact load failed: {exc}"))
            continue
        try:
            payload = _load_json_object(path)
        except (InputError, UnicodeDecodeError, OSError) as exc:
            findings.append(_safety_findings_load_failure(path, f"artifact load failed: {exc}"))
            continue
        raw_findings = payload.get("findings")
        if not isinstance(raw_findings, list):
            findings.append(_safety_findings_load_failure(path, "missing findings array"))
            continue
        for index, raw_finding in enumerate(cast("list[object]", raw_findings), start=1):
            if not isinstance(raw_finding, dict):
                findings.append(_safety_findings_load_failure(path, f"invalid finding at {index}"))
                continue
            findings.append(cast("dict[str, Any]", raw_finding))
    return tuple(findings)


def _safety_findings_load_failure(path: Path, reason: str) -> dict[str, Any]:
    return {
        "severity": "Critical",
        "rule_id": "SAFETY_FINDINGS_ARTIFACT_INVALID",
        "source": path.name,
        "reason": reason,
    }


def _resolve_verdict(
    *,
    overall: float,
    hard_gates: HardGateSummary,
    pass_threshold: float,
    caution_threshold: float,
    artifacts_complete: bool,
) -> str:
    if not hard_gates.passed:
        return "FAIL"
    if overall >= pass_threshold:
        if not artifacts_complete:
            return "CAUTION"
        return "PASS"
    if overall >= caution_threshold:
        return "CAUTION"
    return "FAIL"


def _resolve_overall(dimensions: tuple[DimensionScore, ...]) -> float:
    applicable = tuple(item for item in dimensions if item.max_score > 0)
    if not applicable:
        return 0.0
    raw_score = sum(item.score for item in applicable)
    raw_max = sum(item.max_score for item in applicable)
    if raw_max <= 0:
        return 0.0
    if math.isclose(raw_max, 100.0):
        return round(raw_score, 2)
    return round((raw_score / raw_max) * 100.0, 2)


def _has_complete_stage3_artifacts(
    *,
    claims: tuple[ClaimRecord, ...],
    line_maps: tuple[Any, ...],
    lesson_artifacts: dict[str, str],
    quiz_entries: tuple[dict[str, Any], ...],
) -> bool:
    required_lesson_variants = {"full", "hint", "compact"}
    return required_lesson_variants.issubset(lesson_artifacts) and _has_linked_quiz_entries(
        claims=claims,
        line_maps=line_maps,
        quiz_entries=quiz_entries,
    )


def _has_linked_quiz_entries(
    *,
    claims: tuple[ClaimRecord, ...],
    line_maps: tuple[Any, ...],
    quiz_entries: tuple[dict[str, Any], ...],
) -> bool:
    if not quiz_entries:
        return False
    claim_ids = {claim.claim_id for claim in claims}
    valid_lines: set[tuple[str, int]] = set()
    for file_map in line_maps:
        identity = file_map.path_identity_key
        for hunk in file_map.hunks:
            for line in (
                *hunk.added_lines,
                *hunk.deleted_lines,
                *hunk.context_old_lines,
                *hunk.context_new_lines,
            ):
                valid_lines.add((identity, line))
    for entry in quiz_entries:
        raw_claims = entry.get("source_claims")
        if not isinstance(raw_claims, list) or not raw_claims:
            return False
        claim_values = cast("list[object]", raw_claims)
        if any(not isinstance(item, str) or item.strip() not in claim_ids for item in claim_values):
            return False
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return False
        evidence_items = cast("list[object]", evidence)
        if not any(_evidence_links_to_line_map(item, valid_lines) for item in evidence_items):
            return False
    return True


def _evidence_links_to_line_map(
    payload: object,
    valid_lines: set[tuple[str, int]],
) -> bool:
    if not isinstance(payload, dict):
        return False
    payload_map = cast("dict[str, object]", payload)
    raw_file = payload_map.get("file", payload_map.get("path"))
    raw_line = payload_map.get("line", payload_map.get("start"))
    if not isinstance(raw_file, str) or not isinstance(raw_line, int):
        return False
    return (path_identity_key(Path(raw_file)), raw_line) in valid_lines


def _resolve_weakest_dimension(dimensions: tuple[DimensionScore, ...]) -> str:
    comparable = tuple(item for item in dimensions if item.max_score > 0) or dimensions
    weakest = min(
        comparable,
        key=lambda item: (
            item.score / item.max_score if item.max_score else 0.0,
            item.score,
            item.name,
        ),
    )
    return weakest.name


def _normalize_degraded_flags(raw_value: object) -> dict[str, bool]:
    if not isinstance(raw_value, dict):
        return {}
    raw_mapping = cast("dict[object, object]", raw_value)
    return {str(key): bool(value) for key, value in raw_mapping.items()}


def _temporary_sibling_path(path: Path) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".score.tmp",
        dir=path.parent,
    )
    os.close(fd)
    temp_path = Path(raw_path)
    temp_path.unlink()
    return temp_path


__all__ = [
    "LlmJudgeReport",
    "ScoreReport",
    "build_llm_judge_payload",
    "evaluate_run",
    "load_llm_judge_prompt",
    "parse_llm_judge_output",
    "run_llm_judge_for_run",
    "write_llm_judge_report",
    "write_score_report",
]
