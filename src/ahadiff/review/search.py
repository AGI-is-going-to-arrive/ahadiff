from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ahadiff.core.errors import InputError, StorageError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_FTS_MAX_RESULTS = 200
_FTS_MAX_QUERY_LENGTH = 500
_ALLOWED_FTS_TABLES = frozenset({"concepts", "result_events", "cards"})
_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class SearchResult:
    source_table: str  # "concepts" | "result_events" | "cards"
    primary_key: str
    snippet: str
    rank: float


def search_all(
    db_path: Path,
    query: str,
    *,
    limit: int = 50,
    tables: Sequence[str] | None = None,
) -> tuple[SearchResult, ...]:
    """Search across FTS5 indexes. Returns results ranked by relevance."""
    if not query or not query.strip():
        return ()
    if len(query) > _FTS_MAX_QUERY_LENGTH:
        raise InputError(f"search query exceeds {_FTS_MAX_QUERY_LENGTH} characters")
    limit = min(limit, _FTS_MAX_RESULTS)
    if limit < 1:
        return ()
    if not db_path.exists():
        return ()

    from ahadiff.review.database import connect_review_db

    sanitized = _sanitize_fts_query(query)
    if not sanitized:
        return ()

    results: list[SearchResult] = []
    target_tables = ("concepts", "result_events", "cards") if tables is None else tables

    with connect_review_db(db_path) as connection:
        for table_name in target_tables:
            if table_name not in _ALLOWED_FTS_TABLES:
                continue
            fts_table = f"fts_{table_name}"
            if not _fts_table_exists(connection, fts_table):
                continue
            try:
                rows = _search_fts_table(connection, table_name, fts_table, sanitized, limit)
            except sqlite3.OperationalError as exc:
                raise StorageError(f"FTS search failed for {fts_table}: {exc}") from exc
            results.extend(rows)

    results.sort(key=lambda r: r.rank)
    return tuple(results[:limit])


def _sanitize_fts_query(query: str) -> str:
    """Build a safe FTS5 expression from literal user tokens."""
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


def _search_fts_table(
    connection: sqlite3.Connection,
    source_table: str,
    fts_table: str,
    query: str,
    limit: int,
) -> list[SearchResult]:
    """Search a single FTS5 table."""
    if source_table not in _ALLOWED_FTS_TABLES:
        raise StorageError(f"unknown FTS source table: {source_table}")
    pk_col = _pk_column(source_table)
    snippet_column = -1
    rows = connection.execute(
        f"""
        SELECT {pk_col}, snippet({fts_table}, {snippet_column}, '<b>', '</b>', '...', 32), rank
        FROM {fts_table}
        WHERE {fts_table} MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [
        SearchResult(
            source_table=source_table,
            primary_key=str(row[0]),
            snippet=str(row[1]),
            rank=float(row[2]),
        )
        for row in rows
    ]


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


def search_all_with_graph(
    db_path: Path,
    query: str,
    *,
    limit: int = 50,
    tables: Sequence[str] | None = None,
    graph: object | None = None,
) -> tuple[SearchResult, ...]:
    fts_raw = search_all(db_path, query, limit=limit, tables=tables)
    merged: list[SearchResult] = [
        SearchResult(
            source_table=r.source_table,
            primary_key=r.primary_key,
            snippet=r.snippet,
            rank=_normalize_fts_rank(r.rank),
        )
        for r in fts_raw
    ]

    if graph is not None and (tables is None or "graph_nodes" in tables):
        from ahadiff.graphify.search import search_graph_nodes

        graph_results = search_graph_nodes(graph, query, limit=limit)  # type: ignore[arg-type]
        for gr in graph_results:
            merged.append(
                SearchResult(
                    source_table="graph_nodes",
                    primary_key=gr.node_id,
                    snippet=gr.label,
                    rank=gr.score,
                )
            )

    merged.sort(key=lambda r: r.rank, reverse=True)
    return tuple(merged[:limit])


__all__ = ["SearchResult", "search_all", "search_all_with_graph"]
