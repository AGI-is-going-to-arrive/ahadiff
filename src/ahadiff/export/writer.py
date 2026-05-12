"""Containment + reserved-name guards for export file writes."""

from __future__ import annotations

import contextlib
import errno
import os
import re
import stat
import uuid
from pathlib import Path

from ahadiff.core.errors import InputError

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)

_PATH_TRAVERSAL_RE = re.compile(r"(^|[\\/])\.\.([\\/]|$)")


def _absolute_norm(path: Path) -> Path:
    # Path.resolve() follows symlinks; containment checks here need lexical normalization.
    return Path(os.path.abspath(os.fspath(path)))  # noqa: PTH100


def _segment_is_reserved(segment: str) -> bool:
    stem = segment.split(".", 1)[0]
    return stem.upper() in _WINDOWS_RESERVED_NAMES


def _validate_segment(segment: str) -> None:
    if not segment:
        raise InputError("export path segment must not be empty")
    if segment in {".", ".."}:
        raise InputError(f"export path segment must not be '{segment}'")
    if segment.endswith((".", " ")):
        raise InputError("export path segment must not end with '.' or ' ' (Windows compatibility)")
    if ":" in segment:
        raise InputError("export path segment must not contain ':' (Windows ADS / drive separator)")
    if "\x00" in segment:
        raise InputError("export path segment must not contain NUL")
    for char in segment:
        if ord(char) < 0x20:
            raise InputError("export path segment must not contain control characters")
    if _segment_is_reserved(segment):
        raise InputError(f"export path segment '{segment}' is a Windows reserved device name")


def _validate_relative_path(rel_path: str) -> tuple[str, ...]:
    if not rel_path:
        raise InputError("export relative path must not be empty")
    if rel_path.startswith(("/", "\\")):
        raise InputError("export relative path must not be absolute")
    if Path(rel_path).is_absolute():
        raise InputError("export relative path must not be absolute")
    if _PATH_TRAVERSAL_RE.search(rel_path):
        raise InputError("export relative path must not contain '..' segments")
    if "\x00" in rel_path:
        raise InputError("export relative path must not contain NUL")
    normalized = rel_path.replace("\\", "/")
    segments = tuple(part for part in normalized.split("/") if part != "")
    if not segments:
        raise InputError("export relative path must not resolve to empty")
    for segment in segments:
        _validate_segment(segment)
    return segments


def validate_export_relative_path(rel_path: str) -> tuple[str, ...]:
    """Validate an export manifest/write path and return POSIX-style segments."""

    return _validate_relative_path(rel_path)


def ensure_output_contained(output_root: Path, target_path: Path) -> Path:
    """Resolve ``target_path`` and ensure it stays inside ``output_root``."""
    resolved_root = _absolute_norm(output_root)
    resolved_target = _absolute_norm(target_path)
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise InputError(f"export target path escapes output root: {target_path}") from exc
    return resolved_target


def _reject_unsafe_existing(path: Path) -> None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(path_stat.st_mode):
        raise OSError(
            errno.ELOOP,
            "refusing to follow export target symlink",
            str(path),
        )
    if bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
        raise OSError(
            errno.ELOOP,
            "refusing to follow export target reparse point",
            str(path),
        )
    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError(
            errno.EINVAL,
            "export target must be a regular file when it exists",
            str(path),
        )


def _reject_unsafe_dir(path: Path) -> None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(path_stat.st_mode):
        raise OSError(
            errno.ELOOP,
            "refusing to follow export parent symlink",
            str(path),
        )
    if bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
        raise OSError(
            errno.ELOOP,
            "refusing to follow export parent reparse point",
            str(path),
        )
    if not stat.S_ISDIR(path_stat.st_mode):
        raise OSError(
            errno.ENOTDIR,
            "export parent must be a directory",
            str(path),
        )


def _dir_identity(path_stat: os.stat_result) -> tuple[int, int]:
    return int(path_stat.st_dev), int(path_stat.st_ino)


