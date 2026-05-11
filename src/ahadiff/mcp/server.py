from __future__ import annotations

import asyncio
import json
import math
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from ahadiff.core.errors import AhaDiffError, InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import validate_run_id, validate_state_path_no_symlinks
from ahadiff.review.database import (
    connect_review_db,
    load_result_events_page,
)
from ahadiff.review.database import (
    list_due_cards as db_list_due_cards,
)
from ahadiff.review.search import search_all_with_graph
from ahadiff.wiki.concepts import load_concepts_page

if TYPE_CHECKING:
    from pathlib import Path

    from ahadiff.review.schemas import DueReviewCard

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 200
_MAX_CONCEPTS_JSONL_BYTES = 16 * 1024 * 1024
_LESSON_SUMMARY_CHARS = 1200
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
        except (AhaDiffError, sqlite3.DatabaseError, OSError, ValueError, TypeError) as exc:
            return [_text_json({"error": str(exc), "tool": name})]

    return server


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
    }


def _list_runs(db_path: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = _limit_from_args(arguments)
    events = load_result_events_page(db_path, limit=limit)
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
    cards = db_list_due_cards(db_path, limit=limit)
    return {"cards": [_due_card_payload(card) for card in cards]}


def _search(state_dir: Path, db_path: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = _required_str(arguments, "query")
    limit = _limit_from_args(arguments)
    tables = _optional_tables(arguments.get("tables"))
    include_graph = _optional_bool(arguments.get("include_graph"), default=True)
    graph = _load_graph(state_dir) if include_graph else None
    results = search_all_with_graph(db_path, query, limit=limit, tables=tables, graph=graph)
    return {
        "results": [
            {
                "source_table": result.source_table,
                "primary_key": result.primary_key,
                "snippet": result.snippet,
                "rank": result.rank,
                "href": result.href,
            }
            for result in results
        ]
    }


def _get_concepts(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = _limit_from_args(arguments)
    raw_cursor = arguments.get("cursor")
    cursor = (
        int(raw_cursor)
        if isinstance(raw_cursor, int)
        else int(str(raw_cursor)) if raw_cursor else 0
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
    with connect_review_db(db_path) as connection:
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
    return stats


def _load_latest_result_event_for_run(db_path: Path, run_id: str) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    with connect_review_db(db_path) as connection:
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
    return None if row is None else dict(row)


def _read_lesson_summary(state_dir: Path, run_id: str) -> str | None:
    lesson_dir = state_dir / "runs" / run_id / "lesson"
    for name in ("lesson.compact.md", "lesson.hint.md", "lesson.full.md"):
        path = lesson_dir / name
        if not path.exists():
            continue
        validate_state_path_no_symlinks(path, allow_missing_leaf=False)
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return text[:_LESSON_SUMMARY_CHARS]
    return None


def _load_graph(state_dir: Path) -> object | None:
    graph_path = state_dir / "graphify" / "graph.json"
    try:
        validate_state_path_no_symlinks(graph_path, allow_missing_leaf=False)
        if not graph_path.is_file():
            return None
        from ahadiff.graphify import parse_graph_json

        return parse_graph_json(graph_path)
    except Exception:
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
