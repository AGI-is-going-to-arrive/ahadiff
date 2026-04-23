from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ahadiff.contracts import ClaimRecord, RejectReasonCode, SourceHunk, SourceHunkSide
from ahadiff.core.paths import path_identity_key

from .classify import classify_claim_status, resolve_claim_confidence
from .negative_scan import scan_negative_evidence
from .schema import ClaimCandidate, VerifiedClaim

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ahadiff.contracts import ClaimExtractor
    from ahadiff.git.line_map import FileLineMap, HunkLineMap
    from ahadiff.git.symbols import SymbolRecord


_MAX_SOURCE_HUNK_SPAN = 10_000


@dataclass(frozen=True)
class _MatchedContext:
    source_hunks: tuple[SourceHunk, ...]
    matched_hunks: tuple[HunkLineMap, ...]


@dataclass(frozen=True)
class _MatchFailure:
    reason_code: RejectReasonCode
    source_hunks: tuple[SourceHunk, ...]


def verify_claim_candidate(
    candidate: ClaimCandidate,
    *,
    line_maps: Iterable[FileLineMap],
    symbols: Iterable[SymbolRecord],
    before_text_by_path: Mapping[str, str] | None = None,
    after_text_by_path: Mapping[str, str] | None = None,
) -> VerifiedClaim:
    file_lookup = _build_file_lookup(line_maps)
    before_lookup = _build_text_lookup(before_text_by_path or {})
    after_lookup = _build_text_lookup(after_text_by_path or {})
    matched = _match_source_hunks(
        candidate.source_hunks,
        file_lookup=file_lookup,
        before_text_lookup=before_lookup,
        after_text_lookup=after_lookup,
    )
    if isinstance(matched, _MatchFailure):
        return VerifiedClaim(
            record=ClaimRecord(
                claim_id=candidate.claim_id,
                run_id=candidate.run_id,
                text=candidate.text,
                status="rejected",
                reason_code=matched.reason_code,
                confidence="low",
                source_hunks=list(matched.source_hunks),
                symbols=list(candidate.symbols),
                extractor=_resolve_claim_extractor(candidate),
            )
        )

    matched_hunk_ids = tuple(dict.fromkeys(hunk.hunk_id for hunk in matched.matched_hunks))
    if candidate.hunk_ids and any(
        hunk_id not in matched_hunk_ids for hunk_id in candidate.hunk_ids
    ):
        return VerifiedClaim(
            record=ClaimRecord(
                claim_id=candidate.claim_id,
                run_id=candidate.run_id,
                text=candidate.text,
                status="rejected",
                reason_code="hunk_id_mismatch",
                confidence="low",
                source_hunks=list(matched.source_hunks),
                symbols=list(candidate.symbols),
                extractor=_resolve_claim_extractor(candidate),
            ),
            matched_hunk_ids=list(matched_hunk_ids),
        )

    symbol_matches, unmatched_symbols = _match_symbols(
        candidate.symbols,
        source_hunks=matched.source_hunks,
        matched_hunks=matched.matched_hunks,
        symbols=symbols,
    )
    negative_evidence = scan_negative_evidence(
        candidate.text,
        source_hunks=matched.source_hunks,
        matched_symbols=symbol_matches,
        before_text_by_path=before_text_by_path or {},
        after_text_by_path=after_text_by_path or {},
    )
    status = classify_claim_status(
        unmatched_symbols=unmatched_symbols,
        negative_evidence=negative_evidence,
        matched_symbols=symbol_matches,
    )
    confidence = resolve_claim_confidence(
        status=status,
        matched_symbols=symbol_matches,
    )
    return VerifiedClaim(
        record=ClaimRecord(
            claim_id=candidate.claim_id,
            run_id=candidate.run_id,
            text=candidate.text,
            status=status,
            confidence=confidence,
            source_hunks=list(matched.source_hunks),
            symbols=list(candidate.symbols),
            negative_evidence=[item.render() for item in negative_evidence],
            extractor=_resolve_claim_extractor(candidate, symbol_matches=symbol_matches),
        ),
        matched_hunk_ids=list(matched_hunk_ids),
        matched_symbols=[item.qualified_name for item in symbol_matches],
        negative_evidence=list(negative_evidence),
    )


