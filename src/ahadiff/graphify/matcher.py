from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_TOKEN_SPLIT_CHARS = frozenset("_-./\\:() []{}|,;")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _strip_control_chars(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Cc"))


def _normalize(text: str) -> str:
    cleaned = _strip_control_chars(text)
    return unicodedata.normalize("NFKC", cleaned).strip().casefold()


def _tokenize(text: str) -> list[str]:
    nfkc = unicodedata.normalize("NFKC", _strip_control_chars(text)).strip()
    camel_split = _CAMEL_BOUNDARY_RE.sub(" ", nfkc)
    lowered = camel_split.casefold()
    buf: list[str] = []
    current: list[str] = []
    for ch in lowered:
        if ch in _TOKEN_SPLIT_CHARS or ch.isspace():
            if current:
                buf.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        buf.append("".join(current))
    return buf


def _compact_for_containment(text: str) -> str:
    normalized = _normalize(text)
    return "".join(ch for ch in normalized if ch not in _TOKEN_SPLIT_CHARS and not ch.isspace())


def _token_overlap_score(tokens_a: list[str], tokens_b: list[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    intersection = len(set_a & set_b)
    if intersection == 0:
        return 0.0
    return intersection / max(len(set_a), len(set_b))


def similarity(concept: str, label: str) -> float:
    norm_c = _normalize(concept)
    norm_l = _normalize(label)
    if not norm_c or not norm_l:
        return 0.0

    if norm_c == norm_l:
        return 1.0

    concept_tokens = _tokenize(concept)
    label_tokens = _tokenize(label)

    overlap = _token_overlap_score(concept_tokens, label_tokens)

    compact_c = _compact_for_containment(concept)
    compact_l = _compact_for_containment(label)
    if compact_c and compact_l and (compact_c in compact_l or compact_l in compact_c):
        containment = min(len(compact_c), len(compact_l)) / max(
            len(compact_c),
            len(compact_l),
            1,
        )
        overlap = max(overlap, containment)

    return overlap


def match_concepts(
    concept: str,
    candidates: Sequence[str],
    *,
    threshold: float = 0.5,
    max_results: int = 5,
) -> list[tuple[str, float]]:
    if not concept or not concept.strip() or not candidates:
        return []

    scored: list[tuple[str, float]] = []
    for candidate in candidates:
        score = similarity(concept, candidate)
        if score >= threshold:
            scored.append((candidate, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:max_results]


__all__ = ["match_concepts", "similarity"]
