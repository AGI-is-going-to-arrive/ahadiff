from __future__ import annotations

import errno
import hashlib
import json
import logging
import math
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
    ConceptLedgerEntry,
    ConceptLedgerPageResponse,
    ConceptsTextPageResponse,
    ErrorCode,
    LearnabilityInfo,
    RatchetHistoryEntry,
    RunArtifactEnvelope,
    RunDetail,
    RunSummary,
)
from ahadiff.contracts.event_log import RATCHET_COUNTED_STATUSES, ResultEvent
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import validate_run_id
from ahadiff.review.database import (
    connect_review_db,
    load_finalized_ratchet_history_page,
    load_result_event_by_run_and_id,
    load_result_events_page,
)
from ahadiff.wiki.concepts import (
    load_concepts_page,
    load_concepts_page_from_db,
    load_concepts_page_from_storage,
    load_visible_concepts,
    parse_jsonl_concepts_cursor,
)

from .auth import require_write_token, serve_state
from .locale import request_locale

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
    "distractor_gate": "quiz/distractor_gate.json",
    "graphify_signoff": "graphify_signoff.json",
    "judge": "judge.json",
    "judge_failure": "judge_failure.json",
    "misconceptions": "quiz/misconception_cards.jsonl",
    "quiz": "quiz/quiz.jsonl",
    "score": "score.json",
    "spec_alignment": "spec_alignment.json",
}
_LESSON_LEVELS = {"full", "hint", "compact"}
_SUPPORTED_CONTENT_LANGS = frozenset({"en", "zh-CN"})
_CANONICAL_GRAPHIFY_STATUSES = frozenset({"fresh", "stale", "unavailable", "disabled"})
_LEGACY_GRAPHIFY_STATUS_MAP: dict[str, str] = {
    "source_present": "stale",
    "missing_partial": "stale",
    "missing": "unavailable",
}
_SUPPORTED_GRAPHIFY_STATUSES = _CANONICAL_GRAPHIFY_STATUSES | frozenset(_LEGACY_GRAPHIFY_STATUS_MAP)
_CAPABILITY_LEVEL_WARNING_RUNS: set[str] = set()
_MAX_TEXT_ARTIFACT_BYTES = 10 * 1024 * 1024
_MAX_JSON_OBJECT_BYTES = 1024 * 1024
_MAX_LIST_RUNS = 500
_MAX_LIST_RUN_PAGES = 100
_MAX_RATCHET_HISTORY = 500
_MAX_RATCHET_TRANSPARENCY_RESULTS = 500
_MAX_BENCHMARK_ENTRIES = 8
_MAX_RATCHET_NOTE_CHARS = 64 * 1024
_MAX_RATCHET_NOTE_VALUE_CHARS = 2048
_MAX_RATCHET_NOTE_LIST_ITEMS = 32
_RATCHET_RESULT_COLUMNS = (
    "run_id",
    "source_ref",
    "base_ref",
    "prompt_version",
    "eval_bundle_version",
    "rubric_version",
    "overall",
    "verdict",
    "status",
    "timestamp",
    "weakest_dim",
    "note_json",
)
_RATCHET_HISTORY_NOTE_KEYS = frozenset(
    {
        "anchor_run_id",
        "baseline_overall",
        "cherry_pick_pending",
        "degraded_flags",
        "failed_gates",
        "phase25",
        "phase25_note",
        "ratchet_reason",
        "round",
        "target_dimension",
        "targeted_baseline_score",
        "targeted_candidate_score",
        "targeted_dimensions",
        "targeted_failed_gates",
        "targeted_passed",
        "targeted_reason",
        "trigger_reason",
        "verdict",
    }
)
_MAX_FINALIZED_ARTIFACTS = 64
_MAX_FINALIZED_ARTIFACT_DIRS = 64
_MAX_FINALIZED_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_FINALIZED_ARTIFACTS_TOTAL_BYTES = 50 * 1024 * 1024
_CONCEPT_LEDGER_FIELDS = frozenset(
    {
        "term_key",
        "concept",
        "display_name",
        "related_claims",
        "file_refs",
        "source_refs",
        "updated_by_runs",
        "graphify_node_id",
        "health_status",
    }
)
_CONCEPT_HEALTH_STATUSES = frozenset({"healthy", "orphan", "stale", "contradicted", "dismissed"})
_CANONICAL_RUN_ID_RE = re.compile(r"^run_[0-9a-f]{32}$")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
log = logging.getLogger(__name__)
_ALLOWED_ARTIFACTS = frozenset(
    {
        "claims.jsonl",
        "concepts.jsonl",
        "graphify_signoff.json",
        "judge.json",
        "judge_failure.json",
        "patch.diff",
        "quiz/distractor_gate.json",
        "quiz/misconception_cards.jsonl",
        "quiz/quiz.jsonl",
        "score.json",
        "spec_alignment.json",
        "lesson/lesson.full.md",
        "lesson/lesson.hint.md",
        "lesson/lesson.compact.md",
        "lesson/misconception.md",
        "lesson/not_proven.md",
    }
)


