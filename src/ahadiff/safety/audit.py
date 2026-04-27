from __future__ import annotations

import errno
import gzip
import json
import os
import pathlib as _pathlib
import stat
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import portalocker

from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.ids import make_event_id
from ahadiff.core.paths import (
    audit_log_path,
    ensure_state_parent_dir,
    private_audit_log_path,
    validate_state_path_no_symlinks,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from .redact import RedactionPipelineResult, SecretFinding
else:
    from . import redact as _redact_module

    Path = _pathlib.Path
    RedactionPipelineResult = _redact_module.RedactionPipelineResult
    SecretFinding = _redact_module.SecretFinding

_AUDIT_SCHEMA_VERSION = 1
_ROTATION_SNAPSHOT_SUFFIX = ".rotation-src"
_ROTATION_MAX_SOURCE_BYTES = 100_000_000
_GZIP_COPY_CHUNK_SIZE = 65_536


def audit_log_paths(repo_root: Path | None = None) -> tuple[Path, Path]:
    return audit_log_path(repo_root), private_audit_log_path(repo_root)


def build_redaction_audit_record(
    result: RedactionPipelineResult,
    *,
    privacy_mode: str,
    event_type: str = "redaction_pipeline",
) -> dict[str, Any]:
    return {
        "event_id": make_event_id(),
        "schema_version": _AUDIT_SCHEMA_VERSION,
        "event_type": event_type,
        "timestamp": _utc_now(),
        "privacy_mode": privacy_mode,
        "allowlist_digest": result.allowlist_digest,
        "blocked_remote": result.blocked_remote,
        "finding_count": len(result.findings),
        "findings": [_finding_payload(finding) for finding in result.findings],
    }


def build_provider_audit_record(
    *,
    event_id: str,
    event_type: str,
    provider_class: str,
    model_id: str,
    prompt_name: str,
    prompt_fingerprint: str,
    request_hash: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
    pricing_version: str | None,
    cost_confidence: str,
    billing_mode: str,
    execution_origin: str,
    api_principal_hash: str,
    partial_tokens: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "event_id": event_id,
        "schema_version": _AUDIT_SCHEMA_VERSION,
        "event_type": event_type,
        "timestamp": _utc_now(),
        "provider_class": provider_class,
        "model_id": model_id,
        "prompt_name": prompt_name,
        "prompt_fingerprint": prompt_fingerprint,
        "request_hash": request_hash,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "pricing_version": pricing_version,
        "cost_confidence": cost_confidence,
        "billing_mode": billing_mode,
        "execution_origin": execution_origin,
        "api_principal_hash": api_principal_hash,
    }
    if partial_tokens is not None:
        record["partial_tokens"] = partial_tokens
    if note is not None:
        record["note"] = note
    return record


def append_audit_record(
    path: Path,
    record: dict[str, Any],
    *,
    rotate_bytes: int = 10_000_000,
    max_backups: int = 3,
) -> Path:
    ensure_state_parent_dir(path)
    validate_state_path_no_symlinks(path, allow_missing_leaf=True)
    lock_path = _audit_lock_path(path)
    ensure_state_parent_dir(lock_path)
    validate_state_path_no_symlinks(lock_path, allow_missing_leaf=True)
    with _locked_audit_file(lock_path, timeout=10):
        validate_state_path_no_symlinks(path, allow_missing_leaf=True)
        _rotate_if_needed(path, rotate_bytes=rotate_bytes, max_backups=max_backups)
        _append_line_no_follow(path, json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _rotate_if_needed(path: Path, *, rotate_bytes: int, max_backups: int) -> None:
    snapshot_path = _rotation_snapshot_path(path)
    validate_state_path_no_symlinks(snapshot_path, allow_missing_leaf=True)
    if snapshot_path.exists():
        source_path = snapshot_path
    elif path.exists() and _lstat_size_no_follow(path) >= rotate_bytes:
        path.replace(snapshot_path)
        source_path = snapshot_path
    else:
        return

    for index in range(max_backups, 0, -1):
        destination = _rotated_path(path, index + 1)
        source = _rotated_path(path, index)
        validate_state_path_no_symlinks(destination, allow_missing_leaf=True)
        validate_state_path_no_symlinks(source, allow_missing_leaf=True)
        if source.exists():
            if index == max_backups:
                source.unlink()
            else:
                source.replace(destination)

    rotated_path = _rotated_path(path, 1)
    tmp_path = rotated_path.with_suffix(rotated_path.suffix + ".tmp")
    validate_state_path_no_symlinks(rotated_path, allow_missing_leaf=True)
    validate_state_path_no_symlinks(tmp_path, allow_missing_leaf=True)
    validate_state_path_no_symlinks(source_path, allow_missing_leaf=False)
    _gzip_copy_no_follow(source_path, tmp_path)
    validate_state_path_no_symlinks(tmp_path, allow_missing_leaf=False)
    validate_state_path_no_symlinks(rotated_path, allow_missing_leaf=True)
    tmp_path.replace(rotated_path)
    validate_state_path_no_symlinks(source_path, allow_missing_leaf=False)
    source_path.unlink(missing_ok=True)
    _touch_no_follow(path)


def _rotated_path(path: Path, index: int) -> Path:
    return path.with_name(f"{path.stem}.{index}{path.suffix}.gz")


def _rotation_snapshot_path(path: Path) -> Path:
    return path.with_name(f"{path.name}{_ROTATION_SNAPSHOT_SUFFIX}")


def _audit_lock_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


@contextmanager
def _locked_audit_file(lock_path: Path, *, timeout: float) -> Iterator[None]:
    fd = _open_state_file_no_follow(lock_path, os.O_CREAT | os.O_RDWR)
    handle = os.fdopen(fd, "a+", encoding="utf-8")
    locked = False
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
                locked = True
                break
            except portalocker.exceptions.LockException as exc:
                if time.monotonic() >= deadline:
                    raise StorageError("audit log lock acquisition timed out") from exc
                time.sleep(0.05)
        yield
    finally:
        try:
            if locked:
                portalocker.unlock(handle)
        finally:
            handle.close()


def _lstat_size_no_follow(path: Path) -> int:
    validate_state_path_no_symlinks(path, allow_missing_leaf=False)
    return path.lstat().st_size


def _append_line_no_follow(path: Path, line: str) -> None:
    fd = _open_state_file_no_follow(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(line)


def _touch_no_follow(path: Path) -> None:
    fd = _open_state_file_no_follow(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    os.close(fd)


def _open_state_file_no_follow(path: Path, flags: int) -> int:
    validate_state_path_no_symlinks(path, allow_missing_leaf=True)
    open_flags = flags | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), open_flags, 0o600)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError("state path must not contain symlinks") from exc
        raise StorageError(f"state path is not writable: {path}") from exc
    try:
        file_stat = os.fstat(fd)
        validate_state_path_no_symlinks(path, allow_missing_leaf=False)
        path_stat = path.lstat()
        if not stat.S_ISREG(file_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise InputError("state path must be a regular file")
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError("state path changed during write")
    except Exception:
        os.close(fd)
        raise
    return fd


def _gzip_copy_no_follow(source_path: Path, tmp_path: Path) -> None:
    source_fd = -1
    tmp_fd = -1
    try:
        source_fd = _open_state_file_no_follow(source_path, os.O_RDONLY)
        source_stat = os.fstat(source_fd)
        if source_stat.st_size > _ROTATION_MAX_SOURCE_BYTES:
            os.close(source_fd)
            source_fd = -1
            raise StorageError(
                f"audit log rotation source exceeds {_ROTATION_MAX_SOURCE_BYTES} bytes"
            )
        tmp_fd = _open_state_file_no_follow(tmp_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
        with os.fdopen(source_fd, "rb") as source_handle:
            source_fd = -1
            with os.fdopen(tmp_fd, "wb") as tmp_handle:
                tmp_fd = -1
                with gzip.GzipFile(fileobj=tmp_handle, mode="wb") as gzip_handle:
                    total_read = 0
                    while True:
                        chunk = source_handle.read(_GZIP_COPY_CHUNK_SIZE)
                        if not chunk:
                            break
                        total_read += len(chunk)
                        if total_read > _ROTATION_MAX_SOURCE_BYTES:
                            raise StorageError(
                                f"audit log rotation source exceeds "
                                f"{_ROTATION_MAX_SOURCE_BYTES} bytes"
                            )
                        gzip_handle.write(chunk)
    finally:
        if source_fd != -1:
            os.close(source_fd)
        if tmp_fd != -1:
            os.close(tmp_fd)


def _finding_payload(finding: SecretFinding) -> dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "secret_type": finding.secret_type,
        "severity": finding.severity,
        "source_name": finding.source_name,
        "source_kind": finding.source_kind,
        "path": finding.path,
        "line": finding.line,
        "column": finding.column,
        "action": finding.action,
        "blocked_remote": finding.blocked_remote,
        "allowlisted": finding.allowlisted,
        "value_hash": finding.value_hash,
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "append_audit_record",
    "audit_log_paths",
    "build_provider_audit_record",
    "build_redaction_audit_record",
]