def verify_claim_candidates(
    candidates: Iterable[ClaimCandidate],
    *,
    line_maps: Iterable[FileLineMap],
    symbols: Iterable[SymbolRecord],
    before_text_by_path: Mapping[str, str] | None = None,
    after_text_by_path: Mapping[str, str] | None = None,
) -> tuple[VerifiedClaim, ...]:
    line_map_items = tuple(line_maps)
    symbol_items = tuple(symbols)
    before_lookup = before_text_by_path or {}
    after_lookup = after_text_by_path or {}
    return tuple(
        verify_claim_candidate(
            candidate,
            line_maps=line_map_items,
            symbols=symbol_items,
            before_text_by_path=before_lookup,
            after_text_by_path=after_lookup,
        )
        for candidate in candidates
    )


def _match_source_hunks(
    source_hunks: Sequence[SourceHunk],
    *,
    file_lookup: Mapping[str, tuple[FileLineMap, ...]],
    before_text_lookup: Mapping[str, str],
    after_text_lookup: Mapping[str, str],
) -> _MatchedContext | _MatchFailure:
    matched_hunks: list[HunkLineMap] = []
    normalized_hunks: list[SourceHunk] = []
    for source_hunk in source_hunks:
        file_candidates = file_lookup.get(_identity(source_hunk.file))
        if file_candidates is None:
            return _MatchFailure(
                reason_code="file_not_in_patch",
                source_hunks=(source_hunk,),
            )
        if len(file_candidates) != 1:
            return _MatchFailure(
                reason_code="evidence_missing",
                source_hunks=(source_hunk,),
            )
        file_map = file_candidates[0]
        normalized_file = _resolve_source_hunk_file(file_map, source_hunk.file)
        if source_hunk.end - source_hunk.start + 1 > _MAX_SOURCE_HUNK_SPAN:
            return _MatchFailure(
                reason_code="evidence_missing",
                source_hunks=(
                    SourceHunk(
                        file=normalized_file,
                        start=source_hunk.start,
                        end=source_hunk.end,
                        side=source_hunk.side,
                    ),
                ),
            )
        requested_sides = _requested_source_hunk_sides(source_hunk, file_map=file_map)
        if not file_map.hunks:
            resolved_side = None
            if file_map.change_kind == "renamed":
                resolved_side = _resolve_text_only_source_hunk_side(
                    source_hunk,
                    requested_sides=requested_sides,
                    file_map=file_map,
                    before_text_lookup=before_text_lookup,
                    after_text_lookup=after_text_lookup,
                )
            if resolved_side is not None:
                normalized_hunks.append(
                    SourceHunk(
                        file=normalized_file,
                        start=source_hunk.start,
                        end=source_hunk.end,
                        side=resolved_side,
                    )
                )
                continue
            if file_map.change_kind == "renamed" and _source_hunk_is_within_file_text(
                source_hunk,
                file_map=file_map,
                before_text_lookup=before_text_lookup,
                after_text_lookup=after_text_lookup,
            ):
                return _MatchFailure(
                    reason_code="evidence_missing",
                    source_hunks=(
                        SourceHunk(
                            file=normalized_file,
                            start=source_hunk.start,
                            end=source_hunk.end,
                            side=source_hunk.side,
                        ),
                    ),
                )
            return _MatchFailure(
                reason_code="line_outside_hunk",
                source_hunks=(
                    SourceHunk(
                        file=normalized_file,
                        start=source_hunk.start,
                        end=source_hunk.end,
                        side=source_hunk.side,
                    ),
                ),
            )
        matched_by_side: dict[SourceHunkSide, list[HunkLineMap]] = {
            "old": [],
            "new": [],
            "either": [],
        }
        for hunk in file_map.hunks:
            for matched_side in _source_hunk_matching_sides(
                source_hunk,
                hunk,
                requested_sides=requested_sides,
            ):
                matched_by_side[matched_side].append(hunk)
        resolved_side = _resolve_source_hunk_side_match(
            source_hunk,
            requested_sides=requested_sides,
            matched_by_side=matched_by_side,
        )
        if resolved_side is None:
            if any(matched_by_side[side] for side in ("old", "new")):
                return _MatchFailure(
                    reason_code="evidence_missing",
                    source_hunks=(
                        SourceHunk(
                            file=normalized_file,
                            start=source_hunk.start,
                            end=source_hunk.end,
                            side=source_hunk.side,
                        ),
                    ),
                )
            return _MatchFailure(
                reason_code="line_outside_hunk",
                source_hunks=(
                    SourceHunk(
                        file=normalized_file,
                        start=source_hunk.start,
                        end=source_hunk.end,
                        side=source_hunk.side,
                    ),
                ),
            )
        normalized_hunks.append(
            SourceHunk(
                file=normalized_file,
                start=source_hunk.start,
                end=source_hunk.end,
                side=resolved_side,
            )
        )
        matched_hunks.extend(matched_by_side[resolved_side])
    return _MatchedContext(
        source_hunks=tuple(normalized_hunks),
        matched_hunks=tuple(dict.fromkeys(matched_hunks)),
    )


