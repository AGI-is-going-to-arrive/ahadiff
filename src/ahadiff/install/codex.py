from __future__ import annotations

from typing import TYPE_CHECKING

from .base import (
    InstallAction,
    InstallContext,
    has_marker,
    remove_marked_section,
    write_marked_section,
)
from .common import plan_for, repo_path, section_from_template

if TYPE_CHECKING:
    from pathlib import Path


class CodexTarget:
    name = "codex"

    def detect(self, context: InstallContext) -> bool:
        return has_marker(repo_path(context, "AGENTS.md"), self.name)

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
        return [agents_path]

    def uninstall(self, context: InstallContext) -> list[Path]:
        agents_path = repo_path(context, "AGENTS.md")
        return [agents_path] if remove_marked_section(agents_path, self.name) else []

    def _plan(self, context: InstallContext):
        return plan_for(
            self.name,
            "Install AhaDiff guidance for Codex.",
            [InstallAction(repo_path(context, "AGENTS.md"), "merge-section")],
        )
