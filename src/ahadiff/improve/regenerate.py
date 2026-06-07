from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ahadiff.claims.extract import read_artifact_text_no_follow
from ahadiff.core.errors import AhaDiffError, InputError, StorageError
from ahadiff.core.ids import make_run_id
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import (
    find_workspace_root,
    project_state_dir,
    validate_run_id,
    validate_state_dir_path,
)
from ahadiff.eval.deterministic import DimensionScore
from ahadiff.eval.evaluator import ScoreReport, evaluate_run
from ahadiff.eval.gates import HardGateResult, HardGateSummary
from ahadiff.eval.results import (
    append_result,
    compute_prompt_version,
    publish_result_artifacts,
    rollback_result_event,
)
from ahadiff.lesson.generator import LessonVariant, generate_lessons_from_run
from ahadiff.llm.cost import effective_output_cap, resolve_model_limits

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import httpx

    from ahadiff.contracts import PrivacyMode, ProviderConfig
    from ahadiff.core.config import SecurityConfig
    from ahadiff.llm.schemas import EnforcementMode

_REGENERATE_FULL_OUTPUT_TOKEN_CAP = 32_000
_STEERING_CLAIMS_MAX_BYTES = 256 * 1024


@dataclass(frozen=True)
class RegenerateTarget:
    workspace_root: Path
    state_dir: Path
    run_path: Path
    run_id: str


@dataclass(frozen=True)
class RegenerateRunResult:
    baseline_run_id: str
    accepted_run_id: str | None
    baseline_overall: float
    accepted_overall: float | None
    weakest_dim: str
    candidates: int
    status: str
    message: str
    event_id: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _CandidateSelection:
    index: int
    run_path: Path
    report: ScoreReport


def resolve_regenerate_target(
    *,
    run_id: str,
    workspace_root: Path | None = None,
    state_dir: Path | None = None,
) -> RegenerateTarget:
    validate_run_id(run_id)
    root = find_workspace_root(workspace_root)
    if state_dir is None:
        resolved_state_dir = _state_dir_for_workspace(root)
    else:
        resolved_state_dir = validate_state_dir_path(state_dir)
    run_path = resolved_state_dir / "runs" / run_id
    if not run_path.is_dir():
        raise InputError(f"run artifacts are missing: {run_id}")
    score_path = run_path / "score.json"
    if not score_path.is_file():
        raise InputError(f"baseline run is missing score.json: {run_id}")
    return RegenerateTarget(
        workspace_root=root,
        state_dir=resolved_state_dir,
        run_path=run_path,
        run_id=run_id,
    )


