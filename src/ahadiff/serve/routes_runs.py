from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import re
import stat
from json import JSONDecodeError
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from anyio import to_thread
from pydantic import ValidationError
from starlette.exceptions import HTTPException
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
from ahadiff.review.database import (
    load_finalized_ratchet_history_page,
    load_result_event_by_run_and_id,
    load_result_events_page,
)
from ahadiff.wiki.concepts import load_concepts_page

from .auth import serve_state

if TYPE_CHECKING:
    from starlette.requests import Request

    from .state import ServeState
else:
    Request = Any
    ServeState = Any

_ARTIFACT_PATHS = {
    "claims": "claims.jsonl",
    "concepts": "concepts.jsonl",
    "diff": "patch.diff",
    "quiz": "quiz/quiz.jsonl",
    "score": "score.json",
}
_LESSON_LEVELS = {"full", "hint", "compact"}
_SUPPORTED_CONTENT_LANGS = frozenset({"en", "zh-CN"})
_SUPPORTED_GRAPHIFY_STATUSES = frozenset({"fresh", "stale", "missing_partial", "missing"})
_CAPABILITY_LEVEL_WARNING_RUNS: set[str] = set()
_MAX_TEXT_ARTIFACT_BYTES = 10 * 1024 * 1024
_MAX_JSON_OBJECT_BYTES = 1024 * 1024
_MAX_LIST_RUNS = 500
_MAX_LIST_RUN_PAGES = 100
_MAX_RATCHET_HISTORY = 500
_MAX_FINALIZED_ARTIFACTS = 64
_MAX_FINALIZED_ARTIFACT_DIRS = 64
_MAX_FINALIZED_ARTIFACT_BYTES = 16 * 1024 * 1024
_CANONICAL_RUN_ID_RE = re.compile(r"^run_[0-9a-f]{32}$")
log = logging.getLogger(__name__)
_ALLOWED_ARTIFACTS = frozenset(
    {
        "claims.jsonl",
        "concepts.jsonl",
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
    limit = _query_limit(request, default=_MAX_LIST_RUNS, max_value=_MAX_LIST_RUNS)
    cursor = _query_cursor(request)
    payload = await to_thread.run_sync(
        _list_runs_payload,
        state.runs_dir,
        state.review_db_path,
        state.locale,
        source_kind_filter,
        limit,
        cursor,
    )
    return JSONResponse(payload)


async def get_run(request: Request) -> JSONResponse:
    state = serve_state(request)
    run_id = str(request.path_params["run_id"])
    payload = await to_thread.run_sync(
        _run_detail_payload,
        state.runs_dir,
        state.review_db_path,
        state.locale,
        run_id,
    )
    return JSONResponse(payload)


async def get_lesson(request: Request) -> JSONResponse:
    level = request.query_params.get("level", "full")
    if level not in _LESSON_LEVELS:
        raise InputError("lesson level must be one of: full, hint, compact")
    return await _artifact_response(request, f"lesson/lesson.{level}.md", "lesson")


async def get_claims(request: Request) -> JSONResponse:
    return await _artifact_response(request, _ARTIFACT_PATHS["claims"], "claims")


async def get_quiz(request: Request) -> JSONResponse:
    return await _artifact_response(request, _ARTIFACT_PATHS["quiz"], "quiz")


async def get_diff(request: Request) -> JSONResponse:
    return await _artifact_response(request, _ARTIFACT_PATHS["diff"], "diff")


async def get_run_concepts(request: Request) -> JSONResponse:
    return await _artifact_response(
        request,
        _ARTIFACT_PATHS["concepts"],
        "concepts",
        not_found_status_code=404,
    )


async def get_concepts(request: Request) -> JSONResponse:
    state = serve_state(request)
    limit = _query_limit(request, default=_MAX_LIST_RUNS, max_value=_MAX_LIST_RUNS)
    cursor = _query_line_cursor(request)
    payload = await to_thread.run_sync(
        _concepts_payload,
        state.state_dir,
        limit,
        cursor,
    )
    return JSONResponse(payload)


async def get_ratchet_history(request: Request) -> JSONResponse:
    state = serve_state(request)
    limit = _query_limit(request, default=_MAX_RATCHET_HISTORY, max_value=_MAX_RATCHET_HISTORY)
    cursor = _query_cursor(request)
    payload = await to_thread.run_sync(
        _ratchet_history_payload,
        state.runs_dir,
        state.review_db_path,
        limit,
        cursor,
    )
    return JSONResponse(payload)


async def _artifact_response(
    request: Request,
    relative_path: str,
    artifact_type: str,
    *,
    not_found_status_code: int | None = None,
) -> JSONResponse:
    state = serve_state(request)
    run_id = str(request.path_params["run_id"])
    payload = await to_thread.run_sync(
        lambda: _artifact_payload(
            state,
            run_id,
            relative_path,
            artifact_type,
            not_found_status_code=not_found_status_code,
        )
    )
    return JSONResponse(payload, status_code=payload.pop("_status_code", 200))


def _artifact_payload(
    state: ServeState,
    run_id: str,
    relative_path: str,
    artifact_type: str,
    *,
    not_found_status_code: int | None = None,
) -> dict[str, Any]:
    run_path = _finalized_run_path(state.runs_dir, run_id)
    event = _event_for_finalized_run(state.review_db_path, run_path)
    artifact_path = _artifact_path_for_read(run_path, relative_path)
    if artifact_path is None:
        if not_found_status_code is not None:
            return {
                "_status_code": not_found_status_code,
                "error": "artifact_not_found",
                "status": not_found_status_code,
            }
        raise InputError(f"artifact does not exist for run {run_id}: {relative_path}")
    envelope = RunArtifactEnvelope(
        run_id=run_id,
        artifact_type=artifact_type,
        content=_read_text_capped(artifact_path, max_bytes=_MAX_TEXT_ARTIFACT_BYTES),
        content_lang=_artifact_content_lang(state, run_path, event),
    )
    return envelope.model_dump(mode="json")


def _list_runs_payload(
    runs_dir: Path,
    db_path: Path,
    default_locale: str,
    source_kind_filter: str | None,
    limit: int,
    cursor: tuple[str, str] | None,
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    pages_scanned = 0
    next_cursor: tuple[str, str] | None = None
    while len(summaries) < limit and pages_scanned < _MAX_LIST_RUN_PAGES:
        pages_scanned += 1
        events = load_result_events_page(db_path, limit=limit, before=cursor)
        if not events:
            break
        for event in events:
            next_cursor = (event.timestamp, event.event_id)
            run_path = _finalized_event_run_path(runs_dir, event)
            if run_path is None:
                continue
            metadata = _load_run_metadata_or_none(run_path)
            if metadata is None:
                continue
            if source_kind_filter and metadata.get("source_kind") != source_kind_filter:
                continue
            summary = _summary_from_event(event, metadata, default_locale=default_locale)
            if summary is not None:
                summaries.append(summary.model_dump(mode="json"))
            if len(summaries) >= limit:
                break
        cursor = (events[-1].timestamp, events[-1].event_id)
        if len(events) < limit:
            next_cursor = None
            break
    return _payload_with_cursor(
        {"runs": summaries},
        next_cursor
        if len(summaries) >= limit or (pages_scanned >= _MAX_LIST_RUN_PAGES and next_cursor)
        else None,
    )


def _run_detail_payload(
    runs_dir: Path,
    db_path: Path,
    default_locale: str,
    run_id: str,
) -> dict[str, Any]:
    run_path = _finalized_run_path(runs_dir, run_id)
    event = _event_for_finalized_run(db_path, run_path)
    metadata = _load_json_object(run_path / "metadata.json")
    summary = _summary_from_event(event, metadata, default_locale=default_locale)
    if summary is None:
        raise InputError(f"run metadata is invalid: {run_id}")
    graphify_mode, graphify_status, graphify_notes = _project_graphify(metadata)
    detail = RunDetail(
        **summary.model_dump(mode="json"),
        base_ref=event.base_ref,
        prompt_version=event.prompt_version,
        eval_bundle_version=event.eval_bundle_version,
        note_json=event.note_json,
        artifacts=_artifact_names(run_path),
        graphify_mode=cast("Any", graphify_mode),
        graphify_status=graphify_status,
        graphify_notes=graphify_notes,
    )
    return detail.model_dump(mode="json")


def _concepts_payload(state_dir: Path, limit: int, cursor: int) -> dict[str, Any]:
    concepts_path = state_dir / "concepts.jsonl"
    if not concepts_path.exists() or concepts_path.is_symlink():
        return {"artifact_type": "concepts", "content": ""}
    if concepts_path.stat().st_size > _MAX_TEXT_ARTIFACT_BYTES:
        raise HTTPException(status_code=413, detail="concepts.jsonl exceeds size limit")
    page = load_concepts_page(
        concepts_path,
        limit=limit,
        cursor=cursor,
        max_bytes=_MAX_TEXT_ARTIFACT_BYTES,
    )
    content = "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in page.entries)
    payload: dict[str, Any] = {"artifact_type": "concepts", "content": content}
    if page.next_cursor is not None:
        payload["next_cursor"] = page.next_cursor
    return payload


def _ratchet_history_payload(
    runs_dir: Path,
    db_path: Path,
    limit: int,
    cursor: tuple[str, str] | None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    next_cursor: tuple[str, str] | None = None
    pages_scanned = 0
    while len(entries) < limit and pages_scanned < _MAX_LIST_RUN_PAGES:
        pages_scanned += 1
        events = load_finalized_ratchet_history_page(
            db_path,
            finalized_event_ids=(),
            statuses=RATCHET_COUNTED_STATUSES,
            limit=limit,
            before=cursor,
        )
        if not events:
            break
        for event in events:
            next_cursor = (event.timestamp, event.event_id)
            if _finalized_event_run_path(runs_dir, event) is None:
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
            if len(entries) >= limit:
                break
        cursor = (events[-1].timestamp, events[-1].event_id)
        if len(events) < limit:
            next_cursor = None
            break
    return _payload_with_cursor(
        {"history": entries},
        next_cursor
        if len(entries) >= limit or (pages_scanned >= _MAX_LIST_RUN_PAGES and next_cursor)
        else None,
    )


def _finalized_event_run_path(runs_dir: Path, event: ResultEvent) -> Path | None:
    try:
        _validate_route_run_id(event.run_id)
    except InputError:
        return None
    if event.run_id.endswith(".tmp"):
        return None
    run_path = runs_dir / event.run_id
    if run_path.is_symlink() or not run_path.is_dir():
        return None
    marker = _load_valid_finalized_marker(run_path)
    if marker is None or marker.get("event_id") != event.event_id:
        return None
    return run_path


def _payload_with_cursor(payload: dict[str, Any], cursor: tuple[str, str] | None) -> dict[str, Any]:
    if cursor is not None:
        payload["next_cursor"] = _encode_cursor(cursor)
    return payload


def _encode_cursor(cursor: tuple[str, str]) -> str:
    return f"{cursor[0]},{cursor[1]}"


def _artifact_content_lang(
    state: ServeState,
    run_path: Path,
    event: ResultEvent,
) -> Literal["en", "zh-CN"] | None:
    if not (run_path / "metadata.json").exists():
        return None
    metadata = _load_run_metadata_or_none(run_path)
    if metadata is None:
        return None
    if "content_lang" not in metadata:
        return None
    content_lang = metadata.get("content_lang")
    if content_lang is None:
        return None
    return _normalize_content_lang(content_lang, default_locale=state.locale)


def _finalized_run_path(runs_dir: Path, run_id: str) -> Path:
    _validate_route_run_id(run_id)
    if run_id.endswith(".tmp"):
        raise HTTPException(status_code=404, detail=f"finalized run does not exist: {run_id}")
    run_path = runs_dir / run_id
    if run_path.is_symlink() or not (run_path.is_dir() and (run_path / "finalized.json").is_file()):
        raise HTTPException(status_code=404, detail=f"finalized run does not exist: {run_id}")
    return run_path


def _validate_route_run_id(run_id: str) -> None:
    validate_run_id(run_id)
    if run_id.startswith("run_") and _CANONICAL_RUN_ID_RE.fullmatch(run_id) is None:
        raise InputError("run_id must be 'run_' followed by 32 lowercase hex characters")


def _query_limit(request: Request, *, default: int, max_value: int) -> int:
    raw_value = request.query_params.get("page_size", request.query_params.get("limit"))
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"page_size must be an integer between 1 and {max_value}",
        ) from exc
    if value < 1 or value > max_value:
        raise HTTPException(
            status_code=400,
            detail=f"page_size must be an integer between 1 and {max_value}",
        )
    return value


_MAX_CURSOR_LENGTH = 512


def _query_cursor(request: Request) -> tuple[str, str] | None:
    raw_value = request.query_params.get("cursor")
    if raw_value is None:
        return None
    if len(raw_value) > _MAX_CURSOR_LENGTH:
        raise HTTPException(status_code=400, detail="cursor value exceeds maximum length")
    timestamp, separator, event_id = raw_value.partition(",")
    if not separator or not timestamp or not event_id:
        raise HTTPException(
            status_code=400,
            detail="cursor must use '<timestamp>,<event_id>' format",
        )
    return timestamp, event_id


def _query_line_cursor(request: Request) -> int:
    raw_value = request.query_params.get("cursor")
    if raw_value is None:
        return 0
    if len(raw_value) > _MAX_CURSOR_LENGTH:
        raise HTTPException(status_code=400, detail="cursor value exceeds maximum length")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="cursor must be a non-negative line number"
        ) from exc
    if value < 0:
        raise HTTPException(status_code=400, detail="cursor must be a non-negative line number")
    return value


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


def _summary_from_event(
    event: ResultEvent,
    metadata: dict[str, Any],
    *,
    default_locale: str | None = None,
) -> RunSummary | None:
    try:
        return RunSummary(
            run_id=event.run_id,
            source_ref=event.source_ref,
            source_kind=cast("Any", metadata.get("source_kind")),
            content_lang=_normalize_content_lang(
                metadata.get("content_lang"),
                default_locale=default_locale,
            ),
            capability_level=_normalize_capability_level(
                metadata.get("capability_level"),
                run_id=event.run_id,
            ),
            verdict=event.verdict,
            overall=event.overall,
            status=event.status,
            weakest_dim=event.weakest_dim,
            created_at=event.timestamp,
            degraded_flags=cast("Any", metadata.get("degraded_flags") or {}),
        )
    except ValidationError as exc:
        log.warning("dropping run %s due to schema mismatch: %s", event.run_id, exc)
        return None


def _normalize_content_lang(
    value: object,
    *,
    default_locale: object = None,
) -> Literal["en", "zh-CN"]:
    if isinstance(value, str) and value in _SUPPORTED_CONTENT_LANGS:
        return cast("Literal['en', 'zh-CN']", value)
    if isinstance(default_locale, str) and default_locale in _SUPPORTED_CONTENT_LANGS:
        return cast("Literal['en', 'zh-CN']", default_locale)
    return "en"


def _normalize_capability_level(
    value: object,
    *,
    run_id: str,
) -> Literal[1, 2, 3]:
    if isinstance(value, int) and not isinstance(value, bool) and value in {1, 2, 3}:
        return cast("Literal[1, 2, 3]", value)
    if run_id not in _CAPABILITY_LEVEL_WARNING_RUNS:
        log.warning(
            "defaulting run %s capability_level to 1 due to invalid metadata value: %r",
            run_id,
            value,
        )
        if len(_CAPABILITY_LEVEL_WARNING_RUNS) < 10000:
            _CAPABILITY_LEVEL_WARNING_RUNS.add(run_id)
    return 1


def _project_graphify(metadata: dict[str, Any]) -> tuple[str, str | None, list[str] | None]:
    graphify_value = metadata.get("graphify")
    if not isinstance(graphify_value, dict):
        return "empty", None, None
    graphify = cast("dict[str, Any]", graphify_value)

    mode_value = graphify.get("mode")
    mode = mode_value if isinstance(mode_value, str) else None
    status_value = graphify.get("status")
    status = (
        status_value
        if isinstance(status_value, str) and status_value in _SUPPORTED_GRAPHIFY_STATUSES
        else None
    )

    notes: list[str] | None = None
    notes_value = graphify.get("notes")
    if isinstance(notes_value, list):
        notes_items = cast("list[object]", notes_value)
        if all(isinstance(note, str) for note in notes_items):
            notes = cast("list[str]", notes_items)

    if mode == "full" or status == "fresh":
        projected_mode = "full"
    elif mode == "learning_only" or status in {"stale", "missing_partial"}:
        projected_mode = "learning_only"
    else:
        projected_mode = "empty"
    return projected_mode, status, notes


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload: Any = json.loads(_read_text_capped(path, max_bytes=_MAX_JSON_OBJECT_BYTES))
    if not isinstance(payload, dict):
        raise InputError(f"expected JSON object in {path.name}")
    return cast("dict[str, Any]", payload)


def _read_text_capped(path: Path, *, max_bytes: int) -> str:
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        size = os.fstat(fd).st_size
        if size > max_bytes:
            raise HTTPException(status_code=413, detail=f"{path.name} exceeds size limit")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd != -1:
            os.close(fd)


def _load_run_metadata_or_none(run_path: Path) -> dict[str, Any] | None:
    try:
        return _load_json_object(run_path / "metadata.json")
    except (InputError, JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _load_valid_finalized_marker(
    run_path: Path,
    *,
    verify_digest: bool = True,
) -> dict[str, Any] | None:
    try:
        marker = _load_json_object(run_path / "finalized.json")
    except (HTTPException, InputError, JSONDecodeError, OSError, UnicodeDecodeError):
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
    if verify_digest:
        try:
            artifact_count, checksum = _bounded_finalized_artifact_digest(run_path)
        except (InputError, OSError):
            return None
        if marker["artifact_count"] != artifact_count or marker["checksum"] != checksum:
            return None
    return marker


def _bounded_finalized_artifact_digest(run_path: Path) -> tuple[int, str]:
    artifact_paths: list[tuple[str, Path, os.stat_result]] = []
    stack = [run_path]
    dirs_seen = 0
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
                raise InputError(f"refusing symlink artifact in finalized run: {relative_path}")
            if stat.S_ISDIR(entry_stat.st_mode):
                stack.append(path)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                continue
            if len(artifact_paths) >= _MAX_FINALIZED_ARTIFACTS:
                raise InputError("finalized run has too many artifacts")
            if entry_stat.st_size > _MAX_FINALIZED_ARTIFACT_BYTES:
                raise InputError("finalized run artifact exceeds size limit")
            artifact_paths.append((relative_path, path, entry_stat))
    chunks = [
        relative_path.encode("utf-8")
        + b"\n"
        + _hash_bounded_finalized_artifact(path, relative_path, entry_stat).encode("ascii")
        for relative_path, path, entry_stat in sorted(artifact_paths)
    ]
    return len(chunks), hashlib.sha256(b"\n---\n".join(chunks)).hexdigest()


def _hash_bounded_finalized_artifact(
    path: Path,
    relative_path: str,
    expected_stat: os.stat_result,
) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            message = f"refusing symlink artifact in finalized run: {relative_path}"
            raise InputError(message) from exc
        raise InputError("finalized run artifact is unreadable") from exc
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise InputError("finalized run artifact must be a regular file")
        if (file_stat.st_dev, file_stat.st_ino) != (expected_stat.st_dev, expected_stat.st_ino):
            raise InputError("finalized run artifact changed during validation")
        if file_stat.st_size > _MAX_FINALIZED_ARTIFACT_BYTES:
            raise InputError("finalized run artifact exceeds size limit")

        digest = hashlib.sha256()
        total_read = 0
        while True:
            chunk = os.read(fd, 65_536)
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > _MAX_FINALIZED_ARTIFACT_BYTES:
                raise InputError("finalized run artifact exceeds size limit")
            digest.update(chunk)
        return digest.hexdigest()
    except InputError:
        raise
    except OSError as exc:
        raise InputError("finalized run artifact is unreadable") from exc
    finally:
        os.close(fd)


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
    "get_run_concepts",
    "list_runs",
]
