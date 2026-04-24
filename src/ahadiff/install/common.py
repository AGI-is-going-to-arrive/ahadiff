from __future__ import annotations

from typing import TYPE_CHECKING

from .base import InstallAction, InstallContext, InstallPlan, marker_for
from .template_loader import render_template

if TYPE_CHECKING:
    from pathlib import Path


def repo_path(context: InstallContext, relative: str) -> Path:
    return context.repo_root / relative


def section_from_template(target: str, template_name: str) -> str:
    return marker_for(target, render_template(template_name))


def plan_for(target: str, summary: str, actions: list[InstallAction]) -> InstallPlan:
    return InstallPlan(target=target, summary=summary, actions=tuple(actions))
