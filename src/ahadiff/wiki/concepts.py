from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.git.repo import open_repo, run_git

_MAX_VISIBLE_CONCEPTS_BYTES = 10 * 1024 * 1024
_MAX_ANCESTRY_CHECKS = 200
_MAX_ANCESTRY_INDEX_COUNT = 10_000
_EXPORT_CONCEPTS_BATCH_SIZE = 1000
_SHORT_SHA_RE = re.compile(r"[0-9a-fA-F]{4,39}")
_DB_CURSOR_PREFIX = "db:"
_JSONL_CURSOR_PREFIX = "jsonl:"

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
        self._ancestors: frozenset[str] | None = None
        self._prefix_index: dict[str, str] | None = None
        self._head_sha: str | None = None
        self._call_count = 0

    @property
    def _db_path(self) -> Path:
        return self.workspace_root / ".ahadiff" / "review.sqlite"

    def _resolve_head_sha(self) -> str | None:
        if self._head_sha is not None:
            return self._head_sha
        try:
            result = run_git(
                self.workspace_root,
                "rev-parse",
                "--verify",
                f"{self.head_ref}^{{commit}}",
                timeout=15,
            )
            self._head_sha = result.stdout.strip().lower() or None
        except Exception:
            self._head_sha = None
        return self._head_sha

    def _ensure_ancestors(self) -> frozenset[str]:
        if self._ancestors is not None:
            return self._ancestors
        shas: frozenset[str]
        head_sha = self._resolve_head_sha()
        if head_sha is not None:
            with suppress(Exception):
                from ahadiff.review.database import load_commit_ancestry

                cached = load_commit_ancestry(self._db_path, head_sha=head_sha)
                if cached:
                    shas = frozenset(item.lower() for item in cached if item)
                    self._ancestors = shas
                    self._prefix_index = _build_prefix_index(shas)
                    return shas
        try:
            result = run_git(
                self.workspace_root,
                "rev-list",
                self.head_ref,
                f"--max-count={_MAX_ANCESTRY_INDEX_COUNT}",
                timeout=15,
            )
            ancestor_list = [
                line.strip().lower() for line in result.stdout.splitlines() if line.strip()
            ]
            shas = frozenset(ancestor_list)
            if head_sha is not None and ancestor_list:
                with suppress(Exception):
                    from ahadiff.review.database import replace_commit_ancestry

                    replace_commit_ancestry(
                        self._db_path,
                        head_sha=head_sha,
                        ancestors=ancestor_list,
                    )
        except Exception:
            shas = frozenset()
        self._ancestors = shas
        self._prefix_index = _build_prefix_index(shas)
        return shas

    def is_visible(self, source_ref: object) -> bool:
        if not isinstance(source_ref, str) or not source_ref:
            return False
        cached = self._cache.get(source_ref)
        if cached is not None:
            return cached
        ancestors = self._ensure_ancestors()
        lowered = source_ref.lower()
        if lowered in ancestors:
            self._cache[source_ref] = True
            return True
        if self._prefix_index is not None and _SHORT_SHA_RE.fullmatch(source_ref):
            indexed_sha = self._prefix_index.get(lowered)
            if indexed_sha is not None and _short_sha_resolves_to(
                self.workspace_root,
                source_ref,
                indexed_sha,
            ):
                self._cache[source_ref] = True
                return True
        self._call_count += 1
        if self._call_count > _MAX_ANCESTRY_CHECKS:
            self._cache[source_ref] = False
            return False
        visible = _is_ancestor(self.workspace_root, source_ref, self.head_ref)
        self._cache[source_ref] = visible
        return visible


def _build_prefix_index(full_shas: frozenset[str]) -> dict[str, str]:
    """Build a prefix lookup from 4..39-char prefixes to full SHAs.

    Only stores unique prefixes — ambiguous prefixes are excluded.
    """
    index: dict[str, str | None] = {}
    for sha in full_shas:
        normalized_sha = sha.lower()
        for length in range(4, min(len(normalized_sha), 40)):
            prefix = normalized_sha[:length]
            if prefix in index:
                if index[prefix] != normalized_sha:
                    index[prefix] = None
            else:
                index[prefix] = normalized_sha
    return {k: v for k, v in index.items() if v is not None}


