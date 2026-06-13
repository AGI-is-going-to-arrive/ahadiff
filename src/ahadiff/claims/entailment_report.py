"""Measure S1 entailment false positives over local run artifacts.

The scanner is intentionally read-only: it rebuilds P2 shadow rows in memory
for historical runs and writes only aggregate reports plus input hashes.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import math
import os
import stat
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from ahadiff.claims.entailment_shadow import build_entailment_shadow_rows
from ahadiff.claims.extract import load_line_map_records, load_symbol_records, load_text_map
from ahadiff.contracts import ClaimRecord
from ahadiff.core.atomic_replace import replace_with_retry
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


REPORT_SCHEMA = "ahadiff.s1_fp_coverage_report"
MANIFEST_SCHEMA = "ahadiff.s1_fp_sample_manifest"
SCHEMA_VERSION = 1

_MAX_JSON_OBJECT_BYTES = 1024 * 1024
_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_FINALIZED_ARTIFACTS = 64
_MAX_FINALIZED_ARTIFACT_DIRS = 64
_MAX_FINALIZED_ARTIFACTS_TOTAL_BYTES = 50 * 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_REQUIRED_HASH_ARTIFACTS = {
    "metadata_sha256": "metadata.json",
    "claims_sha256": "claims.jsonl",
    "patch_sha256": "patch.diff",
    "line_map_sha256": "line_map.json",
    "symbols_sha256": "symbols.json",
}
_FP_BUCKETS = (
    "partial_syntax",
    "decorator_scope",
    "nested_function",
    "comprehension",
    "multi_hunk",
    "rename",
    "binary",
    "docs_only",
    "path_mismatch",
    "unexplained",
)
_BINARY_EXTENSIONS = {
    ".avif",
    ".bin",
    ".bmp",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".webp",
    ".zip",
}
_DOC_EXTENSIONS = {".adoc", ".md", ".mdx", ".rst", ".txt"}
_ROUTE_MISS_PREDICATES = {"applicability", "claim"}
_ROUTE_HIT_PREDICATES = frozenset(
    {
        "assignment_literal_changed",
        "branch_added",
        "call_name_added",
        "import_added",
        "return_literal_added",
    }
)
_ROUTE_OUTCOMES = frozenset({"supported", "not_supported"})


@dataclass(frozen=True)
class EntailmentReportMetrics:
    total_runs: int
    claim_runs: int
    verified_claims: int
    route_hit_verified_claims: int
    false_positive_claims: int
    fp_rate: float
    wilson_95_ci: tuple[float, float]
    enforce: str
    advisory: str
    advisory_reason: str


@dataclass(frozen=True)
class EntailmentCorpusReport:
    metrics: EntailmentReportMetrics
    fp_buckets: dict[str, int]
    skip_reasons: dict[str, int]
    manifest_rows: tuple[dict[str, object], ...]
    runs_dir: str

    def to_json_dict(self) -> dict[str, object]:
        low, high = self.metrics.wilson_95_ci
        return {
            "schema": REPORT_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "runs_dir": self.runs_dir,
            "metrics": {
                "total_runs": self.metrics.total_runs,
                "claim_runs": self.metrics.claim_runs,
                "verified_claims": self.metrics.verified_claims,
                "route_hit_verified_claims": self.metrics.route_hit_verified_claims,
                "false_positive_claims": self.metrics.false_positive_claims,
                "fp_rate": self.metrics.fp_rate,
                "wilson_95_ci": {"low": low, "high": high},
                "enforce": self.metrics.enforce,
                "advisory": self.metrics.advisory,
                "advisory_reason": self.metrics.advisory_reason,
            },
            "fp_buckets": dict(sorted(self.fp_buckets.items())),
            "skip_reasons": dict(sorted(self.skip_reasons.items())),
            "notes": [
                "denominator=route_hit_verified_claims",
                "enforce is blocked by this measurement-only plan",
                "manifest stores hashes and skip tokens only",
            ],
        }


def scan_entailment_corpus(runs_dir: str | Path) -> EntailmentCorpusReport:
    root = Path(runs_dir)
    entries = _run_entries(root)
    total_runs = len(entries)
    claim_runs = 0
    verified_claims = 0
    route_hit_verified_claims = 0
    false_positive_claims = 0
    fp_buckets = _empty_fp_counter()
    skip_reasons: Counter[str] = Counter()
    manifest_rows: list[dict[str, object]] = []

    for run_path in entries:
        row = _base_manifest_row(root, run_path)
        skip_reason = _run_directory_skip_reason(run_path)
        if skip_reason is None:
            if _artifact_looks_present(run_path / "claims.jsonl"):
                claim_runs += 1
            _populate_required_hashes(row, run_path)
            skip_reason = _finalized_marker_skip_reason(run_path)
        if skip_reason is None:
            run_result = _scan_finalized_run(run_path)
            skip_reason = run_result.skip_reason
            row.update(dict(run_result.manifest_counts))
            verified_claims += run_result.verified_claims
            route_hit_verified_claims += run_result.route_hit_verified_claims
            false_positive_claims += run_result.false_positive_claims
            fp_buckets.update(run_result.fp_buckets)

        if skip_reason is not None:
            row["skip_reason"] = skip_reason
            skip_reasons[skip_reason] += 1
        manifest_rows.append(row)

    fp_rate = (
        false_positive_claims / route_hit_verified_claims if route_hit_verified_claims else 0.0
    )
    wilson = wilson_95_ci(false_positive_claims, route_hit_verified_claims)
    advisory, advisory_reason = _advisory_status(
        route_hit_verified_claims=route_hit_verified_claims,
        fp_rate=fp_rate,
        fp_buckets=fp_buckets,
    )
    metrics = EntailmentReportMetrics(
        total_runs=total_runs,
        claim_runs=claim_runs,
        verified_claims=verified_claims,
        route_hit_verified_claims=route_hit_verified_claims,
        false_positive_claims=false_positive_claims,
        fp_rate=fp_rate,
        wilson_95_ci=wilson,
        enforce="blocked",
        advisory=advisory,
        advisory_reason=advisory_reason,
    )
    return EntailmentCorpusReport(
        metrics=metrics,
        fp_buckets={bucket: int(fp_buckets[bucket]) for bucket in _FP_BUCKETS},
        skip_reasons=dict(sorted(skip_reasons.items())),
        manifest_rows=tuple(manifest_rows),
        runs_dir=_display_path(root),
    )


def write_entailment_report(
    *,
    runs_dir: str | Path,
    out_json: str | Path,
    out_markdown: str | Path,
    sample_manifest: str | Path,
) -> EntailmentCorpusReport:
    report = scan_entailment_corpus(runs_dir)
    _atomic_write_text(
        Path(out_json),
        json.dumps(report.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write_text(Path(out_markdown), _render_markdown(report))
    _atomic_write_text(
        Path(sample_manifest),
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in report.manifest_rows
        ),
    )
    return report


def wilson_95_ci(false_positives: int, denominator: int) -> tuple[float, float]:
    if denominator <= 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    phat = false_positives / denominator
    denom = 1.0 + z * z / denominator
    center = (phat + z * z / (2.0 * denominator)) / denom
    margin = (
        z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * denominator)) / denominator) / denom
    )
    return (max(0.0, center - margin), min(1.0, center + margin))


def _empty_fp_counter() -> Counter[str]:
    return Counter(dict.fromkeys(_FP_BUCKETS, 0))


def _empty_manifest_counts() -> dict[str, object]:
    return {}


@dataclass(frozen=True)
class _RunScanResult:
    verified_claims: int = 0
    route_hit_verified_claims: int = 0
    false_positive_claims: int = 0
    fp_buckets: Counter[str] = field(default_factory=_empty_fp_counter)
    skip_reason: str | None = None
    manifest_counts: Mapping[str, object] = field(default_factory=_empty_manifest_counts)


def _scan_finalized_run(run_path: Path) -> _RunScanResult:
    try:
        _load_json_artifact(run_path / "metadata.json", max_bytes=_MAX_JSON_OBJECT_BYTES)
        claims = _load_claim_records(run_path / "claims.jsonl", run_id=run_path.name)
        line_maps = load_line_map_records(run_path / "line_map.json")
        load_symbol_records(run_path / "symbols.json")
        _read_artifact_bytes(run_path / "patch.diff", max_bytes=_MAX_ARTIFACT_BYTES)
        before_text_by_path = load_text_map(
            run_path / "before_text_by_path.json",
            expected_artifact="before_text_by_path",
        )
        after_text_by_path = load_text_map(
            run_path / "after_text_by_path.json",
            expected_artifact="after_text_by_path",
        )
    except _SkipRun as exc:
        return _RunScanResult(skip_reason=exc.reason)
    except InputError as exc:
        return _RunScanResult(skip_reason=_skip_reason_from_input_error(exc))
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return _RunScanResult(skip_reason="malformed_artifact")

    verified = tuple(claim for claim in claims if claim.status == "verified")
    if not claims:
        return _RunScanResult(skip_reason="missing_claims")
    if not verified:
        return _RunScanResult(
            manifest_counts={
                "claim_count": len(claims),
                "verified_claims": 0,
                "route_hit_verified_claims": 0,
                "false_positive_claims": 0,
            }
        )

    rows = build_entailment_shadow_rows(
        run_id=run_path.name,
        claims=verified,
        line_maps=line_maps,
        before_text_by_path=before_text_by_path,
        after_text_by_path=after_text_by_path,
        include_route_key=True,
    )
    rows_by_claim: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        claim_id = row.get("claim_id")
        if isinstance(claim_id, str):
            rows_by_claim[claim_id].append(dict(row))

    route_hit = 0
    fp = 0
    fp_buckets = _empty_fp_counter()
    claims_by_id = {claim.claim_id: claim for claim in verified}
    for claim_id, claim in claims_by_id.items():
        claim_rows = rows_by_claim.get(claim_id, [])
        if not _is_route_hit(claim_rows):
            continue
        route_hit += 1
        if _is_false_positive(claim_rows):
            fp += 1
            fp_buckets[_fp_bucket_for_claim(claim, claim_rows)] += 1

    return _RunScanResult(
        verified_claims=len(verified),
        route_hit_verified_claims=route_hit,
        false_positive_claims=fp,
        fp_buckets=fp_buckets,
        manifest_counts={
            "claim_count": len(claims),
            "verified_claims": len(verified),
            "route_hit_verified_claims": route_hit,
            "false_positive_claims": fp,
        },
    )


def _load_claim_records(path: Path, *, run_id: str) -> tuple[ClaimRecord, ...]:
    try:
        text = _read_artifact_text(path, max_bytes=_MAX_ARTIFACT_BYTES)
    except _SkipRun:
        raise
    except InputError as exc:
        reason = _skip_reason_from_input_error(exc)
        if reason == "missing_artifact":
            reason = "missing_claims"
        raise _SkipRun(reason) from exc
    records: list[ClaimRecord] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = safe_json_loads(stripped, max_input_bytes=_MAX_ARTIFACT_BYTES)
        except (JSONDecodeError, ValueError) as exc:
            raise _SkipRun("malformed_claims") from exc
        if not isinstance(payload, dict):
            raise _SkipRun("bad_schema_claims")
        try:
            record = ClaimRecord.model_validate(cast("dict[str, Any]", payload))
        except ValidationError as exc:
            raise _SkipRun("bad_schema_claims") from exc
        if record.run_id == run_id:
            records.append(record)
    if not records:
        raise _SkipRun("stale_claims")
    return tuple(records)


def _load_json_artifact(path: Path, *, max_bytes: int) -> dict[str, Any]:
    try:
        text = _read_artifact_text(path, max_bytes=max_bytes)
        payload = safe_json_loads(text, max_input_bytes=max_bytes)
    except (JSONDecodeError, ValueError) as exc:
        raise _SkipRun(f"malformed_{path.stem}") from exc
    if not isinstance(payload, dict):
        raise _SkipRun(f"bad_schema_{path.stem}")
    return cast("dict[str, Any]", payload)


def _is_route_hit(rows: Sequence[Mapping[str, object]]) -> bool:
    return any(_is_route_predicate_row(row) for row in rows)


def _is_false_positive(rows: Sequence[Mapping[str, object]]) -> bool:
    route_rows = [row for row in rows if _is_route_predicate_row(row)]
    supported_route_keys = {
        _route_key_for_row(row) for row in route_rows if row.get("outcome") == "supported"
    }
    return any(
        row.get("outcome") == "not_supported"
        and _route_key_for_row(row) not in supported_route_keys
        for row in route_rows
    )


def _route_key_for_row(row: Mapping[str, object]) -> str:
    route_key = row.get("route_key")
    if isinstance(route_key, str) and route_key:
        return route_key
    return str(row.get("predicate", ""))


def _is_route_predicate_row(row: Mapping[str, object]) -> bool:
    return (
        row.get("applicability") == "applicable"
        and row.get("predicate") in _ROUTE_HIT_PREDICATES
        and row.get("outcome") in _ROUTE_OUTCOMES
    )


def _fp_bucket_for_claim(claim: ClaimRecord, rows: Sequence[Mapping[str, object]]) -> str:
    reason_values = {str(row.get("reason", "")) for row in rows}
    predicate_values = {str(row.get("predicate", "")) for row in rows}
    lowered_text = claim.text.casefold()
    paths = [hunk.file for hunk in claim.source_hunks]
    suffixes = {Path(path).suffix.casefold() for path in paths}
    if "partial_syntax" in reason_values or "syntax" in predicate_values:
        return "partial_syntax"
    if len(claim.source_hunks) > 1:
        return "multi_hunk"
    if "decorator" in lowered_text or "register" in lowered_text:
        return "decorator_scope"
    if "nested" in lowered_text or "inner" in lowered_text:
        return "nested_function"
    if "comprehension" in lowered_text or "normalize" in lowered_text:
        return "comprehension"
    if not claim.source_hunks:
        return "rename"
    if suffixes and suffixes <= _BINARY_EXTENSIONS:
        return "binary"
    if suffixes and suffixes <= _DOC_EXTENSIONS:
        return "docs_only"
    if reason_values & {"not_applicable", "inconclusive"}:
        return "path_mismatch"
    return "unexplained"


def _advisory_status(
    *,
    route_hit_verified_claims: int,
    fp_rate: float,
    fp_buckets: Mapping[str, int],
) -> tuple[str, str]:
    if route_hit_verified_claims == 0:
        return ("blocked", "no_route_hit_verified_claims")
    if fp_rate >= 0.10:
        return ("blocked", "fp_rate_at_or_above_10_percent")
    if fp_buckets.get("unexplained", 0):
        return ("blocked", "unexplained_false_positive_buckets")
    return ("ready", "fp_rate_below_10_percent_with_explainable_buckets")


def _base_manifest_row(runs_dir: Path, run_path: Path) -> dict[str, object]:
    return {
        "schema": MANIFEST_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_path.name,
        "run_path": _display_path(run_path, anchor=runs_dir.parent),
        "metadata_sha256": None,
        "claims_sha256": None,
        "patch_sha256": None,
        "line_map_sha256": None,
        "symbols_sha256": None,
        "claim_count": 0,
        "verified_claims": 0,
        "route_hit_verified_claims": 0,
        "false_positive_claims": 0,
        "skip_reason": None,
    }


def _populate_required_hashes(row: dict[str, object], run_path: Path) -> None:
    for key, artifact_name in _REQUIRED_HASH_ARTIFACTS.items():
        try:
            row[key] = hashlib.sha256(
                _read_artifact_bytes(run_path / artifact_name, max_bytes=_MAX_ARTIFACT_BYTES)
            ).hexdigest()
        except (InputError, _SkipRun, OSError, UnicodeDecodeError):
            row[key] = None


def _artifact_looks_present(path: Path) -> bool:
    try:
        os.lstat(path)
    except OSError:
        return False
    return True


def _run_entries(root: Path) -> tuple[Path, ...]:
    try:
        root_stat = os.lstat(root)
    except OSError:
        return ()
    if (
        stat.S_ISLNK(root_stat.st_mode)
        or _has_windows_reparse_point(root_stat)
        or not stat.S_ISDIR(root_stat.st_mode)
    ):
        return ()
    try:
        return tuple(
            sorted(
                (path for path in root.iterdir() if not path.name.startswith(".")),
                key=lambda path: path.name,
            )
        )
    except OSError:
        return ()


def _run_directory_skip_reason(run_path: Path) -> str | None:
    try:
        path_stat = os.lstat(run_path)
    except OSError:
        return "unreadable_run_directory"
    if stat.S_ISLNK(path_stat.st_mode):
        return "unsafe_run_directory_symlink"
    if _has_windows_reparse_point(path_stat):
        return "unsafe_run_directory_reparse"
    if not stat.S_ISDIR(path_stat.st_mode):
        return "not_a_run_directory"
    return None


def _finalized_marker_skip_reason(run_path: Path) -> str | None:
    try:
        marker = _load_json_artifact(run_path / "finalized.json", max_bytes=_MAX_JSON_OBJECT_BYTES)
    except _SkipRun as exc:
        if exc.reason in {"malformed_finalized", "bad_schema_finalized"}:
            return exc.reason
        if exc.reason.startswith("unsafe_artifact_") or exc.reason == "oversized_artifact":
            return exc.reason
        return "missing_finalized_marker"
    except InputError as exc:
        reason = _skip_reason_from_input_error(exc)
        if reason.startswith("unsafe_artifact_") or reason == "oversized_artifact":
            return reason
        return "missing_finalized_marker"

    if marker.get("run_id") != run_path.name:
        return "stale_finalized_marker"
    if not isinstance(marker.get("event_id"), str) or not marker["event_id"]:
        return "stale_finalized_marker"
    if not isinstance(marker.get("finalized_at"), str) or not marker["finalized_at"]:
        return "stale_finalized_marker"
    if not isinstance(marker.get("artifact_count"), int) or marker["artifact_count"] < 0:
        return "stale_finalized_marker"
    if not isinstance(marker.get("checksum"), str) or not marker["checksum"]:
        return "stale_finalized_marker"
    try:
        artifact_count, checksum = _bounded_finalized_artifact_digest(run_path)
    except InputError as exc:
        return _skip_reason_from_input_error(exc)
    except OSError:
        return "unreadable_artifact"
    if marker["artifact_count"] != artifact_count or marker["checksum"] != checksum:
        return "stale_finalized_marker"
    return None


def _bounded_finalized_artifact_digest(run_path: Path) -> tuple[int, str]:
    artifact_paths: list[tuple[str, Path, os.stat_result]] = []
    stack = [run_path]
    dirs_seen = 0
    total_bytes = 0
    while stack:
        current = stack.pop()
        dirs_seen += 1
        if dirs_seen > _MAX_FINALIZED_ARTIFACT_DIRS:
            raise InputError("finalized run has too many artifact directories")
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise InputError("finalized run artifact directory is unreadable") from exc
        for entry in entries:
            path = Path(entry.path)
            relative_path = path.relative_to(run_path).as_posix()
            if relative_path == "finalized.json" or path.name.startswith("."):
                continue
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise InputError("finalized run artifact is unreadable") from exc
            if stat.S_ISLNK(entry_stat.st_mode):
                raise InputError("refusing symlink artifact in finalized run")
            if _has_windows_reparse_point(entry_stat):
                raise InputError("refusing Windows reparse point artifact in finalized run")
            if stat.S_ISDIR(entry_stat.st_mode):
                stack.append(path)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                continue
            _reject_hardlinked_regular_file(
                entry_stat,
                message="refusing hardlinked artifact in finalized run",
            )
            if len(artifact_paths) >= _MAX_FINALIZED_ARTIFACTS:
                raise InputError("finalized run has too many artifacts")
            if entry_stat.st_size > _MAX_ARTIFACT_BYTES:
                raise InputError("finalized run artifact exceeds size limit")
            total_bytes += entry_stat.st_size
            if total_bytes > _MAX_FINALIZED_ARTIFACTS_TOTAL_BYTES:
                raise InputError("finalized run artifacts exceed total size limit")
            artifact_paths.append((relative_path, path, entry_stat))
    chunks = [
        relative_path.encode("utf-8")
        + b"\n"
        + _hash_bounded_finalized_artifact(path, expected_stat).encode("ascii")
        for relative_path, path, expected_stat in sorted(artifact_paths)
    ]
    return len(chunks), hashlib.sha256(b"\n---\n".join(chunks)).hexdigest()


def _hash_bounded_finalized_artifact(path: Path, expected_stat: os.stat_result) -> str:
    path_stat = os.lstat(path)
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError("refusing symlink artifact in finalized run")
    if _has_windows_reparse_point(path_stat):
        raise InputError("refusing Windows reparse point artifact in finalized run")
    _reject_hardlinked_regular_file(
        path_stat,
        message="refusing hardlinked artifact in finalized run",
    )
    if (path_stat.st_dev, path_stat.st_ino) != (expected_stat.st_dev, expected_stat.st_ino):
        raise InputError("finalized run artifact changed during validation")
    return hashlib.sha256(_read_artifact_bytes(path, max_bytes=_MAX_ARTIFACT_BYTES)).hexdigest()


def _read_artifact_text(path: Path, *, max_bytes: int) -> str:
    try:
        return _read_artifact_bytes(path, max_bytes=max_bytes).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError("artifact file is not valid UTF-8") from exc


def _read_artifact_bytes(path: Path, *, max_bytes: int) -> bytes:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        raise InputError("artifact file does not exist") from None
    except OSError as exc:
        raise InputError("artifact file is unreadable") from exc
    _validate_artifact_stat(path_stat)
    if path_stat.st_size > max_bytes:
        raise InputError("artifact file too large")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError("artifact file must not be a symlink") from exc
        raise InputError("artifact file is unreadable") from exc
    try:
        file_stat = os.fstat(fd)
        _validate_artifact_stat(file_stat)
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError("artifact file changed during validation")
        if file_stat.st_size > max_bytes:
            raise InputError("artifact file too large")
        chunks: list[bytes] = []
        total_bytes = 0
        while True:
            chunk = os.read(fd, min(65_536, max_bytes + 1 - total_bytes))
            if not chunk:
                break
            chunks.append(chunk)
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise InputError("artifact file too large")
        return b"".join(chunks)
    except InputError:
        raise
    except OSError as exc:
        raise InputError("artifact file is unreadable") from exc
    finally:
        os.close(fd)


def _validate_artifact_stat(path_stat: os.stat_result) -> None:
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError("artifact file must not be a symlink")
    if _has_windows_reparse_point(path_stat):
        raise InputError("artifact file must not be a Windows reparse point or junction")
    if not stat.S_ISREG(path_stat.st_mode):
        raise InputError("artifact file must be a regular file")
    _reject_hardlinked_regular_file(path_stat, message="artifact file must not be a hardlink")


def _reject_hardlinked_regular_file(path_stat: os.stat_result, *, message: str) -> None:
    if stat.S_ISREG(path_stat.st_mode) and getattr(path_stat, "st_nlink", 1) > 1:
        raise InputError(message)


def _has_windows_reparse_point(path_stat: object) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _skip_reason_from_input_error(exc: InputError) -> str:
    message = str(exc).casefold()
    if "symlink" in message:
        return "unsafe_artifact_symlink"
    if "reparse" in message or "junction" in message:
        return "unsafe_artifact_reparse"
    if "hardlink" in message:
        return "unsafe_artifact_hardlink"
    if "too large" in message or "size limit" in message:
        return "oversized_artifact"
    if "does not exist" in message:
        return "missing_artifact"
    if "line_map schema" in message or "line_map schema_version" in message:
        return "bad_schema_line_map"
    if "symbols schema" in message or "symbols schema_version" in message:
        return "bad_schema_symbols"
    if "invalid json" in message:
        return "malformed_artifact"
    return "malformed_artifact"


def _display_path(path: Path, *, anchor: Path | None = None) -> str:
    base = anchor or Path.cwd()
    try:
        return path.resolve(strict=False).relative_to(base.resolve(strict=False)).as_posix()
    except ValueError:
        if path.parent.name:
            return f"{path.parent.name}/{path.name}"
        return path.name


def _render_markdown(report: EntailmentCorpusReport) -> str:
    metrics = report.metrics
    low, high = metrics.wilson_95_ci
    lines = [
        "# S1 FP Coverage Report",
        "",
        "## Summary",
        "",
        f"- total_runs={metrics.total_runs}",
        f"- claim_runs={metrics.claim_runs}",
        f"- verified={metrics.verified_claims}",
        f"- route_hit={metrics.route_hit_verified_claims}",
        f"- fp={metrics.false_positive_claims}",
        f"- fp_rate={metrics.fp_rate:.6f}",
        f"- wilson_ci=<{low:.6f},{high:.6f}>",
        f"- enforce={metrics.enforce}",
        f"- advisory={metrics.advisory}",
        f"- advisory_reason={metrics.advisory_reason}",
        "",
        "## FP Buckets",
        "",
    ]
    lines.extend(f"- {bucket}={report.fp_buckets.get(bucket, 0)}" for bucket in _FP_BUCKETS)
    lines.extend(["", "## Skip Reasons", ""])
    if report.skip_reasons:
        lines.extend(f"- {reason}={count}" for reason, count in sorted(report.skip_reasons.items()))
    else:
        lines.append("- none=0")
    lines.extend(
        [
            "",
            "## Definitions",
            "",
            "- route_hit: a verified claim whose kernel rows contain at least one row with"
            ' applicability=="applicable" and a real predicate (placeholder predicates'
            " excluded); only these claims enter the FP denominator",
            "- fp: a route-hit verified claim with at least one route key whose rows include"
            ' outcome=="not_supported" and no matching outcome=="supported"',
            "- verified claims without any applicable kernel row are counted in `verified` but"
            " excluded from the denominator",
            "",
            "## Boundaries",
            "",
            "- denominator=route_hit_verified_claims",
            "- enforce=blocked for this measurement-only plan",
            "- report files contain hashes and aggregate counts, not raw artifact content",
        ]
    )
    return "\n".join(lines) + "\n"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(text)
        replace_with_retry(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


class _SkipRun(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure S1 entailment FP coverage")
    parser.add_argument("--runs-dir", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-markdown", required=True)
    parser.add_argument("--sample-manifest", required=True)
    args = parser.parse_args(argv)
    write_entailment_report(
        runs_dir=Path(args.runs_dir),
        out_json=Path(args.out_json),
        out_markdown=Path(args.out_markdown),
        sample_manifest=Path(args.sample_manifest),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EntailmentCorpusReport",
    "EntailmentReportMetrics",
    "main",
    "scan_entailment_corpus",
    "wilson_95_ci",
    "write_entailment_report",
]
