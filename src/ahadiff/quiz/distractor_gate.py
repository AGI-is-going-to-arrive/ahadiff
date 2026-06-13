from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

from ahadiff.core.atomic_replace import replace_with_retry
from ahadiff.core.paths import ensure_state_parent_dir, validate_state_path_no_symlinks
from ahadiff.safety.redact import redaction_pipeline

if TYPE_CHECKING:
    from ahadiff.contracts import QuizChoice

    from .schemas import QuizQuestion

DistractorGateSeverity = Literal["advisory"]
_EvidenceValue = str | int | float | bool | list[str]

_SCHEMA = "ahadiff.quiz_distractor_gate"
_SCHEMA_VERSION = 1
_MAX_IDENTIFIER_LENGTH = 96
_MAX_MESSAGE_LENGTH = 160
_WOULD_BLOCK_LOCKED_REASON = "no_historical_fp_fixture"
_TRAILING_PUNCTUATION = ".,!?;:。！？；："

_ABSOLUTE_PATH_RE = re.compile(
    r"(?:/[^\s\"'`]+(?:/[^\s\"'`]+)+|[A-Za-z]:\\[^\s\"'`]+|\\\\[^\s\"'`]+)"
)
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_JSON_SHAPE_RE = re.compile(r"[\{\}\[\]\"]")
_ALL_NONE_EN_RE = re.compile(
    r"^(?:all|both)\b.*(?:above|of these|of the (?:options|choices))$"
    r"|^both\s+[a-d]\s+and\s+[a-d]$"
    r"|^(?:none|neither)\b.*(?:above|of these|of the (?:options|choices))$"
    r"|^no(?:ne)?\s+of\s+(?:the\s+)?(?:above|these)$",
)
_ALL_NONE_ZH_PHRASES = (
    "以上皆非",
    "以上都不是",
    "以上全错",
    "以上皆是",
    "以上都是",
    "两者都是",
)
_ANSWER_LEAK_RE = re.compile(
    r"\b(?:correct\s+answer|answer\s+is\s+[a-d]|option\s+[a-d]\s+is\s+correct)\b"
    r"|答案\s*(?:是|为)\s*[a-d]",
    re.IGNORECASE,
)
_TRUE_FALSE_KEYS = frozenset(
    {
        "true",
        "false",
        "yes",
        "no",
        "正确",
        "错误",
        "对",
        "错",
        "是",
        "否",
    }
)


class DistractorGateFinding(TypedDict):
    question_id: str
    rule: str
    severity: DistractorGateSeverity
    would_block: bool
    would_block_locked_reason: NotRequired[Literal["no_historical_fp_fixture"]]
    message: str
    evidence: dict[str, _EvidenceValue]


class DistractorGateSummary(TypedDict):
    would_block: int
    advisory: int


class DistractorGateReport(TypedDict):
    schema: str
    schema_version: int
    mode: Literal["advisory"]
    run_id: str
    questions_checked: int
    findings: list[DistractorGateFinding]
    summary: DistractorGateSummary


def build_distractor_gate_report(
    *,
    run_id: str,
    questions: list[QuizQuestion] | tuple[QuizQuestion, ...],
) -> DistractorGateReport:
    findings: list[DistractorGateFinding] = []
    for index, question in enumerate(questions, start=1):
        findings.extend(
            _findings_for_question(
                question,
                question_index=index,
            )
        )
    would_block_count = sum(1 for finding in findings if finding["would_block"])
    return {
        "schema": _SCHEMA,
        "schema_version": _SCHEMA_VERSION,
        "mode": "advisory",
        "run_id": _safe_identifier(run_id, fallback="run"),
        "questions_checked": len(questions),
        "findings": findings,
        "summary": {
            "would_block": would_block_count,
            "advisory": len(findings) - would_block_count,
        },
    }


