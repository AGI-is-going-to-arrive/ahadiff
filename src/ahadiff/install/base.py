from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from ahadiff.core.errors import InputError

if TYPE_CHECKING:
    from pathlib import Path

InstallFileStrategy = Literal["generated", "user-managed"]

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
    file_strategy: InstallFileStrategy | None = None


@dataclass(frozen=True)
class InstallManifest:
    target: str
    preview_actions: tuple[InstallAction, ...]
    write_actions: tuple[InstallAction, ...]
    uninstall_actions: tuple[InstallAction, ...]

    def render(self, repo_root: Path) -> str:
        payload = {
            "schema_version": 1,
            "target": self.target,
            "actions": {
                "preview": [_manifest_action(action, repo_root) for action in self.preview_actions],
                "write": [_manifest_action(action, repo_root) for action in self.write_actions],
                "uninstall": [
                    _manifest_action(action, repo_root) for action in self.uninstall_actions
                ],
            },
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class InstallPlan:
    target: str
    summary: str
    actions: tuple[InstallAction, ...]

    def manifest(self) -> InstallManifest:
        actions = tuple(with_file_strategy(action) for action in self.actions)
        return InstallManifest(
            target=self.target,
            preview_actions=actions,
            write_actions=actions,
            uninstall_actions=tuple(_uninstall_action(action) for action in actions),
        )

    def render_manifest(self, repo_root: Path) -> str:
        return self.manifest().render(repo_root)

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


def infer_file_strategy(action: str) -> InstallFileStrategy:
    if action in {"write", "remove"}:
        return "generated"
    return "user-managed"


def with_file_strategy(action: InstallAction) -> InstallAction:
    if action.file_strategy is not None:
        return action
    return InstallAction(
        path=action.path,
        action=action.action,
        file_strategy=infer_file_strategy(action.action),
    )


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


def _uninstall_action(action: InstallAction) -> InstallAction:
    file_strategy = action.file_strategy or infer_file_strategy(action.action)
    action_name = "remove" if file_strategy == "generated" else "remove-section"
    return InstallAction(path=action.path, action=action_name, file_strategy=file_strategy)


def _manifest_action(action: InstallAction, repo_root: Path) -> dict[str, str]:
    try:
        display_path = action.path.relative_to(repo_root).as_posix()
    except ValueError:
        display_path = str(action.path)
    return {
        "action": action.action,
        "file_strategy": action.file_strategy or infer_file_strategy(action.action),
        "path": display_path,
    }


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
