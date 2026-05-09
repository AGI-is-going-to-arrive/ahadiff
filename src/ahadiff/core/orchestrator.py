"""Concrete learn pipeline orchestrator extracted from cli.py.

Runs SYNCHRONOUSLY — callers in serve use ``anyio.to_thread.run_sync``.
No rich/typer/console dependencies.
"""

from __future__ import annotations

import json as _json
import logging
import os
import shutil
import stat
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

from pydantic import ValidationError

from ahadiff.contracts import PrivacyMode, ProviderConfig
from ahadiff.core.config import (
    SecurityConfig,
    load_config,
    load_security_config,
    load_workspace_config,
    load_workspace_security_config,
    local_hosts_for_privacy_mode,
    resolve_provider_api_key,
)
from ahadiff.core.errors import AhaDiffError, ConfigError
from ahadiff.core.paths import (
    assert_local_repo_path,
    atomic_write_state_text,
    find_repo_root,
    find_workspace_root,
    lock_file_path,
    run_dir,
)
from ahadiff.i18n import resolve_locale

if TYPE_CHECKING:
    from pathlib import Path

    from ahadiff.safety.gates import TransportTarget

log = logging.getLogger(__name__)

_T = TypeVar("_T")


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LearnRequest:
    workspace_root: Path

    # Diff source params
    revision: str | None = None
    last: bool = False
    since: str | None = None
    author: str | None = None
    staged: bool = False
    unstaged: bool = False
    include_untracked: bool = False
    changed_paths: Iterable[str] | None = None
    patch: str | None = None
    compare: tuple[Path, Path] | None = None
    compare_dir: tuple[Path, Path] | None = None
    patch_url: str | None = None

    # Provider overrides
    provider_name: str | None = None
    provider_class: str = "openai"
    base_url: str | None = None
    model: str | None = None
    api_key_env: str = "AHADIFF_PROVIDER_API_KEY"

    # Options
    dry_run: bool = False
    force_learn: bool = False
    use_graphify: bool | None = None
    lang: str | None = None
    privacy_mode: str | None = None


@dataclass
class LearnResult:
    run_id: str
    status: str
    overall: float | None = None
    verdict: str | None = None
    weakest_dim: str | None = None
    artifacts_path: str | None = None
    warnings: list[str] = field(default_factory=lambda: [])
    learnability_score: float | None = None
    learnability_skip: bool = False
    recoverable_errors: int = 0


# ---------------------------------------------------------------------------
# Progress / cancellation callback types
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[int, int, str], None]
CancelledCheck = Callable[[], bool]

_TOTAL_STEPS = 10

_DEFAULT_MAX_STEP_RETRIES = 2
_LLM_STEP_MAX_RETRIES = 1
_DEFAULT_ERROR_BUDGET = 8
_MAX_BACKOFF_SECONDS = 30.0
_TIMEOUT_OR_NETWORK_ERROR_MARKERS = (
    "connection",
    "timeout",
    "transport",
    "rate limit",
    "retryable status",
    "network",
    "decompression failed",
    "decompressing",
)
_STEP_OUTPUT_CAPS = {
    "claim_extraction": 16_000,
    "lesson_full": 24_000,
    "lesson_hint": 3_000,
    "lesson_compact": 2_500,
    "quiz_generation": 6_000,
    "misconception_cards": 3_000,
}


def _llm_positive_int(
    llm_config: dict[str, Any],
    key: str,
    default: int,
) -> int:
    raw_value = llm_config.get(key, default)
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"llm.{key} expects int, got {raw_value!r}") from exc
    if value < 1:
        raise ConfigError(f"llm.{key} must be >= 1")
    return value


def _step_output_cap(
    *,
    provider_config: ProviderConfig,
    llm_config: dict[str, Any],
    output_budget: int,
    step_name: str,
) -> int:
    step_default = _STEP_OUTPUT_CAPS[step_name]
    step_cap = _llm_positive_int(
        llm_config,
        f"{step_name}_output_cap",
        step_default,
    )
    candidates = [output_budget, step_cap]
    provider_max = getattr(provider_config, "max_output_tokens", None)
    if provider_max is not None and provider_max > 0:
        candidates.append(int(provider_max))
    return min(candidates)


@dataclass
class PipelineErrorBudget:
    max_step_retries: int = _DEFAULT_MAX_STEP_RETRIES
    max_total_errors: int = _DEFAULT_ERROR_BUDGET
    error_count: int = 0

    def record_error(self) -> None:
        self.error_count += 1

    def exhausted(self) -> bool:
        return self.error_count >= self.max_total_errors


def is_recoverable_error(exc: Exception) -> bool:
    if isinstance(exc, PermissionError):
        return False
    from ahadiff.core.errors import ConfigError, SafetyError

    if isinstance(exc, ConfigError | SafetyError):
        return False
    if isinstance(exc, ValidationError):
        return True
    if isinstance(exc, ConnectionError | TimeoutError):
        return True
    try:
        msg = str(exc).lower()
    except Exception:
        return False
    _recoverable = (
        "connection",
        "timeout",
        "transport",
        "rate limit",
        "503",
        "429",
        "retry",
        "decompression failed",
        "decompressing",
        "does not contain",
        "not valid json",
        "extra data",
    )
    return any(p in msg for p in _recoverable)


