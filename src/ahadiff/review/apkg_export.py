from __future__ import annotations

import hashlib
import html
import importlib.resources
import json
import logging
import sqlite3
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any, TypedDict

from ahadiff.contracts import ErrorCode
from ahadiff.core.card_sources import CardSourceDetails, load_card_sources
from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.sqlite_util import safe_sqlite_connect

logger = logging.getLogger(__name__)

_DECK_ID = int(hashlib.sha256(b"ahadiff-review").hexdigest()[:8], 16)
_MODEL_ID = int(hashlib.sha256(b"ahadiff-review-basic-model").hexdigest()[:8], 16)
_DECK_NAME = "AhaDiff Review"
_GENANKI_MISSING = (
    "genanki is required for .apkg export and is installed with ahadiff by default; "
    "if it is missing, reinstall ahadiff."
)
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

    current_run: str | None = None
    run_sources: dict[str, CardSourceDetails] = {}
    for row in _load_active_cards(db_path):
        if row["run_id"] != current_run:
            current_run = row["run_id"]
            run_sources = load_card_sources(db_path.parent, current_run)
        source = run_sources.get(row["card_id"])
        if source is None and (
            run_sources
            or row["card_id"].startswith("card_exercise_")
            or row["source_ref"].startswith("document:")
        ):
            raise InputError("APKG review card is missing its declared source artifacts")
        if source is not None and row["source_ref"] != source.source_ref:
            raise InputError("APKG review card source identity does not match its artifacts")
        deck.add_note(
            genanki.Note(
                model=model,
                fields=[
                    _source_front(source) if source else _front(row),
                    _source_back(row, source) if source else _back(row),
                ],
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


def _source_front(source: CardSourceDetails) -> str:
    # Choice text is part of the question; correctness and source metadata are not.
    pieces = [f'<div style="white-space: pre-wrap">{html.escape(source.question)}</div>']
    if source.answer_mode == "multiple_choice" and source.choices is not None:
        pieces.append('<ul style="list-style: none; padding-inline-start: 0">')
        pieces.extend(
            f"<li><strong>{html.escape(choice.label)}.</strong> {html.escape(choice.text)}</li>"
            for choice in source.choices
        )
        pieces.append("</ul>")
    return "\n".join(pieces)


def _source_reference_answer(source: CardSourceDetails) -> str:
    if source.answer_mode == "multiple_choice" and source.choices is not None:
        correct = next(choice for choice in source.choices if choice.is_correct)
        return f"{correct.label}. {correct.text}"
    return source.answer


def _source_back(row: _CardRow, source: CardSourceDetails) -> str:
    zh = source.content_lang == "zh-CN"
    labels = (
        {
            "answer": "参考答案",
            "source": "来源",
            "source_kind": "来源类型",
            "path": "路径",
            "evidence": "来源证据",
            "format": "格式",
            "side": "侧",
            "locator": "定位信息",
            "hash": "内容 hash",
            "auxiliary": "人工辅助说明",
        }
        if zh
        else {
            "answer": "Reference answer",
            "source": "Source",
            "source_kind": "Source kind",
            "path": "Path",
            "evidence": "Source evidence",
            "format": "Format",
            "side": "Side",
            "locator": "Locator",
            "hash": "Content hash",
            "auxiliary": "Auxiliary reviewer context",
        }
    )
    pieces = [
        f"<h3>{labels['answer']}</h3>",
        f'<div style="white-space: pre-wrap">{html.escape(_source_reference_answer(source))}</div>',
    ]
    if source.exercise_kind is not None:
        pieces.append(
            "<p>"
            + (
                "此练习采用语义自评；AhaDiff 未执行你的代码。请对照参考答案，"
                "判断你是否独立完成、借助提示完成或尚未完成。"
                if zh
                else "This exercise uses semantic self-assessment; AhaDiff did not execute "
                "your code. Compare the reference answer and assess whether you completed "
                "the variant independently, with help, or not yet."
            )
            + "</p>"
        )
    pieces.extend(
        (
            "<hr>",
            f"<div><strong>{labels['source_kind']}:</strong> "
            f"{html.escape(source.source_kind)}</div>",
            f"<div><strong>{labels['source']}:</strong> {html.escape(source.source_ref)}</div>",
        )
    )
    if source.source_kind == "document":
        pieces.append(
            "<p>"
            + (
                "这是独立 Markdown 文档来源，不表示文件改动或代码执行结果。"
                if zh
                else "This is an independent Markdown document source; it does not represent "
                "a file change or an execution result."
            )
            + "</p>"
        )
    if source.source_anchors:
        pieces.append(f"<h3>{labels['evidence']}</h3>")
    else:
        pieces.append(
            f"<div><strong>{labels['path']}:</strong> {html.escape(row['display_path'])}</div>"
        )
    side_labels = {"old": "修改前", "new": "修改后", "document": "文档"} if zh else {}
    for anchor in source.source_anchors:
        locator = json.dumps(
            anchor.locator.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            sort_keys=True,
        )
        side = side_labels.get(anchor.side, anchor.side)
        pieces.extend(
            (
                "<section>",
                f"<div><strong>{labels['path']}:</strong> "
                f"{html.escape(anchor.file)}:{anchor.start}–{anchor.end}</div>",
                f"<div><strong>{labels['format']}:</strong> {html.escape(anchor.format)}"
                f" · <strong>{labels['side']}:</strong> {html.escape(side)}</div>",
                f"<div><strong>{labels['locator']}:</strong> "
                f"<code>{html.escape(locator)}</code></div>",
                f'<pre style="white-space: pre-wrap">{html.escape(anchor.quote)}</pre>',
                f"<div><strong>{labels['hash']}:</strong> <code>{anchor.content_hash}</code></div>",
                "</section>",
            )
        )
    if source.review_context_used:
        pieces.append(
            f"<p><strong>{labels['auxiliary']}:</strong> auxiliary_untrusted · "
            + (
                "已使用；仅作辅助说明，不构成来源证据。"
                if zh
                else "used; auxiliary context, not source evidence."
            )
            + f" {labels['hash']}: <code>{html.escape(source.review_context_hash or '')}</code></p>"
        )
    return "\n".join(pieces)


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
