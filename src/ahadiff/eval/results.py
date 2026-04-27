from __future__ import annotations

import csv
import errno
import hashlib
import json
import os
import stat
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.contracts import ResultEvent
from ahadiff.core.errors import InputError, StorageError
from ahadiff.review.database import (
    delete_result_event_and_select_tsv_rows,
    load_result_events_from_db,
    make_uuid7,
    select_result_tsv_rows,
    sync_result_event,
)

if TYPE_CHECKING:
    from .evaluator import ScoreReport

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
_RESULT_EVENT_INSERT_ATTEMPTS = 6
_RESULT_EVENT_INSERT_RETRY_SECONDS = 0.05
_MAX_FINALIZED_ARTIFACT_COUNT = 500
_MAX_FINALIZED_ARTIFACT_DIRS = 500
_MAX_FINALIZED_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_FINALIZED_ARTIFACTS_TOTAL_BYTES = 50 * 1024 * 1024


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
    prompt_version_override: str | None = None,
) -> ResultWriteOutcome:
    prompt_version = prompt_version_override or compute_prompt_version(
        _workspace_root_for_run(run_path)
    )
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
        except Exception as exc:
            warnings.append(f"results.tsv append failed: {exc}")

        if write_finalized:
            try:
                _write_finalized_marker(
                    run_path,
                    event,
                    score_path=score_path or (run_path / "score.json"),
                )
                finalized_written = True
            except Exception as exc:
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
    return _write_result_rows(output_path=output_path, rows=rows)


def _write_result_rows(
    *,
    output_path: Path,
    rows: tuple[dict[str, object], ...],
) -> Path:
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
    return load_result_events_from_db(db_path)


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


def finalized_artifact_digest(run_path: Path) -> tuple[int, str]:
    artifact_paths: list[tuple[str, Path, os.stat_result]] = []
    total_bytes = 0
    dirs_seen = 0
    stack = [run_path]
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
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise InputError("finalized run artifact is unreadable") from exc
            if stat.S_ISDIR(entry_stat.st_mode):
                stack.append(path)
                continue
            if not (stat.S_ISREG(entry_stat.st_mode) or stat.S_ISLNK(entry_stat.st_mode)):
                continue

            relative_path = path.relative_to(run_path).as_posix()
            if relative_path == "finalized.json" or path.name.startswith("."):
                continue
            if stat.S_ISLNK(entry_stat.st_mode):
                raise InputError(f"refusing symlink artifact in finalized run: {relative_path}")
            if len(artifact_paths) >= _MAX_FINALIZED_ARTIFACT_COUNT:
                raise InputError("finalized run has too many artifacts")
            artifact_size = entry_stat.st_size
            if artifact_size > _MAX_FINALIZED_ARTIFACT_BYTES:
                raise InputError(f"finalized run artifact exceeds size limit: {relative_path}")
            total_bytes += artifact_size
            if total_bytes > _MAX_FINALIZED_ARTIFACTS_TOTAL_BYTES:
                raise InputError("finalized run artifacts exceed total size limit")
            artifact_paths.append((relative_path, path, entry_stat))

    chunks: list[bytes] = []
    for relative_path, path, entry_stat in sorted(artifact_paths):
        chunks.append(
            relative_path.encode("utf-8")
            + b"\n"
            + _hash_finalized_artifact_file(path, relative_path, entry_stat).encode("ascii")
        )
    return len(chunks), hashlib.sha256(b"\n---\n".join(chunks)).hexdigest()


def _hash_finalized_artifact_file(
    path: Path,
    relative_path: str,
    expected_stat: os.stat_result,
) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(
                f"refusing symlink artifact in finalized run: {relative_path}"
            ) from exc
        raise InputError(f"finalized run artifact is unreadable: {relative_path}") from exc
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise InputError(f"finalized run artifact must be a regular file: {relative_path}")
        if (file_stat.st_dev, file_stat.st_ino) != (expected_stat.st_dev, expected_stat.st_ino):
            raise InputError(f"finalized run artifact changed during validation: {relative_path}")
        if file_stat.st_size > _MAX_FINALIZED_ARTIFACT_BYTES:
            raise InputError(f"finalized run artifact exceeds size limit: {relative_path}")

        digest = hashlib.sha256()
        total_read = 0
        while True:
            chunk = os.read(fd, 65_536)
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > _MAX_FINALIZED_ARTIFACT_BYTES:
                raise InputError(f"finalized run artifact exceeds size limit: {relative_path}")
            digest.update(chunk)
        return digest.hexdigest()
    except InputError:
        raise
    except OSError as exc:
        raise InputError(f"finalized run artifact is unreadable: {relative_path}") from exc
    finally:
        os.close(fd)


def run_state_dir_for_run(run_path: Path) -> Path:
    return run_path.parent.parent


def make_result_event_id() -> str:
    return make_uuid7()


def _insert_result_event(db_path: Path, event: ResultEvent) -> bool:
    if _RESULT_EVENT_INSERT_ATTEMPTS < 1:
        raise AssertionError("_RESULT_EVENT_INSERT_ATTEMPTS must be >= 1")
    for attempt in range(_RESULT_EVENT_INSERT_ATTEMPTS):
        try:
            return sync_result_event(db_path, event)
        except StorageError as exc:
            if "database is locked" not in str(exc) or attempt == _RESULT_EVENT_INSERT_ATTEMPTS - 1:
                raise
            time.sleep(_RESULT_EVENT_INSERT_RETRY_SECONDS * (attempt + 1))
    raise AssertionError("_insert_result_event retry loop exhausted unexpectedly")


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


def _select_result_rows(db_path: Path) -> tuple[dict[str, object], ...]:
    return select_result_tsv_rows(db_path)


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
    artifacts_mutated = False

    try:
        if score_path.exists():
            if not overwrite:
                raise InputError(f"refusing to overwrite existing file: {score_path}")
            score_backup = _temporary_sibling_path(score_path, suffix=".score.bak")
            score_path.replace(score_backup)
            artifacts_mutated = True
        if finalized_path.exists():
            finalized_backup = _temporary_sibling_path(finalized_path, suffix=".finalized.bak")
            finalized_path.replace(finalized_backup)
            artifacts_mutated = True

        score_temp.write_text(
            json.dumps(report.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        score_temp.replace(score_path)
        artifacts_mutated = True
        finalized_temp.write_text(
            _render_finalized_payload(run_path, event, score_path=score_path),
            encoding="utf-8",
        )
        finalized_temp.replace(finalized_path)
        artifacts_mutated = True
    except Exception:
        if artifacts_mutated:
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
    rows = delete_result_event_and_select_tsv_rows(db_path, event_id)
    _write_result_rows(output_path=results_tsv_path_for_run(run_path), rows=rows)


def _prompt_hash_chunks(repo_root: Path) -> tuple[bytes, ...]:
    prompts_dir = repo_root / "src" / "ahadiff" / "prompts"
    if not prompts_dir.is_dir():
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
    artifact_count, checksum = finalized_artifact_digest(run_path)
    payload = {
        "run_id": event.run_id,
        "event_id": event.event_id,
        "finalized_at": event.timestamp,
        "timestamp": event.timestamp,
        "status": event.status,
        "verdict": event.verdict,
        "overall": round(event.overall, 2),
        "weakest_dim": event.weakest_dim,
        "score_path": _score_path_reference(run_path, score_path),
        "artifact_count": artifact_count,
        "checksum": checksum,
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


__all__ = [
    "append_result",
    "compute_prompt_version",
    "export_results",
    "finalized_artifact_digest",
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