async def list_runs(request: Request) -> JSONResponse:
    state = serve_state(request)
    locale = request_locale(request)
    source_kind_filter = request.query_params.get("source_kind")
    limit = _query_limit(request, default=_MAX_LIST_RUNS, max_value=_MAX_LIST_RUNS)
    cursor = _query_cursor(request)
    payload = await to_thread.run_sync(
        _list_runs_payload,
        state.runs_dir,
        state.review_db_path,
        locale,
        source_kind_filter,
        limit,
        cursor,
    )
    return JSONResponse(payload)


async def get_run(request: Request) -> JSONResponse:
    state = serve_state(request)
    locale = request_locale(request)
    run_id = str(request.path_params["run_id"])
    payload = await to_thread.run_sync(
        _run_detail_payload,
        state.runs_dir,
        state.review_db_path,
        locale,
        run_id,
    )
    return JSONResponse(payload)


async def get_lesson(request: Request) -> JSONResponse:
    level = request.query_params.get("level", "full")
    if level not in _LESSON_LEVELS:
        raise InputError("lesson level must be one of: full, hint, compact")
    return await _artifact_response(
        request,
        f"lesson/lesson.{level}.md",
        "lesson",
        not_found_status_code=404,
    )


async def get_claims(request: Request) -> JSONResponse:
    return await _artifact_response(
        request,
        _ARTIFACT_PATHS["claims"],
        "claims",
        not_found_status_code=404,
    )


async def get_quiz(request: Request) -> JSONResponse:
    return await _artifact_response(
        request,
        _ARTIFACT_PATHS["quiz"],
        "quiz",
        not_found_status_code=404,
    )


async def get_misconceptions(request: Request) -> JSONResponse:
    return await _artifact_response(
        request,
        _ARTIFACT_PATHS["misconceptions"],
        "misconceptions",
        not_found_status_code=404,
    )


async def get_distractor_gate(request: Request) -> JSONResponse:
    return await _artifact_response(
        request,
        _ARTIFACT_PATHS["distractor_gate"],
        "distractor_gate",
        not_found_status_code=404,
    )


async def get_diff(request: Request) -> JSONResponse:
    return await _artifact_response(request, _ARTIFACT_PATHS["diff"], "diff")


async def get_score(request: Request) -> JSONResponse:
    return await _artifact_response(request, _ARTIFACT_PATHS["score"], "score")


async def get_judge(request: Request) -> JSONResponse:
    return await _artifact_response(
        request, _ARTIFACT_PATHS["judge"], "judge", not_found_status_code=404
    )


async def get_judge_failure(request: Request) -> JSONResponse:
    return await _artifact_response(
        request,
        _ARTIFACT_PATHS["judge_failure"],
        "judge_failure",
        not_found_status_code=404,
    )


async def get_spec_alignment_artifact(request: Request) -> JSONResponse:
    return await _artifact_response(
        request,
        _ARTIFACT_PATHS["spec_alignment"],
        "spec_alignment",
        not_found_status_code=404,
    )


