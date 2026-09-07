"""Native, single-file guidance targets sharing the guarded installer."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class GeneratedGuidanceTarget:
    name: str
    relative_path: str
    template_name: str = "native_skill.md.j2"

    def detect(self, context: InstallContext) -> bool:
        return is_generated_file(repo_path(context, self.relative_path))

    def preview(self, context: InstallContext) -> str:
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        path = repo_path(context, self.relative_path)
        write_generated_file(path, content=render_template(self.template_name), force=context.force)
        return [path]

    def uninstall(self, context: InstallContext) -> list[Path]:
        path = repo_path(context, self.relative_path)
        if not remove_generated_file(path):
            return []
        remove_empty_parents(path, stop_at=context.repo_root)
        return [path]

    def _plan(self, context: InstallContext) -> InstallPlan:
        return plan_for(
            self.name,
            f"Write repository-local AhaDiff guidance for {self.name}.",
            [InstallAction(repo_path(context, self.relative_path), "write")],
        )
