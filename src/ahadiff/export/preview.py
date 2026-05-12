"""Local static preview export engine."""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import stat
import zipfile
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import (
    reject_leaf_symlink_or_reparse,
    validate_run_id,
    validate_state_path_no_symlinks,
)
from ahadiff.safety.injection import protect_untrusted_text
from ahadiff.safety.redact import redaction_pipeline

from .writer import (
    ensure_output_contained,
    safe_write_export_file,
    validate_export_directory,
    validate_export_relative_path,
)

_README_LINES = (
    "AhaDiff Local Preview Export",
    "",
    "This bundle is a local, self-contained snapshot of a finalized AhaDiff run.",
    "It contains the lesson text, concept references, quiz items, and the score",
    "summary, with secrets and prompt-injection markers redacted.",
    "",
    "Open `index.html` in any modern browser to read offline; no network access",
    "is required.  No raw model prompts, audit-private records, or API keys are",
    "included in this bundle.",
    "",
    "Verify integrity with `manifest.json`: each file is listed with a SHA-256",
    "digest and the top-level `digest` field is the SHA-256 over those entries.",
)

_INDEX_HTML = (
    "<!DOCTYPE html>\n"
    '<html lang="en">\n'
    "<head>\n"
    '<meta charset="utf-8">\n'
    "<title>AhaDiff Local Preview</title>\n"
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<meta name="robots" content="noindex,nofollow">\n'
    "</head>\n"
    "<body>\n"
    "<h1>AhaDiff Local Preview</h1>\n"
    "<p>This is a static, redacted snapshot of an AhaDiff run.  See "
    "<code>data/run.json</code> for the full payload and <code>README.txt</code>"
    " for verification instructions.</p>\n"
    "</body>\n"
    "</html>\n"
)

_DATA_FILES_TO_READ = (
    ("lesson/lesson.full.md", "lesson_full"),
    ("lesson/lesson.hint.md", "lesson_hint"),
    ("lesson/lesson.compact.md", "lesson_compact"),
    ("lesson/misconception.md", "misconception"),
    ("lesson/not_proven.md", "not_proven"),
)

_PRIVATE_FILES_EXCLUDED = frozenset(
    {
        "audit.private.jsonl",
        "audit.private",
        "prompt.raw.txt",
        "raw_prompt.txt",
        "claims.raw.jsonl",
    }
)


@dataclass(frozen=True)
class ExportManifest:
    """Top-level manifest emitted alongside the static preview bundle."""

    run_id: str
    file_count: int
    total_bytes: int
    digest: str
    created_at_utc: str
    privacy_mode: str
    files: tuple[tuple[str, str, int], ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "privacy_mode": self.privacy_mode,
            "created_at_utc": self.created_at_utc,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "digest": self.digest,
            "files": [
                {"path": path, "sha256": digest, "size": size} for path, digest, size in self.files
            ],
        }


def _safe_stat_artifact(path: Path) -> os.stat_result | None:
    """lstat an artifact path, rejecting symlinks/reparse points.

    Returns None when the path does not exist.  Raises InputError for
    symlinks, Windows reparse points, or non-regular files.
    """
    try:
        try:
            path.parent.lstat()
        except FileNotFoundError:
            return None
        validate_state_path_no_symlinks(path.parent, allow_missing_leaf=False)
        leaf_stat = reject_leaf_symlink_or_reparse(path, label="export artifact")
    except InputError as exc:
        if "does not exist" in str(exc):
            return None
        raise
    if not stat.S_ISREG(leaf_stat.st_mode):
        raise InputError(f"export artifact must be a regular file: {path.name}")
    return leaf_stat


