from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import stat
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
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_GENERATED_SENTINELS = frozenset({"<!-- AHADIFF:GENERATED -->", "# AHADIFF:GENERATED"})


@dataclass(frozen=True)
class InstallContext:
    repo_root: Path
    force: bool = False
    layer2: bool = False
    auto_learn: bool = False


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
        for action in self.manifest().uninstall_actions:
            try:
                display_path = action.path.relative_to(repo_root).as_posix()
            except ValueError:
                display_path = str(action.path)
            action_label = "remove section" if action.action == "remove-section" else action.action
            lines.append(f"- {action_label}: {display_path}")
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
    marker = f"<!-- AHADIFF:BEGIN target={target} -->"
    try:
        return marker in _read_text_no_follow_regular(path, "install target")
    except FileNotFoundError:
        return False


def is_generated_file(path: Path) -> bool:
    try:
        content = _read_text_no_follow_regular(path, "generated install target")
        return _has_generated_sentinel(content)
    except (FileNotFoundError, OSError):
        return False


def merge_marked_section(path: Path, target: str, section: str) -> str:
    try:
        original = _read_text_no_follow_regular(path, "install target")
    except FileNotFoundError:
        return section
    marker = f"<!-- AHADIFF:BEGIN target={target} -->"
    if marker in original:
        return _replace_marked_section(original, target, section)
    separator = "\n\n" if original and not original.endswith("\n\n") else ""
    return f"{original}{separator}{section}"


def write_marked_section(path: Path, target: str, section: str) -> None:
    _prepare_install_file_write(path, "install target")
    _atomic_write(path, merge_marked_section(path, target, section))


def remove_marked_section(path: Path, target: str) -> bool:
    try:
        original = _read_text_no_follow_regular(path, "install target")
    except FileNotFoundError:
        return False
    pattern = re.compile(
        rf"\n?<!-- AHADIFF:BEGIN target={re.escape(target)} -->.*?"
        r"<!-- AHADIFF:END -->\n?",
        re.DOTALL,
    )
    updated, count = pattern.subn("\n", original)
    if count == 0:
        return False
    _prepare_install_file_write(path, "install target")
    _atomic_write(path, updated.strip() + "\n" if updated.strip() else "")
    return True


def write_generated_file(
    path: Path,
    *,
    content: str,
    force: bool,
) -> None:
    try:
        existing = _read_text_no_follow_regular(path, "generated install target")
    except FileNotFoundError:
        existing = None
    if existing is not None and not force and not _has_generated_sentinel(existing):
        raise InputError(f"refusing to overwrite user-managed file without --force: {path}")
    _prepare_install_file_write(path, "generated install target")
    _atomic_write(path, content)


def remove_generated_file(path: Path) -> bool:
    try:
        content = _read_text_no_follow_regular(path, "generated install target")
    except FileNotFoundError:
        return False
    if not _has_generated_sentinel(content):
        return False
    _prepare_install_file_write(path, "generated install target")
    path.unlink()
    return True


def _replace_marked_section(original: str, target: str, section: str) -> str:
    pattern = re.compile(
        rf"<!-- AHADIFF:BEGIN target={re.escape(target)} -->.*?<!-- AHADIFF:END -->",
        re.DOTALL,
    )
    updated, count = pattern.subn(section.strip(), original, count=1)
    return updated if count else original


def _has_generated_sentinel(content: str) -> bool:
    lines = content.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index].strip() == "---":
        index += 1
        while index < len(lines) and lines[index].strip() != "---":
            index += 1
        if index >= len(lines):
            return False
        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
    if index >= len(lines):
        return False
    return lines[index].strip() in _GENERATED_SENTINELS


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


def _has_windows_reparse_point(path_stat: os.stat_result) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _ensure_no_symlink_or_reparse(path: Path, path_stat: os.stat_result, description: str) -> None:
    if stat.S_ISLNK(path_stat.st_mode):
        raise OSError(errno.ELOOP, f"refusing to follow {description} symlink", str(path))
    if _has_windows_reparse_point(path_stat):
        raise OSError(errno.ELOOP, f"refusing to follow {description} reparse point", str(path))


