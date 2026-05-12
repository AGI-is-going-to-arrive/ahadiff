"""Compare the learner diff against the canonical diff and return gap claims.

The challenge engine never executes code (challenge runs are strictly diff
review, not code execution). We compute a deterministic gap set by:

1. Parsing the canonical and learner patches into file + hunk envelopes.
2. Diffing the file paths and per-file hunk ranges.
3. Mapping each missing / divergent hunk back to the canonical claim ids
   whose source hunks intersect it.

Returned ``gap_claim_ids`` are downstream-consumable by
:func:`ahadiff.challenge.adapt.adapt_from_gaps`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from ahadiff.core.errors import InputError

if TYPE_CHECKING:
    from .manifest import ChallengeManifest

_OLD_FILE_HEADER_RE = re.compile(r"^---\s+(?:a/)?(.+?)(?:\t.*)?$")
_NEW_FILE_HEADER_RE = re.compile(r"^\+\+\+\s+(?:b/)?(.+?)(?:\t.*)?$")
_HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+"
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@",
)
_LEARNER_DIFF_MAX_BYTES = 5_000_000


@dataclass(frozen=True)
class _FileHunk:
    new_start: int
    new_count: int
    old_start: int
    old_count: int
    added_lines: tuple[str, ...] = ()
    removed_lines: tuple[str, ...] = ()

    def covers(self, line: int) -> bool:
        if self.new_count <= 0:
            return False
        return self.new_start <= line < self.new_start + self.new_count


@dataclass
class _FilePatch:
    path: str
    hunks: list[_FileHunk] = field(default_factory=list[_FileHunk])


def review_attempt(
    *,
    manifest: ChallengeManifest,
    learner_diff: str,
) -> dict[str, Any]:
    """Compare ``learner_diff`` against the canonical manifest patch.

    Returns a feedback envelope with:
      - ``gap_claim_ids``: canonical claim ids whose hunks the learner missed
      - ``missing_files`` / ``extra_files``: file-level deltas
      - ``hunk_coverage``: per-file matched vs missing hunk counts
    """

    if len(learner_diff.encode("utf-8")) > _LEARNER_DIFF_MAX_BYTES:
        raise InputError(
            f"learner_diff exceeds {_LEARNER_DIFF_MAX_BYTES} bytes; "
            "shrink the change before submitting"
        )

    canonical_files = _parse_patch(manifest.canonical_patch)
    learner_files = _parse_patch(learner_diff)

    canonical_paths = {item.path for item in canonical_files}
    learner_paths = {item.path for item in learner_files}
    missing_files = sorted(canonical_paths - learner_paths)
    extra_files = sorted(learner_paths - canonical_paths)

    canonical_by_path = {item.path: item for item in canonical_files}
    learner_by_path = {item.path: item for item in learner_files}

    missing_hunks: list[tuple[str, _FileHunk]] = []
    matched_hunks: dict[str, int] = {}
    hunk_coverage: list[dict[str, Any]] = []

    for path in sorted(canonical_paths):
        canonical_patch = canonical_by_path[path]
        learner_patch = learner_by_path.get(path)
        learner_hunks = learner_patch.hunks if learner_patch is not None else []
        matched = 0
        for canonical_hunk in canonical_patch.hunks:
            if _has_overlapping_hunk(canonical_hunk, learner_hunks):
                matched += 1
            else:
                missing_hunks.append((path, canonical_hunk))
        matched_hunks[path] = matched
        hunk_coverage.append(
            {
                "path": path,
                "canonical_hunks": len(canonical_patch.hunks),
                "matched_hunks": matched,
                "missing_hunks": len(canonical_patch.hunks) - matched,
            }
        )

    gap_claim_ids = _resolve_gap_claim_ids(manifest, missing_files, missing_hunks)

    return {
        "challenge_id": manifest.challenge_id,
        "source_run_id": manifest.source_run_id,
        "missing_files": missing_files,
        "extra_files": extra_files,
        "hunk_coverage": hunk_coverage,
        "gap_claim_ids": gap_claim_ids,
        "all_canonical_claim_ids": list(manifest.canonical_claim_ids),
    }


def _resolve_gap_claim_ids(
    manifest: ChallengeManifest,
    missing_files: list[str],
    missing_hunks: list[tuple[str, _FileHunk]],
) -> list[str]:
    """Map missing files / hunks to manifest claim ids using ``hunks`` metadata."""

    gap: set[str] = set()
    canonical_ids = set(manifest.canonical_claim_ids)
    attributed_canonical_ids: set[str] = set()
    missing_file_set = set(missing_files)
    attributed_missing_files: set[str] = set()
    attributed_missing_hunk_indexes: set[int] = set()

    for entry in manifest.hunks:
        path = _optional_str(entry.get("file") or entry.get("path"))
        if path is None:
            continue
        attributed_ids = [
            claim_id for claim_id in _claim_ids_for_hunk_entry(entry) if claim_id in canonical_ids
        ]
        attributed_canonical_ids.update(attributed_ids)
        if path in missing_file_set:
            for claim_id in attributed_ids:
                gap.add(claim_id)
            if attributed_ids:
                attributed_missing_files.add(path)
            continue
        new_start = _coerce_int(entry.get("new_start") or entry.get("start"))
        new_count = _coerce_int(entry.get("new_count") or entry.get("count"))
        if new_start is None:
            continue
        canonical_hunk = _FileHunk(
            new_start=new_start,
            new_count=new_count or 0,
            old_start=_coerce_int(entry.get("old_start")) or 0,
            old_count=_coerce_int(entry.get("old_count")) or 0,
        )
        for missing_index, (missing_path, missing_hunk) in enumerate(missing_hunks):
            if missing_path != path or not _ranges_overlap(missing_hunk, canonical_hunk):
                continue
            for claim_id in attributed_ids:
                gap.add(claim_id)
            if attributed_ids:
                attributed_missing_hunk_indexes.add(missing_index)

    # Fallback is per missing item, not global. Mixed manifests can attribute
    # one hunk while leaving another un-attributed; those un-attributed misses
    # still need to drive canonical review signals.
    missing_hunk_indexes = set(range(len(missing_hunks)))
    if (missing_file_set - attributed_missing_files) or (
        missing_hunk_indexes - attributed_missing_hunk_indexes
    ):
        fallback_ids = canonical_ids - attributed_canonical_ids
        gap.update(fallback_ids or canonical_ids)

    return sorted(gap)


def _claim_ids_for_hunk_entry(entry: dict[str, Any]) -> list[str]:
    raw: Any = entry.get("claim_ids") or entry.get("canonical_claim_ids")
    if not isinstance(raw, list):
        return []
    items = cast("list[Any]", raw)
    return [item for item in items if isinstance(item, str) and item]


def _ranges_overlap(left: _FileHunk, right: _FileHunk) -> bool:
    left_end = left.new_start + max(left.new_count, 1) - 1
    right_end = right.new_start + max(right.new_count, 1) - 1
    return not (left_end < right.new_start or right_end < left.new_start)


def _has_overlapping_hunk(canonical: _FileHunk, learner_hunks: list[_FileHunk]) -> bool:
    # A canonical hunk only counts as matched when the learner hunk overlaps the
    # same range and covers every substantive canonical edit line. Accepting a
    # single shared added line made partial challenge answers look complete.
    canonical_added = _strip_blank({line.strip() for line in canonical.added_lines})
    canonical_removed = _strip_blank({line.strip() for line in canonical.removed_lines})
    for learner_hunk in learner_hunks:
        if not _ranges_overlap(canonical, learner_hunk):
            continue
        if not canonical_added and not canonical_removed:
            return True
        learner_added = _strip_blank({line.strip() for line in learner_hunk.added_lines})
        if canonical_added and not canonical_added <= learner_added:
            continue
        learner_removed = _strip_blank({line.strip() for line in learner_hunk.removed_lines})
        if canonical_removed and not canonical_removed <= learner_removed:
            continue
        if canonical_added or canonical_removed:
            return True
    return False


def _strip_blank(values: set[str]) -> set[str]:
    return {value for value in values if value}


def _parse_patch(patch_text: str) -> list[_FilePatch]:
    if not patch_text:
        return []
    files: list[_FilePatch] = []
    current: _FilePatch | None = None
    pending_old_path: str | None = None
    pending_added: list[str] = []
    pending_removed: list[str] = []
    pending_header: re.Match[str] | None = None

    def _flush_pending() -> None:
        nonlocal pending_header, pending_added, pending_removed
        if pending_header is None or current is None:
            pending_header = None
            pending_added = []
            pending_removed = []
            return
        current.hunks.append(
            _FileHunk(
                new_start=int(pending_header.group("new_start")),
                new_count=int(pending_header.group("new_count") or 1),
                old_start=int(pending_header.group("old_start")),
                old_count=int(pending_header.group("old_count") or 1),
                added_lines=tuple(pending_added),
                removed_lines=tuple(pending_removed),
            )
        )
        pending_header = None
        pending_added = []
        pending_removed = []

    for raw_line in patch_text.splitlines():
        if raw_line.startswith("--- "):
            _flush_pending()
            match = _OLD_FILE_HEADER_RE.match(raw_line)
            if match is None:
                pending_old_path = None
                continue
            path = match.group(1).strip()
            pending_old_path = None if path == "/dev/null" else path
            continue
        if raw_line.startswith("+++ "):
            _flush_pending()
            match = _NEW_FILE_HEADER_RE.match(raw_line)
            if match is None:
                current = None
                pending_old_path = None
                continue
            path = match.group(1).strip()
            if path == "/dev/null":
                path = pending_old_path or ""
                if not path:
                    current = None
                    pending_old_path = None
                    continue
            pending_old_path = None
            current = _FilePatch(path=path)
            files.append(current)
            continue
        if raw_line.startswith("@@") and current is not None:
            _flush_pending()
            match = _HUNK_HEADER_RE.match(raw_line)
            if match is None:
                continue
            pending_header = match
            continue
        if pending_header is None or current is None:
            continue
        # Collect body content for the active hunk. Skip "+++"/"---" file
        # headers (already routed above) and the "\ No newline at end of file"
        # marker, which is metadata, not content.
        if raw_line.startswith("\\"):
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            pending_added.append(raw_line[1:])
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            pending_removed.append(raw_line[1:])

    _flush_pending()
    return files


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


__all__ = ["review_attempt"]
