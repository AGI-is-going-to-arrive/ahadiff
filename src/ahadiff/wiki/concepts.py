from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.git.repo import open_repo, run_git

_MAX_VISIBLE_CONCEPTS_BYTES = 10 * 1024 * 1024
_MAX_ANCESTRY_CHECKS = 200

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ahadiff.quiz.schemas import QuizQuestion


@dataclass(frozen=True)
class ConceptOccurrence:
    concept: str
    related_claims: tuple[str, ...]
    file_refs: tuple[str, ...]


@dataclass(frozen=True)
class ConceptPage:
    entries: tuple[dict[str, Any], ...]
    next_cursor: str | None


class _AncestryCache:
    def __init__(self, workspace_root: Path, head_ref: str) -> None:
        self.workspace_root = workspace_root
        self.head_ref = head_ref
        self._cache: dict[str, bool] = {}
        self._call_count = 0

    def is_visible(self, source_ref: object) -> bool:
        if not isinstance(source_ref, str) or not source_ref:
            return False
        cached = self._cache.get(source_ref)
        if cached is not None:
            return cached
        self._call_count += 1
        if self._call_count > _MAX_ANCESTRY_CHECKS:
            self._cache[source_ref] = True
            return True
        visible = _is_ancestor(self.workspace_root, source_ref, self.head_ref)
        self._cache[source_ref] = visible
        return visible


def append_concepts(
    *,
    workspace_root: Path,
    run_path: Path,
    run_id: str,
    source_kind: str,
    source_ref: str,
    questions: Sequence[QuizQuestion],
) -> Path | None:
    occurrences = _collect_concept_occurrences(questions)
    if not occurrences:
        return None
    if source_kind in {"patch_file", "patch_stdin", "file_compare"}:
        local_path = run_path / "concepts_local.jsonl"
        payload = [
            _concept_entry(
                occurrence=occurrence,
                run_id=run_id,
                source_ref=source_ref,
                branch_hint=None,
            )
            for occurrence in occurrences
        ]
        _write_jsonl_snapshot(local_path, payload)
        return local_path

    repo = open_repo(workspace_root)
    branch_hint = repo.current_branch
    concepts_path = workspace_root / ".ahadiff" / "concepts.jsonl"
    existing = {entry["term_key"]: entry for entry in _load_jsonl_entries(concepts_path)}
    for occurrence in occurrences:
        term_key = compute_term_key(occurrence.concept)
        entry = existing.get(term_key)
        if entry is None:
            existing[term_key] = _concept_entry(
                occurrence=occurrence,
                run_id=run_id,
                source_ref=source_ref,
                branch_hint=branch_hint,
            )
            continue
        entry.setdefault("term", occurrence.concept)
        entry.setdefault("display_name", occurrence.concept)
        entry.setdefault("lang", "en")
        entry.setdefault("aliases", [])
        entry["source_refs"] = _merge_unique_strings(entry.get("source_refs", []), [source_ref])
        entry["updated_by_runs"] = _merge_unique_strings(entry.get("updated_by_runs", []), [run_id])
        entry["related_claims"] = _merge_unique_strings(
            entry.get("related_claims", []),
            list(occurrence.related_claims),
        )
        entry["file_refs"] = _merge_unique_strings(
            entry.get("file_refs", []),
            list(occurrence.file_refs),
        )
        if entry.get("branch_hint") is None and branch_hint is not None:
            entry["branch_hint"] = branch_hint
    ordered = [existing[key] for key in sorted(existing)]
    _write_jsonl_snapshot(concepts_path, ordered)
    db_path = workspace_root / ".ahadiff" / "review.sqlite"
    from ahadiff.review.database import upsert_concepts_batch

    upsert_concepts_batch(db_path, ordered)
    return concepts_path


