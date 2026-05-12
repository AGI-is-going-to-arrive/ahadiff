"""Build a challenge manifest from a qualifying learn run.

A run "qualifies" when its persisted ``score.json`` reports an ``overall``
score of at least :data:`MIN_QUALIFYING_OVERALL` (80) and a ``pass``
verdict. We refuse to clone runs that did not meet the ratchet bar so the
learner is never asked to reproduce a known-broken lesson.

The manifest captures the canonical diff envelope (``baseline_sha`` /
``target_sha`` / ``hunks``) plus the ids of the verified claims it
exercises. The file is JSON, persisted next to the state file under
``challenges/<id>/manifest.json``.
"""

from __future__ import annotations

import errno
import json
import math
import os
import secrets
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from ahadiff.core.errors import InputError

if TYPE_CHECKING:
    from pathlib import Path
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import (
    atomic_write_state_text,
    validate_run_id,
    validate_state_path_no_symlinks,
)

from .state import challenge_dir, validate_challenge_id

CHALLENGE_MANIFEST_VERSION = "1"
MIN_QUALIFYING_OVERALL = 80.0
_PATCH_MAX_BYTES = 5_000_000
_JSON_ARTIFACT_MAX_BYTES = 1_000_000
_MANIFEST_MAX_BYTES = _PATCH_MAX_BYTES + _JSON_ARTIFACT_MAX_BYTES
_CLAIMS_MAX_BYTES = 5_000_000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class ChallengeManifest:
    challenge_id: str
    source_run_id: str
    baseline_sha: str | None
    target_sha: str | None
    hunks: list[dict[str, Any]]
    canonical_claim_ids: list[str]
    canonical_patch: str
    created_at_utc: str
    manifest_version: str = CHALLENGE_MANIFEST_VERSION
    notes: list[str] = field(default_factory=list[str])

    def to_payload(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "challenge_id": self.challenge_id,
            "source_run_id": self.source_run_id,
            "baseline_sha": self.baseline_sha,
            "target_sha": self.target_sha,
            "hunks": list(self.hunks),
            "canonical_claim_ids": list(self.canonical_claim_ids),
            "canonical_patch": self.canonical_patch,
            "created_at_utc": self.created_at_utc,
            "notes": list(self.notes),
        }


def build_challenge(
    *,
    source_run_id: str,
    state_dir: Path,
    challenge_id: str | None = None,
) -> ChallengeManifest:
    """Construct a manifest from a qualifying learn run."""

    validate_run_id(source_run_id)
    validate_state_path_no_symlinks(state_dir, allow_missing_leaf=False)
    run_path = state_dir / "runs" / source_run_id
    validate_state_path_no_symlinks(run_path, allow_missing_leaf=True)
    if not run_path.exists():
        raise InputError(f"source run not found: {source_run_id}")

    score = _read_score(run_path)
    overall = _coerce_overall(score)
    verdict = str(score.get("verdict") or "").strip().lower()
    if overall < MIN_QUALIFYING_OVERALL or verdict != "pass":
        raise InputError(
            "source run does not qualify for challenge build "
            f"(overall={overall}, verdict={verdict!r}, "
            f"min={MIN_QUALIFYING_OVERALL}, required_verdict='pass')"
        )

    metadata = _read_metadata(run_path)
    baseline_sha, target_sha = _extract_sha_pair(metadata)
    hunks = _extract_hunks(metadata)
    patch_text = _read_patch(run_path)
    canonical_claim_ids = _extract_canonical_claim_ids(run_path)

    final_challenge_id = (
        validate_challenge_id(challenge_id) if challenge_id is not None else _generate_id()
    )

    return ChallengeManifest(
        challenge_id=final_challenge_id,
        source_run_id=source_run_id,
        baseline_sha=baseline_sha,
        target_sha=target_sha,
        hunks=hunks,
        canonical_claim_ids=canonical_claim_ids,
        canonical_patch=patch_text,
        created_at_utc=_now_iso(),
    )


