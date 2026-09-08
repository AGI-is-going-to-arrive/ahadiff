"""Read verified, immutable card provenance without opening or migrating a database.

Older cards retain their original export contract. New source-evidence runs must
have a complete finalized artifact set before their sources can leave the run.
"""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import ValidationError

from ahadiff.contracts import ReviewCard
from ahadiff.contracts.quiz_choice import AnswerMode, QuizChoice  # noqa: TC001
from ahadiff.contracts.source_anchor import SourceAnchor  # noqa: TC001
from ahadiff.eval.results import finalized_artifact_digest
from ahadiff.quiz.schemas import ExerciseKind, QuizQuestion  # noqa: TC001

from .errors import AhaDiffError, InputError
from .json_util import safe_json_loads
from .learn_inputs import read_learning_text
from .paths import validate_run_id, validate_state_path_no_symlinks
from .source_evidence import (
    load_evidence_anchors,
    load_review_context,
    load_run_source_text,
    validate_source_anchor_references,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_MARKER_BYTES = 64 * 1024
_MAX_QUIZ_QUESTIONS = 30
_MAX_SOURCE_CARDS = 10_000
_NEW_SOURCE_ARTIFACTS = ("document.md", "evidence_anchors.json", "review_context.json")


@dataclass(frozen=True)
class CardSourceDetails:
    source_kind: str
    source_ref: str
    question_id: str | None
    exercise_kind: ExerciseKind | None
    source_anchors: tuple[SourceAnchor, ...]
    review_context_used: bool
    review_context_hash: str | None
    content_lang: Literal["en", "zh-CN"]
    # Explicit exports can use these immutable texts. Public practice prompts
    # must allowlist fields and must not project the reference answer.
    question: str
    answer: str
    answer_mode: AnswerMode
    choices: tuple[QuizChoice, ...] | None


def _exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def declares_source_artifacts(run_path: Path, metadata: Mapping[str, Any]) -> bool:
    """Detect declarations by presence, including malformed or orphaned new fields."""
    return (
        "source_evidence_version" in metadata
        or "evidence_anchors_hash" in metadata
        or metadata.get("source_kind") == "document"
        or metadata.get("review_context_used") is True
        or "review_context_hash" in metadata
        or any(_exists(run_path / name) for name in _NEW_SOURCE_ARTIFACTS)
    )


def _guard_directory(path: Path) -> None:
    validate_state_path_no_symlinks(path, allow_missing_leaf=False)
    value = path.lstat()
    if not stat.S_ISDIR(value.st_mode):
        raise InputError("card source parent must be a directory")


def _read_text(run_path: Path, relative: str, *, max_bytes: int = _MAX_ARTIFACT_BYTES) -> str:
    try:
        path = run_path / relative
        validate_state_path_no_symlinks(path, allow_missing_leaf=False)
        return read_learning_text(run_path, path, max_bytes=max_bytes)
    except (AhaDiffError, OSError):
        raise InputError(f"card source artifact is missing or unsafe: {relative}") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate artifact field")
        result[key] = value
    return result


def _parse_json(text: str) -> object:
    return cast(
        "object",
        safe_json_loads(
            text, max_input_bytes=_MAX_ARTIFACT_BYTES, object_pairs_hook=_unique_object
        ),
    )


def _read_object(
    run_path: Path, relative: str, *, max_bytes: int = _MAX_ARTIFACT_BYTES
) -> dict[str, Any]:
    try:
        value = _parse_json(_read_text(run_path, relative, max_bytes=max_bytes))
    except (ValueError, RecursionError):
        raise InputError(f"card source artifact is invalid: {relative}") from None
    if not isinstance(value, dict):
        raise InputError(f"card source artifact must be an object: {relative}")
    return cast("dict[str, Any]", value)


def require_finalized_source(run_path: Path, metadata: Mapping[str, Any]) -> None:
    """Require actual artifact checksums for new sources; leave old markers compatible."""
    if not declares_source_artifacts(run_path, metadata):
        return
    _guard_directory(run_path)
    if metadata.get("run_id") != run_path.name:
        raise InputError("card source run identity mismatch")
    if _read_object(run_path, "metadata.json") != dict(metadata):
        raise InputError("card source metadata changed during read")
    marker = _read_object(run_path, "finalized.json", max_bytes=_MAX_MARKER_BYTES)
    expected_count = marker.get("artifact_count")
    expected_checksum = marker.get("checksum")
    if (
        marker.get("run_id") != run_path.name
        or type(expected_count) is not int
        or expected_count <= 0
        or not isinstance(expected_checksum, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_checksum) is None
    ):
        raise InputError("card source finalized marker is invalid")
    actual_count, actual_checksum = finalized_artifact_digest(run_path)
    _guard_directory(run_path)
    if (actual_count, actual_checksum) != (expected_count, expected_checksum):
        raise InputError("card source finalized artifact checksum mismatch")


def _load_questions(run_path: Path) -> dict[str, QuizQuestion]:
    questions: dict[str, QuizQuestion] = {}
    seen_ids: set[str] = set()
    try:
        for line in _read_text(run_path, "quiz/quiz.jsonl").splitlines():
            if not line.strip():
                continue
            question = QuizQuestion.model_validate(_parse_json(line))
            if not question.question_id or question.question_id in seen_ids:
                raise ValueError("missing or duplicate question identity")
            seen_ids.add(question.question_id)
            if len(seen_ids) > _MAX_QUIZ_QUESTIONS:
                raise ValueError("too many quiz questions")
            if question.review_card_id is not None:
                if question.review_card_id in questions:
                    raise ValueError("duplicate review card identity")
                questions[question.review_card_id] = question
    except (ValidationError, ValueError, RecursionError):
        raise InputError("card source quiz artifact is invalid") from None
    return questions


def _load_cards(run_path: Path) -> tuple[ReviewCard, ...]:
    cards: list[ReviewCard] = []
    seen: set[str] = set()
    try:
        for line in _read_text(run_path, "quiz/cards.jsonl").splitlines():
            if not line.strip():
                continue
            card = ReviewCard.model_validate(_parse_json(line))
            if card.card_id in seen or len(cards) >= _MAX_SOURCE_CARDS:
                raise ValueError("duplicate or excessive cards")
            seen.add(card.card_id)
            cards.append(card)
    except (ValidationError, ValueError, RecursionError):
        raise InputError("card source cards artifact is invalid") from None
    if not cards:
        raise InputError("card source cards artifact is empty")
    return tuple(cards)


def _card_anchors(
    card: ReviewCard, question: QuizQuestion, available: tuple[SourceAnchor, ...], *, document: bool
) -> tuple[SourceAnchor, ...]:
    known: dict[str, SourceAnchor] = {}
    for requested in (card.source_anchors, question.source_anchors):
        if requested and not validate_source_anchor_references(requested, available):
            raise InputError("card source anchor does not match persisted source evidence")
        for anchor in requested:
            known[anchor.anchor_id] = anchor
    if document and not known:
        raise InputError("document review card has no document evidence")
    return tuple(known.values())


def load_card_sources(state_dir: Path, run_id: str) -> dict[str, CardSourceDetails]:
    """Load one run only. Callers should discard this mapping before loading another."""
    validate_run_id(run_id)
    validate_state_path_no_symlinks(state_dir, allow_missing_leaf=True)
    run_path = state_dir / "runs" / run_id
    validate_state_path_no_symlinks(run_path, allow_missing_leaf=True)
    if not _exists(run_path):
        return {}
    _guard_directory(run_path)
    if not _exists(run_path / "metadata.json"):
        if declares_source_artifacts(run_path, {}):
            raise InputError("card source metadata is missing")
        return {}
    metadata = _read_object(run_path, "metadata.json")
    if not declares_source_artifacts(run_path, metadata):
        return {}
    if (
        type(metadata.get("source_evidence_version")) is not int
        or metadata.get("source_evidence_version") != 1
    ):
        raise InputError("unsupported card source evidence version")
    source_kind = metadata.get("source_kind")
    source_ref = metadata.get("source_ref")
    content_lang = metadata.get("content_lang")
    if (
        not isinstance(source_kind, str)
        or not source_kind
        or not isinstance(source_ref, str)
        or not source_ref
        or not isinstance(content_lang, str)
        or content_lang not in {"en", "zh-CN"}
    ):
        raise InputError("card source metadata is invalid")
    require_finalized_source(run_path, metadata)
    # Validate source quotes and their locator-derived identities before exact
    # membership checks. The canonical patch/document is required even for an
    # empty index; this does not re-run each format parser on stored locators.
    load_run_source_text(run_path, metadata)
    anchors = load_evidence_anchors(run_path, metadata)
    auxiliary = load_review_context(run_path, metadata)
    questions = _load_questions(run_path)
    cards = _load_cards(run_path)
    if set(questions) != {card.card_id for card in cards}:
        raise InputError("card source card and quiz membership mismatch")
    result: dict[str, CardSourceDetails] = {}
    for card in cards:
        question = questions.get(card.card_id)
        if (
            card.run_id != run_id
            or card.source_ref != source_ref
            or question is None
            or card.question != question.question
            or card.answer != question.expected_answer
            or card.answer_mode != question.answer_mode
            or card.choices != question.choices
        ):
            raise InputError("card source card and quiz identity or text mismatch")
        result[card.card_id] = CardSourceDetails(
            source_kind=source_kind,
            source_ref=source_ref,
            question_id=question.question_id,
            exercise_kind=question.exercise_kind,
            source_anchors=_card_anchors(
                card, question, anchors, document=source_kind == "document"
            ),
            review_context_used=auxiliary is not None,
            review_context_hash=auxiliary.content_hash if auxiliary else None,
            content_lang=cast("Literal['en', 'zh-CN']", content_lang),
            question=question.question,
            answer=question.expected_answer,
            answer_mode=question.answer_mode,
            choices=tuple(question.choices) if question.choices is not None else None,
        )
    require_finalized_source(run_path, metadata)
    return result


__all__ = [
    "CardSourceDetails",
    "declares_source_artifacts",
    "load_card_sources",
    "require_finalized_source",
]