def load_visible_concepts(
    *,
    workspace_root: Path,
    head_ref: str = "HEAD",
) -> tuple[dict[str, Any], ...]:
    concepts_path = workspace_root / ".ahadiff" / "concepts.jsonl"
    if not concepts_path.exists() or concepts_path.is_symlink():
        return ()
    if concepts_path.stat().st_size > _MAX_VISIBLE_CONCEPTS_BYTES:
        raise InputError("concepts.jsonl exceeds size limit")
    open_repo(workspace_root)
    visible: list[dict[str, Any]] = []
    ancestry = _AncestryCache(workspace_root, head_ref)
    for _line_index, entry in _iter_jsonl_entries_with_offsets(
        concepts_path,
        max_bytes=_MAX_VISIBLE_CONCEPTS_BYTES,
    ):
        source_refs = cast("object", entry.get("source_refs", []))
        source_ref_values: list[str] = []
        if isinstance(source_refs, list):
            for source_ref in cast("list[object]", source_refs):
                if isinstance(source_ref, str):
                    source_ref_values.append(source_ref)
        if any(ancestry.is_visible(source_ref) for source_ref in source_ref_values):
            visible.append(entry)
    return tuple(visible)


def load_concepts_page(
    path: Path,
    *,
    limit: int,
    cursor: int = 0,
    max_bytes: int | None = None,
) -> ConceptPage:
    if limit < 1:
        raise InputError("concepts page limit must be >= 1")
    entries: list[dict[str, Any]] = []
    next_cursor: str | None = None
    for line_index, entry in _iter_jsonl_entries_with_offsets(path, max_bytes=max_bytes):
        if line_index < cursor:
            continue
        if len(entries) >= limit:
            next_cursor = str(line_index)
            break
        entries.append(entry)
    return ConceptPage(entries=tuple(entries), next_cursor=next_cursor)


def load_concepts_page_from_storage(
    state_dir: Path,
    *,
    limit: int,
    cursor: str | None = None,
    max_bytes: int | None = None,
) -> ConceptPage:
    db_path = state_dir / "review.sqlite"
    concepts_path = state_dir / "concepts.jsonl"
    jsonl_readable = _concepts_jsonl_readable(concepts_path, max_bytes=max_bytes)
    if db_path.exists():
        try:
            if jsonl_readable:
                _sync_jsonl_concepts_to_db(
                    db_path,
                    concepts_path,
                    max_bytes=max_bytes,
                )
            page = load_concepts_page_from_db(db_path, limit=limit, cursor=cursor)
        except InputError:
            raise
        except Exception:
            if not jsonl_readable:
                raise
        else:
            if page.entries or cursor is not None or not jsonl_readable:
                return page
    if not jsonl_readable:
        return ConceptPage(entries=(), next_cursor=None)
    return load_concepts_page(
        concepts_path,
        limit=limit,
        cursor=parse_jsonl_concepts_cursor(cursor),
        max_bytes=max_bytes,
    )


def parse_jsonl_concepts_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError as exc:
        raise InputError("concepts JSONL cursor must be an integer") from exc
    if value < 0:
        raise InputError("concepts JSONL cursor must be >= 0")
    return value


def compute_term_key(value: str) -> str:
    source = unicodedata.normalize("NFKC", value).strip().casefold()
    if not source:
        raise InputError("concept term_key would be empty")
    parts: list[str] = []
    ascii_chars: list[str] = []
    unicode_chars: list[str] = []

    def flush_ascii() -> None:
        if ascii_chars:
            parts.append("".join(ascii_chars))
            ascii_chars.clear()

    def flush_unicode() -> None:
        if unicode_chars:
            parts.append("u-" + "-".join(unicode_chars))
            unicode_chars.clear()

    for char in source:
        if char.isascii() and char.isalnum():
            flush_unicode()
            ascii_chars.append(char)
        elif char.isalnum():
            flush_ascii()
            unicode_chars.append(format(ord(char), "x"))
        else:
            flush_ascii()
            flush_unicode()
    flush_ascii()
    flush_unicode()
    term_key = re.sub(r"-+", "-", "-".join(parts)).strip("-")
    if not term_key:
        raise InputError("concept term_key would be empty")
    return term_key


def _collect_concept_occurrences(
    questions: Sequence[QuizQuestion],
) -> tuple[ConceptOccurrence, ...]:
    merged: dict[str, ConceptOccurrence] = {}
    for question in questions:
        file_refs = tuple(dict.fromkeys(item.file for item in question.evidence))
        for concept in question.concepts:
            term_key = compute_term_key(concept)
            existing = merged.get(term_key)
            if existing is None:
                merged[term_key] = ConceptOccurrence(
                    concept=concept,
                    related_claims=tuple(question.source_claims),
                    file_refs=file_refs,
                )
                continue
            merged[term_key] = ConceptOccurrence(
                concept=existing.concept,
                related_claims=tuple(
                    _merge_unique_strings(existing.related_claims, question.source_claims)
                ),
                file_refs=tuple(_merge_unique_strings(existing.file_refs, file_refs)),
            )
    return tuple(merged[key] for key in sorted(merged))


