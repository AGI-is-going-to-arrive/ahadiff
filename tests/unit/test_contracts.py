"""Stage 0 acceptance for the importable contracts surface."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import get_args

import pytest

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
        assert ReviewCard
        assert RunSource
        assert ProviderConfig
        assert ProviderCapabilities
        assert AllowlistPolicy
        assert ResultEvent
        assert UsageEvent
        assert LearnabilityGate
        assert OrchestratorCommand
        assert OrchestratorResult
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

    def test_run_source_rejects_unknown_degraded_flag(self) -> None:
        from ahadiff.contracts import RunSource

        with pytest.raises(Exception):
            RunSource(
                source_kind="git_ref",
                source_ref="abc1234",
                capability_level=3,
                degraded_flags={"unexpected_flag": True},
            )

    def test_claim_record_roundtrip(self) -> None:
        from ahadiff.contracts import ClaimRecord

        record = ClaimRecord(
            claim_id="cl1",
            run_id="run-1",
            text="adds retry logic",
            status="verified",
            source_hunks=[{"file": "a.py", "start": 10, "end": 20}],
        )
        assert ClaimRecord.model_validate(record.model_dump()) == record

    def test_review_card_preserves_stage0_fields(self) -> None:
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
        assert dumped["card_state"] == "active"
        assert dumped["scaffolding_level"] == "full"
        assert dumped["peeked_this_session"] is False

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

        with pytest.raises(Exception):
            UsageEvent(
                event_id="e1",
                run_id="r1",
                repo_id="repo",
                provider_class="bad-provider",
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


class TestUtilities:
    def test_eval_bundle_hash_uses_frozen_logical_labels(self, tmp_path: Path) -> None:
        from ahadiff.contracts import EVAL_BUNDLE_FILES, compute_eval_bundle_version

        chunks: list[bytes] = []
        for logical_path, disk_path in EVAL_BUNDLE_FILES:
            target = tmp_path / disk_path
            target.parent.mkdir(parents=True, exist_ok=True)
            content = f"payload:{logical_path}".encode("utf-8")
            target.write_bytes(content)
            chunks.append(logical_path.encode("utf-8") + b"\n" + content)

        expected = hashlib.sha256(b"\n---\n".join(chunks)).hexdigest()[:12]
        assert compute_eval_bundle_version(tmp_path) == expected

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

        with pytest.raises(Exception):
            OrchestratorCommand(kind="learn")
        with pytest.raises(Exception):
            OrchestratorCommand(kind="serve", run_config=run_config)

        assert OrchestratorCommand(kind="learn", run_config=run_config).kind == "learn"
        assert OrchestratorCommand(kind="serve", serve_config=serve_config).kind == "serve"
