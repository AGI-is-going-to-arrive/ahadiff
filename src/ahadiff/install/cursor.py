from __future__ import annotations

from typing import TYPE_CHECKING

from .base import (
    InstallAction,
    InstallContext,
    InstallPlan,
    remove_empty_parents,
    remove_generated_file,
    write_generated_file,
)
from .common import plan_for, repo_path
from .template_loader import render_template

if TYPE_CHECKING:
    from pathlib import Path


class CursorTarget:
    name = "cursor"

    def detect(self, context: InstallContext) -> bool:
        try:
            rule_path = repo_path(context, ".cursor/rules/ahadiff.mdc")
            return rule_path.exists() and "AHADIFF:GENERATED" in rule_path.read_text(
                encoding="utf-8"
            )
        except OSError:
            return False

    def preview(self, context: InstallContext) -> str:
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        rule_path = repo_path(context, ".cursor/rules/ahadiff.mdc")
        write_generated_file(
            rule_path,
            content=render_template("cursor_rule.mdc.j2"),
            force=context.force,
        )
        return [rule_path]

    def uninstall(self, context: InstallContext) -> list[Path]:
        rule_path = repo_path(context, ".cursor/rules/ahadiff.mdc")
        if remove_generated_file(rule_path):
            remove_empty_parents(rule_path, stop_at=context.repo_root)
            return [rule_path]
        return []

    def _plan(self, context: InstallContext) -> InstallPlan:
        return plan_for(
            self.name,
            "Install AhaDiff guidance for Cursor rules.",
            [InstallAction(repo_path(context, ".cursor/rules/ahadiff.mdc"), "write")],
        )
