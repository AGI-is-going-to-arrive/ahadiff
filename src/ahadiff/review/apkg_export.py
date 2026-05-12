from __future__ import annotations

import hashlib
import html
import importlib.resources
import logging
import sqlite3
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any, TypedDict

from ahadiff.contracts import ErrorCode
from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.sqlite_util import safe_sqlite_connect

logger = logging.getLogger(__name__)

_DECK_ID = int(hashlib.sha256(b"ahadiff-review").hexdigest()[:8], 16)
_MODEL_ID = int(hashlib.sha256(b"ahadiff-review-basic-model").hexdigest()[:8], 16)
_DECK_NAME = "AhaDiff Review"
_GENANKI_MISSING = "genanki not installed. Install with: pip install ahadiff[anki]"
_AHADIFF_TAG = "ahadiff"
_MAX_APKG_CARDS = 10_000
_REQUIRED_CARD_COLUMNS = frozenset(
    {
        "id",
        "concept",
        "question",
        "answer",
        "display_path",
        "source_ref",
        "run_id",
        "card_state",
    }
)


class _CardRow(TypedDict):
    card_id: str
    concept: str
    question: str | None
    answer: str | None
    display_path: str
    source_ref: str
    run_id: str


def export_apkg(db_path: Path, output: Path | None = None) -> bytes:
    genanki = _load_genanki()
    deck = genanki.Deck(_DECK_ID, _DECK_NAME)
    model = genanki.Model(
        _MODEL_ID,
        "AhaDiff Basic",
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
            }
        ],
        css=_load_card_css(),
    )

    for row in _load_active_cards(db_path):
        deck.add_note(
            genanki.Note(
                model=model,
                fields=[_front(row), _back(row)],
                guid=genanki.guid_for(row["card_id"]),
                tags=[_AHADIFF_TAG],
            )
        )

    package = genanki.Package(deck)
    apkg_bytes = _package_bytes(package)
    if output is not None:
        output.write_bytes(apkg_bytes)
    return apkg_bytes


def _load_genanki() -> Any:
    try:
        return import_module("genanki")
    except ImportError as exc:
        raise ImportError(_GENANKI_MISSING) from exc


def _load_card_css() -> str:
    try:
        return (
            importlib.resources.files("ahadiff.review.templates")
            .joinpath("anki_card.css")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        logger.warning("Failed to load anki_card.css, using empty CSS")
        return ""


def _load_active_cards(db_path: Path) -> tuple[_CardRow, ...]:
    if not db_path.exists():
        return ()
    try:
        with _connect_review_db_readonly(db_path) as connection:
            if not _cards_table_exists(connection):
                return ()
            _validate_cards_schema(connection)
            active_count = _active_card_count(connection)
            if active_count > _MAX_APKG_CARDS:
                raise InputError(
                    f"APKG export supports at most {_MAX_APKG_CARDS} active cards; "
                    f"found {active_count}",
                    code=ErrorCode.RUN_ARTIFACT_TOO_LARGE,
                    details={"limit": _MAX_APKG_CARDS, "count": active_count},
                )
            # The current schema uses id/card_state instead of legacy card_id/active columns.
            rows = connection.execute(
                """
                SELECT
                    id AS card_id,
                    concept,
                    question,
                    answer,
                    display_path,
                    source_ref,
                    run_id
                FROM cards
                WHERE card_state = 'active'
                ORDER BY run_id ASC, id ASC
                """
            ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise StorageError(
            f"review.sqlite cannot be exported to APKG: {exc}",
            code=ErrorCode.STORAGE_REVIEW_DB,
        ) from exc
    except OSError as exc:
        raise StorageError(
            f"review.sqlite cannot be exported to APKG: {exc}",
            code=ErrorCode.STORAGE_REVIEW_DB,
        ) from exc
    cards = tuple(
        _CardRow(
            card_id=_required_text(row["card_id"]),
            concept=_required_text(row["concept"]),
            question=_optional_text(row["question"]),
            answer=_optional_text(row["answer"]),
            display_path=_required_text(row["display_path"]),
            source_ref=_required_text(row["source_ref"]),
            run_id=_required_text(row["run_id"]),
        )
        for row in rows
    )
    for row in cards:
        _front(row)
    return cards


def _connect_review_db_readonly(db_path: Path) -> sqlite3.Connection:
    connection = safe_sqlite_connect(
        db_path,
        read_only=True,
        row_factory=sqlite3.Row,
        busy_timeout_ms=5000,
        defensive=True,
    )
    try:
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute("PRAGMA query_only").fetchone()
        if row is None or int(row[0]) != 1:
            actual = "unknown" if row is None else str(row[0])
            raise StorageError(
                f"review.sqlite APKG export failed query_only=ON verification: {actual}",
                code=ErrorCode.STORAGE_REVIEW_DB,
            )
    except Exception:
        connection.close()
        raise
    return connection


def _cards_table_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("cards",),
    ).fetchone()
    return row is not None


def _validate_cards_schema(connection: sqlite3.Connection) -> None:
    columns = {
        str(row["name"]) for row in connection.execute("PRAGMA table_info(cards)").fetchall()
    }
    missing = sorted(_REQUIRED_CARD_COLUMNS - columns)
    if missing:
        raise StorageError(
            "review.sqlite cards table is missing columns required for APKG export",
            code=ErrorCode.STORAGE_REVIEW_DB,
            details={"missing_columns": missing},
        )


def _active_card_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) FROM cards WHERE card_state = 'active'").fetchone()
    return 0 if row is None else int(row[0])


def _front(row: _CardRow) -> str:
    text = (row["question"] or row["concept"]).strip()
    if not text:
        raise StorageError(
            "review card has an empty APKG front",
            code=ErrorCode.STORAGE_REVIEW_DB,
            details={"card_id": row["card_id"]},
        )
    return html.escape(text)


def _back(row: _CardRow) -> str:
    return "\n".join(
        (
            f"<div>{html.escape(row['answer'] or '')}</div>",
            "<hr>",
            f"<div><strong>Source:</strong> {html.escape(row['source_ref'])}</div>",
            f"<div><strong>Path:</strong> {html.escape(row['display_path'])}</div>",
        )
    )


def _required_text(value: object) -> str:
    return "" if value is None else str(value)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _package_bytes(package: Any) -> bytes:
    with tempfile.TemporaryDirectory(prefix="ahadiff-apkg-") as temp_dir:
        package_path = Path(temp_dir) / "ahadiff_review.apkg"
        package.write_to_file(package_path)
        return package_path.read_bytes()


__all__ = ["export_apkg"]
