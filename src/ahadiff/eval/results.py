from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.contracts import ResultEvent
from ahadiff.core.errors import InputError, StorageError

if TYPE_CHECKING:
    from .evaluator import ScoreReport

_SQLITE_MIN_VERSION = (3, 51, 3)
_SQLITE_ALLOWED_BACKPORTS = {(3, 50, 7), (3, 44, 6)}

RESULTS_TSV_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "run_id",
    "source_ref",
    "base_ref",
    "prompt_version",
    "rubric_version",
    "overall",
    "verdict",
    "status",
    "weakest_dim",
    "note_json",
)


@dataclass(frozen=True)
class ResultWriteOutcome:
    event: ResultEvent
    sqlite_inserted: bool
    tsv_appended: bool
    finalized_written: bool
    warnings: tuple[str, ...]


def append_result(
    *,
    run_path: Path,
    report: ScoreReport,
    status: str,
    base_ref: str | None,
    event_type: str,
    note_payload: dict[str, object] | None = None,
    event_id: str | None = None,
    score_path: Path | None = None,
    write_finalized: bool = True,
) -> ResultWriteOutcome:
    prompt_version = compute_prompt_version(_workspace_root_for_run(run_path))
    rendered_note_payload = dict(note_payload or {})
    if report.degraded_flags:
        rendered_note_payload["degraded_flags"] = dict(report.degraded_flags)
    rendered_note = (
        None if not rendered_note_payload else json.dumps(rendered_note_payload, sort_keys=True)
    )
    event = ResultEvent(
        event_id=event_id or make_result_event_id(),
        run_id=report.run_id,
        event_type=event_type,
        timestamp=_utc_now(),
        source_ref=report.source_ref,
        base_ref=base_ref,
        prompt_version=prompt_version,
        eval_bundle_version=report.eval_bundle_version,
        rubric_version=report.rubric_version,
        overall=report.overall,
        verdict=cast("Any", report.verdict),
        status=cast("Any", status),
        weakest_dim=report.weakest_dim,
        note_json=rendered_note,
    )

    db_path = review_db_path_for_run(run_path)
    sqlite_inserted = _insert_result_event(db_path, event)

    warnings: list[str] = []
    tsv_appended = False
    finalized_written = False
    if sqlite_inserted:
        try:
            _append_results_tsv(results_tsv_path_for_run(run_path), event)
            tsv_appended = True
        except OSError as exc:
            warnings.append(f"results.tsv append failed: {exc}")

        if write_finalized:
            try:
                _write_finalized_marker(
                    run_path,
                    event,
                    score_path=score_path or (run_path / "score.json"),
                )
                finalized_written = True
            except OSError as exc:
                warnings.append(f"finalized.json write failed: {exc}")

    return ResultWriteOutcome(
        event=event,
        sqlite_inserted=sqlite_inserted,
        tsv_appended=tsv_appended,
        finalized_written=finalized_written,
        warnings=tuple(warnings),
    )


