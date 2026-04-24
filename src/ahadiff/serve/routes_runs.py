from __future__ import annotations

import json
from json import JSONDecodeError
from typing import TYPE_CHECKING, Any, cast

from starlette.responses import JSONResponse

from ahadiff.contracts import (
    RatchetHistoryEntry,
    RunArtifactEnvelope,
    RunDetail,
    RunSummary,
)
from ahadiff.contracts.event_log import RATCHET_COUNTED_STATUSES, ResultEvent
from ahadiff.core.errors import InputError
from ahadiff.core.paths import validate_run_id
from ahadiff.eval.results import finalized_artifact_digest
from ahadiff.review.database import load_result_event_by_run_and_id, load_result_events_from_db

from .auth import serve_state

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

_ARTIFACT_PATHS = {
    "claims": "claims.jsonl",
    "diff": "patch.diff",
    "quiz": "quiz/quiz.jsonl",
    "score": "score.json",
}
_LESSON_LEVELS = {"full", "hint", "compact"}
_ALLOWED_ARTIFACTS = frozenset(
    {
        "claims.jsonl",
        "patch.diff",
        "quiz/quiz.jsonl",
        "score.json",
        "lesson/lesson.full.md",
        "lesson/lesson.hint.md",
        "lesson/lesson.compact.md",
        "lesson/misconception.md",
        "lesson/not_proven.md",
    }
)


async def list_runs(request: Request) -> JSONResponse:
    state = serve_state(request)
    source_kind_filter = request.query_params.get("source_kind")
    summaries: list[dict[str, Any]] = []
    for event, metadata, _run_path in _iter_latest_finalized_run_events(
        state.runs_dir,
        state.review_db_path,
    ):
        if source_kind_filter and metadata.get("source_kind") != source_kind_filter:
            continue
        summary = _summary_from_event(event, metadata)
        if summary is not None:
            summaries.append(summary.model_dump(mode="json"))
    return JSONResponse({"runs": summaries})


async def get_run(request: Request) -> JSONResponse:
    state = serve_state(request)
    run_id = str(request.path_params["run_id"])
    run_path = _finalized_run_path(state.runs_dir, run_id)
    event = _event_for_finalized_run(state.review_db_path, run_path)
    metadata = _load_json_object(run_path / "metadata.json")
    summary = _summary_from_event(event, metadata)
    if summary is None:
        raise InputError(f"run metadata is invalid: {run_id}")
    detail = RunDetail(
        **summary.model_dump(mode="json"),
        base_ref=event.base_ref,
        prompt_version=event.prompt_version,
        eval_bundle_version=event.eval_bundle_version,
        note_json=event.note_json,
        artifacts=_artifact_names(run_path),
        graphify_mode=cast("Any", metadata.get("graphify_mode")),
        graphify_status=cast("str | None", metadata.get("graphify_status")),
    )
    return JSONResponse(detail.model_dump(mode="json"))


async def get_lesson(request: Request) -> JSONResponse:
    level = request.query_params.get("level", "full")
    if level not in _LESSON_LEVELS:
        raise InputError("lesson level must be one of: full, hint, compact")
    return _artifact_response(request, f"lesson/lesson.{level}.md", "lesson")


async def get_claims(request: Request) -> JSONResponse:
    return _artifact_response(request, _ARTIFACT_PATHS["claims"], "claims")


async def get_quiz(request: Request) -> JSONResponse:
    return _artifact_response(request, _ARTIFACT_PATHS["quiz"], "quiz")


async def get_diff(request: Request) -> JSONResponse:
    return _artifact_response(request, _ARTIFACT_PATHS["diff"], "diff")


async def get_concepts(request: Request) -> JSONResponse:
    state = serve_state(request)
    concepts_path = state.state_dir / "concepts.jsonl"
    content = (
        concepts_path.read_text(encoding="utf-8")
        if concepts_path.exists() and not concepts_path.is_symlink()
        else ""
    )
    return JSONResponse({"artifact_type": "concepts", "content": content})


async def get_ratchet_history(request: Request) -> JSONResponse:
    state = serve_state(request)
    finalized_event_ids = set(_finalized_event_ids(state.runs_dir).values())
    entries: list[dict[str, Any]] = []
    for event in reversed(load_result_events_from_db(state.review_db_path)):
        if (
            event.event_id not in finalized_event_ids
            or event.status not in RATCHET_COUNTED_STATUSES
        ):
            continue
        entries.append(
            RatchetHistoryEntry(
                run_id=event.run_id,
                source_ref=event.source_ref,
                eval_bundle_version=event.eval_bundle_version,
                overall=event.overall,
                verdict=event.verdict,
                status=event.status,
                timestamp=event.timestamp,
                weakest_dim=event.weakest_dim,
            ).model_dump(mode="json")
        )
    return JSONResponse({"history": entries})


def _artifact_response(request: Request, relative_path: str, artifact_type: str) -> JSONResponse:
    state = serve_state(request)
    run_id = str(request.path_params["run_id"])
    run_path = _finalized_run_path(state.runs_dir, run_id)
    _event_for_finalized_run(state.review_db_path, run_path)
    artifact_path = _artifact_path_for_read(run_path, relative_path)
    if artifact_path is None:
        raise InputError(f"artifact does not exist for run {run_id}: {relative_path}")
    envelope = RunArtifactEnvelope(
        run_id=run_id,
        artifact_type=artifact_type,
        content=artifact_path.read_text(encoding="utf-8"),
    )
    return JSONResponse(envelope.model_dump(mode="json"))


