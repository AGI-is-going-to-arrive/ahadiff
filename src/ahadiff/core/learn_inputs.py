"""Bounded, explicit local-file inputs shared by CLI and HTTP learn adapters."""

from __future__ import annotations

import os
import stat
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ahadiff.contracts.run_source import COMPARE_FILE_MAX_BYTES, CompareFileInput
from ahadiff.core.errors import InputError
from ahadiff.safety.ignore import resolve_safe_path_from_root

if TYPE_CHECKING:
    from ahadiff.contracts.run_source import SnapshotProvenance

_HAS_DIR_FD = os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _check_stat(value: os.stat_result, *, directory: bool = False) -> None:
    if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
        raise InputError("selected input must not contain links or reparse points")
    if directory:
        if not stat.S_ISDIR(value.st_mode):
            raise InputError("selected input parent must be a directory")
    elif not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise InputError("selected input must be a regular file without hardlinks")


def _verify_parents(parents: list[tuple[Path, os.stat_result]]) -> None:
    for parent, expected in parents:
        current = parent.lstat()
        _check_stat(current, directory=True)
        if _identity(current) != _identity(expected):
            raise InputError("selected input parent changed during read")


def _read_bound_file(source: Path, *, max_bytes: int) -> bytes:
    """Bind each POSIX parent descriptor; recheck the full parent chain elsewhere."""
    parents: list[tuple[Path, os.stat_result]] = []
    with ExitStack() as stack:
        cursor = Path(source.anchor)
        parent_fd: int | None = None
        if _HAS_DIR_FD:
            parent_fd = os.open(cursor, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            stack.callback(os.close, parent_fd)
        for part in source.parts[1:-1]:
            cursor = cursor / part
            expected = (
                os.stat(part, dir_fd=parent_fd, follow_symlinks=False)
                if parent_fd is not None
                else cursor.lstat()
            )
            _check_stat(expected, directory=True)
            parents.append((cursor, expected))
            if parent_fd is not None:
                child_fd = os.open(
                    part,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_fd,
                )
                stack.callback(os.close, child_fd)
                opened = os.fstat(child_fd)
                _check_stat(opened, directory=True)
                if _identity(opened) != _identity(expected):
                    raise InputError("selected input parent changed during read")
                parent_fd = child_fd
        _verify_parents(parents)
        expected = (
            os.stat(source.name, dir_fd=parent_fd, follow_symlinks=False)
            if parent_fd is not None
            else source.lstat()
        )
        _check_stat(expected)
        if expected.st_size > max_bytes:
            raise InputError("selected input exceeds its byte limit")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = (
            os.open(source.name, flags, dir_fd=parent_fd)
            if parent_fd is not None
            else os.open(source, flags)
        )
        stack.callback(os.close, fd)
        opened = os.fstat(fd)
        _check_stat(opened)
        if _identity(opened) != _identity(expected) or opened.st_size > max_bytes:
            raise InputError("selected input changed during read")
        _verify_parents(parents)
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            chunk = os.read(fd, min(65_536, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > max_bytes:
            raise InputError("selected input exceeds its byte limit")
        final = os.fstat(fd)
        _check_stat(final)
        current = (
            os.stat(source.name, dir_fd=parent_fd, follow_symlinks=False)
            if parent_fd is not None
            else source.lstat()
        )
        _check_stat(current)
        if _identity(final) != _identity(current) or (
            final.st_size,
            final.st_mtime_ns,
            final.st_ctime_ns,
        ) != (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
            raise InputError("selected input changed during read")
        _verify_parents(parents)
        return b"".join(chunks)


def read_learning_text(root: Path, file: Path, *, max_bytes: int) -> str:
    """Read only the explicitly selected, regular workspace file, without following links."""
    source = resolve_safe_path_from_root(root, file)
    try:
        return _read_bound_file(source, max_bytes=max_bytes).decode("utf-8")
    except UnicodeDecodeError:
        raise InputError("selected input must be valid UTF-8") from None
    except OSError:
        raise InputError("selected input could not be read safely") from None


def read_learning_file(root: Path, file: Path) -> CompareFileInput:
    content = read_learning_text(root, file, max_bytes=COMPARE_FILE_MAX_BYTES)
    try:
        return CompareFileInput(name=file.name, content=content)
    except ValidationError:
        raise InputError("selected file has an invalid name or UTF-8 text body") from None


def resolve_snapshot_comparison(
    root: Path,
    snapshot_id: str,
    *,
    expected_hash: str | None,
    after: CompareFileInput,
) -> tuple[tuple[CompareFileInput, CompareFileInput], SnapshotProvenance]:
    from ahadiff.contracts.run_source import SnapshotProvenance
    from ahadiff.core.snapshots import load_snapshot, prepare_snapshot_file

    record = load_snapshot(root, snapshot_id, expected_hash=expected_hash)
    before = CompareFileInput(name=record.file_name, content=record.content)
    # Baseline and current file must have identical filtering semantics. Diffing
    # a stored redaction against an unfiltered secret would manufacture a change.
    prepared_after = prepare_snapshot_file(after)
    provenance = SnapshotProvenance(
        snapshot_id=record.snapshot_id,
        content_hash=record.content_hash,
        hash_scope=record.hash_scope,
        name=record.name,
        file_name=record.file_name,
        sanitized=record.sanitized,
        schema_version=record.schema_version,
    )
    return (before, prepared_after), provenance
