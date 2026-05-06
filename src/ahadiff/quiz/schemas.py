from __future__ import annotations

import json
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from ahadiff.contracts.quiz_choice import AnswerMode, QuizChoice, validate_quiz_choices


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _normalize_string_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        line = _normalize_text(value)
        if line:
            normalized.append(line)
    return list(dict.fromkeys(normalized))


class QuizEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    line: StrictInt

    @field_validator("file")
    @classmethod
    def validate_file(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("evidence file must not be empty")
        return normalized

    @field_validator("line")
    @classmethod
    def validate_line(cls, value: int) -> int:
        if value < 1:
            raise ValueError("evidence line must be positive")
        return value


class QuizQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str | None = None
    review_card_id: str | None = None
    question: str
    expected_answer: str
    answer_mode: AnswerMode = "open"
    choices: list[QuizChoice] | None = None
    source_claims: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    evidence: list[QuizEvidence]
    explanation: str | None = None

    @model_validator(mode="before")
    @classmethod
    def infer_answer_mode(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data_map = cast("dict[str, Any]", data)
        if (
            "answer_mode" not in data_map
            and "choices" in data_map
            and data_map.get("choices") is not None
        ):
            return {**data_map, "answer_mode": "multiple_choice"}
        return data_map

    @field_validator("question", "expected_answer")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("quiz question text must not be empty")
        return normalized

    @field_validator("question_id", "review_card_id")
    @classmethod
    def normalize_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("source_claims", "concepts")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return _normalize_string_list(values)

    @field_validator("explanation")
    @classmethod
    def normalize_explanation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_text(value)
        return normalized or None

    @model_validator(mode="after")
    def validate_links_and_choices(self) -> QuizQuestion:
        if not self.source_claims:
            raise ValueError("quiz question must link to at least one source claim")
        if not self.evidence:
            raise ValueError("quiz question must include at least one evidence anchor")
        if self.choices is None:
            if self.answer_mode == "multiple_choice":
                raise ValueError("multiple_choice quiz questions must include choices")
            return self
        if self.answer_mode != "multiple_choice":
            raise ValueError("quiz choices are only allowed for multiple_choice questions")
        self.choices = list(
            validate_quiz_choices(self.choices, expected_answer=self.expected_answer)
        )
        return self


class QuizSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[QuizQuestion]

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, values: list[QuizQuestion]) -> list[QuizQuestion]:
        if not values:
            raise ValueError("quiz set must contain at least one question")
        return values


def parse_quiz_payload(payload: str, *, require_choices: bool = False) -> QuizSet:
    last_error: Exception | None = None
    for candidate in _extract_json_candidates(payload):
        try:
            if isinstance(candidate, list):
                return _validate_required_choices(
                    QuizSet.model_validate({"questions": candidate}),
                    require_choices=require_choices,
                )
            if isinstance(candidate, dict):
                candidate_map = cast("dict[str, Any]", candidate)
                if "questions" in candidate_map:
                    return _validate_required_choices(
                        QuizSet.model_validate(candidate_map),
                        require_choices=require_choices,
                    )
                required_keys = {"question", "expected_answer", "source_claims", "evidence"}
                if required_keys <= set(candidate_map.keys()):
                    return _validate_required_choices(
                        QuizSet.model_validate({"questions": [candidate_map]}),
                        require_choices=require_choices,
                    )
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise ValueError("payload does not contain a valid quiz JSON object")


def _validate_required_choices(quiz_set: QuizSet, *, require_choices: bool) -> QuizSet:
    if not require_choices:
        return quiz_set
    for question in quiz_set.questions:
        if question.answer_mode != "multiple_choice" or not question.choices:
            raise ValueError("quiz payload must include choices for every question")
    return quiz_set


def _extract_json_candidates(payload: str) -> tuple[Any, ...]:
    stripped = payload.strip()
    decoder = json.JSONDecoder()
    candidates = [*_iter_fenced_blocks(stripped), stripped]
    parsed_candidates: list[Any] = []
    for candidate in candidates:
        parsed_candidates.extend(_decode_json_values(candidate, decoder))
    return tuple(parsed_candidates)


def _iter_fenced_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    in_fence = False
    fence_lines: list[str] = []
    for line in text.splitlines():
        marker = line.strip()
        if not in_fence and marker.startswith("```"):
            in_fence = True
            fence_lines = []
            continue
        if in_fence and marker == "```":
            block = "\n".join(fence_lines).strip()
            if block:
                blocks.append(block)
            in_fence = False
            fence_lines = []
            continue
        if in_fence:
            fence_lines.append(line)
    return blocks


def _decode_json_values(text: str, decoder: json.JSONDecoder) -> list[Any]:
    values: list[Any] = []
    for index, character in enumerate(text):
        if character not in {"{", "["}:
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        values.append(parsed)
    return values


__all__ = ["QuizEvidence", "QuizQuestion", "QuizSet", "parse_quiz_payload"]
