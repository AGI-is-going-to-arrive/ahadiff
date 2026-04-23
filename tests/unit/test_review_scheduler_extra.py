from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Any

import pytest
from fsrs import Rating

import ahadiff.review.scheduler as scheduler_module
from ahadiff.core.errors import InputError
from ahadiff.review import (
    default_scheduler_parameters,
    default_weights_json,
    normalize_fsrs_state,
    rating_for_answer,
    review_fsrs_card,
    scheduler_version,
    snapshot_card_state,
)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("good", Rating.Good),
        ("hard", Rating.Hard),
        ("wrong", Rating.Again),
    ],
)
def test_rating_for_answer_maps_supported_answers(answer: str, expected: Rating) -> None:
    review_answer: Any = answer
    assert rating_for_answer(review_answer) is expected


def test_rating_for_answer_rejects_unknown_answer() -> None:
    review_answer: Any = "skip"
    with pytest.raises(InputError, match="unsupported review answer"):
        rating_for_answer(review_answer)


@pytest.mark.parametrize(
    ("raw_state", "match"),
    [
        ("", "must not be an empty string"),
        ("{", "must be valid JSON"),
        ("[]", "must be a JSON object"),
    ],
)
def test_normalize_fsrs_state_rejects_invalid_boundaries(raw_state: str, match: str) -> None:
    with pytest.raises(InputError, match=match):
        normalize_fsrs_state(raw_state)


def test_normalize_fsrs_state_preserves_cards_and_rebuilds_incomplete_payloads() -> None:
    now = datetime(2026, 4, 24, tzinfo=UTC)
    normalized = normalize_fsrs_state(None, now=now)

    assert json.loads(normalize_fsrs_state(normalized, now=now)) == json.loads(normalized)

    rebuilt = json.loads(normalize_fsrs_state('{"unexpected": 1}', now=now))
    assert rebuilt["due"] == "2026-04-24T00:00:00+00:00"
    assert rebuilt["state"] == 1
    assert rebuilt["stability"] is None
    assert rebuilt["difficulty"] is None


def test_default_scheduler_exports_round_trip() -> None:
    parameters = default_scheduler_parameters()

    assert parameters
    assert all(isinstance(item, float) for item in parameters)
    assert json.loads(default_weights_json()) == list(parameters)


def test_snapshot_card_state_exports_normalized_card_state() -> None:
    now = datetime(2026, 4, 24, tzinfo=UTC)
    normalized = normalize_fsrs_state(None, now=now)

    snapshot, due_date, stability, difficulty, scaffolding = snapshot_card_state(normalized)

    assert json.loads(snapshot) == json.loads(normalized)
    assert due_date == "2026-04-24T00:00:00Z"
    assert stability == 0.0
    assert difficulty == 0.0
    assert scaffolding == "full"


def test_scheduler_version_matches_installed_fsrs_package() -> None:
    assert scheduler_version() == f"fsrs-{version('fsrs')}"


class _FakeState:
    name = "Review"


class _FakeCardWithMissingAttribute:
    def __init__(self, missing: str) -> None:
        self.state = _FakeState()
        self.due = datetime(2026, 4, 25, tzinfo=UTC)
        if missing != "stability":
            self.stability = 12.5
        if missing != "difficulty":
            self.difficulty = 4.0

    def to_json(self) -> str:
        return '{"state":2,"due":"2026-04-25T00:00:00+00:00"}'


@pytest.mark.parametrize("missing", ["stability", "difficulty"])
def test_snapshot_card_state_rejects_missing_fsrs_core_attributes(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    fake_card = _FakeCardWithMissingAttribute(missing)

    def fake_card_from_json(_payload: str) -> _FakeCardWithMissingAttribute:
        return fake_card

    monkeypatch.setattr(scheduler_module, "_card_from_json", fake_card_from_json)

    with pytest.raises(InputError, match=f"missing required attribute: {missing}"):
        snapshot_card_state('{"state": 1, "due": "2026-04-24T00:00:00+00:00"}')


class _FakeScheduler:
    def __init__(self, card: _FakeCardWithMissingAttribute) -> None:
        self._card = card

    def review_card(
        self, card: object, rating: Rating, review_datetime: datetime
    ) -> tuple[_FakeCardWithMissingAttribute, object]:
        del card, rating, review_datetime
        return self._card, object()


@pytest.mark.parametrize("missing", ["stability", "difficulty"])
def test_review_fsrs_card_rejects_missing_fsrs_core_attributes(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    reviewed_at = datetime(2026, 4, 24, tzinfo=UTC)
    initial_state = normalize_fsrs_state(None, now=reviewed_at)
    fake_card = _FakeCardWithMissingAttribute(missing)

    def fake_make_scheduler(**_kwargs: Any) -> _FakeScheduler:
        return _FakeScheduler(fake_card)

    monkeypatch.setattr(scheduler_module, "_make_scheduler", fake_make_scheduler)

    with pytest.raises(InputError, match=f"missing required attribute: {missing}"):
        review_answer: Any = "good"
        review_fsrs_card(
            fsrs_state=initial_state,
            answer=review_answer,
            reviewed_at=reviewed_at,
        )
