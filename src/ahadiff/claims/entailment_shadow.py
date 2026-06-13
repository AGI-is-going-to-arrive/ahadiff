"""Write entailment shadow artifacts for in-flight runs.

The learn pipeline holds the repo write lock while producing run artifacts. The
finalized marker is checked both at entry and immediately before the final
artifact replace; the second check is defense-in-depth for out-of-band writers
and practically closes the residual write window.
"""

from __future__ import annotations

import json
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from ahadiff.claims.entailment import analyze_claim_predicates, confidence_band
from ahadiff.claims.extract import (
    load_line_map_records,
    load_text_map,
    read_artifact_text_no_follow,
)
from ahadiff.contracts import ClaimRecord
from ahadiff.core.atomic_replace import replace_with_retry
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import (
    atomic_write_state_text,
    ensure_state_parent_dir,
    validate_state_path_no_symlinks,
)
from ahadiff.eval.results import finalized_marker_path

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from ahadiff.git.line_map import FileLineMap


ENTAILMENT_SHADOW_ARTIFACT = "entailment.jsonl"
ENTAILMENT_SHADOW_SCHEMA = "ahadiff.entailment_shadow"
ENTAILMENT_SHADOW_SCHEMA_VERSION = 1
_MAX_CLAIMS_JSONL_BYTES = 50 * 1024 * 1024
_SAFE_REASON_PREFIX_RE = re.compile(r"^[a-z0-9_]+")
_MALFORMED_ARTIFACT_ERRORS = (KeyError, TypeError, ValueError, IndexError, AttributeError)
_UNSAFE_PATH_REDACTION = "unsafe_path_redacted"


@dataclass(frozen=True)
class EntailmentShadowWriteResult:
    path: Path
    rows_written: int
    warnings: tuple[str, ...] = ()


def build_entailment_shadow_rows(
    *,
    run_id: str,
    claims: Iterable[ClaimRecord],
    line_maps: Iterable[FileLineMap],
    before_text_by_path: Mapping[str, str],
    after_text_by_path: Mapping[str, str],
    include_route_key: bool = False,
) -> tuple[dict[str, object], ...]:
    effective_before_text = _before_text_with_known_empty_new_files(
        line_maps=line_maps,
        before_text_by_path=before_text_by_path,
        after_text_by_path=after_text_by_path,
    )
    rows: list[dict[str, object]] = []
    for claim in claims:
        evidence_items = analyze_claim_predicates(
            claim.text,
            claim.source_hunks,
            effective_before_text,
            after_text_by_path,
        )
        rows.extend(
            _row_from_evidence(
                run_id=run_id,
                claim=claim,
                evidence=item,
                include_route_key=include_route_key,
            )
            for item in evidence_items
        )
    return tuple(rows)


def write_entailment_shadow_jsonl(
    path: Path,
    *,
    run_id: str,
    claims: Iterable[ClaimRecord],
    line_maps: Iterable[FileLineMap],
    before_text_by_path: Mapping[str, str],
    after_text_by_path: Mapping[str, str],
    overwrite: bool = False,
) -> Path:
    if path.exists() and not overwrite:
        raise InputError(f"refusing to overwrite existing file: {path}")
    rows = build_entailment_shadow_rows(
        run_id=run_id,
        claims=claims,
        line_maps=line_maps,
        before_text_by_path=before_text_by_path,
        after_text_by_path=after_text_by_path,
    )
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    atomic_write_state_text(path, payload)
    return path


def write_entailment_shadow_from_run_artifacts(
    run_path: Path,
    *,
    run_id: str,
    overwrite: bool = False,
) -> EntailmentShadowWriteResult:
    output_path = run_path / ENTAILMENT_SHADOW_ARTIFACT
    if _run_bears_finalized_marker(run_path):
        return EntailmentShadowWriteResult(
            path=output_path,
            rows_written=0,
            warnings=("finalized_run_write_refused",),
        )
    try:
        claims = _load_claim_records(run_path / "claims.jsonl")
        matched_claims = tuple(claim for claim in claims if claim.run_id == run_id)
        if not matched_claims:
            return EntailmentShadowWriteResult(
                path=output_path,
                rows_written=0,
                warnings=(f"stale claims.jsonl skipped: no claims matched run_id {run_id}",),
            )
        line_maps = load_line_map_records(run_path / "line_map.json")
        before_text_by_path = load_text_map(
            run_path / "before_text_by_path.json",
            expected_artifact="before_text_by_path",
        )
        after_text_by_path = load_text_map(
            run_path / "after_text_by_path.json",
            expected_artifact="after_text_by_path",
        )
    except _MALFORMED_ARTIFACT_ERRORS:
        return EntailmentShadowWriteResult(
            path=output_path,
            rows_written=0,
            warnings=("malformed_artifact",),
        )
    except InputError as exc:
        return EntailmentShadowWriteResult(
            path=output_path,
            rows_written=0,
            warnings=(str(exc),),
        )
    try:
        rows = build_entailment_shadow_rows(
            run_id=run_id,
            claims=matched_claims,
            line_maps=line_maps,
            before_text_by_path=before_text_by_path,
            after_text_by_path=after_text_by_path,
        )
        if output_path.exists() and not overwrite:
            raise InputError(f"refusing to overwrite existing file: {output_path}")
        payload = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        )
        if not _atomic_write_shadow_text_unless_finalized(run_path, output_path, payload):
            return EntailmentShadowWriteResult(
                path=output_path,
                rows_written=0,
                warnings=("finalized_run_write_refused",),
            )
        return EntailmentShadowWriteResult(path=output_path, rows_written=len(rows))
    except InputError as exc:
        return EntailmentShadowWriteResult(
            path=output_path,
            rows_written=0,
            warnings=(str(exc),),
        )


