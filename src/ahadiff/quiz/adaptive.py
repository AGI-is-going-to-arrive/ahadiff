from __future__ import annotations


def _clamp(value: int, lower: int, upper: int) -> int:
    return min(max(value, lower), upper)


_QUESTION_COUNT_MIN = 1
_QUESTION_COUNT_MAX = 10


def _require_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _require_non_negative_int(name: str, value: object) -> int:
    parsed = _require_int(name, value)
    if parsed < 0:
        raise ValueError(f"{name} must be >= 0")
    return parsed


def _require_question_count(name: str, value: object) -> int:
    parsed = _require_int(name, value)
    if parsed < _QUESTION_COUNT_MIN or parsed > _QUESTION_COUNT_MAX:
        raise ValueError(f"{name} must be between {_QUESTION_COUNT_MIN} and {_QUESTION_COUNT_MAX}")
    return parsed


def compute_adaptive_question_count(
    total_changed_lines: int,
    file_count: int,
    range_min: int = 3,
    range_max: int = 8,
) -> int:
    """Map diff size and file diversity to a bounded quiz question count."""

    total_changed_lines = _require_non_negative_int("total_changed_lines", total_changed_lines)
    file_count = _require_non_negative_int("file_count", file_count)
    range_min = _require_int("range_min", range_min)
    range_max = _require_int("range_max", range_max)

    lower = _clamp(range_min, _QUESTION_COUNT_MIN, _QUESTION_COUNT_MAX)
    upper = _clamp(range_max, _QUESTION_COUNT_MIN, _QUESTION_COUNT_MAX)
    if lower > upper:
        lower, upper = upper, lower
    if total_changed_lines == 0:
        return lower

    if total_changed_lines <= 20:
        base_count = 3
    elif total_changed_lines <= 50:
        base_count = 4
    elif total_changed_lines <= 100:
        base_count = 5
    elif total_changed_lines <= 200:
        base_count = 6
    elif total_changed_lines <= 400:
        base_count = 7
    else:
        base_count = 8

    file_bonus = min(max(file_count - 1, 0) // 3, 2)
    return _clamp(base_count + file_bonus, lower, upper)


def resolve_question_count(
    mode: str,
    fixed_count: int,
    diff_stats: dict[str, int] | None,
    auto_range_min: int = 3,
    auto_range_max: int = 8,
) -> int:
    """Resolve the effective quiz question count for fixed or adaptive mode."""

    fixed_count = _require_question_count("fixed_count", fixed_count)
    if mode == "fixed":
        return fixed_count
    if mode != "auto":
        raise ValueError("mode must be 'fixed' or 'auto'")
    if diff_stats is None:
        return fixed_count

    total_changed_lines = diff_stats.get("total_changed_lines")
    file_count = diff_stats.get("file_count")
    if not isinstance(total_changed_lines, int) or isinstance(total_changed_lines, bool):
        return fixed_count
    if not isinstance(file_count, int) or isinstance(file_count, bool):
        return fixed_count
    if total_changed_lines < 0 or file_count < 0:
        return fixed_count

    return compute_adaptive_question_count(
        total_changed_lines,
        file_count,
        range_min=auto_range_min,
        range_max=auto_range_max,
    )
