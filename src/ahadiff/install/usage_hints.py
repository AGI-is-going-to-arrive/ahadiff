"""Localized usage hints for generated AI tool guidance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ahadiff.contracts.serve_install import ToolUsageHint

ToolCategory = Literal["cli", "ide", "ci"]
PlatformKey = Literal["windows", "macos", "linux"]


@dataclass(frozen=True)
class _TargetUsage:
    category: ToolCategory
    en_name: str
    zh_name: str
    en_invocation: str
    zh_invocation: str


_TARGETS: dict[str, _TargetUsage] = {
    "aider": _TargetUsage(
        "cli",
        "Aider",
        "Aider",
        'aider --message "Run ahadiff learn --staged after this change"',
        'aider --message "这次修改后运行 ahadiff learn --staged"',
    ),
    "antigravity": _TargetUsage(
        "ide",
        "Antigravity IDE",
        "Antigravity IDE",
        "Open Antigravity IDE and use the AhaDiff workspace skill.",
        "在 Antigravity IDE 打开本仓库，并使用 AhaDiff workspace skill。",
    ),
    "antigravity-cli": _TargetUsage(
        "cli",
        "Antigravity CLI",
        "Antigravity CLI",
        'antigravity "Use AhaDiff to learn HEAD~1..HEAD"',
        'antigravity "使用 AhaDiff 学习 HEAD~1..HEAD"',
    ),
    "claude": _TargetUsage(
        "cli",
        "Claude Code",
        "Claude Code",
        'claude "Use the ahadiff skill to learn HEAD~1..HEAD"',
        'claude "使用 ahadiff skill 学习 HEAD~1..HEAD"',
    ),
    "cline": _TargetUsage(
        "ide",
        "Cline",
        "Cline",
        "Open Cline in VS Code and ask it to use AhaDiff for the current diff.",
        "在 VS Code 打开 Cline，并要求它为当前 diff 使用 AhaDiff。",
    ),
    "codex": _TargetUsage(
        "cli",
        "Codex CLI",
        "Codex CLI",
        'codex "Use AhaDiff to learn the staged diff"',
        'codex "使用 AhaDiff 学习 staged diff"',
    ),
    "continue": _TargetUsage(
        "ide",
        "Continue",
        "Continue",
        "Open Continue and ask for an AhaDiff learning pass.",
        "打开 Continue，并要求它执行一次 AhaDiff 学习流程。",
    ),
    "copilot": _TargetUsage(
        "ide",
        "Copilot Chat",
        "Copilot Chat",
        "Use Copilot Chat in VS Code and ask it to follow the AhaDiff instructions.",
        "在 VS Code 使用 Copilot Chat，并要求它遵循 AhaDiff 指引。",
    ),
    "cursor": _TargetUsage(
        "ide",
        "Cursor",
        "Cursor",
        "Open Cursor and ask the agent to use AhaDiff for the current diff.",
        "打开 Cursor，并要求 agent 为当前 diff 使用 AhaDiff。",
    ),
    "gemini": _TargetUsage(
        "cli",
        "Gemini CLI",
        "Gemini CLI",
        'gemini "Use AhaDiff to learn HEAD~1..HEAD"',
        'gemini "使用 AhaDiff 学习 HEAD~1..HEAD"',
    ),
    "github-action": _TargetUsage(
        "ci",
        "GitHub Actions",
        "GitHub Actions",
        "Run the generated AhaDiff workflow on a pull request or manual dispatch.",
        "在 pull request 或手动 dispatch 中运行生成的 AhaDiff workflow。",
    ),
    "hooks": _TargetUsage(
        "ci",
        "Git hooks",
        "Git hooks",
        "git commit; git push",
        "git commit; git push",
    ),
    "opencode": _TargetUsage(
        "cli",
        "OpenCode",
        "OpenCode",
        'opencode run "Use the AhaDiff agent to learn the staged diff"',
        'opencode run "使用 AhaDiff agent 学习 staged diff"',
    ),
    "roo": _TargetUsage(
        "ide",
        "Roo Code",
        "Roo Code",
        "Open Roo Code and ask it to follow the AhaDiff workspace rules.",
        "打开 Roo Code，并要求它遵循 AhaDiff 工作区规则。",
    ),
    "windsurf": _TargetUsage(
        "ide",
        "Windsurf",
        "Windsurf",
        "Open Windsurf and ask the agent to use AhaDiff before handoff.",
        "打开 Windsurf，并要求 agent 在交付前使用 AhaDiff。",
    ),
}


def get_usage_hint(target_name: str, locale: str) -> ToolUsageHint | None:
    usage = _TARGETS.get(target_name)
    if usage is None:
        return None
    localized = locale == "zh-CN"
    label = usage.zh_name if localized else usage.en_name
    return ToolUsageHint(
        tool_category=usage.category,
        invocation_pattern=usage.zh_invocation if localized else usage.en_invocation,
        quick_start_steps=list(_quick_start_steps(usage.category, label, localized)),
        example_prompts=list(_example_prompts(usage.category, label, localized)),
        expected_behavior=_expected_behavior(usage.category, label, localized),
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


def _expected_behavior(category: ToolCategory, label: str, localized: bool) -> str:
    if localized:
        if category == "ci":
            return f"{label} 会在自动化边界生成或验证 AhaDiff 学习产物。"
        return f"{label} 会遵循仓库本地指引，把代码 diff 转成可验证的学习输出。"
    if category == "ci":
        return f"{label} generates or verifies AhaDiff learning artifacts at automation gates."
    return (
        f"{label} follows repo-local guidance and turns code diffs into verified learning output."
    )


def _platform_notes(target_name: str, localized: bool) -> dict[PlatformKey, str]:
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
