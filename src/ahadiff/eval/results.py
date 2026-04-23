from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.contracts import ResultEvent
from ahadiff.core.errors import InputError
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
    chunks: list[bytes] = []
    for path in sorted(item for item in run_path.rglob("*") if item.is_file() or item.is_symlink()):
        relative_path = path.relative_to(run_path).as_posix()
        if relative_path == "finalized.json" or path.name.startswith("."):
            continue
        if path.is_symlink():
            raise InputError(f"refusing symlink artifact in finalized run: {relative_path}")
        chunks.append(
            relative_path.encode("utf-8")
            + b"\n"
            + hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii")
        )
    return len(chunks), hashlib.sha256(b"\n---\n".join(chunks)).hexdigest()


def run_state_dir_for_run(run_path: Path) -> Path:
    return run_path.parent.parent


def make_result_event_id() -> str:
    return make_uuid7()


def _insert_result_event(db_path: Path, event: ResultEvent) -> bool:
    return sync_result_event(db_path, event)


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
        score_temp.replace(score_path)
        finalized_temp.write_text(
            _render_finalized_payload(run_path, event, score_path=score_path),
            encoding="utf-8",
        )
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
