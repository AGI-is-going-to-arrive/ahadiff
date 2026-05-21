from __future__ import annotations

from typing import TYPE_CHECKING

from .base import (
    InstallAction,
    InstallContext,
    InstallPlan,
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


class CopilotTarget:
    name = "copilot"

    def detect(self, context: InstallContext) -> bool:
        try:
            return is_generated_file(
                repo_path(context, ".github/instructions/ahadiff.instructions.md")
            ) or has_marker(repo_path(context, ".github/copilot-instructions.md"), self.name)
        except OSError:
            return False

    def preview(self, context: InstallContext) -> str:
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        instruction_path = repo_path(context, ".github/instructions/ahadiff.instructions.md")
        write_generated_file(
            instruction_path,
            content=render_template("copilot_instruction.md.j2"),
            force=context.force,
        )
        instructions_path = repo_path(context, ".github/copilot-instructions.md")
        write_marked_section(
            instructions_path,
            self.name,
            section_from_template(self.name, "copilot_section.md.j2"),
        )
        return [instruction_path, instructions_path]

    def uninstall(self, context: InstallContext) -> list[Path]:
        removed: list[Path] = []
        instruction_path = repo_path(context, ".github/instructions/ahadiff.instructions.md")
        if remove_generated_file(instruction_path):
            remove_empty_parents(instruction_path, stop_at=context.repo_root)
            removed.append(instruction_path)
        instructions_path = repo_path(context, ".github/copilot-instructions.md")
        if remove_marked_section(instructions_path, self.name):
            removed.append(instructions_path)
        return removed

    def _plan(self, context: InstallContext) -> InstallPlan:
        return plan_for(
            self.name,
            "Install AhaDiff guidance for GitHub Copilot.",
            [
                InstallAction(
                    repo_path(context, ".github/instructions/ahadiff.instructions.md"),
                    "write",
                ),
                InstallAction(
                    repo_path(context, ".github/copilot-instructions.md"),
                    "merge-section",
                ),
            ],
        )
