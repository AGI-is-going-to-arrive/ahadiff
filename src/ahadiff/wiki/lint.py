"""Deterministic concept lint engine for staleness, orphan, and contradiction detection.

This module implements the deterministic half of the RFC 2.1 Maintenance Loop.
It only inspects local state (concepts, claims, git ls-files) and never issues
network calls or LLM requests. The LLM-assisted (Option B) path lives elsewhere.
"""

from __future__ import annotations

import sqlite3
import stat
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.git.repo import run_git

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from ahadiff.contracts.claim_status import StaleReason

HealthStatus = Literal["healthy", "stale", "contradicted", "orphan", "dismissed"]
LintMode = Literal["deterministic", "llm_assisted"]

_DEFAULT_ORPHAN_RUN_WINDOW = 5
_DEFAULT_LINE_DRIFT_THRESHOLD = 50
_MAX_LS_FILES_BYTES = 64 * 1024 * 1024
_MAX_CLAIMS_JSONL_BYTES = 5 * 1024 * 1024
_MAX_CLAIM_FILES = 500


@dataclass(frozen=True)
class LintFinding:
    """Single deterministic lint finding for a concept."""

    term_key: str
    current_status: HealthStatus
    new_status: HealthStatus
    reason: str
    stale_reason: StaleReason | None = None
    contradicted_by_run: str | None = None


@dataclass(frozen=True)
class LintRunSummary:
    """Aggregate result of a deterministic lint run."""

    lint_id: str
    mode: LintMode
    started_at_utc: str
    finished_at_utc: str
    findings: tuple[LintFinding, ...] = field(default_factory=tuple)


def canonical_term_key(value: str) -> str:
    """Canonicalize a term_key for cross-platform collision-free comparison.

    NFC + casefold matches AhaDiff's compute_term_key contract on the read side.
    """

    normalized = unicodedata.normalize("NFC", value).strip().casefold()
    if not normalized:
        raise InputError("term_key would be empty after normalization")
    return normalized


def _normalize_repo_path(value: str) -> str:
    """Normalize a repo-relative path for Windows-friendly comparison."""

    return value.replace("\\", "/").lstrip("./").strip()


def _coerce_status(value: object) -> HealthStatus:
    if isinstance(value, str) and value in {
        "healthy",
        "stale",
        "contradicted",
        "orphan",
        "dismissed",
    }:
        return cast("HealthStatus", value)
    return "healthy"


def _git_tracked_files(repo_root: Path) -> frozenset[str]:
    """Return a set of repo-relative POSIX paths currently tracked by git.

    Uses ``git ls-files -z`` with ``--end-of-options`` and the project's
    git_clean_env wrapper. Returns an empty set when git is unavailable
    or the repo cannot be inspected (callers treat that as "skip stale
    detection" rather than raising).
    """

    try:
        result = run_git(
            repo_root,
            "ls-files",
            "-z",
            "--end-of-options",
            timeout=30,
            check=False,
        )
    except Exception:
        return frozenset()
    if result.returncode != 0:
        return frozenset()
    payload = result.stdout or ""
    if len(payload.encode("utf-8", errors="ignore")) > _MAX_LS_FILES_BYTES:
        return frozenset()
    entries = (entry for entry in payload.split("\x00") if entry)
    return frozenset(_normalize_repo_path(entry) for entry in entries)


def _extract_file_paths(entry: dict[str, Any]) -> tuple[str, ...]:
    paths: list[str] = []
    raw_files = entry.get("file_refs", [])
    if isinstance(raw_files, list):
        for item in cast("list[object]", raw_files):
            if isinstance(item, str):
                normalized = _normalize_repo_path(item)
                if normalized:
                    paths.append(normalized)
    return tuple(dict.fromkeys(paths))


def detect_orphans(
    concepts: Sequence[dict[str, Any]],
    recent_runs: Sequence[str],
    *,
    threshold: int = _DEFAULT_ORPHAN_RUN_WINDOW,
    current_status_map: dict[str, HealthStatus] | None = None,
) -> list[LintFinding]:
    """Detect concepts that are not referenced by any of the last ``threshold`` runs.

    A concept is orphaned when its ``updated_by_runs`` does not intersect
    the most recent ``threshold`` run ids in ``recent_runs`` (oldest first
    or newest first — the set membership check is order-independent).
    """

    if threshold < 0:
        raise InputError("orphan detection threshold must be >= 0")
    if threshold == 0:
        recent_set: frozenset[str] = frozenset()
    else:
        run_ids = [run_id for run_id in recent_runs if run_id]
        recent_set = frozenset(run_ids[-threshold:])
    status_map = current_status_map or {}
    findings: list[LintFinding] = []
    for entry in concepts:
        term_key_raw = entry.get("term_key")
        if not isinstance(term_key_raw, str) or not term_key_raw:
            continue
        try:
            term_key = canonical_term_key(term_key_raw)
        except InputError:
            continue
        updated_by_raw = entry.get("updated_by_runs", [])
        references: set[str] = set()
        if isinstance(updated_by_raw, list):
            for item in cast("list[object]", updated_by_raw):
                if isinstance(item, str) and item:
                    references.add(item)
        if recent_set and references & recent_set:
            continue
        current_status = status_map.get(term_key, "healthy")
        if current_status == "dismissed":
            continue
        findings.append(
            LintFinding(
                term_key=term_key,
                current_status=current_status,
                new_status="orphan",
                reason=(f"no references within last {threshold} runs (refcount={len(references)})"),
            )
        )
    return findings


