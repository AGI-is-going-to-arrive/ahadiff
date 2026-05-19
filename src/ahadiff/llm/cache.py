from __future__ import annotations

import hashlib
import json
import re
import stat
import tempfile
import time
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.core.errors import SafetyError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import ensure_state_parent_dir, validate_state_path_no_symlinks

from .schemas import CacheKeyInput, ProviderResponse, RateLimitSnapshot

if TYPE_CHECKING:
    from collections.abc import Mapping

_CACHE_SCHEMA_VERSION = 1
_ORPHANED_TMP_TTL_SECONDS = 24 * 60 * 60
_CACHE_TMP_NAME_RE = re.compile(r"^\.[0-9a-f]{64}\..+\.tmp$")


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
        "base_url": parts.base_url.rstrip("/"),
        "model_id": parts.model_id,
        "output_lang": parts.output_lang,
        "privacy_mode": parts.privacy_mode,
        "provider_class": parts.provider_class,
        "provider_kind": parts.provider_kind,
        "prompt_fingerprint": parts.prompt_fingerprint,
        "prompt_name": parts.prompt_name,
        "prompt_version": parts.prompt_version,
        "redaction_config": parts.redaction_config,
        "response_format": parts.response_format,
        "output_schema_id": parts.output_schema_id,
        "output_schema_version": parts.output_schema_version,
        "output_schema_hash": parts.output_schema_hash,
        "normalized_output_schema_hash": parts.normalized_output_schema_hash,
        "enforcement_mode": parts.enforcement_mode,
        "max_output_tokens": parts.max_output_tokens,
        "temperature": parts.temperature,
        "request_payload_sha256": parts.request_payload_sha256,
        "source_ref": parts.source_ref,
        "thinking_level": parts.thinking_level or "none",
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
    validate_state_path_no_symlinks(path, allow_missing_leaf=True)
    try:
        file_size = path.stat().st_size
        if file_size > 16 * 1024 * 1024:
            return None
        loaded: object = safe_json_loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
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
    ensure_state_parent_dir(path)
    validate_state_path_no_symlinks(path, allow_missing_leaf=True)
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
        validate_state_path_no_symlinks(tmp_path, allow_missing_leaf=True)
        tmp_file.write(encoded)
        tmp_file.write("\n")
    try:
        validate_state_path_no_symlinks(path, allow_missing_leaf=True)
        tmp_path.replace(path)
        validate_state_path_no_symlinks(path, allow_missing_leaf=False)
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
        validate_state_path_no_symlinks(directory, allow_missing_leaf=False)
        directory_stat = directory.lstat()
        if not stat.S_ISDIR(directory_stat.st_mode):
            return
        now = time.time()
        for index, tmp_path in enumerate(directory.glob(".*.tmp")):
            if index >= 10:
                break
            try:
                if not _CACHE_TMP_NAME_RE.fullmatch(tmp_path.name):
                    continue
                tmp_stat = tmp_path.lstat()
                if not stat.S_ISREG(tmp_stat.st_mode):
                    continue
                if now - tmp_stat.st_mtime > _ORPHANED_TMP_TTL_SECONDS:
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
