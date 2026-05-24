"""Install target endpoints for preview and protected local writes."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
from typing import TYPE_CHECKING, Any, Literal, cast

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_install import (
    InstallMutationRequest,
    InstallPreviewRequest,
    InstallTargetMutationResponse,
    InstallTargetPreviewResponse,
    InstallTargetsResponse,
)
from ahadiff.core.errors import InputError
from ahadiff.install.base import InstallContext
from ahadiff.install.common import manifest_preview_for
from ahadiff.install.registry import available_targets, get_target
from ahadiff.install.usage_hints import get_usage_hint

from .auth import require_write_token, serve_state
from .locale import request_locale
from .lock import serve_repo_write_lock

if TYPE_CHECKING:
    from starlette.requests import Request

    from .state import ServeState

log = logging.getLogger(__name__)

_TARGET_DESCRIPTIONS = {
    "aider": "Write AhaDiff guidance for Aider.",
    "antigravity": "Write Antigravity IDE workspace skill and AhaDiff rules.",
    "antigravity-cli": "Write Antigravity CLI workspace skill and GEMINI.md guidance.",
    "claude": "Write Claude Code project instructions and skills.",
    "cline": "Write AhaDiff instructions for Cline.",
    "codex": "Write Codex AGENTS.md guidance.",
    "continue": "Write AhaDiff instructions for Continue.",
    "copilot": "Write GitHub Copilot instructions.",
    "cursor": "Write Cursor rules for AhaDiff.",
    "gemini": "Write Gemini CLI guidance.",
    "github-action": "Write the GitHub Actions workflow template.",
    "hooks": "Write local git hook integration files.",
    "opencode": "Write OpenCode agent instructions.",
    "roo": "Write AhaDiff instructions for Roo.",
    "windsurf": "Write Windsurf rules for AhaDiff.",
}

_TARGET_DISPLAY_NAMES = {
    "antigravity": "Antigravity IDE",
    "antigravity-cli": "Antigravity CLI",
    "claude": "Claude Code",
    "codex": "Codex CLI",
    "copilot": "Copilot / VS Code",
    "gemini": "Gemini CLI",
    "github-action": "GitHub Action",
    "opencode": "OpenCode",
}


def _display_name(name: str) -> str:
    return _TARGET_DISPLAY_NAMES.get(name, name.replace("-", " ").title())


def _normalize_install_target_entry(entry: dict[str, Any], *, locale: str = "en") -> dict[str, Any]:
    name = str(entry.get("name") or "unknown")
    detected = bool(entry.get("detected"))
    platform_supported = bool(entry.get("platform_supported", True))
    raw_status = entry.get("status")
    if raw_status in {"installed", "available", "unsupported", "error"}:
        status = str(raw_status)
    elif not platform_supported:
        status = "unsupported"
    else:
        status = "installed" if detected else "available"
    description = str(entry.get("description") or "")
    if not description:
        description = _TARGET_DESCRIPTIONS.get(name, f"Write AhaDiff guidance for {name}.")
    error_message = entry.get("error_message")
    return {
        "name": name,
        "display_name": str(entry.get("display_name") or _display_name(name)),
        "detected": detected,
        "platform_supported": platform_supported,
        "status": status,
        "description": description,
        "install_command": str(entry.get("install_command") or _install_command(name)),
        "uninstall_command": str(entry.get("uninstall_command") or _uninstall_command(name)),
        "manifest": entry.get("manifest") if isinstance(entry.get("manifest"), dict) else None,
        "manifest_hash": (
            str(entry["manifest_hash"]) if isinstance(entry.get("manifest_hash"), str) else None
        ),
        "manifest_error": (
            str(entry["manifest_error"]) if isinstance(entry.get("manifest_error"), str) else None
        ),
        "error_message": str(error_message) if isinstance(error_message, str) else None,
        "usage_hint": get_usage_hint(name, locale),
    }


def _install_command(name: str) -> str:
    return f"ahadiff install {name}"


def _uninstall_command(name: str) -> str:
    return f"ahadiff uninstall {name}"


def _manifest_hash(payload: dict[str, Any], context: InstallContext) -> str:
    hash_payload = {
        "manifest": payload,
        "options": {
            "force": context.force,
            "layer2": context.layer2,
        },
    }
    canonical = json.dumps(hash_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _manifest_preview_payload(target: Any, context: InstallContext) -> tuple[dict[str, Any], str]:
    raw_payload = json.loads(manifest_preview_for(target, context))
    if not isinstance(raw_payload, dict):
        raise InputError("install target manifest preview is invalid")
    manifest_payload = cast("dict[str, Any]", raw_payload)
    raw_actions = manifest_payload.get("actions")
    if not isinstance(raw_actions, dict):
        raise InputError("install target manifest preview is invalid")
    actions = cast("dict[str, Any]", raw_actions)
    return actions, _manifest_hash(manifest_payload, context)


def _relative_paths(paths: list[Any], repo_root: Any) -> list[str]:
    result: list[str] = []
    for path in paths:
        try:
            result.append(path.relative_to(repo_root).as_posix())
        except ValueError:
            result.append(str(path))
    return result


def _validate_install_options(name: str, *, layer2: bool) -> None:
    if layer2 and name != "github-action":
        raise InputError("layer2 install is only supported for github-action")


def _target_context(
    state: ServeState,
    *,
    force: bool = False,
    layer2: bool = False,
) -> InstallContext:
    return InstallContext(repo_root=state.state_dir.parent, force=force, layer2=layer2)


def _target_entry(name: str, state: ServeState, context: InstallContext) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": name,
        "display_name": _display_name(name),
        "detected": False,
        "platform_supported": True,
        "status": "available",
        "description": _TARGET_DESCRIPTIONS.get(name, f"Write AhaDiff guidance for {name}."),
        "install_command": _install_command(name),
        "uninstall_command": _uninstall_command(name),
        "manifest": None,
        "manifest_hash": None,
        "manifest_error": None,
        "error_message": None,
    }
    del state
    try:
        target = get_target(name)
    except ValueError as exc:
        raise InputError(str(exc)) from exc
    if name == "hooks" and sys.platform == "win32":
        entry["platform_supported"] = False
        entry["status"] = "unsupported"
        return entry
    try:
        entry["detected"] = target.detect(context)
        entry["status"] = "installed" if entry["detected"] else "available"
        try:
            actions, manifest_hash = _manifest_preview_payload(target, context)
            entry["manifest"] = actions
            entry["manifest_hash"] = manifest_hash
        except Exception:
            entry["manifest_error"] = "target manifest preview failed"
    except NotImplementedError:
        entry["platform_supported"] = False
        entry["status"] = "unsupported"
    except (TimeoutError, subprocess.TimeoutExpired):
        entry["detected"] = False
        entry["status"] = "error"
        entry["error_message"] = "target detection timed out"
    except Exception:
        entry["detected"] = False
        entry["status"] = "error"
        entry["error_message"] = "target detection failed"
    return entry


def _detect_all_targets(state: ServeState) -> list[dict[str, Any]]:
    try:
        context = _target_context(state)
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for name in available_targets():
        entry = _target_entry(name, state, context)
        results.append(entry)

    return results


async def get_install_targets(request: Request) -> JSONResponse:
    state: ServeState = serve_state(request)
    locale = request_locale(request)
    targets = await to_thread.run_sync(_detect_all_targets, state)
    normalized = [_normalize_install_target_entry(target, locale=locale) for target in targets]
    payload = InstallTargetsResponse.model_validate(
        {"targets": normalized, "total": len(normalized)}
    ).model_dump(mode="json")
    return JSONResponse(payload)


def _preview_target_sync(
    state: ServeState,
    name: str,
    body: InstallPreviewRequest,
    locale: str,
) -> dict[str, Any]:
    _validate_install_options(name, layer2=body.layer2)
    context = _target_context(state, force=body.force, layer2=body.layer2)
    entry = _target_entry(name, state, context)
    normalized = _normalize_install_target_entry(entry, locale=locale)
    manifest_hash = normalized.get("manifest_hash")
    if not isinstance(manifest_hash, str):
        raise InputError("install target manifest preview is unavailable")
    return InstallTargetPreviewResponse.model_validate(
        {"target": normalized, "manifest_hash": manifest_hash}
    ).model_dump(mode="json")


def _mutate_target_sync(
    state: ServeState,
    name: str,
    body: InstallMutationRequest,
    operation: Literal["install", "uninstall"],
    locale: str,
) -> dict[str, Any]:
    _validate_install_options(name, layer2=body.layer2)
    context = _target_context(state, force=body.force, layer2=body.layer2)
    try:
        target = get_target(name)
    except ValueError as exc:
        raise InputError(str(exc)) from exc
    _actions, manifest_hash = _manifest_preview_payload(target, context)
    if body.confirmed_manifest_hash != manifest_hash:
        raise InputError("confirmed_manifest_hash does not match current install manifest")
    with serve_repo_write_lock(state, command=f"serve {operation} {name}"):
        if operation == "install":
            updated_paths = target.write(context)
        else:
            updated_paths = target.uninstall(context)
        entry = _target_entry(name, state, context)
    normalized = _normalize_install_target_entry(entry, locale=locale)
    return InstallTargetMutationResponse.model_validate(
        {
            "target": normalized,
            "operation": operation,
            "updated": len(updated_paths) > 0,
            "updated_paths": _relative_paths(updated_paths, context.repo_root),
            "manifest_hash": manifest_hash,
        }
    ).model_dump(mode="json")


async def preview_install_target(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    name = request.path_params["target"]
    body = InstallPreviewRequest.model_validate(await request.json())
    locale = request_locale(request)
    payload = await to_thread.run_sync(_preview_target_sync, state, name, body, locale)
    return JSONResponse(payload)


async def install_target(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    name = request.path_params["target"]
    body = InstallMutationRequest.model_validate(await request.json())
    locale = request_locale(request)
    payload = await to_thread.run_sync(_mutate_target_sync, state, name, body, "install", locale)
    return JSONResponse(payload)


async def uninstall_target(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    name = request.path_params["target"]
    body = InstallMutationRequest.model_validate(await request.json())
    locale = request_locale(request)
    payload = await to_thread.run_sync(
        _mutate_target_sync,
        state,
        name,
        body,
        "uninstall",
        locale,
    )
    return JSONResponse(payload)
