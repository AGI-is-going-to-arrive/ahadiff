"""Diffity-style learning loop: build -> tour -> challenge -> review -> adapt.

The challenge engine is an *opt-in* surface (config gated by
``challenge.enabled``). State is persisted under ``.ahadiff/challenges/<id>/``
which is already covered by the repo-level ``.gitignore``. No new database
tables or card states are introduced; ``adapt`` only emits learning signals
via the existing ``review.database`` API.
"""

from __future__ import annotations

from .adapt import adapt_from_gaps
from .engine import review_attempt
from .manifest import (
    CHALLENGE_MANIFEST_VERSION,
    ChallengeManifest,
    build_challenge,
    read_manifest,
    write_manifest,
)
from .state import (
    CHALLENGE_ID_PATTERN,
    VALID_TRANSITIONS,
    ChallengeStage,
    ChallengeState,
    InvalidTransitionError,
    challenge_dir,
    create_state,
    ensure_rebuild_allowed,
    is_feature_enabled,
    read_state,
    validate_challenge_id,
    write_state,
)

__all__ = [
    "CHALLENGE_ID_PATTERN",
    "CHALLENGE_MANIFEST_VERSION",
    "ChallengeManifest",
    "ChallengeStage",
    "ChallengeState",
    "InvalidTransitionError",
    "VALID_TRANSITIONS",
    "adapt_from_gaps",
    "build_challenge",
    "challenge_dir",
    "create_state",
    "ensure_rebuild_allowed",
    "is_feature_enabled",
    "read_manifest",
    "read_state",
    "review_attempt",
    "validate_challenge_id",
    "write_manifest",
    "write_state",
]
