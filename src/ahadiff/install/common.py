from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ahadiff.core.errors import InputError

from .base import (
    InstallAction,
    InstallContext,
    InstallManifest,
    InstallPlan,
    InstallTarget,
    marker_for,
    with_file_strategy,
)
from .template_loader import render_template

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def repo_path(context: InstallContext, relative: str) -> Path:
    return context.repo_root / relative


def section_from_template(target: str, template_name: str) -> str:
    return marker_for(target, render_template(template_name))


def plan_for(target: str, summary: str, actions: list[InstallAction]) -> InstallPlan:
    return InstallPlan(
        target=target,
        summary=summary,
        actions=tuple(with_file_strategy(action) for action in actions),
    )


def manifest_preview_for(target: InstallTarget, context: InstallContext) -> str:
    plan_factory = getattr(target, "_plan", None)
    if not callable(plan_factory):
        raise InputError(f"install target {target.name!r} does not expose a manifest plan")
    target.preview(context)
    plan = cast("Callable[[InstallContext], InstallPlan]", plan_factory)(context)
    manifest = plan.manifest()
    uninstall_plan_factory = getattr(target, "_uninstall_plan", None)
    if callable(uninstall_plan_factory):
        uninstall_plan = cast("Callable[[InstallContext], InstallPlan]", uninstall_plan_factory)(
            context
        )
        manifest = InstallManifest(
            target=manifest.target,
            preview_actions=manifest.preview_actions,
            write_actions=manifest.write_actions,
            uninstall_actions=uninstall_plan.manifest().uninstall_actions,
        )
    return manifest.render(context.repo_root)