def detect_stale_by_file_deletion(
    concepts: Sequence[dict[str, Any]],
    repo_root: Path,
    *,
    tracked_files: frozenset[str] | None = None,
    current_status_map: dict[str, HealthStatus] | None = None,
) -> list[LintFinding]:
    """Flag concepts whose ``file_refs`` no longer exist in ``git ls-files``."""

    if tracked_files is not None:
        tracked = tracked_files
    else:
        tracked = _git_tracked_files(repo_root)
        if not tracked:
            return []
    status_map = current_status_map or {}
    findings: list[LintFinding] = []
    for entry in concepts:
        term_key_raw = entry.get("term_key")
        if not isinstance(term_key_raw, str) or not term_key_raw:
            continue
        try:
            term_key = canonical_term_key(term_key_raw)
        except InputError:
            continue
        files = _extract_file_paths(entry)
        if not files:
            continue
        missing = [path for path in files if path not in tracked]
        if not missing or len(missing) < len(files):
            continue
        current_status = status_map.get(term_key, "healthy")
        if current_status == "dismissed":
            continue
        findings.append(
            LintFinding(
                term_key=term_key,
                current_status=current_status,
                new_status="stale",
                reason=f"all file_refs deleted: {sorted(missing)[:5]}",
                stale_reason="file_deleted",
            )
        )
    return findings


def detect_stale_by_line_drift(
    concepts: Sequence[dict[str, Any]],
    repo_root: Path,
    *,
    drift_threshold: int = _DEFAULT_LINE_DRIFT_THRESHOLD,
    file_line_counts: dict[str, int] | None = None,
    current_status_map: dict[str, HealthStatus] | None = None,
) -> list[LintFinding]:
    """Flag concepts whose recorded line numbers drift beyond ``drift_threshold``.

    Currently inspects optional ``source_refs`` entries shaped as
    ``"path/to/file.py:123"``. Files without recorded line metadata are
    skipped (no false positives). ``file_line_counts`` may be supplied to
    avoid reading from disk during tests.
    """

    if drift_threshold < 0:
        raise InputError("line drift threshold must be >= 0")
    status_map = current_status_map or {}
    cache: dict[str, int] = dict(file_line_counts or {})
    findings: list[LintFinding] = []
    for entry in concepts:
        term_key_raw = entry.get("term_key")
        if not isinstance(term_key_raw, str) or not term_key_raw:
            continue
        try:
            term_key = canonical_term_key(term_key_raw)
        except InputError:
            continue
        source_refs = entry.get("source_refs", [])
        if not isinstance(source_refs, list):
            continue
        drifted: list[str] = []
        for raw in cast("list[object]", source_refs):
            if not isinstance(raw, str) or ":" not in raw:
                continue
            path_part, _, line_part = raw.rpartition(":")
            try:
                expected_line = int(line_part)
            except ValueError:
                continue
            normalized_path = _normalize_repo_path(path_part)
            if not normalized_path:
                continue
            actual_lines = _file_line_count(repo_root, normalized_path, cache)
            if actual_lines is None:
                continue
            if abs(actual_lines - expected_line) > drift_threshold:
                drifted.append(f"{normalized_path}:{expected_line} (file has {actual_lines})")
        if not drifted:
            continue
        current_status = status_map.get(term_key, "healthy")
        if current_status == "dismissed":
            continue
        findings.append(
            LintFinding(
                term_key=term_key,
                current_status=current_status,
                new_status="stale",
                reason=(f"line drift > {drift_threshold} on {len(drifted)} ref(s): {drifted[:3]}"),
                stale_reason="line_drifted",
            )
        )
    return findings