async def get_graphify_signoff(request: Request) -> JSONResponse:
    return await _artifact_response(
        request,
        _ARTIFACT_PATHS["graphify_signoff"],
        "graphify_signoff",
        not_found_status_code=404,
    )


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
    raw_cursor = request.query_params.get("cursor")
    payload = await to_thread.run_sync(
        _concepts_payload,
        state.state_dir,
        limit,
        raw_cursor,
    )
    return JSONResponse(payload)


async def get_concepts_ledger(request: Request) -> JSONResponse:
    try:
        require_write_token(request)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    state = serve_state(request)
    limit = _query_limit(request, default=50, max_value=200)
    cursor = request.query_params.get("cursor")
    run_filter = request.query_params.get("run")
    result = await to_thread.run_sync(
        _concepts_ledger_sync,
        state,
        limit,
        cursor,
        run_filter,
    )
    return JSONResponse(result)


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


async def get_ratchet_transparency(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    payload = await to_thread.run_sync(_ratchet_transparency_payload, state)
    return JSONResponse(payload)


async def _artifact_response(
    request: Request,
    relative_path: str,
    artifact_type: str,
    *,
    not_found_status_code: int | None = None,
) -> JSONResponse:
    state = serve_state(request)
    locale = request_locale(request)
    run_id = str(request.path_params["run_id"])
    payload = await to_thread.run_sync(
        lambda: _artifact_payload(
            state,
            run_id,
            relative_path,
            artifact_type,
            not_found_status_code=not_found_status_code,
            default_locale=locale,
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
    default_locale: str | None = None,
) -> dict[str, Any]:
    run_path = _finalized_run_path(state.runs_dir, run_id)
    event = _event_for_finalized_run(state.review_db_path, run_path)
    artifact_path = _artifact_path_for_read(run_path, relative_path)
    if artifact_path is None:
        if not_found_status_code is not None:
            return {
                "_status_code": not_found_status_code,
                "error_code": ErrorCode.RUN_ARTIFACT_NOT_FOUND.value,
                "error": "artifact_not_found",
                "status": not_found_status_code,
            }
        raise InputError(f"artifact does not exist for run {run_id}: {relative_path}")
    envelope = RunArtifactEnvelope(
        run_id=run_id,
        artifact_type=artifact_type,
        content=_read_text_capped(artifact_path, max_bytes=_MAX_TEXT_ARTIFACT_BYTES),
        content_lang=_artifact_content_lang(state, run_path, event, default_locale=default_locale),
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
    learnability_info = _project_learnability(metadata)
    detail = RunDetail(
        **summary.model_dump(mode="json"),
        base_ref=event.base_ref,
        prompt_version=event.prompt_version,
        eval_bundle_version=event.eval_bundle_version,
        note_json=_public_result_event_note_json(event.note_json),
        artifacts=_artifact_names(run_path),
        graphify_mode=cast("Any", graphify_mode),
        graphify_status=graphify_status,
        graphify_notes=graphify_notes,
        learnability=learnability_info,
    )
    return detail.model_dump(mode="json")


def _concepts_payload(state_dir: Path, limit: int, cursor: str | None) -> dict[str, Any]:
    concepts_path = state_dir / "concepts.jsonl"
    db_path = state_dir / "review.sqlite"
    concepts_stat, concepts_blocked = _concepts_jsonl_leaf_stat(concepts_path)
    if concepts_stat is not None and concepts_stat.st_size > _MAX_TEXT_ARTIFACT_BYTES:
        raise HTTPException(status_code=413, detail="concepts.jsonl exceeds size limit")
    if concepts_blocked and not db_path.exists():
        return {"artifact_type": "concepts", "content": ""}
    if not (state_dir.parent / ".git").exists():
        if concepts_blocked:
            page = load_concepts_page_from_db(
                db_path,
                limit=limit,
                cursor=_db_cursor_from_storage_cursor(cursor),
            )
        else:
            page = load_concepts_page_from_storage(
                state_dir,
                limit=limit,
                cursor=cursor,
                max_bytes=_MAX_TEXT_ARTIFACT_BYTES,
            )
        page_entries = page.entries
        next_cursor = page.next_cursor
    else:
        offset = parse_jsonl_concepts_cursor(cursor)
        visible_concepts = load_visible_concepts(workspace_root=state_dir.parent)
        page_entries = visible_concepts[offset : offset + limit]
        next_cursor = None
        if offset + limit < len(visible_concepts):
            next_cursor = str(offset + limit)
    content = "".join(json.dumps(dict(entry), ensure_ascii=False) + "\n" for entry in page_entries)
    payload: dict[str, Any] = {"artifact_type": "concepts", "content": content}
    if next_cursor is not None:
        payload["next_cursor"] = next_cursor
    return ConceptsTextPageResponse.model_validate(payload).model_dump(
        mode="json",
        exclude_none=True,
    )


def _concepts_ledger_sync(
    state: ServeState,
    limit: int,
    cursor: str | None,
    run_filter: str | None,
) -> dict[str, Any]:
    offset = parse_jsonl_concepts_cursor(cursor)
    all_concepts = _concepts_ledger_entries(state)
    current_graph_node_ids = _current_graph_node_ids(state.state_dir)
    if run_filter:
        all_concepts = [
            entry
            for entry in all_concepts
            if run_filter in _string_list(entry.get("updated_by_runs", []))
        ]
    page_entries = all_concepts[offset : offset + limit]
    page_entries = [
        _drop_stale_graphify_node_id(entry, current_graph_node_ids) for entry in page_entries
    ]
    next_cursor = None
    if offset + limit < len(all_concepts):
        next_cursor = str(offset + limit)
    response = ConceptLedgerPageResponse(
        entries=[_concept_ledger_entry(entry) for entry in page_entries],
        next_cursor=next_cursor,
        total_count=len(all_concepts),
    )
    payload = response.model_dump(mode="json")
    entries_payload = payload.get("entries")
    if isinstance(entries_payload, list):
        for item in cast("list[Any]", entries_payload):
            if not isinstance(item, dict):
                continue
            entry = cast("dict[str, Any]", item)
            if entry.get("health_status") is None:
                entry.pop("health_status", None)
    return payload


def _current_graph_node_ids(state_dir: Path) -> set[str]:
    graph_path = state_dir / "graphify" / "graph.json"
    if not graph_path.exists():
        return set()
    try:
        from ahadiff.graphify import parse_graph_json

        graph = parse_graph_json(graph_path)
    except Exception:
        return set()
    return {node.id for node in graph.nodes}


def _drop_stale_graphify_node_id(
    entry: dict[str, Any],
    current_graph_node_ids: set[str],
) -> dict[str, Any]:
    graphify_node_id = entry.get("graphify_node_id")
    if not isinstance(graphify_node_id, str) or graphify_node_id in current_graph_node_ids:
        return entry
    scrubbed = dict(entry)
    scrubbed["graphify_node_id"] = None
    return scrubbed


def _concepts_ledger_entries(state: ServeState) -> list[dict[str, Any]]:
    workspace_root = state.state_dir.parent
    if (workspace_root / ".git").exists():
        return _merge_concept_health(
            state.review_db_path,
            list(load_visible_concepts(workspace_root=workspace_root)),
        )
    entries: list[dict[str, Any]] = []
    cursor = 0
    while True:
        page = load_concepts_page(
            state.state_dir / "concepts.jsonl",
            limit=1000,
            cursor=cursor,
            max_bytes=_MAX_TEXT_ARTIFACT_BYTES,
        )
        entries.extend(page.entries)
        if page.next_cursor is None:
            return _merge_concept_health(state.review_db_path, entries)
        cursor = parse_jsonl_concepts_cursor(page.next_cursor)


def _merge_concept_health(db_path: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not entries or not db_path.exists():
        return entries
    try:
        with connect_review_db(db_path) as connection:
            rows = connection.execute(
                "SELECT term_key, health_status FROM concept_status"
            ).fetchall()
    except Exception:
        return entries
    health_by_key: dict[str, str] = {}
    for row in rows:
        term_key = row["term_key"]
        health_status = row["health_status"]
        if isinstance(term_key, str) and isinstance(health_status, str):
            health_by_key[term_key] = health_status
    merged: list[dict[str, Any]] = []
    for entry in entries:
        term_key = entry.get("term_key")
        if isinstance(term_key, str) and term_key in health_by_key:
            next_entry = dict(entry)
            next_entry["health_status"] = health_by_key[term_key]
            merged.append(next_entry)
        else:
            merged.append(entry)
    return merged


def _concept_ledger_entry(entry: dict[str, Any]) -> ConceptLedgerEntry:
    payload = {key: entry[key] for key in _CONCEPT_LEDGER_FIELDS if key in entry}
    if payload.get("health_status") not in _CONCEPT_HEALTH_STATUSES:
        payload.pop("health_status", None)
    return ConceptLedgerEntry.model_validate(payload)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast("list[object]", value)
    return [item for item in items if isinstance(item, str)]


def _concepts_jsonl_leaf_stat(path: Path) -> tuple[os.stat_result | None, bool]:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return None, False
    except OSError as exc:
        raise InputError("concepts.jsonl is unreadable") from exc
    if stat.S_ISLNK(path_stat.st_mode) or _has_windows_reparse_point(path_stat):
        return None, True
    return path_stat, False


def _db_cursor_from_storage_cursor(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    if cursor.startswith("db:"):
        value = cursor.removeprefix("db:")
        if not value:
            raise InputError("concepts DB cursor must include a term key")
        return value
    if cursor.startswith("jsonl:"):
        raise InputError("concepts JSONL cursor cannot be used when concepts.jsonl is blocked")
    try:
        parse_jsonl_concepts_cursor(cursor)
    except InputError:
        return cursor
    raise InputError("concepts JSONL cursor cannot be used when concepts.jsonl is blocked")


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
                    note_json=_public_result_event_note_json(event.note_json),
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


def _ratchet_transparency_payload(state: ServeState) -> dict[str, Any]:
    return {
        "results": _ratchet_result_rows(state.review_db_path),
        "benchmark": _benchmark_transparency_payload(state),
    }


def _ratchet_result_rows(db_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not db_path.exists():
        return rows
    with connect_review_db(db_path) as connection:
        if (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'result_events'"
            ).fetchone()
            is None
        ):
            return rows
        records = connection.execute(
            f"""
            SELECT {", ".join(_RATCHET_RESULT_COLUMNS)}
            FROM result_events
            ORDER BY timestamp DESC, event_id DESC
            LIMIT ?
            """,
            (_MAX_RATCHET_TRANSPARENCY_RESULTS,),
        ).fetchall()
    for record in records:
        event = dict(record)
        overall = _finite_float(event.get("overall"))
        if overall is None:
            continue
        run_id = _string_or_none(event.get("run_id"))
        source_ref = _string_or_none(event.get("source_ref"))
        timestamp = _string_or_none(event.get("timestamp"))
        if run_id is None or source_ref is None or timestamp is None:
            continue
        note_json_value = event.get("note_json")
        note_json = note_json_value if isinstance(note_json_value, str) else None
        rows.append(
            {
                "run_id": run_id,
                "source_ref": source_ref,
                "base_ref": _string_or_none(event.get("base_ref")),
                "prompt_version": _string_or_none(event.get("prompt_version")) or "-",
                "eval_bundle_version": _string_or_none(event.get("eval_bundle_version")) or "-",
                "rubric_version": _string_or_none(event.get("rubric_version")),
                "overall": overall,
                "verdict": _string_or_none(event.get("verdict")) or "UNKNOWN",
                "status": _string_or_none(event.get("status")) or "unknown",
                "timestamp": timestamp,
                "weakest_dim": _string_or_none(event.get("weakest_dim")) or "unknown",
                "note_json": _public_result_event_note_json(note_json),
            }
        )
    return rows


def _benchmark_transparency_payload(state: ServeState) -> dict[str, Any]:
    manifest_summary, manifest_warnings = _benchmark_manifest_summary(
        state.state_dir.parent / "benchmarks" / "manifest.json"
    )
    report_summary, report_warnings = _benchmark_report_summary(
        state.state_dir / "benchmarks" / "local-report.json"
    )
    return {
        "manifest": manifest_summary,
        "report": report_summary,
        "warnings": [*manifest_warnings, *report_warnings],
    }


def _benchmark_manifest_summary(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, ["benchmark_manifest_missing"]
    try:
        payload = _load_json_object(path)
    except (HTTPException, InputError, OSError, UnicodeDecodeError, ValueError):
        return None, ["benchmark_manifest_unreadable"]

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        return None, ["benchmark_manifest_invalid"]

    eval_count = 0
    integration_count = 0
    degraded_count = 0
    languages: set[str] = set()
    groups: set[str] = set()
    for item in cast("list[object]", raw_entries):
        if not isinstance(item, dict):
            continue
        entry = cast("dict[str, object]", item)
        kind = entry.get("kind")
        if kind == "eval":
            eval_count += 1
        elif kind == "integration":
            integration_count += 1
        language = entry.get("language")
        if isinstance(language, str) and language:
            languages.add(language)
        group = entry.get("group")
        if isinstance(group, str) and group:
            groups.add(group)
        if entry.get("degraded") is True:
            degraded_count += 1

    return (
        {
            "schema_version": _finite_int(payload.get("schema_version")),
            "suite_id": _string_or_none(payload.get("suite_id")),
            "suite_digest": _string_or_none(payload.get("suite_digest")),
            "visibility": _string_or_none(payload.get("visibility")),
            "entry_count": eval_count + integration_count,
            "eval_entry_count": eval_count,
            "integration_entry_count": integration_count,
            "degraded_entry_count": degraded_count,
            "language_count": len(languages),
            "group_count": len(groups),
        },
        [],
    )


def _benchmark_report_summary(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, ["benchmark_report_missing"]
    try:
        payload = _load_json_object(path)
    except (HTTPException, InputError, OSError, UnicodeDecodeError, ValueError):
        return None, ["benchmark_report_unreadable"]

    raw_entries = payload.get("entries")
    entries: list[dict[str, Any]] = []
    if isinstance(raw_entries, list):
        for item in cast("list[object]", raw_entries)[:_MAX_BENCHMARK_ENTRIES]:
            entry = _benchmark_report_entry(item)
            if entry is not None:
                entries.append(entry)

    return (
        {
            "suite_id": _string_or_none(payload.get("suite_id")),
            "suite_digest": _string_or_none(payload.get("suite_digest")),
            "eval_bundle_version": _string_or_none(payload.get("eval_bundle_version")),
            "model_id": _string_or_none(payload.get("model_id")),
            "api_family_version": _string_or_none(payload.get("api_family_version")),
            "output_lang": _string_or_none(payload.get("output_lang")),
            "comparable_entry_count": _finite_int(payload.get("comparable_entry_count")),
            "excluded_degraded_count": _finite_int(payload.get("excluded_degraded_count")),
            "mean_score": _finite_float(payload.get("mean_score")),
            "claim_verification_rate": _finite_float(payload.get("claim_verification_rate")),
            "entries": entries,
        },
        [],
    )


def _benchmark_report_entry(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    entry = cast("dict[str, object]", value)
    degraded = entry.get("degraded")
    if not isinstance(degraded, bool):
        return None
    return {
        "id": _string_or_none(entry.get("id")),
        "group": _string_or_none(entry.get("group")),
        "language": _string_or_none(entry.get("language")),
        "degraded": degraded,
        "overall": _finite_float(entry.get("overall")),
        "verdict": _string_or_none(entry.get("verdict")),
        "weakest_dim": _string_or_none(entry.get("weakest_dim")),
        "claim_verification_rate": _finite_float(entry.get("claim_verification_rate")),
        "ground_truth_digest": _string_or_none(entry.get("ground_truth_digest")),
    }


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _finite_float(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
    return None


def _finite_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _public_result_event_note_json(note_json: str | None) -> str | None:
    if note_json is None:
        return None
    if len(note_json) > _MAX_RATCHET_NOTE_CHARS:
        return None
    try:
        parsed = safe_json_loads(note_json)
    except (JSONDecodeError, RecursionError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    payload: dict[str, object] = {}
    for key, value in cast("dict[object, object]", parsed).items():
        if not isinstance(key, str) or key not in _RATCHET_HISTORY_NOTE_KEYS:
            continue
        accepted, sanitized = _sanitize_ratchet_history_note_value(value)
        if accepted:
            payload[key] = sanitized
    if not payload:
        return None
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _sanitize_ratchet_history_note_value(value: object) -> tuple[bool, object]:
    if value is None or isinstance(value, bool):
        return True, value
    if isinstance(value, int) and not isinstance(value, bool):
        return True, value
    if isinstance(value, float):
        if math.isfinite(value):
            return True, value
        return False, None
    if isinstance(value, str):
        return True, value[:_MAX_RATCHET_NOTE_VALUE_CHARS]
    if isinstance(value, list):
        sanitized_items: list[object] = []
        for item in cast("list[object]", value)[:_MAX_RATCHET_NOTE_LIST_ITEMS]:
            if isinstance(item, list | dict):
                continue
            accepted, sanitized = _sanitize_ratchet_history_note_value(item)
            if accepted:
                sanitized_items.append(sanitized)
        return True, sanitized_items
    return False, None


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
    *,
    default_locale: str | None = None,
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
    return _normalize_content_lang(content_lang, default_locale=default_locale or state.locale)


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
    freshness_value = graphify.get("freshness") or graphify.get("status")
    if isinstance(freshness_value, str) and freshness_value in _SUPPORTED_GRAPHIFY_STATUSES:
        projected_freshness = _LEGACY_GRAPHIFY_STATUS_MAP.get(freshness_value, freshness_value)
        freshness = (
            projected_freshness if projected_freshness in _CANONICAL_GRAPHIFY_STATUSES else None
        )
    else:
        freshness = None

    notes: list[str] | None = None
    notes_value = graphify.get("notes")
    if isinstance(notes_value, list):
        notes_items = cast("list[object]", notes_value)
        if all(isinstance(note, str) for note in notes_items):
            notes = cast("list[str]", notes_items)

    if mode == "full" or freshness == "fresh":
        projected_mode = "full"
    elif mode == "learning_only" or freshness in {"stale", "unavailable"}:
        projected_mode = "learning_only"
    else:
        projected_mode = "empty"
    return projected_mode, freshness, notes


def _project_learnability(metadata: dict[str, Any]) -> LearnabilityInfo | None:
    raw = metadata.get("learnability")
    if not isinstance(raw, dict):
        return None
    learn = cast("dict[str, Any]", raw)
    score_raw = learn.get("score")
    threshold_raw = learn.get("threshold")
    skip_raw = learn.get("skip_lesson_quiz")
    if (
        not isinstance(score_raw, int | float)
        or isinstance(score_raw, bool)
        or not isinstance(threshold_raw, int | float)
        or isinstance(threshold_raw, bool)
        or not isinstance(skip_raw, bool)
    ):
        return None
    score = float(score_raw)
    threshold = float(threshold_raw)
    if not (
        math.isfinite(score)
        and math.isfinite(threshold)
        and 0.0 <= score <= 1.0
        and 0.0 <= threshold <= 1.0
    ):
        return None
    reasons_raw: object = learn.get("reasons", [])
    if reasons_raw is None:
        reasons: list[str] = []
    elif isinstance(reasons_raw, list):
        reason_items = cast("list[object]", reasons_raw)
        if not all(isinstance(reason, str) for reason in reason_items):
            return None
        reasons = [reason for reason in reason_items if isinstance(reason, str)]
    else:
        return None
    return LearnabilityInfo(
        score=score,
        threshold=threshold,
        skip_lesson_quiz=skip_raw,
        reasons=reasons,
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload: Any = safe_json_loads(_read_text_capped(path, max_bytes=_MAX_JSON_OBJECT_BYTES))
    except (JSONDecodeError, ValueError, OSError, UnicodeDecodeError) as exc:
        raise InputError(f"invalid JSON object in {path.name}") from exc
    if not isinstance(payload, dict):
        raise InputError(f"expected JSON object in {path.name}")
    return cast("dict[str, Any]", payload)


def _read_text_capped(path: Path, *, max_bytes: int) -> str:
    path_stat = os.lstat(path)
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError(f"{path.name} must not be a symlink")
    if _has_windows_reparse_point(path_stat):
        raise InputError(f"{path.name} must not be a Windows reparse point or junction")
    _reject_hardlinked_regular_file(path, path_stat, message=f"{path.name} must not be a hardlink")
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(f"{path.name} must not be a symlink") from exc
        raise
    try:
        opened_stat = os.fstat(fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise InputError(f"{path.name} must be a regular file")
        if _has_windows_reparse_point(opened_stat):
            raise InputError(f"{path.name} must not be a Windows reparse point or junction")
        _reject_hardlinked_regular_file(
            path,
            opened_stat,
            message=f"{path.name} must not be a hardlink",
        )
        if (opened_stat.st_dev, opened_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError(f"{path.name} changed during validation")
        size = opened_stat.st_size
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
    except (InputError, JSONDecodeError, ValueError, OSError, UnicodeDecodeError):
        return None


def _load_valid_finalized_marker(
    run_path: Path,
    *,
    verify_digest: bool = True,
) -> dict[str, Any] | None:
    try:
        marker = _load_json_object(run_path / "finalized.json")
    except (HTTPException, InputError, JSONDecodeError, ValueError, OSError, UnicodeDecodeError):
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


def finalized_marker_is_valid(run_path: Path) -> bool:
    return _load_valid_finalized_marker(run_path) is not None


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
                raise InputError(f"refusing symlink artifact in finalized run: {relative_path}")
            if _has_windows_reparse_point(entry_stat):
                raise InputError(
                    f"refusing Windows reparse point artifact in finalized run: {relative_path}"
                )
            if stat.S_ISDIR(entry_stat.st_mode):
                stack.append(path)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                continue
            _reject_hardlinked_regular_file(
                path,
                entry_stat,
                message=f"refusing hardlinked artifact in finalized run: {relative_path}",
            )
            if len(artifact_paths) >= _MAX_FINALIZED_ARTIFACTS:
                raise InputError("finalized run has too many artifacts")
            if entry_stat.st_size > _MAX_FINALIZED_ARTIFACT_BYTES:
                raise InputError("finalized run artifact exceeds size limit")
            total_bytes += entry_stat.st_size
            if total_bytes > _MAX_FINALIZED_ARTIFACTS_TOTAL_BYTES:
                raise InputError("finalized run artifacts exceed total size limit")
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
    path_stat = os.lstat(path)
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError(f"refusing symlink artifact in finalized run: {relative_path}")
    if _has_windows_reparse_point(path_stat):
        raise InputError(
            f"refusing Windows reparse point artifact in finalized run: {relative_path}"
        )
    _reject_hardlinked_regular_file(
        path,
        path_stat,
        message=f"refusing hardlinked artifact in finalized run: {relative_path}",
    )
    if (path_stat.st_dev, path_stat.st_ino) != (expected_stat.st_dev, expected_stat.st_ino):
        raise InputError("finalized run artifact changed during validation")
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
        if _has_windows_reparse_point(file_stat):
            raise InputError(
                f"refusing Windows reparse point artifact in finalized run: {relative_path}"
            )
        _reject_hardlinked_regular_file(
            path,
            file_stat,
            message=f"refusing hardlinked artifact in finalized run: {relative_path}",
        )
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


def _has_windows_reparse_point(path_stat: object) -> bool:
    if os.name != "nt":
        return False
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _reject_hardlinked_regular_file(path: Path, path_stat: os.stat_result, *, message: str) -> None:
    if stat.S_ISREG(path_stat.st_mode) and getattr(path_stat, "st_nlink", 1) > 1:
        raise InputError(message)


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
    "get_concepts_ledger",
    "get_diff",
    "get_distractor_gate",
    "get_graphify_signoff",
    "get_judge",
    "get_judge_failure",
    "get_lesson",
    "get_misconceptions",
    "get_quiz",
    "get_ratchet_history",
    "get_ratchet_transparency",
    "get_run",
    "get_run_concepts",
    "get_score",
    "get_spec_alignment_artifact",
    "finalized_marker_is_valid",
    "list_runs",
]
