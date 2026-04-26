from __future__ import annotations

from typing import TYPE_CHECKING

from .base import (
    InstallAction,
    InstallContext,
    InstallPlan,
    has_marker,
    remove_marked_section,
    write_marked_section,
)
from .common import plan_for, repo_path, section_from_template

if TYPE_CHECKING:
    from pathlib import Path


class AiderTarget:
    name = "aider"

    def detect(self, context: InstallContext) -> bool:
        try:
            return has_marker(repo_path(context, "CONVENTIONS.md"), self.name)
        except OSError:
            return False

    def preview(self, context: InstallContext) -> str:
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        conventions_path = repo_path(context, "CONVENTIONS.md")
        write_marked_section(
            conventions_path,
            self.name,
            section_from_template(self.name, "aider_section.md.j2"),
        )
        return [conventions_path]

    def uninstall(self, context: InstallContext) -> list[Path]:
        conventions_path = repo_path(context, "CONVENTIONS.md")
        if remove_marked_section(conventions_path, self.name):
            return [conventions_path]
        return []

    def _plan(self, context: InstallContext) -> InstallPlan:
        return plan_for(
            self.name,
            "Install AhaDiff guidance for Aider conventions.",
            [InstallAction(repo_path(context, "CONVENTIONS.md"), "merge-section")],
        )