def write_distractor_gate_report(path: Path, report: DistractorGateReport) -> Path:
    parent = ensure_state_parent_dir(path)
    validate_state_path_no_symlinks(path, allow_missing_leaf=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            validate_state_path_no_symlinks(temp_path, allow_missing_leaf=False)
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        validate_state_path_no_symlinks(path, allow_missing_leaf=True)
        replace_with_retry(temp_path, path)
        temp_path = None
        validate_state_path_no_symlinks(path, allow_missing_leaf=False)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return path


def _findings_for_question(
    question: QuizQuestion,
    *,
    question_index: int,
) -> list[DistractorGateFinding]:
    choices = tuple(question.choices or ())
    if not choices:
        return []
    question_id = _safe_identifier(
        question.question_id or f"question_{question_index}",
        fallback=f"question_{question_index}",
    )
    findings: list[DistractorGateFinding] = []
    duplicate_labels = _duplicate_choice_labels(choices)
    if duplicate_labels:
        findings.append(
            _finding(
                question_id=question_id,
                rule="D1_duplicate_choice_text",
                message="Duplicate choice text detected.",
                evidence={"choice_labels": duplicate_labels},
            )
        )
    all_none_labels = _all_none_choice_labels(choices)
    if all_none_labels:
        findings.append(
            _finding(
                question_id=question_id,
                rule="D2_all_none_phrasing",
                message="All-or-none choice phrasing detected.",
                evidence={"choice_labels": all_none_labels},
            )
        )
    leakage_sources = _answer_leakage_sources(question, choices)
    if leakage_sources:
        findings.append(
            _finding(
                question_id=question_id,
                rule="D3_correct_answer_leakage",
                message="Correct-answer label leakage detected.",
                evidence={"sources": leakage_sources},
            )
        )
    true_false_labels = _true_false_choice_labels(choices)
    if true_false_labels:
        findings.append(
            _finding(
                question_id=question_id,
                rule="D4_true_false_options",
                message="Multiple-choice answers collapse to true/false choices.",
                evidence={"choice_labels": true_false_labels},
            )
        )
    return findings


def _finding(
    *,
    question_id: str,
    rule: str,
    message: str,
    evidence: dict[str, _EvidenceValue],
) -> DistractorGateFinding:
    finding: DistractorGateFinding = {
        "question_id": question_id,
        "rule": rule,
        "severity": "advisory",
        "would_block": False,
        "message": _safe_message(message),
        "evidence": evidence,
    }
    if rule.startswith(("D1_", "D2_")):
        finding["would_block_locked_reason"] = _WOULD_BLOCK_LOCKED_REASON
    return finding


def _duplicate_choice_labels(choices: tuple[QuizChoice, ...]) -> list[str]:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for choice in choices:
        key = _near_duplicate_key(choice.text)
        first_label = seen.get(key)
        if first_label is None:
            seen[key] = choice.label
            continue
        if first_label not in duplicates:
            duplicates.append(first_label)
        duplicates.append(choice.label)
    return _dedupe_labels(duplicates)


def _all_none_choice_labels(choices: tuple[QuizChoice, ...]) -> list[str]:
    labels: list[str] = []
    for choice in choices:
        key = _strip_trailing_punctuation(_comparison_key(choice.text))
        compact_key = _strip_trailing_punctuation(key.replace(" ", ""))
        if _ALL_NONE_EN_RE.search(key) or compact_key in _ALL_NONE_ZH_PHRASES:
            labels.append(choice.label)
    return labels


def _answer_leakage_sources(
    question: QuizQuestion,
    choices: tuple[QuizChoice, ...],
) -> list[str]:
    sources: list[str] = []
    if _has_answer_label_leak(question.question):
        sources.append("question")
    if question.explanation is not None and _has_answer_label_leak(question.explanation):
        sources.append("explanation")
    for choice in choices:
        if choice.is_correct:
            continue
        if _has_answer_label_leak(choice.text):
            sources.append(f"choice_{choice.label}")
    return sources


def _true_false_choice_labels(choices: tuple[QuizChoice, ...]) -> list[str]:
    labels = [
        choice.label for choice in choices if _comparison_key(choice.text) in _TRUE_FALSE_KEYS
    ]
    return labels if len(labels) == len(choices) else []


def _has_answer_label_leak(value: str) -> bool:
    return _ANSWER_LEAK_RE.search(unicodedata.normalize("NFKC", value)) is not None


def _comparison_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.strip().casefold().split())


def _near_duplicate_key(value: str) -> str:
    return _strip_trailing_punctuation(_comparison_key(value))


def _strip_trailing_punctuation(value: str) -> str:
    return value.rstrip(_TRAILING_PUNCTUATION).strip()


def _dedupe_labels(labels: list[str]) -> list[str]:
    return list(dict.fromkeys(labels))


def _safe_identifier(value: str, *, fallback: str) -> str:
    collapsed = " ".join(value.strip().split())
    redacted = _sanitize_text(collapsed, max_length=_MAX_IDENTIFIER_LENGTH)
    if (
        not redacted
        or redacted != collapsed
        or _JSON_SHAPE_RE.search(collapsed)
        or _SAFE_IDENTIFIER_RE.fullmatch(redacted) is None
    ):
        return fallback
    return redacted


def _safe_message(value: str) -> str:
    return _sanitize_text(value, max_length=_MAX_MESSAGE_LENGTH)


def _sanitize_text(value: str, *, max_length: int) -> str:
    text = " ".join(value.split())
    text = redaction_pipeline(text).redacted_text
    text = _ABSOLUTE_PATH_RE.sub("[path omitted]", text)
    if len(text) > max_length:
        return text[:max_length].rstrip() + "..."
    return text


__all__ = [
    "DistractorGateFinding",
    "DistractorGateReport",
    "DistractorGateSeverity",
    "DistractorGateSummary",
    "build_distractor_gate_report",
    "write_distractor_gate_report",
]