def run_regenerate(
    run_id: str,
    candidates: int,
    *,
    workspace_root: Path | None = None,
    state_dir: Path | None = None,
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
    lesson_output_token_caps: Mapping[LessonVariant, int] | None = None,
    on_sub_progress: Callable[[str], None] | None = None,
    structured_output_mode: EnforcementMode = "json_object",
    structured_validation_retries: int = 0,
) -> RegenerateRunResult:
    if candidates < 1:
        raise InputError("improve-run candidates must be >= 1")
    target = resolve_regenerate_target(
        run_id=run_id,
        workspace_root=workspace_root,
        state_dir=state_dir,
    )
    baseline_report = _load_persisted_score_report(target.run_path)
    steering_context = _build_steering_context(target.run_path, baseline_report)
    output_caps = _regenerate_output_caps(lesson_output_token_caps)
    warnings = list(
        _regenerate_cap_warnings(
            provider_config=provider_config,
            output_token_budget=output_token_budget,
            output_caps=output_caps,
        )
    )
    prompt_version_override = _bundled_prompt_version()

    best: _CandidateSelection | None = None
    for candidate_index in range(1, candidates + 1):
        candidate_path = _copy_run_to_candidate(target)
        try:
            generate_lessons_from_run(
                run_id=candidate_path.name,
                run_path=candidate_path,
                workspace_root=target.workspace_root,
                provider_config=provider_config,
                api_key=api_key,
                security_config=security_config,
                output_lang=output_lang,
                overwrite=True,
                client=client,
                request_timeout_seconds=request_timeout_seconds,
                max_concurrent=max_concurrent,
                qps_limit=qps_limit,
                retry_attempts=retry_attempts,
                privacy_mode=privacy_mode,
                input_token_budget=input_token_budget,
                output_token_budget=output_token_budget,
                lesson_output_token_caps=output_caps,
                lesson_variants=("full", "hint", "compact"),
                steering_context=steering_context,
                on_sub_progress=on_sub_progress,
                structured_output_mode=structured_output_mode,
                structured_validation_retries=structured_validation_retries,
            )
            candidate_report = evaluate_run(candidate_path)
            _validate_candidate_report(candidate_report, candidate_path)
            candidate = _CandidateSelection(
                index=candidate_index,
                run_path=candidate_path,
                report=candidate_report,
            )
            if _accepts_candidate(baseline_report, candidate_report) and (
                best is None or candidate_report.overall > best.report.overall
            ):
                if best is not None:
                    _remove_candidate_run(best.run_path)
                best = candidate
                continue
            _remove_candidate_run(candidate_path)
        except Exception:
            if best is None or candidate_path != best.run_path:
                _remove_candidate_run(candidate_path)
            raise

    if best is None:
        return RegenerateRunResult(
            baseline_run_id=target.run_id,
            accepted_run_id=None,
            baseline_overall=baseline_report.overall,
            accepted_overall=None,
            weakest_dim=baseline_report.weakest_dim,
            candidates=candidates,
            status="no_improvement",
            message="no improvement, baseline kept",
            event_id=None,
            warnings=tuple(warnings),
        )

    note_payload: dict[str, object] = {
        "baseline_run_id": target.run_id,
        "baseline_overall": round(baseline_report.overall, 2),
        "candidate_index": best.index,
        "candidates": candidates,
        "prior_weakest_dim": baseline_report.weakest_dim,
        "mode": "improve_run",
    }
    outcome = append_result(
        run_path=best.run_path,
        report=best.report,
        status="keep",
        base_ref=_metadata_base_ref(best.run_path),
        event_type="improve_run",
        note_payload=note_payload,
        write_finalized=False,
        prompt_version_override=prompt_version_override,
    )
    try:
        publish_result_artifacts(
            run_path=best.run_path,
            report=best.report,
            event=outcome.event,
            score_path=best.run_path / "score.json",
            overwrite=False,
        )
    except Exception:
        if outcome.sqlite_inserted:
            rollback_result_event(run_path=best.run_path, event_id=outcome.event.event_id)
        raise
    return RegenerateRunResult(
        baseline_run_id=target.run_id,
        accepted_run_id=best.report.run_id,
        baseline_overall=baseline_report.overall,
        accepted_overall=best.report.overall,
        weakest_dim=baseline_report.weakest_dim,
        candidates=candidates,
        status="accepted",
        message="accepted regenerated lesson",
        event_id=outcome.event.event_id,
        warnings=(*warnings, *outcome.warnings),
    )


def _state_dir_for_workspace(workspace_root: Path) -> Path:
    try:
        return project_state_dir(workspace_root)
    except AhaDiffError:
        return validate_state_dir_path(workspace_root / ".ahadiff")


def _copy_run_to_candidate(target: RegenerateTarget) -> Path:
    _reject_symlink_tree(target.run_path)
    candidate_path = _next_candidate_path(target.state_dir)
    shutil.copytree(target.run_path, candidate_path, symlinks=False)
    _rewrite_candidate_identity(
        candidate_path,
        baseline_run_id=target.run_id,
        candidate_run_id=candidate_path.name,
    )
    _remove_if_exists(candidate_path / "score.json")
    _remove_if_exists(candidate_path / "finalized.json")
    return candidate_path


def _next_candidate_path(state_dir: Path) -> Path:
    runs_dir = state_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for _attempt in range(100):
        candidate_path = runs_dir / make_run_id()
        if not candidate_path.exists():
            return candidate_path
    raise StorageError("failed to allocate an improve-run candidate id")


def _rewrite_candidate_identity(
    run_path: Path,
    *,
    baseline_run_id: str,
    candidate_run_id: str,
) -> None:
    metadata_path = run_path / "metadata.json"
    metadata = _load_json_object(metadata_path)
    metadata["run_id"] = candidate_run_id
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for jsonl_path in sorted(run_path.rglob("*.jsonl")):
        _rewrite_jsonl_run_id(
            jsonl_path,
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
        )


