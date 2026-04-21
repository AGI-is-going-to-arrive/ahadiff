from __future__ import annotations

import gzip
import json
import pathlib as _pathlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ahadiff.core.paths import audit_log_path, private_audit_log_path

if TYPE_CHECKING:
    from pathlib import Path

    from .redact import RedactionPipelineResult, SecretFinding
else:
    from . import redact as _redact_module

    Path = _pathlib.Path
    RedactionPipelineResult = _redact_module.RedactionPipelineResult
    SecretFinding = _redact_module.SecretFinding

_AUDIT_SCHEMA_VERSION = 1
_ROTATION_SNAPSHOT_SUFFIX = ".rotation-src"


def audit_log_paths(repo_root: Path | None = None) -> tuple[Path, Path]:
    return audit_log_path(repo_root), private_audit_log_path(repo_root)


def build_redaction_audit_record(
    result: RedactionPipelineResult,
    *,
    privacy_mode: str,
    event_type: str = "redaction_pipeline",
) -> dict[str, Any]:
    return {
        "schema_version": _AUDIT_SCHEMA_VERSION,
        "event_type": event_type,
        "timestamp": _utc_now(),
        "privacy_mode": privacy_mode,
        "allowlist_digest": result.allowlist_digest,
        "blocked_remote": result.blocked_remote,
        "finding_count": len(result.findings),
        "findings": [_finding_payload(finding) for finding in result.findings],
    }


def append_audit_record(
    path: Path,
    record: dict[str, Any],
    *,
    rotate_bytes: int = 10_000_000,
    max_backups: int = 3,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(path, rotate_bytes=rotate_bytes, max_backups=max_backups)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _rotate_if_needed(path: Path, *, rotate_bytes: int, max_backups: int) -> None:
    snapshot_path = _rotation_snapshot_path(path)
    if snapshot_path.exists():
        source_path = snapshot_path
    elif path.exists() and path.stat().st_size >= rotate_bytes:
        path.replace(snapshot_path)
        source_path = snapshot_path
    else:
        return

    for index in range(max_backups, 0, -1):
        destination = _rotated_path(path, index + 1)
        source = _rotated_path(path, index)
        if source.exists():
            if index == max_backups:
                source.unlink()
            else:
                source.replace(destination)

    rotated_path = _rotated_path(path, 1)
    tmp_path = rotated_path.with_suffix(rotated_path.suffix + ".tmp")
    with source_path.open("rb") as source_handle, gzip.open(tmp_path, "wb") as gzip_handle:
        gzip_handle.write(source_handle.read())
    tmp_path.replace(rotated_path)
    source_path.unlink(missing_ok=True)
    path.touch()


def _rotated_path(path: Path, index: int) -> Path:
    return path.with_name(f"{path.stem}.{index}{path.suffix}.gz")


def _rotation_snapshot_path(path: Path) -> Path:
    return path.with_name(f"{path.name}{_ROTATION_SNAPSHOT_SUFFIX}")


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


__all__ = ["append_audit_record", "audit_log_paths", "build_redaction_audit_record"]
