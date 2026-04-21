from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ahadiff.core.errors import SafetyError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .redact import SecretFinding

PrivacyMode = Literal["strict_local", "redacted_remote", "explicit_remote"]
TransportTarget = Literal["local", "remote"]
_VALID_PRIVACY_MODES = frozenset({"strict_local", "redacted_remote", "explicit_remote"})
_VALID_TRANSPORT_TARGETS = frozenset({"local", "remote"})


def assert_no_unredacted_secret(text: str, findings: Iterable[SecretFinding]) -> None:
    leaked_rules = [
        finding.rule_id
        for finding in findings
        if finding.blocked_remote and not finding.allowlisted and finding.raw_value in text
    ]
    if leaked_rules:
        raise SafetyError(
            "unredacted secret remains in outbound payload: " + ", ".join(sorted(set(leaked_rules)))
        )


def enforce_privacy_mode(
    mode: PrivacyMode,
    *,
    target: TransportTarget,
    text: str,
    findings: Iterable[SecretFinding],
    is_redacted: bool,
) -> None:
    if mode not in _VALID_PRIVACY_MODES:
        raise SafetyError(f"unsupported privacy_mode: {mode}")
    if target not in _VALID_TRANSPORT_TARGETS:
        raise SafetyError(f"unsupported transport target: {target}")
    if target == "local":
        return
    if mode == "strict_local":
        raise SafetyError("strict_local mode forbids remote transport")
    if mode == "redacted_remote":
        if not is_redacted:
            raise SafetyError("redacted_remote mode requires a redacted payload")
        assert_no_unredacted_secret(text, findings)
        return
    return


__all__ = ["assert_no_unredacted_secret", "enforce_privacy_mode"]