def _rewrite_jsonl_run_id(
    path: Path,
    *,
    baseline_run_id: str,
    candidate_run_id: str,
) -> None:
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            lines.append(raw_line)
            continue
        payload = safe_json_loads(stripped)
        if isinstance(payload, dict):
            payload_map = cast("dict[str, object]", payload)
            if payload_map.get("run_id") == baseline_run_id:
                payload_map["run_id"] = candidate_run_id
                lines.append(json.dumps(payload_map, ensure_ascii=False, sort_keys=True))
                continue
            lines.append(raw_line)
            continue
        lines.append(raw_line)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _remove_candidate_run(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _remove_if_exists(path: Path) -> None:
    if path.is_symlink():
        raise InputError(f"refusing to remove symlinked run artifact: {path.name}")
    path.unlink(missing_ok=True)


def _reject_symlink_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise InputError(f"baseline run artifact must not be a symlink: {path}")


def _load_persisted_score_report(run_path: Path) -> ScoreReport:
    score_path = run_path / "score.json"
    if not score_path.is_file():
        raise InputError(f"baseline run is missing score.json: {run_path.name}")
    payload = _load_json_object(score_path)
    dimensions = _score_dimensions(payload, target=score_path)
    return ScoreReport(
        run_id=_required_string(payload, "run_id", target=score_path),
        source_ref=_required_string(payload, "source_ref", target=score_path),
        source_kind=_required_string(payload, "source_kind", target=score_path),
        capability_level=_required_int(payload, "capability_level", target=score_path),
        degraded_flags=_optional_bool_map(payload.get("degraded_flags"), target=score_path),
        overall=_required_number(payload, "overall", target=score_path),
        verdict=_required_string(payload, "verdict", target=score_path),
        weakest_dim=_required_string(payload, "weakest_dim", target=score_path),
        eval_bundle_version=_required_string(payload, "eval_bundle_version", target=score_path),
        rubric_version=_required_string(payload, "rubric_version", target=score_path),
        dimensions=dimensions,
        hard_gates=_hard_gate_summary(payload.get("hard_gates"), target=score_path),
        notes=_optional_string_tuple(payload.get("notes"), target=score_path),
    )


def _score_dimensions(payload: dict[str, object], *, target: Path) -> tuple[DimensionScore, ...]:
    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, dict):
        raise InputError(f"score.json dimensions must be an object: {target}")
    dimensions: list[DimensionScore] = []
    dimension_map = cast("dict[object, object]", raw_dimensions)
    for raw_name, raw_value in dimension_map.items():
        if not isinstance(raw_name, str):
            raise InputError(f"score.json dimension names must be strings: {target}")
        if isinstance(raw_value, dict):
            value_map = cast("dict[str, object]", raw_value)
            score = _required_number(value_map, "score", target=target)
            max_score = _required_number(value_map, "max_score", target=target)
            reason = value_map.get("reason")
        elif isinstance(raw_value, int | float):
            score = float(raw_value)
            max_score = 100.0
            reason = None
        else:
            raise InputError(f"score.json dimension {raw_name!r} score must be numeric: {target}")
        dimensions.append(
            DimensionScore(
                name=raw_name,
                score=score,
                max_score=max_score,
                reason=reason if isinstance(reason, str) else "persisted score",
            )
        )
    if not dimensions:
        raise InputError(f"score.json dimensions must not be empty: {target}")
    return tuple(dimensions)


def _hard_gate_summary(raw_value: object, *, target: Path) -> HardGateSummary:
    if raw_value is None:
        return HardGateSummary(results=())
    if not isinstance(raw_value, dict):
        raise InputError(f"score.json hard_gates must be an object: {target}")
    results: list[HardGateResult] = []
    gate_map = cast("dict[object, object]", raw_value)
    for raw_name, raw_gate in gate_map.items():
        if not isinstance(raw_name, str) or not isinstance(raw_gate, dict):
            raise InputError(f"score.json hard_gates entries must be objects: {target}")
        gate_payload = cast("dict[str, object]", raw_gate)
        passed = gate_payload.get("passed")
        if not isinstance(passed, bool):
            raise InputError(f"score.json hard gate {raw_name!r} passed must be boolean: {target}")
        detail = gate_payload.get("detail")
        results.append(
            HardGateResult(
                name=raw_name,
                passed=passed,
                detail=detail if isinstance(detail, str) else "",
                score=_optional_number(gate_payload.get("score")),
                threshold=_optional_number(gate_payload.get("threshold")),
            )
        )
    return HardGateSummary(results=tuple(results))


def _accepts_candidate(baseline: ScoreReport, candidate: ScoreReport) -> bool:
    if candidate.overall <= baseline.overall:
        return False
    if candidate.verdict != "PASS":
        return False
    return candidate.hard_gates.passed