def is_timeout_or_network_error(exc: Exception) -> bool:
    if isinstance(exc, ConnectionError | TimeoutError):
        return True
    try:
        msg = str(exc).lower()
    except Exception:
        return False
    return any(p in msg for p in _TIMEOUT_OR_NETWORK_ERROR_MARKERS)


_CANCEL_POLL_INTERVAL = 0.25


def _cancellable_sleep(seconds: float, is_cancelled: CancelledCheck) -> None:
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        _check_cancelled(is_cancelled)
        time.sleep(min(remaining, _CANCEL_POLL_INTERVAL))


def run_with_retry(
    step_fn: Callable[[], _T],
    *,
    step_name: str,
    budget: PipelineErrorBudget,
    is_cancelled: CancelledCheck,
    max_retries_override: int | None = None,
) -> _T:
    last_exc: Exception | None = None
    max_step_retries = (
        budget.max_step_retries if max_retries_override is None else max(0, max_retries_override)
    )
    for attempt in range(max_step_retries + 1):
        _check_cancelled(is_cancelled)
        try:
            return step_fn()
        except Exception as exc:
            if not is_recoverable_error(exc):
                raise
            last_exc = exc
            budget.record_error()
            if budget.exhausted():
                raise AhaDiffError(
                    f"pipeline error budget exhausted ({budget.error_count} recoverable errors, "
                    f"last failure in step '{step_name}'): {exc}"
                ) from exc
            if max_retries_override is not None and is_timeout_or_network_error(exc):
                raise
            if attempt >= max_step_retries:
                raise
            wait = min(2.0**attempt, _MAX_BACKOFF_SECONDS)
            log.warning(
                "step '%s' failed (attempt %d/%d, budget %d/%d), retrying in %.1fs: %s",
                step_name,
                attempt + 1,
                max_step_retries + 1,
                budget.error_count,
                budget.max_total_errors,
                wait,
                exc,
            )
            _cancellable_sleep(wait, is_cancelled)
    assert last_exc is not None  # noqa: S101
    raise last_exc


# ---------------------------------------------------------------------------
# Internal helpers (no CLI dependency)
# ---------------------------------------------------------------------------


def _cli_overrides(
    *,
    privacy_mode: str | None = None,
    lang: str | None = None,
) -> dict[str, Any]:
    return {"privacy_mode": privacy_mode, "lang": lang}


def _resolve_output_lang_from_snapshot(snapshot: Any, *, cli_lang: str | None) -> str:
    llm_config = cast("dict[str, Any]", snapshot.values["llm"])
    configured_output_lang = str(llm_config.get("output_lang", "auto"))
    configured_content_lang = (
        configured_output_lang if configured_output_lang != "auto" else str(snapshot.values["lang"])
    )
    return resolve_locale(cli_lang=cli_lang, config_lang=configured_content_lang)


def _normalize_provider_base_url(base_url: str, *, provider_class: str) -> str:
    normalized = base_url.rstrip("/")
    suffixes: tuple[str, ...] = ()
    if provider_class in {"openai", "openai_responses", "newapi", "lmstudio"}:
        suffixes = (
            "/v1/chat/completions",
            "/chat/completions",
            "/v1/responses",
            "/responses",
        )
    for suffix in suffixes:
        if normalized.endswith(suffix):
            trimmed = normalized[: -len(suffix)]
            if trimmed:
                return trimmed
    return normalized


def _provider_config_from_payload(payload: dict[str, Any]) -> ProviderConfig:
    try:
        return ProviderConfig.model_validate(payload)
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "invalid provider configuration")
        raise AhaDiffError(f"invalid provider configuration: {message}") from exc


