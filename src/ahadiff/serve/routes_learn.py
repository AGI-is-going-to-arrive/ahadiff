from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from anyio.to_thread import run_sync as run_sync_in_thread
from starlette.responses import JSONResponse

from ahadiff.contracts import ErrorCode
from ahadiff.contracts.serve_app import LearnEstimateResponse, LearnEstimateRiskLevel
from ahadiff.contracts.serve_runtime import TaskSubmitResponse
from ahadiff.core.budget import compute_cjk_factor
from ahadiff.core.config import (
    load_config,
    load_security_config,
    load_workspace_config,
    load_workspace_security_config,
)
from ahadiff.core.errors import AhaDiffError
from ahadiff.core.orchestrator import (
    _effective_capture_recommendation,  # pyright: ignore[reportPrivateUsage]
)
from ahadiff.core.paths import assert_local_repo_path, find_repo_root
from ahadiff.git.capture import capture_patch
from ahadiff.git.repo import repo_write_lock
from ahadiff.llm.cost import estimate_text_tokens
from ahadiff.safety.ignore import resolve_safe_path_from_root

from ._errors import error_response
from .auth import require_write_token, serve_state
from .lock import serve_repo_write_lock

if TYPE_CHECKING:
    from starlette.requests import Request

    from ahadiff.core.budget import CaptureRecommendation
    from ahadiff.core.task_runner import TaskHandle

_ACCEPTED_FIELDS = frozenset(
    {
        "revision",
        "last",
        "since",
        "author",
        "staged",
        "unstaged",
        "include_untracked",
        "patch",
        "compare",
        "compare_dir",
        "against_spec",
        "spec_semantic_review",
        "patch_url",
        "dry_run",
        "force_learn",
        "use_graphify",
        "lang",
        "privacy_mode",
        "changed_paths",
    }
)
_IGNORED_FIELDS: frozenset[str] = frozenset()

_BOOL_FIELDS = frozenset(
    {
        "last",
        "staged",
        "unstaged",
        "include_untracked",
        "dry_run",
        "force_learn",
        "spec_semantic_review",
    }
)
_OPTIONAL_BOOL_FIELDS = frozenset({"use_graphify"})
_PATH_PAIR_FIELDS = frozenset({"compare", "compare_dir"})
_PATH_FIELDS = frozenset({"against_spec"})
_ENUM_FIELDS = {
    "lang": frozenset({"auto", "en", "zh-CN"}),
    "privacy_mode": frozenset({"strict_local", "redacted_remote", "explicit_remote"}),
}
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})
_MAX_STRING_LENGTH = 4096
_MAX_CHANGED_PATHS = 500
_RUN_IN_PROGRESS_ERROR = "run_in_progress"

_MAX_PENDING_TASKS = 1
_DANGER_CONTEXT_RATIO = 0.8
_WARN_CONTEXT_RATIO = 0.5
_WARN_FILE_COUNT = 30
_DANGER_FILE_COUNT = 50
_REDACTED_PATCH_TASK_ERROR = "learn task failed; pasted patch details were redacted"


def _contains_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _looks_like_windows_absolute_or_unc_path(value: str) -> bool:
    if value.startswith(("\\\\", "//")):
        return True
    return len(value) >= 2 and value[1] == ":" and value[0].isalpha()


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise ValueError("expected boolean-compatible integer")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    raise ValueError("expected boolean-compatible value")


def _coerce_optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    return _coerce_bool(value)