def _validate_candidate_report(report: ScoreReport, run_path: Path) -> None:
    if report.run_id != run_path.name:
        raise InputError("candidate score report run_id does not match candidate run")


def _build_steering_context(run_path: Path, baseline: ScoreReport) -> str:
    claims_text = read_artifact_text_no_follow(
        run_path / "claims.jsonl",
        max_bytes=_STEERING_CLAIMS_MAX_BYTES,
    )
    return "\n".join(
        (
            f"Prior weakest deterministic dimension: {baseline.weakest_dim}",
            f"Prior deterministic overall score: {baseline.overall:.2f}",
            "Use the existing verified claims below as grounding. Do not invent new claims.",
            "```jsonl",
            claims_text.rstrip(),
            "```",
        )
    )


def _regenerate_output_caps(
    caps: Mapping[LessonVariant, int] | None,
) -> dict[LessonVariant, int]:
    merged = dict(caps or {})
    merged["full"] = max(int(merged.get("full", 0)), _REGENERATE_FULL_OUTPUT_TOKEN_CAP)
    return merged


def _regenerate_cap_warnings(
    *,
    provider_config: ProviderConfig,
    output_token_budget: int | None,
    output_caps: Mapping[LessonVariant, int],
) -> tuple[str, ...]:
    requested_full_cap = int(output_caps["full"])
    effective_full_cap = _effective_regenerate_output_cap(
        provider_config=provider_config,
        output_token_budget=output_token_budget,
        requested_cap=requested_full_cap,
    )
    if effective_full_cap >= requested_full_cap:
        return ()
    return (
        "full lesson output cap requested "
        f"{requested_full_cap} tokens but effective cap is {effective_full_cap}; "
        "model or configured output limits may constrain improve-run quality",
    )


def _effective_regenerate_output_cap(
    *,
    provider_config: ProviderConfig,
    output_token_budget: int | None,
    requested_cap: int,
) -> int:
    limits = resolve_model_limits(
        str(provider_config.provider_class),
        provider_config.model_name,
        provider_config,
    )
    model_max_candidates = [limits.max_output_tokens]
    if provider_config.max_output_tokens and provider_config.max_output_tokens > 0:
        model_max_candidates.append(provider_config.max_output_tokens)
    return effective_output_cap(
        requested_step_cap=requested_cap,
        llm_output_budget=output_token_budget,
        resolved_model_max_output=min(model_max_candidates),
        default_step_cap=requested_cap,
    )


def _bundled_prompt_version() -> str:
    clean_root = Path(__file__).resolve().parent / "__bundled_prompt_version_root__"
    return compute_prompt_version(clean_root)


def _metadata_base_ref(run_path: Path) -> str | None:
    metadata = _load_json_object(run_path / "metadata.json")
    base_ref = metadata.get("base_ref")
    return base_ref if isinstance(base_ref, str) and base_ref else None


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        payload = safe_json_loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise InputError(f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise InputError(f"expected a JSON object in {path}")
    return cast("dict[str, object]", payload)


def _required_string(payload: dict[str, object], key: str, *, target: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise InputError(f"score.json {key} must be a non-empty string: {target}")
    return value


def _required_int(payload: dict[str, object], key: str, *, target: Path) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise InputError(f"score.json {key} must be an integer: {target}")
    return value


def _required_number(payload: dict[str, object], key: str, *, target: Path) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float):
        raise InputError(f"score.json {key} must be numeric: {target}")
    return float(value)


def _optional_number(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _optional_bool_map(value: object, *, target: Path) -> dict[str, bool]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InputError(f"score.json degraded_flags must be an object: {target}")
    result: dict[str, bool] = {}
    value_map = cast("dict[object, object]", value)
    for raw_key, raw_flag in value_map.items():
        if not isinstance(raw_key, str) or not isinstance(raw_flag, bool):
            raise InputError(f"score.json degraded_flags must map strings to booleans: {target}")
        result[raw_key] = raw_flag
    return result


def _optional_string_tuple(value: object, *, target: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise InputError(f"score.json notes must be a list of strings: {target}")
    items = cast("list[object]", value)
    if not all(isinstance(item, str) for item in items):
        raise InputError(f"score.json notes must be a list of strings: {target}")
    return tuple(cast("list[str]", items))


__all__ = [
    "RegenerateRunResult",
    "RegenerateTarget",
    "resolve_regenerate_target",
    "run_regenerate",
]
