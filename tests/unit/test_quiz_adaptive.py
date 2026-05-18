from __future__ import annotations

from typing import Any

import pytest

from ahadiff.quiz.adaptive import compute_adaptive_question_count, resolve_question_count


@pytest.mark.parametrize(
    ("changed_lines", "expected"),
    [
        (0, 3),
        (1, 3),
        (20, 3),
        (21, 4),
        (50, 4),
        (51, 5),
        (100, 5),
        (101, 6),
        (200, 6),
        (201, 7),
        (400, 7),
        (401, 8),
        (500, 8),
        (2**63 - 1, 8),
    ],
)
def test_compute_adaptive_question_count_uses_changed_line_buckets(
    changed_lines: int,
    expected: int,
) -> None:
    assert compute_adaptive_question_count(changed_lines, file_count=1) == expected


def test_compute_adaptive_question_count_returns_lower_bound_for_empty_diff() -> None:
    assert compute_adaptive_question_count(0, file_count=0, range_min=2, range_max=6) == 2


@pytest.mark.parametrize(
    ("file_count", "expected"),
    [
        (0, 4),
        (1, 4),
        (2, 4),
        (3, 4),
        (4, 5),
        (6, 5),
        (9, 6),
        (100, 6),
    ],
)
def test_compute_adaptive_question_count_adds_file_diversity_bonus(
    file_count: int,
    expected: int,
) -> None:
    assert compute_adaptive_question_count(21, file_count=file_count) == expected


def test_compute_adaptive_question_count_clamps_to_configured_range() -> None:
    assert compute_adaptive_question_count(500, file_count=9, range_min=2, range_max=6) == 6
    assert compute_adaptive_question_count(1, file_count=1, range_min=5, range_max=10) == 5
    assert compute_adaptive_question_count(500, file_count=9, range_min=-5, range_max=99) == 10


def test_compute_adaptive_question_count_handles_very_large_inputs() -> None:
    assert compute_adaptive_question_count(10**9, file_count=10**6) == 8


@pytest.mark.parametrize("invalid_value", [float("nan"), True, False, None, float("inf")])
def test_compute_adaptive_question_count_rejects_invalid_changed_lines(
    invalid_value: Any,
) -> None:
    with pytest.raises(TypeError):
        compute_adaptive_question_count(invalid_value, file_count=1)


@pytest.mark.parametrize("invalid_value", [float("nan"), True, False, None, float("inf")])
def test_compute_adaptive_question_count_rejects_invalid_file_count(
    invalid_value: Any,
) -> None:
    with pytest.raises(TypeError):
        compute_adaptive_question_count(20, file_count=invalid_value)


@pytest.mark.parametrize(
    ("changed_lines", "file_count"),
    [(-1, 1), (20, -1)],
)
def test_compute_adaptive_question_count_rejects_negative_stats(
    changed_lines: int,
    file_count: int,
) -> None:
    with pytest.raises(ValueError):
        compute_adaptive_question_count(changed_lines, file_count=file_count)


@pytest.mark.parametrize("field_name", ["range_min", "range_max"])
@pytest.mark.parametrize("invalid_value", [float("nan"), True, None, float("inf")])
def test_compute_adaptive_question_count_rejects_invalid_range_bounds(
    field_name: str,
    invalid_value: Any,
) -> None:
    with pytest.raises(TypeError):
        compute_adaptive_question_count(20, file_count=1, **{field_name: invalid_value})


def test_compute_adaptive_question_count_clamps_equal_range_to_single_value() -> None:
    assert compute_adaptive_question_count(500, file_count=9, range_min=4, range_max=4) == 4


def test_compute_adaptive_question_count_swaps_reversed_range_bounds() -> None:
    assert compute_adaptive_question_count(500, file_count=9, range_min=6, range_max=2) == 6


def test_resolve_question_count_uses_fixed_count_for_fixed_mode() -> None:
    assert (
        resolve_question_count(
            "fixed",
            fixed_count=5,
            diff_stats={"total_changed_lines": 500, "file_count": 9},
        )
        == 5
    )


@pytest.mark.parametrize("invalid_count", [0, 11, True, None, float("nan"), "3"])
def test_resolve_question_count_rejects_invalid_fixed_count(invalid_count: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        resolve_question_count("fixed", fixed_count=invalid_count, diff_stats=None)


def test_resolve_question_count_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="mode must be 'fixed' or 'auto'"):
        resolve_question_count("adaptive", fixed_count=3, diff_stats=None)


def test_resolve_question_count_uses_diff_stats_for_auto_mode() -> None:
    assert (
        resolve_question_count(
            "auto",
            fixed_count=3,
            diff_stats={"total_changed_lines": 500, "file_count": 9},
            auto_range_min=3,
            auto_range_max=8,
        )
        == 8
    )


@pytest.mark.parametrize(
    "diff_stats",
    [
        None,
        {},
        {"total_changed_lines": 100},
        {"file_count": 3},
        {"total_changed_lines": True, "file_count": 3},
        {"total_changed_lines": 100, "file_count": False},
        {"total_changed_lines": -1, "file_count": 3},
        {"total_changed_lines": 100, "file_count": -1},
    ],
)
def test_resolve_question_count_falls_back_to_fixed_count_without_complete_stats(
    diff_stats: dict[str, int] | None,
) -> None:
    assert resolve_question_count("auto", fixed_count=4, diff_stats=diff_stats) == 4