def _read_regular_bytes(path: Path, *, label: str, max_bytes: int) -> bytes | None:
    try:
        path.parent.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InputError(f"{label} parent is unreadable: {path.parent.name}") from exc
    validate_state_path_no_symlinks(path.parent, allow_missing_leaf=False)
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InputError(f"{label} is unreadable: {path.name}") from exc
    _validate_regular_stat(path_stat, label=label, name=path.name)
    if path_stat.st_size > max_bytes:
        raise InputError(f"{label} too large: {path.name} exceeds {max_bytes} bytes")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(f"{label} must not be a symlink: {path.name}") from exc
        raise InputError(f"{label} is unreadable: {path.name}") from exc

    try:
        file_stat = os.fstat(fd)
        _validate_regular_stat(file_stat, label=label, name=path.name)
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError(f"{label} changed during validation: {path.name}")
        if file_stat.st_size > max_bytes:
            raise InputError(f"{label} too large: {path.name} exceeds {max_bytes} bytes")

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
                raise InputError(f"{label} too large: {path.name} exceeds {max_bytes} bytes")
        return b"".join(chunks)
    except OSError as exc:
        raise InputError(f"{label} is unreadable: {path.name}") from exc
    finally:
        os.close(fd)


def _validate_regular_stat(path_stat: os.stat_result, *, label: str, name: str) -> None:
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError(f"{label} must not be a symlink: {name}")
    if bool(getattr(path_stat, "st_file_attributes", 0) & 0x400):
        raise InputError(f"{label} must not be a Windows reparse point or junction: {name}")
    if not stat.S_ISREG(path_stat.st_mode):
        raise InputError(f"{label} must be a regular file: {name}")
    if getattr(path_stat, "st_nlink", 1) > 1:
        raise InputError(f"{label} must not be a hardlink: {name}")


def _read_text(path: Path, *, max_bytes: int = 5_000_000) -> str | None:
    data = _read_regular_bytes(path, label="export artifact", max_bytes=max_bytes)
    if data is None:
        return None
    return data.decode("utf-8")


def _read_json(path: Path, *, max_bytes: int = 5_000_000) -> Any | None:
    text = _read_text(path, max_bytes=max_bytes)
    if text is None:
        return None
    return safe_json_loads(text)