def _build_file_lookup(line_maps: Iterable[FileLineMap]) -> dict[str, tuple[FileLineMap, ...]]:
    lookup: dict[str, list[FileLineMap]] = {}

    def add(path: str | None, item: FileLineMap) -> None:
        if path is None:
            return
        identity = _identity(path)
        existing = lookup.setdefault(identity, [])
        if all(candidate.file_id != item.file_id for candidate in existing):
            existing.append(item)

    for item in line_maps:
        add(item.display_path, item)
        add(item.old_path, item)
        add(item.new_path, item)
    return {key: tuple(value) for key, value in lookup.items()}


def _match_symbols(
    claim_symbols: Sequence[str],
    *,
    source_hunks: Sequence[SourceHunk],
    matched_hunks: Sequence[HunkLineMap],
    symbols: Iterable[SymbolRecord],
) -> tuple[tuple[SymbolRecord, ...], tuple[str, ...]]:
    if not claim_symbols:
        return (), ()
    allowed_paths = {_identity(item.file) for item in source_hunks}
    allowed_hunk_ids = {item.hunk_id for item in matched_hunks}
    candidate_symbols = [
        item
        for item in symbols
        if _identity(item.path) in allowed_paths
        and (not allowed_hunk_ids or bool(set(item.hunk_ids) & allowed_hunk_ids))
    ]
    matched: list[SymbolRecord] = []
    unmatched: list[str] = []
    for claim_symbol in claim_symbols:
        exact = [item for item in candidate_symbols if item.qualified_name == claim_symbol]
        if exact:
            matched.append(_pick_best_symbol(exact))
            continue
        fuzzy = _match_fuzzy_symbol(
            claim_symbol,
            source_hunks=source_hunks,
            candidate_symbols=candidate_symbols,
        )
        if fuzzy is not None:
            matched.append(fuzzy)
            continue
        unmatched.append(claim_symbol)
    return tuple(dict.fromkeys(matched)), tuple(unmatched)


def _pick_best_symbol(matches: Sequence[SymbolRecord]) -> SymbolRecord:
    priority = {"high": 3, "medium": 2, "low": 1}
    return max(
        matches,
        key=lambda item: (
            priority[item.confidence],
            len(item.hunk_ids),
            len(item.touched_lines),
            item.qualified_name,
        ),
    )


def _source_hunk_matching_sides(
    source_hunk: SourceHunk,
    hunk: HunkLineMap,
    *,
    requested_sides: Sequence[SourceHunkSide],
) -> tuple[SourceHunkSide, ...]:
    old_lines, new_lines = _hunk_line_sides(hunk)
    matched: list[SourceHunkSide] = []
    if "old" in requested_sides and _source_hunk_is_within_lines(source_hunk, old_lines):
        matched.append("old")
    if "new" in requested_sides and _source_hunk_is_within_lines(source_hunk, new_lines):
        matched.append("new")
    return tuple(matched)


