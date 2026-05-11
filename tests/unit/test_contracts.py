"""Stage 0 acceptance for the importable contracts surface."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Any, cast, get_args

import pytest
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ahadiff.contracts.serve_app import (  # noqa: E402
    DueReviewCardResponse,
    QuizAnswerRequest,
    ReviewRateRequest,
    ReviewSignalRequest,
)


class TestContractsImport:
    def test_wildcard_import(self) -> None:
        namespace: dict[str, object] = {}
        exec("from ahadiff.contracts import *", namespace)
        assert "RunSource" in namespace
        assert "ProviderCapabilities" in namespace
        assert "UsageEvent" in namespace
        assert "LearnabilityGate" in namespace

    def test_key_types_importable(self) -> None:
        from ahadiff.contracts import (
            AllowlistPolicy,
            AuthTokenResponse,
            ClaimRecord,
            ClaimStatus,
            ConfigResponse,
            InputError,
            LearnabilityGate,
            OrchestratorCommand,
            OrchestratorResult,
            ProviderCapabilities,
            ProviderConfig,
            QuizAnswerRequest,
            RatchetHistoryEntry,
            ResultEvent,
            ReviewCard,
            ReviewMasteryResponse,
            RunConfig,
            RunDetail,
            RunSource,
            RunSummary,
            ServeConfig,
            SetLocaleRequest,
            SpecAlignmentResponse,
            UsageEvent,
            WatchStatusResponse,
        )

        assert ClaimStatus
        assert ClaimRecord
        assert ReviewCard
        assert RunSource
        assert ProviderConfig
        assert QuizAnswerRequest
        assert ProviderCapabilities
        assert AllowlistPolicy
        assert ResultEvent
        assert UsageEvent
        assert LearnabilityGate
        assert OrchestratorCommand
        assert OrchestratorResult
        assert RunConfig
        assert ServeConfig
        assert AuthTokenResponse
        assert RunSummary
        assert RunDetail
        assert RatchetHistoryEntry
        assert SetLocaleRequest
        assert ConfigResponse
        assert ReviewMasteryResponse
        assert SpecAlignmentResponse
        assert WatchStatusResponse
        assert InputError

    def test_error_code_status_mapping_is_complete(self) -> None:
        from ahadiff.contracts import ERROR_STATUS, ErrorCode

        assert set(ERROR_STATUS) == set(ErrorCode)
        assert ERROR_STATUS[ErrorCode.AUTH_REQUIRED] == 401
        assert ERROR_STATUS[ErrorCode.LOOPBACK_DENIED] == 403
        assert ERROR_STATUS[ErrorCode.INPUT_VALIDATION] == 422
        assert ERROR_STATUS[ErrorCode.LOCK_CONFLICT] == 409
        assert ERROR_STATUS[ErrorCode.FEATURE_UNAVAILABLE] == 501


class TestSerialization:
    def test_run_source_roundtrip(self) -> None:
        from ahadiff.contracts import RunSource

        source = RunSource(
            source_kind="git_ref",
            source_ref="abc1234",
            capability_level=3,
            degraded_flags={"token_exceeded": True},
        )
        assert RunSource.model_validate(source.model_dump()) == source

    def test_run_summary_includes_capability_level(self) -> None:
        from ahadiff.contracts import RunSummary

        summary = RunSummary(
            run_id="run-1",
            source_ref="abc1234",
            source_kind="git_ref",
            capability_level=3,
            verdict="PASS",
            overall=88.5,
            status="keep",
            weakest_dim="conciseness",
            created_at="2026-04-22T00:00:00Z",
        )
        assert summary.capability_level == 3

    def test_run_detail_declares_graphify_notes_and_rejects_unknown_fields(self) -> None:
        from ahadiff.contracts import RunDetail

        detail = RunDetail(
            run_id="run-1",
            source_ref="abc1234",
            source_kind="git_ref",
            capability_level=3,
            verdict="PASS",
            overall=88.5,
            status="keep",
            weakest_dim="conciseness",
            created_at="2026-04-22T00:00:00Z",
            prompt_version="prompt123",
            eval_bundle_version="eval123",
            graphify_notes=["graph artifact is fresh"],
        )

        assert detail.graphify_notes == ["graph artifact is fresh"]
        with pytest.raises(ValidationError):
            RunDetail.model_validate({**detail.model_dump(mode="json"), "extra": "blocked"})

    def test_due_review_card_response_serializes_choice_mode_contract(self) -> None:
        from ahadiff.contracts.quiz_choice import QuizChoice
        from ahadiff.contracts.serve_app import DueReviewCardResponse

        card = DueReviewCardResponse(
            card_id="card-1",
            concept="retry loop",
            run_id="run-1",
            due_date="2026-04-22T00:00:00Z",
            scaffolding_level="full",
            display_path="src/a.py",
            answer_mode="multiple_choice",
            choices=[
                QuizChoice(label="A", text="Retry loop", is_correct=True),
                QuizChoice(label="B", text="Disables retry", is_correct=False),
                QuizChoice(label="C", text="Only renames a variable", is_correct=False),
                QuizChoice(label="D", text="Removes exception handling", is_correct=False),
            ],
        )

        assert card.model_dump(mode="json")["answer_mode"] == "multiple_choice"
        assert card.model_dump(mode="json")["choices"][0] == {
            "label": "A",
            "text": "Retry loop",
            "is_correct": True,
        }

    def test_due_review_card_response_defaults_to_open_mode(self) -> None:
        from ahadiff.contracts.serve_app import DueReviewCardResponse

        card = DueReviewCardResponse(
            card_id="card-1",
            concept="retry loop",
            run_id="run-1",
            due_date="2026-04-22T00:00:00Z",
            scaffolding_level="full",
            display_path="src/a.py",
        )

        assert card.model_dump(mode="json")["answer_mode"] == "open"
        assert card.model_dump(mode="json")["choices"] is None

    def test_review_signal_requests_accept_optional_selected_choice_label(self) -> None:
        from ahadiff.contracts.serve_app import ReviewRateRequest, ReviewSignalRequest

        signal = ReviewSignalRequest(
            idempotency_key="review:card-1:A",
            card_id="card-1",
            answer="good",
            selected_choice_label="A",
        )
        rate = ReviewRateRequest(
            idempotency_key="rate:card-1:B",
            card_id="card-1",
            answer="hard",
            selected_choice_label="B",
        )

        assert signal.model_dump(mode="json")["selected_choice_label"] == "A"
        assert rate.model_dump(mode="json")["selected_choice_label"] == "B"

    def test_quiz_answer_request_serializes_viewer_payload(self) -> None:
        from ahadiff.contracts import QuizAnswerRequest

        request = QuizAnswerRequest(
            idempotency_key="quiz:run-1:q1",
            quiz_id="q1",
            choice="B",
            correct=True,
            selected_choice_label="B",
        )

        assert request.model_dump(mode="json") == {
            "idempotency_key": "quiz:run-1:q1",
            "quiz_id": "q1",
            "choice": "B",
            "correct": True,
            "selected_choice_label": "B",
        }

    @pytest.mark.parametrize(
        ("model_type", "payload"),
        [
            (
                DueReviewCardResponse,
                {
                    "card_id": "card-1",
                    "concept": "retry loop",
                    "run_id": "run-1",
                    "due_date": "2026-04-22T00:00:00Z",
                    "scaffolding_level": "full",
                    "display_path": "src/a.py",
                },
            ),
            (
                ReviewSignalRequest,
                {"idempotency_key": "review-1", "card_id": "card-1", "answer": "good"},
            ),
            (
                ReviewRateRequest,
                {"idempotency_key": "rate-1", "card_id": "card-1", "answer": "hard"},
            ),
            (
                QuizAnswerRequest,
                {
                    "idempotency_key": "quiz-1",
                    "quiz_id": "q1",
                    "choice": "B",
                    "correct": True,
                },
            ),
        ],
    )
    def test_serve_review_choice_dtos_reject_unknown_fields(
        self,
        model_type: type[BaseModel],
        payload: dict[str, object],
    ) -> None:
        with pytest.raises(ValidationError):
            model_type.model_validate({**payload, "unexpected": "blocked"})

    @pytest.mark.parametrize(
        ("model_type", "payload"),
        [
            (
                ReviewSignalRequest,
                {"idempotency_key": "review-1", "card_id": "card-1", "answer": "good"},
            ),
            (
                ReviewRateRequest,
                {"idempotency_key": "rate-1", "card_id": "card-1", "answer": "hard"},
            ),
            (
                QuizAnswerRequest,
                {
                    "idempotency_key": "quiz-1",
                    "quiz_id": "q1",
                    "choice": "B",
                    "correct": True,
                },
            ),
        ],
    )
    def test_serve_review_choice_dtos_reject_invalid_selected_choice_label(
        self,
        model_type: type[BaseModel],
        payload: dict[str, object],
    ) -> None:
        with pytest.raises(ValidationError):
            model_type.model_validate({**payload, "selected_choice_label": "E"})

    def test_run_artifact_envelope_accepts_legacy_payload_without_content_lang(self) -> None:
        from ahadiff.contracts import RunArtifactEnvelope

        envelope = RunArtifactEnvelope.model_validate(
            {
                "run_id": "run-1",
                "artifact_type": "lesson",
                "content": "lesson body",
            }
        )

        assert envelope.content_lang is None
        assert envelope.model_dump(mode="json")["content_lang"] is None

    def test_run_artifact_envelope_serializes_content_lang(self) -> None:
        from ahadiff.contracts import RunArtifactEnvelope

        envelope = RunArtifactEnvelope(
            run_id="run-1",
            artifact_type="lesson",
            content="lesson body",
            content_lang="zh-CN",
        )

        assert envelope.content_lang == "zh-CN"
        assert envelope.model_dump(mode="json")["content_lang"] == "zh-CN"

    def test_run_source_rejects_unknown_degraded_flag(self) -> None:
        from ahadiff.contracts import RunSource

        with pytest.raises(ValidationError):
            RunSource(
                source_kind="git_ref",
                source_ref="abc1234",
                capability_level=3,
                degraded_flags=cast("Any", {"unexpected_flag": True}),
            )

    def test_claim_record_roundtrip(self) -> None:
        from ahadiff.contracts import ClaimRecord, SourceHunk

        record = ClaimRecord(
            claim_id="cl1",
            run_id="run-1",
            text="adds retry logic",
            status="verified",
            source_hunks=[SourceHunk(file="a.py", start=10, end=20, side="new")],
        )
        assert ClaimRecord.model_validate(record.model_dump()) == record

    def test_review_card_excludes_session_local_flag_from_dump(self) -> None:
        from ahadiff.contracts import ReviewCard

        card = ReviewCard(
            card_id="card-1",
            concept="retry loop",
            run_id="run-1",
            source_ref="abc1234",
            fsrs_state="{}",
            file_id="file-1",
            display_path="src/a.py",
            hunk_id="h1",
            hunk_hash="deadbeef",
        )
        dumped = card.model_dump()
        assert card.peeked_this_session is False
        assert dumped["card_state"] == "active"
        assert dumped["scaffolding_level"] == "full"
        assert "peeked_this_session" not in dumped

    def test_review_card_rejects_invalid_fsrs_state_or_change_kind(self) -> None:
        from ahadiff.contracts import ReviewCard

        with pytest.raises(ValidationError):
            ReviewCard(
                card_id="card-1",
                concept="retry loop",
                run_id="run-1",
                source_ref="abc1234",
                fsrs_state="[]",
                file_id="file-1",
                display_path="src/a.py",
                hunk_id="h1",
                hunk_hash="deadbeef",
            )

        with pytest.raises(ValidationError):
            ReviewCard(
                card_id="card-1",
                concept="retry loop",
                run_id="run-1",
                source_ref="abc1234",
                fsrs_state="{}",
                file_id="file-1",
                display_path="src/a.py",
                hunk_id="h1",
                hunk_hash="deadbeef",
                change_kind=cast("Any", "modified"),
            )

    def test_review_card_enforces_rating_and_stale_state_contract(self) -> None:
        from ahadiff.contracts import ReviewCard

        with pytest.raises(ValidationError):
            ReviewCard(
                card_id="card-1",
                concept="retry loop",
                run_id="run-1",
                source_ref="abc1234",
                fsrs_state="{}",
                last_rating=5,
                file_id="file-1",
                display_path="src/a.py",
                hunk_id="h1",
                hunk_hash="deadbeef",
            )

        with pytest.raises(ValidationError):
            ReviewCard(
                card_id="card-1",
                concept="retry loop",
                run_id="run-1",
                source_ref="abc1234",
                fsrs_state="{}",
                card_state="stale",
                file_id="file-1",
                display_path="src/a.py",
                hunk_id="h1",
                hunk_hash="deadbeef",
            )

        with pytest.raises(ValidationError):
            ReviewCard(
                card_id="card-1",
                concept="retry loop",
                run_id="run-1",
                source_ref="abc1234",
                fsrs_state="{}",
                card_state="active",
                stale_reason="file_deleted",
                file_id="file-1",
                display_path="src/a.py",
                hunk_id="h1",
                hunk_hash="deadbeef",
            )

    def test_review_card_enforces_multiple_choice_contract(self) -> None:
        from ahadiff.contracts import QuizChoice, ReviewCard

        base_payload = {
            "card_id": "card-1",
            "concept": "retry loop",
            "run_id": "run-1",
            "source_ref": "abc1234",
            "fsrs_state": "{}",
            "file_id": "file-1",
            "display_path": "src/a.py",
            "hunk_id": "h1",
            "hunk_hash": "deadbeef",
        }
        choices = [
            QuizChoice(label="A", text="Retry loop", is_correct=True),
            QuizChoice(label="B", text="Disables retry", is_correct=False),
            QuizChoice(label="C", text="Only renames a variable", is_correct=False),
            QuizChoice(label="D", text="Removes exception handling", is_correct=False),
        ]

        valid = ReviewCard.model_validate(
            {
                **base_payload,
                "answer": "Retry loop",
                "answer_mode": "multiple_choice",
                "choices": choices,
            }
        )
        assert valid.choices == choices

        with pytest.raises(ValidationError, match="non-empty answer"):
            ReviewCard.model_validate(
                {**base_payload, "answer_mode": "multiple_choice", "choices": choices}
            )

        with pytest.raises(ValidationError, match="must include choices"):
            ReviewCard.model_validate(
                {**base_payload, "answer": "Retry loop", "answer_mode": "multiple_choice"}
            )

        with pytest.raises(ValidationError, match="must not include choices"):
            ReviewCard.model_validate({**base_payload, "answer": "Retry loop", "choices": choices})

    def test_claim_record_enforces_reason_code_and_source_hunk_shape(self) -> None:
        from ahadiff.contracts import ClaimRecord

        invalid_hunks = cast("Any", [{"file": "a.py", "start": 10, "end": 20}])
        reversed_hunks = cast("Any", [{"file": "a.py", "start": 20, "end": 10}])
        invalid_side_hunks = cast(
            "Any",
            [{"file": "a.py", "start": 10, "end": 20, "side": "middle"}],
        )

        with pytest.raises(ValidationError):
            ClaimRecord(
                claim_id="cl1",
                run_id="run-1",
                text="missing evidence",
                status="rejected",
                source_hunks=invalid_hunks,
            )

        with pytest.raises(ValidationError):
            ClaimRecord(
                claim_id="cl1",
                run_id="run-1",
                text="verified text",
                status="verified",
                reason_code="evidence_missing",
                source_hunks=invalid_hunks,
            )

        with pytest.raises(ValidationError):
            ClaimRecord(
                claim_id="cl1",
                run_id="run-1",
                text="bad hunk",
                status="verified",
                source_hunks=reversed_hunks,
            )

        with pytest.raises(ValidationError):
            ClaimRecord(
                claim_id="cl1",
                run_id="run-1",
                text="bad side",
                status="verified",
                source_hunks=invalid_side_hunks,
            )

    def test_learnability_defaults(self) -> None:
        from ahadiff.contracts import LearnabilityGate

        gate = LearnabilityGate()
        assert gate.threshold == 0.3
        assert gate.weights.complexity == 0.4
        assert gate.weights.novelty == 0.3
        assert gate.weights.pattern == 0.3

    def test_ratchet_history_keeps_eval_bundle_version(self) -> None:
        from ahadiff.contracts import RatchetHistoryEntry

        entry = RatchetHistoryEntry(
            run_id="run-1",
            source_ref="abc1234",
            eval_bundle_version="123456789abc",
            overall=88.5,
            verdict="PASS",
            status="keep",
            timestamp="2026-04-22T00:00:00Z",
            weakest_dim="conciseness",
        )
        assert entry.eval_bundle_version == "123456789abc"

    def test_usage_event_rejects_unknown_provider_class(self) -> None:
        from ahadiff.contracts import UsageEvent

        with pytest.raises(ValidationError):
            UsageEvent(
                event_id="e1",
                run_id="r1",
                repo_id="repo",
                provider_class=cast("Any", "bad-provider"),
                model_id="m1",
                input_tokens=1,
                output_tokens=1,
                billing_mode="local",
                execution_origin="test",
                api_principal_hash="hash",
                timestamp="2026-04-22T00:00:00Z",
            )

    def test_card_state_literal_values(self) -> None:
        from ahadiff.contracts import CardState

        assert set(get_args(CardState)) == {"active", "stale", "archived", "suspended"}

    def test_quiz_choice_contract_exports_validate_and_normalize_choices(self) -> None:
        from ahadiff.contracts import (
            AnswerMode,
            QuizChoice,
            QuizChoiceLabel,
            validate_quiz_choices,
        )

        choices = validate_quiz_choices(
            [
                QuizChoice(label="A", text="  Retry loop  ", is_correct=True),
                QuizChoice(label="B", text="Disables retry", is_correct=False),
                QuizChoice(label="C", text="Only renames a variable", is_correct=False),
                QuizChoice(label="D", text="Removes exception handling", is_correct=False),
            ],
            expected_answer="Retry loop",
        )

        assert set(get_args(AnswerMode)) == {"open", "multiple_choice"}
        assert set(get_args(QuizChoiceLabel)) == {"A", "B", "C", "D"}
        assert [choice.label for choice in choices] == ["A", "B", "C", "D"]
        assert choices[0].text == "Retry loop"

    @pytest.mark.parametrize(
        "raw_choices",
        [
            [
                {"label": "A", "text": "Retry loop", "is_correct": True},
                {"label": "B", "text": "Disables retry", "is_correct": False},
                {"label": "C", "text": "Only renames a variable", "is_correct": False},
            ],
            [
                {"label": "A", "text": "Retry loop", "is_correct": True},
                {"label": "B", "text": "Disables retry", "is_correct": False},
                {"label": "C", "text": "Only renames a variable", "is_correct": False},
                {"label": "D", "text": "Removes exception handling", "is_correct": False},
                {"label": "A", "text": "Changes comments only", "is_correct": False},
            ],
        ],
    )
    def test_quiz_choice_validation_rejects_wrong_choice_count(
        self,
        raw_choices: list[dict[str, object]],
    ) -> None:
        from ahadiff.contracts import QuizChoice, validate_quiz_choices

        choices = [QuizChoice.model_validate(choice) for choice in raw_choices]

        with pytest.raises(ValueError, match="exactly 4"):
            validate_quiz_choices(choices)

    @pytest.mark.parametrize(
        "raw_choices",
        [
            [
                {"label": "A", "text": "Retry loop", "is_correct": False},
                {"label": "B", "text": "Disables retry", "is_correct": False},
                {"label": "C", "text": "Only renames a variable", "is_correct": False},
                {"label": "D", "text": "Removes exception handling", "is_correct": False},
            ],
            [
                {"label": "A", "text": "Retry loop", "is_correct": True},
                {"label": "B", "text": "Disables retry", "is_correct": True},
                {"label": "C", "text": "Only renames a variable", "is_correct": False},
                {"label": "D", "text": "Removes exception handling", "is_correct": False},
            ],
        ],
    )
    def test_quiz_choice_validation_rejects_zero_or_multiple_correct_choices(
        self,
        raw_choices: list[dict[str, object]],
    ) -> None:
        from ahadiff.contracts import QuizChoice, validate_quiz_choices

        choices = [QuizChoice.model_validate(choice) for choice in raw_choices]

        with pytest.raises(ValueError, match="exactly one correct"):
            validate_quiz_choices(choices)

    @pytest.mark.parametrize(
        "raw_choices",
        [
            [
                {"label": "A", "text": "Retry loop", "is_correct": True},
                {"label": "B", "text": "Disables retry", "is_correct": False},
                {"label": "D", "text": "Removes exception handling", "is_correct": False},
                {"label": "C", "text": "Only renames a variable", "is_correct": False},
            ],
            [
                {"label": "A", "text": "Retry loop", "is_correct": True},
                {"label": "B", "text": "Disables retry", "is_correct": False},
                {"label": "B", "text": "Only renames a variable", "is_correct": False},
                {"label": "D", "text": "Removes exception handling", "is_correct": False},
            ],
            [
                {"label": "A", "text": "Retry loop", "is_correct": True},
                {"label": "B", "text": "Disables retry", "is_correct": False},
                {"label": "C", "text": "Only renames a variable", "is_correct": False},
                {"text": "Missing label", "is_correct": False},
            ],
        ],
    )
    def test_quiz_choice_validation_rejects_missing_duplicate_or_unordered_labels(
        self,
        raw_choices: list[dict[str, object]],
    ) -> None:
        from ahadiff.contracts import QuizChoice, validate_quiz_choices

        with pytest.raises((ValidationError, ValueError), match="label|A/B/C/D"):
            choices = [QuizChoice.model_validate(choice) for choice in raw_choices]
            validate_quiz_choices(choices)

    def test_quiz_choice_validation_rejects_casefold_duplicate_text(self) -> None:
        from ahadiff.contracts import QuizChoice, validate_quiz_choices

        choices = [
            QuizChoice(label="A", text="Retry loop", is_correct=True),
            QuizChoice(label="B", text="retry   loop", is_correct=False),
            QuizChoice(label="C", text="Only renames a variable", is_correct=False),
            QuizChoice(label="D", text="Removes exception handling", is_correct=False),
        ]

        with pytest.raises(ValueError, match="duplicate"):
            validate_quiz_choices(choices)

    def test_quiz_choice_validation_rejects_expected_answer_mismatch(self) -> None:
        from ahadiff.contracts import QuizChoice, validate_quiz_choices

        choices = [
            QuizChoice(label="A", text="Retry loop", is_correct=True),
            QuizChoice(label="B", text="Disables retry", is_correct=False),
            QuizChoice(label="C", text="Only renames a variable", is_correct=False),
            QuizChoice(label="D", text="Removes exception handling", is_correct=False),
        ]

        with pytest.raises(ValueError, match="expected_answer"):
            validate_quiz_choices(choices, expected_answer="Backoff was added")

        with pytest.raises(ValueError, match="expected_answer"):
            validate_quiz_choices(choices, expected_answer="retry loop")

    def test_quiz_choice_rejects_unknown_fields(self) -> None:
        from ahadiff.contracts import QuizChoice

        with pytest.raises(ValidationError):
            QuizChoice.model_validate(
                {
                    "label": "A",
                    "text": "Retry loop",
                    "is_correct": True,
                    "metadata": "blocked",
                }
            )

    def test_public_identifier_fields_reject_empty_strings(self) -> None:
        from ahadiff.contracts import (
            ClaimRecord,
            DueReviewCardResponse,
            MarkWrongRequest,
            OrchestratorResult,
            RatchetHistoryEntry,
            ResultEvent,
            ReviewCard,
            ReviewRateRequest,
            ReviewSignalRequest,
            RunArtifactEnvelope,
            RunSummary,
            SourceHunk,
            TaskInfoResponse,
            TaskSubmitResponse,
            UsageEvent,
        )

        cases: list[tuple[type[BaseModel], dict[str, Any], str]] = [
            (
                RunSummary,
                {
                    "run_id": "run-1",
                    "source_ref": "abc1234",
                    "source_kind": "git_ref",
                    "capability_level": 3,
                    "verdict": "PASS",
                    "overall": 88.5,
                    "status": "keep",
                    "weakest_dim": "conciseness",
                    "created_at": "2026-04-22T00:00:00Z",
                },
                "run_id",
            ),
            (
                RunArtifactEnvelope,
                {"run_id": "run-1", "artifact_type": "lesson", "content": "body"},
                "run_id",
            ),
            (
                RatchetHistoryEntry,
                {
                    "run_id": "run-1",
                    "source_ref": "abc1234",
                    "eval_bundle_version": "eval123",
                    "overall": 88.5,
                    "verdict": "PASS",
                    "status": "keep",
                    "timestamp": "2026-04-22T00:00:00Z",
                    "weakest_dim": "conciseness",
                },
                "run_id",
            ),
            (
                DueReviewCardResponse,
                {
                    "card_id": "card-1",
                    "concept": "retry loop",
                    "run_id": "run-1",
                    "due_date": "2026-04-22T00:00:00Z",
                    "scaffolding_level": "full",
                    "display_path": "src/a.py",
                },
                "card_id",
            ),
            (
                DueReviewCardResponse,
                {
                    "card_id": "card-1",
                    "concept": "retry loop",
                    "run_id": "run-1",
                    "due_date": "2026-04-22T00:00:00Z",
                    "scaffolding_level": "full",
                    "display_path": "src/a.py",
                },
                "run_id",
            ),
            (
                MarkWrongRequest,
                {"claim_id": "claim-1", "idempotency_key": "mark-1"},
                "claim_id",
            ),
            (
                ReviewSignalRequest,
                {"card_id": "card-1", "answer": "hard", "idempotency_key": "review-1"},
                "card_id",
            ),
            (
                ReviewRateRequest,
                {"card_id": "card-1", "answer": "good", "idempotency_key": "rate-1"},
                "card_id",
            ),
            (
                ReviewCard,
                {
                    "card_id": "card-1",
                    "concept": "retry loop",
                    "run_id": "run-1",
                    "source_ref": "abc1234",
                    "fsrs_state": "{}",
                    "file_id": "file-1",
                    "display_path": "src/a.py",
                    "hunk_id": "hunk-1",
                    "hunk_hash": "deadbeef",
                },
                "card_id",
            ),
            (
                ReviewCard,
                {
                    "card_id": "card-1",
                    "concept": "retry loop",
                    "run_id": "run-1",
                    "source_ref": "abc1234",
                    "fsrs_state": "{}",
                    "file_id": "file-1",
                    "display_path": "src/a.py",
                    "hunk_id": "hunk-1",
                    "hunk_hash": "deadbeef",
                },
                "run_id",
            ),
            (
                ClaimRecord,
                {
                    "claim_id": "claim-1",
                    "run_id": "run-1",
                    "text": "adds retry logic",
                    "status": "verified",
                    "source_hunks": [SourceHunk(file="a.py", start=1, end=2, side="new")],
                },
                "claim_id",
            ),
            (
                ClaimRecord,
                {
                    "claim_id": "claim-1",
                    "run_id": "run-1",
                    "text": "adds retry logic",
                    "status": "verified",
                    "source_hunks": [SourceHunk(file="a.py", start=1, end=2, side="new")],
                },
                "run_id",
            ),
            (
                ResultEvent,
                {
                    "event_id": "event-1",
                    "run_id": "run-1",
                    "event_type": "learn",
                    "timestamp": "2026-04-22T00:00:00Z",
                    "source_ref": "abc1234",
                    "prompt_version": "pv1",
                    "eval_bundle_version": "ev1",
                    "overall": 88.5,
                    "verdict": "PASS",
                    "status": "keep",
                    "weakest_dim": "conciseness",
                },
                "event_id",
            ),
            (
                ResultEvent,
                {
                    "event_id": "event-1",
                    "run_id": "run-1",
                    "event_type": "learn",
                    "timestamp": "2026-04-22T00:00:00Z",
                    "source_ref": "abc1234",
                    "prompt_version": "pv1",
                    "eval_bundle_version": "ev1",
                    "overall": 88.5,
                    "verdict": "PASS",
                    "status": "keep",
                    "weakest_dim": "conciseness",
                },
                "run_id",
            ),
            (
                UsageEvent,
                {
                    "event_id": "event-1",
                    "run_id": "run-1",
                    "repo_id": "repo-1",
                    "provider_class": "openai",
                    "model_id": "model-1",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "billing_mode": "local",
                    "execution_origin": "test",
                    "api_principal_hash": "hash",
                    "timestamp": "2026-04-22T00:00:00Z",
                },
                "event_id",
            ),
            (
                UsageEvent,
                {
                    "event_id": "event-1",
                    "run_id": "run-1",
                    "repo_id": "repo-1",
                    "provider_class": "openai",
                    "model_id": "model-1",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "billing_mode": "local",
                    "execution_origin": "test",
                    "api_principal_hash": "hash",
                    "timestamp": "2026-04-22T00:00:00Z",
                },
                "run_id",
            ),
            (
                OrchestratorResult,
                {"run_id": "run-1", "status": "keep"},
                "run_id",
            ),
            (
                TaskInfoResponse,
                {
                    "task_id": "task-1",
                    "task_type": "learn",
                    "status": "pending",
                    "progress": {"current": 0, "total": 0, "message": ""},
                    "created_at": "2026-04-22T00:00:00Z",
                },
                "task_id",
            ),
            (TaskSubmitResponse, {"task_id": "task-1"}, "task_id"),
        ]

        for model_type, payload, field in cases:
            with pytest.raises(ValidationError) as exc_info:
                model_type.model_validate({**payload, field: ""})
            assert exc_info.value.errors()[0]["loc"] == (field,)


class TestHelpfulnessRequestContract:
    def test_file_target_kind_accepts_any_target_id(self) -> None:
        from ahadiff.contracts.serve_app import HelpfulnessRequest

        req = HelpfulnessRequest(
            idempotency_key="k1",
            target_kind="file",
            target_id="src/main.py",
        )
        assert req.target_kind == "file"
        assert req.target_id == "src/main.py"

    def test_section_target_kind_requires_colon_in_target_id(self) -> None:
        from ahadiff.contracts.serve_app import HelpfulnessRequest

        req = HelpfulnessRequest(
            idempotency_key="k2",
            target_kind="section",
            target_id="run1:intro",
        )
        assert req.target_kind == "section"
        assert req.target_id == "run1:intro"

        padded = HelpfulnessRequest(
            idempotency_key="k2-padding",
            target_kind="section",
            target_id="  run1  :  intro  ",
        )
        assert padded.target_id == "run1:intro"

    def test_section_target_kind_rejects_target_id_without_colon(self) -> None:
        from ahadiff.contracts.serve_app import HelpfulnessRequest

        with pytest.raises(ValidationError, match="target_id must contain ':'"):
            HelpfulnessRequest(
                idempotency_key="k3",
                target_kind="section",
                target_id="no_separator",
            )

    def test_section_target_kind_rejects_fullwidth_colon(self) -> None:
        from ahadiff.contracts.serve_app import HelpfulnessRequest

        with pytest.raises(ValidationError, match="target_id must contain ':'"):
            HelpfulnessRequest(
                idempotency_key="k3-fullwidth",
                target_kind="section",
                target_id="run1：intro",
            )

    def test_section_target_kind_accepts_multiple_colons(self) -> None:
        from ahadiff.contracts.serve_app import HelpfulnessRequest

        req = HelpfulnessRequest(
            idempotency_key="k4",
            target_kind="section",
            target_id="run1:chapter:subsection",
        )
        assert req.target_id == "run1:chapter:subsection"

    def test_default_target_kind_is_file(self) -> None:
        from ahadiff.contracts.serve_app import HelpfulnessRequest

        req = HelpfulnessRequest(
            idempotency_key="k5",
            target_id="src/lib.py",
        )
        assert req.target_kind == "file"

    def test_section_rejects_empty_run_id(self) -> None:
        from ahadiff.contracts.serve_app import HelpfulnessRequest

        with pytest.raises(ValidationError, match="non-empty run_id"):
            HelpfulnessRequest(
                idempotency_key="k6",
                target_kind="section",
                target_id=":intro",
            )

    def test_section_rejects_empty_section_name(self) -> None:
        from ahadiff.contracts.serve_app import HelpfulnessRequest

        with pytest.raises(ValidationError, match="non-empty"):
            HelpfulnessRequest(
                idempotency_key="k7",
                target_kind="section",
                target_id="run1:",
            )

    def test_section_rejects_colon_only(self) -> None:
        from ahadiff.contracts.serve_app import HelpfulnessRequest

        with pytest.raises(ValidationError, match="non-empty"):
            HelpfulnessRequest(
                idempotency_key="k8",
                target_kind="section",
                target_id=":",
            )

    def test_section_rejects_whitespace_parts(self) -> None:
        from ahadiff.contracts.serve_app import HelpfulnessRequest

        with pytest.raises(ValidationError, match="non-empty"):
            HelpfulnessRequest(
                idempotency_key="k9",
                target_kind="section",
                target_id=" : ",
            )


class TestServeResponseContracts:
    def test_config_response_rejects_unknown_key_status(self) -> None:
        from ahadiff.contracts import ConfigResponse

        with pytest.raises(ValidationError):
            ConfigResponse.model_validate(
                {
                    "lang": None,
                    "privacy_mode": None,
                    "generate_model": None,
                    "judge_model": None,
                    "serve_port": None,
                    "key_status": {"llm": "unknown"},
                }
            )

    def test_review_mastery_response_rejects_negative_counts(self) -> None:
        from ahadiff.contracts import ReviewMasteryResponse

        with pytest.raises(ValidationError):
            ReviewMasteryResponse.model_validate(
                {
                    "mastery": [
                        {
                            "concept": "evidence",
                            "review_count": -1,
                            "avg_rating": 3.0,
                            "last_review": None,
                        }
                    ]
                }
            )

    def test_spec_alignment_response_rejects_invalid_trend(self) -> None:
        from ahadiff.contracts import SpecAlignmentResponse

        with pytest.raises(ValidationError):
            SpecAlignmentResponse.model_validate(
                {
                    "alignment_score": 80.0,
                    "total_evaluated": 3,
                    "recent_trend": "sideways",
                }
            )

    def test_watch_status_response_rejects_private_extra_fields(self) -> None:
        from ahadiff.contracts import WatchStatusResponse

        with pytest.raises(ValidationError):
            WatchStatusResponse.model_validate(
                {
                    "enabled": False,
                    "running": False,
                    "last_trigger_time": None,
                    "pending_changes": 0,
                    "restartable": True,
                    "stop_timed_out": False,
                    "consecutive_failures": 0,
                    "total_triggers": 0,
                    "total_failures": 0,
                    "last_error": None,
                    "failure_threshold_hit": False,
                    "watch_path": "/tmp/private",
                }
            )


class TestUtilities:
    def test_eval_bundle_hash_uses_frozen_logical_labels(self, tmp_path: Path) -> None:
        from ahadiff.contracts import EVAL_BUNDLE_FILES, compute_eval_bundle_version

        assert ("eval/rubric.yaml", "src/ahadiff/eval/rubric.yaml") in EVAL_BUNDLE_FILES
        chunks: list[tuple[str, bytes]] = []
        for logical_path, disk_path in reversed(EVAL_BUNDLE_FILES):
            target = tmp_path / disk_path
            target.parent.mkdir(parents=True, exist_ok=True)
            content = f"payload:{logical_path}".encode()
            target.write_bytes(content)
            chunks.append((logical_path, content))

        expected = hashlib.sha256(
            b"\n---\n".join(
                logical_path.encode("utf-8") + b"\n" + content
                for logical_path, content in sorted(chunks, key=lambda item: item[0])
            )
        ).hexdigest()[:12]
        assert compute_eval_bundle_version(tmp_path) == expected

    def test_eval_bundle_hash_raises_clear_error_when_bundle_missing(self, tmp_path: Path) -> None:
        from ahadiff.contracts import compute_eval_bundle_version

        with pytest.raises(FileNotFoundError, match="eval bundle files are not available"):
            compute_eval_bundle_version(tmp_path)

    def test_error_hierarchy(self) -> None:
        from ahadiff.contracts import AhaDiffError, InputError

        assert issubclass(InputError, AhaDiffError)
        with pytest.raises(AhaDiffError):
            raise InputError("bad input")

    def test_orchestrator_command_enforces_config_shape(self) -> None:
        from ahadiff.contracts import OrchestratorCommand, RunConfig, RunSource, ServeConfig

        run_config = RunConfig(
            source=RunSource(source_kind="git_ref", source_ref="abc1234", capability_level=3)
        )
        serve_config = ServeConfig()

        with pytest.raises(ValidationError):
            OrchestratorCommand(kind="learn")
        with pytest.raises(ValidationError):
            OrchestratorCommand(kind="serve", run_config=run_config)

        assert OrchestratorCommand(kind="learn", run_config=run_config).kind == "learn"
        assert OrchestratorCommand(kind="serve", serve_config=serve_config).kind == "serve"

    def test_orchestrator_stubs_raise_not_implemented(self) -> None:
        from ahadiff.contracts import Orchestrator, RunConfig, RunSource

        orchestrator = Orchestrator()
        run_config = RunConfig(
            source=RunSource(source_kind="git_ref", source_ref="abc1234", capability_level=3)
        )

        with pytest.raises(NotImplementedError):
            asyncio.run(orchestrator.run_learn(run_config))

    def test_event_log_numeric_fields_are_strict(self) -> None:
        from ahadiff.contracts import ResultEvent, UsageEvent

        with pytest.raises(ValidationError):
            ResultEvent(
                event_id="e1",
                run_id="r1",
                event_type="lesson_scored",
                timestamp="2026-04-22T00:00:00Z",
                source_ref="abc1234",
                prompt_version="pv1",
                eval_bundle_version="ev1",
                overall=cast("Any", "9.5"),
                verdict="PASS",
                status="keep",
                weakest_dim="conciseness",
            )

        with pytest.raises(ValidationError):
            UsageEvent(
                event_id="e1",
                run_id="r1",
                repo_id="repo",
                provider_class="openai",
                model_id="m1",
                input_tokens=cast("Any", "1"),
                output_tokens=1,
                billing_mode="local",
                execution_origin="test",
                api_principal_hash="hash",
                timestamp="2026-04-22T00:00:00Z",
            )
