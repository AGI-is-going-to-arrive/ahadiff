from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads

from .database import insert_learning_signal, make_uuid7

if TYPE_CHECKING:
    from pathlib import Path


def mark_claim_wrong(
    *,
    db_path: Path,
    claim_id: str,
    idempotency_key: str | None = None,
) -> bool:
    normalized_claim_id = claim_id.strip()
    if not normalized_claim_id:
        raise InputError("claim_id must not be empty")
    payload: dict[str, object] = {"claim_id": normalized_claim_id}
    return insert_learning_signal(
        db_path,
        event_id=_make_signal_event_id(),
        idempotency_key=idempotency_key or f"mark:{normalized_claim_id}:wrong",
        signal_type="mark_wrong",
        payload=safe_json_loads(json.dumps(payload)),
    )


def _make_signal_event_id() -> str:
    return make_uuid7()


__all__ = ["mark_claim_wrong"]
