from __future__ import annotations

import hashlib
import json
import tempfile
import time
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.core.errors import SafetyError

from .schemas import CacheKeyInput, ProviderResponse, RateLimitSnapshot

if TYPE_CHECKING:
    from collections.abc import Mapping

_CACHE_SCHEMA_VERSION = 1


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
        "api_family_version": parts.api_family_version,
        "context_bundle_hash": parts.context_bundle_hash,
        "diff_content_sha256": hashlib.sha256(parts.diff_content.encode("utf-8")).hexdigest(),
        "eval_bundle_version": parts.eval_bundle_version,
        "model_id": parts.model_id,
        "output_lang": parts.output_lang,
        "privacy_mode": parts.privacy_mode,
        "prompt_fingerprint": parts.prompt_fingerprint,
        "prompt_name": parts.prompt_name,
        "prompt_version": parts.prompt_version,
        "redaction_config": parts.redaction_config,
        "request_payload_sha256": parts.request_payload_sha256,
        "source_ref": parts.source_ref,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def cache_dir(workspace_root: Path) -> Path:
    return workspace_root / ".ahadiff" / "cache"


def cache_file_path(workspace_root: Path, cache_key: str) -> Path:
    if not _is_cache_key(cache_key):
        raise SafetyError("cache key must be a lowercase sha256 hex digest")
    return cache_dir(workspace_root) / f"{cache_key}.json"


def lookup_cached_response(
    workspace_root: Path,
    parts: CacheKeyInput,
    *,
    cache_key: str | None = None,
) -> ProviderResponse | None:
    key = build_cache_key(parts) if cache_key is None else cache_key
    path = cache_file_path(workspace_root, key)
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _cleanup_orphaned_tmp_files(path.parent)
        return None
    if not isinstance(loaded, dict):
        return None
    raw = cast("dict[str, object]", loaded)
    if raw.get("schema_version") != _CACHE_SCHEMA_VERSION:
        return None
    if raw.get("cache_key") != key:
        return None
    if raw.get("eval_bundle_version") != parts.eval_bundle_version:
        return None
    response_payload = raw.get("response")
    if not isinstance(response_payload, dict):
        return None
    return _response_from_json(cast("dict[str, object]", response_payload))


def store_cached_response(
    workspace_root: Path,
    parts: CacheKeyInput,
    response: ProviderResponse,
    *,
    cache_key: str | None = None,
) -> Path:
    key = build_cache_key(parts) if cache_key is None else cache_key
    path = cache_file_path(workspace_root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "cache_key": key,
        "eval_bundle_version": parts.eval_bundle_version,
        "response": _response_to_json(response),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{key}.",
        suffix=".tmp",
        delete=False,
    ) as tmp_file:
        tmp_path = Path(tmp_file.name)
        tmp_file.write(encoded)
        tmp_file.write("\n")
    try:
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            with suppress(OSError):
                tmp_path.unlink()
    return path


def _response_to_json(response: ProviderResponse) -> dict[str, object]:
    return {
        "content": response.content,
        "model_id": response.model_id,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "finish_reason": response.finish_reason,
        "request_id": response.request_id,
        "rate_limits": asdict(response.rate_limits) if response.rate_limits is not None else None,
        "degraded_flags": response.degraded_flags,
        "notes": list(response.notes),
        "raw_json": response.raw_json,
    }


def _cleanup_orphaned_tmp_files(directory: Path) -> None:
    try:
        now = time.time()
        for index, tmp_path in enumerate(directory.glob(".*.tmp")):
            if index >= 10:
                break
            try:
                if now - tmp_path.stat().st_mtime > 3600:
                    tmp_path.unlink()
            except Exception:
                continue
    except Exception:
        return


def _response_from_json(payload: dict[str, object]) -> ProviderResponse | None:
    content = payload.get("content")
    model_id = payload.get("model_id")
    input_tokens = payload.get("input_tokens")
    output_tokens = payload.get("output_tokens")
    if not (
        isinstance(content, str)
        and isinstance(model_id, str)
        and isinstance(input_tokens, int)
        and isinstance(output_tokens, int)
    ):
        return None
    rate_limits_payload = payload.get("rate_limits")
    rate_limits = None
    if isinstance(rate_limits_payload, dict):
        rate_limits_values = cast("dict[str, object]", rate_limits_payload)
        rate_limits = RateLimitSnapshot(
            rpm_limit=_optional_int(rate_limits_values.get("rpm_limit")),
            rpm_remaining=_optional_int(rate_limits_values.get("rpm_remaining")),
            tpm_limit=_optional_int(rate_limits_values.get("tpm_limit")),
            tpm_remaining=_optional_int(rate_limits_values.get("tpm_remaining")),
            retry_after_seconds=_optional_float(rate_limits_values.get("retry_after_seconds")),
        )
    degraded_flags_payload = payload.get("degraded_flags")
    degraded_flags: dict[str, bool] = {}
    if isinstance(degraded_flags_payload, dict):
        degraded_flags_values = cast("dict[object, object]", degraded_flags_payload)
        degraded_flags = {
            key: value
            for key, value in degraded_flags_values.items()
            if isinstance(key, str) and isinstance(value, bool)
        }
    notes_payload = payload.get("notes")
    notes: tuple[str, ...] = ()
    if isinstance(notes_payload, list):
        note_values = cast("list[object]", notes_payload)
        notes = tuple(str(note) for note in note_values)
    raw_json_payload = payload.get("raw_json")
    raw_json = (
        cast("dict[str, Any]", raw_json_payload) if isinstance(raw_json_payload, dict) else None
    )
    finish_reason = payload.get("finish_reason")
    request_id = payload.get("request_id")
    return ProviderResponse(
        content=content,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        request_id=request_id if isinstance(request_id, str) else None,
        rate_limits=rate_limits,
        degraded_flags=degraded_flags,
        notes=notes,
        raw_json=raw_json,
    )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _optional_float(value: object) -> float | None:
    return value if isinstance(value, int | float) else None


def _is_cache_key(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


__all__ = [
    "assert_context_bundle_hash",
    "build_cache_key",
    "build_context_bundle_hash",
    "cache_dir",
    "cache_file_path",
    "lookup_cached_response",
    "store_cached_response",
]