def _open_safe_parent_dir(parent: Path) -> tuple[int, tuple[int, int]]:
    parent_stat = parent.lstat()
    _reject_unsafe_dir(parent)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(parent), flags)
    except OSError:
        raise
    try:
        fd_stat = os.fstat(fd)
        if not stat.S_ISDIR(fd_stat.st_mode):
            raise OSError(errno.ENOTDIR, "export parent must be a directory", str(parent))
        if bool(getattr(fd_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
            raise OSError(
                errno.ELOOP,
                "refusing to follow export parent reparse point",
                str(parent),
            )
        if _dir_identity(fd_stat) != _dir_identity(parent_stat):
            raise OSError(errno.EAGAIN, "export parent changed during validation", str(parent))
        return fd, _dir_identity(fd_stat)
    except BaseException:
        os.close(fd)
        raise


def _parent_identity_unchanged(parent: Path, expected: tuple[int, int]) -> None:
    parent_stat = parent.lstat()
    _reject_unsafe_dir(parent)
    if _dir_identity(parent_stat) != expected:
        raise OSError(errno.EAGAIN, "export parent changed during validation", str(parent))


def _replace_from_parent_fd(
    *,
    parent_fd: int,
    parent: Path,
    parent_identity: tuple[int, int],
    tmp_name: str,
    target_name: str,
) -> None:
    _parent_identity_unchanged(parent, parent_identity)
    try:
        os.replace(tmp_name, target_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    except TypeError:
        _parent_identity_unchanged(parent, parent_identity)
        (parent / tmp_name).replace(parent / target_name)
        _parent_identity_unchanged(parent, parent_identity)


def _ensure_parent(output_root: Path, target: Path) -> None:
    parent = target.parent
    if parent == target:
        return
    relative_parent = parent.relative_to(output_root)
    cursor = output_root
    for part in relative_parent.parts:
        cursor = cursor / part
        try:
            cursor.lstat()
        except FileNotFoundError:
            cursor.mkdir()
        _reject_unsafe_dir(cursor)


def validate_export_directory(output_root: Path, *, create: bool = False) -> Path:
    """Return an absolute export directory after rejecting symlink/reparse ancestors."""

    absolute = _absolute_norm(output_root)
    if not absolute.anchor:
        raise InputError("export output root must be absolute")
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor = cursor / part
        try:
            cursor.lstat()
        except FileNotFoundError:
            if not create:
                raise InputError(f"export output directory does not exist: {cursor}") from None
            cursor.mkdir()
        _reject_unsafe_dir(cursor)
    return absolute


def safe_write_export_file(
    output_root: Path,
    rel_path: str,
    content: bytes | str,
) -> Path:
    """Write ``content`` to ``rel_path`` inside ``output_root`` with safety guards."""
    segments = _validate_relative_path(rel_path)
    resolved_root = validate_export_directory(output_root, create=True)
    target = resolved_root.joinpath(*segments)
    target = ensure_output_contained(resolved_root, target)
    _ensure_parent(resolved_root, target)
    _reject_unsafe_existing(target)

    data = content.encode("utf-8") if isinstance(content, str) else content
    parent_fd, parent_identity = _open_safe_parent_dir(target.parent)
    tmp_name = f".{target.name}.{uuid.uuid4().hex}.ahadiff-export.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = -1
    try:
        fd = os.open(tmp_name, flags, 0o600, dir_fd=parent_fd)
        with os.fdopen(fd, "wb") as fh:
            fd = -1
            fh.write(data)
        _replace_from_parent_fd(
            parent_fd=parent_fd,
            parent=target.parent,
            parent_identity=parent_identity,
            tmp_name=tmp_name,
            target_name=target.name,
        )
    except BaseException:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp_name, dir_fd=parent_fd)
        raise
    finally:
        os.close(parent_fd)
    return target


__all__ = [
    "ensure_output_contained",
    "safe_write_export_file",
    "validate_export_directory",
    "validate_export_relative_path",
]
