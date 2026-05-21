from __future__ import annotations

from typing import TYPE_CHECKING

from .base import (
    InstallAction,
    InstallContext,
    has_marker,
    is_generated_file,
    remove_empty_parents,
    remove_generated_file,
    remove_marked_section,
    write_generated_file,
    write_marked_section,
)
from .common import plan_for, repo_path, section_from_template
from .template_loader import render_template

if TYPE_CHECKING:
    from pathlib import Path


class ClaudeTarget:
    name = "claude"

    def detect(self, context: InstallContext) -> bool:
        skill_path = repo_path(context, ".claude/skills/ahadiff/SKILL.md")
        return is_generated_file(skill_path) or has_marker(
            repo_path(context, "CLAUDE.md"),
            self.name,
        )

    def preview(self, context: InstallContext) -> str:
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        skill_path = repo_path(context, ".claude/skills/ahadiff/SKILL.md")
        write_generated_file(
            skill_path,
            content=render_template("claude_skill.md.j2"),
            force=context.force,
        )
        claude_path = repo_path(context, "CLAUDE.md")
        write_marked_section(
            claude_path,
            self.name,
            section_from_template(self.name, "claude_section.md.j2"),
        )
        return [skill_path, claude_path]

    def uninstall(self, context: InstallContext) -> list[Path]:
        removed: list[Path] = []
        skill_path = repo_path(context, ".claude/skills/ahadiff/SKILL.md")
        if remove_generated_file(skill_path):
            remove_empty_parents(skill_path, stop_at=context.repo_root)
            removed.append(skill_path)
        claude_path = repo_path(context, "CLAUDE.md")
        if remove_marked_section(claude_path, self.name):
            removed.append(claude_path)
        return removed

    def _plan(self, context: InstallContext):
        return plan_for(
            self.name,
            "Install AhaDiff guidance for Claude Code.",
            [
                InstallAction(repo_path(context, ".claude/skills/ahadiff/SKILL.md"), "write"),
                InstallAction(repo_path(context, "CLAUDE.md"), "merge-section"),
            ],
        )
