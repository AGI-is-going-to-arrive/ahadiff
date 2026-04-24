from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ahadiff.core.errors import InputError

if TYPE_CHECKING:
    from pathlib import Path

SECTION_RE = re.compile(
    r"\n?<!-- AHADIFF:BEGIN target=(?P<target>[A-Za-z0-9_-]+) -->.*?"
    r"<!-- AHADIFF:END -->\n?",
    re.DOTALL,
)


@dataclass(frozen=True)
class InstallContext:
    repo_root: Path
    force: bool = False
    layer2: bool = False


@dataclass(frozen=True)
class InstallAction:
    path: Path
    action: str


@dataclass(frozen=True)
class InstallPlan:
    target: str
    summary: str
    actions: tuple[InstallAction, ...]

    def render(self, repo_root: Path) -> str:
        lines = [self.summary, ""]
        for action in self.actions:
            try:
                display_path = action.path.relative_to(repo_root).as_posix()
            except ValueError:
                display_path = str(action.path)
            lines.append(f"- {action.action}: {display_path}")
        return "\n".join(lines).rstrip() + "\n"

    def render_uninstall(self, repo_root: Path) -> str:
        lines = [f"Remove {self.target} AhaDiff install artifacts.", ""]
        for action in self.actions:
            try:
                display_path = action.path.relative_to(repo_root).as_posix()
            except ValueError:
                display_path = str(action.path)
            lines.append(f"- remove: {display_path}")
        return "\n".join(lines).rstrip() + "\n"


class InstallTarget(Protocol):
    name: str

    def detect(self, context: InstallContext) -> bool: ...

    def preview(self, context: InstallContext) -> str: ...

    def preview_uninstall(self, context: InstallContext) -> str: ...

    def write(self, context: InstallContext) -> list[Path]: ...

    def uninstall(self, context: InstallContext) -> list[Path]: ...


def marker_for(target: str, body: str) -> str:
    stripped = body.strip()
    return f"<!-- AHADIFF:BEGIN target={target} -->\n{stripped}\n<!-- AHADIFF:END -->\n"


def has_marker(path: Path, target: str) -> bool:
    if not path.exists():
        return False
    marker = f"<!-- AHADIFF:BEGIN target={target} -->"
    return marker in path.read_text(encoding="utf-8")


def merge_marked_section(path: Path, target: str, section: str) -> str:
    if not path.exists():
        return section
    original = path.read_text(encoding="utf-8")
    marker = f"<!-- AHADIFF:BEGIN target={target} -->"
    if marker in original:
        return _replace_marked_section(original, target, section)
    separator = "\n\n" if original and not original.endswith("\n\n") else ""
    return f"{original}{separator}{section}"


def write_marked_section(path: Path, target: str, section: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, merge_marked_section(path, target, section))


def remove_marked_section(path: Path, target: str) -> bool:
    if not path.exists():
        return False
    original = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"\n?<!-- AHADIFF:BEGIN target={re.escape(target)} -->.*?"
        r"<!-- AHADIFF:END -->\n?",
        re.DOTALL,
    )
    updated, count = pattern.subn("\n", original)
    if count == 0:
        return False
    _atomic_write(path, updated.strip() + "\n" if updated.strip() else "")
    return True


def write_generated_file(
    path: Path,
    *,
    content: str,
    force: bool,
) -> None:
    if path.exists() and not force and "AHADIFF:GENERATED" not in path.read_text(encoding="utf-8"):
        raise InputError(f"refusing to overwrite user-managed file without --force: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, content)


def remove_generated_file(path: Path) -> bool:
    if not path.exists():
        return False
    if "AHADIFF:GENERATED" not in path.read_text(encoding="utf-8"):
        return False
    path.unlink()
    return True


def _replace_marked_section(original: str, target: str, section: str) -> str:
    pattern = re.compile(
        rf"<!-- AHADIFF:BEGIN target={re.escape(target)} -->.*?<!-- AHADIFF:END -->",
        re.DOTALL,
    )
    updated, count = pattern.subn(section.strip(), original, count=1)
    return updated if count else original


def _atomic_write(path: Path, content: str) -> None:
    temp_path = path.with_name(f".{path.name}.ahadiff.tmp")
    temp_path.write_text(content if content.endswith("\n") else f"{content}\n", encoding="utf-8")
    temp_path.replace(path)


def remove_empty_parents(path: Path, *, stop_at: Path) -> None:
    current = path.parent
    stop = stop_at.resolve()
    while current.resolve() != stop and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
