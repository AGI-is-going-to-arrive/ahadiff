from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ahadiff.core.errors import InputError
from ahadiff.core.ids import make_hunk_id

from .hunk_hash import compute_hunk_hash
from .path_tokens import normalize_diff_path_token, parse_diff_git_header_paths

DiffChangeKind = Literal["modified", "added", "deleted", "renamed", "binary"]
DiffLineKind = Literal["context", "add", "delete"]
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[ ]?(.*)$")


@dataclass(frozen=True)
class DiffLineRecord:
    kind: DiffLineKind
    content: str
    old_line: int | None
    new_line: int | None


@dataclass(frozen=True)
class HunkRecord:
    path: str
    change_kind: DiffChangeKind
    header: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    section_header: str | None
    hunk_id: str
    hunk_hash: str
    raw_lines: tuple[str, ...]
    lines: tuple[DiffLineRecord, ...]

    @property
    def old_end(self) -> int:
        if self.old_count == 0:
            return self.old_start - 1
        return self.old_start + self.old_count - 1

    @property
    def new_end(self) -> int:
        if self.new_count == 0:
            return self.new_start - 1
        return self.new_start + self.new_count - 1

    @property
    def added_lines(self) -> tuple[int, ...]:
        return tuple(
            line.new_line for line in self.lines if line.kind == "add" and line.new_line is not None
        )

    @property
    def deleted_lines(self) -> tuple[int, ...]:
        return tuple(
            line.old_line
            for line in self.lines
            if line.kind == "delete" and line.old_line is not None
        )

    @property
    def context_old_lines(self) -> tuple[int, ...]:
        return tuple(
            line.old_line
            for line in self.lines
            if line.kind == "context" and line.old_line is not None
        )

    @property
    def context_new_lines(self) -> tuple[int, ...]:
        return tuple(
            line.new_line
            for line in self.lines
            if line.kind == "context" and line.new_line is not None
        )


@dataclass(frozen=True)
class ChangedFileRecord:
    old_path: str | None
    new_path: str | None
    display_path: str
    change_kind: DiffChangeKind
    is_binary: bool
    headers: tuple[str, ...]
    hunks: tuple[HunkRecord, ...]

    @property
    def path(self) -> str:
        return self.display_path


def parse_unified_diff(patch_text: str) -> tuple[ChangedFileRecord, ...]:
    lines = patch_text.splitlines()
    segments = _split_segments(lines)
    return tuple(_parse_segment(segment) for segment in segments)


def iter_changed_files(patch_text: str) -> tuple[ChangedFileRecord, ...]:
    return parse_unified_diff(patch_text)


def iter_hunks(patch_text: str) -> tuple[HunkRecord, ...]:
    return tuple(
        hunk for changed_file in parse_unified_diff(patch_text) for hunk in changed_file.hunks
    )


