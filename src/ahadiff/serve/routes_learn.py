from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from anyio.to_thread import run_sync as run_sync_in_thread
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_app import LearnEstimateResponse, LearnEstimateRiskLevel
from ahadiff.contracts.serve_runtime import TaskSubmitResponse
from ahadiff.core.config import load_config, load_workspace_config
from ahadiff.core.errors import AhaDiffError
from ahadiff.core.paths import assert_local_repo_path, find_repo_root, find_workspace_root
from ahadiff.git.capture import capture_patch
from ahadiff.llm.cost import estimate_text_tokens, resolve_context_window

from .auth import require_write_token, serve_state

if TYPE_CHECKING:
    from starlette.requests import Request

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
    {"last", "staged", "unstaged", "include_untracked", "dry_run", "force_learn"}
)
_OPTIONAL_BOOL_FIELDS = frozenset({"use_graphify"})
_PATH_PAIR_FIELDS = frozenset({"compare", "compare_dir"})
_ENUM_FIELDS = {
    "lang": frozenset({"auto", "en", "zh-CN"}),
    "privacy_mode": frozenset({"strict_local", "redacted_remote", "explicit_remote"}),
}
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})
_MAX_STRING_LENGTH = 4096
_MAX_CHANGED_PATHS = 500

_MAX_PENDING_TASKS = 1
_DANGER_CONTEXT_RATIO = 0.8
_WARN_CONTEXT_RATIO = 0.5
_WARN_FILE_COUNT = 30
_DANGER_FILE_COUNT = 50


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
        coerced.append(item)
    return tuple(coerced)


def _coerce_field(key: str, value: object) -> object:
    if key == "changed_paths":
        return _coerce_changed_paths(value)
    if key in _BOOL_FIELDS:
        return _coerce_bool(value)
    if key in _OPTIONAL_BOOL_FIELDS:
        return _coerce_optional_bool(value)
    if key in _PATH_PAIR_FIELDS:
        return _coerce_path_pair(key, value)
    return _coerce_string(key, value)


