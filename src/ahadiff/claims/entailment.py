"""Deterministic claim predicate entailment for source hunks.

Callers, including the P2 shadow adapter, must represent newly created files by
passing ``before_text_by_path[path] = ""``. Omit a key only when the before text
is genuinely unavailable. An absent key yields
``inconclusive:missing_before_text``; an explicit empty string is evaluated as a
known-empty before state.
"""

from __future__ import annotations

import ast
import hashlib
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

EntailmentApplicability = Literal["applicable", "not_applicable", "inconclusive"]
PredicateOutcome = Literal["supported", "not_supported", "inconclusive"]
ConfidenceBand = Literal["low", "medium"]

CONFIDENCE_LOW: ConfidenceBand = "low"
CONFIDENCE_MEDIUM: ConfidenceBand = "medium"
CONFIDENCE_MEDIUM_THRESHOLD = 0.5


@dataclass(frozen=True)
class PredicateEvidence:
    predicate: str
    outcome: PredicateOutcome
    file: str
    side: str
    start: int
    end: int
    reason: str
    confidence: float
    route_key: str | None = None


class _SourceHunkDTO(Protocol):
    @property
    def file(self) -> str: ...

    @property
    def start(self) -> int: ...

    @property
    def end(self) -> int: ...

    @property
    def side(self) -> str: ...


@dataclass(frozen=True)
class _TextLookupResult:
    text: str | None
    reason: Literal["missing_text", "ambiguous_path_identity"] | None = None


@dataclass(frozen=True)
class _Fact:
    key: str
    start: int
    end: int


@dataclass(frozen=True)
class _AssignmentFact:
    target: str
    literal: str
    start: int
    end: int


@dataclass(frozen=True)
class _AstFacts:
    return_literals: tuple[_Fact, ...]
    call_names: tuple[_Fact, ...]
    imports: tuple[_Fact, ...]
    branches: tuple[_Fact, ...]
    assignments: tuple[_AssignmentFact, ...]


@dataclass(frozen=True)
class _ClaimPredicates:
    return_literals: tuple[str, ...]
    call_names: tuple[str, ...]
    imports: tuple[str, ...]
    wants_branch: bool
    assignment_literals: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not (
            self.return_literals
            or self.call_names
            or self.imports
            or self.wants_branch
            or self.assignment_literals
        )