def _split_segments(lines: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    current_has_diff_header = False

    for index, line in enumerate(lines):
        plain_start = (
            line.startswith("--- ")
            and index + 1 < len(lines)
            and lines[index + 1].startswith("+++ ")
        )
        if line.startswith("diff --git ") or (plain_start and not current_has_diff_header):
            if current:
                segments.append(current)
            current = [line]
            current_has_diff_header = line.startswith("diff --git ")
            continue
        if not current:
            continue
        current.append(line)

    if current:
        segments.append(current)
    return segments


def _parse_segment(lines: list[str]) -> ChangedFileRecord:
    old_path: str | None = None
    new_path: str | None = None
    change_kind: DiffChangeKind = "modified"
    is_binary = False
    headers: list[str] = []

    for line in lines:
        if line.startswith("@@ "):
            break
        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            is_binary = True
            if change_kind == "modified":
                change_kind = "binary"
            break
        headers.append(line)
        if line.startswith("diff --git "):
            parsed_paths = parse_diff_git_header_paths(line)
            if parsed_paths is not None:
                old_path, new_path = parsed_paths
        elif line.startswith("--- "):
            old_path = _normalize_diff_path(line.removeprefix("--- ").strip(), prefix="a/")
        elif line.startswith("+++ "):
            new_path = _normalize_diff_path(line.removeprefix("+++ ").strip(), prefix="b/")
        elif line.startswith("rename from "):
            old_path = _normalize_diff_path(line.removeprefix("rename from ").strip())
            change_kind = "renamed"
        elif line.startswith("rename to "):
            new_path = _normalize_diff_path(line.removeprefix("rename to ").strip())
            change_kind = "renamed"
        elif line.startswith("new file mode "):
            change_kind = "added"
        elif line.startswith("deleted file mode "):
            change_kind = "deleted"

    display_path = new_path or old_path or "__unknown__"
    hunks = _parse_hunks(display_path, change_kind, lines)
    return ChangedFileRecord(
        old_path=old_path,
        new_path=new_path,
        display_path=display_path,
        change_kind=change_kind,
        is_binary=is_binary,
        headers=tuple(headers),
        hunks=tuple(hunks),
    )


def _parse_hunks(path: str, change_kind: DiffChangeKind, lines: list[str]) -> list[HunkRecord]:
    hunks: list[HunkRecord] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("@@ "):
            index += 1
            continue
        header = line
        body: list[str] = []
        index += 1
        while (
            index < len(lines)
            and not lines[index].startswith("@@ ")
            and not lines[index].startswith("diff --git ")
        ):
            body.append(lines[index])
            index += 1
        hunks.append(_build_hunk(path, change_kind, header, body))
    return hunks


def _normalize_diff_path(candidate: str, *, prefix: str = "") -> str | None:
    return normalize_diff_path_token(candidate, prefix=prefix)


def _build_hunk(
    path: str,
    change_kind: DiffChangeKind,
    header: str,
    body_lines: list[str],
) -> HunkRecord:
    match = _HUNK_HEADER_RE.match(header)
    if match is None:
        raise InputError(f"invalid unified diff hunk header: {header}")
    old_start = int(match.group(1))
    old_count = int(match.group(2) or "1")
    new_start = int(match.group(3))
    new_count = int(match.group(4) or "1")
    section_header = match.group(5).strip() or None

    old_cursor = old_start
    new_cursor = new_start
    consumed_old = 0
    consumed_new = 0
    parsed_lines: list[DiffLineRecord] = []

    for index, raw_line in enumerate(body_lines):
        if raw_line.startswith("\\ "):
            continue
        if raw_line == "[truncated]":
            continue
        prefix = raw_line[:1]
        content = raw_line[1:] if prefix in {" ", "+", "-"} else raw_line
        if prefix not in {" ", "+", "-"}:
            prefix = _infer_prefix(
                remaining_lines=body_lines[index + 1 :],
                old_remaining=old_count - consumed_old,
                new_remaining=new_count - consumed_new,
            )
        if prefix == " ":
            parsed_lines.append(DiffLineRecord("context", content, old_cursor, new_cursor))
            old_cursor += 1
            new_cursor += 1
            consumed_old += 1
            consumed_new += 1
        elif prefix == "-":
            parsed_lines.append(DiffLineRecord("delete", content, old_cursor, None))
            old_cursor += 1
            consumed_old += 1
        else:
            parsed_lines.append(DiffLineRecord("add", content, None, new_cursor))
            new_cursor += 1
            consumed_new += 1

    return HunkRecord(
        path=path,
        change_kind=change_kind,
        header=header,
        old_start=old_start,
        old_count=old_count,
        new_start=new_start,
        new_count=new_count,
        section_header=section_header,
        hunk_id=make_hunk_id(path, old_start, new_start, section_header),
        hunk_hash=compute_hunk_hash(header=header, body_lines=body_lines),
        raw_lines=tuple(body_lines),
        lines=tuple(parsed_lines),
    )


def _infer_prefix(
    *,
    remaining_lines: list[str],
    old_remaining: int,
    new_remaining: int,
) -> Literal[" ", "+", "-"]:
    future_old = 0
    future_new = 0
    for line in remaining_lines:
        if line.startswith("\\ "):
            continue
        if line.startswith(" "):
            future_old += 1
            future_new += 1
        elif line.startswith("-"):
            future_old += 1
        elif line.startswith("+"):
            future_new += 1

    delta_old = old_remaining - future_old
    delta_new = new_remaining - future_new
    if delta_old > 0 and delta_new <= 0:
        return "-"
    if delta_new > 0 and delta_old <= 0:
        return "+"
    return " "


__all__ = [
    "ChangedFileRecord",
    "DiffChangeKind",
    "DiffLineKind",
    "DiffLineRecord",
    "HunkRecord",
    "iter_changed_files",
    "iter_hunks",
    "parse_unified_diff",
]
