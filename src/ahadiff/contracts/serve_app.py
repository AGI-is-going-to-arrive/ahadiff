from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ahadiff.core.budget import CaptureRecommendation  # noqa: TC001

from . import event_log as event_log_contract
from . import run_source as run_source_contract
from .quiz_choice import AnswerMode, QuizChoice, QuizChoiceLabel  # noqa: TC001

DegradedFlag: TypeAlias = run_source_contract.DegradedFlag
DegradedFlagsMap: TypeAlias = run_source_contract.DegradedFlagsMap
SourceKind: TypeAlias = run_source_contract.SourceKind
RunStatus: TypeAlias = event_log_contract.RunStatus
Verdict: TypeAlias = event_log_contract.Verdict

ReviewAnswer = Literal["easy", "good", "hard", "wrong"]
ReviewQueueState = Literal["archived", "suspended"]
GraphifyMode = Literal["full", "learning_only", "empty"]
LearnEstimateRiskLevel = Literal["ok", "warn", "danger"]


class AuthTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    expires_at: str | None = None


class LocaleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: Literal["en", "zh-CN"]


class CaptureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto", "manual"] = "auto"
    max_files: int = 30
    hard_limit: int = 3000
    max_patch_bytes: int = 5_000_000
    file_ranking: str = "learning_value"
    symbol_extractor: str = "auto"


class LlmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_token_budget: int = 200_000
    output_token_budget: int = 50_000
    request_timeout_seconds: int = 30
    max_concurrent: int = 3
    retry_attempts: int = 3
    output_lang: str = "auto"


class LearnConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    learnability_threshold: float = Field(default=0.3, ge=0.0, le=1.0, allow_inf_nan=False)
    desired_retention: float = Field(default=0.9, ge=0.7, le=0.99, allow_inf_nan=False)


class QuizConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quiz_question_count: StrictInt = Field(default=3, ge=1, le=30)
    quiz_question_count_mode: Literal["fixed", "auto"] = "fixed"
    quiz_auto_range_min: StrictInt = Field(default=3, ge=1, le=30)
    quiz_auto_range_max: StrictInt = Field(default=12, ge=1, le=30)

    @model_validator(mode="after")
    def _validate_auto_range(self) -> QuizConfig:
        if self.quiz_auto_range_min > self.quiz_auto_range_max:
            raise ValueError("quiz_auto_range_min must be <= quiz_auto_range_max")
        return self


class ConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lang: str | None = None
    privacy_mode: str | None = None
    generate_provider: str | None = None
    generate_model: str | None = None
    judge_provider: str | None = None
    judge_model: str | None = None
    serve_port: int | None = None
    key_status: dict[str, Literal["configured", "missing"]] = Field(default_factory=dict)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    learn: LearnConfig = Field(default_factory=LearnConfig)
    quiz: QuizConfig = Field(default_factory=QuizConfig)


class ConfigUpdateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updated: bool
    scope: Literal["session"]


class LearnEstimateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch_bytes: int
    file_count: int
    total_lines: int
    estimated_tokens: int
    provider_context_window: int
    provider_max_output: int | None
    effective_capture_limits: CaptureRecommendation | None = None
    diff_clipped: bool = False
    omitted_files_count: int = 0
    risk_level: LearnEstimateRiskLevel
    warnings: list[str]


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    source_ref: str
    source_kind: SourceKind
    content_lang: Literal["en", "zh-CN"] = "en"
    capability_level: Literal[1, 2, 3]
    verdict: Verdict
    overall: float
    status: RunStatus
    weakest_dim: str
    created_at: str
    degraded_flags: DegradedFlagsMap = Field(
        default_factory=run_source_contract.empty_degraded_flags
    )


class LearnabilityInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    threshold: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    skip_lesson_quiz: bool
    reasons: list[str] = Field(default_factory=list)


class RunDetail(RunSummary):
    model_config = ConfigDict(extra="forbid")

    base_ref: str | None = None
    prompt_version: str
    eval_bundle_version: str
    note_json: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    graphify_mode: GraphifyMode | None = None
    graphify_status: str | None = None
    graphify_notes: list[str] | None = None
    learnability: LearnabilityInfo | None = None


class RunArtifactEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    artifact_type: str
    content: str
    content_lang: Literal["en", "zh-CN"] | None = Field(
        default=None,
        description=(
            "Content language from run metadata.content_lang, normalized to en or zh-CN; "
            "None when missing."
        ),
    )


class RatchetHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    source_ref: str
    eval_bundle_version: str
    overall: float
    verdict: Verdict
    status: RunStatus
    timestamp: str
    weakest_dim: str
    note_json: str | None = None


class DueReviewCardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str = Field(min_length=1)
    concept: str
    run_id: str = Field(min_length=1)
    due_date: str
    scaffolding_level: str
    stability: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    difficulty: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    reps: int = Field(default=0, ge=0)
    lapses: int = Field(default=0, ge=0)
    last_rating: int | None = Field(default=None, ge=1, le=4)
    display_path: str
    source_ref: str | None = None
    symbol: str | None = None
    question: str | None = None
    answer: str | None = None
    answer_mode: AnswerMode = "open"
    choices: list[QuizChoice] | None = None


class ReviewMasteryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept: str
    review_count: int = Field(ge=0)
    avg_rating: float | None = Field(default=None, allow_inf_nan=False)
    last_review: str | None = None


class ReviewMasteryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mastery: list[ReviewMasteryItem]


class SetLocaleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lang: Literal["en", "zh-CN"]


class LearningSignalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1)


class MarkWrongRequest(LearningSignalRequest):
    claim_id: str = Field(min_length=1)
    reason: str | None = None


class ReviewSignalRequest(LearningSignalRequest):
    card_id: str = Field(min_length=1)
    answer: ReviewAnswer
    peeked_this_session: bool = False
    selected_choice_label: QuizChoiceLabel | None = None


class ReviewRateRequest(LearningSignalRequest):
    card_id: str = Field(min_length=1)
    answer: ReviewAnswer
    peeked_this_session: bool = False
    selected_choice_label: QuizChoiceLabel | None = None


class ReviewQueueStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str = Field(min_length=1)
    state: ReviewQueueState


class ReviewQueueStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str = Field(min_length=1)
    state: ReviewQueueState
    updated: bool = True


class QuizAnswerRequest(LearningSignalRequest):
    quiz_id: str
    choice: str
    correct: bool
    selected_choice_label: QuizChoiceLabel | None = None


class HelpfulnessRequest(LearningSignalRequest):
    target_kind: Literal["file", "section"] = "file"
    target_id: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _section_target_id_must_contain_separator(self) -> HelpfulnessRequest:
        if self.target_kind == "section":
            if ":" not in self.target_id:
                raise ValueError(
                    "target_id must contain ':' when target_kind is 'section' "
                    "(expected format: '{run_id}:{section_name}')"
                )
            run_id, section_name = self.target_id.split(":", 1)
            run_id = run_id.strip()
            section_name = section_name.strip()
            if not run_id or not section_name:
                raise ValueError(
                    "target_id must have non-empty run_id and section_name on both sides of ':'"
                )
            self.target_id = f"{run_id}:{section_name}"
        return self


__all__ = [
    "AuthTokenResponse",
    "CaptureConfig",
    "ConfigResponse",
    "LlmConfig",
    "ConfigUpdateResponse",
    "DueReviewCardResponse",
    "GraphifyMode",
    "HelpfulnessRequest",
    "LearnEstimateResponse",
    "LearnEstimateRiskLevel",
    "LearnabilityInfo",
    "LearningSignalRequest",
    "LocaleResponse",
    "MarkWrongRequest",
    "QuizConfig",
    "QuizAnswerRequest",
    "RatchetHistoryEntry",
    "ReviewAnswer",
    "ReviewMasteryItem",
    "ReviewMasteryResponse",
    "ReviewQueueState",
    "ReviewQueueStateRequest",
    "ReviewQueueStateResponse",
    "ReviewRateRequest",
    "ReviewSignalRequest",
    "RunArtifactEnvelope",
    "RunDetail",
    "RunSummary",
    "SetLocaleRequest",
]
