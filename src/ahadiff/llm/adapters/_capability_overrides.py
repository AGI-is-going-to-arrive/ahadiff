from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from ahadiff.contracts import ProviderCapabilities, ProviderCapabilityOverride

if TYPE_CHECKING:
    from collections.abc import Mapping

_PROVIDER_CAPABILITY_OVERRIDE_FIELDS = frozenset(get_args(ProviderCapabilityOverride))


def _bool_override_value(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def apply_capability_overrides(
    caps: ProviderCapabilities,
    overrides: Mapping[str, object] | None,
    *,
    blocked_fields: frozenset[str] = frozenset(),
) -> ProviderCapabilities:
    """Apply fail-open boolean capability overrides to adapter defaults.

    Unknown keys and non-bool values are ignored by design so bypassed or
    forward-compatible values cannot crash adapter construction. Strict key and
    bool validation lives in ProviderConfig; callers that require rejection must
    validate through that contract instead of using model_copy(update=...).
    """
    if not overrides:
        return caps
    values = caps.model_dump()
    updates: dict[str, bool] = {}
    for key, raw_value in overrides.items():
        value = _bool_override_value(raw_value)
        if (
            key in _PROVIDER_CAPABILITY_OVERRIDE_FIELDS
            and value is not None
            and key in values
            and key not in blocked_fields
            and isinstance(values[key], bool)
        ):
            updates[key] = value
    if not updates:
        return caps
    return caps.model_copy(update=updates)


__all__ = ["apply_capability_overrides"]
