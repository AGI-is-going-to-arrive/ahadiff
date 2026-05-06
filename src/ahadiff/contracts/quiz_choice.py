from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

QuizChoiceLabel: TypeAlias = Literal["A", "B", "C", "D"]
AnswerMode: TypeAlias = Literal["open", "multiple_choice"]

_EXPECTED_LABELS: tuple[QuizChoiceLabel, ...] = ("A", "B", "C", "D")


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _comparison_key(value: str) -> str:
    return _normalize_text(value).casefold()


class QuizChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: QuizChoiceLabel
    text: str = Field(min_length=1)
    is_correct: bool = False

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("choice text must not be empty")
        return normalized


def validate_quiz_choices(
    choices: list[QuizChoice] | tuple[QuizChoice, ...],
    *,
    expected_answer: str | None = None,
) -> tuple[QuizChoice, ...]:
    validated = tuple(choices)
    if len(validated) != len(_EXPECTED_LABELS):
        raise ValueError("quiz choices must contain exactly 4 choices")

    labels = tuple(choice.label for choice in validated)
    if labels != _EXPECTED_LABELS:
        raise ValueError("quiz choice labels must be exactly A, B, C, D in order")

    correct_choices = tuple(choice for choice in validated if choice.is_correct)
    if len(correct_choices) != 1:
        raise ValueError("quiz choices must contain exactly one correct choice")

    text_keys = [_comparison_key(choice.text) for choice in validated]
    if len(set(text_keys)) != len(text_keys):
        raise ValueError("duplicate quiz choice text is not allowed")

    if expected_answer is not None:
        normalized_expected = _normalize_text(expected_answer)
        if not normalized_expected:
            raise ValueError("expected_answer must not be empty when provided")
        if correct_choices[0].text != normalized_expected:
            raise ValueError("correct choice text must match expected_answer")

    return validated


__all__ = [
    "AnswerMode",
    "QuizChoice",
    "QuizChoiceLabel",
    "validate_quiz_choices",
]
