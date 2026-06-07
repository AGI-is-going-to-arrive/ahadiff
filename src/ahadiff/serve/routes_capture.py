from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts import ErrorCode
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
from ahadiff.core.paths import assert_local_repo_path, find_repo_root, find_workspace_root

from ._errors import error_response
from .auth import serve_state

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from .state import ServeState


def _workspace_root_for_capture_recommendation(workspace_root: Path) -> tuple[Path, bool]:
    try:
        return find_repo_root(workspace_root), True
    except AhaDiffError:
        ws = find_workspace_root(workspace_root)
        assert_local_repo_path(ws)
        return ws, False


def _recommended_capture_payload(state: ServeState) -> dict[str, Any]:
    state_dir = state.state_dir
    root, has_git_repo = _workspace_root_for_capture_recommendation(state_dir.parent)
    snapshot = load_config(root) if has_git_repo else load_workspace_config(root)
    security_config = (
        load_security_config(root) if has_git_repo else load_workspace_security_config(root)
    )
    capture_config = cast("dict[str, Any]", snapshot.values["capture"])
    recommendation = _effective_capture_recommendation(
        snapshot=snapshot,
        capture_config=capture_config,
        llm_config=cast("dict[str, Any]", snapshot.values["llm"]),
        provider_name=None,
        provider_class="openai",
        base_url=None,
        model=None,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        privacy_mode=str(snapshot.values["privacy_mode"]),
        local_hosts=security_config.local_hosts,
        strict_local_hosts=security_config.strict_local_hosts,
        require_configured_provider=True,
    )
    return asdict(recommendation)


async def get_capture_recommended(request: Request) -> JSONResponse:
    state = serve_state(request)
    try:
        payload = await to_thread.run_sync(_recommended_capture_payload, state)
    except AhaDiffError as exc:
        if _is_provider_not_configured_error(exc):
            return error_response(
                ErrorCode.NOT_FOUND,
                "capture_recommendation_requires_configured_provider",
                status=404,
            )
        if _is_provider_ambiguous_error(exc):
            return error_response(
                ErrorCode.INPUT_VALIDATION,
                "capture_recommendation_requires_generate_provider",
            )
        return error_response(
            exc.code,
            "capture_recommendation_failed",
        )
    return JSONResponse(payload)


def _is_provider_not_configured_error(exc: AhaDiffError) -> bool:
    return "requires --base-url or a configured provider entry under providers.<name>" in str(exc)


def _is_provider_ambiguous_error(exc: AhaDiffError) -> bool:
    message = str(exc)
    return (
        "requires --provider or set generate_provider in [llm] config" in message
        and "when multiple providers are configured" in message
    )


__all__ = ["get_capture_recommended"]
