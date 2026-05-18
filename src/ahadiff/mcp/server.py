from __future__ import annotations

import asyncio
import errno
import json
import logging
import math
import os
import re
import sqlite3
import stat
from collections.abc import Callable, Iterable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import ValidationError

from ahadiff.contracts import ErrorCode, ResultEvent
from ahadiff.contracts.quiz_choice import (
    AnswerMode,
    QuizChoice,
    validate_quiz_choices,
)
from ahadiff.core.errors import AhaDiffError, InputError, StorageError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import (
    reject_leaf_symlink_or_reparse,
    validate_run_id,
    validate_state_path_no_symlinks,
)
from ahadiff.core.sqlite_util import mcp_readonly_connect
from ahadiff.review.database import CURRENT_SCHEMA_VERSION
from ahadiff.review.schemas import (
    DueReviewCard,
    normalize_due_card_count,
    normalize_due_card_float,
    normalize_due_card_last_rating,
)
from ahadiff.wiki.concepts import load_concepts_page

from ._lesson_search import (
    DEFAULT_TOP_K as _ASK_LESSON_DEFAULT_TOP_K,
)
from ._lesson_search import (
    MAX_QUESTION_LENGTH as _ASK_LESSON_MAX_QUESTION,
)
from ._lesson_search import (
    MAX_TOP_K as _ASK_LESSON_MAX_TOP_K,
)
from ._lesson_search import (
    bounded_top_k,
    evidence_for_fragments,
    search_lesson,
    validate_question,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 200
_MAX_CONCEPTS_JSONL_BYTES = 16 * 1024 * 1024
_LESSON_SUMMARY_CHARS = 1200
_ASK_LESSON_MAX_LESSON_BYTES = 2 * 1024 * 1024
_ASK_LESSON_MAX_CLAIMS_BYTES = 5 * 1024 * 1024
_ASK_LESSON_LESSON_FILES: tuple[str, ...] = (
    "lesson.full.md",
    "lesson.hint.md",
    "lesson.compact.md",
)
_ALLOWED_TABLES = frozenset({"result_events", "review_logs", "cards", "concepts"})
_ALLOWED_FTS_TABLES = frozenset({"concepts", "result_events", "cards"})
_ALLOWED_GRAPH_FTS_TABLE = "fts_graph_nodes"
_FTS_MAX_QUERY_LENGTH = 500
_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_RESULT_EVENT_COLUMNS = (
    "event_id",
    "run_id",
    "event_type",
    "timestamp",
    "source_ref",
    "base_ref",
    "prompt_version",
    "eval_bundle_version",
    "rubric_version",
    "overall",
    "verdict",
    "status",
    "weakest_dim",
    "note_json",
)
_DUE_CARD_COLUMNS = (
    "id",
    "concept",
    "run_id",
    "due_date",
    "scaffolding_level",
    "stability",
    "difficulty",
    "reps",
    "lapses",
    "last_rating",
    "display_path",
    "source_ref",
    "symbol",
    "question",
    "answer",
    "answer_mode",
    "choices_json",
)

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


def create_mcp_server(state_dir: Path) -> Server[Any, Any]:
    """Create the read-only AhaDiff MCP server bound to a repository state dir."""
    resolved_state_dir = state_dir.expanduser().resolve()
    review_db = resolved_state_dir / "review.sqlite"
    server: Server[Any, Any] = Server("ahadiff")
    handlers = _tool_handlers(resolved_state_dir, review_db)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:  # pyright: ignore[reportUnusedFunction]
        return [
            types.Tool(
                name="list_runs",
                description="List recent AhaDiff result events with scores.",
                inputSchema=_object_schema(
                    {
                        "limit": _integer_schema(
                            "Maximum number of runs to return.",
                            default=_DEFAULT_LIMIT,
                            minimum=1,
                            maximum=_MAX_LIMIT,
                        ),
                    }
                ),
            ),
            types.Tool(
                name="get_run_summary",
                description="Get the latest score and lesson summary for a run.",
                inputSchema=_object_schema(
                    {
                        "run_id": {"type": "string", "description": "AhaDiff run id."},
                    },
                    required=("run_id",),
                ),
            ),
            types.Tool(
                name="list_due_cards",
                description="List active review cards that are due now.",
                inputSchema=_object_schema(
                    {
                        "limit": _integer_schema(
                            "Maximum number of cards to return.",
                            default=_DEFAULT_LIMIT,
                            minimum=1,
                            maximum=_MAX_LIMIT,
                        ),
                    }
                ),
            ),
            types.Tool(
                name="search",
                description=(
                    "Full-text search across AhaDiff concepts, result events, cards, "
                    "and graph nodes."
                ),
                inputSchema=_object_schema(
                    {
                        "query": {"type": "string", "description": "Literal search query."},
                        "limit": _integer_schema(
                            "Maximum number of search results.",
                            default=_DEFAULT_LIMIT,
                            minimum=1,
                            maximum=_MAX_LIMIT,
                        ),
                        "tables": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Optional subset: concepts, result_events, cards, graph_nodes."
                            ),
                        },
                        "include_graph": {
                            "type": "boolean",
                            "default": True,
                            "description": (
                                "Include imported graph search when graph data is available."
                            ),
                        },
                    },
                    required=("query",),
                ),
            ),
            types.Tool(
                name="get_concepts",
                description="List concepts from concepts.jsonl.",
                inputSchema=_object_schema(
                    {
                        "limit": _integer_schema(
                            "Maximum number of concepts to return.",
                            default=_DEFAULT_LIMIT,
                            minimum=1,
                            maximum=_MAX_LIMIT,
                        ),
                        "cursor": {
                            "type": "string",
                            "description": "Optional JSONL cursor returned by the previous call.",
                        },
                    }
                ),
            ),
            types.Tool(
                name="get_stats",
                description="Return aggregate AhaDiff run, review, card, concept, and score stats.",
                inputSchema=_object_schema({}),
            ),
            types.Tool(
                name="ask_lesson",
                description=(
                    "Return ranked lesson fragments and verified claim evidence "
                    "for a natural-language question about a specific run. "
                    'privacy: "strict_local"; read-only; no network or LLM calls.'
                ),
                inputSchema=_object_schema(
                    {
                        "run_id": {"type": "string", "description": "AhaDiff run id."},
                        "question": {
                            "type": "string",
                            "description": "Natural language question about the run lesson.",
                            "maxLength": _ASK_LESSON_MAX_QUESTION,
                        },
                        "top_k": _integer_schema(
                            "Maximum number of lesson fragments to return.",
                            default=_ASK_LESSON_DEFAULT_TOP_K,
                            minimum=1,
                            maximum=_ASK_LESSON_MAX_TOP_K,
                        ),
                    },
                    required=("run_id", "question"),
                ),
            ),
        ]

    @server.call_tool()
    async def call_tool(  # pyright: ignore[reportUnusedFunction]
        name: str,
        arguments: dict[str, Any],
    ) -> list[types.TextContent]:
        handler = handlers.get(name)
        if handler is None:
            return [_text_json({"error": f"unknown tool: {name}"})]
        try:
            return [_text_json(handler(arguments))]
        except AhaDiffError as exc:
            payload: dict[str, Any] = {
                "error": _public_mcp_error_message(exc),
                "tool": name,
                "error_code": exc.code.value,
            }
            return [_text_json(payload)]
        except (sqlite3.DatabaseError, OSError, ValueError, TypeError):
            logger.debug("MCP tool failed: %s", name, exc_info=True)
            return [_text_json({"error": "mcp_tool_failed", "tool": name})]

    return server


