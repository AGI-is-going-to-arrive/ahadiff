from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[ ]?(.*)$")


def normalize_hunk_for_hash(*, header: str, body_lines: Iterable[str]) -> tuple[str, ...]:
    match = _HUNK_HEADER_RE.match(header.strip())
    section_header = match.group(5).strip() if match is not None else ""
    normalized: list[str] = []
    if section_header:
        normalized.append(f"section:{section_header}")

    for raw_line in body_lines:
        if raw_line.startswith("\\ ") or raw_line == "[truncated]":
            continue
        normalized.append(raw_line.rstrip("\r\n"))
    return tuple(normalized)


def compute_hunk_hash(*, header: str, body_lines: Iterable[str], size: int = 12) -> str:
    normalized = normalize_hunk_for_hash(header=header, body_lines=body_lines)
    payload = "\n".join(normalized).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:size]


__all__ = ["compute_hunk_hash", "normalize_hunk_for_hash"]
