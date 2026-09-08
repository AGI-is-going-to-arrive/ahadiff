"""Explicit local learning baselines. Raw input is never written to disk.

Callers acquire the repository lock before mutations. A separate process/thread
lock serializes quota checks and publication without re-entering the repo lock.
POSIX operations stay bound to directory descriptors; platforms without dir_fd
use no-reparse parent checks and identity checks around each file operation.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
import threading
import time
import unicodedata
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import portalocker
from pydantic import ValidationError

from ahadiff.contracts import ErrorCode
from ahadiff.contracts.run_source import COMPARE_FILE_MAX_BYTES, CompareFileInput
from ahadiff.contracts.snapshots import (
    SNAPSHOT_HASH_PATTERN,
    SNAPSHOT_ID_PATTERN,
    SNAPSHOT_MAX_BYTES,
    SNAPSHOT_MAX_COUNT,
    SnapshotRecord,
    SnapshotSummary,
    validate_snapshot_name,
)
from ahadiff.safety.injection import protect_untrusted_text
from ahadiff.safety.redact import redaction_pipeline

from .errors import InputError, StorageError
from .json_util import safe_json_loads
from .paths import assert_local_repo_path, validate_state_path_no_symlinks

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_REPARSE_POINT = 0x400
# JSON escapes can expand each text byte to six bytes. Metadata remains bounded.
_MAX_RECORD_BYTES = 6 * COMPARE_FILE_MAX_BYTES + 16 * 1024
_MAX_DIRECTORY_ENTRIES = 1000
_LOCK_TIMEOUT = 5.0
_THREAD_LOCK = threading.Lock()
_HAS_DIR_FD = os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd


def _clean_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    redacted = redaction_pipeline(normalized).redacted_text
    protected = protect_untrusted_text(redacted, source_name="snapshot", source_kind="string")
    # Stable short markers cannot themselves trigger the entropy detector on a
    # later comparison. No injection report containing excerpts is persisted.
    return re.sub(r"\[INJECTION_BLOCKED:[A-Z_]+\]", "[INJECTION_BLOCKED]", protected.protected_text)


def _clean_name(name: str) -> str:
    return re.sub(r"\[REDACTED:[a-z_]+\]", "[REDACTED]", _clean_text(name))


def prepare_snapshot_file(file: CompareFileInput) -> CompareFileInput:
    """Apply the same deterministic privacy policy to saved and later inputs."""
    try:
        return CompareFileInput(name=_clean_name(file.name), content=_clean_text(file.content))
    except (ValidationError, ValueError):
        raise InputError("snapshot_file_invalid_after_sanitization") from None


def _validate_id(snapshot_id: str) -> None:
    if not re.fullmatch(SNAPSHOT_ID_PATTERN, snapshot_id):
        raise InputError("snapshot_id_invalid")


def _validate_hash(expected_hash: str) -> None:
    if not re.fullmatch(SNAPSHOT_HASH_PATTERN, expected_hash):
        raise InputError("snapshot_expected_hash_invalid")


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _validate_stat(value: os.stat_result, *, directory: bool = False) -> None:
    if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & _REPARSE_POINT:
        raise InputError("snapshot_path_must_not_be_a_link_or_reparse_point")
    if directory:
        if not stat.S_ISDIR(value.st_mode):
            raise InputError("snapshot_parent_must_be_a_directory")
    elif not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise InputError("snapshot_file_must_be_regular_and_not_hardlinked")


@dataclass(frozen=True)
class _Directory:
    path: Path
    expected_stat: os.stat_result
    fd: int | None

    def check(self) -> None:
        validate_state_path_no_symlinks(self.path, allow_missing_leaf=False)
        current = self.path.lstat()
        _validate_stat(current, directory=True)
        if _identity(current) != _identity(self.expected_stat):
            raise InputError("snapshot_directory_changed")
        if self.fd is not None and _identity(os.fstat(self.fd)) != _identity(current):
            raise InputError("snapshot_directory_changed")

    def entry_stat(self, name: str) -> os.stat_result:
        self.check()
        if self.fd is not None:
            return os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        return (self.path / name).lstat()

    def open_file(self, name: str, flags: int) -> int:
        self.check()
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        if self.fd is not None:
            return os.open(name, flags, 0o600, dir_fd=self.fd)
        return os.open(self.path / name, flags, 0o600)

    def unlink(self, name: str) -> None:
        self.check()
        if self.fd is not None:
            os.unlink(name, dir_fd=self.fd)
        else:
            (self.path / name).unlink()

    def names(self) -> list[str]:
        self.check()
        result: list[str] = []
        with os.scandir(self.fd if self.fd is not None else self.path) as entries:
            for entry in entries:
                result.append(entry.name)
                if len(result) > _MAX_DIRECTORY_ENTRIES:
                    raise InputError("snapshot_directory_entry_limit_exceeded")
        self.check()
        return sorted(result)


@contextmanager
def _root_directory(workspace_root: Path) -> Iterator[_Directory]:
    root = workspace_root.absolute()
    assert_local_repo_path(root)
    if ".." in root.parts:
        raise InputError("snapshot_workspace_path_invalid")
    validate_state_path_no_symlinks(root, allow_missing_leaf=False)
    root_stat = root.lstat()
    _validate_stat(root_stat, directory=True)
    fd: int | None = None
    if _HAS_DIR_FD:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        # Walk every parent using descriptors; O_NOFOLLOW alone protects only a leaf.
        fd = os.open(root.anchor, flags)
        try:
            for part in root.parts[1:]:
                next_fd = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
        except BaseException:
            os.close(fd)
            raise
    directory = _Directory(root, root_stat, fd)
    try:
        directory.check()
        yield directory
    finally:
        if fd is not None:
            os.close(fd)


@contextmanager
def _child_directory(parent: _Directory, name: str, *, create: bool) -> Iterator[_Directory]:
    parent.check()
    if create:
        try:
            if parent.fd is not None:
                os.mkdir(name, mode=0o700, dir_fd=parent.fd)
            else:
                (parent.path / name).mkdir(mode=0o700)
        except FileExistsError:
            pass
    expected = parent.entry_stat(name)
    _validate_stat(expected, directory=True)
    fd: int | None = None
    if parent.fd is not None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(name, flags, dir_fd=parent.fd)
    child = _Directory(parent.path / name, expected, fd)
    try:
        child.check()
        yield child
    finally:
        if fd is not None:
            os.close(fd)


def _check_open_file(directory: _Directory, name: str, fd: int) -> os.stat_result:
    opened = os.fstat(fd)
    current = directory.entry_stat(name)
    _validate_stat(opened)
    _validate_stat(current)
    if _identity(opened) != _identity(current):
        raise InputError("snapshot_file_changed")
    return opened


@contextmanager
def _mutation_lock(state: _Directory) -> Iterator[None]:
    if not _THREAD_LOCK.acquire(timeout=_LOCK_TIMEOUT):
        raise StorageError("snapshot_lock_conflict", code=ErrorCode.LOCK_CONFLICT)
    try:
        try:
            existing = state.entry_stat("snapshots.lock")
        except FileNotFoundError:
            existing = None
        if existing is not None:
            _validate_stat(existing)
        fd = state.open_file("snapshots.lock", os.O_RDWR | os.O_CREAT)
        with os.fdopen(fd, "r+b") as handle:
            opened = _check_open_file(state, "snapshots.lock", handle.fileno())
            if existing is not None and _identity(existing) != _identity(opened):
                raise InputError("snapshot_lock_changed")
            deadline = time.monotonic() + _LOCK_TIMEOUT
            while True:
                try:
                    portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
                    break
                except portalocker.exceptions.LockException:
                    if time.monotonic() >= deadline:
                        raise StorageError(
                            "snapshot_lock_conflict", code=ErrorCode.LOCK_CONFLICT
                        ) from None
                    time.sleep(0.01)
            try:
                _check_open_file(state, "snapshots.lock", handle.fileno())
                yield
            finally:
                portalocker.unlock(handle)
    finally:
        _THREAD_LOCK.release()


@contextmanager
def _store(workspace_root: Path, *, write: bool = False) -> Iterator[_Directory]:
    try:
        with (
            _root_directory(workspace_root) as root,
            _child_directory(root, ".ahadiff", create=write) as state,
        ):
            if write:
                with (
                    _mutation_lock(state),
                    _child_directory(state, "snapshots", create=True) as directory,
                ):
                    _ensure_ignored(directory)
                    yield directory
            else:
                with _child_directory(state, "snapshots", create=False) as directory:
                    yield directory
    except FileNotFoundError:
        raise
    except OSError:
        raise StorageError("snapshot_storage_failed") from None


def _read_file(directory: _Directory, name: str) -> tuple[bytes, os.stat_result]:
    expected = directory.entry_stat(name)
    _validate_stat(expected)
    if expected.st_size > _MAX_RECORD_BYTES:
        raise InputError("snapshot_record_too_large", code=ErrorCode.RUN_ARTIFACT_TOO_LARGE)
    fd = directory.open_file(name, os.O_RDONLY)
    try:
        opened = _check_open_file(directory, name, fd)
        if _identity(opened) != _identity(expected) or opened.st_size > _MAX_RECORD_BYTES:
            raise InputError("snapshot_file_changed")
        chunks: list[bytes] = []
        size = 0
        while size <= _MAX_RECORD_BYTES:
            chunk = os.read(fd, min(65536, _MAX_RECORD_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        current = _check_open_file(directory, name, fd)
        if (
            size > _MAX_RECORD_BYTES
            or size != opened.st_size
            or (current.st_mtime_ns, current.st_size) != (opened.st_mtime_ns, opened.st_size)
        ):
            raise InputError("snapshot_file_changed")
        return b"".join(chunks), current
    finally:
        os.close(fd)


def _ensure_ignored(directory: _Directory) -> None:
    try:
        fd = directory.open_file(".gitignore", os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        data, _ = _read_file(directory, ".gitignore")
        if data != b"*\n":
            raise InputError("snapshot_gitignore_must_ignore_local_contents") from None
        return
    try:
        _check_open_file(directory, ".gitignore", fd)
        os.write(fd, b"*\n")
        os.fsync(fd)
        _check_open_file(directory, ".gitignore", fd)
    finally:
        os.close(fd)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate snapshot field")
        result[key] = value
    return result


def _parse_record(data: bytes, snapshot_id: str) -> SnapshotRecord:
    try:
        payload = cast(
            "object",
            safe_json_loads(
                data, max_input_bytes=_MAX_RECORD_BYTES, object_pairs_hook=_unique_object
            ),
        )
        if isinstance(payload, dict):
            version = cast("dict[str, object]", payload).get("schema_version")
            if type(version) is not int:
                raise ValueError("snapshot version is required")
            if version != 1:
                raise InputError("snapshot_unsupported_version", code=ErrorCode.FEATURE_UNAVAILABLE)
            if set(cast("dict[str, object]", payload)) != set(SnapshotRecord.model_fields):
                raise ValueError("snapshot record fields are incomplete")
        record = SnapshotRecord.model_validate(payload)
        prepared = prepare_snapshot_file(
            CompareFileInput(name=record.file_name, content=record.content)
        )
        if (
            record.snapshot_id != snapshot_id
            or prepared.name != record.file_name
            or prepared.content != record.content
            or _clean_name(record.name) != record.name
        ):
            raise ValueError("invalid snapshot record")
        return record
    except (ValidationError, ValueError, RecursionError, UnicodeError):
        raise InputError("snapshot_record_corrupt", code=ErrorCode.RUN_ARTIFACT_INVALID) from None


def _usage(directory: _Directory) -> tuple[int, int]:
    count = size = 0
    for name in directory.names():
        entry = directory.entry_stat(name)
        # Unknown, stale temporary, corrupt and unsupported files consume quota.
        # Unexpected subdirectories or links fail closed instead of hiding data.
        _validate_stat(entry)
        count += name != ".gitignore"
        size += entry.st_size
    return count, size


def _publish(directory: _Directory, name: str, data: bytes) -> None:
    temp_name = f".{uuid4().hex}.tmp"
    fd = directory.open_file(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        initial = _check_open_file(directory, temp_name, fd)
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(fd)
        _check_open_file(directory, temp_name, fd)
        # Windows cannot replace an open file; retain the checked identity and
        # close the descriptor before the portable publication step.
        os.close(fd)
        fd = -1
        try:
            directory.entry_stat(name)
        except FileNotFoundError:
            pass
        else:
            raise StorageError("snapshot_id_collision")
        directory.check()
        if directory.fd is not None:
            os.replace(temp_name, name, src_dir_fd=directory.fd, dst_dir_fd=directory.fd)
        else:
            (directory.path / temp_name).replace(directory.path / name)
        current = directory.entry_stat(name)
        _validate_stat(current)
        if _identity(initial) != _identity(current):
            raise InputError("snapshot_file_changed")
        if directory.fd is not None:
            os.fsync(directory.fd)
    finally:
        if fd != -1:
            os.close(fd)
        with suppress(FileNotFoundError):
            directory.unlink(temp_name)


def save_snapshot(workspace_root: Path, *, name: str, file: CompareFileInput) -> SnapshotRecord:
    try:
        validate_snapshot_name(name)
        clean_name = _clean_name(name)
        validate_snapshot_name(clean_name)
    except (ValueError, ValidationError):
        raise InputError("snapshot_name_invalid") from None
    prepared = prepare_snapshot_file(file)
    content = prepared.content.encode("utf-8")
    record = SnapshotRecord(
        snapshot_id=f"snap_{uuid4().hex}",
        name=clean_name,
        file_name=prepared.name,
        content=prepared.content,
        content_hash=hashlib.sha256(content).hexdigest(),
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        size_bytes=len(content),
        sanitized=name != clean_name or file != prepared,
    )
    data = record.model_dump_json().encode("utf-8") + b"\n"
    with _store(workspace_root, write=True) as directory:
        count, size = _usage(directory)
        if count >= SNAPSHOT_MAX_COUNT or size + len(data) > SNAPSHOT_MAX_BYTES:
            raise InputError("snapshot_capacity_exceeded", code=ErrorCode.RUN_ARTIFACT_TOO_LARGE)
        _publish(directory, f"{record.snapshot_id}.json", data)
    return record


def list_snapshots(workspace_root: Path) -> list[SnapshotSummary]:
    summaries: list[SnapshotSummary] = []
    try:
        with _store(workspace_root) as directory:
            for name in directory.names():
                snapshot_id = name.removesuffix(".json")
                if not name.endswith(".json") or not re.fullmatch(SNAPSHOT_ID_PATTERN, snapshot_id):
                    continue
                try:
                    entry = directory.entry_stat(name)
                except FileNotFoundError:
                    continue
                raw_hash: str | None = None
                stored_bytes = entry.st_size
                try:
                    data, current = _read_file(directory, name)
                    stored_bytes = current.st_size
                    raw_hash = hashlib.sha256(data).hexdigest()
                    record = _parse_record(data, snapshot_id)
                    summary = record.to_summary(stored_bytes=stored_bytes, record_hash=raw_hash)
                except FileNotFoundError:
                    continue
                except (InputError, StorageError, OSError) as exc:
                    summary = SnapshotSummary(
                        snapshot_id=snapshot_id,
                        status="unsupported"
                        if isinstance(exc, InputError) and exc.code is ErrorCode.FEATURE_UNAVAILABLE
                        else "corrupt",
                        stored_bytes=stored_bytes,
                        record_hash=raw_hash,
                    )
                summaries.append(summary)
    except FileNotFoundError:
        return []
    return sorted(
        summaries, key=lambda item: (item.created_at or "", item.snapshot_id), reverse=True
    )


def load_snapshot(
    workspace_root: Path, snapshot_id: str, *, expected_hash: str | None = None
) -> SnapshotRecord:
    _validate_id(snapshot_id)
    if expected_hash is not None:
        _validate_hash(expected_hash)
    try:
        with _store(workspace_root) as directory:
            data, _ = _read_file(directory, f"{snapshot_id}.json")
            record = _parse_record(data, snapshot_id)
    except FileNotFoundError:
        raise InputError("snapshot_not_found", code=ErrorCode.NOT_FOUND) from None
    if expected_hash is not None and not hmac.compare_digest(record.content_hash, expected_hash):
        raise InputError("snapshot_hash_mismatch")
    return record


def delete_snapshot(workspace_root: Path, snapshot_id: str, *, expected_hash: str) -> None:
    """Delete only the checked local record; no source-file restoration occurs.

    Use record_hash from the list for corrupt or unknown-version records. A
    ready record also accepts its sanitized content_hash for CLI compatibility.
    Unsafe linked or over-sized files require separate filesystem recovery.
    """
    _validate_id(snapshot_id)
    _validate_hash(expected_hash)
    try:
        with _store(workspace_root, write=True) as directory:
            name = f"{snapshot_id}.json"
            data, expected = _read_file(directory, name)
            matches = hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected_hash)
            if not matches:
                record = _parse_record(data, snapshot_id)
                matches = hmac.compare_digest(record.content_hash, expected_hash)
            if not matches:
                raise InputError("snapshot_hash_mismatch")
            current = directory.entry_stat(name)
            _validate_stat(current)
            if _identity(current) != _identity(expected) or (
                current.st_mtime_ns,
                current.st_size,
            ) != (expected.st_mtime_ns, expected.st_size):
                raise InputError("snapshot_file_changed")
            directory.unlink(name)
            if directory.fd is not None:
                os.fsync(directory.fd)
    except FileNotFoundError:
        raise InputError("snapshot_not_found", code=ErrorCode.NOT_FOUND) from None


__all__ = [
    "delete_snapshot",
    "list_snapshots",
    "load_snapshot",
    "prepare_snapshot_file",
    "save_snapshot",
]
