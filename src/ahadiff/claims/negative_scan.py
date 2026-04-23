from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ahadiff.core.paths import path_identity_key

from .schema import NegativeEvidence

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ahadiff.contracts import SourceHunk
    from ahadiff.git.symbols import SymbolRecord


_RISKY_GENERALIZATION_RE = re.compile(
    r"\b(always|never|faster|fastest|secure|safer|guarantee[sd]?|prevent[sd]?|ensure[sd]?)\b",
    re.IGNORECASE,
)
_RETRY_RE = re.compile(r"\b(retry|retries|backoff)\b", re.IGNORECASE)
_TEST_RE = re.compile(r"\b(test|assert)\b", re.IGNORECASE)
_IMPORT_RE = re.compile(r"\b(import|dependency|dependencies)\b", re.IGNORECASE)
_SECURITY_RE = re.compile(r"\b(secure|security|sanitize|escape|redact|allowlist)\b", re.IGNORECASE)
_DELETION_ACK_RE = re.compile(r"\b(delete[sd]?|remove[sd]?|rename[sd]?)\b", re.IGNORECASE)
_SECURITY_STRUCTURE_RE = re.compile(
    r"\b(redact|sanitize|escape|allowlist|guard|secret|token|permission|auth)\b",
    re.IGNORECASE,
)


def scan_negative_evidence(
    claim_text: str,
    *,
    source_hunks: Sequence[SourceHunk],
    matched_symbols: Sequence[SymbolRecord],
    before_text_by_path: Mapping[str, str],
    after_text_by_path: Mapping[str, str],
) -> tuple[NegativeEvidence, ...]:
    evidences: list[NegativeEvidence] = []
    normalized_claim = claim_text.casefold()
    for symbol in matched_symbols:
        if symbol.change_kind == "deleted" and not _DELETION_ACK_RE.search(normalized_claim):
            evidences.append(
                NegativeEvidence(
                    code="deleted_symbol_reference",
                    detail=symbol.qualified_name,
                    path=symbol.path,
                )
            )

    texts = [
        (
            source_hunk.file,
            _resolve_text_for_source_hunk(
                source_hunk,
                before_text_by_path,
                after_text_by_path,
            ),
        )
        for source_hunk in source_hunks
    ]
    available_texts = [text for _, text in texts if text is not None]
    if available_texts:
        if _RETRY_RE.search(claim_text) and not any(
            _has_retry_structure(text) for text in available_texts
        ):
            evidences.append(
                NegativeEvidence(code="missing_retry_structure", detail="retry markers absent")
            )
        if _TEST_RE.search(claim_text) and not any(
            _has_test_structure(text) for text in available_texts
        ):
            evidences.append(
                NegativeEvidence(
                    code="missing_test_structure",
                    detail="assert/test markers absent",
                )
            )
        if _IMPORT_RE.search(claim_text) and not any(
            _has_import_structure(text) for text in available_texts
        ):
            evidences.append(
                NegativeEvidence(code="missing_import_structure", detail="import statements absent")
            )
        if _SECURITY_RE.search(claim_text) and not any(
            _has_security_structure(text) for text in available_texts
        ):
            evidences.append(
                NegativeEvidence(
                    code="missing_security_structure",
                    detail="security related structure absent",
                )
            )
    if _RISKY_GENERALIZATION_RE.search(claim_text) and not matched_symbols:
        evidences.append(
            NegativeEvidence(
                code="risky_generalization_without_symbol_support",
                detail="risky wording without symbol support",
            )
        )
    deduped: dict[str, NegativeEvidence] = {}
    for evidence in evidences:
        deduped.setdefault(evidence.render(), evidence)
    return tuple(deduped.values())


def _resolve_text_for_source_hunk(
    source_hunk: SourceHunk,
    before_text_by_path: Mapping[str, str],
    after_text_by_path: Mapping[str, str],
) -> str | None:
    identity = _identity(source_hunk.file)
    if source_hunk.side == "old":
        ordered_lookups = (before_text_by_path, after_text_by_path)
    elif source_hunk.side == "new":
        ordered_lookups = (after_text_by_path, before_text_by_path)
    else:
        ordered_lookups = (after_text_by_path, before_text_by_path)
    for lookup in ordered_lookups:
        for candidate_path, text in lookup.items():
            if _identity(candidate_path) == identity:
                return text
    return None


def _has_retry_structure(text: str) -> bool:
    parsed = _safe_parse_python(text)
    if parsed is not None:
        if any(isinstance(node, ast.Try) for node in ast.walk(parsed)):
            return True
        call_names = {_call_name(node) for node in ast.walk(parsed) if isinstance(node, ast.Call)}
        if any(name in {"retry", "backoff", "sleep"} for name in call_names):
            return True
    lowered = text.casefold()
    return any(token in lowered for token in ("retry", "backoff", "sleep", "attempt"))


def _has_test_structure(text: str) -> bool:
    parsed = _safe_parse_python(text)
    if parsed is not None:
        if any(isinstance(node, ast.Assert) for node in ast.walk(parsed)):
            return True
        return any(
            isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
            for node in ast.walk(parsed)
        )
    lowered = text.casefold()
    return "assert" in lowered or "test_" in lowered


def _has_import_structure(text: str) -> bool:
    parsed = _safe_parse_python(text)
    if parsed is not None:
        return any(isinstance(node, ast.Import | ast.ImportFrom) for node in ast.walk(parsed))
    lowered = text.casefold()
    return "\nimport " in lowered or "\nfrom " in lowered


def _has_security_structure(text: str) -> bool:
    return bool(_SECURITY_STRUCTURE_RE.search(text))


def _safe_parse_python(text: str) -> ast.AST | None:
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id.casefold()
    if isinstance(func, ast.Attribute):
        return func.attr.casefold()
    return ""


def _identity(path: str) -> str:
    return path_identity_key(Path(path))


__all__ = ["scan_negative_evidence"]