def _read_text_no_follow_regular(path: Path, description: str) -> str:
    _ensure_existing_directory_chain_safe(path.parent, description)
    path_stat = path.lstat()
    _ensure_no_symlink_or_reparse(path, path_stat, description)
    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError(errno.EINVAL, f"{description} must be a regular file", str(path))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    try:
        opened_stat = os.fstat(fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise OSError(errno.EINVAL, f"{description} must be a regular file", str(path))
        _ensure_no_symlink_or_reparse(path, opened_stat, description)
        if (opened_stat.st_dev, opened_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise OSError(errno.ELOOP, f"{description} changed during validation", str(path))
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd != -1:
            os.close(fd)


def read_bytes_and_mode_no_follow_regular(path: Path, description: str) -> tuple[bytes, int]:
    _ensure_existing_directory_chain_safe(path.parent, description)
    path_stat = path.lstat()
    _ensure_no_symlink_or_reparse(path, path_stat, description)
    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError(errno.EINVAL, f"{description} must be a regular file", str(path))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    try:
        opened_stat = os.fstat(fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise OSError(errno.EINVAL, f"{description} must be a regular file", str(path))
        _ensure_no_symlink_or_reparse(path, opened_stat, description)
        if (opened_stat.st_dev, opened_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise OSError(errno.ELOOP, f"{description} changed during validation", str(path))
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            return handle.read(), opened_stat.st_mode
    finally:
        if fd != -1:
            os.close(fd)


def read_bytes_no_follow_regular(path: Path, description: str) -> bytes:
    content, _mode = read_bytes_and_mode_no_follow_regular(path, description)
    return content


def _prepare_install_file_write(path: Path, description: str) -> None:
    _ensure_safe_parent_dir(path.parent, description)
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return
    _ensure_no_symlink_or_reparse(path, path_stat, description)
    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError(errno.EINVAL, f"{description} must be a regular file", str(path))


def _ensure_safe_parent_dir(parent: Path, description: str) -> None:
    if parent.exists():
        _ensure_existing_directory_chain_safe(parent, description)
        return
    missing: list[Path] = []
    current = parent
    while True:
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            missing.append(current)
            current = current.parent
            if current == current.parent:
                raise
            continue
        _ensure_no_symlink_or_reparse(current, current_stat, f"{description} parent")
        if not stat.S_ISDIR(current_stat.st_mode):
            raise OSError(errno.ENOTDIR, f"{description} parent must be a directory", str(current))
        break
    for directory in reversed(missing):
        try:
            directory_stat = directory.lstat()
        except FileNotFoundError:
            directory.mkdir()
            directory_stat = directory.lstat()
        _ensure_no_symlink_or_reparse(directory, directory_stat, f"{description} parent")
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise OSError(
                errno.ENOTDIR,
                f"{description} parent must be a directory",
                str(directory),
            )


def _ensure_existing_directory_safe(path: Path, description: str) -> None:
    path_stat = path.lstat()
    _ensure_no_symlink_or_reparse(path, path_stat, f"{description} parent")
    if not stat.S_ISDIR(path_stat.st_mode):
        raise OSError(errno.ENOTDIR, f"{description} parent must be a directory", str(path))


def _ensure_existing_directory_chain_safe(path: Path, description: str) -> None:
    chain = [path, *path.parents]
    for directory in reversed(chain):
        if not directory.exists():
            continue
        _ensure_existing_directory_safe(directory, description)


def _atomic_write(path: Path, content: str) -> None:
    import tempfile
    from pathlib import Path as _Path

    text = content if content.endswith("\n") else f"{content}\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".ahadiff.tmp"
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
        _Path(tmp_name).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            _Path(tmp_name).unlink()
        raise


def atomic_write_bytes(path: Path, content: bytes, *, mode: int | None = None) -> None:
    import tempfile
    from pathlib import Path as _Path

    desired_mode = stat.S_IMODE(mode) if mode is not None else None
    chmod_after_replace = False
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".ahadiff.tmp"
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
            if desired_mode is not None:
                fchmod = getattr(os, "fchmod", None)
                if callable(fchmod):
                    with contextlib.suppress(OSError, NotImplementedError):
                        fchmod(fh.fileno(), desired_mode)
                else:
                    chmod_after_replace = True
        _Path(tmp_name).replace(path)
        if chmod_after_replace and desired_mode is not None:
            with contextlib.suppress(OSError, NotImplementedError):
                path.chmod(desired_mode)
    except BaseException:
        with contextlib.suppress(OSError):
            _Path(tmp_name).unlink()
        raise


def remove_empty_parents(path: Path, *, stop_at: Path) -> None:
    current = path.parent
    stop = stop_at.resolve()
    while current.resolve() != stop and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