def implicit_duplicate_provider_name(
    *,
    providers_table: dict[str, Any],
    configured_names: list[str],
    model: str | None,
) -> str | None:
    config_identities: set[str] = set()
    for name in configured_names:
        raw_config_payload = providers_table.get(name)
        if not isinstance(raw_config_payload, dict):
            return None
        normalized_payload = dict(cast("dict[str, Any]", raw_config_payload))
        try:
            normalized_payload["base_url"] = _normalize_provider_base_url(
                str(normalized_payload["base_url"]),
                provider_class=str(normalized_payload["provider_class"]),
            )
            if model is not None:
                normalized_payload["model_name"] = model
            provider_config = _provider_config_from_payload(normalized_payload)
        except (AhaDiffError, KeyError):
            return None
        config_identities.add(
            _json.dumps(
                provider_config.model_dump(mode="json", exclude={"probe_timestamp"}),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    if len(config_identities) == 1:
        return configured_names[0]
    return None


def _privacy_mode_for_explicit_provider_call(
    privacy_mode: str,
    *,
    transport_target: TransportTarget,
    provider_selection_explicit: bool,
) -> str:
    if (
        provider_selection_explicit
        and privacy_mode == "strict_local"
        and transport_target == "remote"
    ):
        return "explicit_remote"
    return privacy_mode


def _resolve_workspace_root(
    workspace_root: Path,
) -> tuple[Path, bool]:
    try:
        return find_repo_root(workspace_root), True
    except AhaDiffError:
        ws = find_workspace_root(workspace_root)
        assert_local_repo_path(ws)
        return ws, False


def _resolve_provider_from_config(
    *,
    snapshot: Any,
    operation_label: str,
    provider_name: str | None,
    provider_class: str,
    base_url: str | None,
    model: str | None,
    api_key_env: str,
    privacy_mode: str,
    local_hosts: tuple[str, ...],
    strict_local_hosts: tuple[str, ...],
    role: str = "generate",
) -> tuple[ProviderConfig, str | None, TransportTarget, bool]:
    from ahadiff.llm.provider import transport_target_for_base_url

    llm_config = cast("dict[str, Any]", snapshot.values["llm"])
    model_key = f"{role}_model"
    resolved_model = model or str(llm_config.get(model_key, llm_config.get("generate_model", "")))
    configured_model_override = _configured_model_override(
        snapshot=snapshot,
        role=role,
        model=model,
    )
    provider_selection_explicit = base_url is not None or provider_name is not None

    if base_url is not None:
        normalized_base_url = _normalize_provider_base_url(base_url, provider_class=provider_class)
        provider_config = _provider_config_from_payload(
            {
                "provider_class": provider_class,
                "model_name": resolved_model,
                "base_url": normalized_base_url,
                "api_key_env": api_key_env,
            }
        )
    else:
        raw_providers_table = snapshot.values.get("providers")
        if not isinstance(raw_providers_table, dict) or not raw_providers_table:
            raise AhaDiffError(
                f"{operation_label} requires --base-url or a configured [providers.<name>] entry"
            )
        providers_table = cast("dict[str, Any]", raw_providers_table)
        resolved_name = provider_name
        if resolved_name is None:
            config_provider_key = f"{role}_provider"
            config_provider = str(llm_config.get(config_provider_key, "")).strip()
            if config_provider and config_provider in providers_table:
                resolved_name = config_provider
            elif config_provider and config_provider not in providers_table:
                raise AhaDiffError(
                    f"{role}_provider '{config_provider}' not found in configured providers"
                )
        if resolved_name is None:
            configured_names = sorted(providers_table.keys())
            if len(configured_names) != 1:
                resolved_name = implicit_duplicate_provider_name(
                    providers_table=providers_table,
                    configured_names=configured_names,
                    model=configured_model_override,
                )
                if resolved_name is None:
                    raise AhaDiffError(
                        f"{operation_label} requires --provider or set {role}_provider "
                        "in [llm] config when multiple providers are configured"
                    )
            else:
                resolved_name = configured_names[0]
        raw_config_payload = providers_table.get(resolved_name)
        if not isinstance(raw_config_payload, dict):
            raise AhaDiffError(f"configured provider is missing or invalid: {resolved_name}")
        config_payload = cast("dict[str, Any]", raw_config_payload)
        normalized_payload = dict(config_payload)
        normalized_payload["base_url"] = _normalize_provider_base_url(
            str(normalized_payload["base_url"]),
            provider_class=str(normalized_payload["provider_class"]),
        )
        if configured_model_override is not None:
            normalized_payload["model_name"] = configured_model_override
        provider_config = _provider_config_from_payload(normalized_payload)

    transport_target: TransportTarget = transport_target_for_base_url(
        provider_config.base_url,
        local_hosts=local_hosts_for_privacy_mode(
            SecurityConfig(
                local_hosts=local_hosts,
                strict_local_hosts=strict_local_hosts,
            ),
            privacy_mode,
        ),
        strict_local=privacy_mode == "strict_local",
    )

    if (
        not provider_selection_explicit
        and privacy_mode == "strict_local"
        and transport_target == "remote"
    ):
        raise AhaDiffError(
            f"{operation_label} requires --provider or --base-url to use a "
            "remote provider while privacy_mode is strict_local"
        )

    effective_api_key = resolve_provider_api_key(provider_config.api_key_env)
    if (
        not effective_api_key
        and provider_config.provider_class != "ollama"
        and transport_target == "remote"
    ):
        raise AhaDiffError(
            f"env var {provider_config.api_key_env!r} is not set (required for remote provider)"
        )

    return provider_config, effective_api_key, transport_target, provider_selection_explicit


def _configured_model_override(
    *,
    snapshot: Any,
    role: str,
    model: str | None,
) -> str | None:
    if model is not None:
        return model
    resolved = getattr(snapshot, "resolved", None)
    if not isinstance(resolved, dict):
        return None
    resolved_settings = cast("dict[str, Any]", resolved)
    setting = resolved_settings.get(f"llm.{role}_model")
    if setting is None or getattr(setting, "source", "default") == "default":
        return None
    value = str(getattr(setting, "value", "")).strip()
    return value or None


def _cleanup_lesson_generation_artifacts(
    *,
    run_path: Path,
    raw_claims_path: Path | None,
    claims_output_path: Path | None,
) -> None:
    for target in (
        raw_claims_path,
        claims_output_path,
        run_path / "lesson",
        run_path / "quiz",
        run_path / "concepts_local.jsonl",
    ):
        if target is None or not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)


def _cleanup_cancelled_run(
    *,
    run_path: Path | None,
    learn_outcome: Any,
) -> None:
    if run_path is None:
        return
    event = getattr(learn_outcome, "event", None)
    event_id = getattr(event, "event_id", None)
    if isinstance(event_id, str) and event_id:
        try:
            from ahadiff.eval.results import rollback_result_event

            rollback_result_event(run_path=run_path, event_id=event_id)
        except Exception:
            log.warning(
                "keeping cancelled run artifacts because result rollback failed",
                exc_info=True,
            )
            return
    if run_path.exists():
        shutil.rmtree(run_path, ignore_errors=True)


def _persist_evaluated_run_sync(
    *,
    run_path: Path,
    report: Any,
    workspace_root: Path,
    event_type: str,
    output_path: Path,
    force: bool,
    note_payload: dict[str, object] | None = None,
) -> tuple[Any, list[str]]:
    from ahadiff.eval.ratchet import decide_learn_ratchet
    from ahadiff.eval.results import (
        append_result,
        load_result_events,
        publish_result_artifacts,
        rollback_result_event,
    )

    db_path = run_path.parent.parent / "review.sqlite"
    decision = decide_learn_ratchet(
        workspace_root=workspace_root,
        report=report,
        prior_events=load_result_events(db_path),
    )
    combined_note_payload = dict(decision.note_payload or {})
    if note_payload:
        combined_note_payload.update(note_payload)
    outcome = append_result(
        run_path=run_path,
        report=report,
        status=decision.status,
        base_ref=decision.base_ref,
        event_type=event_type,
        note_payload=combined_note_payload or None,
        score_path=output_path,
        write_finalized=False,
    )
    warnings = list(outcome.warnings)
    try:
        publish_result_artifacts(
            run_path=run_path,
            report=report,
            event=outcome.event,
            score_path=output_path,
            overwrite=force,
        )
    except Exception as exc:
        if outcome.sqlite_inserted:
            try:
                rollback_result_event(run_path=run_path, event_id=outcome.event.event_id)
            except Exception as rollback_error:
                raise AhaDiffError(
                    "failed to publish score artifacts and failed to roll back "
                    f"result event {outcome.event.event_id}: {rollback_error}"
                ) from rollback_error
        raise AhaDiffError(f"failed to publish score artifacts: {exc}") from exc
    return outcome, warnings


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def _persist_graphify_context(capture: Any, run_path: Path) -> None:
    """Write graphify metadata to ``runs/<run_id>/graphify_context.json``.

    Failures are logged but never block the pipeline.
    """
    gs = getattr(capture, "graphify_status", None)
    if gs is None or not getattr(gs, "has_graph", False):
        return
    try:
        from ahadiff.git.capture import graphify_context_payload_from_capture

        payload = graphify_context_payload_from_capture(capture)
        if payload is None:
            return
        run_path.mkdir(parents=True, exist_ok=True)
        ctx_path = run_path / "graphify_context.json"
        if ctx_path.exists():
            if not stat.S_ISREG(ctx_path.lstat().st_mode):
                log.warning("graphify context path is not a regular file: %s", ctx_path)
            return
        atomic_write_state_text(
            ctx_path,
            _json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
    except Exception:
        log.warning("failed to persist graphify context to %s", run_path, exc_info=True)


def _check_cancelled(is_cancelled: CancelledCheck) -> None:
    if is_cancelled():
        raise AhaDiffError("cancelled")


def run_learn_pipeline(
    request: LearnRequest,
    *,
    on_progress: ProgressCallback | None = None,
    is_cancelled: CancelledCheck | None = None,
) -> LearnResult:
    def _noop_progress(_step: int, _total: int, _msg: str) -> None:
        pass

    def _noop_cancel() -> bool:
        return False

    _progress = on_progress or _noop_progress
    _cancelled = is_cancelled or _noop_cancel

    def _emit(step: int, message: str) -> None:
        _progress(step, _TOTAL_STEPS, message)

    # ------------------------------------------------------------------
    # Step 1: resolve workspace and load config
    # ------------------------------------------------------------------
    _emit(1, "Loading workspace config")
    _check_cancelled(_cancelled)

    allow_non_git = (
        request.patch is not None
        or request.compare is not None
        or request.compare_dir is not None
        or request.patch_url is not None
    )
    try:
        root, has_git_repo = _resolve_workspace_root(request.workspace_root)
    except AhaDiffError:
        if not allow_non_git:
            raise
        root = find_workspace_root(request.workspace_root)
        assert_local_repo_path(root)
        has_git_repo = False

    overrides = _cli_overrides(privacy_mode=request.privacy_mode, lang=request.lang)
    snapshot = (
        load_config(root, cli_overrides=overrides)
        if has_git_repo
        else load_workspace_config(root, cli_overrides=overrides)
    )

    capture_config = cast("dict[str, Any]", snapshot.values["capture"])
    learn_config = cast("dict[str, Any]", snapshot.values["learn"])
    llm_config = cast("dict[str, Any]", snapshot.values["llm"])
    provider_limits = cast("dict[str, Any]", snapshot.values["provider"])
    effective_privacy_mode = str(snapshot.values["privacy_mode"])
    resolved_content_lang = _resolve_output_lang_from_snapshot(snapshot, cli_lang=request.lang)
    security_config = (
        load_security_config(root) if has_git_repo else load_workspace_security_config(root)
    )
    repo_lock_path = lock_file_path(root) if has_git_repo else root / ".ahadiff" / "ahadiff.lock"

    # ------------------------------------------------------------------
    # Step 2: capture patch (under repo lock)
    # ------------------------------------------------------------------
    _emit(2, "Capturing diff")
    _check_cancelled(_cancelled)

    from ahadiff.git.capture import (
        capture_patch,
        write_input_artifacts,
    )
    from ahadiff.git.repo import repo_write_lock

    early_result: LearnResult | None = None
    captured_state_dir: Path | None = None
    run_path: Path | None = None
    raw_claims_path: Path | None = None
    claims_output_path: Path | None = None
    lesson_skip_reason: str | None = None
    learn_report: Any = None
    learn_outcome: Any = None
    learn_warnings: list[str] = []
    provider_config: ProviderConfig | None = None
    effective_api_key: str | None = None
    resolved_privacy_mode: str | None = None

    with repo_write_lock(repo_lock_path, command="learn") as _:
        try:
            capture = capture_patch(
                workspace_root=root,
                revision=request.revision,
                last=request.last,
                since=request.since,
                author=request.author,
                staged=request.staged,
                unstaged=request.unstaged,
                include_untracked=request.include_untracked,
                changed_paths=request.changed_paths,
                patch=request.patch,
                compare=request.compare,
                compare_dir=request.compare_dir,
                patch_url=request.patch_url,
                use_graphify=request.use_graphify,
                max_files=int(capture_config["max_files"]),
                hard_limit=int(capture_config["hard_limit"]),
                max_patch_bytes=int(capture_config["max_patch_bytes"]),
                privacy_mode=effective_privacy_mode,
                content_lang=resolved_content_lang,
            )
            captured_state_dir = capture.state_dir

            # ------------------------------------------------------------------
            # Step 3: assess learnability
            # ------------------------------------------------------------------
            _emit(3, "Assessing learnability")
            _check_cancelled(_cancelled)

            from ahadiff.lesson.learnability import assess_learnability

            learnability = assess_learnability(
                capture.persisted_patch_text,
                threshold=float(learn_config["learnability_threshold"]),
                force_learn=request.force_learn,
            )
            capture.metadata["learnability"] = learnability.as_metadata()
            write_input_artifacts(capture)

            run_path = (
                run_dir(capture.run_id, root)
                if has_git_repo
                else (root / ".ahadiff" / "runs" / capture.run_id)
            )

            # Persist graphify context snapshot into run directory
            _persist_graphify_context(capture, run_path)

            _env_retries_raw = os.environ.get(
                "AHADIFF_PIPELINE_MAX_STEP_RETRIES",
                str(_DEFAULT_MAX_STEP_RETRIES),
            )
            _env_budget_raw = os.environ.get(
                "AHADIFF_PIPELINE_ERROR_BUDGET",
                str(_DEFAULT_ERROR_BUDGET),
            )
            try:
                _parsed_retries = int(_env_retries_raw)
                _parsed_budget = int(_env_budget_raw)
            except ValueError:
                _parsed_retries = _DEFAULT_MAX_STEP_RETRIES
                _parsed_budget = _DEFAULT_ERROR_BUDGET
            error_budget = PipelineErrorBudget(
                max_step_retries=max(0, min(_parsed_retries, 10)),
                max_total_errors=max(1, min(_parsed_budget, 20)),
            )

            if request.dry_run or learnability.skip_lesson_quiz:
                early_result = LearnResult(
                    run_id=capture.run_id,
                    status="dry_run" if request.dry_run else "learnability_skip",
                    artifacts_path=str(run_path),
                    learnability_score=learnability.score,
                    learnability_skip=learnability.skip_lesson_quiz,
                )
            else:
                # ------------------------------------------------------------------
                # Step 4: resolve provider
                # ------------------------------------------------------------------
                _emit(4, "Resolving provider")
                _check_cancelled(_cancelled)

                try:
                    (
                        provider_config,
                        effective_api_key,
                        transport_target,
                        provider_selection_explicit,
                    ) = _resolve_provider_from_config(
                        snapshot=snapshot,
                        operation_label="lesson generation",
                        provider_name=request.provider_name,
                        provider_class=request.provider_class,
                        base_url=request.base_url,
                        model=request.model,
                        api_key_env=request.api_key_env,
                        privacy_mode=effective_privacy_mode,
                        local_hosts=security_config.local_hosts,
                        strict_local_hosts=security_config.strict_local_hosts,
                    )
                    resolved_privacy_mode = _privacy_mode_for_explicit_provider_call(
                        effective_privacy_mode,
                        transport_target=transport_target,
                        provider_selection_explicit=provider_selection_explicit,
                    )
                except Exception:
                    _cleanup_lesson_generation_artifacts(
                        run_path=run_path,
                        raw_claims_path=None,
                        claims_output_path=None,
                    )
                    raise

            if early_result is None:
                assert provider_config is not None  # noqa: S101
                assert resolved_privacy_mode is not None  # noqa: S101

                output_budget = _llm_positive_int(llm_config, "output_token_budget", 50_000)
                claim_output_cap = _step_output_cap(
                    provider_config=provider_config,
                    llm_config=llm_config,
                    output_budget=output_budget,
                    step_name="claim_extraction",
                )
                lesson_output_caps: dict[Literal["full", "hint", "compact"], int] = {
                    "full": _step_output_cap(
                        provider_config=provider_config,
                        llm_config=llm_config,
                        output_budget=output_budget,
                        step_name="lesson_full",
                    ),
                    "hint": _step_output_cap(
                        provider_config=provider_config,
                        llm_config=llm_config,
                        output_budget=output_budget,
                        step_name="lesson_hint",
                    ),
                    "compact": _step_output_cap(
                        provider_config=provider_config,
                        llm_config=llm_config,
                        output_budget=output_budget,
                        step_name="lesson_compact",
                    ),
                }
                quiz_output_cap = _step_output_cap(
                    provider_config=provider_config,
                    llm_config=llm_config,
                    output_budget=output_budget,
                    step_name="quiz_generation",
                )
                misconception_output_cap = _step_output_cap(
                    provider_config=provider_config,
                    llm_config=llm_config,
                    output_budget=output_budget,
                    step_name="misconception_cards",
                )

                # ------------------------------------------------------------------
                # Step 5: extract and verify claims
                # ------------------------------------------------------------------
                _emit(5, "Extracting claims from diff (1/2)")
                _check_cancelled(_cancelled)

                try:
                    from ahadiff.claims.extract import (
                        load_claim_candidates,
                        load_line_map_records,
                        load_symbol_records,
                        load_text_map,
                        write_verified_claims_jsonl,
                    )
                    from ahadiff.claims.runtime import extract_claim_candidates_from_run
                    from ahadiff.claims.verify import verify_claim_candidates

                    def _extract_claims() -> Any:
                        nonlocal raw_claims_path
                        result_path, _ = extract_claim_candidates_from_run(
                            run_id=capture.run_id,
                            run_path=run_path,
                            workspace_root=root,
                            provider_config=provider_config.model_copy(
                                update={"max_output_tokens": claim_output_cap}
                            ),
                            api_key=effective_api_key,
                            security_config=security_config,
                            output_path=run_path / "claims.raw.jsonl",
                            overwrite=False,
                            privacy_mode=cast("PrivacyMode", resolved_privacy_mode),
                            max_concurrent=int(llm_config["max_concurrent"]),
                            qps_limit=int(provider_limits["qps_limit"]),
                            retry_attempts=int(llm_config["retry_attempts"]),
                            request_timeout_seconds=int(llm_config["request_timeout_seconds"]),
                            input_token_budget=int(llm_config.get("input_token_budget", 200000)),
                            output_token_budget=output_budget,
                            claim_output_token_cap=claim_output_cap,
                        )
                        raw_claims_path = result_path
                        return result_path

                    run_with_retry(
                        _extract_claims,
                        step_name="claim_extraction",
                        budget=error_budget,
                        is_cancelled=_cancelled,
                        max_retries_override=_LLM_STEP_MAX_RETRIES,
                    )
                    assert raw_claims_path is not None  # noqa: S101

                    _emit(5, "Verifying extracted claims (2/2)")
                    _check_cancelled(_cancelled)
                    candidates = load_claim_candidates(
                        raw_claims_path,
                        default_run_id=capture.run_id,
                        enforce_run_id_match=True,
                    )
                    line_maps = load_line_map_records(run_path / "line_map.json")
                    symbols = load_symbol_records(run_path / "symbols.json")
                    before_text_by_path = load_text_map(
                        run_path / "before_text_by_path.json",
                        expected_artifact="before_text_by_path",
                    )
                    after_text_by_path = load_text_map(
                        run_path / "after_text_by_path.json",
                        expected_artifact="after_text_by_path",
                    )
                    verified = verify_claim_candidates(
                        candidates,
                        line_maps=line_maps,
                        symbols=symbols,
                        before_text_by_path=before_text_by_path,
                        after_text_by_path=after_text_by_path,
                    )
                    claims_output_path = run_path / "claims.jsonl"
                    write_verified_claims_jsonl(claims_output_path, verified, overwrite=False)

                    verified_claim_count = sum(
                        1 for item in verified if item.record.status == "verified"
                    )
                    if verified_claim_count == 0:
                        lesson_skip_reason = "no verified claims survived verification"
                except Exception as exc:
                    _cleanup_lesson_generation_artifacts(
                        run_path=run_path,
                        raw_claims_path=raw_claims_path,
                        claims_output_path=claims_output_path,
                    )
                    raise AhaDiffError("claim extraction failed") from exc

                if lesson_skip_reason is not None:
                    early_result = LearnResult(
                        run_id=capture.run_id,
                        status="no_verified_claims",
                        artifacts_path=str(run_path),
                        learnability_score=learnability.score,
                        learnability_skip=False,
                        warnings=[lesson_skip_reason],
                        recoverable_errors=error_budget.error_count,
                    )
                else:
                    # ------------------------------------------------------------------
                    # Step 6: generate lessons
                    # ------------------------------------------------------------------
                    _check_cancelled(_cancelled)

                    try:
                        from ahadiff.lesson.generator import generate_lessons_from_run

                        def _generate_lessons() -> None:
                            generate_lessons_from_run(
                                run_id=capture.run_id,
                                run_path=run_path,
                                workspace_root=root,
                                provider_config=provider_config.model_copy(
                                    update={"max_output_tokens": max(lesson_output_caps.values())}
                                ),
                                api_key=effective_api_key,
                                security_config=security_config,
                                request_timeout_seconds=int(llm_config["request_timeout_seconds"]),
                                max_concurrent=int(llm_config["max_concurrent"]),
                                qps_limit=int(provider_limits["qps_limit"]),
                                retry_attempts=int(llm_config["retry_attempts"]),
                                privacy_mode=cast("PrivacyMode", resolved_privacy_mode),
                                output_lang=resolved_content_lang,
                                input_token_budget=int(
                                    llm_config.get("input_token_budget", 200000)
                                ),
                                output_token_budget=output_budget,
                                lesson_output_token_caps=lesson_output_caps,
                                on_sub_progress=lambda message: _emit(6, message),
                            )

                        run_with_retry(
                            _generate_lessons,
                            step_name="lesson_generation",
                            budget=error_budget,
                            is_cancelled=_cancelled,
                            max_retries_override=_LLM_STEP_MAX_RETRIES,
                        )
                    except Exception as exc:
                        _cleanup_lesson_generation_artifacts(
                            run_path=run_path,
                            raw_claims_path=raw_claims_path,
                            claims_output_path=claims_output_path,
                        )
                        raise AhaDiffError("lesson generation failed") from exc

                    # ------------------------------------------------------------------
                    # Step 7: generate quiz
                    # ------------------------------------------------------------------
                    _check_cancelled(_cancelled)

                    try:
                        from ahadiff.quiz.generator import (
                            generate_cards_for_run,
                            generate_quiz_from_run,
                        )

                        quiz_questions_holder: list[Any] = []

                        def _generate_quiz() -> None:
                            _, questions = generate_quiz_from_run(
                                run_id=capture.run_id,
                                run_path=run_path,
                                workspace_root=root,
                                provider_config=provider_config.model_copy(
                                    update={
                                        "max_output_tokens": max(
                                            quiz_output_cap,
                                            misconception_output_cap,
                                        )
                                    }
                                ),
                                api_key=effective_api_key,
                                security_config=security_config,
                                request_timeout_seconds=int(llm_config["request_timeout_seconds"]),
                                max_concurrent=int(llm_config["max_concurrent"]),
                                qps_limit=int(provider_limits["qps_limit"]),
                                retry_attempts=int(llm_config["retry_attempts"]),
                                privacy_mode=cast("PrivacyMode", resolved_privacy_mode),
                                output_lang=resolved_content_lang,
                                input_token_budget=int(
                                    llm_config.get("input_token_budget", 200000)
                                ),
                                output_token_budget=output_budget,
                                quiz_output_token_cap=quiz_output_cap,
                                misconception_output_token_cap=misconception_output_cap,
                                on_sub_progress=lambda message: _emit(7, message),
                            )
                            quiz_questions_holder[:] = [questions]

                        run_with_retry(
                            _generate_quiz,
                            step_name="quiz_generation",
                            budget=error_budget,
                            is_cancelled=_cancelled,
                            max_retries_override=_LLM_STEP_MAX_RETRIES,
                        )
                        quiz_questions = quiz_questions_holder[0]
                    except Exception as exc:
                        _cleanup_lesson_generation_artifacts(
                            run_path=run_path,
                            raw_claims_path=raw_claims_path,
                            claims_output_path=claims_output_path,
                        )
                        raise AhaDiffError("quiz generation failed") from exc

                    # ------------------------------------------------------------------
                    # Step 8: evaluate run
                    # ------------------------------------------------------------------
                    _emit(8, "Evaluating run")
                    _check_cancelled(_cancelled)

                    from ahadiff.eval.evaluator import evaluate_run, run_llm_judge_for_run

                    learn_report = evaluate_run(run_path)

                    judge_provider_name = str(llm_config.get("judge_provider", "")).strip()
                    if judge_provider_name:
                        try:
                            (
                                judge_provider_config,
                                judge_api_key,
                                judge_transport_target,
                                judge_provider_selection_explicit,
                            ) = _resolve_provider_from_config(
                                snapshot=snapshot,
                                operation_label="LLM judge evaluation",
                                provider_name=None,
                                provider_class=request.provider_class,
                                base_url=None,
                                model=None,
                                api_key_env=request.api_key_env,
                                privacy_mode=effective_privacy_mode,
                                local_hosts=security_config.local_hosts,
                                strict_local_hosts=security_config.strict_local_hosts,
                                role="judge",
                            )
                            judge_privacy_mode = _privacy_mode_for_explicit_provider_call(
                                effective_privacy_mode,
                                transport_target=judge_transport_target,
                                provider_selection_explicit=judge_provider_selection_explicit,
                            )

                            def _run_llm_judge() -> None:
                                run_llm_judge_for_run(
                                    run_path=run_path,
                                    workspace_root=root,
                                    provider_config=judge_provider_config,
                                    api_key=judge_api_key,
                                    security_config=security_config,
                                    privacy_mode=cast("PrivacyMode", judge_privacy_mode),
                                    output_lang=resolved_content_lang,
                                    deterministic_report=learn_report,
                                    request_timeout_seconds=int(
                                        llm_config["request_timeout_seconds"]
                                    ),
                                    max_concurrent=int(llm_config["max_concurrent"]),
                                    qps_limit=int(provider_limits["qps_limit"]),
                                    retry_attempts=int(llm_config["retry_attempts"]),
                                    input_token_budget=int(
                                        llm_config.get("input_token_budget", 200000)
                                    ),
                                    output_token_budget=output_budget,
                                )

                            _emit(8, "Evaluating run with LLM judge")
                            run_with_retry(
                                _run_llm_judge,
                                step_name="llm_judge",
                                budget=error_budget,
                                is_cancelled=_cancelled,
                                max_retries_override=_LLM_STEP_MAX_RETRIES,
                            )
                        except Exception as judge_error:
                            learn_warnings.append(f"LLM judge evaluation failed: {judge_error}")

                    generate_cards_for_run(
                        run_path=run_path,
                        questions=quiz_questions,
                        verdict=learn_report.verdict,
                    )

                    # ------------------------------------------------------------------
                    # Step 9: persist evaluated run (ratchet + result event + artifacts)
                    # ------------------------------------------------------------------
                    _emit(9, "Persisting results")
                    _check_cancelled(_cancelled)

                    learn_outcome, learn_warnings = _persist_evaluated_run_sync(
                        run_path=run_path,
                        report=learn_report,
                        workspace_root=root,
                        event_type="learn",
                        output_path=run_path / "score.json",
                        force=False,
                        note_payload={"learnability": learnability.as_metadata()},
                    )

                    try:
                        from ahadiff.review.database import import_cards_from_jsonl

                        import_cards_from_jsonl(
                            run_path.parent.parent / "review.sqlite",
                            run_path / "quiz" / "cards.jsonl",
                            desired_retention=float(learn_config["desired_retention"]),
                        )
                    except Exception as review_import_error:
                        learn_warnings.append(f"review card import failed: {review_import_error}")

                    # ------------------------------------------------------------------
                    # Step 10: append concepts + register repo
                    # ------------------------------------------------------------------
                    _emit(10, "Updating concepts")
                    _check_cancelled(_cancelled)

                    try:
                        from ahadiff.wiki.concepts import append_concepts

                        append_concepts(
                            workspace_root=root,
                            run_path=run_path,
                            run_id=capture.run_id,
                            source_kind=str(capture.run_source.source_kind),
                            source_ref=str(capture.run_source.source_ref),
                            questions=quiz_questions,
                        )
                    except Exception as concept_error:
                        learn_warnings.append(f"concepts append failed: {concept_error}")
                    # Step 10 is the commit boundary for published learn results.
                    # Once concepts write starts, late cancellation must not roll back
                    # finalized artifacts or global concept state.
        except AhaDiffError as exc:
            if str(exc) == "cancelled":
                _cleanup_cancelled_run(run_path=run_path, learn_outcome=learn_outcome)
            raise

    # Outside the repo lock
    try:
        from ahadiff.core.registry import register_repo

        register_repo(root, captured_state_dir or (root / ".ahadiff"))
    except Exception as reg_error:
        warning = f"registry auto-register failed: {reg_error}"
        if early_result is not None:
            early_result.warnings.append(warning)
        else:
            learn_warnings.append(warning)

    if early_result is not None:
        return early_result

    return LearnResult(
        run_id=capture.run_id,
        status=learn_outcome.event.status if learn_outcome else "completed",
        overall=learn_report.overall if learn_report else None,
        verdict=learn_report.verdict if learn_report else None,
        weakest_dim=learn_report.weakest_dim if learn_report else None,
        artifacts_path=str(run_path),
        warnings=learn_warnings,
        learnability_score=learnability.score,
        learnability_skip=False,
        recoverable_errors=error_budget.error_count,
    )


__all__ = [
    "LearnRequest",
    "LearnResult",
    "PipelineErrorBudget",
    "implicit_duplicate_provider_name",
    "is_recoverable_error",
    "is_timeout_or_network_error",
    "run_learn_pipeline",
    "run_with_retry",
]
