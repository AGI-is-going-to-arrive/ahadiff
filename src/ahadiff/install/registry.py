from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

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
from .generated import GeneratedGuidanceTarget
from .github_action import GitHubActionTarget
from .hooks import HooksTarget
from .opencode import OpenCodeTarget
from .roo import RooTarget
from .windsurf import WindsurfTarget

if TYPE_CHECKING:
    from .base import InstallContext, InstallTarget


@dataclass(frozen=True)
class TargetMetadata:
    display_name: str
    category: Literal["cli", "ide", "ci"]
    en_description: str
    zh_description: str
    documentation_url: str
    lifecycle: Literal["active", "preview", "limited", "retired", "replaced"] = "active"
    en_note: str = ""
    zh_note: str = ""
    verified_at: str = "2026-09-07"

    def description(self, locale: str) -> str:
        return self.zh_description if locale == "zh-CN" else self.en_description

    def note(self, locale: str) -> str:
        return self.zh_note if locale == "zh-CN" else self.en_note


def available_targets() -> tuple[str, ...]:
    """Default catalogue; account-limited and replaced targets are explicit only."""
    return tuple(
        sorted(
            name for name, (_, meta) in _TARGETS.items() if meta.lifecycle in {"active", "preview"}
        )
    )


def legacy_targets() -> tuple[str, ...]:
    return tuple(sorted(set(_TARGETS) - set(available_targets())))


def get_target_metadata(name: str) -> TargetMetadata | None:
    entry = _TARGETS.get(name)
    return entry[1] if entry is not None else None


def get_target(name: str) -> InstallTarget:
    entry = _TARGETS.get(name)
    if entry is not None and entry[1].lifecycle not in {"retired", "replaced"}:
        return entry[0]
    if entry is not None:
        raise ValueError(
            f"{name!r} is no longer offered for new guidance; "
            f"use ahadiff uninstall {name} to remove existing guidance"
        )
    allowed = ", ".join(available_targets())
    raise ValueError(f"unknown install target {name!r}; expected one of: {allowed}")


def get_uninstall_target(name: str) -> InstallTarget:
    """Resolve owned legacy files without reopening retired installation paths."""
    entry = _TARGETS.get(name)
    if entry is None:
        raise ValueError(f"unknown uninstall target {name!r}")
    return entry[0]


def target_detection(context: InstallContext) -> dict[str, bool]:
    detections = {name: _detect_target(_TARGETS[name][0], context) for name in available_targets()}
    for name in legacy_targets():
        if _detect_target(_TARGETS[name][0], context):
            detections[name] = True
    return detections


def _detect_target(target: InstallTarget, context: InstallContext) -> bool:
    try:
        return target.detect(context)
    except OSError:
        return False