def _short_sha_resolves_to(workspace_root: Path, source_ref: str, expected_sha: str) -> bool:
    try:
        result = run_git(
            workspace_root,
            "rev-parse",
            "--verify",
            "--quiet",
            f"{source_ref}^{{commit}}",
            timeout=15,
        )
    except Exception:
        return False
    return result.stdout.strip().lower() == expected_sha.lower()


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
    ordered = _link_graphify_entries(workspace_root, [existing[key] for key in sorted(existing)])
    _write_jsonl_snapshot(concepts_path, ordered)
    db_path = workspace_root / ".ahadiff" / "review.sqlite"
    from ahadiff.review.database import upsert_concepts_batch

    upsert_concepts_batch(db_path, ordered)
    return concepts_path


def _link_graphify_entries(
    workspace_root: Path,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    graph_path = workspace_root / ".ahadiff" / "graphify" / "graph.json"
    if not entries or not graph_path.exists():
        return entries
    try:
        from ahadiff.core.paths import reject_leaf_symlink_or_reparse
        from ahadiff.graphify import link_concepts_to_entries, parse_graph_json

        reject_leaf_symlink_or_reparse(graph_path, label="graphify graph")
        graph = parse_graph_json(graph_path)
        return link_concepts_to_entries(graph, entries)
    except (InputError, OSError, ValueError):
        return entries


def load_visible_concepts(
    *,
    workspace_root: Path,
    head_ref: str = "HEAD",
) -> tuple[dict[str, Any], ...]:
    from ahadiff.core.paths import reject_leaf_symlink_or_reparse

    concepts_path = workspace_root / ".ahadiff" / "concepts.jsonl"
    if not concepts_path.exists():
        return ()
    leaf_stat = reject_leaf_symlink_or_reparse(concepts_path, label="concepts.jsonl")
    if leaf_stat.st_size > _MAX_VISIBLE_CONCEPTS_BYTES:
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
    cursor_kind, cursor_value = _decode_storage_cursor(cursor)
    if cursor_kind == "jsonl":
        if not jsonl_readable:
            return ConceptPage(entries=(), next_cursor=None)
        return _prefix_concepts_cursor(
            load_concepts_page(
                concepts_path,
                limit=limit,
                cursor=parse_jsonl_concepts_cursor(cursor_value),
                max_bytes=max_bytes,
            ),
            _JSONL_CURSOR_PREFIX,
        )
    if db_path.exists():
        try:
            if jsonl_readable:
                _sync_jsonl_concepts_to_db(
                    db_path,
                    concepts_path,
                    max_bytes=max_bytes,
                )
            db_cursor = cursor_value if cursor_kind in {"db", "db_legacy"} else None
            page = load_concepts_page_from_db(db_path, limit=limit, cursor=db_cursor)
        except InputError:
            raise
        except Exception:
            if cursor_kind in {"db", "db_legacy"} and jsonl_readable:
                return _load_concepts_page_from_jsonl_after_term_key(
                    concepts_path,
                    after_term_key=str(cursor_value),
                    limit=limit,
                    max_bytes=max_bytes,
                    legacy_cursor=cursor_kind == "db_legacy",
                )
            if not jsonl_readable:
                raise
        else:
            if page.entries or cursor_kind in {"db", "db_legacy"} or not jsonl_readable:
                return _prefix_concepts_cursor(page, _DB_CURSOR_PREFIX)
    if not jsonl_readable:
        return ConceptPage(entries=(), next_cursor=None)
    if cursor_kind in {"db", "db_legacy"}:
        return _load_concepts_page_from_jsonl_after_term_key(
            concepts_path,
            after_term_key=str(cursor_value),
            limit=limit,
            max_bytes=max_bytes,
            legacy_cursor=cursor_kind == "db_legacy",
        )
    return _prefix_concepts_cursor(
        load_concepts_page(
            concepts_path,
            limit=limit,
            cursor=0,
            max_bytes=max_bytes,
        ),
        _JSONL_CURSOR_PREFIX,
    )


def _prefix_concepts_cursor(page: ConceptPage, prefix: str) -> ConceptPage:
    if page.next_cursor is None:
        return page
    return ConceptPage(entries=page.entries, next_cursor=f"{prefix}{page.next_cursor}")


def _decode_storage_cursor(cursor: str | None) -> tuple[str | None, str | None]:
    if cursor is None:
        return None, None
    if cursor.startswith(_JSONL_CURSOR_PREFIX):
        value = cursor.removeprefix(_JSONL_CURSOR_PREFIX)
        return "jsonl", str(parse_jsonl_concepts_cursor(value))
    if cursor.startswith(_DB_CURSOR_PREFIX):
        value = cursor.removeprefix(_DB_CURSOR_PREFIX)
        if not value:
            raise InputError("concepts DB cursor must include a term key")
        return "db", value
    try:
        return "jsonl", str(parse_jsonl_concepts_cursor(cursor))
    except InputError:
        if not cursor.strip():
            raise
        return "db_legacy", cursor


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


def _load_concepts_page_from_jsonl_after_term_key(
    path: Path,
    *,
    after_term_key: str,
    limit: int,
    max_bytes: int | None = None,
    legacy_cursor: bool = False,
) -> ConceptPage:
    if limit < 1:
        raise InputError("concepts page limit must be >= 1")
    entries: list[dict[str, Any]] = []
    saw_cursor = False
    next_cursor: str | None = None
    last_returned: str | None = None
    for _line_index, entry in _iter_jsonl_entries_with_offsets(path, max_bytes=max_bytes):
        term_key = entry.get("term_key")
        if not isinstance(term_key, str):
            continue
        if term_key == after_term_key:
            saw_cursor = True
            continue
        if term_key <= after_term_key:
            continue
        if len(entries) >= limit:
            next_cursor = last_returned
            break
        entries.append(entry)
        last_returned = term_key
    if not saw_cursor:
        if legacy_cursor:
            raise InputError("concepts JSONL cursor must be an integer")
        raise InputError("concepts DB cursor is not compatible with JSONL fallback")
    return _prefix_concepts_cursor(
        ConceptPage(entries=tuple(entries), next_cursor=next_cursor),
        _DB_CURSOR_PREFIX,
    )


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
        "graphify_node_id": None,
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
    from ahadiff.core.paths import reject_leaf_symlink_or_reparse

    leaf_stat = reject_leaf_symlink_or_reparse(path, label=path.name)
    import stat as stat_mod

    if not stat_mod.S_ISREG(leaf_stat.st_mode):
        raise InputError(f"{path.name} is not a regular file")
    if max_bytes is not None and leaf_stat.st_size > max_bytes:
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
    if not path.exists():
        return False
    try:
        leaf_stat = path.lstat()
    except OSError:
        return False
    import stat as stat_mod

    if stat_mod.S_ISLNK(leaf_stat.st_mode):
        return False
    if not stat_mod.S_ISREG(leaf_stat.st_mode):
        return False
    if bool(getattr(leaf_stat, "st_file_attributes", 0) & 0x400):
        return False
    if max_bytes is not None and leaf_stat.st_size > max_bytes:
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


def export_concepts_from_db(state_dir: Path) -> Path:
    db_path = state_dir / "review.sqlite"
    concepts_path = state_dir / "concepts.jsonl"
    if not db_path.exists():
        raise InputError("review.sqlite not found")
    from ahadiff.review.database import load_concepts_from_db

    _DB_ONLY_KEYS = {"created_at_utc", "updated_at_utc"}
    entries: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        rows = load_concepts_from_db(
            db_path,
            limit=_EXPORT_CONCEPTS_BATCH_SIZE,
            after_term_key=cursor,
        )
        if not rows:
            break
        entries.extend({k: v for k, v in dict(r).items() if k not in _DB_ONLY_KEYS} for r in rows)
        last_term_key = rows[-1].get("term_key")
        if not isinstance(last_term_key, str) or not last_term_key:
            break
        cursor = last_term_key
    _write_jsonl_snapshot(concepts_path, entries)
    return concepts_path


def rollback_concepts_to_jsonl(db_path: Path, jsonl_path: Path) -> int:
    """Export all concepts from SQLite to JSONL, overwriting the target file.

    Uses atomic write (tmp -> replace) to avoid partial writes.
    Returns the number of entries exported.

    ``jsonl_path`` must reside under the same ``.ahadiff/`` tree as
    ``db_path``.  Callers outside the CLI surface should derive paths
    from ``concepts_path()`` rather than accepting user input directly.
    """
    if not db_path.exists():
        raise InputError("review.sqlite not found")
    if jsonl_path.is_symlink():
        raise InputError("jsonl_path must not be a symlink")
    try:
        jsonl_path.resolve().relative_to(db_path.resolve().parent)
    except ValueError:
        raise InputError(
            "jsonl_path must be under the same .ahadiff directory as db_path"
        ) from None
    from ahadiff.review.database import load_concepts_from_db

    _DB_ONLY_KEYS = {"created_at_utc", "updated_at_utc"}
    entries: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        rows = load_concepts_from_db(
            db_path,
            limit=_EXPORT_CONCEPTS_BATCH_SIZE,
            after_term_key=cursor,
        )
        if not rows:
            break
        for row in rows:
            entry = {k: v for k, v in dict(row).items() if k not in _DB_ONLY_KEYS}
            term_key = entry.get("term_key")
            if not isinstance(term_key, str) or not term_key:
                continue
            entries.append(entry)
        last_term_key = rows[-1].get("term_key")
        if not isinstance(last_term_key, str) or not last_term_key:
            break
        cursor = last_term_key
    _write_jsonl_snapshot(jsonl_path, entries)
    return len(entries)


def verify_concepts_consistency(
    db_path: Path,
    jsonl_path: Path,
) -> tuple[bool, list[str]]:
    """Compare JSONL and SQLite concept entries by term_key identity.

    Returns (is_consistent, list_of_discrepancies).
    """
    discrepancies: list[str] = []
    db_exists = db_path.exists()
    jsonl_exists = jsonl_path.exists()
    if not db_exists and not jsonl_exists:
        return (
            False,
            ["No concepts data found: review.sqlite and concepts.jsonl are both missing"],
        )

    jsonl_keys: set[str] = set()
    if jsonl_exists:
        for _idx, entry in _iter_jsonl_entries_with_offsets(jsonl_path):
            term_key = entry.get("term_key")
            if isinstance(term_key, str) and term_key:
                jsonl_keys.add(term_key)

    db_keys: set[str] = set()
    if db_exists:
        from ahadiff.review.database import load_concepts_from_db

        cursor: str | None = None
        while True:
            rows = load_concepts_from_db(
                db_path,
                limit=_EXPORT_CONCEPTS_BATCH_SIZE,
                after_term_key=cursor,
            )
            if not rows:
                break
            for row in rows:
                term_key = row.get("term_key")
                if isinstance(term_key, str) and term_key:
                    db_keys.add(term_key)
            last = rows[-1].get("term_key")
            if not isinstance(last, str) or not last:
                break
            cursor = last

    if len(jsonl_keys) != len(db_keys):
        discrepancies.append(
            f"count mismatch: JSONL has {len(jsonl_keys)}, SQLite has {len(db_keys)}"
        )
    only_jsonl = jsonl_keys - db_keys
    only_db = db_keys - jsonl_keys
    if only_jsonl:
        discrepancies.append(f"only in JSONL ({len(only_jsonl)}): {sorted(only_jsonl)[:10]}")
    if only_db:
        discrepancies.append(f"only in SQLite ({len(only_db)}): {sorted(only_db)[:10]}")

    return (len(discrepancies) == 0, discrepancies)


def _is_ancestor(repo_root: Path, source_ref: str, head_ref: str) -> bool:
    if source_ref.startswith("-") or head_ref.startswith("-"):
        return False
    result = run_git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        "--",
        source_ref,
        head_ref,
        check=False,
    )
    return result.returncode == 0


__all__ = [
    "ConceptOccurrence",
    "ConceptPage",
    "append_concepts",
    "compute_term_key",
    "export_concepts_from_db",
    "load_concepts_page",
    "load_concepts_page_from_db",
    "load_concepts_page_from_storage",
    "load_visible_concepts",
    "parse_jsonl_concepts_cursor",
    "rollback_concepts_to_jsonl",
    "verify_concepts_consistency",
]