def export_results(*, db_path: Path, output_path: Path) -> Path:
    rows = _select_result_rows(db_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling_path(output_path, suffix=".export.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(RESULTS_TSV_COLUMNS),
                delimiter="\t",
                extrasaction="ignore",
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        temp_path.replace(output_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return output_path


def load_result_events(db_path: Path) -> tuple[ResultEvent, ...]:
    if not db_path.exists():
        return ()
    try:
        with _connect_result_db(db_path) as connection:
            if not _result_events_table_exists(connection):
                return ()
            rows = connection.execute(
                """
                SELECT
                    event_id,
                    run_id,
                    event_type,
                    timestamp,
                    source_ref,
                    base_ref,
                    prompt_version,
                    eval_bundle_version,
                    rubric_version,
                    overall,
                    verdict,
                    status,
                    weakest_dim,
                    note_json
                FROM result_events
                ORDER BY timestamp DESC, event_id DESC
                """
            ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"failed to read result_events from {db_path}: {exc}") from exc
    return tuple(ResultEvent.model_validate(dict(row)) for row in rows)


def compute_prompt_version(repo_root: Path) -> str:
    prompt_chunks = _prompt_hash_chunks(repo_root)
    if not prompt_chunks:
        return "no-prompts"
    return hashlib.sha256(b"\n---\n".join(prompt_chunks)).hexdigest()[:7]


def review_db_path_for_run(run_path: Path) -> Path:
    return run_state_dir_for_run(run_path) / "review.sqlite"


def results_tsv_path_for_run(run_path: Path) -> Path:
    return run_state_dir_for_run(run_path) / "results.tsv"


def finalized_marker_path(run_path: Path) -> Path:
    return run_path / "finalized.json"


def run_state_dir_for_run(run_path: Path) -> Path:
    return run_path.parent.parent


def make_result_event_id() -> str:
    timestamp_ms = int(datetime.now(UTC).timestamp() * 1000)
    unix_ms = timestamp_ms & ((1 << 48) - 1)
    random_low = uuid.uuid4().int & ((1 << 74) - 1)
    versioned = (unix_ms << 80) | (0x7 << 76) | random_low
    return str(uuid.UUID(int=versioned))


def _insert_result_event(db_path: Path, event: ResultEvent) -> bool:
    try:
        with _connect_result_db(db_path) as connection:
            _ensure_result_events_schema(connection)
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO result_events (
                    event_id,
                    run_id,
                    event_type,
                    timestamp,
                    source_ref,
                    base_ref,
                    prompt_version,
                    eval_bundle_version,
                    rubric_version,
                    overall,
                    verdict,
                    status,
                    weakest_dim,
                    note_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.event_type,
                    event.timestamp,
                    event.source_ref,
                    event.base_ref,
                    event.prompt_version,
                    event.eval_bundle_version,
                    event.rubric_version,
                    event.overall,
                    event.verdict,
                    event.status,
                    event.weakest_dim,
                    event.note_json,
                ),
            )
        return cursor.rowcount > 0
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"failed to append result event to {db_path}: {exc}") from exc


def _append_results_tsv(path: Path, event: ResultEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(RESULTS_TSV_COLUMNS),
            delimiter="\t",
            extrasaction="ignore",
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(_results_tsv_row(event))


def _write_finalized_marker(run_path: Path, event: ResultEvent, *, score_path: Path) -> None:
    target = finalized_marker_path(run_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling_path(target, suffix=".finalized.tmp")
    try:
        temp_path.write_text(
            _render_finalized_payload(run_path, event, score_path=score_path),
            encoding="utf-8",
        )
        temp_path.replace(target)
    finally:
        temp_path.unlink(missing_ok=True)


def _connect_result_db(db_path: Path) -> sqlite3.Connection:
    _assert_sqlite_runtime_supported()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA foreign_keys=ON")
    defensive_flag = getattr(sqlite3, "SQLITE_DBCONFIG_DEFENSIVE", None)
    setconfig = getattr(connection, "setconfig", None)
    if defensive_flag is not None and callable(setconfig):
        cast("Any", setconfig)(defensive_flag, True)
    return connection


def _ensure_result_events_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS result_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            base_ref TEXT,
            prompt_version TEXT NOT NULL,
            eval_bundle_version TEXT NOT NULL,
            rubric_version TEXT,
            overall REAL NOT NULL,
            verdict TEXT NOT NULL,
            status TEXT NOT NULL,
            weakest_dim TEXT NOT NULL,
            note_json TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_result_events_run_type_ts
            ON result_events (run_id, event_type, timestamp)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_result_events_source_ts
            ON result_events (source_ref, timestamp DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_result_events_prompt_eval
            ON result_events (prompt_version, eval_bundle_version)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_result_events_verdict_status
            ON result_events (verdict, status)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_result_events_weakest_dim_ts
            ON result_events (weakest_dim, timestamp DESC)
        """
    )


def _result_events_table_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'result_events'"
    ).fetchone()
    return row is not None


def _select_result_rows(db_path: Path) -> tuple[dict[str, object], ...]:
    if not db_path.exists():
        raise InputError(f"review.sqlite does not exist: {db_path}")
    with _connect_result_db(db_path) as connection:
        if not _result_events_table_exists(connection):
            raise InputError("result_events table does not exist yet")
        rows = connection.execute(
            """
            SELECT
                timestamp,
                run_id,
                source_ref,
                base_ref,
                prompt_version,
                rubric_version,
                overall,
                verdict,
                status,
                weakest_dim,
                note_json
            FROM result_events
            ORDER BY timestamp ASC, event_id ASC
            """
        ).fetchall()
    return tuple(dict(row) for row in rows)


def _results_tsv_row(event: ResultEvent) -> dict[str, object]:
    return {
        "timestamp": event.timestamp,
        "run_id": event.run_id,
        "source_ref": event.source_ref,
        "base_ref": event.base_ref or "",
        "prompt_version": event.prompt_version,
        "rubric_version": event.rubric_version or "",
        "overall": f"{event.overall:.2f}",
        "verdict": event.verdict,
        "status": event.status,
        "weakest_dim": event.weakest_dim,
        "note_json": event.note_json or "",
    }


def _workspace_root_for_run(run_path: Path) -> Path:
    return run_state_dir_for_run(run_path).parent


def write_finalized_result(*, run_path: Path, event: ResultEvent, score_path: Path) -> None:
    _write_finalized_marker(run_path, event, score_path=score_path)


def publish_result_artifacts(
    *,
    run_path: Path,
    report: ScoreReport,
    event: ResultEvent,
    score_path: Path,
    overwrite: bool,
) -> None:
    finalized_path = finalized_marker_path(run_path)
    score_path.parent.mkdir(parents=True, exist_ok=True)
    finalized_path.parent.mkdir(parents=True, exist_ok=True)

    score_backup: Path | None = None
    finalized_backup: Path | None = None
    score_temp = _temporary_sibling_path(score_path, suffix=".score.tmp")
    finalized_temp = _temporary_sibling_path(finalized_path, suffix=".finalized.tmp")

    try:
        if score_path.exists():
            if not overwrite:
                raise InputError(f"refusing to overwrite existing file: {score_path}")
            score_backup = _temporary_sibling_path(score_path, suffix=".score.bak")
            score_path.replace(score_backup)
        if finalized_path.exists():
            finalized_backup = _temporary_sibling_path(finalized_path, suffix=".finalized.bak")
            finalized_path.replace(finalized_backup)

        score_temp.write_text(
            json.dumps(report.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        finalized_temp.write_text(
            _render_finalized_payload(run_path, event, score_path=score_path),
            encoding="utf-8",
        )

        score_temp.replace(score_path)
        finalized_temp.replace(finalized_path)
    except OSError:
        _restore_file_from_backup(target=score_path, backup_path=score_backup)
        _restore_file_from_backup(target=finalized_path, backup_path=finalized_backup)
        raise
    finally:
        score_temp.unlink(missing_ok=True)
        finalized_temp.unlink(missing_ok=True)
        if score_backup is not None:
            score_backup.unlink(missing_ok=True)
        if finalized_backup is not None:
            finalized_backup.unlink(missing_ok=True)


def rollback_result_event(*, run_path: Path, event_id: str) -> None:
    db_path = review_db_path_for_run(run_path)
    try:
        with _connect_result_db(db_path) as connection:
            if not _result_events_table_exists(connection):
                return
            connection.execute("DELETE FROM result_events WHERE event_id = ?", (event_id,))
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"failed to roll back result event in {db_path}: {exc}") from exc
    export_results(db_path=db_path, output_path=results_tsv_path_for_run(run_path))


def _prompt_hash_chunks(repo_root: Path) -> tuple[bytes, ...]:
    del repo_root
    prompts_dir = Path(__file__).resolve().parents[1] / "prompts"
    if prompts_dir.is_dir():
        prompt_files = sorted(path for path in prompts_dir.rglob("*") if path.is_file())
        return tuple(
            path.relative_to(prompts_dir.parent).as_posix().encode("utf-8")
            + b"\n"
            + path.read_bytes()
            for path in prompt_files
        )

    try:
        package_prompts = files("ahadiff").joinpath("prompts")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return ()
    if not package_prompts.is_dir():
        return ()

    chunks: list[bytes] = []
    for resource_path, resource in sorted(
        _iter_prompt_resources(package_prompts),
        key=lambda item: item[0],
    ):
        chunks.append(resource_path.encode("utf-8") + b"\n" + resource.read_bytes())
    return tuple(chunks)


def _iter_prompt_resources(root: Any, *, prefix: str = "prompts") -> list[tuple[str, Any]]:
    resources: list[tuple[str, Any]] = []
    for child in root.iterdir():
        child_path = f"{prefix}/{child.name}"
        if child.is_dir():
            resources.extend(_iter_prompt_resources(child, prefix=child_path))
            continue
        if child.is_file():
            resources.append((child_path, child))
    return resources


def _score_path_reference(run_path: Path, score_path: Path) -> str:
    run_root = run_path.resolve()
    resolved_score_path = score_path.resolve()
    try:
        return resolved_score_path.relative_to(run_root).as_posix()
    except ValueError:
        return str(resolved_score_path)


def _render_finalized_payload(run_path: Path, event: ResultEvent, *, score_path: Path) -> str:
    payload = {
        "run_id": event.run_id,
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "status": event.status,
        "verdict": event.verdict,
        "overall": round(event.overall, 2),
        "weakest_dim": event.weakest_dim,
        "score_path": _score_path_reference(run_path, score_path),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _restore_file_from_backup(*, target: Path, backup_path: Path | None) -> None:
    if backup_path is None:
        target.unlink(missing_ok=True)
        return
    target.unlink(missing_ok=True)
    backup_path.replace(target)


def _temporary_sibling_path(path: Path, *, suffix: str) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=suffix,
        dir=path.parent,
    )
    os.close(fd)
    temp_path = Path(raw_path)
    temp_path.unlink()
    return temp_path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _assert_sqlite_runtime_supported() -> None:
    version = _sqlite_version_tuple()
    if _sqlite_gate_ok(version):
        return
    minimum = ".".join(str(part) for part in _SQLITE_MIN_VERSION)
    backports = ", ".join(
        ".".join(str(part) for part in item) for item in sorted(_SQLITE_ALLOWED_BACKPORTS)
    )
    raise StorageError(
        f"SQLite runtime {sqlite3.sqlite_version} is below {minimum}; "
        f"allowed backports are {backports}"
    )


def _sqlite_version_tuple() -> tuple[int, int, int]:
    parts = sqlite3.sqlite_version.split(".")
    major, minor, patch = (int(part) for part in parts[:3])
    return major, minor, patch


def _sqlite_gate_ok(version: tuple[int, int, int]) -> bool:
    return version >= _SQLITE_MIN_VERSION or version in _SQLITE_ALLOWED_BACKPORTS


__all__ = [
    "append_result",
    "compute_prompt_version",
    "export_results",
    "finalized_marker_path",
    "load_result_events",
    "make_result_event_id",
    "publish_result_artifacts",
    "RESULTS_TSV_COLUMNS",
    "ResultWriteOutcome",
    "rollback_result_event",
    "results_tsv_path_for_run",
    "review_db_path_for_run",
    "write_finalized_result",
]