# One authority for names, lifecycle, locale copy and native documentation.
_REGISTRATIONS: tuple[tuple[InstallTarget, TargetMetadata], ...] = (
    (
        AiderTarget(),
        TargetMetadata(
            "Aider",
            "cli",
            "Write AhaDiff conventions; load them with aider --read.",
            "写入 AhaDiff 约定，通过 aider --read 显式加载。",
            "https://aider.chat/docs/usage/conventions.html",
        ),
    ),
    (
        AntigravityTarget(),
        TargetMetadata(
            "Antigravity IDE",
            "ide",
            "Write a workspace skill and AhaDiff rules.",
            "写入工作区技能和 AhaDiff 规则。",
            "https://antigravity.google/docs/skills/",
        ),
    ),
    (
        AntigravityCLITarget(),
        TargetMetadata(
            "Antigravity CLI",
            "cli",
            "Write workspace guidance for the agy CLI.",
            "为 agy CLI 写入工作区指引。",
            "https://antigravity.google/docs/cli/",
            "active",
            (
                "Start agy, then ask to use AhaDiff. The CLI docs describe flat skill files; "
                "discovery of this directory-style skill has not been verified in the current CLI."
            ),
            (
                "启动 agy 后要求使用 AhaDiff。CLI 文档使用平铺技能文件；"
                "当前目录格式的发现能力尚未在该 CLI 上验证。"
            ),
        ),
    ),
    (
        ClaudeTarget(),
        TargetMetadata(
            "Claude Code",
            "cli",
            "Write project instructions and an AhaDiff skill.",
            "写入项目指引和 AhaDiff 技能。",
            "https://code.claude.com/docs/en/skills",
        ),
    ),
    (
        ClineTarget(),
        TargetMetadata(
            "Cline",
            "ide",
            "Write project rules for Cline.",
            "为 Cline 写入项目规则。",
            "https://docs.cline.bot/features/cline-rules/overview",
        ),
    ),
    (
        CodexTarget(),
        TargetMetadata(
            "Codex",
            "cli",
            "Write a project skill and AGENTS.md guidance for Codex.",
            "为 Codex 写入项目技能和 AGENTS.md 指引。",
            "https://developers.openai.com/codex/skills/",
        ),
    ),
    (
        ContinueTarget(),
        TargetMetadata(
            "Continue",
            "ide",
            "Write project instructions for Continue.",
            "为 Continue 写入项目指引。",
            "https://docs.continue.dev/customize/deep-dives/rules",
        ),
    ),
    (
        CopilotTarget(),
        TargetMetadata(
            "GitHub Copilot",
            "ide",
            "Write repository instructions for GitHub Copilot.",
            "为 GitHub Copilot 写入仓库指引。",
            "https://docs.github.com/en/copilot/customizing-copilot/adding-custom-instructions-for-github-copilot",
        ),
    ),
    (
        CursorTarget(),
        TargetMetadata(
            "Cursor",
            "ide",
            "Write native Cursor project rules.",
            "写入 Cursor 原生项目规则。",
            "https://cursor.com/docs/context/rules",
        ),
    ),
    (
        GeneratedGuidanceTarget("deepseek-harness", ".dsh/skills/ahadiff/SKILL.md"),
        TargetMetadata(
            "DeepSeek Harness",
            "cli",
            "Write a native skill for the DeepSeek Harness Web UI.",
            "为 DeepSeek Harness Web 界面写入原生技能。",
            "https://github.com/deepseek-ai/deepseek-harness",
            "preview",
            (
                "Developer preview. Choose this workspace in dsh web; custom profiles "
                "may disable skills. Runtime support depends on the installed Harness "
                "release."
            ),
            (
                "开发者预览版。在 dsh web 中选择此工作区；自定义配置可能禁用技"
                "能。运行平台支持以所安装的 Harness 版本为准。"
            ),
        ),
    ),
    (
        GeneratedGuidanceTarget("devin", ".devin/rules/ahadiff.md", "windsurf_rule.md.j2"),
        TargetMetadata(
            "Devin Desktop / CLI",
            "ide",
            "Write native Devin project rules.",
            "写入 Devin 原生项目规则。",
            "https://cli.devin.ai/docs/extensibility/rules",
        ),
    ),
    (
        GeminiTarget(),
        TargetMetadata(
            "Gemini CLI",
            "cli",
            "Explicit installation for API-key or Enterprise accounts.",
            "仅供 API key 或企业账号显式安装。",
            "https://developers.googleblog.com/en/an-important-update-transitioning-gemini-cli-to-antigravity-cli/",
            "limited",
            (
                "Individual Google accounts stopped being served on June 18, 2026. "
                "API-key and Enterprise access remain supported. Individual users can "
                "migrate to Antigravity CLI."
            ),
            (
                "自 2026 年 6 月 18 日起停止服务个人 Google 账号；"
                "API key 与企业账号仍受支持。个人用户可迁移至 Antigravity CLI。"
            ),
        ),
    ),
    (
        GitHubActionTarget(),
        TargetMetadata(
            "GitHub Actions",
            "ci",
            "Write an opt-in GitHub Actions workflow template.",
            "写入需主动启用的 GitHub Actions 工作流模板。",
            "https://docs.github.com/en/actions",
        ),
    ),
    (
        GeneratedGuidanceTarget("grok", ".grok/skills/ahadiff/SKILL.md"),
        TargetMetadata(
            "Grok Build",
            "cli",
            "Write a native Grok Build project skill.",
            "写入 Grok Build 原生项目技能。",
            "https://docs.x.ai/build/features/skills-plugins-marketplaces",
        ),
    ),
    (
        HooksTarget(),
        TargetMetadata(
            "Git hooks",
            "ci",
            "Write local Git hook integration files.",
            "写入本地 Git hook 集成文件。",
            "https://git-scm.com/docs/githooks",
        ),
    ),
    (
        OpenCodeTarget(),
        TargetMetadata(
            "OpenCode",
            "cli",
            "Write an OpenCode agent and repository instructions.",
            "写入 OpenCode agent 和仓库指引。",
            "https://opencode.ai/docs/agents/",
        ),
    ),
    (
        GeneratedGuidanceTarget("pi", ".pi/skills/ahadiff/SKILL.md"),
        TargetMetadata(
            "Pi Agent",
            "cli",
            "Write a native Pi project skill.",
            "写入 Pi 原生项目技能。",
            "https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md",
        ),
    ),
    (
        RooTarget(),
        TargetMetadata(
            "Roo Code",
            "ide",
            "Remove previously generated Roo Code guidance.",
            "移除此前生成的 Roo Code 指引。",
            "https://github.com/RooCodeInc/Roo-Code",
            "retired",
            (
                "Roo Code shut down on May 15, 2026. Existing AhaDiff guidance can be "
                "removed; Cline remains available."
            ),
            (
                "Roo Code 已于 2026 年 5 月 15 日停止服务。可移除"
                "已有 AhaDiff 指引；可用替代工具包括 Cline。"
            ),
        ),
    ),
    (
        WindsurfTarget(),
        TargetMetadata(
            "Windsurf",
            "ide",
            "Remove previously generated Windsurf guidance.",
            "移除此前生成的 Windsurf 指引。",
            "https://devin.ai/blog/windsurf-is-now-devin-desktop",
            "replaced",
            (
                "Windsurf became Devin Desktop. Existing .windsurf rules remain "
                "supported; use the Devin target for new guidance and remove old "
                "guidance only when ready."
            ),
            (
                "Windsurf 已更名为 Devin Desktop。已有 .win"
                "dsurf 规则仍受支持；新指引请使用 Devin，确认迁移完成后再移除旧指引。"
            ),
        ),
    ),
)
_TARGETS: dict[str, tuple[InstallTarget, TargetMetadata]] = {
    target.name: (target, metadata) for target, metadata in _REGISTRATIONS
}
