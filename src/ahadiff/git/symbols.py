from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from .line_map import build_file_id_index

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from typing import Any

    from ahadiff.contracts.claim_status import ChangeKind, ClaimConfidence, ClaimExtractor

    from .parser import ChangedFileRecord, HunkRecord


@dataclass(frozen=True)
class SymbolRange:
    start: int
    end: int


@dataclass(frozen=True)
class SymbolRecord:
    path: str
    qualified_name: str
    kind: str
    range: SymbolRange
    selection_range: SymbolRange
    parent: str | None
    touched_lines: tuple[int, ...]
    hunk_ids: tuple[str, ...]
    hunk_hash: str
    change_kind: ChangeKind | None
    extractor: ClaimExtractor
    confidence: ClaimConfidence
    error: str | None = None


class SymbolExtractor(Protocol):
    def extract(
        self,
        path: str,
        before_text: str | None,
        after_text: str | None,
        hunks: Sequence[HunkRecord],
    ) -> list[SymbolRecord]: ...


_REGEX_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"), "function"),
    (re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)"), "class"),
    (
        re.compile(r"^\s*(?:export\s+default\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"),
        "function",
    ),
    (
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)"),
        "const",
    ),
    (
        re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
        "type",
    ),
)
_JS_LIKE_TOP_LEVEL_REGEX_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^\s*(?:export\s+default\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
        "class",
    ),
    (
        re.compile(
            r"^\s*(?:export\s+default\s+)?(?:async\s+)?function\s+"
            r"([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:<[^>{}()]+>)?\s*\("
        ),
        "function",
    ),
    (
        re.compile(
            r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
            r"(?:async\s*)?(?:function\b|(?:<[^>{}()]+>\s*)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>)"
        ),
        "function",
    ),
    (
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
        "const",
    ),
    (
        re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
        "type",
    ),
)
_JS_LIKE_METHOD_REGEX_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|readonly|static|abstract|override|declare|get|set)\s+)*"
            r"(?:async\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:<[^>{}()]+>)?\s*\("
        ),
        "method",
    ),
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|readonly|static|abstract|override|declare)\s+)*"
            r"(?:async\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
            r"(?:async\s*)?(?:function\b|(?:<[^>{}()]+>\s*)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>)"
        ),
        "method",
    ),
)
_JS_LIKE_NON_SYMBOL_NAMES = frozenset(
    {
        "catch",
        "class",
        "const",
        "default",
        "else",
        "enum",
        "export",
        "for",
        "function",
        "if",
        "interface",
        "let",
        "return",
        "switch",
        "throw",
        "type",
        "var",
        "while",
    }
)
_JS_LIKE_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
_JS_LIKE_STRING_RE = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`")
_SECTION_HEADER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"), "function"),
    (re.compile(r"class\s+([A-Za-z_][A-Za-z0-9_]*)"), "class"),
    (re.compile(r"function\s+([A-Za-z_][A-Za-z0-9_]*)"), "function"),
    (re.compile(r"(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)"), "const"),
)
_PRIORITY = {"python_ast": 3, "regex": 2, "section_header": 1}
SYMBOLS_SCHEMA = "ahadiff.symbols"
SYMBOLS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _RegexScopeCandidate:
    name: str
    kind: str
    line_number: int
    end_line: int
    indent: int
    parent: str | None = None
    qualified_name: str | None = None


def extract_symbols(
    changed_files: Iterable[ChangedFileRecord],
    *,
    before_text_by_path: Mapping[str, str] | None = None,
    after_text_by_path: Mapping[str, str] | None = None,
) -> tuple[SymbolRecord, ...]:
    records = tuple(changed_files)
    build_file_id_index(record.display_path for record in records)
    before_lookup = before_text_by_path or {}
    after_lookup = after_text_by_path or {}
    merged: list[SymbolRecord] = []

    for changed_file in records:
        before_text = _lookup_text(before_lookup, changed_file.old_path, changed_file.display_path)
        after_text = _lookup_text(after_lookup, changed_file.new_path, changed_file.display_path)
        candidates: list[SymbolRecord] = []
        if (
            changed_file.change_kind == "renamed"
            and changed_file.old_path is not None
            and changed_file.new_path is not None
            and before_text is not None
            and after_text is not None
            and changed_file.old_path != changed_file.new_path
        ):
            old_candidates = _extract_best_symbols(
                changed_file=changed_file,
                before_text=before_text,
                after_text=after_text,
                path_override=changed_file.old_path,
                source_selector="before",
            )
            if not old_candidates:
                old_candidates.extend(
                    _extract_section_header_symbols(
                        changed_file,
                        before_text=before_text,
                        after_text=after_text,
                        path_override=changed_file.old_path,
                        source_selector="before",
                    )
                )
            new_candidates = _extract_best_symbols(
                changed_file=changed_file,
                before_text=before_text,
                after_text=after_text,
                path_override=changed_file.new_path,
                source_selector="after",
            )
            if not new_candidates:
                new_candidates.extend(
                    _extract_section_header_symbols(
                        changed_file,
                        before_text=before_text,
                        after_text=after_text,
                        path_override=changed_file.new_path,
                        source_selector="after",
                    )
                )
            candidates.extend(old_candidates)
            candidates.extend(new_candidates)
        else:
            candidates = _extract_best_symbols(
                changed_file=changed_file,
                before_text=before_text,
                after_text=after_text,
            )
            if not candidates:
                candidates.extend(
                    _extract_section_header_symbols(
                        changed_file,
                        before_text=before_text,
                        after_text=after_text,
                    )
                )
        merged.extend(_merge_symbol_records(candidates))

    return tuple(merged)


def _extract_best_symbols(
    *,
    changed_file: ChangedFileRecord,
    before_text: str | None,
    after_text: str | None,
    path_override: str | None = None,
    source_selector: Literal["auto", "before", "after"] = "auto",
) -> list[SymbolRecord]:
    candidates: list[SymbolRecord] = []
    target_path = path_override or changed_file.display_path
    python_records, python_error = _extract_python_symbols(
        changed_file=changed_file,
        before_text=before_text,
        after_text=after_text,
        path_override=path_override,
        source_selector=source_selector,
    )
    candidates.extend(python_records)
    if not python_records and (_is_python_path(target_path) or python_error is not None):
        candidates.extend(
            _extract_regex_symbols(
                changed_file=changed_file,
                before_text=before_text,
                after_text=after_text,
                error=python_error,
                path_override=path_override,
                source_selector=source_selector,
            )
        )
    elif not _is_python_path(target_path):
        candidates.extend(
            _extract_regex_symbols(
                changed_file=changed_file,
                before_text=before_text,
                after_text=after_text,
                error=None,
                path_override=path_override,
                source_selector=source_selector,
            )
        )
    return candidates


def _lookup_text(
    mapping: Mapping[str, str],
    preferred_path: str | None,
    fallback_path: str,
) -> str | None:
    if preferred_path is not None and preferred_path in mapping:
        return mapping[preferred_path]
    return mapping.get(fallback_path)


def _extract_python_symbols(
    *,
    changed_file: ChangedFileRecord,
    before_text: str | None,
    after_text: str | None,
    path_override: str | None = None,
    source_selector: Literal["auto", "before", "after"] = "auto",
) -> tuple[list[SymbolRecord], str | None]:
    source_text, touched_lines, side, include_all = _symbol_source(
        changed_file, before_text, after_text, source_selector=source_selector
    )
    target_path = path_override or changed_file.display_path
    if not _is_python_path(target_path) or source_text is None:
        return [], None
    if changed_file.is_binary and not changed_file.hunks:
        return [], None

    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        message = f"{exc.__class__.__name__}: {exc.msg}"
        return [], message

    records: list[SymbolRecord] = []

    def visit(node: ast.AST, parents: tuple[str, ...] = ()) -> None:
        if isinstance(node, ast.ClassDef):
            records.extend(
                _build_ast_record(
                    path=target_path,
                    qualified_name=".".join((*parents, node.name)),
                    kind="class",
                    parent=".".join(parents) or None,
                    start=node.lineno,
                    end=node.end_lineno or node.lineno,
                    touched_lines=touched_lines,
                    include_all=include_all,
                    hunks=changed_file.hunks,
                    side=side,
                    change_kind=_symbol_change_kind(changed_file),
                )
            )
            for child in node.body:
                visit(child, (*parents, node.name))
            return
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            function_name = node.name
            if parents and any(part and part[0].isupper() for part in parents):
                kind = "method"
            elif function_name.startswith("test_"):
                kind = "test_function"
            else:
                kind = "function"
            records.extend(
                _build_ast_record(
                    path=target_path,
                    qualified_name=".".join((*parents, function_name)),
                    kind=kind,
                    parent=".".join(parents) or None,
                    start=node.lineno,
                    end=node.end_lineno or node.lineno,
                    touched_lines=touched_lines,
                    include_all=include_all,
                    hunks=changed_file.hunks,
                    side=side,
                    change_kind=_symbol_change_kind(changed_file),
                )
            )
            for child in node.body:
                visit(child, (*parents, function_name))
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                records.extend(
                    _build_ast_record(
                        path=target_path,
                        qualified_name=name,
                        kind="import",
                        parent=None,
                        start=node.lineno,
                        end=node.end_lineno or node.lineno,
                        touched_lines=touched_lines,
                        include_all=include_all,
                        hunks=changed_file.hunks,
                        side=side,
                        change_kind=_symbol_change_kind(changed_file),
                    )
                )
            return
        if isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            for alias in node.names:
                name = alias.asname or alias.name
                qualified = f"{module_name}.{name}" if module_name else name
                records.extend(
                    _build_ast_record(
                        path=target_path,
                        qualified_name=qualified,
                        kind="import",
                        parent=module_name or None,
                        start=node.lineno,
                        end=node.end_lineno or node.lineno,
                        touched_lines=touched_lines,
                        include_all=include_all,
                        hunks=changed_file.hunks,
                        side=side,
                        change_kind=_symbol_change_kind(changed_file),
                    )
                )
            return
        for child in ast.iter_child_nodes(node):
            visit(child, parents)

    visit(tree)
    return records, None


def _build_ast_record(
    *,
    path: str,
    qualified_name: str,
    kind: str,
    parent: str | None,
    start: int,
    end: int,
    touched_lines: set[int],
    include_all: bool,
    hunks: Sequence[HunkRecord],
    side: Literal["old", "new"],
    change_kind: ChangeKind | None,
) -> list[SymbolRecord]:
    symbol_lines = set(range(start, end + 1))
    overlap = tuple(sorted(symbol_lines & touched_lines))
    if not include_all and not overlap:
        return []
    hunk_ids = _collect_hunk_ids(hunks, symbol_lines, side=side)
    return [
        SymbolRecord(
            path=path,
            qualified_name=qualified_name,
            kind=kind,
            range=SymbolRange(start, end),
            selection_range=SymbolRange(start, start),
            parent=parent,
            touched_lines=(
                overlap if overlap else tuple(sorted(symbol_lines)) if include_all else ()
            ),
            hunk_ids=hunk_ids,
            hunk_hash=_combine_hunk_hashes(hunks, hunk_ids),
            change_kind=change_kind,
            extractor="python_ast",
            confidence="high",
        )
    ]


def _extract_regex_symbols(
    *,
    changed_file: ChangedFileRecord,
    before_text: str | None,
    after_text: str | None,
    error: str | None,
    path_override: str | None = None,
    source_selector: Literal["auto", "before", "after"] = "auto",
) -> list[SymbolRecord]:
    if changed_file.is_binary and not changed_file.hunks:
        return []
    source_text, touched_lines, side, include_all = _symbol_source(
        changed_file, before_text, after_text, source_selector=source_selector
    )
    target_path = path_override or changed_file.display_path
    if source_text is None:
        return []

    source_lines = source_text.splitlines()
    if _is_python_path(target_path):
        return _extract_python_regex_symbols(
            changed_file=changed_file,
            target_path=target_path,
            source_lines=source_lines,
            touched_lines=touched_lines,
            side=side,
            include_all=include_all,
            error=error,
        )

    if _is_js_like_path(target_path):
        return _extract_js_like_regex_symbols(
            changed_file=changed_file,
            target_path=target_path,
            source_lines=source_lines,
            touched_lines=touched_lines,
            side=side,
            include_all=include_all,
            error=error,
        )

    return _extract_generic_regex_symbols(
        changed_file=changed_file,
        target_path=target_path,
        source_lines=source_lines,
        touched_lines=touched_lines,
        side=side,
        include_all=include_all,
        error=error,
    )


def _extract_generic_regex_symbols(
    *,
    changed_file: ChangedFileRecord,
    target_path: str,
    source_lines: Sequence[str],
    touched_lines: set[int],
    side: Literal["old", "new"],
    include_all: bool,
    error: str | None,
) -> list[SymbolRecord]:
    records: list[SymbolRecord] = []
    for line_number, line in enumerate(source_lines, start=1):
        if not include_all and line_number not in touched_lines:
            continue
        for pattern, kind in _REGEX_PATTERNS:
            match = pattern.search(line)
            if match is None:
                continue
            end_line = _infer_regex_end_line(
                source_lines,
                start_line=line_number,
                kind=kind,
                is_python=False,
            )
            symbol_lines = set(range(line_number, end_line + 1))
            overlap = tuple(sorted(symbol_lines & touched_lines))
            hunk_ids = _collect_hunk_ids(changed_file.hunks, symbol_lines, side=side)
            records.append(
                SymbolRecord(
                    path=target_path,
                    qualified_name=match.group(1),
                    kind=kind,
                    range=SymbolRange(line_number, end_line),
                    selection_range=SymbolRange(line_number, line_number),
                    parent=None,
                    touched_lines=(
                        overlap
                        if overlap
                        else tuple(sorted(symbol_lines))
                        if include_all
                        else (line_number,)
                    ),
                    hunk_ids=hunk_ids,
                    hunk_hash=_combine_hunk_hashes(changed_file.hunks, hunk_ids),
                    change_kind=_symbol_change_kind(changed_file),
                    extractor="regex",
                    confidence="medium",
                    error=error,
                )
            )
            break
    return records


def _extract_js_like_regex_symbols(
    *,
    changed_file: ChangedFileRecord,
    target_path: str,
    source_lines: Sequence[str],
    touched_lines: set[int],
    side: Literal["old", "new"],
    include_all: bool,
    error: str | None,
) -> list[SymbolRecord]:
    records: list[SymbolRecord] = []
    for candidate in _qualify_js_like_regex_candidates(source_lines):
        symbol_lines = set(range(candidate.line_number, candidate.end_line + 1))
        overlap = tuple(sorted(symbol_lines & touched_lines))
        if not include_all and not overlap:
            continue
        hunk_ids = _collect_hunk_ids(changed_file.hunks, symbol_lines, side=side)
        records.append(
            SymbolRecord(
                path=target_path,
                qualified_name=candidate.qualified_name or candidate.name,
                kind=candidate.kind,
                range=SymbolRange(candidate.line_number, candidate.end_line),
                selection_range=SymbolRange(candidate.line_number, candidate.line_number),
                parent=candidate.parent,
                touched_lines=(
                    overlap
                    if overlap
                    else tuple(sorted(symbol_lines))
                    if include_all
                    else (candidate.line_number,)
                ),
                hunk_ids=hunk_ids,
                hunk_hash=_combine_hunk_hashes(changed_file.hunks, hunk_ids),
                change_kind=_symbol_change_kind(changed_file),
                extractor="regex",
                confidence="medium",
                error=error,
            )
        )
    return records


def _extract_section_header_symbols(
    changed_file: ChangedFileRecord,
    *,
    before_text: str | None,
    after_text: str | None,
    path_override: str | None = None,
    source_selector: Literal["auto", "before", "after"] = "auto",
) -> list[SymbolRecord]:
    if changed_file.is_binary and not changed_file.hunks:
        return []
    source_text, _, _, _ = _symbol_source(
        changed_file,
        before_text,
        after_text,
        source_selector=source_selector,
    )
    target_path = path_override or changed_file.display_path
    source_lines = source_text.splitlines() if source_text is not None else ()
    records: list[SymbolRecord] = []
    for hunk in changed_file.hunks:
        if not hunk.section_header:
            continue
        name, kind = _symbol_from_section_header(hunk.section_header)
        if name is None:
            continue
        symbol_name, _ = _split_symbol_parent(name)
        start, end = _hunk_range_for_symbol(hunk, changed_file.change_kind)
        touched_lines = (
            hunk.deleted_lines if changed_file.change_kind == "deleted" else hunk.added_lines
        )
        if not touched_lines:
            touched_lines = (
                hunk.context_old_lines
                if changed_file.change_kind == "deleted"
                else hunk.context_new_lines
            )
        parent = _section_header_parent(
            source_lines=source_lines,
            hunk=hunk,
            change_kind=changed_file.change_kind,
            name=name,
        )
        qualified_name = f"{parent}.{symbol_name}" if parent else symbol_name
        records.append(
            SymbolRecord(
                path=target_path,
                qualified_name=qualified_name,
                kind=kind,
                range=SymbolRange(start, end),
                selection_range=SymbolRange(start, start),
                parent=parent,
                touched_lines=touched_lines,
                hunk_ids=(hunk.hunk_id,),
                hunk_hash=hunk.hunk_hash,
                change_kind=_symbol_change_kind(changed_file),
                extractor="section_header",
                confidence="low",
            )
        )
    return records


def _extract_python_regex_symbols(
    *,
    changed_file: ChangedFileRecord,
    target_path: str,
    source_lines: Sequence[str],
    touched_lines: set[int],
    side: Literal["old", "new"],
    include_all: bool,
    error: str | None,
) -> list[SymbolRecord]:
    records: list[SymbolRecord] = []
    for candidate in _qualify_python_regex_candidates(source_lines):
        symbol_lines = set(range(candidate.line_number, candidate.end_line + 1))
        overlap = tuple(sorted(symbol_lines & touched_lines))
        if not include_all and not overlap:
            continue
        hunk_ids = _collect_hunk_ids(changed_file.hunks, symbol_lines, side=side)
        records.append(
            SymbolRecord(
                path=target_path,
                qualified_name=candidate.qualified_name or candidate.name,
                kind=candidate.kind,
                range=SymbolRange(candidate.line_number, candidate.end_line),
                selection_range=SymbolRange(candidate.line_number, candidate.line_number),
                parent=candidate.parent,
                touched_lines=(
                    overlap
                    if overlap
                    else tuple(sorted(symbol_lines))
                    if include_all
                    else (candidate.line_number,)
                ),
                hunk_ids=hunk_ids,
                hunk_hash=_combine_hunk_hashes(changed_file.hunks, hunk_ids),
                change_kind=_symbol_change_kind(changed_file),
                extractor="regex",
                confidence="medium",
                error=error,
            )
        )
    return records


def _qualify_python_regex_candidates(lines: Sequence[str]) -> list[_RegexScopeCandidate]:
    raw_candidates: list[_RegexScopeCandidate] = []
    for line_number, line in enumerate(lines, start=1):
        for pattern, kind in _REGEX_PATTERNS:
            match = pattern.search(line)
            if match is None:
                continue
            raw_candidates.append(
                _RegexScopeCandidate(
                    name=match.group(1),
                    kind=kind,
                    line_number=line_number,
                    end_line=_infer_regex_end_line(
                        lines,
                        start_line=line_number,
                        kind=kind,
                        is_python=True,
                    ),
                    indent=_line_indent(line),
                )
            )
            break

    qualified: list[_RegexScopeCandidate] = []
    for candidate in raw_candidates:
        parent = _enclosing_python_scope_name(
            qualified,
            line_number=candidate.line_number,
            indent=candidate.indent,
        )
        qualified_name = f"{parent}.{candidate.name}" if parent else candidate.name
        qualified.append(
            _RegexScopeCandidate(
                name=candidate.name,
                kind=candidate.kind,
                line_number=candidate.line_number,
                end_line=candidate.end_line,
                indent=candidate.indent,
                parent=parent,
                qualified_name=qualified_name,
            )
        )
    return qualified


def _qualify_js_like_regex_candidates(lines: Sequence[str]) -> list[_RegexScopeCandidate]:
    raw_candidates: list[_RegexScopeCandidate] = []
    for line_number, line in enumerate(lines, start=1):
        matched = _match_regex_candidate(line, _JS_LIKE_TOP_LEVEL_REGEX_PATTERNS)
        if matched is None:
            matched = _match_regex_candidate(line, _JS_LIKE_METHOD_REGEX_PATTERNS)
        if matched is None:
            continue
        name, kind = matched
        if name in _JS_LIKE_NON_SYMBOL_NAMES:
            continue
        raw_candidates.append(
            _RegexScopeCandidate(
                name=name,
                kind=kind,
                line_number=line_number,
                end_line=_infer_js_like_end_line(lines, start_line=line_number, kind=kind),
                indent=_line_indent(line),
            )
        )

    qualified: list[_RegexScopeCandidate] = []
    for candidate in raw_candidates:
        parent = _enclosing_js_like_scope_name(
            qualified,
            line_number=candidate.line_number,
            end_line=candidate.end_line,
        )
        if candidate.kind == "method" and parent is None:
            continue
        qualified_name = f"{parent}.{candidate.name}" if parent else candidate.name
        qualified.append(
            _RegexScopeCandidate(
                name=candidate.name,
                kind=candidate.kind,
                line_number=candidate.line_number,
                end_line=candidate.end_line,
                indent=candidate.indent,
                parent=parent,
                qualified_name=qualified_name,
            )
        )
    return qualified


def _enclosing_python_scope_name(
    scopes: Sequence[_RegexScopeCandidate],
    *,
    line_number: int,
    indent: int,
) -> str | None:
    for scope in reversed(scopes):
        if scope.line_number >= line_number:
            continue
        if scope.indent >= indent:
            continue
        if line_number <= scope.end_line:
            return scope.qualified_name
    return None


def _enclosing_js_like_scope_name(
    scopes: Sequence[_RegexScopeCandidate],
    *,
    line_number: int,
    end_line: int,
) -> str | None:
    for scope in reversed(scopes):
        if scope.kind != "class":
            continue
        if scope.line_number >= line_number:
            continue
        if end_line <= scope.end_line:
            return scope.qualified_name or scope.name
    return None


def _section_header_parent(
    *,
    source_lines: Sequence[str],
    hunk: HunkRecord,
    change_kind: str,
    name: str,
) -> str | None:
    _, qualified_parent = _split_symbol_parent(name)
    if qualified_parent is not None:
        return qualified_parent
    if not source_lines:
        return None
    anchor_line = hunk.old_start if change_kind == "deleted" else hunk.new_start
    if anchor_line < 1 or anchor_line > len(source_lines):
        return None
    inferred = _infer_python_parent_for_line(source_lines, anchor_line)
    if inferred is None:
        return None
    inferred_name, inferred_parent = _split_symbol_parent(inferred)
    symbol_name, _ = _split_symbol_parent(name)
    if _normalize_symbol_name(inferred_name) == _normalize_symbol_name(symbol_name):
        return inferred_parent
    return inferred


def _infer_python_parent_for_line(lines: Sequence[str], line_number: int) -> str | None:
    for candidate in reversed(_qualify_python_regex_candidates(lines)):
        if candidate.line_number < line_number <= candidate.end_line:
            return candidate.qualified_name
    return None


def _symbol_source(
    changed_file: ChangedFileRecord,
    before_text: str | None,
    after_text: str | None,
    *,
    source_selector: Literal["auto", "before", "after"] = "auto",
) -> tuple[str | None, set[int], Literal["old", "new"], bool]:
    if changed_file.change_kind == "deleted" or source_selector == "before":
        text = before_text
        side: Literal["old", "new"] = "old"
        touched_lines = {line for hunk in changed_file.hunks for line in hunk.deleted_lines}
        if not touched_lines:
            touched_lines = {line for hunk in changed_file.hunks for line in hunk.context_old_lines}
    else:
        text = after_text if after_text is not None else before_text
        side = "new"
        touched_lines = {line for hunk in changed_file.hunks for line in hunk.added_lines}
        if not touched_lines:
            touched_lines = {line for hunk in changed_file.hunks for line in hunk.context_new_lines}

    include_all = changed_file.change_kind == "renamed" and not changed_file.hunks
    if include_all and text is not None:
        touched_lines = set(range(1, len(text.splitlines()) + 1))
    return text, touched_lines, side, include_all


def _collect_hunk_ids(
    hunks: Sequence[HunkRecord],
    symbol_lines: set[int],
    *,
    side: Literal["old", "new"],
) -> tuple[str, ...]:
    matched: list[str] = []
    for hunk in hunks:
        hunk_lines = set(hunk.deleted_lines) if side == "old" else set(hunk.added_lines)
        if not hunk_lines:
            hunk_lines = (
                set(hunk.context_old_lines) if side == "old" else set(hunk.context_new_lines)
            )
        if symbol_lines & hunk_lines:
            matched.append(hunk.hunk_id)
    return tuple(dict.fromkeys(matched))


def _combine_hunk_hashes(hunks: Sequence[HunkRecord], hunk_ids: Sequence[str]) -> str:
    if not hunk_ids:
        return ""
    lookup = {hunk.hunk_id: hunk.hunk_hash for hunk in hunks}
    selected = [lookup[hunk_id] for hunk_id in hunk_ids if hunk_id in lookup]
    if len(selected) == 1:
        return selected[0]
    payload = "::".join(sorted(set(selected))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def _symbol_change_kind(changed_file: ChangedFileRecord) -> ChangeKind | None:
    if changed_file.change_kind == "deleted":
        return "deleted"
    if changed_file.change_kind == "renamed":
        return "renamed"
    return None


def _symbol_from_section_header(section_header: str) -> tuple[str | None, str]:
    for pattern, kind in _SECTION_HEADER_PATTERNS:
        match = pattern.search(section_header)
        if match is not None:
            return match.group(1), kind
    cleaned = section_header.strip()
    if not cleaned:
        return None, "symbol"
    return cleaned, "symbol"


def _split_symbol_parent(name: str) -> tuple[str, str | None]:
    normalized = name.replace("::", ".").replace("#", ".")
    parts = [part for part in normalized.split(".") if part]
    if len(parts) <= 1:
        return name, None
    return parts[-1], ".".join(parts[:-1])


def _hunk_range_for_symbol(
    hunk: HunkRecord,
    change_kind: str,
) -> tuple[int, int]:
    if change_kind == "deleted":
        return hunk.old_start, hunk.old_end if hunk.old_end >= hunk.old_start else hunk.old_start
    return hunk.new_start, hunk.new_end if hunk.new_end >= hunk.new_start else hunk.new_start


def _merge_symbol_records(records: Iterable[SymbolRecord]) -> list[SymbolRecord]:
    chosen: dict[tuple[str, str, str | None], SymbolRecord] = {}
    for record in records:
        normalized_name = _normalize_symbol_name(record.qualified_name)
        key = (record.path, normalized_name, record.parent)
        current = chosen.get(key)
        if current is None:
            chosen[key] = record
            continue
        if _PRIORITY[record.extractor] > _PRIORITY[current.extractor]:
            chosen[key] = _merge_symbol_record(record, current)
        else:
            chosen[key] = _merge_symbol_record(current, record)
    return list(chosen.values())


def _merge_symbol_record(primary: SymbolRecord, secondary: SymbolRecord) -> SymbolRecord:
    hunk_ids = tuple(dict.fromkeys((*primary.hunk_ids, *secondary.hunk_ids)))
    touched_lines = tuple(dict.fromkeys((*primary.touched_lines, *secondary.touched_lines)))
    range_start = min(primary.range.start, secondary.range.start)
    range_end = max(primary.range.end, secondary.range.end)
    selection_start = min(primary.selection_range.start, secondary.selection_range.start)
    selection_end = min(primary.selection_range.end, secondary.selection_range.end)
    return SymbolRecord(
        path=primary.path,
        qualified_name=primary.qualified_name,
        kind=primary.kind,
        range=SymbolRange(range_start, range_end),
        selection_range=SymbolRange(selection_start, selection_end),
        parent=primary.parent or secondary.parent,
        touched_lines=touched_lines,
        hunk_ids=hunk_ids,
        hunk_hash=_combine_hash_values(primary.hunk_hash, secondary.hunk_hash),
        change_kind=primary.change_kind or secondary.change_kind,
        extractor=primary.extractor,
        confidence=primary.confidence,
        error=primary.error or secondary.error,
    )


def _combine_hash_values(*values: str) -> str:
    selected = sorted({value for value in values if value})
    if not selected:
        return ""
    if len(selected) == 1:
        return selected[0]
    payload = "::".join(selected).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def _infer_regex_end_line(
    lines: Sequence[str],
    *,
    start_line: int,
    kind: str,
    is_python: bool,
) -> int:
    if not is_python or kind not in {"function", "class"}:
        return start_line
    start_index = start_line - 1
    start_indent = _line_indent(lines[start_index])
    end_line = start_line
    for index in range(start_index + 1, len(lines)):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if not stripped:
            end_line = index + 1
            continue
        if _line_indent(raw_line) <= start_indent and not raw_line.lstrip().startswith("#"):
            break
        end_line = index + 1
    return end_line


def _infer_js_like_end_line(
    lines: Sequence[str],
    *,
    start_line: int,
    kind: str,
) -> int:
    if kind not in {"class", "function", "method"}:
        return start_line
    start_index = start_line - 1
    depth = 0
    started = False
    end_line = start_line
    for index in range(start_index, len(lines)):
        sanitized = _sanitize_js_like_structure_line(lines[index])
        open_count = sanitized.count("{")
        close_count = sanitized.count("}")
        if open_count > 0:
            started = True
            depth += open_count
        if started:
            depth -= close_count
            end_line = index + 1
            if depth <= 0:
                return end_line
            continue
        if index == start_index and "=>" in sanitized and "{" not in sanitized:
            return start_line
    return end_line if started else start_line


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_python_path(path: str) -> bool:
    return path.endswith(".py")


def _is_js_like_path(path: str) -> bool:
    return path.endswith(_JS_LIKE_EXTENSIONS)


def _normalize_symbol_name(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", name).casefold()


def _match_regex_candidate(
    line: str,
    patterns: Sequence[tuple[re.Pattern[str], str]],
) -> tuple[str, str] | None:
    for pattern, kind in patterns:
        match = pattern.search(line)
        if match is not None:
            return match.group(1), kind
    return None


def _sanitize_js_like_structure_line(line: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", "", line)
    without_line_comments = re.sub(r"//.*", "", without_block_comments)
    return _JS_LIKE_STRING_RE.sub("", without_line_comments)


def serialize_symbols_payload(items: Iterable[SymbolRecord]) -> dict[str, Any]:
    return {
        "artifact": "symbols",
        "schema": SYMBOLS_SCHEMA,
        "schema_version": SYMBOLS_SCHEMA_VERSION,
        "symbols": [serialize_symbol_record(item) for item in items],
    }


def serialize_symbol_record(item: SymbolRecord) -> dict[str, Any]:
    return {
        "change_kind": item.change_kind,
        "confidence": item.confidence,
        "error": item.error,
        "extractor": item.extractor,
        "hunk_hash": item.hunk_hash,
        "hunk_ids": list(item.hunk_ids),
        "kind": item.kind,
        "parent": item.parent,
        "path": item.path,
        "qualified_name": item.qualified_name,
        "range": {"start": item.range.start, "end": item.range.end},
        "selection_range": {
            "start": item.selection_range.start,
            "end": item.selection_range.end,
        },
        "touched_lines": list(item.touched_lines),
    }


__all__ = [
    "SymbolExtractor",
    "SymbolRange",
    "SymbolRecord",
    "extract_symbols",
    "serialize_symbols_payload",
    "SYMBOLS_SCHEMA",
    "SYMBOLS_SCHEMA_VERSION",
]