def detect_contradictions(
    concepts: Sequence[dict[str, Any]],
    claims: Sequence[dict[str, Any]],
    *,
    current_status_map: dict[str, HealthStatus] | None = None,
) -> list[LintFinding]:
    """Flag concepts linked to contradicted local claim records."""

    status_map = current_status_map or {}
    contradicted_claims: dict[str, str | None] = {}
    for claim in claims:
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id:
            continue
        if claim.get("status") != "contradicted":
            continue
        run_id = claim.get("run_id")
        contradicted_claims[claim_id] = run_id if isinstance(run_id, str) and run_id else None
    if not contradicted_claims:
        return []

    findings: list[LintFinding] = []
    for entry in concepts:
        term_key_raw = entry.get("term_key")
        if not isinstance(term_key_raw, str) or not term_key_raw:
            continue
        try:
            term_key = canonical_term_key(term_key_raw)
        except InputError:
            continue
        current_status = status_map.get(term_key, "healthy")
        if current_status == "dismissed":
            continue
        related_raw = entry.get("related_claims", [])
        if not isinstance(related_raw, list):
            continue
        related_claims = [
            item for item in cast("list[object]", related_raw) if isinstance(item, str)
        ]
        matched = sorted(claim_id for claim_id in related_claims if claim_id in contradicted_claims)
        if not matched:
            continue
        first_claim = matched[0]
        findings.append(
            LintFinding(
                term_key=term_key,
                current_status=current_status,
                new_status="contradicted",
                reason=f"linked contradicted claim(s): {matched[:5]}",
                contradicted_by_run=contradicted_claims[first_claim],
            )
        )
    return findings


def _file_line_count(repo_root: Path, rel_path: str, cache: dict[str, int]) -> int | None:
    cached = cache.get(rel_path)
    if cached is not None:
        return cached
    candidate = (repo_root / rel_path).resolve()
    try:
        repo_resolved = repo_root.resolve()
    except OSError:
        return None
    try:
        candidate.relative_to(repo_resolved)
    except ValueError:
        return None
    if not candidate.is_file() or candidate.is_symlink():
        return None
    try:
        with candidate.open("rb") as handle:
            line_count = sum(1 for _ in handle)
    except OSError:
        return None
    cache[rel_path] = line_count
    return line_count


def run_deterministic_lint(
    concepts: Sequence[dict[str, Any]],
    recent_runs: Sequence[str],
    repo_root: Path,
    *,
    db_path: Path | None = None,
    dry_run: bool = False,
    orphan_threshold: int = _DEFAULT_ORPHAN_RUN_WINDOW,
    line_drift_threshold: int = _DEFAULT_LINE_DRIFT_THRESHOLD,
    tracked_files: frozenset[str] | None = None,
    file_line_counts: dict[str, int] | None = None,
    claims: Sequence[dict[str, Any]] | None = None,
) -> LintRunSummary:
    """Run all deterministic checks and (optionally) persist results.

    When ``dry_run`` is True the function returns a summary but skips any
    SQLite writes. ``db_path`` is required when ``dry_run`` is False.
    """

    if not dry_run and db_path is None:
        raise InputError("db_path is required when dry_run=False")

    status_map: dict[str, HealthStatus] = {}
    if db_path is not None and db_path.exists():
        status_map = _load_status_map(db_path)
    claim_records = list(claims) if claims is not None else []
    if claims is None and db_path is not None:
        claim_records = _load_claims_from_state_dir(db_path.parent)

    findings = _collect_findings(
        concepts=concepts,
        claims=claim_records,
        recent_runs=recent_runs,
        repo_root=repo_root,
        status_map=status_map,
        orphan_threshold=orphan_threshold,
        line_drift_threshold=line_drift_threshold,
        tracked_files=tracked_files,
        file_line_counts=file_line_counts,
    )

    lint_id = uuid.uuid4().hex
    started_at = _utc_now_iso()
    finished_at = _utc_now_iso()

    if not dry_run and db_path is not None:
        _persist_lint_results(
            db_path=db_path,
            lint_id=lint_id,
            mode="deterministic",
            started_at=started_at,
            finished_at=finished_at,
            findings=findings,
        )

    return LintRunSummary(
        lint_id=lint_id,
        mode="deterministic",
        started_at_utc=started_at,
        finished_at_utc=finished_at,
        findings=tuple(findings),
    )