def _before_text_with_known_empty_new_files(
    *,
    line_maps: Iterable[FileLineMap],
    before_text_by_path: Mapping[str, str],
    after_text_by_path: Mapping[str, str],
) -> dict[str, str]:
    effective = dict(before_text_by_path)
    for item in line_maps:
        if item.change_kind != "added":
            continue
        candidate_paths = [item.display_path]
        if item.new_path is not None:
            candidate_paths.append(item.new_path)
        for path in candidate_paths:
            if path in after_text_by_path:
                effective[path] = ""
    return effective


def _row_from_evidence(
    *,
    run_id: str,
    claim: ClaimRecord,
    evidence: Any,
    include_route_key: bool = False,
) -> dict[str, object]:
    row: dict[str, object] = {
        "schema": ENTAILMENT_SHADOW_SCHEMA,
        "schema_version": ENTAILMENT_SHADOW_SCHEMA_VERSION,
        "run_id": run_id,
        "claim_id": claim.claim_id,
        "mode": "shadow",
        "applicability": _applicability_from_reason(str(evidence.reason)),
        "outcome": evidence.outcome,
        "predicate": evidence.predicate,
        "file": _serialized_file_path(evidence.file),
        "side": evidence.side,
        "start": evidence.start,
        "end": evidence.end,
        "reason": _serialized_reason_token(str(evidence.reason)),
        "confidence": confidence_band(float(evidence.confidence)),
    }
    if include_route_key and isinstance(evidence.route_key, str):
        row["route_key"] = evidence.route_key
    return row


def _applicability_from_reason(reason: str) -> str:
    if reason.startswith("not_applicable:"):
        return "not_applicable"
    if reason.startswith("inconclusive:"):
        return "inconclusive"
    return "applicable"


def _serialized_reason_token(reason: str) -> str:
    match = _SAFE_REASON_PREFIX_RE.match(reason)
    if match is None:
        return "kernel_reason_redacted"
    return match.group(0) or "kernel_reason_redacted"


def _serialized_file_path(value: object) -> str:
    if not isinstance(value, str) or not _is_safe_repo_relative_posix_path(value):
        return _UNSAFE_PATH_REDACTION
    return value


_MAX_SERIALIZED_PATH_CHARS = 512
_MAX_SERIALIZED_PATH_SEGMENT_CHARS = 255


def _is_safe_repo_relative_posix_path(value: str) -> bool:
    if not value or len(value) > _MAX_SERIALIZED_PATH_CHARS or not value.isprintable():
        return False
    if value.startswith(("/", "~")) or "\\" in value or ":" in value or "//" in value:
        return False
    return all(
        segment not in {"", ".", ".."} and len(segment) <= _MAX_SERIALIZED_PATH_SEGMENT_CHARS
        for segment in value.split("/")
    )


def _run_bears_finalized_marker(run_path: Path) -> bool:
    marker_path = finalized_marker_path(run_path)
    return marker_path.exists() or marker_path.is_symlink()


def _atomic_write_shadow_text_unless_finalized(run_path: Path, path: Path, text: str) -> bool:
    ensure_state_parent_dir(path)
    validate_state_path_no_symlinks(path, allow_missing_leaf=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            validate_state_path_no_symlinks(tmp_path, allow_missing_leaf=True)
            tmp_file.write(text)
        validate_state_path_no_symlinks(path, allow_missing_leaf=True)
        if _run_bears_finalized_marker(run_path):
            with suppress(OSError):
                tmp_path.unlink(missing_ok=True)
            return False
        replace_with_retry(tmp_path, path)
        tmp_path = None
        validate_state_path_no_symlinks(path, allow_missing_leaf=False)
        return True
    except Exception:
        if tmp_path is not None:
            with suppress(OSError):
                tmp_path.unlink(missing_ok=True)
        raise


def _load_claim_records(path: Path) -> tuple[ClaimRecord, ...]:
    text = read_artifact_text_no_follow(path, max_bytes=_MAX_CLAIMS_JSONL_BYTES)
    records: list[ClaimRecord] = []
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = safe_json_loads(stripped, max_input_bytes=_MAX_CLAIMS_JSONL_BYTES)
        except (json.JSONDecodeError, ValueError) as exc:
            raise InputError(f"invalid claims.jsonl line {index}: {exc}") from exc
        if not isinstance(payload, dict):
            raise InputError(f"claims.jsonl line {index} must be a JSON object")
        try:
            records.append(ClaimRecord.model_validate(cast("dict[str, Any]", payload)))
        except ValidationError as exc:
            raise InputError(f"invalid claims.jsonl line {index}: {exc}") from exc
    if not records:
        raise InputError(f"claims.jsonl did not contain any claim records: {path}")
    return tuple(records)


__all__ = [
    "ENTAILMENT_SHADOW_ARTIFACT",
    "ENTAILMENT_SHADOW_SCHEMA",
    "ENTAILMENT_SHADOW_SCHEMA_VERSION",
    "EntailmentShadowWriteResult",
    "build_entailment_shadow_rows",
    "write_entailment_shadow_from_run_artifacts",
    "write_entailment_shadow_jsonl",
]
