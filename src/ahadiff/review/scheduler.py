from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, cast

from fsrs import Card, Rating, Scheduler

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.lesson.scaffolding import compute_scaffolding_level

if TYPE_CHECKING:
    from .schemas import ReviewAnswer

DEFAULT_DESIRED_RETENTION = 0.9
DEFAULT_MAXIMUM_INTERVAL = 365


@dataclass(frozen=True)
class ScheduledReview:
    fsrs_state: str
    rating: int
    due_date: str
    stability: float
    difficulty: float
    state_name: str
    scaffolding_level: str


def scheduler_version() -> str:
    try:
        return f"fsrs-{version('fsrs')}"
    except PackageNotFoundError:  # pragma: no cover - dependency is declared for runtime use
        return "fsrs-unknown"


def default_scheduler_parameters() -> tuple[float, ...]:
    payload = _make_scheduler(enable_fuzzing=False).to_dict()
    raw_parameters = cast("list[object]", payload["parameters"])
    return tuple(_coerce_float(item) for item in raw_parameters)


def default_weights_json() -> str:
    return json.dumps(list(default_scheduler_parameters()), separators=(",", ":"))


def normalize_fsrs_state(fsrs_state: str | None, *, now: datetime | None = None) -> str:
    if isinstance(fsrs_state, str) and fsrs_state == "":
        raise InputError("fsrs_state must not be an empty string; use None for a new card")
    if fsrs_state:
        try:
            payload_obj = safe_json_loads(fsrs_state)
        except (json.JSONDecodeError, ValueError) as exc:
            raise InputError("fsrs_state must be valid JSON") from exc
        if not isinstance(payload_obj, dict):
            raise InputError("fsrs_state must be a JSON object")
        payload = cast("dict[str, object]", payload_obj)
        if "state" in payload and "due" in payload:
            return _card_from_json(fsrs_state).to_json()

    card = Card(due=_coerce_utc(now or datetime.now(UTC)))
    return card.to_json()


def snapshot_card_state(fsrs_state: str) -> tuple[str, str, float, float, str]:
    card = _card_from_json(normalize_fsrs_state(fsrs_state))
    due_date = _datetime_to_utc_text(card.due)
    stability = _required_card_float(card, "stability")
    difficulty = _required_card_float(card, "difficulty")
    state_name = _state_name(card)
    scaffolding = compute_scaffolding_level(
        fsrs_state={
            "state_name": state_name,
            "stability_days": stability,
        },
        recent_successes=0,
    )
    return card.to_json(), due_date, stability, difficulty, scaffolding


def review_fsrs_card(
    *,
    fsrs_state: str,
    answer: ReviewAnswer,
    peeked_this_session: bool = False,
    reviewed_at: datetime | None = None,
    desired_retention: float = DEFAULT_DESIRED_RETENTION,
    weights: tuple[float, ...] | None = None,
    enable_fuzzing: bool = True,
    recent_successes: int = 0,
) -> ScheduledReview:
    rating = rating_for_answer(answer)
    if peeked_this_session and rating in {Rating.Good, Rating.Easy}:
        raise InputError("peeked cards cannot be reviewed as good or easy; use hard or wrong")
    scheduler = _make_scheduler(
        parameters=weights,
        desired_retention=desired_retention,
        enable_fuzzing=enable_fuzzing,
    )
    review_datetime = _coerce_utc(reviewed_at or datetime.now(UTC))
    card = _card_from_json(normalize_fsrs_state(fsrs_state, now=review_datetime))
    new_card, _review_log = scheduler.review_card(
        card,
        rating,
        review_datetime=review_datetime,
    )
    stability = _required_card_float(new_card, "stability")
    difficulty = _required_card_float(new_card, "difficulty")
    state_name = _state_name(new_card)
    successful_streak = recent_successes + 1 if rating.value in {2, 3, 4} else 0
    scaffolding = compute_scaffolding_level(
        fsrs_state={
            "state_name": state_name,
            "stability_days": stability,
        },
        recent_successes=successful_streak,
    )
    return ScheduledReview(
        fsrs_state=new_card.to_json(),
        rating=int(rating.value),
        due_date=_datetime_to_utc_text(new_card.due),
        stability=stability,
        difficulty=difficulty,
        state_name=state_name,
        scaffolding_level=scaffolding,
    )


def rating_for_answer(answer: ReviewAnswer) -> Rating:
    if answer == "easy":
        return Rating.Easy
    if answer == "good":
        return Rating.Good
    if answer == "hard":
        return Rating.Hard
    if answer == "wrong":
        return Rating.Again
    raise InputError(f"unsupported review answer: {answer!r}")


def _make_scheduler(
    *,
    parameters: tuple[float, ...] | None = None,
    desired_retention: float = DEFAULT_DESIRED_RETENTION,
    enable_fuzzing: bool = True,
) -> Scheduler:
    kwargs: dict[str, Any] = {
        "desired_retention": desired_retention,
        "maximum_interval": DEFAULT_MAXIMUM_INTERVAL,
        "enable_fuzzing": enable_fuzzing,
    }
    if parameters is not None:
        kwargs["parameters"] = parameters
    return Scheduler(**kwargs)


def _card_from_json(payload: str) -> Card:
    try:
        card = Card.from_json(payload)
    except Exception as exc:  # py-fsrs raises ValueError/KeyError depending on shape
        raise InputError("fsrs_state is not a valid py-fsrs Card JSON object") from exc
    _validate_optional_card_float(card, "stability")
    _validate_optional_card_float(card, "difficulty")
    return card


def _state_name(card: Card) -> str:
    raw_state = card.state
    return str(getattr(raw_state, "name", raw_state))


_MISSING_CARD_ATTRIBUTE = object()


def _validate_optional_card_float(card: object, field_name: str) -> None:
    value = getattr(card, field_name, _MISSING_CARD_ATTRIBUTE)
    if value is _MISSING_CARD_ATTRIBUTE:
        raise InputError(f"py-fsrs Card is missing required attribute: {field_name}")
    if value is not None:
        _coerce_float(value)


def _required_card_float(card: object, field_name: str) -> float:
    value = getattr(card, field_name, _MISSING_CARD_ATTRIBUTE)
    if value is _MISSING_CARD_ATTRIBUTE:
        raise InputError(f"py-fsrs Card is missing required attribute: {field_name}")
    return _optional_float(value)


def _optional_float(value: object) -> float:
    if value is None:
        return 0.0
    return _coerce_float(value)


def _coerce_float(value: object) -> float:
    if isinstance(value, int | float | str):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise InputError("FSRS numeric fields must be finite numbers")
        return parsed
    raise InputError("FSRS numeric fields must be numbers")


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _datetime_to_utc_text(value: datetime) -> str:
    return _coerce_utc(value).isoformat().replace("+00:00", "Z")


__all__ = [
    "DEFAULT_DESIRED_RETENTION",
    "DEFAULT_MAXIMUM_INTERVAL",
    "ScheduledReview",
    "default_scheduler_parameters",
    "default_weights_json",
    "normalize_fsrs_state",
    "rating_for_answer",
    "review_fsrs_card",
    "scheduler_version",
    "snapshot_card_state",
]