def _read_jsonl(path: Path, *, max_bytes: int = 5_000_000) -> list[dict[str, Any]]:
    data = _read_regular_bytes(path, label="export artifact", max_bytes=max_bytes)
    if data is None:
        return []
    records: list[dict[str, Any]] = []
    for line in data.decode("utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = safe_json_loads(stripped)
        if isinstance(parsed, dict):
            records.append(cast("dict[str, Any]", parsed))
    return records


def _scrub_string(value: str) -> str:
    if not value:
        return value
    injection_report = protect_untrusted_text(
        value,
        source_name="export_preview",
        source_kind="markdown",
    )
    result = redaction_pipeline(injection_report.protected_text)
    return result.primary_target.redacted_text


def _scrub_value(value: Any, *, _depth: int = 0) -> Any:
    if _depth > 32:
        raise InputError("export payload exceeds maximum nesting depth")
    if isinstance(value, str):
        return _scrub_string(value)
    if isinstance(value, dict):
        typed_dict = cast("dict[Any, Any]", value)
        result: dict[Any, Any] = {}
        for raw_key, raw_value in typed_dict.items():
            if isinstance(raw_key, str) and raw_key in _PRIVATE_FILES_EXCLUDED:
                continue
            new_key = _scrub_string(raw_key) if isinstance(raw_key, str) else raw_key
            result[new_key] = _scrub_value(raw_value, _depth=_depth + 1)
        return result
    if isinstance(value, list):
        typed_list = cast("list[Any]", value)
        return [_scrub_value(item, _depth=_depth + 1) for item in typed_list]
    if isinstance(value, tuple):
        typed_tuple = cast("tuple[Any, ...]", value)
        return [_scrub_value(item, _depth=_depth + 1) for item in typed_tuple]
    return value


def _load_run_payload(run_dir: Path) -> dict[str, Any]:
    finalized_path = run_dir / "finalized.json"
    finalized_raw = _read_json(finalized_path)
    if finalized_raw is None:
        raise InputError(f"run is not finalized (missing finalized.json): {run_dir.name}")
    if not isinstance(finalized_raw, dict):
        raise InputError(f"finalized.json must be a JSON object: {run_dir.name}")
    finalized = cast("dict[str, Any]", finalized_raw)

    metadata_raw = _read_json(run_dir / "metadata.json")
    metadata: dict[str, Any] = (
        cast("dict[str, Any]", metadata_raw) if isinstance(metadata_raw, dict) else {}
    )

    score_raw = _read_json(run_dir / "score.json")
    score: dict[str, Any] = cast("dict[str, Any]", score_raw) if isinstance(score_raw, dict) else {}

    lessons: dict[str, str] = {}
    for rel_path, key in _DATA_FILES_TO_READ:
        text = _read_text(run_dir / rel_path)
        if text is not None:
            lessons[key] = text

    quiz = _read_jsonl(run_dir / "quiz" / "quiz.jsonl")
    cards = _read_jsonl(run_dir / "quiz" / "cards.jsonl")
    misconception_cards = _read_jsonl(run_dir / "quiz" / "misconception_cards.jsonl")
    claims = _read_jsonl(run_dir / "claims.jsonl")

    return {
        "schema_version": 1,
        "finalized": finalized,
        "metadata": metadata,
        "score": score,
        "lessons": lessons,
        "quiz": quiz,
        "cards": cards,
        "misconception_cards": misconception_cards,
        "claims": claims,
    }


def _extract_concept_terms(payload: dict[str, Any]) -> set[str]:
    terms: set[str] = set()

    def _maybe_add(value: Any) -> None:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                terms.add(stripped)
        elif isinstance(value, list):
            typed_list = cast("list[Any]", value)
            for item in typed_list:
                _maybe_add(item)

    claims_raw = payload.get("claims", [])
    if isinstance(claims_raw, list):
        for claim in cast("list[Any]", claims_raw):
            if not isinstance(claim, dict):
                continue
            claim_dict = cast("dict[str, Any]", claim)
            _maybe_add(claim_dict.get("concepts"))
            _maybe_add(claim_dict.get("concept"))
            _maybe_add(claim_dict.get("term"))
            _maybe_add(claim_dict.get("term_key"))
    metadata_raw = payload.get("metadata", {})
    if isinstance(metadata_raw, dict):
        _maybe_add(cast("dict[str, Any]", metadata_raw).get("concepts"))
    return terms


def _filter_concepts(state_dir: Path, run_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    concepts_path = state_dir / "concepts.jsonl"
    leaf_stat = _safe_stat_artifact(concepts_path)
    if leaf_stat is None:
        return []
    if leaf_stat.st_size > 50_000_000:
        raise InputError("concepts.jsonl exceeds export size limit")
    terms = _extract_concept_terms(payload)
    selected: list[dict[str, Any]] = []
    data = _read_regular_bytes(
        concepts_path,
        label="concepts.jsonl",
        max_bytes=50_000_000,
    )
    if data is None:
        return []
    for line in data.decode("utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = safe_json_loads(stripped)
        if not isinstance(parsed, dict):
            continue
        entry = cast("dict[str, Any]", parsed)
        introduced_by = entry.get("introduced_by_run")
        updated_by_raw = entry.get("updated_by_runs")
        updated_by: list[Any] = (
            cast("list[Any]", updated_by_raw) if isinstance(updated_by_raw, list) else []
        )
        run_matches = introduced_by == run_id or any(
            isinstance(item, str) and item == run_id for item in updated_by
        )
        term_matches = False
        if terms:
            for key in ("concept", "term", "term_key", "display_name"):
                value = entry.get(key)
                if isinstance(value, str) and value in terms:
                    term_matches = True
                    break
        if run_matches or term_matches:
            selected.append(entry)
    return selected


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_entry(rel_path: str, data: bytes) -> tuple[str, str, int]:
    return rel_path, _sha256_bytes(data), len(data)


def _compute_top_level_digest(files: list[tuple[str, str, int]]) -> str:
    sorted_files = sorted(files, key=lambda item: item[0])
    hasher = hashlib.sha256()
    for path, digest, size in sorted_files:
        hasher.update(f"{path}\x00{digest}\x00{size}\n".encode())
    return hasher.hexdigest()


def validate_preview_run(run_id: str, state_dir: Path) -> Path:
    """Validate that a run can be exported before touching output paths."""

    validate_run_id(run_id)
    validate_state_path_no_symlinks(state_dir, allow_missing_leaf=False)
    run_dir = state_dir / "runs" / run_id
    try:
        run_stat = os.lstat(run_dir)
    except FileNotFoundError:
        raise InputError(f"run not found: {run_id}") from None
    except OSError as exc:
        raise InputError(f"run path is unreadable: {run_id}") from exc
    if (
        stat.S_ISLNK(run_stat.st_mode)
        or bool(getattr(run_stat, "st_file_attributes", 0) & 0x400)
        or not stat.S_ISDIR(run_stat.st_mode)
    ):
        raise InputError(f"run not found: {run_id}")
    validate_state_path_no_symlinks(run_dir, allow_missing_leaf=False)
    finalized_stat = _safe_stat_artifact(run_dir / "finalized.json")
    if finalized_stat is None:
        raise InputError(f"run is not finalized (missing finalized.json): {run_id}")
    if finalized_stat.st_size > 5_000_000:
        raise InputError(f"finalized.json too large: {run_id}")
    return run_dir


def export_preview(
    run_id: str,
    output_path: Path,
    state_dir: Path,
    privacy_mode: str = "strict_local",
) -> ExportManifest:
    """Export a finalized run as a self-contained static HTML bundle."""
    if privacy_mode not in {"strict_local", "redacted_remote", "explicit_remote"}:
        raise InputError(
            "privacy_mode must be one of strict_local, redacted_remote, explicit_remote"
        )
    run_dir = validate_preview_run(run_id, state_dir)

    payload = _load_run_payload(run_dir)

    # strict_local must enforce redaction defense-in-depth even if upstream
    # already scrubbed.  Other modes still scrub for consistency.
    scrubbed_payload = _scrub_value(payload)
    if not isinstance(scrubbed_payload, dict):
        raise InputError("export payload must be a JSON object after scrubbing")
    scrubbed_run_payload = cast("dict[str, Any]", scrubbed_payload)

    concept_entries = _filter_concepts(state_dir, run_id, payload)
    scrubbed_concepts = [_scrub_value(entry) for entry in concept_entries]

    run_json = json.dumps(scrubbed_run_payload, ensure_ascii=False, indent=2, sort_keys=True)
    concepts_json = json.dumps(
        {"schema_version": 1, "run_id": run_id, "concepts": scrubbed_concepts},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    readme_text = "\n".join(_README_LINES) + "\n"

    file_payloads: list[tuple[str, bytes]] = [
        ("README.txt", readme_text.encode("utf-8")),
        ("index.html", _INDEX_HTML.encode("utf-8")),
        ("data/run.json", run_json.encode("utf-8")),
        ("data/concepts.json", concepts_json.encode("utf-8")),
    ]

    file_entries: list[tuple[str, str, int]] = []
    for rel_path, data in file_payloads:
        safe_write_export_file(output_path, rel_path, data)
        file_entries.append(_file_entry(rel_path, data))

    total_bytes = sum(size for _, _, size in file_entries)
    digest = _compute_top_level_digest(file_entries)

    manifest = ExportManifest(
        run_id=run_id,
        file_count=len(file_entries),
        total_bytes=total_bytes,
        digest=digest,
        created_at_utc=_export_created_at(scrubbed_run_payload),
        privacy_mode=privacy_mode,
        files=tuple(file_entries),
    )
    manifest_bytes = (
        json.dumps(manifest.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    safe_write_export_file(output_path, "manifest.json", manifest_bytes)
    return manifest


def _export_created_at(payload: dict[str, Any]) -> str:
    finalized_raw = payload.get("finalized")
    if isinstance(finalized_raw, dict):
        finalized = cast("dict[str, Any]", finalized_raw)
        for key in ("finalized_at", "timestamp", "created_at_utc"):
            value = finalized.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "1970-01-01T00:00:00Z"


_ZIP_MAX_ENTRY_BYTES = 50_000_000


def build_zip_bytes(output_root: Path) -> bytes:
    """Build a deterministic zip archive from an exported preview directory.

    Only files listed in ``manifest.json`` (plus the manifest itself) are
    included; the output directory is never walked.  Each entry must be a
    regular file (no symlinks / reparse points) and its on-disk SHA-256
    must match the manifest entry to guard against TOCTOU swaps.
    """
    output_root = validate_export_directory(output_root, create=False)

    manifest_path = output_root / "manifest.json"
    manifest_text = _read_text(manifest_path, max_bytes=10_000_000)
    if manifest_text is None:
        raise InputError("export output root missing manifest.json")
    manifest_payload = safe_json_loads(manifest_text)
    if not isinstance(manifest_payload, dict):
        raise InputError("manifest.json must be a JSON object")
    manifest_dict = cast("dict[str, Any]", manifest_payload)
    manifest_digest_raw = manifest_dict.get("digest")
    if not isinstance(manifest_digest_raw, str) or not _is_sha256_hex(manifest_digest_raw):
        raise InputError("manifest.json digest must be a SHA-256 hex string")
    manifest_files_raw = manifest_dict.get("files")
    if not isinstance(manifest_files_raw, list):
        raise InputError("manifest.json 'files' field must be a list")

    allowlist: list[tuple[str, str, int]] = []
    seen_rel: set[str] = set()
    for entry in cast("list[Any]", manifest_files_raw):
        if not isinstance(entry, dict):
            raise InputError("manifest.json file entry must be an object")
        entry_dict = cast("dict[str, Any]", entry)
        rel_raw = entry_dict.get("path")
        sha_raw = entry_dict.get("sha256")
        size_raw = entry_dict.get("size")
        if not isinstance(rel_raw, str) or not isinstance(sha_raw, str):
            raise InputError("manifest.json file entry must have string path and sha256")
        if not _is_sha256_hex(sha_raw):
            raise InputError("manifest.json file entry sha256 must be a SHA-256 hex string")
        if not isinstance(size_raw, int) or size_raw < 0:
            raise InputError("manifest.json file entry must have non-negative integer size")
        segments = validate_export_relative_path(rel_raw)
        rel = "/".join(segments)
        if rel in seen_rel:
            raise InputError(f"manifest.json has duplicate file path: {rel_raw}")
        seen_rel.add(rel)
        allowlist.append((rel, sha_raw, size_raw))

    computed_manifest_digest = _compute_top_level_digest(allowlist)
    if computed_manifest_digest != manifest_digest_raw:
        raise InputError("manifest.json digest mismatch")

    files: list[tuple[str, bytes]] = []
    for rel, expected_sha, expected_size in allowlist:
        file_path = ensure_output_contained(output_root, output_root / rel)
        data = _read_regular_bytes(
            file_path,
            label="export zip entry",
            max_bytes=_ZIP_MAX_ENTRY_BYTES,
        )
        if data is None:
            raise InputError(f"export zip entry missing: {rel}")
        if len(data) != expected_size:
            raise InputError(f"export zip entry size mismatch: {rel}")
        if _sha256_bytes(data) != expected_sha:
            raise InputError(f"export zip entry digest mismatch: {rel}")
        files.append((rel, data))

    # Append manifest itself last; it is not listed in its own files array.
    manifest_stat = reject_leaf_symlink_or_reparse(manifest_path, label="export manifest")
    if not stat.S_ISREG(manifest_stat.st_mode):
        raise InputError("manifest.json must be a regular file")
    files.append(("manifest.json", manifest_text.encode("utf-8")))

    files.sort(key=lambda item: item[0])

    buf = io.BytesIO()
    with zipfile.ZipFile(
        buf, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False
    ) as archive:
        for rel, data in files:
            info = zipfile.ZipInfo(filename=rel)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return buf.getvalue()


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


__all__ = ["ExportManifest", "build_zip_bytes", "export_preview", "validate_preview_run"]