def _collect_findings(
    *,
    concepts: Sequence[dict[str, Any]],
    claims: Sequence[dict[str, Any]],
    recent_runs: Sequence[str],
    repo_root: Path,
    status_map: dict[str, HealthStatus],
    orphan_threshold: int,
    line_drift_threshold: int,
    tracked_files: frozenset[str] | None,
    file_line_counts: dict[str, int] | None,
) -> list[LintFinding]:
    contradiction_findings = detect_contradictions(
        concepts,
        claims,
        current_status_map=status_map,
    )
    orphan_findings = detect_orphans(
        concepts,
        recent_runs,
        threshold=orphan_threshold,
        current_status_map=status_map,
    )
    deletion_findings = detect_stale_by_file_deletion(
        concepts,
        repo_root,
        tracked_files=tracked_files,
        current_status_map=status_map,
    )
    drift_findings = detect_stale_by_line_drift(
        concepts,
        repo_root,
        drift_threshold=line_drift_threshold,
        file_line_counts=file_line_counts,
        current_status_map=status_map,
    )
    merged: dict[str, LintFinding] = {}
    for finding in (
        *contradiction_findings,
        *deletion_findings,
        *drift_findings,
        *orphan_findings,
    ):
        merged.setdefault(finding.term_key, finding)
    return sorted(
        merged.values(),
        key=lambda item: (item.new_status, item.term_key),
    )


def _load_status_map(db_path: Path) -> dict[str, HealthStatus]:
    from ahadiff.review.database import connect_review_db

    status_map: dict[str, HealthStatus] = {}
    try:
        with connect_review_db(db_path) as connection:
            rows = connection.execute(
                "SELECT term_key, health_status FROM concept_status"
            ).fetchall()
    except sqlite3.DatabaseError:
        return status_map
    except Exception:
        return status_map
    for row in rows:
        row_keys = set(row.keys())
        term_key_raw = row["term_key"] if "term_key" in row_keys else None
        status_raw = row["health_status"] if "health_status" in row_keys else None
        if isinstance(term_key_raw, str) and term_key_raw:
            status_map[term_key_raw] = _coerce_status(status_raw)
    return status_map


def _load_claims_from_state_dir(state_dir: Path) -> list[dict[str, Any]]:
    runs_dir = state_dir / "runs"
    if not runs_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    scanned = 0
    try:
        claim_paths = sorted(runs_dir.glob("*/claims.jsonl"))
    except OSError:
        return []
    for claims_path in claim_paths:
        if scanned >= _MAX_CLAIM_FILES:
            break
        scanned += 1
        try:
            leaf_stat = claims_path.lstat()
        except OSError:
            continue
        if (
            stat.S_ISLNK(leaf_stat.st_mode)
            or not stat.S_ISREG(leaf_stat.st_mode)
            or bool(getattr(leaf_stat, "st_file_attributes", 0) & 0x400)
            or leaf_stat.st_size > _MAX_CLAIMS_JSONL_BYTES
        ):
            continue
        try:
            lines = claims_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        run_id = claims_path.parent.name
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = safe_json_loads(stripped)
            except ValueError:
                continue
            if not isinstance(parsed, dict):
                continue
            record = cast("dict[str, Any]", parsed)
            record.setdefault("run_id", run_id)
            records.append(record)
    return records


def _persist_lint_results(
    *,
    db_path: Path,
    lint_id: str,
    mode: LintMode,
    started_at: str,
    finished_at: str,
    findings: Iterable[LintFinding],
) -> None:
    from ahadiff.review.database import connect_review_db

    findings_list = list(findings)
    with connect_review_db(db_path, create_parent=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                INSERT INTO concept_lint_runs (
                    lint_id, started_at_utc, finished_at_utc,
                    mode, findings_count, run_summary_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    lint_id,
                    started_at,
                    finished_at,
                    mode,
                    len(findings_list),
                    None,
                ),
            )
            for finding in findings_list:
                stale_since = finished_at if finding.stale_reason is not None else None
                connection.execute(
                    """
                    INSERT INTO concept_status (
                        term_key, health_status, stale_since, contradicted_by_run,
                        refcount, dismissed_reason, dismissed_at_utc, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(term_key) DO UPDATE SET
                        health_status = excluded.health_status,
                        stale_since = COALESCE(
                            excluded.stale_since, concept_status.stale_since
                        ),
                        contradicted_by_run = COALESCE(
                            excluded.contradicted_by_run,
                            concept_status.contradicted_by_run
                        ),
                        updated_at_utc = excluded.updated_at_utc
                    """,
                    (
                        finding.term_key,
                        finding.new_status,
                        stale_since,
                        finding.contradicted_by_run,
                        0,
                        None,
                        None,
                        finished_at,
                    ),
                )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "HealthStatus",
    "LintFinding",
    "LintMode",
    "LintRunSummary",
    "canonical_term_key",
    "detect_contradictions",
    "detect_orphans",
    "detect_stale_by_file_deletion",
    "detect_stale_by_line_drift",
    "run_deterministic_lint",
]
