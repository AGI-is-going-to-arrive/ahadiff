from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ahadiff.contracts import ClaimConfidence, ClaimStatus
    from ahadiff.git.symbols import SymbolRecord

    from .schema import NegativeEvidence


def classify_claim_status(
    *,
    unmatched_symbols: Sequence[str],
    negative_evidence: Sequence[NegativeEvidence],
    matched_symbols: Sequence[SymbolRecord],
) -> ClaimStatus:
    negative_codes = {item.code for item in negative_evidence}
    if "deleted_symbol_reference" in negative_codes:
        return "contradicted"
    if any(
        code in negative_codes
        for code in {
            "missing_retry_structure",
            "missing_test_structure",
            "missing_import_structure",
            "missing_security_structure",
        }
    ):
        return "contradicted"
    if unmatched_symbols:
        return "not_proven"
    if negative_evidence:
        return "weak"
    if matched_symbols:
        return "verified"
    return "weak"


def resolve_claim_confidence(
    *,
    status: ClaimStatus,
    matched_symbols: Sequence[SymbolRecord],
) -> ClaimConfidence:
    if status in {"weak", "not_proven", "contradicted"}:
        return "low"
    if not matched_symbols:
        return "low"
    if any(item.confidence == "high" for item in matched_symbols):
        return "high"
    if any(item.confidence == "medium" for item in matched_symbols):
        return "medium"
    return "low"


__all__ = ["classify_claim_status", "resolve_claim_confidence"]