def _concept_entry(
    *,
    occurrence: ConceptOccurrence,
    run_id: str,
    source_ref: str,
    branch_hint: str | None,
) -> dict[str, Any]:
    return {
        "concept": occurrence.concept,
        "term_key": compute_term_key(occurrence.concept),
        "term": occurrence.concept,
        "display_name": occurrence.concept,
        "lang": "en",
        "aliases": [],
        "source_refs": [source_ref],
        "branch_hint": branch_hint,
        "introduced_by_run": run_id,
        "updated_by_runs": [run_id],
        "related_claims": list(occurrence.related_claims),
        "file_refs": list(occurrence.file_refs),
    }


def _load_jsonl_entries(path: Path) -> list[dict[str, Any]]:
    return list(_iter_jsonl_entries(path))


def _iter_jsonl_entries(path: Path) -> Iterable[dict[str, Any]]:
    for _line_index, entry in _iter_jsonl_entries_with_offsets(path):
        yield entry


def _iter_jsonl_entries_with_offsets(
    path: Path,
    *,
    max_bytes: int | None = None,
) -> Iterable[tuple[int, dict[str, Any]]]:
    if not path.exists():
        return
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise InputError(f"{path.name} exceeds size limit")
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = safe_json_loads(stripped)
            except (json.JSONDecodeError, ValueError) as exc:
                raise InputError(f"invalid concepts.jsonl line {index}") from exc
            if not isinstance(payload, dict):
                raise InputError(f"concepts.jsonl line {index} must be an object")
            yield index, cast("dict[str, Any]", payload)


def _concepts_jsonl_readable(path: Path, *, max_bytes: int | None = None) -> bool:
    if not path.exists() or path.is_symlink():
        return False
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise InputError(f"{path.name} exceeds size limit")
    return True


def _sync_jsonl_concepts_to_db(
    db_path: Path,
    concepts_path: Path,
    *,
    max_bytes: int | None = None,
) -> int:
    entries = [
        entry
        for _line_index, entry in _iter_jsonl_entries_with_offsets(
            concepts_path,
            max_bytes=max_bytes,
        )
    ]
    if not entries:
        return 0
    from ahadiff.review.database import upsert_concepts_batch

    return upsert_concepts_batch(db_path, entries)


def _write_jsonl_snapshot(path: Path, entries: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        try:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    temp_path.replace(path)


def _merge_unique_strings(existing: Sequence[str], incoming: Sequence[str]) -> list[str]:
    merged: list[str] = []
    for value in (*existing, *incoming):
        normalized = value.strip()
        if normalized and normalized not in merged:
            merged.append(normalized)
    return merged


def load_concepts_page_from_db(
    db_path: Path,
    *,
    limit: int,
    cursor: str | None = None,
) -> ConceptPage:
    """Load concepts from SQLite with keyset pagination."""
    if limit < 1:
        raise InputError("concepts page limit must be >= 1")
    from ahadiff.review.database import load_concepts_from_db

    rows = load_concepts_from_db(
        db_path,
        limit=limit + 1,
        after_term_key=cursor,
    )
    if len(rows) > limit:
        entries = tuple(dict(r) for r in rows[:limit])
        last = entries[-1]
        next_cursor = str(last.get("term_key", ""))
        return ConceptPage(entries=entries, next_cursor=next_cursor)
    return ConceptPage(entries=tuple(dict(r) for r in rows), next_cursor=None)


def _is_ancestor(repo_root: Path, source_ref: str, head_ref: str) -> bool:
    result = run_git(repo_root, "merge-base", "--is-ancestor", source_ref, head_ref, check=False)
    return result.returncode == 0


__all__ = [
    "ConceptOccurrence",
    "ConceptPage",
    "append_concepts",
    "compute_term_key",
    "load_concepts_page",
    "load_concepts_page_from_db",
    "load_concepts_page_from_storage",
    "load_visible_concepts",
    "parse_jsonl_concepts_cursor",
]
