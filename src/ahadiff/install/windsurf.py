from __future__ import annotations

from typing import TYPE_CHECKING

from .base import (
    InstallAction,
    InstallContext,
    InstallPlan,
    is_generated_file,
    remove_empty_parents,
    remove_generated_file,
    write_generated_file,
)
from .common import plan_for, repo_path
from .template_loader import render_template

if TYPE_CHECKING:
    from pathlib import Path


class WindsurfTarget:
    name = "windsurf"

    def detect(self, context: InstallContext) -> bool:
        return is_generated_file(repo_path(context, ".windsurf/rules/ahadiff.md"))

    def preview(self, context: InstallContext) -> str:
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        rule_path = repo_path(context, ".windsurf/rules/ahadiff.md")
        write_generated_file(
            rule_path,
            content=render_template("windsurf_rule.md.j2"),
            force=context.force,
        )
        return [rule_path]

    def uninstall(self, context: InstallContext) -> list[Path]:
        rule_path = repo_path(context, ".windsurf/rules/ahadiff.md")
        if remove_generated_file(rule_path):
            remove_empty_parents(rule_path, stop_at=context.repo_root)
            return [rule_path]
        return []

    def _plan(self, context: InstallContext) -> InstallPlan:
        return plan_for(
            self.name,
            "Install AhaDiff guidance for Windsurf rules.",
            [InstallAction(repo_path(context, ".windsurf/rules/ahadiff.md"), "write")],
        )
