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


class OpenCodeTarget:
    name = "opencode"

    def detect(self, context: InstallContext) -> bool:
        return is_generated_file(repo_path(context, ".opencode/agents/ahadiff.md")) or has_marker(
            repo_path(context, "AGENTS.md"), self.name
        )

    def preview(self, context: InstallContext) -> str:
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        agents_path = repo_path(context, "AGENTS.md")
        write_marked_section(
            agents_path,
            self.name,
            section_from_template(self.name, "agents_section.md.j2"),
        )
        opencode_agent = repo_path(context, ".opencode/agents/ahadiff.md")
        write_generated_file(
            opencode_agent,
            content=render_template("opencode_agent.md.j2"),
            force=context.force,
        )
        return [agents_path, opencode_agent]

    def uninstall(self, context: InstallContext) -> list[Path]:
        removed: list[Path] = []
        agents_path = repo_path(context, "AGENTS.md")
        if remove_marked_section(agents_path, self.name):
            removed.append(agents_path)
        opencode_agent = repo_path(context, ".opencode/agents/ahadiff.md")
        if remove_generated_file(opencode_agent):
            remove_empty_parents(opencode_agent, stop_at=context.repo_root)
            removed.append(opencode_agent)
        return removed

    def _plan(self, context: InstallContext):
        return plan_for(
            self.name,
            "Install AhaDiff guidance for OpenCode.",
            [
                InstallAction(repo_path(context, "AGENTS.md"), "merge-section"),
                InstallAction(repo_path(context, ".opencode/agents/ahadiff.md"), "write"),
            ],
        )
