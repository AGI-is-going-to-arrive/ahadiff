"""DTOs for deterministic serve demo endpoints."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DemoClaimPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    status: Literal["verified", "weak", "not_proven"]
    evidence: str = Field(min_length=1)


class DemoQuizPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1)
    choices: list[str] = Field(min_length=2, max_length=5)
    answer_index: int = Field(ge=0, le=4)

    @model_validator(mode="after")
    def _answer_index_points_to_choice(self) -> Self:
        if self.answer_index >= len(self.choices):
            raise ValueError("answer_index must point to an existing choice")
        return self


class DemoLearnPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locale: Literal["en", "zh-CN"]
    sample_diff: str = Field(min_length=1)
    claims: list[DemoClaimPreview] = Field(min_length=1, max_length=3)
    lesson_snippet: str = Field(min_length=1)
    quiz: DemoQuizPreview


__all__ = ["DemoClaimPreview", "DemoLearnPreviewResponse", "DemoQuizPreview"]
