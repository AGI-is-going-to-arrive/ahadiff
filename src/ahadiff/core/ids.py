from __future__ import annotations

import hashlib
import time
import uuid


def _digest(*parts: object, size: int = 12) -> str:
    payload = "::".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:size]


def make_run_id() -> str:
    """Create a sortable run identifier for Python 3.11+ runtimes."""

    timestamp_ms = int(time.time() * 1000)
    suffix = uuid.uuid4().hex[:20]
    return f"run_{timestamp_ms:012x}{suffix}"


def make_event_id() -> str:
    """Create a sortable event identifier for audit and event streams."""

    timestamp_ms = int(time.time() * 1000)
    suffix = uuid.uuid4().hex[:20]
    return f"evt_{timestamp_ms:012x}{suffix}"


def make_claim_id(run_id: str, ordinal: int) -> str:
    """Create a deterministic claim identifier within a run."""

    return f"claim_{_digest(run_id, ordinal)}"


def make_hunk_id(
    repo_relative_path: str,
    old_start: int,
    new_start: int,
    section_header: str | None = None,
) -> str:
    """Create a deterministic hunk identifier from diff coordinates."""

    return f"hunk_{_digest(repo_relative_path, old_start, new_start, section_header or '')}"


__all__ = ["make_claim_id", "make_event_id", "make_hunk_id", "make_run_id"]
