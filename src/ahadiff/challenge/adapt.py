"""Translate gap claim ids into learning signals.

``adapt_from_gaps`` is intentionally minimal:

- Each gap claim id is registered as a ``mark_wrong`` learning signal so the
  existing review surface treats the concept as unstable.
- We do **not** add new card states, new tables, or any FSRS hooks; everything
  funnels through :func:`ahadiff.review.signal.mark_claim_wrong`, which is the
  single sanctioned write path for claim-level learning signals.

The function returns a summary suitable for surfacing in the challenge
``feedback`` envelope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ahadiff.core.errors import InputError
from ahadiff.review.signal import mark_claim_wrong

if TYPE_CHECKING:
    from pathlib import Path


def adapt_from_gaps(
    *,
    challenge_id: str,
    gap_claim_ids: list[str],
    db_path: Path,
) -> dict[str, Any]:
    """Insert mark_wrong signals for each gap claim id (idempotent)."""

    if not challenge_id.strip():
        raise InputError("challenge_id must be a non-empty string")

    inserted: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()

    for raw_id in gap_claim_ids:
        claim_id = raw_id.strip()
        if not claim_id or claim_id in seen:
            continue
        seen.add(claim_id)
        idempotency_key = f"challenge:{challenge_id}:gap:{claim_id}"
        wrote = mark_claim_wrong(
            db_path=db_path,
            claim_id=claim_id,
            idempotency_key=idempotency_key,
        )
        if wrote:
            inserted.append(claim_id)
        else:
            skipped.append(claim_id)

    return {
        "challenge_id": challenge_id,
        "inserted_claim_ids": inserted,
        "duplicate_claim_ids": skipped,
        "signal_count": len(inserted),
    }


__all__ = ["adapt_from_gaps"]