def _hunk_line_sides(hunk: HunkLineMap) -> tuple[set[int], set[int]]:
    return (
        {
            *hunk.deleted_lines,
            *hunk.context_old_lines,
        },
        {
            *hunk.added_lines,
            *hunk.context_new_lines,
        },
    )


def _source_hunk_is_within_lines(source_hunk: SourceHunk, line_numbers: set[int]) -> bool:
    return all(
        line_number in line_numbers for line_number in range(source_hunk.start, source_hunk.end + 1)
    )


def _requested_source_hunk_sides(
    source_hunk: SourceHunk,
    *,
    file_map: FileLineMap,
) -> tuple[SourceHunkSide, ...]:
    if source_hunk.side != "either":
        return (source_hunk.side,)
    inferred = _infer_source_hunk_side_from_path(file_map, raw_path=source_hunk.file)
    if inferred is not None:
        return (inferred,)
    if file_map.change_kind == "deleted":
        return ("old",)
    if file_map.change_kind == "added":
        return ("new",)
    return ("old", "new")


def _infer_source_hunk_side_from_path(
    file_map: FileLineMap,
    *,
    raw_path: str,
) -> SourceHunkSide | None:
    target = _identity(raw_path)
    old_matches = file_map.old_path is not None and _identity(file_map.old_path) == target
    new_matches = file_map.new_path is not None and _identity(file_map.new_path) == target
    if old_matches and not new_matches:
        return "old"
    if new_matches and not old_matches:
        return "new"
    return None


def _resolve_source_hunk_side_match(
    source_hunk: SourceHunk,
    *,
    requested_sides: Sequence[SourceHunkSide],
    matched_by_side: Mapping[SourceHunkSide, Sequence[HunkLineMap]],
) -> SourceHunkSide | None:
    if source_hunk.side != "either":
        return source_hunk.side if matched_by_side[source_hunk.side] else None
    if len(requested_sides) == 1:
        requested_side = requested_sides[0]
        return requested_side if matched_by_side[requested_side] else None
    old_matched = bool(matched_by_side["old"])
    new_matched = bool(matched_by_side["new"])
    if old_matched and not new_matched:
        return "old"
    if new_matched and not old_matched:
        return "new"
    if old_matched and new_matched and source_hunk.start != source_hunk.end:
        return "new"
    return None


def _resolve_text_only_source_hunk_side(
    source_hunk: SourceHunk,
    *,
    requested_sides: Sequence[SourceHunkSide],
    file_map: FileLineMap,
    before_text_lookup: Mapping[str, str],
    after_text_lookup: Mapping[str, str],
) -> SourceHunkSide | None:
    matched_sides: list[SourceHunkSide] = [
        side
        for side in requested_sides
        if _source_hunk_is_within_file_text_for_side(
            source_hunk,
            side=side,
            file_map=file_map,
            before_text_lookup=before_text_lookup,
            after_text_lookup=after_text_lookup,
        )
    ]
    if source_hunk.side != "either":
        return source_hunk.side if matched_sides else None
    if len(matched_sides) == 1:
        return matched_sides[0]
    return None


def _resolve_claim_extractor(
    candidate: ClaimCandidate,
    symbol_matches: Sequence[SymbolRecord] = (),
) -> ClaimExtractor:
    if symbol_matches:
        return symbol_matches[0].extractor
    if candidate.extractor is not None:
        return cast("ClaimExtractor", candidate.extractor)
    return "section_header"


def _normalize_symbol_name(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value).casefold()


