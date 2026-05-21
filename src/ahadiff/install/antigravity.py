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


class AntigravityTarget:
    name = "antigravity"

    def detect(self, context: InstallContext) -> bool:
        skill_path = repo_path(context, ".agents/skills/ahadiff-antigravity/SKILL.md")
        rule_path = repo_path(context, ".agents/rules/ahadiff.md")
        return is_generated_file(skill_path) or is_generated_file(rule_path)

    def preview(self, context: InstallContext) -> str:
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        skill_path = repo_path(context, ".agents/skills/ahadiff-antigravity/SKILL.md")
        write_generated_file(
            skill_path,
            content=render_template("antigravity_skill.md.j2"),
            force=context.force,
        )
        rule_path = repo_path(context, ".agents/rules/ahadiff.md")
        write_generated_file(
            rule_path,
            content=render_template("antigravity_rule.md.j2"),
            force=context.force,
        )
        return [skill_path, rule_path]

    def uninstall(self, context: InstallContext) -> list[Path]:
        removed: list[Path] = []
        skill_path = repo_path(context, ".agents/skills/ahadiff-antigravity/SKILL.md")
        if remove_generated_file(skill_path):
            remove_empty_parents(skill_path, stop_at=context.repo_root)
            removed.append(skill_path)
        rule_path = repo_path(context, ".agents/rules/ahadiff.md")
        if remove_generated_file(rule_path):
            remove_empty_parents(rule_path, stop_at=context.repo_root)
            removed.append(rule_path)
        return removed

    def _plan(self, context: InstallContext) -> InstallPlan:
        return plan_for(
            self.name,
            "Install AhaDiff guidance for Antigravity IDE workspace skills and rules.",
            [
                InstallAction(
                    repo_path(context, ".agents/skills/ahadiff-antigravity/SKILL.md"),
                    "write",
                ),
                InstallAction(repo_path(context, ".agents/rules/ahadiff.md"), "write"),
            ],
        )
