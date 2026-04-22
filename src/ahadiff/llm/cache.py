from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from ahadiff.core.errors import SafetyError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .schemas import CacheKeyInput


def build_context_bundle_hash(artifacts: Mapping[str, bytes | str]) -> str:
    chunks: list[bytes] = []
    for name in sorted(artifacts):
        value = artifacts[name]
        encoded = value if isinstance(value, bytes) else value.encode("utf-8")
        chunks.append(name.encode("utf-8") + b"\n" + encoded)
    return hashlib.sha256(b"\n---\n".join(chunks)).hexdigest()


def assert_context_bundle_hash(
    expected_hash: str,
    artifacts: Mapping[str, bytes | str],
) -> str:
    actual_hash = build_context_bundle_hash(artifacts)
    if expected_hash and actual_hash != expected_hash:
        raise SafetyError(
            "context_bundle_hash drift detected between assembly and provider dispatch"
        )
    return actual_hash


def build_cache_key(parts: CacheKeyInput) -> str:
    payload = {
        "api_family": parts.api_family,
        "context_bundle_hash": parts.context_bundle_hash,
        "diff_content_sha256": hashlib.sha256(parts.diff_content.encode("utf-8")).hexdigest(),
        "eval_bundle_version": parts.eval_bundle_version,
        "model_id": parts.model_id,
        "output_lang": parts.output_lang,
        "privacy_mode": parts.privacy_mode,
        "prompt_version": parts.prompt_version,
        "redaction_config": parts.redaction_config,
        "source_ref": parts.source_ref,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["assert_context_bundle_hash", "build_cache_key", "build_context_bundle_hash"]
