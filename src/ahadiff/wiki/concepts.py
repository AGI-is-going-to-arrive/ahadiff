from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.core.errors import InputError
from ahadiff.git.repo import open_repo, run_git

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ahadiff.quiz.schemas import QuizQuestion


@dataclass(frozen=True)
class ConceptOccurrence:
    concept: str
    related_claims: tuple[str, ...]
    file_refs: tuple[str, ...]


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
    return concepts_path


def load_visible_concepts(
    *,
    workspace_root: Path,
    head_ref: str = "HEAD",
) -> tuple[dict[str, Any], ...]:
    concepts_path = workspace_root / ".ahadiff" / "concepts.jsonl"
    if not concepts_path.exists():
        return ()
    open_repo(workspace_root)
    visible: list[dict[str, Any]] = []
    for entry in _load_jsonl_entries(concepts_path):
        source_refs = entry.get("source_refs", [])
        if any(_is_ancestor(workspace_root, source_ref, head_ref) for source_ref in source_refs):
            visible.append(entry)
    return tuple(visible)


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
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise InputError(f"invalid concepts.jsonl line {index}") from exc
        if not isinstance(payload, dict):
            raise InputError(f"concepts.jsonl line {index} must be an object")
        entries.append(cast("dict[str, Any]", payload))
    return entries


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


def _is_ancestor(repo_root: Path, source_ref: str, head_ref: str) -> bool:
    result = run_git(repo_root, "merge-base", "--is-ancestor", source_ref, head_ref, check=False)
    return result.returncode == 0


__all__ = ["ConceptOccurrence", "append_concepts", "compute_term_key", "load_visible_concepts"]
