from __future__ import annotations

MAX_PROBED_TOKEN_LIMIT = 100_000_000


def safe_positive_int(
    value: object,
    *,
    max_value: int = MAX_PROBED_TOKEN_LIMIT,
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value <= 0 or value > max_value:
        return None
    return value


__all__ = ["MAX_PROBED_TOKEN_LIMIT", "safe_positive_int"]