def _coerce_string(key: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{key} expects string value")
    if len(value) > _MAX_STRING_LENGTH:
        raise ValueError(f"{key} exceeds max length")
    allowed_values = _ENUM_FIELDS.get(key)
    if allowed_values is not None and value not in allowed_values:
        raise ValueError(f"{key} must be one of {sorted(allowed_values)!r}")
    return value


def _coerce_patch_text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("patch expects string value")
    return value


def _coerce_path_pair(key: str, value: object) -> tuple[Path, Path]:
    if not isinstance(value, list | tuple):
        raise TypeError(f"{key} expects a two-item path array")
    raw_paths = cast("tuple[object, ...] | list[object]", value)
    if len(raw_paths) != 2:
        raise ValueError(f"{key} expects exactly two paths")

    coerced: list[Path] = []
    for item in raw_paths:
        if not isinstance(item, str):
            raise TypeError(f"{key} path entries must be strings")
        if len(item) > _MAX_STRING_LENGTH:
            raise ValueError(f"{key} path exceeds max length")
        coerced.append(Path(item))
    return coerced[0], coerced[1]


def _coerce_path(key: str, value: object) -> Path:
    if not isinstance(value, str):
        raise TypeError(f"{key} expects string path value")
    if len(value) > _MAX_STRING_LENGTH:
        raise ValueError(f"{key} exceeds max length")
    return Path(value)


def _coerce_changed_paths(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise TypeError("changed_paths expects a path array")
    raw_paths = cast("tuple[object, ...] | list[object]", value)
    if len(raw_paths) > _MAX_CHANGED_PATHS:
        raise ValueError("changed_paths exceeds max length")
    coerced: list[str] = []
    for item in raw_paths:
        if not isinstance(item, str):
            raise TypeError("changed_paths entries must be strings")
        if len(item) > _MAX_STRING_LENGTH:
            raise ValueError("changed_paths entry exceeds max length")
        if item.strip() == "":
            raise ValueError("changed_paths entry must not be empty")
        if _contains_control_chars(item):
            raise ValueError("changed_paths entry contains control characters")
        normalized = item.replace("\\", "/")
        path = Path(normalized)
        if path.is_absolute() or _looks_like_windows_absolute_or_unc_path(item):
            raise ValueError("changed_paths entries must be repository-relative paths")
        if any(part in {"", ".", ".."} for part in path.parts) or normalized in {"", "."}:
            raise ValueError("changed_paths entry escapes repository root")
        if normalized.startswith((".git/", ".ahadiff/")) or normalized in {".git", ".ahadiff"}:
            raise ValueError("changed_paths entry targets an internal repository directory")
        coerced.append(item)
    return tuple(coerced)


def _coerce_field(key: str, value: object) -> object:
    if key == "changed_paths":
        return _coerce_changed_paths(value)
    if key == "patch":
        return _coerce_patch_text(value)
    if key in _BOOL_FIELDS:
        return _coerce_bool(value)
    if key in _OPTIONAL_BOOL_FIELDS:
        return _coerce_optional_bool(value)
    if key in _PATH_PAIR_FIELDS:
        return _coerce_path_pair(key, value)
    if key in _PATH_FIELDS:
        return _coerce_path(key, value)
    return _coerce_string(key, value)


def _invalid_value_response(key: str, message: str | None = None) -> JSONResponse:
    details = {"field": key}
    if message:
        details["reason"] = message
    return error_response(
        ErrorCode.INPUT_VALIDATION,
        f"invalid_value_for_{key}",
        details=details,
    )


def _route_patch_as_inline_text(params: dict[str, Any]) -> None:
    patch = params.pop("patch", None)
    if patch is not None:
        params["patch_text"] = patch


async def _parse_learn_request_body(
    request: Request,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    try:
        raw_body_object = cast("object", await request.json())
    except Exception:
        return None, error_response(ErrorCode.INPUT_INVALID_JSON, "invalid_json")

    if not isinstance(raw_body_object, dict):
        return None, error_response(ErrorCode.INPUT_BAD_FIELD, "body_must_be_object")
    raw_body = cast("dict[str, object]", raw_body_object)

    unknown_fields = set(raw_body) - _ACCEPTED_FIELDS
    if unknown_fields:
        return None, error_response(
            ErrorCode.INPUT_UNKNOWN_KEYS,
            f"unknown_fields: {', '.join(sorted(unknown_fields))}",
            status=422,
            details={"fields": sorted(unknown_fields)},
        )

    params: dict[str, Any] = {}
    for k, v in raw_body.items():
        if k in _ACCEPTED_FIELDS and v is not None:
            try:
                coerced = _coerce_field(k, v)
            except (ValueError, TypeError) as exc:
                return None, _invalid_value_response(k, str(exc))
            if k not in _IGNORED_FIELDS:
                params[k] = coerced
    if params.get("patch") == "-":
        return None, _invalid_value_response("patch", "stdin patch input is not supported")
    _route_patch_as_inline_text(params)
    return params, None


def _resolve_against_spec_param(root: Path, params: dict[str, Any]) -> JSONResponse | None:
    raw_path = params.get("against_spec")
    if raw_path is None:
        return None
    path = cast("Path", raw_path)
    path_text = str(path)
    if "://" in path_text:
        return _invalid_value_response(
            "against_spec",
            "against_spec only accepts a local workspace file path",
        )
    if _contains_control_chars(path_text):
        return _invalid_value_response("against_spec", "against_spec contains control characters")
    try:
        params["against_spec"] = resolve_safe_path_from_root(root, path)
    except AhaDiffError as exc:
        return _invalid_value_response("against_spec", str(exc))
    return None


def _validate_git_filter_param(key: str, params: dict[str, Any]) -> JSONResponse | None:
    value = params.get(key)
    if value is None:
        return None
    text = cast("str", value)
    if text.startswith("-"):
        return _invalid_value_response(key, f"{key} must not start with '-'")
    if _contains_control_chars(text):
        return _invalid_value_response(key, f"{key} contains control characters")
    return None


def _validate_git_filter_params(params: dict[str, Any]) -> JSONResponse | None:
    for key in ("since", "author"):
        error = _validate_git_filter_param(key, params)
        if error is not None:
            return error
    return None


def _resolve_workspace_root_for_estimate(workspace_root: Path) -> tuple[Path, bool]:
    try:
        return find_repo_root(workspace_root), True
    except AhaDiffError:
        ws = workspace_root.resolve()
        assert_local_repo_path(ws)
        return ws, False


def _workspace_root_from_state_dir(state_dir: Path) -> Path:
    return state_dir.parent if state_dir.name == ".ahadiff" else state_dir


def _file_count_from_capture(capture: object) -> int:
    metadata = getattr(capture, "metadata", None)
    if isinstance(metadata, dict):
        typed_metadata = cast("dict[str, object]", metadata)
        selected_files = typed_metadata.get("selected_files")
        if isinstance(selected_files, list | tuple):
            selected_files = cast("list[object] | tuple[object, ...]", selected_files)
            return len(selected_files)
    after_text_by_path = getattr(capture, "after_text_by_path", None)
    if isinstance(after_text_by_path, dict):
        after_text_by_path = cast("dict[object, object]", after_text_by_path)
        return len(after_text_by_path)
    before_text_by_path = getattr(capture, "before_text_by_path", None)
    if isinstance(before_text_by_path, dict):
        before_text_by_path = cast("dict[object, object]", before_text_by_path)
        return len(before_text_by_path)
    return 0


def _learn_conflict_response() -> JSONResponse:
    return error_response(
        ErrorCode.LOCK_CONFLICT,
        _RUN_IN_PROGRESS_ERROR,
        status=409,
    )


def _precheck_repo_write_lock(state: Any) -> JSONResponse | None:
    repo_lock_path = getattr(state, "repo_lock_path", None)
    thread_write_lock = getattr(state, "thread_write_lock", None)
    if not isinstance(repo_lock_path, Path) or thread_write_lock is None:
        return None

    acquired = bool(thread_write_lock.acquire(False))
    if not acquired:
        return _learn_conflict_response()
    try:
        try:
            with repo_write_lock(repo_lock_path, command="serve learn precheck"):
                return None
        except AhaDiffError as exc:
            if exc.code is ErrorCode.LOCK_CONFLICT:
                return _learn_conflict_response()
            return error_response(exc.code, str(exc) or "repo_write_lock_unavailable")
    finally:
        thread_write_lock.release()


def _assert_sqlite_runtime_supported_for_learn() -> None:
    from ahadiff.review import database as review_database

    review_database._assert_sqlite_runtime_supported()  # pyright: ignore[reportPrivateUsage]


def _precheck_sqlite_runtime_for_learn() -> JSONResponse | None:
    try:
        _assert_sqlite_runtime_supported_for_learn()
    except AhaDiffError as exc:
        return error_response(ErrorCode.STORAGE_REVIEW_DB, str(exc))
    return None


def _estimate_risk(
    *,
    estimated_tokens: int,
    context_window: int,
    patch_bytes: int,
    max_patch_bytes: int,
    file_count: int,
    capture_mode: str = "manual",
    diff_clipped: bool = False,
    omitted_files_count: int = 0,
) -> tuple[LearnEstimateRiskLevel, list[str]]:
    danger_warnings: list[str] = []
    warn_warnings: list[str] = []
    if estimated_tokens > int(context_window * _DANGER_CONTEXT_RATIO):
        danger_warnings.append(
            f"Estimated tokens {estimated_tokens} exceed 80% of context window {context_window}"
        )
    elif estimated_tokens > int(context_window * _WARN_CONTEXT_RATIO):
        warn_warnings.append(
            f"Estimated tokens {estimated_tokens} exceed 50% of context window {context_window}"
        )
    if patch_bytes > max_patch_bytes:
        danger_warnings.append(
            f"Patch size {patch_bytes} bytes exceeds capture.max_patch_bytes {max_patch_bytes}"
        )
    if capture_mode == "auto":
        if omitted_files_count > 0:
            warn_warnings.append(f"Capture omitted {omitted_files_count} files")
        if diff_clipped:
            warn_warnings.append("Diff was clipped by effective capture limits")
    else:
        if file_count > _DANGER_FILE_COUNT:
            danger_warnings.append(f"File count {file_count} exceeds {_DANGER_FILE_COUNT}")
        elif file_count > _WARN_FILE_COUNT:
            warn_warnings.append(f"File count {file_count} exceeds {_WARN_FILE_COUNT}")
    if danger_warnings:
        return "danger", [*danger_warnings, *warn_warnings]
    if warn_warnings:
        return "warn", warn_warnings
    return "ok", []


def _omitted_files_count_from_capture(capture: object) -> int:
    metadata = getattr(capture, "metadata", None)
    if not isinstance(metadata, dict):
        return 0
    omitted = cast("dict[str, object]", metadata).get("omitted_files")
    if isinstance(omitted, list | tuple):
        omitted = cast("list[object] | tuple[object, ...]", omitted)
        return len(omitted)
    return 0


def _diff_clipped_from_capture(capture: object) -> bool:
    metadata = getattr(capture, "metadata", None)
    if not isinstance(metadata, dict):
        return False
    typed_metadata = cast("dict[str, object]", metadata)
    degraded_flags = typed_metadata.get("degraded_flags")
    if not isinstance(degraded_flags, dict):
        return False
    typed_flags = cast("dict[object, object]", degraded_flags)
    return typed_flags.get("diff_clipped") is True


def _capture_recommendation_for_estimate(
    *,
    root: Path,
    has_git_repo: bool,
    snapshot: object,
    capture_config: dict[str, Any],
    cjk_factor: float = 1.0,
) -> CaptureRecommendation:
    security_config = (
        load_security_config(root) if has_git_repo else load_workspace_security_config(root)
    )
    return _effective_capture_recommendation(
        snapshot=snapshot,
        capture_config=capture_config,
        llm_config=cast("dict[str, Any]", cast("Any", snapshot).values["llm"]),
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode=str(cast("Any", snapshot).values["privacy_mode"]),
        local_hosts=security_config.local_hosts,
        strict_local_hosts=security_config.strict_local_hosts,
        cjk_factor=cjk_factor,
    )


async def post_learn_estimate(request: Request) -> JSONResponse:
    """POST /api/learn/estimate -- capture and estimate a learn run without LLM calls."""
    require_write_token(request)
    state = serve_state(request)
    params, parse_error = await _parse_learn_request_body(request)
    if parse_error is not None:
        return parse_error
    assert params is not None  # noqa: S101

    workspace_root = _workspace_root_from_state_dir(state.state_dir)
    root, has_git_repo = _resolve_workspace_root_for_estimate(workspace_root)
    against_spec_error = _resolve_against_spec_param(root, params)
    if against_spec_error is not None:
        return against_spec_error
    git_filter_error = _validate_git_filter_params(params)
    if git_filter_error is not None:
        return git_filter_error
    if not params.get("lang"):
        cookie_lang = request.cookies.get("ahadiff_lang")
        if cookie_lang in {"en", "zh-CN"}:
            params["lang"] = cookie_lang

    cli_overrides = {"privacy_mode": params.get("privacy_mode"), "lang": params.get("lang")}
    snapshot = (
        load_config(root, cli_overrides=cli_overrides)
        if has_git_repo
        else load_workspace_config(root, cli_overrides=cli_overrides)
    )
    capture_config = cast("dict[str, Any]", snapshot.values["capture"])
    effective_capture_limits = _capture_recommendation_for_estimate(
        root=root,
        has_git_repo=has_git_repo,
        snapshot=snapshot,
        capture_config=capture_config,
    )
    max_patch_bytes = effective_capture_limits.max_patch_bytes
    from ahadiff.i18n import resolve_locale

    content_lang = resolve_locale(
        cli_lang=cast("str | None", params.get("lang")),
        config_lang=str(snapshot.values.get("lang", "en")),
    )

    def capture_with_limits(limits: CaptureRecommendation) -> Any:
        return capture_patch(
            workspace_root=root,
            revision=cast("str | None", params.get("revision")),
            last=bool(params.get("last", False)),
            since=cast("str | None", params.get("since")),
            author=cast("str | None", params.get("author")),
            staged=bool(params.get("staged", False)),
            unstaged=bool(params.get("unstaged", False)),
            include_untracked=bool(params.get("include_untracked", False)),
            changed_paths=cast("tuple[str, ...] | None", params.get("changed_paths")),
            patch=cast("str | None", params.get("patch")),
            patch_text=cast("str | None", params.get("patch_text")),
            compare=cast("tuple[Path, Path] | None", params.get("compare")),
            compare_dir=cast("tuple[Path, Path] | None", params.get("compare_dir")),
            patch_url=cast("str | None", params.get("patch_url")),
            use_graphify=cast("bool | None", params.get("use_graphify")),
            max_files=limits.max_files,
            hard_limit=limits.hard_limit,
            max_patch_bytes=limits.max_patch_bytes,
            privacy_mode=str(snapshot.values["privacy_mode"]),
            content_lang=content_lang,
        )

    def _capture_estimate_with_lock() -> tuple[Any, str, int, CaptureRecommendation, int]:
        locked_limits = effective_capture_limits
        locked_max_patch_bytes = max_patch_bytes
        with serve_repo_write_lock(state, command="serve learn estimate"):
            capture = capture_with_limits(locked_limits)
            patch_text = str(capture.persisted_patch_text)
            patch_bytes = len(patch_text.encode("utf-8"))
            if locked_limits.mode != "auto":
                return capture, patch_text, patch_bytes, locked_limits, locked_max_patch_bytes
            adjusted_capture_limits = _capture_recommendation_for_estimate(
                root=root,
                has_git_repo=has_git_repo,
                snapshot=snapshot,
                capture_config=capture_config,
                cjk_factor=compute_cjk_factor(patch_text),
            )
            if (
                adjusted_capture_limits.max_patch_bytes < locked_limits.max_patch_bytes
                and patch_bytes > adjusted_capture_limits.max_patch_bytes
            ):
                capture = capture_with_limits(adjusted_capture_limits)
                patch_text = str(capture.persisted_patch_text)
                patch_bytes = len(patch_text.encode("utf-8"))
            return (
                capture,
                patch_text,
                patch_bytes,
                adjusted_capture_limits,
                adjusted_capture_limits.max_patch_bytes,
            )

    (
        capture,
        patch_text,
        patch_bytes,
        effective_capture_limits,
        max_patch_bytes,
    ) = await run_sync_in_thread(_capture_estimate_with_lock)
    file_count = _file_count_from_capture(capture)
    total_lines = len(patch_text.splitlines())
    estimated_tokens = estimate_text_tokens(patch_text, "char_div_4")
    diff_clipped = _diff_clipped_from_capture(capture)
    omitted_files_count = _omitted_files_count_from_capture(capture)
    context_window = (
        effective_capture_limits.context_window or effective_capture_limits.max_input_tokens
    )
    provider_max_output = effective_capture_limits.max_output_tokens
    risk_level, warnings = _estimate_risk(
        estimated_tokens=estimated_tokens,
        context_window=context_window,
        patch_bytes=patch_bytes,
        max_patch_bytes=max_patch_bytes,
        file_count=file_count,
        capture_mode=effective_capture_limits.mode,
        diff_clipped=diff_clipped,
        omitted_files_count=omitted_files_count,
    )
    response = LearnEstimateResponse(
        patch_bytes=patch_bytes,
        file_count=file_count,
        total_lines=total_lines,
        estimated_tokens=estimated_tokens,
        provider_context_window=context_window,
        provider_max_output=provider_max_output,
        effective_capture_limits=effective_capture_limits,
        diff_clipped=diff_clipped,
        omitted_files_count=omitted_files_count,
        risk_level=risk_level,
        warnings=warnings,
    )
    return JSONResponse(response.model_dump(mode="json"))


async def post_learn(request: Request) -> JSONResponse:
    """POST /api/learn -- submit a learn pipeline run to the task runner."""
    require_write_token(request)
    state = serve_state(request)
    runner = state.task_runner
    if runner is None:
        return error_response(
            ErrorCode.REQUEST_TIMEOUT,
            "task_runner_unavailable",
            status=503,
        )

    params, parse_error = await _parse_learn_request_body(request)
    if parse_error is not None:
        return parse_error
    assert params is not None  # noqa: S101

    workspace_root = _workspace_root_from_state_dir(state.state_dir)
    root, _has_git_repo = _resolve_workspace_root_for_estimate(workspace_root)
    against_spec_error = _resolve_against_spec_param(root, params)
    if against_spec_error is not None:
        return against_spec_error
    git_filter_error = _validate_git_filter_params(params)
    if git_filter_error is not None:
        return git_filter_error
    lock_error = _precheck_repo_write_lock(state)
    if lock_error is not None:
        return lock_error
    sqlite_error = _precheck_sqlite_runtime_for_learn()
    if sqlite_error is not None:
        return sqlite_error

    if not params.get("lang"):
        cookie_lang = request.cookies.get("ahadiff_lang")
        if cookie_lang in {"en", "zh-CN"}:
            params["lang"] = cookie_lang

    from ahadiff.core.orchestrator import LearnRequest, run_learn_pipeline

    learn_request = LearnRequest(workspace_root=workspace_root, **params)
    has_sensitive_patch_text = learn_request.patch_text is not None

    async def _learn_task(handle: TaskHandle) -> dict[str, Any]:
        def _on_progress(step: int, total: int, message: str) -> None:
            handle.update_progress(step, total, message)

        def _is_cancelled() -> bool:
            return handle.is_cancelled()

        result = await run_sync_in_thread(
            lambda: run_learn_pipeline(
                learn_request,
                on_progress=_on_progress,
                is_cancelled=_is_cancelled,
            )
        )

        return {
            "run_id": result.run_id,
            "status": result.status,
            "overall": result.overall,
            "verdict": result.verdict,
            "weakest_dim": result.weakest_dim,
            "warnings": result.warnings,
            "recoverable_errors": result.recoverable_errors,
        }

    task_id = runner.submit_if_capacity(
        "learn",
        _learn_task,
        max_pending=_MAX_PENDING_TASKS,
        thread_backed=True,
        redact_errors=has_sensitive_patch_text,
        redacted_error_message=_REDACTED_PATCH_TASK_ERROR,
    )
    if task_id is None:
        return error_response(
            ErrorCode.LOCK_CONFLICT,
            "too_many_pending_learn_tasks",
            status=409,
        )
    return JSONResponse(
        TaskSubmitResponse(task_id=task_id).model_dump(mode="json"),
        status_code=202,
    )


__all__ = ["post_learn", "post_learn_estimate"]
