from __future__ import annotations

from typing import TYPE_CHECKING

from .aider import AiderTarget
from .antigravity import AntigravityTarget
from .antigravity_cli import AntigravityCLITarget
from .claude import ClaudeTarget
from .cline import ClineTarget
from .codex import CodexTarget
from .continue_ import ContinueTarget
from .copilot import CopilotTarget
from .cursor import CursorTarget
from .gemini import GeminiTarget
from .github_action import GitHubActionTarget
from .hooks import HooksTarget
from .opencode import OpenCodeTarget
from .roo import RooTarget
from .windsurf import WindsurfTarget

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
    return {name: _detect_target(target, context) for name, target in sorted(_TARGETS.items())}


def _detect_target(target: InstallTarget, context: InstallContext) -> bool:
    try:
        return target.detect(context)
    except OSError:
        return False


_TARGETS: dict[str, InstallTarget] = {
    "aider": AiderTarget(),
    "antigravity": AntigravityTarget(),
    "antigravity-cli": AntigravityCLITarget(),
    "claude": ClaudeTarget(),
    "cline": ClineTarget(),
    "codex": CodexTarget(),
    "continue": ContinueTarget(),
    "copilot": CopilotTarget(),
    "cursor": CursorTarget(),
    "gemini": GeminiTarget(),
    "github-action": GitHubActionTarget(),
    "hooks": HooksTarget(),
    "opencode": OpenCodeTarget(),
    "roo": RooTarget(),
    "windsurf": WindsurfTarget(),
}