def write_manifest(state_dir: Path, manifest: ChallengeManifest) -> Path:
    target_dir = challenge_dir(state_dir, manifest.challenge_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    validate_state_path_no_symlinks(target_dir, allow_missing_leaf=False)
    manifest_path = target_dir / "manifest.json"
    atomic_write_state_text(
        manifest_path,
        json.dumps(manifest.to_payload(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )
    return manifest_path


def read_manifest(state_dir: Path, challenge_id: str) -> ChallengeManifest:
    target_dir = challenge_dir(state_dir, challenge_id)
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.exists():
        raise InputError(f"challenge manifest not found: {challenge_id}")
    raw = _read_regular_text(
        manifest_path,
        label="challenge manifest file",
        max_bytes=_MANIFEST_MAX_BYTES,
    )
    try:
        payload = safe_json_loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise InputError(f"challenge manifest is not valid JSON: {challenge_id}") from exc
    if not isinstance(payload, dict):
        raise InputError("challenge manifest must be a JSON object")
    return _manifest_from_payload(cast("dict[str, Any]", payload))


def _manifest_from_payload(payload: dict[str, Any]) -> ChallengeManifest:
    required = {"challenge_id", "source_run_id", "created_at_utc"}
    missing = required - payload.keys()
    if missing:
        raise InputError(f"challenge manifest missing fields: {sorted(missing)}")
    hunks_raw = payload.get("hunks", [])
    claim_ids_raw = payload.get("canonical_claim_ids", [])
    notes_raw = payload.get("notes", [])
    if not isinstance(hunks_raw, list):
        raise InputError("challenge manifest.hunks must be a list")
    if not isinstance(claim_ids_raw, list):
        raise InputError("challenge manifest.canonical_claim_ids must be a list")
    if not isinstance(notes_raw, list):
        raise InputError("challenge manifest.notes must be a list")
    challenge_id = str(payload["challenge_id"])
    source_run_id = str(payload["source_run_id"])
    validate_challenge_id(challenge_id)
    validate_run_id(source_run_id)
    return ChallengeManifest(
        challenge_id=challenge_id,
        source_run_id=source_run_id,
        baseline_sha=_optional_str(payload.get("baseline_sha")),
        target_sha=_optional_str(payload.get("target_sha")),
        hunks=[
            cast("dict[str, Any]", item)
            for item in cast("list[Any]", hunks_raw)
            if isinstance(item, dict)
        ],
        canonical_claim_ids=[str(item) for item in cast("list[Any]", claim_ids_raw)],
        canonical_patch=str(payload.get("canonical_patch") or ""),
        created_at_utc=str(payload["created_at_utc"]),
        manifest_version=str(payload.get("manifest_version") or CHALLENGE_MANIFEST_VERSION),
        notes=[str(item) for item in cast("list[Any]", notes_raw)],
    )


def _read_score(run_path: Path) -> dict[str, Any]:
    score_path = run_path / "score.json"
    if not score_path.exists():
        raise InputError("source run is missing score.json; cannot evaluate qualification")
    try:
        payload = safe_json_loads(
            _read_regular_text(
                score_path,
                label="run score file",
                max_bytes=_JSON_ARTIFACT_MAX_BYTES,
            )
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise InputError("score.json must contain valid finite JSON") from exc
    if not isinstance(payload, dict):
        raise InputError("score.json must contain a JSON object")
    return cast("dict[str, Any]", payload)


def _read_metadata(run_path: Path) -> dict[str, Any]:
    metadata_path = run_path / "metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        payload = safe_json_loads(
            _read_regular_text(
                metadata_path,
                label="run metadata file",
                max_bytes=_JSON_ARTIFACT_MAX_BYTES,
            )
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise InputError("metadata.json must contain valid finite JSON") from exc
    if not isinstance(payload, dict):
        raise InputError("metadata.json must contain a JSON object")
    return cast("dict[str, Any]", payload)


def _read_patch(run_path: Path) -> str:
    patch_path = run_path / "patch.diff"
    if not patch_path.exists():
        return ""
    return _read_regular_text(patch_path, label="run patch file", max_bytes=_PATCH_MAX_BYTES)


def _extract_canonical_claim_ids(run_path: Path) -> list[str]:
    claims_path = run_path / "claims.jsonl"
    if not claims_path.exists():
        return []
    canonical: list[str] = []
    raw_text = _read_regular_text(claims_path, label="run claims file", max_bytes=_CLAIMS_MAX_BYTES)
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = safe_json_loads(stripped)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        record = cast("dict[str, Any]", payload)
        status = str(record.get("status") or "").strip().lower()
        if status not in {"verified", "weak"}:
            continue
        claim_id = record.get("claim_id")
        if isinstance(claim_id, str) and claim_id:
            canonical.append(claim_id)
    return canonical


def _coerce_overall(score: dict[str, Any]) -> float:
    raw = score.get("overall")
    if isinstance(raw, bool):
        raise InputError("score.overall must be numeric, got bool")
    value: float
    if isinstance(raw, int | float):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw)
        except ValueError as exc:
            raise InputError(f"score.overall is not numeric: {raw!r}") from exc
    else:
        raise InputError(f"score.overall is missing or invalid: {raw!r}")
    if not math.isfinite(value):
        raise InputError(f"score.overall must be finite: {raw!r}")
    return value


def _extract_sha_pair(metadata: dict[str, Any]) -> tuple[str | None, str | None]:
    baseline = _optional_str(metadata.get("baseline_sha"))
    target = _optional_str(metadata.get("target_sha"))
    if baseline is None and target is None:
        source_ref = _optional_str(metadata.get("source_ref"))
        if source_ref and ".." in source_ref:
            left, _, right = source_ref.partition("..")
            baseline = left or None
            target = right or None
    return baseline, target


def _extract_hunks(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    raw = metadata.get("hunks")
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in cast("list[Any]", raw):
        if isinstance(entry, dict):
            items.append(cast("dict[str, Any]", entry))
    return items


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def _read_regular_text(path: Path, *, label: str, max_bytes: int) -> str:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        raise InputError(f"{label} does not exist: {path}") from None
    except OSError as exc:
        raise InputError(f"{label} is unreadable: {path}") from exc
    _validate_regular_artifact(path_stat, label=label)
    if path_stat.st_size > max_bytes:
        raise InputError(f"{label} exceeds {max_bytes} bytes")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(f"{label} must not be a symlink") from exc
        raise InputError(f"{label} is unreadable: {path}") from exc
    try:
        file_stat = os.fstat(fd)
        _validate_regular_artifact(file_stat, label=label)
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError(f"{label} changed during validation")
        if file_stat.st_size > max_bytes:
            raise InputError(f"{label} exceeds {max_bytes} bytes")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk_size = min(65_536, max_bytes + 1 - total)
            if chunk_size <= 0:
                break
            chunk = os.read(fd, chunk_size)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise InputError(f"{label} exceeds {max_bytes} bytes")
        return b"".join(chunks).decode("utf-8", errors="replace")
    except OSError as exc:
        raise InputError(f"{label} is unreadable: {path}") from exc
    finally:
        os.close(fd)


def _validate_regular_artifact(path_stat: os.stat_result, *, label: str) -> None:
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError(f"{label} must not be a symlink")
    if bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
        raise InputError(f"{label} must not be a Windows reparse point or junction")
    if not stat.S_ISREG(path_stat.st_mode):
        raise InputError(f"{label} must be a regular file")
    if getattr(path_stat, "st_nlink", 1) > 1:
        raise InputError(f"{label} must not be a hardlink")


def _generate_id() -> str:
    return secrets.token_hex(6)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "CHALLENGE_MANIFEST_VERSION",
    "ChallengeManifest",
    "MIN_QUALIFYING_OVERALL",
    "build_challenge",
    "read_manifest",
    "write_manifest",
]
