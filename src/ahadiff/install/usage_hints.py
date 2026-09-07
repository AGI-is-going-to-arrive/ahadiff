"""Localized usage hints for generated AI tool guidance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ahadiff.contracts.serve_install import ToolUsageHint

from .registry import get_target_metadata

ToolCategory = Literal["cli", "ide", "ci"]
PlatformKey = Literal["windows", "macos", "linux"]


@dataclass(frozen=True)
class _TargetUsage:
    en_invocation: str
    zh_invocation: str


_TARGETS: dict[str, _TargetUsage] = {
    "aider": _TargetUsage(
        'aider --read CONVENTIONS.md --message "Run ahadiff learn --staged after this change"',
        'aider --read CONVENTIONS.md --message "这次修改后运行 ahadiff learn --staged"',
    ),
    "antigravity": _TargetUsage(
        "Open Antigravity IDE and use the AhaDiff workspace skill.",
        "在 Antigravity IDE 打开本仓库，并使用 AhaDiff workspace skill。",
    ),
    "antigravity-cli": _TargetUsage(
        "Start agy in this repository, then ask it to use AhaDiff.",
        "在此仓库启动 agy，然后要求它使用 AhaDiff。",
    ),
    "claude": _TargetUsage(
        'claude "Use the ahadiff skill to learn HEAD~1..HEAD"',
        'claude "使用 ahadiff skill 学习 HEAD~1..HEAD"',
    ),
    "cline": _TargetUsage(
        "Open this repository in Cline and ask to use AhaDiff for the current diff.",
        "在 Cline 打开此仓库，并要求为当前 diff 使用 AhaDiff。",
    ),
    "codex": _TargetUsage(
        'codex "Use AhaDiff to learn the staged diff"', 'codex "使用 AhaDiff 学习 staged diff"'
    ),
    "continue": _TargetUsage(
        "Open Continue and ask for an AhaDiff learning pass.",
        "打开 Continue，并要求它执行一次 AhaDiff 学习流程。",
    ),
    "copilot": _TargetUsage(
        "Ask GitHub Copilot to follow this repository's AhaDiff instructions.",
        "要求 GitHub Copilot 遵循此仓库的 AhaDiff 指引。",
    ),
    "cursor": _TargetUsage(
        "Open Cursor and ask the agent to use AhaDiff for the current diff.",
        "打开 Cursor，并要求 agent 为当前 diff 使用 AhaDiff。",
    ),
    "gemini": _TargetUsage(
        'gemini "Use AhaDiff to learn HEAD~1..HEAD"', 'gemini "使用 AhaDiff 学习 HEAD~1..HEAD"'
    ),
    "github-action": _TargetUsage(
        "Run the generated AhaDiff workflow on a pull request or manual dispatch.",
        "在 pull request 或手动 dispatch 中运行生成的 AhaDiff workflow。",
    ),
    "hooks": _TargetUsage(
        "ahadiff install hooks; ahadiff install hooks --auto-learn",
        "ahadiff install hooks；ahadiff install hooks --auto-learn",
    ),
    "opencode": _TargetUsage(
        'opencode run "Use the AhaDiff agent to learn the staged diff"',
        'opencode run "使用 AhaDiff agent 学习 staged diff"',
    ),
    "pi": _TargetUsage(
        "Start pi in this repository, trust the project, then use /skill:ahadiff.",
        "在此仓库启动 pi，确认信任项目后使用 /skill:ahadiff。",
    ),
    "deepseek-harness": _TargetUsage(
        "Start npx @deepseek-ai/dsh web, choose this workspace, then ask to use the AhaDiff skill.",
        ("启动 npx @deepseek-ai/dsh web，选择此工作区，然后要求使用 AhaDiff 技能。"),
    ),
    "grok": _TargetUsage(
        "Start grok in this repository, then use /ahadiff.",
        "在此仓库启动 grok，然后使用 /ahadiff。",
    ),
    "devin": _TargetUsage(
        "Open this repository in Devin Desktop or Devin CLI and ask to use AhaDiff.",
        "在 Devin Desktop 或 Devin CLI 打开此仓库，并要求使用 AhaDiff。",
    ),
}


def get_usage_hint(target_name: str, locale: str) -> ToolUsageHint | None:
    usage = _TARGETS.get(target_name)
    metadata = get_target_metadata(target_name)
    if usage is None or metadata is None:
        return None
    localized = locale == "zh-CN"
    label = metadata.display_name
    return ToolUsageHint(
        tool_category=metadata.category,
        invocation_pattern=usage.zh_invocation if localized else usage.en_invocation,
        quick_start_steps=list(_quick_start_steps(metadata.category, label, localized)),
        example_prompts=list(_example_prompts(metadata.category, label, localized)),
        expected_behavior=_expected_behavior(target_name, metadata.category, label, localized),
        platform_notes=_platform_notes(target_name, localized),
    )


def _quick_start_steps(
    category: ToolCategory,
    label: str,
    localized: bool,
) -> tuple[str, ...]:
    if localized:
        if category == "cli":
            return (
                f"把 {label} 指引写入当前仓库。",
                f"从仓库根目录启动 {label}。",
                "要求它运行 AhaDiff 学习 staged diff、最新提交或指定 patch。",
            )
        if category == "ide":
            return (
                f"把 {label} 工作区指引写入当前仓库。",
                f"在 {label} 中打开这个仓库。",
                "要求 agent 在交付前调用 AhaDiff 学习当前 diff。",
            )
        return (
            f"预览并写入 {label} 集成文件。",
            "在 commit、push、pull request 或手动 dispatch 中触发它。",
            "查看 AhaDiff 输出里的 lesson、claims 和 quiz。",
        )
    if category == "cli":
        return (
            f"Write the {label} guidance into this repository.",
            f"Start {label} from the repository root.",
            "Ask it to run AhaDiff for the staged diff, latest commit, or a patch.",
        )
    if category == "ide":
        return (
            f"Write the {label} workspace guidance into this repository.",
            f"Open this repository in {label}.",
            "Ask the agent to call AhaDiff for the current diff before handoff.",
        )
    return (
        f"Preview and write the {label} integration files.",
        "Trigger it from commit, push, pull request, or manual dispatch.",
        "Review the AhaDiff lesson, claims, and quiz output.",
    )


def _example_prompts(
    category: ToolCategory,
    label: str,
    localized: bool,
) -> tuple[str, ...]:
    del label
    if localized:
        if category == "ci":
            return (
                "合并前查看 AhaDiff workflow 结果。",
                "把生成的 lesson 和 claims 用作 PR review 上下文。",
            )
        return (
            "使用 AhaDiff 学习当前 diff，并列出证据薄弱点。",
            "运行 ahadiff learn --staged，然后总结 verified claims。",
        )
    if category == "ci":
        return (
            "Review the AhaDiff workflow result before merging.",
            "Use the generated lesson and claims as PR review context.",
        )
    return (
        "Use AhaDiff to learn the current diff and list weak evidence.",
        "Run ahadiff learn --staged, then summarize the verified claims.",
    )


def _expected_behavior(
    target_name: str,
    category: ToolCategory,
    label: str,
    localized: bool,
) -> str:
    if target_name == "hooks":
        if localized:
            return (
                f"{label} 默认只在 commit 后提醒学习、push 前提醒验证；"
                "--auto-learn 会在 post-commit 后台运行 `ahadiff learn --last`，"
                "日志写入 `.ahadiff/hooks.log`。"
            )
        return (
            f"{label} defaults to commit-time learn reminders and push-time verify reminders; "
            "--auto-learn runs `ahadiff learn --last` from post-commit in the background "
            "and logs to `.ahadiff/hooks.log`."
        )
    if localized:
        if category == "ci":
            return f"{label} 会在自动化边界生成或验证 AhaDiff 学习产物。"
        return f"在已安装并启用技能的 {label} 中，可要求使用仓库本地指引生成可验证的学习输出。"
    if category == "ci":
        return f"{label} generates or verifies AhaDiff learning artifacts at automation gates."
    return (
        f"Once {label} is installed and the guidance is enabled, "
        "ask it to produce verified learning output."
    )


def _platform_notes(target_name: str, localized: bool) -> dict[PlatformKey, str]:
    if target_name == "pi":
        return {
            "windows": "Pi 在 Windows 上默认使用 Git Bash；也可配置 PowerShell。"
            if localized
            else "Pi uses Git Bash on Windows by default; PowerShell can be configured."
        }
    if target_name != "hooks":
        return {}
    if localized:
        return {
            "windows": "Windows 不支持安装 Git hooks 目标。",
            "macos": "请使用 zsh 或 bash 这类 POSIX 兼容 shell。",
            "linux": "请使用 bash 这类 POSIX 兼容 shell。",
        }
    return {
        "windows": "Git hook installation is unsupported on Windows.",
        "macos": "Use a POSIX-compatible shell such as zsh or bash.",
        "linux": "Use a POSIX-compatible shell such as bash.",
    }


__all__ = ["get_usage_hint"]
