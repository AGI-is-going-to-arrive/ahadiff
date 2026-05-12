"""Deterministic token-based lesson fragment search for MCP ask_lesson.

The search uses literal whitespace + punctuation tokenization (no regex compiled
from user input) and a simple Jaccard-style overlap score. The intent is to give
ask_lesson callers a stable ranking signal grounded in the lesson markdown
without invoking an LLM.
"""

from __future__ import annotations

import string
import unicodedata
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable


_HEADING_PREFIXES: tuple[str, ...] = ("## ", "### ")
_MAX_QUESTION_LENGTH = 512
_DEFAULT_MAX_FRAGMENT_CHARS = 800
_DEFAULT_TOP_K = 3
_MAX_TOP_K = 10
_PUNCTUATION_TRANSLATION = str.maketrans(dict.fromkeys(string.punctuation, " "))

# Small, language-neutral stopword set. Kept short to avoid dropping useful
# tokens; per-CJK script we rely on character-level overlap instead.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
    }
)


def split_lesson_fragments(
    lesson_text: str,
    *,
    max_chars: int = _DEFAULT_MAX_FRAGMENT_CHARS,
) -> list[dict[str, Any]]:
    """Split lesson markdown by ``##`` / ``###`` headings into fragments.

    Returns a list of ``{section_id, heading, body}`` dicts. Each body is
    truncated to at most ``max_chars`` characters. Body text excludes the
    heading line itself. Text before the first heading (preamble) is returned
    as ``section_id`` 0 with heading ``""`` when present.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")
    if not lesson_text:
        return []

    fragments: list[dict[str, Any]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    def flush(heading: str | None) -> None:
        if heading is None and not current_lines:
            return
        body = "\n".join(current_lines).strip()
        if heading is None and not body:
            return
        fragments.append(
            {
                "section_id": len(fragments),
                "heading": heading or "",
                "body": body[:max_chars],
            }
        )

    for raw_line in lesson_text.splitlines():
        line = raw_line.rstrip("\r")
        heading_text = _heading_text(line)
        if heading_text is not None:
            flush(current_heading)
            current_heading = heading_text
            current_lines = []
            continue
        current_lines.append(line)
    flush(current_heading)
    return fragments


def tokenize_query(text: str) -> set[str]:
    """Whitespace + punctuation split with stopword filtering.

    The implementation uses ``str.translate`` and ``str.split`` only — never
    a regex compiled from user input. Unicode characters survive intact; CJK
    runs are kept as a single token so callers can still match against
    heading text that contains the same span.
    """
    if not text:
        return set()
    normalized = unicodedata.normalize("NFKC", text)
    spaced = normalized.translate(_PUNCTUATION_TRANSLATION)
    tokens: set[str] = set()
    for raw_token in spaced.split():
        token = raw_token.strip().casefold()
        if not token:
            continue
        if token in _STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def score_fragments(
    query_tokens: set[str],
    fragments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score each fragment by token overlap with the query.

    Each returned dict copies the input plus a ``score`` (float in [0.0, 1.0])
    and ``matched_tokens`` (sorted list of overlapping tokens). Sorted in
    descending order by score, ties broken by section_id ascending.
    """
    if not fragments:
        return []
    denominator = max(len(query_tokens), 1)
    scored: list[dict[str, Any]] = []
    for fragment in fragments:
        fragment_tokens = tokenize_query(_fragment_text(fragment))
        matched = sorted(query_tokens & fragment_tokens) if query_tokens else []
        score = len(matched) / denominator if query_tokens else 0.0
        enriched: dict[str, Any] = dict(fragment)
        enriched["score"] = float(score)
        enriched["matched_tokens"] = matched
        scored.append(enriched)
    scored.sort(key=lambda item: (-float(item["score"]), int(item.get("section_id", 0))))
    return scored


def search_lesson(
    lesson_text: str,
    question: str,
    *,
    top_k: int = _DEFAULT_TOP_K,
    max_chars: int = _DEFAULT_MAX_FRAGMENT_CHARS,
) -> list[dict[str, Any]]:
    """Split → tokenize → score → return top_k fragments.

    Fragments with a score of 0 are still included up to ``top_k`` so callers
    always see deterministic preamble context when the question has no
    overlap.
    """
    if top_k < 0:
        raise ValueError("top_k must be >= 0")
    bounded_k = min(top_k, _MAX_TOP_K)
    if bounded_k == 0:
        return []
    fragments = split_lesson_fragments(lesson_text, max_chars=max_chars)
    if not fragments:
        return []
    query_tokens = tokenize_query(question)
    scored = score_fragments(query_tokens, fragments)
    return scored[:bounded_k]


def validate_question(question: str) -> str:
    """Strip and validate the user-supplied question.

    Raises ``ValueError`` when the question is empty or longer than
    ``_MAX_QUESTION_LENGTH``.
    """
    stripped = question.strip()
    if not stripped:
        raise ValueError("question is required")
    if len(stripped) > _MAX_QUESTION_LENGTH:
        raise ValueError(f"question exceeds {_MAX_QUESTION_LENGTH} characters")
    return stripped


