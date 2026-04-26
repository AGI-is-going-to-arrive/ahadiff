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


class ClineTarget:
    name = "cline"

    def detect(self, context: InstallContext) -> bool:
        return _is_generated(self._rules_path(context))

    def preview(self, context: InstallContext) -> str:
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        rules_path = self._rules_path(context)
        write_generated_file(
            rules_path,
            content=render_template("cline_rules.md.j2"),
            force=context.force,
        )
        return [rules_path]

    def uninstall(self, context: InstallContext) -> list[Path]:
        rules_path = self._rules_path(context)
        if not remove_generated_file(rules_path):
            return []
        remove_empty_parents(rules_path, stop_at=context.repo_root)
        return [rules_path]

    def _plan(self, context: InstallContext) -> InstallPlan:
        return plan_for(
            self.name,
            "Install AhaDiff guidance for Cline.",
            [InstallAction(self._rules_path(context), "write")],
        )

    def _rules_path(self, context: InstallContext) -> Path:
        return repo_path(context, ".clinerules/ahadiff.md")


def _is_generated(path: Path) -> bool:
    try:
        return path.exists() and "AHADIFF:GENERATED" in path.read_text(encoding="utf-8")
    except OSError:
        return False
