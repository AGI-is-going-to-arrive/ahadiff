from __future__ import annotations

from typing import TYPE_CHECKING

from .claude import ClaudeTarget
from .codex import CodexTarget
from .gemini import GeminiTarget
from .github_action import GitHubActionTarget
from .hooks import HooksTarget
from .opencode import OpenCodeTarget

if TYPE_CHECKING:
    from .base import InstallContext, InstallTarget


def available_targets() -> tuple[str, ...]:
    return tuple(sorted(_TARGETS))


def get_target(name: str) -> InstallTarget:
    try:
        return _TARGETS[name]
    except KeyError as exc:
        allowed = ", ".join(available_targets())
        raise ValueError(f"unknown install target {name!r}; expected one of: {allowed}") from exc


def target_detection(context: InstallContext) -> dict[str, bool]:
    return {name: target.detect(context) for name, target in sorted(_TARGETS.items())}


_TARGETS: dict[str, InstallTarget] = {
    "claude": ClaudeTarget(),
    "codex": CodexTarget(),
    "gemini": GeminiTarget(),
    "github-action": GitHubActionTarget(),
    "hooks": HooksTarget(),
    "opencode": OpenCodeTarget(),
}
