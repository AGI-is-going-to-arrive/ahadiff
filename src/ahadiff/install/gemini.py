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


class GeminiTarget:
    name = "gemini"

    def detect(self, context: InstallContext) -> bool:
        return has_marker(repo_path(context, "GEMINI.md"), self.name)

    def preview(self, context: InstallContext) -> str:
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        gemini_path = repo_path(context, "GEMINI.md")
        write_marked_section(
            gemini_path,
            self.name,
            section_from_template(self.name, "gemini_section.md.j2"),
        )
        return [gemini_path]

    def uninstall(self, context: InstallContext) -> list[Path]:
        gemini_path = repo_path(context, "GEMINI.md")
        return [gemini_path] if remove_marked_section(gemini_path, self.name) else []

    def _plan(self, context: InstallContext):
        return plan_for(
            self.name,
            "Install AhaDiff guidance for Gemini CLI.",
            [InstallAction(repo_path(context, "GEMINI.md"), "merge-section")],
        )
