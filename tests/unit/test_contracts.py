"""Stage 0 acceptance for the importable contracts surface."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Any, cast, get_args

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


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
            RunConfig,
            RunDetail,
            RunSource,
            RunSummary,
            ServeConfig,
            SetLocaleRequest,
            UsageEvent,
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
        assert InputError


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

    def test_quiz_answer_request_serializes_viewer_payload(self) -> None:
        from ahadiff.contracts import QuizAnswerRequest

        request = QuizAnswerRequest(
            idempotency_key="quiz:run-1:q1",
            quiz_id="q1",
            choice="B",
            correct=True,
        )

        assert request.model_dump(mode="json") == {
            "idempotency_key": "quiz:run-1:q1",
            "quiz_id": "q1",
            "choice": "B",
            "correct": True,
        }

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