def _public_mcp_error_message(exc: AhaDiffError) -> str:
    if isinstance(exc, StorageError):
        return "storage_unavailable"
    if exc.code is ErrorCode.INPUT_VALIDATION:
        return "invalid input"
    return exc.code.value.lower()


async def run_mcp_stdio_server(state_dir: Path) -> None:
    server = create_mcp_server(state_dir)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run_mcp_server(state_dir: Path) -> None:
    asyncio.run(run_mcp_stdio_server(state_dir))


def _tool_handlers(state_dir: Path, review_db: Path) -> dict[str, ToolHandler]:
    return {
        "list_runs": lambda arguments: _list_runs(review_db, arguments),
        "get_run_summary": lambda arguments: _get_run_summary(state_dir, review_db, arguments),
        "list_due_cards": lambda arguments: _list_due_cards(review_db, arguments),
        "search": lambda arguments: _search(state_dir, review_db, arguments),
        "get_concepts": lambda arguments: _get_concepts(state_dir, arguments),
        "get_stats": lambda _arguments: _get_stats(state_dir, review_db),
        "ask_lesson": lambda arguments: _ask_lesson(state_dir, arguments),
    }


def _list_runs(db_path: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = _limit_from_args(arguments)
    events = _load_recent_result_events(db_path, limit=limit)
    return {
        "runs": [_result_event_payload(event.model_dump(mode="json")) for event in events],
    }


def _get_run_summary(state_dir: Path, db_path: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    run_id = _required_str(arguments, "run_id")
    validate_run_id(run_id)
    event = _load_latest_result_event_for_run(db_path, run_id)
    if event is None:
        return {"run_id": run_id, "found": False}
    payload = _result_event_payload(event)
    payload["found"] = True
    payload["lesson_summary"] = _read_lesson_summary(state_dir, run_id)
    return payload


def _list_due_cards(db_path: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    if not db_path.exists():
        return {"cards": []}
    limit = _limit_from_args(arguments)
    cards = _read_due_cards(db_path, limit=limit)
    return {"cards": [_due_card_payload(card) for card in cards]}


def _search(state_dir: Path, db_path: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = _required_str(arguments, "query")
    limit = _limit_from_args(arguments)
    tables = _optional_tables(arguments.get("tables"))
    include_graph = _optional_bool(arguments.get("include_graph"), default=True)
    graph = _load_graph(state_dir) if include_graph else None
    results = _search_with_graph(
        db_path,
        query,
        limit=limit,
        tables=tables,
        include_graph=include_graph,
        graph=graph,
    )
    return {"results": results}


def _get_concepts(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = _limit_from_args(arguments)
    raw_cursor = arguments.get("cursor")
    cursor = (
        int(raw_cursor)
        if isinstance(raw_cursor, int)
        else int(str(raw_cursor))
        if raw_cursor
        else 0
    )
    page = load_concepts_page(
        state_dir / "concepts.jsonl",
        limit=limit,
        cursor=cursor,
        max_bytes=_MAX_CONCEPTS_JSONL_BYTES,
    )
    payload: dict[str, Any] = {"concepts": [dict(entry) for entry in page.entries]}
    if page.next_cursor is not None:
        payload["next_cursor"] = page.next_cursor
    return payload


def _get_stats(state_dir: Path, db_path: Path) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "total_runs": 0,
        "total_result_events": 0,
        "total_reviews": 0,
        "total_cards": 0,
        "total_due_cards": 0,
        "total_concepts": _count_concepts_jsonl(state_dir),
        "avg_overall_score": None,
        "last_run_at": None,
    }
    if not db_path.exists():
        return stats
    connection = mcp_readonly_connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        stats["total_result_events"] = _count_table_rows(connection, "result_events")
        stats["total_runs"] = _count_distinct_runs(connection)
        stats["total_reviews"] = _count_table_rows(connection, "review_logs")
        stats["total_cards"] = _count_table_rows(connection, "cards")
        stats["total_due_cards"] = _count_due_cards(connection)
        stats["avg_overall_score"] = _avg_overall_score(connection)
        stats["last_run_at"] = _max_timestamp(connection)
        stats["total_concepts"] = max(
            int(stats["total_concepts"]),
            _count_table_rows(connection, "concepts"),
        )
    finally:
        connection.close()
    return stats


def _ask_lesson(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    raw_run_id = arguments.get("run_id")
    if not isinstance(raw_run_id, str) or not raw_run_id.strip():
        raise InputError("run_id is required", code=ErrorCode.INPUT_VALIDATION)
    run_id = raw_run_id.strip()
    try:
        validate_run_id(run_id)
    except InputError as exc:
        raise InputError(str(exc), code=ErrorCode.INPUT_VALIDATION) from exc
    raw_question = arguments.get("question")
    if not isinstance(raw_question, str):
        raise InputError("question is required", code=ErrorCode.INPUT_VALIDATION)
    try:
        question = validate_question(raw_question)
    except ValueError as exc:
        raise InputError(str(exc), code=ErrorCode.INPUT_VALIDATION) from exc
    top_k = bounded_top_k(arguments.get("top_k"), default=_ASK_LESSON_DEFAULT_TOP_K)

    run_dir = state_dir / "runs" / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise InputError(f"run not found: {run_id}", code=ErrorCode.RUN_NOT_FOUND)

    finalized_path = run_dir / "finalized.json"
    if not finalized_path.exists():
        raise InputError(
            f"run is not finalized: {run_id}",
            code=ErrorCode.RUN_NOT_FOUND,
        )
    try:
        finalized_stat = reject_leaf_symlink_or_reparse(
            finalized_path,
            label="mcp finalized marker",
        )
    except InputError as exc:
        raise InputError(
            f"run is not finalized: {run_id}",
            code=ErrorCode.RUN_NOT_FOUND,
        ) from exc
    if not stat.S_ISREG(finalized_stat.st_mode):
        raise InputError(
            f"run is not finalized: {run_id}",
            code=ErrorCode.RUN_NOT_FOUND,
        )

    lesson_text, lesson_file = _read_first_lesson_file(state_dir, run_id)
    run_meta: dict[str, Any] = {
        "run_id": run_id,
        "generated_at": _read_run_generated_at(state_dir, finalized_path),
        "lesson_tier": _lesson_tier_from_file(lesson_file),
        "lesson_file": lesson_file,
    }

    if lesson_text is None:
        return {"fragments": [], "evidence": [], "run_meta": run_meta}

    fragments = search_lesson(lesson_text, question, top_k=top_k)
    if not fragments:
        return {"fragments": [], "evidence": [], "run_meta": run_meta}

    claims = _read_claims_jsonl(state_dir, run_dir)
    evidence = evidence_for_fragments(fragments, claims) if claims else []
    return {"fragments": fragments, "evidence": evidence, "run_meta": run_meta}


def _read_run_generated_at(state_dir: Path, finalized_path: Path) -> str | None:
    try:
        raw_bytes = _read_mcp_regular_bytes(
            finalized_path,
            label="mcp finalized marker",
            max_bytes=1_000_000,
            state_dir=state_dir,
        )
        payload = safe_json_loads(raw_bytes.decode("utf-8", errors="replace"))
    except (InputError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    finalized = cast("dict[str, Any]", payload)
    for key in ("generated_at", "finalized_at", "timestamp", "created_at_utc"):
        value = finalized.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _lesson_tier_from_file(lesson_file: str | None) -> str | None:
    if lesson_file is None:
        return None
    mapping = {
        "lesson.full.md": "full",
        "lesson.hint.md": "hint",
        "lesson.compact.md": "compact",
    }
    return mapping.get(lesson_file)


def _read_first_lesson_file(state_dir: Path, run_id: str) -> tuple[str | None, str | None]:
    lesson_dir = state_dir / "runs" / run_id / "lesson"
    for name in _ASK_LESSON_LESSON_FILES:
        path = lesson_dir / name
        if not path.exists():
            continue
        try:
            validate_state_path_no_symlinks(path, allow_missing_leaf=False)
        except InputError as exc:
            logger.warning("rejected lesson path %s: %s", path, exc)
            continue
        try:
            text = _read_lesson_text(path, state_dir=state_dir)
        except InputError as exc:
            logger.warning("failed to read lesson %s: %s", path, exc)
            continue
        return text, name
    return None, None


def _read_lesson_text(path: Path, *, state_dir: Path | None = None) -> str:
    raw_bytes = _read_mcp_regular_bytes(
        path,
        label="mcp lesson artifact",
        max_bytes=_ASK_LESSON_MAX_LESSON_BYTES,
        state_dir=state_dir,
    )
    try:
        return raw_bytes.decode("utf-8", errors="replace")
    except UnicodeDecodeError as exc:
        raise InputError(f"lesson file is not valid UTF-8: {path}") from exc


def _read_mcp_regular_bytes(
    path: Path,
    *,
    label: str,
    max_bytes: int,
    state_dir: Path | None = None,
) -> bytes:
    if state_dir is not None and _supports_secure_relative_open():
        return _read_mcp_regular_bytes_from_state_dir(
            state_dir,
            path,
            label=label,
            max_bytes=max_bytes,
        )
    return _read_mcp_regular_bytes_by_path(path, label=label, max_bytes=max_bytes)


def _read_mcp_regular_bytes_by_path(path: Path, *, label: str, max_bytes: int) -> bytes:
    leaf_stat = reject_leaf_symlink_or_reparse(path, label=label)
    _validate_mcp_regular_stat(leaf_stat, path=path, label=label, max_bytes=max_bytes)

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(os.fspath(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(f"{label} must not be a symlink: {path}") from exc
        raise InputError(f"{label} is unreadable: {path}") from exc

    try:
        file_stat = os.fstat(fd)
        _validate_mcp_regular_stat(file_stat, path=path, label=label, max_bytes=max_bytes)
        if (file_stat.st_dev, file_stat.st_ino) != (leaf_stat.st_dev, leaf_stat.st_ino):
            raise InputError(f"{label} changed during validation: {path}")
        return _read_bounded_fd(fd, path=path, label=label, max_bytes=max_bytes)
    finally:
        os.close(fd)


def _read_mcp_regular_bytes_from_state_dir(
    state_dir: Path,
    path: Path,
    *,
    label: str,
    max_bytes: int,
) -> bytes:
    validate_state_path_no_symlinks(path, allow_missing_leaf=False)
    leaf_stat = reject_leaf_symlink_or_reparse(path, label=label)
    _validate_mcp_regular_stat(leaf_stat, path=path, label=label, max_bytes=max_bytes)

    root = state_dir if state_dir.is_absolute() else state_dir.absolute()
    target = path if path.is_absolute() else path.absolute()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise InputError(f"{label} must stay under state dir: {path}") from exc
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise InputError(f"{label} path is invalid: {path}")

    validate_state_path_no_symlinks(root, allow_missing_leaf=False)
    root_stat = root.lstat()
    if not stat.S_ISDIR(root_stat.st_mode):
        raise InputError(f"mcp state dir is not a directory: {root}")

    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    current_fd = os.open(os.fspath(root), dir_flags)
    try:
        opened_root_stat = os.fstat(current_fd)
        if (opened_root_stat.st_dev, opened_root_stat.st_ino) != (
            root_stat.st_dev,
            root_stat.st_ino,
        ):
            raise InputError(f"mcp state dir changed during validation: {root}")

        for part in parts[:-1]:
            parent_fd = current_fd
            current_fd = _open_mcp_child_dir(parent_fd, part, path=path, label=label)
            os.close(parent_fd)

        leaf_name = parts[-1]
        relative_leaf_stat = os.stat(leaf_name, dir_fd=current_fd, follow_symlinks=False)
        _validate_mcp_regular_stat(
            relative_leaf_stat,
            path=path,
            label=label,
            max_bytes=max_bytes,
        )
        try:
            file_fd = os.open(leaf_name, file_flags, dir_fd=current_fd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise InputError(f"{label} must not be a symlink: {path}") from exc
            raise InputError(f"{label} is unreadable: {path}") from exc
        try:
            file_stat = os.fstat(file_fd)
            _validate_mcp_regular_stat(file_stat, path=path, label=label, max_bytes=max_bytes)
            if (file_stat.st_dev, file_stat.st_ino) != (
                relative_leaf_stat.st_dev,
                relative_leaf_stat.st_ino,
            ):
                raise InputError(f"{label} changed during validation: {path}")
            return _read_bounded_fd(file_fd, path=path, label=label, max_bytes=max_bytes)
        finally:
            os.close(file_fd)
    finally:
        os.close(current_fd)


def _supports_secure_relative_open() -> bool:
    return (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    )


def _open_mcp_child_dir(parent_fd: int, name: str, *, path: Path, label: str) -> int:
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        child_fd = os.open(name, dir_flags, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(f"{label} parent must not be a symlink: {path}") from exc
        raise InputError(f"{label} parent is unreadable: {path}") from exc
    try:
        child_stat = os.fstat(child_fd)
        if not stat.S_ISDIR(child_stat.st_mode):
            raise InputError(f"{label} parent is not a directory: {path}")
        if _stat_has_windows_reparse_point(child_stat):
            raise InputError(f"{label} parent must not be a Windows reparse point: {path}")
        return child_fd
    except Exception:
        os.close(child_fd)
        raise


def _validate_mcp_regular_stat(
    file_stat: os.stat_result,
    *,
    path: Path,
    label: str,
    max_bytes: int,
) -> None:
    if stat.S_ISLNK(file_stat.st_mode):
        raise InputError(f"{label} must not be a symlink: {path}")
    if _stat_has_windows_reparse_point(file_stat):
        raise InputError(f"{label} must not be a Windows reparse point: {path}")
    if not stat.S_ISREG(file_stat.st_mode):
        raise InputError(f"{label} is not a regular file: {path}")
    if getattr(file_stat, "st_nlink", 1) > 1:
        raise InputError(f"{label} must not be a hardlink: {path}")
    if file_stat.st_size > max_bytes:
        raise InputError(f"{label} too large (>{max_bytes} bytes): {path}")


def _stat_has_windows_reparse_point(file_stat: object) -> bool:
    return bool(getattr(file_stat, "st_file_attributes", 0) & 0x400)


def _read_bounded_fd(fd: int, *, path: Path, label: str, max_bytes: int) -> bytes:
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
            raise InputError(f"{label} too large (>{max_bytes} bytes): {path}")
    return b"".join(chunks)


def _read_claims_jsonl(state_dir: Path, run_dir: Path) -> list[dict[str, Any]]:
    claims_path = run_dir / "claims.jsonl"
    if not claims_path.exists():
        return []
    try:
        validate_state_path_no_symlinks(claims_path, allow_missing_leaf=False)
    except InputError as exc:
        logger.warning("rejected claims path %s: %s", claims_path, exc)
        return []
    try:
        raw_bytes = _read_mcp_regular_bytes(
            claims_path,
            label="mcp claims artifact",
            max_bytes=_ASK_LESSON_MAX_CLAIMS_BYTES,
            state_dir=state_dir,
        )
    except InputError as exc:
        logger.warning("rejected claims path %s: %s", claims_path, exc)
        return []
    text = raw_bytes.decode("utf-8", errors="replace")
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = safe_json_loads(stripped)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(payload, dict):
            records.append(cast("dict[str, Any]", payload))
    return records


def _load_latest_result_event_for_run(db_path: Path, run_id: str) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    connection = mcp_readonly_connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        if not _table_exists(connection, "result_events"):
            return None
        row = connection.execute(
            f"""
            SELECT {", ".join(_RESULT_EVENT_COLUMNS)}
            FROM result_events
            WHERE run_id = ?
            ORDER BY timestamp DESC, event_id DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    finally:
        connection.close()
    return None if row is None else dict(row)


def _load_recent_result_events(db_path: Path, *, limit: int) -> tuple[ResultEvent, ...]:
    if limit <= 0 or not db_path.exists():
        return ()
    connection = mcp_readonly_connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        if not _table_exists(connection, "result_events"):
            return ()
        rows = connection.execute(
            f"""
            SELECT {", ".join(_RESULT_EVENT_COLUMNS)}
            FROM result_events
            ORDER BY timestamp DESC, event_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    return tuple(ResultEvent.model_validate(dict(row)) for row in rows)


def _read_due_cards(db_path: Path, *, limit: int) -> tuple[DueReviewCard, ...]:
    connection = mcp_readonly_connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        if not _table_exists(connection, "cards"):
            return ()
        if _sqlite_user_version(connection) != CURRENT_SCHEMA_VERSION:
            return ()
        if not _table_has_columns(connection, "cards", _DUE_CARD_COLUMNS):
            return ()
        rows = connection.execute(
            f"""
            SELECT {", ".join(_DUE_CARD_COLUMNS)}
            FROM cards
            WHERE card_state = 'active'
              AND due_date <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            ORDER BY due_date ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    return tuple(_row_to_due_review_card(row) for row in rows)


def _search_with_graph(
    db_path: Path,
    query: str,
    *,
    limit: int,
    tables: tuple[str, ...] | None,
    include_graph: bool,
    graph: object | None,
) -> list[dict[str, Any]]:
    if not query.strip() or not db_path.exists() or limit < 1:
        return []
    if len(query) > _FTS_MAX_QUERY_LENGTH:
        raise InputError(f"search query exceeds {_FTS_MAX_QUERY_LENGTH} characters")
    sanitized = _sanitize_fts_query(query)
    if not sanitized:
        return []

    target_tables: tuple[str, ...] = (
        ("concepts", "result_events", "cards") if tables is None else tables
    )

    raw_results: list[tuple[str, str, str, float, str | None]] = []
    graph_fts_rows: list[tuple[str, str, str, float, str | None]] = []
    connection = mcp_readonly_connect(db_path)
    try:
        for table_name in target_tables:
            if table_name not in _ALLOWED_FTS_TABLES:
                continue
            fts_table = f"fts_{table_name}"
            if not _fts_table_exists(connection, fts_table):
                continue
            raw_results.extend(
                _fts_query_table(connection, table_name, fts_table, sanitized, limit)
            )

        if (
            include_graph
            and (tables is None or "graph_nodes" in tables)
            and _fts_table_exists(connection, _ALLOWED_GRAPH_FTS_TABLE)
        ):
            try:
                rows = connection.execute(
                    f"""
                    SELECT id,
                           snippet({_ALLOWED_GRAPH_FTS_TABLE}, -1, '<b>', '</b>', '...', 32),
                           rank
                    FROM {_ALLOWED_GRAPH_FTS_TABLE}
                    WHERE {_ALLOWED_GRAPH_FTS_TABLE} MATCH ?
                    ORDER BY rank, id ASC
                    LIMIT ?
                    """,
                    (sanitized, limit),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                raise StorageError(
                    f"FTS search failed for {_ALLOWED_GRAPH_FTS_TABLE}: {exc}"
                ) from exc
            graph_fts_rows = [
                ("graph_nodes", str(row[0]), str(row[1]), float(row[2]), None) for row in rows
            ]
    finally:
        connection.close()

    raw_results.sort(key=lambda r: (r[3], r[0], r[1]))
    raw_results = raw_results[:limit]

    merged: list[dict[str, Any]] = [
        {
            "source_table": r[0],
            "primary_key": r[1],
            "snippet": r[2],
            "rank": _normalize_fts_rank(r[3]),
            "href": r[4],
        }
        for r in raw_results
    ]

    if include_graph and (tables is None or "graph_nodes" in tables):
        seen_ids: set[str] = {r[1] for r in graph_fts_rows}
        for r in graph_fts_rows:
            merged.append(
                {
                    "source_table": r[0],
                    "primary_key": r[1],
                    "snippet": r[2],
                    "rank": _normalize_fts_rank(r[3]),
                    "href": r[4],
                }
            )
        if graph is not None:
            from ahadiff.graphify.search import search_graph_nodes

            graph_results = search_graph_nodes(graph, query, limit=limit)  # type: ignore[arg-type]
            for gr in graph_results:
                if gr.node_id not in seen_ids:
                    merged.append(
                        {
                            "source_table": "graph_nodes",
                            "primary_key": gr.node_id,
                            "snippet": gr.label,
                            "rank": gr.score,
                            "href": None,
                        }
                    )

    merged.sort(
        key=lambda r: (
            -float(cast("float", r["rank"])),
            str(r["source_table"]),
            str(r["primary_key"]),
        )
    )
    return merged[:limit]


def _fts_query_table(
    connection: sqlite3.Connection,
    source_table: str,
    fts_table: str,
    query: str,
    limit: int,
) -> list[tuple[str, str, str, float, str | None]]:
    if source_table == "result_events":
        try:
            rows = connection.execute(
                f"""
                SELECT
                    {fts_table}.event_id,
                    result_events.run_id,
                    snippet({fts_table}, -1, '<b>', '</b>', '...', 32),
                    rank
                FROM {fts_table}
                JOIN result_events ON result_events.event_id = {fts_table}.event_id
                WHERE {fts_table} MATCH ?
                ORDER BY rank, {fts_table}.event_id ASC
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise StorageError(f"FTS search failed for {fts_table}: {exc}") from exc
        return [
            (
                source_table,
                str(row[0]),
                str(row[2]),
                float(row[3]),
                f"#/run/{quote(str(row[1]), safe='')}/lesson",
            )
            for row in rows
        ]
    pk_col = _pk_column(source_table)
    try:
        rows = connection.execute(
            f"""
            SELECT {pk_col}, snippet({fts_table}, -1, '<b>', '</b>', '...', 32), rank
            FROM {fts_table}
            WHERE {fts_table} MATCH ?
            ORDER BY rank, {pk_col} ASC
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise StorageError(f"FTS search failed for {fts_table}: {exc}") from exc
    return [(source_table, str(row[0]), str(row[1]), float(row[2]), None) for row in rows]


def _pk_column(source_table: str) -> str:
    if source_table == "concepts":
        return "term_key"
    if source_table == "result_events":
        return "event_id"
    if source_table == "cards":
        return "id"
    return "rowid"


def _normalize_fts_rank(rank: float) -> float:
    return 1.0 - 1.0 / (1.0 + abs(rank))


def _sanitize_fts_query(query: str) -> str:
    tokens = _FTS_TOKEN_RE.findall(query)
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens)


def _fts_table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _row_to_due_review_card(row: sqlite3.Row) -> DueReviewCard:
    answer = cast("str | None", row["answer"])
    answer_mode, choices = _deserialize_card_choices(
        row["answer_mode"],
        row["choices_json"],
        expected_answer=answer,
    )
    return DueReviewCard(
        card_id=str(row["id"]),
        concept=str(row["concept"]),
        run_id=str(row["run_id"]),
        due_date=str(row["due_date"]),
        scaffolding_level=str(row["scaffolding_level"]),
        display_path=str(row["display_path"]),
        stability=normalize_due_card_float(row["stability"]),
        difficulty=normalize_due_card_float(row["difficulty"]),
        reps=normalize_due_card_count(row["reps"]),
        lapses=normalize_due_card_count(row["lapses"]),
        last_rating=normalize_due_card_last_rating(row["last_rating"]),
        source_ref=cast("str | None", row["source_ref"]),
        symbol=cast("str | None", row["symbol"]),
        question=cast("str | None", row["question"]),
        answer=answer,
        answer_mode=answer_mode,
        choices=choices,
    )


def _deserialize_card_choices(
    answer_mode: object,
    choices_json: object,
    *,
    expected_answer: str | None,
) -> tuple[AnswerMode, tuple[QuizChoice, ...] | None]:
    if not isinstance(answer_mode, str) or answer_mode not in {"open", "multiple_choice"}:
        raise StorageError(f"invalid review card answer_mode: {answer_mode!r}")
    mode = cast("AnswerMode", answer_mode)
    if mode == "open":
        if choices_json not in (None, ""):
            raise StorageError("open review card unexpectedly stores choices_json")
        return mode, None
    if not isinstance(choices_json, str) or not choices_json.strip():
        raise StorageError("multiple_choice review card is missing choices_json")
    if not isinstance(expected_answer, str) or not expected_answer.strip():
        raise StorageError("multiple_choice review cards require a non-empty answer")
    try:
        payload = safe_json_loads(choices_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise StorageError("review card choices_json is not valid JSON") from exc
    if not isinstance(payload, list | tuple):
        raise StorageError("multiple_choice review cards require a choices array")
    raw_items: list[object] = list(cast("Iterable[object]", payload))
    try:
        choices = tuple(
            item if isinstance(item, QuizChoice) else QuizChoice.model_validate(item)
            for item in raw_items
        )
        return mode, validate_quiz_choices(choices, expected_answer=expected_answer)
    except (TypeError, ValueError, ValidationError) as exc:
        raise StorageError("invalid review card choices") from exc


def _read_lesson_summary(state_dir: Path, run_id: str) -> str | None:
    lesson_dir = state_dir / "runs" / run_id / "lesson"
    for name in ("lesson.compact.md", "lesson.hint.md", "lesson.full.md"):
        path = lesson_dir / name
        if not path.exists():
            continue
        try:
            validate_state_path_no_symlinks(path, allow_missing_leaf=False)
            text = _read_lesson_text(path, state_dir=state_dir).strip()
        except InputError as exc:
            logger.warning("failed to read lesson summary %s: %s", path, exc)
            continue
        if text:
            return text[:_LESSON_SUMMARY_CHARS]
    return None


def _load_graph(state_dir: Path) -> object | None:
    graph_path = state_dir / "graphify" / "graph.json"
    if not graph_path.exists():
        return None
    try:
        validate_state_path_no_symlinks(graph_path, allow_missing_leaf=False)
        if not graph_path.is_file():
            return None
        from ahadiff.graphify import parse_graph_json

        return parse_graph_json(graph_path)
    except Exception as exc:
        logger.warning("failed to load graph: %s", exc)
        return None


def _count_concepts_jsonl(state_dir: Path) -> int:
    concepts_path = state_dir / "concepts.jsonl"
    if not concepts_path.exists():
        return 0
    page = load_concepts_page(
        concepts_path,
        limit=_MAX_LIMIT,
        max_bytes=_MAX_CONCEPTS_JSONL_BYTES,
    )
    count = len(page.entries)
    cursor = page.next_cursor
    while cursor is not None:
        page = load_concepts_page(
            concepts_path,
            limit=_MAX_LIMIT,
            cursor=int(cursor),
            max_bytes=_MAX_CONCEPTS_JSONL_BYTES,
        )
        count += len(page.entries)
        cursor = page.next_cursor
    return count


def _count_table_rows(connection: sqlite3.Connection, table_name: str) -> int:
    if table_name not in _ALLOWED_TABLES:
        raise ValueError("table not in allowlist")
    if not _table_exists(connection, table_name):
        return 0
    row = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    return int(row[0]) if row is not None else 0


def _count_distinct_runs(connection: sqlite3.Connection) -> int:
    if not _table_exists(connection, "result_events"):
        return 0
    row = connection.execute("SELECT COUNT(DISTINCT run_id) FROM result_events").fetchone()
    return int(row[0]) if row is not None else 0


def _count_due_cards(connection: sqlite3.Connection) -> int:
    if not _table_exists(connection, "cards"):
        return 0
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM cards
        WHERE card_state = 'active' AND due_date <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _avg_overall_score(connection: sqlite3.Connection) -> float | None:
    if not _table_exists(connection, "result_events"):
        return None
    row = connection.execute(
        """
        SELECT AVG(overall)
        FROM result_events
        WHERE status IN ('baseline', 'keep', 'keep_final')
        """
    ).fetchone()
    if row is None or row[0] is None:
        return None
    value = float(row[0])
    return value if math.isfinite(value) else None


def _max_timestamp(connection: sqlite3.Connection) -> str | None:
    if not _table_exists(connection, "result_events"):
        return None
    row = connection.execute("SELECT MAX(timestamp) FROM result_events").fetchone()
    return None if row is None or row[0] is None else str(row[0])


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _sqlite_user_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError, OverflowError):
        return 0


def _table_has_columns(
    connection: sqlite3.Connection,
    table_name: str,
    column_names: tuple[str, ...],
) -> bool:
    rows = connection.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    present = {str(row[1]) for row in rows}
    return all(column_name in present for column_name in column_names)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _result_event_payload(event: dict[str, Any]) -> dict[str, Any]:
    note = _parse_note(event.get("note_json"))
    return {
        "event_id": event.get("event_id"),
        "run_id": event.get("run_id"),
        "timestamp": event.get("timestamp"),
        "source_ref": event.get("source_ref"),
        "base_ref": event.get("base_ref"),
        "overall": event.get("overall"),
        "verdict": event.get("verdict"),
        "status": event.get("status"),
        "weakest_dim": event.get("weakest_dim"),
        "prompt_version": event.get("prompt_version"),
        "eval_bundle_version": event.get("eval_bundle_version"),
        "rubric_version": event.get("rubric_version"),
        "note": note,
    }


def _due_card_payload(card: DueReviewCard) -> dict[str, Any]:
    payload = asdict(card)
    choices = payload.get("choices")
    if choices is not None:
        payload["choices"] = [
            choice.model_dump(mode="json") if hasattr(choice, "model_dump") else choice
            for choice in choices
        ]
    return payload


def _parse_note(raw_note: object) -> object | None:
    if raw_note is None:
        return None
    try:
        return safe_json_loads(str(raw_note))
    except (json.JSONDecodeError, ValueError):
        return str(raw_note)


def _limit_from_args(arguments: dict[str, Any]) -> int:
    raw = arguments.get("limit", _DEFAULT_LIMIT)
    if isinstance(raw, bool):
        return _DEFAULT_LIMIT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT
    return min(max(value, 1), _MAX_LIMIT)


def _required_str(arguments: dict[str, Any], key: str) -> str:
    raw = arguments.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise InputError(f"{key} is required")
    return raw.strip()


def _optional_tables(raw: object) -> tuple[str, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise InputError("tables must be a list")
    raw_values = cast("list[object]", raw)
    values = tuple(str(item).strip() for item in raw_values if str(item).strip())
    return values or None


def _optional_bool(raw: object, *, default: bool) -> bool:
    return raw if isinstance(raw, bool) else default


def _text_json(payload: dict[str, Any]) -> types.TextContent:
    return types.TextContent(
        type="text",
        text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


def _object_schema(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _integer_schema(
    description: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> dict[str, Any]:
    return {
        "type": "integer",
        "description": description,
        "default": default,
        "minimum": minimum,
        "maximum": maximum,
    }


__all__ = ["create_mcp_server", "run_mcp_server", "run_mcp_stdio_server"]
