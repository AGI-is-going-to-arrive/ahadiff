from __future__ import annotations

from typing import TYPE_CHECKING

from .base import (
    InstallAction,
    InstallContext,
    remove_empty_parents,
    remove_generated_file,
    write_generated_file,
)
from .common import plan_for, repo_path
from .template_loader import render_template

if TYPE_CHECKING:
    from pathlib import Path


class GitHubActionTarget:
    name = "github-action"

    def detect(self, context: InstallContext) -> bool:
        return any(path.exists() for path in self._workflow_paths(context))

    def preview(self, context: InstallContext) -> str:
        return self._plan(context).render(context.repo_root)

    def preview_uninstall(self, context: InstallContext) -> str:
        return self._uninstall_plan(context).render_uninstall(context.repo_root)

    def write(self, context: InstallContext) -> list[Path]:
        written: list[Path] = []
        verify_path = repo_path(context, ".github/workflows/ahadiff-verify.yml")
        write_generated_file(
            verify_path,
            content=render_template("ahadiff-verify.yml.j2"),
            force=context.force,
        )
        written.append(verify_path)
        if context.layer2:
            generate_path = repo_path(context, ".github/workflows/ahadiff-generate.yml")
            write_generated_file(
                generate_path,
                content=render_template("ahadiff-generate.yml.j2"),
                force=context.force,
            )
            written.append(generate_path)
        return written

    def uninstall(self, context: InstallContext) -> list[Path]:
        removed: list[Path] = []
        for path in self._workflow_paths(context):
            if remove_generated_file(path):
                remove_empty_parents(path, stop_at=context.repo_root)
                removed.append(path)
        return removed

    def _plan(self, context: InstallContext):
        actions = [
            InstallAction(repo_path(context, ".github/workflows/ahadiff-verify.yml"), "write")
        ]
        if context.layer2:
            actions.append(
                InstallAction(repo_path(context, ".github/workflows/ahadiff-generate.yml"), "write")
            )
        return plan_for(
            self.name,
            "Install AhaDiff GitHub Actions workflows.",
            actions,
        )

    def _workflow_paths(self, context: InstallContext) -> tuple[Path, Path]:
        return (
            repo_path(context, ".github/workflows/ahadiff-verify.yml"),
            repo_path(context, ".github/workflows/ahadiff-generate.yml"),
        )

    def _uninstall_plan(self, context: InstallContext):
        return plan_for(
            self.name,
            "Remove AhaDiff GitHub Actions workflows.",
            [
                InstallAction(repo_path(context, ".github/workflows/ahadiff-verify.yml"), "remove"),
                InstallAction(
                    repo_path(context, ".github/workflows/ahadiff-generate.yml"), "remove"
                ),
            ],
        )
