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
        (401, 9),
        (800, 9),
        (801, 12),
        (1200, 12),
        (1201, 15),
        (2000, 15),
        (2001, 18),
        (3000, 18),
        (3001, 20),
        (2**63 - 1, 20),
    ],
)
def test_compute_adaptive_question_count_uses_changed_line_buckets(
    changed_lines: int,
    expected: int,
) -> None:
    assert compute_adaptive_question_count(changed_lines, file_count=1, range_max=30) == expected


def test_compute_adaptive_question_count_returns_lower_bound_for_empty_diff() -> None:
    assert compute_adaptive_question_count(0, file_count=0, range_min=2, range_max=6) == 2
    assert compute_adaptive_question_count(0, file_count=0, range_min=1, range_max=30) == 1


@pytest.mark.parametrize(
    ("file_count", "expected"),
    [
        (0, 4),
        (1, 4),
        (2, 4),
        (3, 4),
        (4, 5),
        (6, 5),
        (7, 6),
        (10, 7),
        (13, 8),
        (100, 8),
    ],
)
def test_compute_adaptive_question_count_adds_file_diversity_bonus(
    file_count: int,
    expected: int,
) -> None:
    assert compute_adaptive_question_count(21, file_count=file_count) == expected


def test_compute_adaptive_question_count_clamps_result_to_configured_range() -> None:
    assert compute_adaptive_question_count(500, file_count=9, range_min=2, range_max=6) == 6
    assert compute_adaptive_question_count(1, file_count=1, range_min=5, range_max=10) == 5
    assert compute_adaptive_question_count(10**9, file_count=10**6, range_min=1, range_max=30) == 24


def test_compute_adaptive_question_count_keeps_small_multifile_diff_bounded() -> None:
    assert compute_adaptive_question_count(10, file_count=20, range_min=1, range_max=30) == 7


def test_compute_adaptive_question_count_respects_high_minimum_floor() -> None:
    assert compute_adaptive_question_count(5, file_count=1, range_min=25, range_max=30) == 25


def test_compute_adaptive_question_count_handles_very_large_inputs() -> None:
    assert compute_adaptive_question_count(10**9, file_count=10**6) == 12


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
@pytest.mark.parametrize("invalid_value", [0, 31, float("nan"), True, None, float("inf"), "8"])
def test_compute_adaptive_question_count_rejects_invalid_range_bounds(
    field_name: str,
    invalid_value: Any,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        compute_adaptive_question_count(20, file_count=1, **{field_name: invalid_value})


def test_compute_adaptive_question_count_clamps_equal_range_to_single_value() -> None:
    assert compute_adaptive_question_count(500, file_count=9, range_min=4, range_max=4) == 4


def test_compute_adaptive_question_count_rejects_reversed_range_bounds() -> None:
    with pytest.raises(ValueError, match="range_min must be <= range_max"):
        compute_adaptive_question_count(500, file_count=9, range_min=6, range_max=2)


def test_resolve_question_count_uses_fixed_count_for_fixed_mode() -> None:
    assert (
        resolve_question_count(
            "fixed",
            fixed_count=5,
            diff_stats={"total_changed_lines": 500, "file_count": 9},
        )
        == 5
    )


@pytest.mark.parametrize("invalid_count", [0, 31, True, None, float("nan"), "3"])
def test_resolve_question_count_rejects_invalid_fixed_count(invalid_count: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        resolve_question_count("fixed", fixed_count=invalid_count, diff_stats=None)


def test_resolve_question_count_accepts_max_fixed_count() -> None:
    assert resolve_question_count("fixed", fixed_count=30, diff_stats=None) == 30


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


def test_resolve_question_count_uses_default_auto_range_max() -> None:
    assert (
        resolve_question_count(
            "auto",
            fixed_count=3,
            diff_stats={"total_changed_lines": 10**9, "file_count": 10**6},
        )
        == 12
    )


def test_resolve_question_count_allows_large_diff_to_reach_explicit_max() -> None:
    assert (
        resolve_question_count(
            "auto",
            fixed_count=3,
            diff_stats={"total_changed_lines": 10**9, "file_count": 10**6},
            auto_range_min=1,
            auto_range_max=30,
        )
        == 24
    )


@pytest.mark.parametrize(
    ("auto_range_min", "auto_range_max"),
    [(0, 12), (3, 31), (12, 3), ("3", 12), (3.5, 12)],
)
def test_resolve_question_count_rejects_invalid_auto_range(
    auto_range_min: Any,
    auto_range_max: Any,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        resolve_question_count(
            "auto",
            fixed_count=3,
            diff_stats={"total_changed_lines": 100, "file_count": 1},
            auto_range_min=auto_range_min,
            auto_range_max=auto_range_max,
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
