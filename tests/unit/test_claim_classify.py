from __future__ import annotations

from typing import Literal

from ahadiff.claims.classify import classify_claim_status, resolve_claim_confidence
from ahadiff.claims.schema import NegativeEvidence
from ahadiff.git.symbols import SymbolRange, SymbolRecord


def _symbol(*, confidence: Literal["high", "medium", "low"] = "high") -> SymbolRecord:
    return SymbolRecord(
        path="src/app.py",
        qualified_name="retry_once",
        kind="function",
        range=SymbolRange(1, 2),
        selection_range=SymbolRange(1, 1),
        parent=None,
        touched_lines=(1, 2),
        hunk_ids=("hunk_1",),
        hunk_hash="deadbeef1234",
        change_kind=None,
        extractor="python_ast" if confidence == "high" else "regex",
        confidence=confidence,
    )


def test_classify_claim_returns_contradicted_for_hard_negative_signal() -> None:
    status = classify_claim_status(
        unmatched_symbols=[],
        negative_evidence=[NegativeEvidence(code="missing_security_structure", detail="missing")],
        matched_symbols=[],
    )

    assert status == "contradicted"


def test_classify_claim_returns_not_proven_for_missing_symbol() -> None:
    status = classify_claim_status(
        unmatched_symbols=["missing_symbol"],
        negative_evidence=[],
        matched_symbols=[],
    )

    assert status == "not_proven"


def test_classify_claim_returns_weak_for_soft_negative_signal() -> None:
    status = classify_claim_status(
        unmatched_symbols=[],
        negative_evidence=[
            NegativeEvidence(
                code="risky_generalization_without_symbol_support",
                detail="risky",
            )
        ],
        matched_symbols=[],
    )

    assert status == "weak"


def test_classify_claim_returns_weak_for_zero_evidence_fallback() -> None:
    status = classify_claim_status(
        unmatched_symbols=[],
        negative_evidence=[],
        matched_symbols=[],
    )

    assert status == "weak"


def test_classify_claim_treats_missing_test_structure_as_contradicted() -> None:
    status = classify_claim_status(
        unmatched_symbols=[],
        negative_evidence=[NegativeEvidence(code="missing_test_structure", detail="missing")],
        matched_symbols=[],
    )

    assert status == "contradicted"


def test_resolve_claim_confidence_prefers_symbol_signal_strength() -> None:
    assert resolve_claim_confidence(status="verified", matched_symbols=[_symbol()]) == "high"
    assert (
        resolve_claim_confidence(status="verified", matched_symbols=[_symbol(confidence="medium")])
        == "medium"
    )
    assert resolve_claim_confidence(status="weak", matched_symbols=[_symbol()]) == "low"
