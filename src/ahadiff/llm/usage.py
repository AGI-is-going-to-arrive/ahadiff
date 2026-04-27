from __future__ import annotations

import pathlib as _pathlib
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.ids import make_event_id
from ahadiff.core.paths import is_wsl2_mnt, usage_db_path
from ahadiff.core.sqlite_util import safe_sqlite_connect

if TYPE_CHECKING:
    from pathlib import Path
else:
    Path = _pathlib.Path

_USAGE_BUSY_TIMEOUT_MS = 30_000
_USAGE_WRITE_ATTEMPTS = 5
_SCHEMA_INITIALIZED: set[str] = set()
_SCHEMA_INIT_LOCK = threading.Lock()
_SQLITE_MIN_VERSION = (3, 51, 3)
_SQLITE_ALLOWED_BACKPORTS = {(3, 50, 7), (3, 44, 6)}


@dataclass(frozen=True)
class UsageRecord:
    workspace_identity: str
    provider_class: str
    api_family: str
    api_family_version: str
    model_id: str
    prompt_name: str
    prompt_fingerprint: str
    prompt_version: str
    eval_bundle_version: str
    output_lang: str
    privacy_mode: str
    source_ref: str
    cache_key: str
    cache_hit: bool
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    pricing_version: str | None
    cost_confidence: str
    execution_origin: str
    request_id: str | None = None


def connect_usage_db(db_path: Path, *, create_parent: bool = False) -> sqlite3.Connection:
    _assert_sqlite_runtime_supported()
    try:
        if create_parent:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        elif not db_path.parent.exists():
            raise InputError(f"usage DB parent directory does not exist: {db_path.parent}")
        connection = safe_sqlite_connect(
            db_path,
            timeout=_USAGE_BUSY_TIMEOUT_MS / 1000,
            busy_timeout_ms=_USAGE_BUSY_TIMEOUT_MS,
            journal_mode=_resolve_sqlite_journal_mode(db_path),
            row_factory=sqlite3.Row,
            defensive=True,
        )
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"SQLite quick_check failed for {db_path}: {exc}") from exc
    except OSError as exc:
        raise StorageError(f"failed to open usage DB safely: {db_path} ({exc})") from exc
    try:
        try:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise StorageError(f"SQLite quick_check failed for {db_path}: {exc}") from exc
        if quick_check is None or quick_check[0] != "ok":
            value = "unknown" if quick_check is None else str(quick_check[0])
            raise StorageError(f"SQLite quick_check failed for {db_path}: {value}")
        return connection
    except Exception:
        connection.close()
        raise


def record_usage_event(record: UsageRecord, *, db_path: Path | None = None) -> None:
    target = usage_db_path() if db_path is None else db_path
    for attempt in range(_USAGE_WRITE_ATTEMPTS):
        try:
            with connect_usage_db(target, create_parent=True) as connection:
                _ensure_usage_schema(connection, target)
                connection.execute(
                    """
                    INSERT INTO llm_usage (
                        event_id,
                        timestamp_utc,
                        workspace_identity,
                        provider_class,
                        api_family,
                        api_family_version,
                        model_id,
                        prompt_name,
                        prompt_fingerprint,
                        prompt_version,
                        eval_bundle_version,
                        output_lang,
                        privacy_mode,
                        source_ref,
                        cache_key,
                        cache_hit,
                        input_tokens,
                        output_tokens,
                        cost_usd,
                        pricing_version,
                        cost_confidence,
                        execution_origin,
                        request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        make_event_id(),
                        _utc_now(),
                        record.workspace_identity,
                        record.provider_class,
                        record.api_family,
                        record.api_family_version,
                        record.model_id,
                        record.prompt_name,
                        record.prompt_fingerprint,
                        record.prompt_version,
                        record.eval_bundle_version,
                        record.output_lang,
                        record.privacy_mode,
                        record.source_ref,
                        record.cache_key,
                        int(record.cache_hit),
                        max(0, record.input_tokens),
                        max(0, record.output_tokens),
                        record.cost_usd,
                        record.pricing_version,
                        record.cost_confidence,
                        record.execution_origin,
                        record.request_id,
                    ),
                )
            return
        except (sqlite3.OperationalError, StorageError) as exc:
            root = exc.__cause__ if isinstance(exc, StorageError) and exc.__cause__ else exc
            if not _is_retryable_usage_write_error(exc, root) or attempt == (
                _USAGE_WRITE_ATTEMPTS - 1
            ):
                raise
            time.sleep(min(0.5, 0.05 * (2**attempt)))


def _is_retryable_usage_write_error(exc: BaseException, root: BaseException) -> bool:
    error_text = f"{root} {exc}".casefold()
    if "locked" in error_text:
        return True
    return isinstance(root, PermissionError) and "changed during open" in error_text


def _ensure_usage_schema(connection: sqlite3.Connection, db_path: Path) -> None:
    db_path_key = str(db_path)
    if db_path_key in _SCHEMA_INITIALIZED:
        return
    with _SCHEMA_INIT_LOCK:
        if db_path_key in _SCHEMA_INITIALIZED:
            return
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_usage (
                event_id TEXT PRIMARY KEY,
                timestamp_utc TEXT NOT NULL,
                workspace_identity TEXT NOT NULL,
                provider_class TEXT NOT NULL,
                api_family TEXT NOT NULL,
                api_family_version TEXT NOT NULL,
                model_id TEXT NOT NULL,
                prompt_name TEXT NOT NULL,
                prompt_fingerprint TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                eval_bundle_version TEXT NOT NULL,
                output_lang TEXT NOT NULL,
                privacy_mode TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                cache_hit INTEGER NOT NULL CHECK (cache_hit IN (0, 1)),
                input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
                output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
                cost_usd REAL,
                pricing_version TEXT,
                cost_confidence TEXT NOT NULL,
                execution_origin TEXT NOT NULL,
                request_id TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_llm_usage_cache_key
            ON llm_usage (cache_key, cache_hit)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_llm_usage_timestamp
            ON llm_usage (timestamp_utc)
            """
        )
        _SCHEMA_INITIALIZED.add(db_path_key)


def _resolve_sqlite_journal_mode(db_path: Path) -> str:
    return "DELETE" if is_wsl2_mnt(db_path) else "WAL"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _assert_sqlite_runtime_supported() -> None:
    version = sqlite3.sqlite_version_info
    if _sqlite_version_supported(version):
        return
    minimum = ".".join(str(part) for part in _SQLITE_MIN_VERSION)
    allowed = ", ".join(
        ".".join(str(part) for part in item) for item in sorted(_SQLITE_ALLOWED_BACKPORTS)
    )
    raise StorageError(
        f"SQLite runtime {sqlite3.sqlite_version} is below {minimum}; "
        f"upgrade SQLite or use an allowed patched runtime ({allowed})"
    )


def _sqlite_version_supported(version: tuple[int, int, int]) -> bool:
    return version >= _SQLITE_MIN_VERSION or version in _SQLITE_ALLOWED_BACKPORTS


__all__ = ["UsageRecord", "connect_usage_db", "record_usage_event"]