def bounded_top_k(raw: object, *, default: int = _DEFAULT_TOP_K) -> int:
    """Clamp ``top_k`` between 1 and ``_MAX_TOP_K`` (inclusive)."""
    if isinstance(raw, bool):
        return default
    if not isinstance(raw, int | str):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, _MAX_TOP_K))


def evidence_for_fragments(
    fragments: Iterable[dict[str, Any]],
    claims: Iterable[dict[str, Any]],
    *,
    per_fragment_limit: int = 10,
    total_limit: int = 30,
    min_matched_tokens: int = 1,
) -> list[dict[str, Any]]:
    """Join claim records to fragment headings via shared token overlap.

    Each output entry contains ``section_id``, ``claim_id``, ``status``,
    ``confidence``, ``text``, ``source_hunks`` (truncated to the first 5 by
    ``hunk_id``), ``matched_tokens``, and ``score`` (matched / claim tokens).

    Evidence is sorted by descending score and capped at
    ``per_fragment_limit`` entries per fragment and ``total_limit`` overall.
    A claim can appear under multiple fragments if it independently passes
    the threshold for each.
    """
    fragment_token_sets: list[tuple[int, set[str]]] = []
    for fragment in fragments:
        heading = str(fragment.get("heading", ""))
        body = str(fragment.get("body", ""))
        tokens = tokenize_query(heading) | tokenize_query(body)
        if not tokens:
            continue
        fragment_token_sets.append((int(fragment.get("section_id", 0) or 0), tokens))

    bucket: dict[int, list[dict[str, Any]]] = {}
    for claim in claims:
        claim_text = str(claim.get("text", ""))
        claim_tokens = tokenize_query(claim_text)
        if not claim_tokens:
            continue
        for section_id, fragment_tokens in fragment_token_sets:
            matched = sorted(claim_tokens & fragment_tokens)
            if len(matched) < min_matched_tokens:
                continue
            score = len(matched) / max(len(claim_tokens), 1)
            source_hunks = _truncate_source_hunks(claim.get("source_hunks"))
            primary_hunk = source_hunks[0] if source_hunks else {}
            bucket.setdefault(section_id, []).append(
                {
                    "section_id": section_id,
                    "claim_id": str(claim.get("claim_id", "")),
                    "status": str(claim.get("status", "")),
                    "confidence": str(claim.get("confidence", "")),
                    "text": claim_text,
                    "file": str(primary_hunk.get("file", "")),
                    "line_start": int(primary_hunk.get("start", 0)),
                    "line_end": int(primary_hunk.get("end", 0)),
                    "hunk_hash": str(primary_hunk.get("hunk_hash", "")),
                    "source_hunks": source_hunks,
                    "matched_tokens": matched,
                    "score": float(score),
                }
            )

    evidence: list[dict[str, Any]] = []
    for section_id in sorted(bucket):
        ranked = sorted(
            bucket[section_id],
            key=lambda item: (-float(item["score"]), str(item["claim_id"])),
        )
        evidence.extend(ranked[:per_fragment_limit])
    return evidence[:total_limit]


def _heading_text(line: str) -> str | None:
    for prefix in _HEADING_PREFIXES:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _fragment_text(fragment: dict[str, Any]) -> str:
    heading = str(fragment.get("heading", ""))
    body = str(fragment.get("body", ""))
    if heading and body:
        return f"{heading}\n{body}"
    return heading or body


def _truncate_source_hunks(raw: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    hunks: list[dict[str, Any]] = []
    items: list[Any] = list(raw)  # type: ignore[arg-type]
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = item  # type: ignore[assignment]
        hunks.append(
            {
                "file": str(entry.get("file") or entry.get("display_path", "")),
                "start": _safe_hunk_int(entry.get("start", entry.get("line_start", 0))),
                "end": _safe_hunk_int(entry.get("end", entry.get("line_end", 0))),
                "side": str(entry.get("side", "")),
                "hunk_id": str(entry.get("hunk_id", "")),
                "hunk_hash": str(entry.get("hunk_hash", "")),
            }
        )
    return hunks


def _safe_hunk_int(raw: object) -> int:
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return max(raw, 0)
    if not isinstance(raw, float | str):
        return 0
    try:
        value = int(raw or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(value, 0)


MAX_QUESTION_LENGTH = _MAX_QUESTION_LENGTH
DEFAULT_TOP_K = _DEFAULT_TOP_K
MAX_TOP_K = _MAX_TOP_K
DEFAULT_MAX_FRAGMENT_CHARS = _DEFAULT_MAX_FRAGMENT_CHARS

__all__ = [
    "DEFAULT_MAX_FRAGMENT_CHARS",
    "DEFAULT_TOP_K",
    "MAX_QUESTION_LENGTH",
    "MAX_TOP_K",
    "bounded_top_k",
    "evidence_for_fragments",
    "score_fragments",
    "search_lesson",
    "split_lesson_fragments",
    "tokenize_query",
    "validate_question",
]
