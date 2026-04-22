from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ahadiff.core.errors import InputError
from ahadiff.core.paths import path_identity_key

from .parser import ChangedFileRecord, DiffChangeKind, HunkRecord, parse_unified_diff

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any

LINE_MAP_SCHEMA = "ahadiff.line_map"
LINE_MAP_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HunkLineMap:
    file_id: str
    display_path: str
    hunk_id: str
    hunk_hash: str
    change_kind: DiffChangeKind
    old_start: int
    old_end: int
    new_start: int
    new_end: int
    section_header: str | None
    added_lines: tuple[int, ...]
    deleted_lines: tuple[int, ...]
    context_old_lines: tuple[int, ...]
    context_new_lines: tuple[int, ...]


@dataclass(frozen=True)
class FileLineMap:
    file_id: str
    display_path: str
    path_identity_key: str
    old_path: str | None
    new_path: str | None
    change_kind: DiffChangeKind
    hunks: tuple[HunkLineMap, ...]


def build_line_map(
    changed_files: str | Iterable[ChangedFileRecord],
) -> tuple[FileLineMap, ...]:
    records = (
        parse_unified_diff(changed_files)
        if isinstance(changed_files, str)
        else tuple(changed_files)
    )
    file_ids = build_file_id_index(record.display_path for record in records)
    return tuple(_build_file_line_map(record, file_ids[record.display_path]) for record in records)


def build_file_id_index(paths: Iterable[str]) -> dict[str, str]:
    identities: dict[str, str] = {}
    result: dict[str, str] = {}
    for display_path in paths:
        identity = path_identity_key(Path(display_path))
        previous = identities.get(identity)
        if previous is not None and previous != display_path:
            raise InputError("case-insensitive path collision")
        identities[identity] = display_path
        result[display_path] = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return result


def _build_file_line_map(changed_file: ChangedFileRecord, file_id: str) -> FileLineMap:
    return FileLineMap(
        file_id=file_id,
        display_path=changed_file.display_path,
        path_identity_key=path_identity_key(Path(changed_file.display_path)),
        old_path=changed_file.old_path,
        new_path=changed_file.new_path,
        change_kind=changed_file.change_kind,
        hunks=tuple(
            _build_hunk_line_map(file_id, changed_file.display_path, hunk)
            for hunk in changed_file.hunks
        ),
    )


def _build_hunk_line_map(file_id: str, display_path: str, hunk: HunkRecord) -> HunkLineMap:
    return HunkLineMap(
        file_id=file_id,
        display_path=display_path,
        hunk_id=hunk.hunk_id,
        hunk_hash=hunk.hunk_hash,
        change_kind=hunk.change_kind,
        old_start=hunk.old_start,
        old_end=hunk.old_end,
        new_start=hunk.new_start,
        new_end=hunk.new_end,
        section_header=hunk.section_header,
        added_lines=hunk.added_lines,
        deleted_lines=hunk.deleted_lines,
        context_old_lines=hunk.context_old_lines,
        context_new_lines=hunk.context_new_lines,
    )


def serialize_line_map_payload(items: Iterable[FileLineMap]) -> dict[str, Any]:
    return {
        "artifact": "line_map",
        "schema": LINE_MAP_SCHEMA,
        "schema_version": LINE_MAP_SCHEMA_VERSION,
        "files": [serialize_file_line_map(item) for item in items],
    }


def serialize_file_line_map(item: FileLineMap) -> dict[str, Any]:
    return {
        "change_kind": item.change_kind,
        "display_path": item.display_path,
        "file_id": item.file_id,
        "hunks": [serialize_hunk_line_map(hunk) for hunk in item.hunks],
        "new_path": item.new_path,
        "old_path": item.old_path,
        "path_identity_key": item.path_identity_key,
    }


def serialize_hunk_line_map(item: HunkLineMap) -> dict[str, Any]:
    return {
        "added_lines": list(item.added_lines),
        "change_kind": item.change_kind,
        "context_new_lines": list(item.context_new_lines),
        "context_old_lines": list(item.context_old_lines),
        "deleted_lines": list(item.deleted_lines),
        "display_path": item.display_path,
        "file_id": item.file_id,
        "hunk_hash": item.hunk_hash,
        "hunk_id": item.hunk_id,
        "new_end": item.new_end,
        "new_start": item.new_start,
        "old_end": item.old_end,
        "old_start": item.old_start,
        "section_header": item.section_header,
    }


__all__ = [
    "FileLineMap",
    "HunkLineMap",
    "LINE_MAP_SCHEMA",
    "LINE_MAP_SCHEMA_VERSION",
    "build_file_id_index",
    "build_line_map",
    "serialize_line_map_payload",
]