_IDENTIFIER_RE = r"[^\W\d]\w*"
_DOTTED_IDENTIFIER_RE = rf"{_IDENTIFIER_RE}(?:\.{_IDENTIFIER_RE})*"
_CALL_AFTER_RE = re.compile(rf"\bcall(?:s|ed|ing)?\s+({_DOTTED_IDENTIFIER_RE})", re.IGNORECASE)
_CALL_BEFORE_RE = re.compile(rf"\b({_IDENTIFIER_RE})\s+call\b", re.IGNORECASE)
_CALL_ZH_RE = re.compile(rf"(?:新增|添加)?\s*调用\s+({_DOTTED_IDENTIFIER_RE})")
_FROM_IMPORT_RE = re.compile(rf"\bfrom\s+({_DOTTED_IDENTIFIER_RE})\s+import\b", re.IGNORECASE)
_IMPORT_RE = re.compile(rf"\bimport\s+({_DOTTED_IDENTIFIER_RE})", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
_QUOTED_RE = re.compile(r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)")
_SKIP_CALL_WORDS = frozenset(
    {
        "a",
        "add",
        "added",
        "adds",
        "call",
        "calls",
        "function",
        "method",
        "semantic",
        "proof",
    }
)


def analyze_claim_predicates(
    claim_text: str,
    source_hunks: Sequence[_SourceHunkDTO],
    before_text_by_path: Mapping[str, str],
    after_text_by_path: Mapping[str, str],
) -> tuple[PredicateEvidence, ...]:
    """Evaluate added-code predicates against before/after file text.

    Callers must set ``before_text_by_path[path] = ""`` for newly created files
    and omit ``path`` only when the before text is unavailable. Missing before
    text is reported as ``inconclusive:missing_before_text``; explicit empty
    text is parsed and evaluated as a known-empty before state.
    """

    if not source_hunks:
        return (
            _evidence(
                predicate="applicability",
                outcome="inconclusive",
                file="",
                side="either",
                start=0,
                end=0,
                reason="not_applicable:no_source_hunks",
                confidence=0.0,
            ),
        )

    evidence: list[PredicateEvidence] = []
    claim = _parse_claim_predicates(claim_text)
    for hunk in source_hunks:
        applicability = _path_applicability(hunk.file)
        if applicability != "applicable":
            evidence.append(
                _evidence(
                    predicate="applicability",
                    outcome="inconclusive",
                    file=hunk.file,
                    side=hunk.side,
                    start=hunk.start,
                    end=hunk.end,
                    reason=f"not_applicable:{applicability}",
                    confidence=0.0,
                )
            )
            continue
        if claim.is_empty:
            evidence.append(
                _evidence(
                    predicate="claim",
                    outcome="inconclusive",
                    file=hunk.file,
                    side=hunk.side,
                    start=hunk.start,
                    end=hunk.end,
                    reason="inconclusive:no_supported_predicate",
                    confidence=0.0,
                )
            )
            continue

        if hunk.side != "new":
            evidence.append(_inconclusive_hunk(hunk, "old_side_hunk_not_evaluable"))
            continue

        resolved = _resolve_text(hunk.file, after_text_by_path)
        if resolved.reason == "ambiguous_path_identity":
            evidence.append(_inconclusive_hunk(hunk, "ambiguous_path_identity"))
            continue
        after_text = resolved.text
        if after_text is None:
            evidence.append(_not_applicable_hunk(hunk, "missing_text"))
            continue

        before_resolved = _resolve_text(hunk.file, before_text_by_path)
        if before_resolved.reason == "ambiguous_path_identity":
            evidence.append(_inconclusive_hunk(hunk, "ambiguous_path_identity"))
            continue
        if before_resolved.text is None:
            evidence.append(_inconclusive_hunk(hunk, "missing_before_text"))
            continue
        before_text = before_resolved.text

        parsed = _parse_facts_for_hunk(hunk, before_text=before_text, after_text=after_text)
        if isinstance(parsed, PredicateEvidence):
            evidence.append(parsed)
            continue
        before_facts, after_facts = parsed
        evidence.extend(_evaluate_hunk_claim(hunk, claim, before_facts, after_facts))
    return tuple(evidence)


def _path_applicability(path: str) -> Literal["applicable", "unsafe_path", "non_python_path"]:
    if _is_unsafe_path(path):
        return "unsafe_path"
    if not path.casefold().endswith(".py"):
        return "non_python_path"
    return "applicable"


def _is_unsafe_path(path: str) -> bool:
    if not path or len(path) > 512 or not path.isprintable():
        return True
    if path.startswith("~") or "\\" in path:
        return True
    if path.startswith("/") or path.startswith("//"):
        return True
    if len(path) >= 2 and path[0].isalpha() and path[1] == ":":
        return True
    return any(segment in {"", ".", ".."} for segment in path.split("/"))


def _resolve_text(path: str, mapping: Mapping[str, str]) -> _TextLookupResult:
    if path in mapping:
        return _TextLookupResult(mapping[path])

    target = _path_identity(path)
    if any(_path_identity(candidate) == target for candidate in mapping):
        return _TextLookupResult(None, "ambiguous_path_identity")
    return _TextLookupResult(None, "missing_text")


def confidence_band(value: float) -> ConfidenceBand:
    if math.isfinite(value) and value >= CONFIDENCE_MEDIUM_THRESHOLD:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _path_identity(path: str) -> str:
    return "/".join(segment.casefold() for segment in path.split("/"))


def _parse_claim_predicates(claim_text: str) -> _ClaimPredicates:
    lowered = claim_text.casefold()
    return _ClaimPredicates(
        return_literals=_dedupe(_claim_return_literals(claim_text)),
        call_names=_dedupe(_claim_call_names(claim_text)),
        imports=_dedupe(_claim_imports(claim_text)),
        wants_branch=bool(re.search(r"\b(branch|if|elif|match)\b", lowered)),
        assignment_literals=_dedupe(_claim_assignment_literals(claim_text)),
    )


def _claim_return_literals(claim_text: str) -> tuple[str, ...]:
    if "return" not in claim_text.casefold():
        return ()
    return (*_quoted_literals(claim_text), *_number_literals(claim_text))


def _claim_call_names(claim_text: str) -> tuple[str, ...]:
    names: list[str] = []
    for match in _CALL_AFTER_RE.finditer(claim_text):
        names.append(_normalize_name(match.group(1)))
    for match in _CALL_BEFORE_RE.finditer(claim_text):
        candidate = _normalize_name(match.group(1))
        if candidate.casefold() not in _SKIP_CALL_WORDS:
            names.append(candidate)
    for match in _CALL_ZH_RE.finditer(claim_text):
        names.append(_normalize_name(match.group(1)))
    return tuple(name for name in names if name)


def _claim_imports(claim_text: str) -> tuple[str, ...]:
    imports = [_normalize_import(match.group(1)) for match in _IMPORT_RE.finditer(claim_text)]
    imports.extend(
        _normalize_import(match.group(1)) for match in _FROM_IMPORT_RE.finditer(claim_text)
    )
    return tuple(item for item in imports if item)


def _claim_assignment_literals(claim_text: str) -> tuple[str, ...]:
    lowered = claim_text.casefold()
    if not any(token in lowered for token in ("assign", "assignment", "changes", "changed")):
        return ()
    return (*_quoted_literals(claim_text), *_number_literals(claim_text))


def _quoted_literals(text: str) -> tuple[str, ...]:
    return tuple(f'"{match.group("value")}"' for match in _QUOTED_RE.finditer(text))


def _number_literals(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _NUMBER_RE.finditer(text))


def _parse_facts_for_hunk(
    hunk: _SourceHunkDTO,
    *,
    before_text: str,
    after_text: str,
) -> tuple[_AstFacts, _AstFacts] | PredicateEvidence:
    try:
        before_tree = ast.parse(before_text)
        after_tree = ast.parse(after_text)
    except SyntaxError:
        return _evidence(
            predicate="syntax",
            outcome="inconclusive",
            file=hunk.file,
            side=hunk.side,
            start=hunk.start,
            end=hunk.end,
            reason="partial_syntax",
            confidence=0.0,
        )
    return _extract_facts(before_tree), _extract_facts(after_tree)


def _extract_facts(tree: ast.AST) -> _AstFacts:
    return_literals: list[_Fact] = []
    call_names: list[_Fact] = []
    imports: list[_Fact] = []
    branches: list[_Fact] = []
    assignments: list[_AssignmentFact] = []

    for node in ast.walk(tree):
        span = _node_span(node)
        if span is None:
            continue
        start, end = span
        if isinstance(node, ast.Return):
            literal = _literal_from_node(node.value)
            if literal is not None:
                return_literals.append(_Fact(literal, start, end))
        elif isinstance(node, ast.Call):
            call_name = _call_name(node)
            if call_name:
                call_names.append(_Fact(call_name, start, end))
        elif isinstance(node, ast.Import):
            imports.extend(_Fact(alias.name, start, end) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module:
                imports.append(_Fact(module, start, end))
        elif isinstance(node, ast.If | ast.Match):
            branches.append(_Fact(type(node).__name__.casefold(), start, end))
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            assignment = _assignment_fact(node, start, end)
            if assignment is not None:
                assignments.append(assignment)

    return _AstFacts(
        return_literals=tuple(return_literals),
        call_names=tuple(call_names),
        imports=tuple(imports),
        branches=tuple(branches),
        assignments=tuple(assignments),
    )


def _evaluate_hunk_claim(
    hunk: _SourceHunkDTO,
    claim: _ClaimPredicates,
    before_facts: _AstFacts,
    after_facts: _AstFacts,
) -> tuple[PredicateEvidence, ...]:
    evidence: list[PredicateEvidence] = []
    for literal in claim.return_literals:
        evidence.append(
            _evaluate_added_fact(
                hunk,
                predicate="return_literal_added",
                desired=literal,
                before=before_facts.return_literals,
                after=after_facts.return_literals,
                confidence=0.74,
            )
        )
    for call_name in claim.call_names:
        evidence.append(
            _evaluate_added_fact(
                hunk,
                predicate="call_name_added",
                desired=call_name,
                before=before_facts.call_names,
                after=after_facts.call_names,
                confidence=0.72,
            )
        )
    for imported in claim.imports:
        evidence.append(
            _evaluate_added_fact(
                hunk,
                predicate="import_added",
                desired=imported,
                before=before_facts.imports,
                after=after_facts.imports,
                confidence=0.78,
            )
        )
    if claim.wants_branch:
        evidence.append(_evaluate_branch_added(hunk, before_facts, after_facts))
    for literal in claim.assignment_literals:
        evidence.append(
            _evaluate_assignment_literal_changed(hunk, literal, before_facts, after_facts)
        )
    return tuple(evidence)


def _evaluate_added_fact(
    hunk: _SourceHunkDTO,
    *,
    predicate: str,
    desired: str,
    before: Sequence[_Fact],
    after: Sequence[_Fact],
    confidence: float,
) -> PredicateEvidence:
    route_key = _target_route_key(predicate, desired)
    match = _first_fact_in_hunk(
        after,
        desired=desired,
        hunk_start=hunk.start,
        hunk_end=hunk.end,
    )
    before_match = _first_fact_in_hunk(
        before,
        desired=desired,
        hunk_start=hunk.start,
        hunk_end=hunk.end,
    )
    if match is not None and before_match is None:
        return _evidence(
            predicate=predicate,
            outcome="supported",
            file=hunk.file,
            side=hunk.side,
            start=max(match.start, hunk.start),
            end=min(match.end, hunk.end),
            reason=f"{predicate}:{desired}",
            confidence=confidence,
            route_key=route_key,
        )
    return _evidence(
        predicate=predicate,
        outcome="not_supported",
        file=hunk.file,
        side=hunk.side,
        start=hunk.start,
        end=hunk.end,
        reason=f"{predicate}:not_found_in_hunk",
        confidence=0.2,
        route_key=route_key,
    )


def _evaluate_branch_added(
    hunk: _SourceHunkDTO,
    before_facts: _AstFacts,
    after_facts: _AstFacts,
) -> PredicateEvidence:
    for fact in after_facts.branches:
        if not _overlaps_hunk(fact.start, fact.end, hunk.start, hunk.end):
            continue
        if not _has_same_position_fact(before_facts.branches, fact):
            return _evidence(
                predicate="branch_added",
                outcome="supported",
                file=hunk.file,
                side=hunk.side,
                start=max(fact.start, hunk.start),
                end=min(fact.end, hunk.end),
                reason=f"branch_added:{fact.key}",
                confidence=0.68,
                route_key="branch_added",
            )
    return _evidence(
        predicate="branch_added",
        outcome="not_supported",
        file=hunk.file,
        side=hunk.side,
        start=hunk.start,
        end=hunk.end,
        reason="branch_added:not_found_in_hunk",
        confidence=0.2,
        route_key="branch_added",
    )


def _evaluate_assignment_literal_changed(
    hunk: _SourceHunkDTO,
    literal: str,
    before_facts: _AstFacts,
    after_facts: _AstFacts,
) -> PredicateEvidence:
    route_key = _target_route_key("assignment_literal_changed", literal)
    for fact in after_facts.assignments:
        if fact.literal != literal:
            continue
        if not _overlaps_hunk(fact.start, fact.end, hunk.start, hunk.end):
            continue
        before_match = _same_position_assignment(before_facts.assignments, fact)
        if before_match is not None and before_match.literal != fact.literal:
            return _evidence(
                predicate="assignment_literal_changed",
                outcome="supported",
                file=hunk.file,
                side=hunk.side,
                start=max(fact.start, hunk.start),
                end=min(fact.end, hunk.end),
                reason=f"assignment_literal_changed:{fact.target}={literal}",
                confidence=0.7,
                route_key=route_key,
            )
    return _evidence(
        predicate="assignment_literal_changed",
        outcome="not_supported",
        file=hunk.file,
        side=hunk.side,
        start=hunk.start,
        end=hunk.end,
        reason="assignment_literal_changed:not_found_in_hunk",
        confidence=0.2,
        route_key=route_key,
    )


def _first_fact_in_hunk(
    facts: Sequence[_Fact],
    *,
    desired: str,
    hunk_start: int,
    hunk_end: int,
) -> _Fact | None:
    for fact in facts:
        if fact.key == desired and _overlaps_hunk(
            fact.start,
            fact.end,
            hunk_start,
            hunk_end,
        ):
            return fact
    return None


def _has_same_position_fact(facts: Sequence[_Fact], candidate: _Fact) -> bool:
    return any(
        fact.key == candidate.key and fact.start == candidate.start and fact.end == candidate.end
        for fact in facts
    )


def _same_position_assignment(
    facts: Sequence[_AssignmentFact],
    candidate: _AssignmentFact,
) -> _AssignmentFact | None:
    for fact in facts:
        if (
            fact.target == candidate.target
            and fact.start == candidate.start
            and fact.end == candidate.end
        ):
            return fact
    return None


def _overlaps_hunk(start: int, end: int, hunk_start: int, hunk_end: int) -> bool:
    return start <= hunk_end and end >= hunk_start


def _node_span(node: ast.AST) -> tuple[int, int] | None:
    start = getattr(node, "lineno", None)
    if not isinstance(start, int):
        return None
    end = getattr(node, "end_lineno", start)
    if not isinstance(end, int):
        end = start
    return start, end


def _literal_from_node(node: ast.AST | None) -> str | None:
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "None"
    if isinstance(value, int | float):
        return str(value)
    return None


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _assignment_fact(
    node: ast.Assign | ast.AnnAssign,
    start: int,
    end: int,
) -> _AssignmentFact | None:
    value_node = node.value
    literal = _literal_from_node(value_node)
    if literal is None:
        return None
    target = _assignment_target(node)
    if target is None:
        return None
    return _AssignmentFact(target=target, literal=literal, start=start, end=end)


def _assignment_target(node: ast.Assign | ast.AnnAssign) -> str | None:
    if isinstance(node, ast.AnnAssign):
        return _target_name(node.target)
    for target in node.targets:
        name = _target_name(target)
        if name is not None:
            return name
    return None


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _normalize_name(value: str) -> str:
    return value.rstrip(".,;:").split(".")[-1]


def _normalize_import(value: str) -> str:
    return value.rstrip(".,;:")


def _dedupe(items: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.casefold()
        if item and key not in seen:
            result.append(item)
            seen.add(key)
    return tuple(result)


def _inconclusive_hunk(hunk: _SourceHunkDTO, reason: str) -> PredicateEvidence:
    return _evidence(
        predicate="applicability",
        outcome="inconclusive",
        file=hunk.file,
        side=hunk.side,
        start=hunk.start,
        end=hunk.end,
        reason=f"inconclusive:{reason}",
        confidence=0.0,
    )


def _not_applicable_hunk(hunk: _SourceHunkDTO, reason: str) -> PredicateEvidence:
    return _evidence(
        predicate="applicability",
        outcome="inconclusive",
        file=hunk.file,
        side=hunk.side,
        start=hunk.start,
        end=hunk.end,
        reason=f"not_applicable:{reason}",
        confidence=0.0,
    )


def _evidence(
    *,
    predicate: str,
    outcome: PredicateOutcome,
    file: str,
    side: str,
    start: int,
    end: int,
    reason: str,
    confidence: float,
    route_key: str | None = None,
) -> PredicateEvidence:
    return PredicateEvidence(
        predicate=predicate,
        outcome=outcome,
        file=file,
        side=side,
        start=start,
        end=end,
        reason=reason,
        confidence=confidence,
        route_key=route_key,
    )


def _target_route_key(predicate: str, target: str) -> str:
    digest = hashlib.sha256(target.encode("utf-8", errors="surrogatepass")).hexdigest()[:16]
    return f"{predicate}:{digest}"


__all__ = [
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_MEDIUM_THRESHOLD",
    "ConfidenceBand",
    "EntailmentApplicability",
    "PredicateEvidence",
    "PredicateOutcome",
    "analyze_claim_predicates",
    "confidence_band",
]