def _match_fuzzy_symbol(
    claim_symbol: str,
    *,
    source_hunks: Sequence[SourceHunk],
    candidate_symbols: Sequence[SymbolRecord],
) -> SymbolRecord | None:
    normalized_claim = _normalize_symbol_segments(claim_symbol)
    if not normalized_claim:
        return None
    full_matches = [
        item
        for item in candidate_symbols
        if _normalize_symbol_segments(item.qualified_name) == normalized_claim
    ]
    if full_matches:
        return _pick_best_symbol(full_matches)

    claim_parent = normalized_claim[:-1]
    claim_basename = normalized_claim[-1]
    basename_matches = [
        item
        for item in candidate_symbols
        if _normalize_symbol_segments(item.qualified_name)[-1:] == (claim_basename,)
    ]
    if not basename_matches:
        return None
    if claim_parent:
        scoped_matches = [
            item
            for item in basename_matches
            if _normalize_symbol_segments(item.qualified_name)[:-1] == claim_parent
        ]
        if scoped_matches:
            return _pick_best_symbol(scoped_matches)
        return None

    overlapping_matches = [
        item for item in basename_matches if _symbol_overlaps_source_hunks(item, source_hunks)
    ]
    if len(overlapping_matches) == 1:
        return overlapping_matches[0]
    if overlapping_matches:
        basename_matches = overlapping_matches

    parent_scopes = {
        _normalize_symbol_segments(item.qualified_name)[:-1] for item in basename_matches
    }
    if len(parent_scopes) > 1:
        return None
    return _pick_best_symbol(basename_matches)


def _normalize_symbol_segments(value: str) -> tuple[str, ...]:
    normalized = value.replace("::", ".").replace("#", ".")
    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return ()
    return tuple(_normalize_symbol_name(part) for part in parts if _normalize_symbol_name(part))


def _symbol_overlaps_source_hunks(
    symbol: SymbolRecord,
    source_hunks: Sequence[SourceHunk],
) -> bool:
    symbol_lines = set(symbol.touched_lines)
    symbol_path = _identity(symbol.path)
    for source_hunk in source_hunks:
        if _identity(source_hunk.file) != symbol_path:
            continue
        if symbol_lines & set(range(source_hunk.start, source_hunk.end + 1)):
            return True
    return False


def _build_text_lookup(mapping: Mapping[str, str]) -> dict[str, str]:
    return {_identity(path): text for path, text in mapping.items()}


def _resolve_source_hunk_file(file_map: FileLineMap, raw_path: str) -> str:
    target = _identity(raw_path)
    for candidate in (file_map.old_path, file_map.new_path, file_map.display_path):
        if candidate is not None and _identity(candidate) == target:
            return candidate
    return file_map.display_path


def _source_hunk_is_within_file_text(
    source_hunk: SourceHunk,
    *,
    file_map: FileLineMap,
    before_text_lookup: Mapping[str, str],
    after_text_lookup: Mapping[str, str],
) -> bool:
    line_counts: list[int] = []
    for candidate in (file_map.old_path, file_map.new_path, file_map.display_path):
        if candidate is None:
            continue
        candidate_identity = _identity(candidate)
        before_text = before_text_lookup.get(candidate_identity)
        if before_text is not None:
            line_counts.append(len(before_text.splitlines()))
        after_text = after_text_lookup.get(candidate_identity)
        if after_text is not None:
            line_counts.append(len(after_text.splitlines()))
    if not line_counts:
        return False
    return source_hunk.start >= 1 and source_hunk.end <= max(line_counts)


def _source_hunk_is_within_file_text_for_side(
    source_hunk: SourceHunk,
    *,
    side: SourceHunkSide,
    file_map: FileLineMap,
    before_text_lookup: Mapping[str, str],
    after_text_lookup: Mapping[str, str],
) -> bool:
    if side == "old":
        candidate_paths = (file_map.old_path, file_map.display_path)
        lookup = before_text_lookup
    else:
        candidate_paths = (file_map.new_path, file_map.display_path)
        lookup = after_text_lookup
    line_counts: list[int] = []
    for candidate in candidate_paths:
        if candidate is None:
            continue
        text = lookup.get(_identity(candidate))
        if text is not None:
            line_counts.append(len(text.splitlines()))
    if not line_counts:
        return False
    return source_hunk.start >= 1 and source_hunk.end <= max(line_counts)


def _identity(path: str) -> str:
    return path_identity_key(Path(path))


__all__ = ["verify_claim_candidate", "verify_claim_candidates"]
