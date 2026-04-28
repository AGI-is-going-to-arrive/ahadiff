from __future__ import annotations

from typing import TYPE_CHECKING

from ahadiff.lesson.helpfulness import aggregate_helpfulness
from ahadiff.review.database import initialize_review_db, insert_learning_signal, make_uuid7

if TYPE_CHECKING:
    from pathlib import Path


def _insert_helpfulness(
    db_path: Path,
    *,
    target_kind: str = "file",
    target_id: str,
    payload: dict[str, object] | None = None,
) -> None:
    initialize_review_db(db_path)
    insert_learning_signal(
        db_path,
        event_id=make_uuid7(),
        idempotency_key=make_uuid7(),
        signal_type="helpfulness",
        payload={
            "target_kind": target_kind,
            "target_id": target_id,
            "payload": payload or {},
        },
    )


def test_aggregate_empty_db(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    assert aggregate_helpfulness(db_path) == []


def test_aggregate_nonexistent_db(tmp_path: Path) -> None:
    db_path = tmp_path / "does_not_exist.sqlite"
    assert aggregate_helpfulness(db_path) == []


def test_aggregate_file_signals(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    _insert_helpfulness(db_path, target_id="src/main.py", payload={"helpful": True})
    _insert_helpfulness(db_path, target_id="src/main.py", payload={"helpful": False})
    _insert_helpfulness(db_path, target_id="src/main.py", payload={"helpful": True})

    result = aggregate_helpfulness(db_path)
    assert len(result) == 1
    agg = result[0]
    assert agg.target_kind == "file"
    assert agg.target_id == "src/main.py"
    assert agg.signal_count == 3
    assert agg.positive_count == 2
    assert agg.negative_count == 1
    assert abs(agg.helpfulness_score - (2 / 3)) < 0.001


def test_aggregate_section_signals(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    _insert_helpfulness(
        db_path,
        target_kind="section",
        target_id="run1:intro",
        payload={"helpful": True},
    )
    _insert_helpfulness(
        db_path,
        target_kind="section",
        target_id="run1:intro",
        payload={"helpful": True},
    )

    result = aggregate_helpfulness(db_path, target_kind="section")
    assert len(result) == 1
    assert result[0].target_kind == "section"
    assert result[0].helpfulness_score == 1.0


def test_aggregate_filter_by_target_kind(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    _insert_helpfulness(db_path, target_id="src/a.py", payload={"helpful": True})
    _insert_helpfulness(
        db_path,
        target_kind="section",
        target_id="run1:methods",
        payload={"helpful": True},
    )

    file_only = aggregate_helpfulness(db_path, target_kind="file")
    assert len(file_only) == 1
    assert file_only[0].target_kind == "file"

    section_only = aggregate_helpfulness(db_path, target_kind="section")
    assert len(section_only) == 1
    assert section_only[0].target_kind == "section"

    all_kinds = aggregate_helpfulness(db_path)
    assert len(all_kinds) == 2


def test_aggregate_thumbs_payload_is_ignored(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    _insert_helpfulness(db_path, target_id="f.py", payload={"thumbs": "up"})
    _insert_helpfulness(db_path, target_id="f.py", payload={"thumbs": "down"})
    _insert_helpfulness(db_path, target_id="f.py", payload={"thumbs": "up"})

    result = aggregate_helpfulness(db_path)
    assert result == []


def test_aggregate_numeric_rating_is_ignored(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    _insert_helpfulness(db_path, target_id="f.py", payload={"rating": 5})
    _insert_helpfulness(db_path, target_id="f.py", payload={"rating": -1})
    _insert_helpfulness(db_path, target_id="f.py", payload={"rating": 0})

    result = aggregate_helpfulness(db_path)
    assert result == []


def test_aggregate_empty_payload_excluded_from_score(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    _insert_helpfulness(db_path, target_id="f.py", payload={})

    result = aggregate_helpfulness(db_path)
    assert len(result) == 0


def test_aggregate_mixed_determined_and_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "review.sqlite"
    _insert_helpfulness(db_path, target_id="f.py", payload={"helpful": True})
    _insert_helpfulness(db_path, target_id="f.py", payload={})
    _insert_helpfulness(db_path, target_id="f.py", payload={"helpful": True})

    result = aggregate_helpfulness(db_path)
    assert len(result) == 1
    assert result[0].signal_count == 2
    assert result[0].positive_count == 2
    assert result[0].helpfulness_score == 1.0
