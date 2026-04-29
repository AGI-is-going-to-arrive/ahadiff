from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from anyio.to_thread import run_sync as run_sync_in_thread
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_runtime import TaskSubmitResponse

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
    }
)

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

_MAX_PENDING_TASKS = 5


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


def _coerce_field(key: str, value: object) -> object:
    if key in _BOOL_FIELDS:
        return _coerce_bool(value)
    if key in _OPTIONAL_BOOL_FIELDS:
        return _coerce_optional_bool(value)
    if key in _PATH_PAIR_FIELDS:
        return _coerce_path_pair(key, value)
    return _coerce_string(key, value)


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

    try:
        raw_body_object = cast("object", await request.json())
    except Exception:
        return JSONResponse(
            {"error": "invalid_json", "status": 400},
            status_code=400,
        )

    if not isinstance(raw_body_object, dict):
        return JSONResponse(
            {"error": "body_must_be_object", "status": 400},
            status_code=400,
        )
    raw_body = cast("dict[str, object]", raw_body_object)

    params: dict[str, Any] = {}
    for k, v in raw_body.items():
        if k in _ACCEPTED_FIELDS and v is not None:
            try:
                params[k] = _coerce_field(k, v)
            except (ValueError, TypeError):
                return JSONResponse(
                    {"error": f"invalid_value_for_{k}", "status": 422},
                    status_code=422,
                )
    if params.get("patch") == "-":
        return JSONResponse(
            {"error": "invalid_value_for_patch", "status": 422},
            status_code=422,
        )

    workspace_root = state.state_dir.parent

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
        }

    task_id = runner.submit_if_capacity(
        "learn",
        _learn_task,
        max_pending=_MAX_PENDING_TASKS,
        disable_timeout=True,
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


__all__ = ["post_learn"]
