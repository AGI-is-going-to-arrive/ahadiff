"""GET /api/install/targets endpoint."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_install import InstallTargetsResponse
from ahadiff.install.base import InstallContext
from ahadiff.install.common import manifest_preview_for
from ahadiff.install.registry import available_targets, get_target

if TYPE_CHECKING:
    from starlette.requests import Request

    from .state import ServeState

log = logging.getLogger(__name__)

_TARGET_DESCRIPTIONS = {
    "aider": "Install AhaDiff guidance for Aider.",
    "claude": "Install Claude Code project instructions and skills.",
    "cline": "Install AhaDiff instructions for Cline.",
    "codex": "Install Codex AGENTS.md guidance.",
    "continue": "Install AhaDiff instructions for Continue.",
    "copilot": "Install GitHub Copilot instructions.",
    "cursor": "Install Cursor rules for AhaDiff.",
    "gemini": "Install Gemini CLI guidance.",
    "github-action": "Install the GitHub Actions workflow template.",
    "hooks": "Install local git hook integration.",
    "opencode": "Install OpenCode agent instructions.",
    "roo": "Install AhaDiff instructions for Roo.",
    "windsurf": "Install Windsurf rules for AhaDiff.",
}


def _display_name(name: str) -> str:
    if name == "github-action":
        return "GitHub Action"
    return name.replace("-", " ").title()


def _normalize_install_target_entry(entry: dict[str, Any]) -> dict[str, Any]:
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
        description = _TARGET_DESCRIPTIONS.get(name, f"Install AhaDiff guidance for {name}.")
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
        "manifest_error": (
            str(entry["manifest_error"]) if isinstance(entry.get("manifest_error"), str) else None
        ),
        "error_message": str(error_message) if isinstance(error_message, str) else None,
    }


def _install_command(name: str) -> str:
    return f"ahadiff install {name}"


def _uninstall_command(name: str) -> str:
    return f"ahadiff uninstall {name}"


def _detect_all_targets(state: ServeState) -> list[dict[str, Any]]:
    repo_root = state.state_dir.parent
    try:
        context = InstallContext(repo_root=repo_root)
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for name in available_targets():
        entry: dict[str, Any] = {
            "name": name,
            "display_name": _display_name(name),
            "detected": False,
            "platform_supported": True,
            "status": "available",
            "description": _TARGET_DESCRIPTIONS.get(name, f"Install AhaDiff guidance for {name}."),
            "install_command": _install_command(name),
            "uninstall_command": _uninstall_command(name),
            "manifest": None,
            "manifest_error": None,
            "error_message": None,
        }
        try:
            target = get_target(name)
            entry["detected"] = target.detect(context)
            entry["status"] = "installed" if entry["detected"] else "available"
            try:
                manifest_payload = json.loads(manifest_preview_for(target, context))
                actions = manifest_payload.get("actions")
                if isinstance(actions, dict):
                    entry["manifest"] = actions
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
        results.append(entry)

    return results


async def get_install_targets(request: Request) -> JSONResponse:
    from .auth import serve_state

    state: ServeState = serve_state(request)
    targets = await to_thread.run_sync(_detect_all_targets, state)
    normalized = [_normalize_install_target_entry(target) for target in targets]
    payload = InstallTargetsResponse.model_validate(
        {"targets": normalized, "total": len(normalized)}
    ).model_dump(mode="json")
    return JSONResponse(payload)