def _iter_latest_finalized_run_events(
    runs_dir: Path,
    db_path: Path,
) -> tuple[tuple[ResultEvent, dict[str, Any], Path], ...]:
    finalized_event_ids = _finalized_event_ids(runs_dir)
    by_run: dict[str, ResultEvent] = {}
    for event in load_result_events_from_db(db_path):
        if finalized_event_ids.get(event.run_id) == event.event_id:
            by_run[event.run_id] = event
    rows: list[tuple[ResultEvent, dict[str, Any], Path]] = []
    for run_id, event in by_run.items():
        run_path = runs_dir / run_id
        metadata = _load_run_metadata_or_none(run_path)
        if metadata is not None:
            rows.append((event, metadata, run_path))
    return tuple(rows)


def _finalized_event_ids(runs_dir: Path) -> dict[str, str]:
    if not runs_dir.exists():
        return {}
    event_ids: dict[str, str] = {}
    for path in runs_dir.iterdir():
        if path.is_symlink() or not path.is_dir() or path.name.endswith(".tmp"):
            continue
        marker_path = path / "finalized.json"
        if not marker_path.is_file():
            continue
        marker = _load_valid_finalized_marker(path)
        if marker is None:
            continue
        run_id = marker.get("run_id")
        event_id = marker.get("event_id")
        if run_id == path.name and isinstance(event_id, str) and event_id:
            event_ids[path.name] = event_id
    return event_ids


def _finalized_run_path(runs_dir: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    run_path = runs_dir / run_id
    if run_path.is_symlink() or not (run_path.is_dir() and (run_path / "finalized.json").is_file()):
        raise InputError(f"finalized run does not exist: {run_id}")
    return run_path


def _event_for_finalized_run(db_path: Path, run_path: Path) -> ResultEvent:
    marker = _load_valid_finalized_marker(run_path)
    if marker is None:
        raise InputError(f"finalized marker is invalid for run: {run_path.name}")
    event_id = marker.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise InputError(f"finalized marker is missing event_id for run: {run_path.name}")
    event = load_result_event_by_run_and_id(db_path, run_id=run_path.name, event_id=event_id)
    if event is not None:
        return event
    raise InputError(f"finalized result event does not exist for run: {run_path.name}")


def _summary_from_event(event: ResultEvent, metadata: dict[str, Any]) -> RunSummary | None:
    try:
        return RunSummary(
            run_id=event.run_id,
            source_ref=event.source_ref,
            source_kind=cast("Any", metadata.get("source_kind")),
            content_lang=cast("Any", metadata.get("content_lang") or "en"),
            capability_level=cast("Any", metadata.get("capability_level")),
            verdict=event.verdict,
            overall=event.overall,
            status=event.status,
            weakest_dim=event.weakest_dim,
            created_at=event.timestamp,
            degraded_flags=cast("Any", metadata.get("degraded_flags") or {}),
        )
    except Exception:
        return None


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InputError(f"expected JSON object in {path.name}")
    return cast("dict[str, Any]", payload)


def _load_run_metadata_or_none(run_path: Path) -> dict[str, Any] | None:
    try:
        return _load_json_object(run_path / "metadata.json")
    except (InputError, JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _load_valid_finalized_marker(run_path: Path) -> dict[str, Any] | None:
    try:
        marker = _load_json_object(run_path / "finalized.json")
    except (InputError, JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if marker.get("run_id") != run_path.name:
        return None
    if not isinstance(marker.get("event_id"), str) or not marker["event_id"]:
        return None
    if not isinstance(marker.get("finalized_at"), str) or not marker["finalized_at"]:
        return None
    if not isinstance(marker.get("artifact_count"), int) or marker["artifact_count"] < 0:
        return None
    if not isinstance(marker.get("checksum"), str) or not marker["checksum"]:
        return None
    try:
        artifact_count, checksum = finalized_artifact_digest(run_path)
    except (InputError, OSError):
        return None
    if marker["artifact_count"] != artifact_count or marker["checksum"] != checksum:
        return None
    return marker


def _artifact_path_for_read(run_path: Path, relative_path: str) -> Path | None:
    artifact_path = run_path / relative_path
    if not artifact_path.is_file() or artifact_path.is_symlink():
        return None
    try:
        artifact_path.resolve(strict=True).relative_to(run_path.resolve(strict=True))
    except (OSError, ValueError):
        return None
    return artifact_path


def _artifact_names(run_path: Path) -> list[str]:
    artifacts: list[str] = []
    for relative in sorted(_ALLOWED_ARTIFACTS):
        if _artifact_path_for_read(run_path, relative) is not None:
            artifacts.append(relative)
    return artifacts


__all__ = [
    "get_claims",
    "get_concepts",
    "get_diff",
    "get_lesson",
    "get_quiz",
    "get_ratchet_history",
    "get_run",
    "list_runs",
]