async def _parse_learn_request_body(
    request: Request,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    try:
        raw_body_object = cast("object", await request.json())
    except Exception:
        return None, JSONResponse(
            {"error": "invalid_json", "status": 400},
            status_code=400,
        )

    if not isinstance(raw_body_object, dict):
        return None, JSONResponse(
            {"error": "body_must_be_object", "status": 400},
            status_code=400,
        )
    raw_body = cast("dict[str, object]", raw_body_object)

    unknown_fields = set(raw_body) - _ACCEPTED_FIELDS
    if unknown_fields:
        return None, JSONResponse(
            {"error": f"unknown_fields: {', '.join(sorted(unknown_fields))}", "status": 422},
            status_code=422,
        )

    params: dict[str, Any] = {}
    for k, v in raw_body.items():
        if k in _ACCEPTED_FIELDS and v is not None:
            try:
                coerced = _coerce_field(k, v)
            except (ValueError, TypeError):
                return None, JSONResponse(
                    {"error": f"invalid_value_for_{k}", "status": 422},
                    status_code=422,
                )
            if k not in _IGNORED_FIELDS:
                params[k] = coerced
    if params.get("patch") == "-":
        return None, JSONResponse(
            {"error": "invalid_value_for_patch", "status": 422},
            status_code=422,
        )
    return params, None


def _resolve_workspace_root_for_estimate(workspace_root: Path) -> tuple[Path, bool]:
    try:
        return find_repo_root(workspace_root), True
    except AhaDiffError:
        ws = find_workspace_root(workspace_root)
        assert_local_repo_path(ws)
        return ws, False


def _provider_limits_from_config(
    *,
    root: Path,
    has_git_repo: bool,
    params: dict[str, Any],
) -> tuple[int, int | None]:
    from ahadiff.core.orchestrator import (
        _resolve_provider_from_config,  # pyright: ignore[reportPrivateUsage]
    )

    cli_overrides = {"privacy_mode": params.get("privacy_mode"), "lang": params.get("lang")}
    snapshot = (
        load_config(root, cli_overrides=cli_overrides)
        if has_git_repo
        else load_workspace_config(root, cli_overrides=cli_overrides)
    )
    llm_config = cast("dict[str, Any]", snapshot.values["llm"])
    try:
        provider_config, _, _, _ = _resolve_provider_from_config(
            snapshot=snapshot,
            operation_label="learn estimate",
            provider_name=None,
            provider_class="openai",
            base_url=None,
            model=None,
            api_key_env="AHADIFF_PROVIDER_API_KEY",
            privacy_mode=str(snapshot.values["privacy_mode"]),
            local_hosts=(),
            strict_local_hosts=(),
        )
        return (
            resolve_context_window(provider_config.model_name, provider_config.probed_max_context),
            provider_config.max_output_tokens,
        )
    except AhaDiffError:
        model_name = str(llm_config.get("generate_model", "gpt-5.4-mini"))
        max_output = int(llm_config.get("output_token_budget", 50000))
        return resolve_context_window(model_name, None), max_output


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


def _estimate_risk(
    *,
    estimated_tokens: int,
    context_window: int,
    patch_bytes: int,
    max_patch_bytes: int,
    file_count: int,
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
    if file_count > _DANGER_FILE_COUNT:
        danger_warnings.append(f"File count {file_count} exceeds {_DANGER_FILE_COUNT}")
    elif file_count > _WARN_FILE_COUNT:
        warn_warnings.append(f"File count {file_count} exceeds {_WARN_FILE_COUNT}")
    if danger_warnings:
        return "danger", [*danger_warnings, *warn_warnings]
    if warn_warnings:
        return "warn", warn_warnings
    return "ok", []


async def post_learn_estimate(request: Request) -> JSONResponse:
    """POST /api/learn/estimate -- capture and estimate a learn run without LLM calls."""
    require_write_token(request)
    state = serve_state(request)
    params, error_response = await _parse_learn_request_body(request)
    if error_response is not None:
        return error_response
    assert params is not None  # noqa: S101

    workspace_root = state.state_dir.parent
    root, has_git_repo = _resolve_workspace_root_for_estimate(workspace_root)
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
    max_patch_bytes = int(capture_config["max_patch_bytes"])
    from ahadiff.i18n import resolve_locale

    content_lang = resolve_locale(
        cli_lang=cast("str | None", params.get("lang")),
        config_lang=str(snapshot.values.get("lang", "en")),
    )

    capture = capture_patch(
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
        compare=cast("tuple[Path, Path] | None", params.get("compare")),
        compare_dir=cast("tuple[Path, Path] | None", params.get("compare_dir")),
        patch_url=cast("str | None", params.get("patch_url")),
        use_graphify=cast("bool | None", params.get("use_graphify")),
        max_files=int(capture_config["max_files"]),
        hard_limit=int(capture_config["hard_limit"]),
        max_patch_bytes=max_patch_bytes,
        privacy_mode=str(snapshot.values["privacy_mode"]),
        content_lang=content_lang,
    )
    patch_text = str(capture.persisted_patch_text)
    patch_bytes = len(patch_text.encode("utf-8"))
    file_count = _file_count_from_capture(capture)
    total_lines = len(patch_text.splitlines())
    estimated_tokens = estimate_text_tokens(patch_text, "char_div_4")
    context_window, provider_max_output = _provider_limits_from_config(
        root=root,
        has_git_repo=has_git_repo,
        params=params,
    )
    risk_level, warnings = _estimate_risk(
        estimated_tokens=estimated_tokens,
        context_window=context_window,
        patch_bytes=patch_bytes,
        max_patch_bytes=max_patch_bytes,
        file_count=file_count,
    )
    response = LearnEstimateResponse(
        patch_bytes=patch_bytes,
        file_count=file_count,
        total_lines=total_lines,
        estimated_tokens=estimated_tokens,
        provider_context_window=context_window,
        provider_max_output=provider_max_output,
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
        return JSONResponse(
            {"error": "task_runner_unavailable", "status": 503},
            status_code=503,
        )

    params, error_response = await _parse_learn_request_body(request)
    if error_response is not None:
        return error_response
    assert params is not None  # noqa: S101

    workspace_root = state.state_dir.parent

    if not params.get("lang"):
        cookie_lang = request.cookies.get("ahadiff_lang")
        if cookie_lang in {"en", "zh-CN"}:
            params["lang"] = cookie_lang

    from ahadiff.core.orchestrator import LearnRequest, run_learn_pipeline

    learn_request = LearnRequest(workspace_root=workspace_root, **params)

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
    )
    if task_id is None:
        return JSONResponse(
            {"error": "too_many_pending_learn_tasks", "status": 503},
            status_code=503,
        )
    return JSONResponse(
        TaskSubmitResponse(task_id=task_id).model_dump(mode="json"),
        status_code=202,
    )


__all__ = ["post_learn", "post_learn_estimate"]
