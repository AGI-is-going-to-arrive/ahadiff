from __future__ import annotations

import json
import sqlite3
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from ahadiff.contracts import CardState, ReviewCard
from ahadiff.core.errors import InputError, StorageError
from ahadiff.review.database import import_cards_from_jsonl
from ahadiff.serve import ServeState, create_app

_AUTH = {"X-AhaDiff-Token": "test-token"}


class _FakeModel:
    def __init__(
        self,
        model_id: int,
        name: str,
        *,
        fields: list[dict[str, str]],
        templates: list[dict[str, str]],
        css: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.name = name
        self.fields = fields
        self.templates = templates
        self.css = css


class _FakeNote:
    def __init__(self, *, model: _FakeModel, fields: list[str], guid: str) -> None:
        self.model = model
        self.fields = fields
        self.guid = guid


class _FakeDeck:
    def __init__(self, deck_id: int, name: str) -> None:
        self.deck_id = deck_id
        self.name = name
        self.notes: list[_FakeNote] = []

    def add_note(self, note: _FakeNote) -> None:
        self.notes.append(note)


class _FakePackage:
    def __init__(self, deck: _FakeDeck) -> None:
        self.deck = deck

    def write_to_file(self, path: str | Path) -> None:
        payload = {
            "deck_id": self.deck.deck_id,
            "deck_name": self.deck.name,
            "notes": [
                {"fields": note.fields, "guid": note.guid, "model_id": note.model.model_id}
                for note in self.deck.notes
            ],
        }
        Path(path).write_bytes(json.dumps(payload, sort_keys=True).encode("utf-8"))


def _install_fake_genanki(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("genanki")

    def guid_for(value: object) -> str:
        return f"guid:{value}"

    module.__dict__.update(
        {
            "Deck": _FakeDeck,
            "Model": _FakeModel,
            "Note": _FakeNote,
            "Package": _FakePackage,
            "guid_for": guid_for,
        }
    )
    monkeypatch.setitem(sys.modules, "genanki", module)


def _fail_import(name: str) -> Any:
    if name == "genanki":
        raise ImportError("missing genanki")
    raise AssertionError(f"unexpected import: {name}")


def _review_card(
    card_id: str,
    *,
    card_state: CardState = "active",
    question: str | None = "What changed?",
    answer: str | None = "It retries transient failures before giving up.",
) -> ReviewCard:
    return ReviewCard(
        card_id=card_id,
        concept=f"concept-{card_id}",
        run_id="run-1",
        source_ref="abc1234",
        fsrs_state="{}",
        card_state=card_state,
        file_id="file-app",
        display_path="src/app.py",
        hunk_id=f"hunk-{card_id}",
        hunk_hash=f"deadbeef{card_id}",
        symbol="retry_once",
        question=question,
        answer=answer,
    )


def _write_cards_jsonl(path: Path, cards: tuple[ReviewCard, ...]) -> None:
    path.write_text(
        "".join(card.model_dump_json() + "\n" for card in cards),
        encoding="utf-8",
    )


def test_export_apkg_builds_deterministic_notes_and_writes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.review.apkg_export import export_apkg

    _install_fake_genanki(monkeypatch)
    db_path = tmp_path / "review.sqlite"
    cards_path = tmp_path / "cards.jsonl"
    _write_cards_jsonl(
        cards_path,
        (
            _review_card("card-1", question=None, answer="<keep escaped>"),
            _review_card("card-2", card_state="suspended"),
        ),
    )
    assert import_cards_from_jsonl(db_path, cards_path) == 2

    output_path = tmp_path / "review.apkg"
    apkg_bytes = export_apkg(db_path, output_path)

    assert output_path.read_bytes() == apkg_bytes
    payload = json.loads(apkg_bytes.decode("utf-8"))
    assert payload["deck_id"] == 187760382
    assert payload["deck_name"] == "AhaDiff Review"
    assert payload["notes"] == [
        {
            "fields": [
                "concept-card-1",
                (
                    "<div>&lt;keep escaped&gt;</div>\n"
                    "<hr>\n"
                    "<div><strong>Source:</strong> abc1234</div>\n"
                    "<div><strong>Path:</strong> src/app.py</div>"
                ),
            ],
            "guid": "guid:card-1",
            "model_id": 249423608,
        }
    ]


def test_export_apkg_empty_cards_still_returns_package_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.review.apkg_export import export_apkg

    _install_fake_genanki(monkeypatch)
    db_path = tmp_path / "review.sqlite"
    cards_path = tmp_path / "cards.jsonl"
    _write_cards_jsonl(cards_path, (_review_card("card-1", card_state="archived"),))
    assert import_cards_from_jsonl(db_path, cards_path) == 1

    payload = json.loads(export_apkg(db_path).decode("utf-8"))

    assert payload["notes"] == []


def test_export_apkg_rejects_active_card_with_empty_front(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.review.apkg_export import export_apkg

    _install_fake_genanki(monkeypatch)
    db_path = tmp_path / "review.sqlite"
    cards_path = tmp_path / "cards.jsonl"
    _write_cards_jsonl(cards_path, (_review_card("card-1", question=""),))
    assert import_cards_from_jsonl(db_path, cards_path) == 1
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE cards SET concept = '' WHERE id = 'card-1'")

    with pytest.raises(StorageError, match="empty APKG front"):
        export_apkg(db_path)


def test_export_apkg_rejects_too_many_active_cards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ahadiff.review.apkg_export as apkg_export

    _install_fake_genanki(monkeypatch)
    db_path = tmp_path / "review.sqlite"
    cards_path = tmp_path / "cards.jsonl"
    _write_cards_jsonl(cards_path, (_review_card("card-1"), _review_card("card-2")))
    assert import_cards_from_jsonl(db_path, cards_path) == 2
    monkeypatch.setattr(apkg_export, "_MAX_APKG_CARDS", 1)

    with pytest.raises(InputError, match="at most 1 active cards"):
        apkg_export.export_apkg(db_path)


def test_export_apkg_reports_missing_optional_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ahadiff.review.apkg_export as apkg_export

    monkeypatch.setattr(apkg_export, "import_module", _fail_import)

    with pytest.raises(ImportError, match=r"pip install ahadiff\[anki\]"):
        apkg_export.export_apkg(tmp_path / "review.sqlite")


def test_export_apkg_route_returns_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_genanki(monkeypatch)
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    cards_path = tmp_path / "cards.jsonl"
    _write_cards_jsonl(cards_path, (_review_card("card-1"),))
    assert import_cards_from_jsonl(state_dir / "review.sqlite", cards_path) == 1

    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )
    response = client.get("/api/export/apkg", headers=_AUTH)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert "ahadiff_review.apkg" in response.headers["content-disposition"]
    assert json.loads(response.content.decode("utf-8"))["notes"][0]["guid"] == "guid:card-1"


def test_export_apkg_route_returns_501_when_dependency_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ahadiff.review.apkg_export as apkg_export

    monkeypatch.setattr(apkg_export, "import_module", _fail_import)
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )

    response = client.get("/api/export/apkg", headers=_AUTH)

    assert response.status_code == 501
    assert response.json() == {
        "error_code": "FEATURE_UNAVAILABLE",
        "error": "genanki not installed. Install with: pip install ahadiff[anki]",
        "status": 501,
    }


def test_export_apkg_route_returns_storage_error_for_old_cards_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_genanki(monkeypatch)
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    with sqlite3.connect(state_dir / "review.sqlite") as connection:
        connection.execute("CREATE TABLE cards (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO cards (id) VALUES ('legacy-card')")
    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )

    response = client.get("/api/export/apkg", headers=_AUTH)

    assert response.status_code == 500
    assert response.json()["error_code"] == "STORAGE_REVIEW_DB"
    assert response.json()["error"] == "review_database_unavailable"
