from __future__ import annotations

import base64
import binascii
import hashlib
import math
import pathlib as _pathlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

    from ._types import SourceKind
else:
    from . import _types as _safety_types

    Path = _pathlib.Path
    SourceKind = _safety_types.SourceKind
from .ignore import (
    AllowlistPolicy,
    compute_allowlist_digest,
    is_finding_allowlisted,
    load_allowlist_policy,
)

RuleSeverity = Literal["hard_block", "soft_detect"]


@dataclass(frozen=True)
class ScanTarget:
    source_name: str
    text: str
    source_kind: SourceKind = "raw_patch"
    path: str | None = None


@dataclass(frozen=True)
class SecretFinding:
    rule_id: str
    secret_type: str
    severity: RuleSeverity
    source_name: str
    source_kind: SourceKind
    start: int
    end: int
    line: int
    column: int
    action: str
    blocked_remote: bool
    allowlisted: bool = False
    path: str | None = None
    raw_value: str = field(repr=False, default="")

    @property
    def replacement(self) -> str:
        return f"[REDACTED:{self.secret_type}]"

    @property
    def value_hash(self) -> str:
        return hashlib.sha256(self.raw_value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RedactedTarget:
    source_name: str
    source_kind: SourceKind
    redacted_text: str
    findings: tuple[SecretFinding, ...]
    path: str | None = None


@dataclass(frozen=True)
class RedactionPipelineResult:
    primary_target: RedactedTarget
    secondary_targets: tuple[RedactedTarget, ...]
    findings: tuple[SecretFinding, ...]
    allowlist_digest: str
    blocked_remote: bool

    @property
    def redacted_text(self) -> str:
        return self.primary_target.redacted_text


@dataclass(frozen=True)
class _SecretRule:
    rule_id: str
    secret_type: str
    severity: RuleSeverity
    pattern: re.Pattern[str]
    blocked_remote: bool = True


_SECRET_RULES: tuple[_SecretRule, ...] = (
    _SecretRule(
        rule_id="OPENAI_API_KEY",
        secret_type="openai_api_key",
        severity="hard_block",
        pattern=re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    ),
    _SecretRule(
        rule_id="ANTHROPIC_API_KEY",
        secret_type="anthropic_api_key",
        severity="hard_block",
        pattern=re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b"),
    ),
    _SecretRule(
        rule_id="AWS_ACCESS_KEY",
        secret_type="aws_access_key",
        severity="hard_block",
        pattern=re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ),
    _SecretRule(
        rule_id="JWT_TOKEN",
        secret_type="jwt_token",
        severity="hard_block",
        pattern=re.compile(r"\beyJ[A-Za-z0-9_\-=]+?\.[A-Za-z0-9_\-=]+?\.[A-Za-z0-9_\-+/=]+\b"),
    ),
    _SecretRule(
        rule_id="DATABASE_URL",
        secret_type="database_url",
        severity="hard_block",
        pattern=re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:@]+:[^\s@]+@[^\s]+"
        ),
    ),
    _SecretRule(
        rule_id="PEM_PRIVATE_KEY",
        secret_type="pem_private_key",
        severity="hard_block",
        pattern=re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"
        ),
    ),
    _SecretRule(
        rule_id="GITHUB_TOKEN",
        secret_type="github_token",
        severity="hard_block",
        pattern=re.compile(
            r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"
        ),
    ),
    _SecretRule(
        rule_id="SLACK_WEBHOOK",
        secret_type="slack_webhook",
        severity="hard_block",
        pattern=re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+"),
    ),
    _SecretRule(
        rule_id="COOKIE_SESSION_TOKEN",
        secret_type="cookie_session_token",
        severity="hard_block",
        pattern=re.compile(
            r"(?im)\b(?:set-cookie|cookie)\s*:\s*[^=\n;]+=(?:[A-Za-z0-9._%+-]{16,})"
        ),
    ),
    _SecretRule(
        rule_id="CERTIFICATE_BLOCK",
        secret_type="certificate_block",
        severity="soft_detect",
        pattern=re.compile(r"-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----"),
        blocked_remote=False,
    ),
)
_BASE64_WRAPPED_SECRET = re.compile(
    r"(?im)(?:api[_-]?key|token|secret|password|session(?:id)?)\s*[:=]\s*[\"']?(?P<value>[A-Za-z0-9+/]{24,}={0,2})[\"']?"
)
_HIGH_ENTROPY_TOKEN = re.compile(
    r"(?<![A-Za-z0-9+/=_-])(?P<value>[A-Za-z0-9+/=_-]{21,})(?![A-Za-z0-9+/=_-])"
)
_UUID_TOKEN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_HEX_HASH = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64}|[0-9a-fA-F]{128})$")
_SOURCE_MAP_FRAGMENT = re.compile(r"^(?:AAAA|CAAC|EAAE|GAAG|IAAI|OAAO|QAAQ|SAAS|UAAU|YAAA){2,}$")


def redaction_pipeline(
    raw_text: str,
    *,
    repo_root: Path | None = None,
    policy: AllowlistPolicy | None = None,
    resolved_files: dict[str, str] | None = None,
    branch_names: tuple[str, ...] = (),
    tag_names: tuple[str, ...] = (),
) -> RedactionPipelineResult:
    active_policy = policy or _resolve_policy(repo_root)
    targets = [ScanTarget(source_name="raw_patch", text=raw_text, source_kind="raw_patch")]
    if resolved_files:
        for path, text in sorted(resolved_files.items()):
            targets.append(
                ScanTarget(
                    source_name=path,
                    text=text,
                    source_kind="resolved_file",
                    path=path,
                )
            )
    for branch_name in branch_names:
        targets.append(
            ScanTarget(source_name=branch_name, text=branch_name, source_kind="branch_name")
        )
    for tag_name in tag_names:
        targets.append(ScanTarget(source_name=tag_name, text=tag_name, source_kind="tag_name"))

    redacted_targets: list[RedactedTarget] = []
    all_findings: list[SecretFinding] = []
    for target in targets:
        findings = scan_target_for_secrets(target, policy=active_policy)
        redacted_targets.append(
            RedactedTarget(
                source_name=target.source_name,
                source_kind=target.source_kind,
                redacted_text=apply_redactions(target.text, findings),
                findings=findings,
                path=target.path,
            )
        )
        all_findings.extend(findings)

    primary_target = redacted_targets[0]
    secondary_targets = tuple(redacted_targets[1:])
    return RedactionPipelineResult(
        primary_target=primary_target,
        secondary_targets=secondary_targets,
        findings=tuple(all_findings),
        allowlist_digest=compute_allowlist_digest(active_policy),
        blocked_remote=any(
            finding.blocked_remote and not finding.allowlisted for finding in all_findings
        ),
    )


def scan_text_for_secrets(
    text: str,
    *,
    source_name: str = "raw_patch",
    source_kind: SourceKind = "raw_patch",
    path: str | None = None,
    policy: AllowlistPolicy | None = None,
) -> tuple[SecretFinding, ...]:
    return scan_target_for_secrets(
        ScanTarget(source_name=source_name, text=text, source_kind=source_kind, path=path),
        policy=policy or AllowlistPolicy(),
    )


def scan_target_for_secrets(
    target: ScanTarget, *, policy: AllowlistPolicy
) -> tuple[SecretFinding, ...]:
    normalized_text = unicodedata.normalize("NFC", target.text)
    findings: list[SecretFinding] = []
    occupied: list[tuple[int, int]] = []

    for rule in _SECRET_RULES:
        for match in rule.pattern.finditer(normalized_text):
            start, end = match.span()
            if _overlaps(occupied, start, end):
                continue
            occupied.append((start, end))
            findings.append(
                _make_finding(
                    rule_id=rule.rule_id,
                    secret_type=rule.secret_type,
                    severity=rule.severity,
                    blocked_remote=rule.blocked_remote,
                    raw_value=match.group(0),
                    start=start,
                    end=end,
                    target=target,
                    text=normalized_text,
                    policy=policy,
                )
            )

    for start, end, raw_value in _iter_base64_wrapped_secret_matches(normalized_text):
        if _overlaps(occupied, start, end):
            continue
        occupied.append((start, end))
        findings.append(
            _make_finding(
                rule_id="BASE64_WRAPPED_SECRET",
                secret_type="base64_wrapped_secret",
                severity="hard_block",
                blocked_remote=True,
                raw_value=raw_value,
                start=start,
                end=end,
                target=target,
                text=normalized_text,
                policy=policy,
            )
        )

    for start, end, raw_value in _iter_high_entropy_matches(normalized_text):
        if _overlaps(occupied, start, end):
            continue
        occupied.append((start, end))
        findings.append(
            _make_finding(
                rule_id="HIGH_ENTROPY_STRING",
                secret_type="high_entropy_string",
                severity="soft_detect",
                blocked_remote=False,
                raw_value=raw_value,
                start=start,
                end=end,
                target=target,
                text=normalized_text,
                policy=policy,
            )
        )

    findings.sort(key=lambda item: (item.start, item.end))
    return tuple(findings)


def apply_redactions(text: str, findings: tuple[SecretFinding, ...]) -> str:
    output = unicodedata.normalize("NFC", text)
    active_findings = [finding for finding in findings if not finding.allowlisted]
    for finding in sorted(active_findings, key=lambda item: item.start, reverse=True):
        output = output[: finding.start] + finding.replacement + output[finding.end :]
    return output


def _resolve_policy(repo_root: Path | None) -> AllowlistPolicy:
    if repo_root is None:
        return AllowlistPolicy()
    return load_allowlist_policy(repo_root)


def _make_finding(
    *,
    rule_id: str,
    secret_type: str,
    severity: RuleSeverity,
    blocked_remote: bool,
    raw_value: str,
    start: int,
    end: int,
    target: ScanTarget,
    text: str,
    policy: AllowlistPolicy,
) -> SecretFinding:
    line, column = _line_and_column(text, start)
    allowlisted = is_finding_allowlisted(
        severity=severity,
        rule_id=rule_id,
        raw_value=raw_value,
        path=target.path,
        policy=policy,
    )
    return SecretFinding(
        rule_id=rule_id,
        secret_type=secret_type,
        severity=severity,
        source_name=target.source_name,
        source_kind=target.source_kind,
        start=start,
        end=end,
        line=line,
        column=column,
        action="redact" if not allowlisted else "allow",
        blocked_remote=blocked_remote,
        allowlisted=allowlisted,
        path=target.path,
        raw_value=raw_value,
    )


def _iter_base64_wrapped_secret_matches(text: str) -> tuple[tuple[int, int, str], ...]:
    matches: list[tuple[int, int, str]] = []
    for match in _BASE64_WRAPPED_SECRET.finditer(text):
        raw_value = match.group("value")
        decoded = _decode_base64(raw_value)
        if decoded is None:
            continue
        if not _decoded_payload_matches_hard_block_rule(decoded):
            continue
        start, end = match.span("value")
        matches.append((start, end, raw_value))
    return tuple(matches)


def _iter_high_entropy_matches(text: str) -> tuple[tuple[int, int, str], ...]:
    matches: list[tuple[int, int, str]] = []
    for match in _HIGH_ENTROPY_TOKEN.finditer(text):
        raw_value = match.group("value")
        if _is_high_entropy_exempt(raw_value):
            continue
        if len(raw_value) <= 20 or _shannon_entropy(raw_value) <= 4.5:
            continue
        start, end = match.span("value")
        matches.append((start, end, raw_value))
    return tuple(matches)


def _decoded_payload_matches_hard_block_rule(payload: str) -> bool:
    normalized_payload = unicodedata.normalize("NFC", payload)
    return any(
        rule.blocked_remote and rule.pattern.search(normalized_payload) for rule in _SECRET_RULES
    )


def _decode_base64(value: str) -> str | None:
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.b64decode(value + padding, validate=True)
    except (ValueError, binascii.Error):
        return None
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError:
        return decoded.decode("utf-8", errors="ignore")


def _is_high_entropy_exempt(value: str) -> bool:
    lowered = value.casefold()
    return (
        _UUID_TOKEN.fullmatch(value) is not None
        or _HEX_HASH.fullmatch(value) is not None
        or _SOURCE_MAP_FRAGMENT.fullmatch(value) is not None
        or "__webpack" in lowered
        or "webpack" in lowered
        or "parcel" in lowered
        or "sourcemappingurl" in lowered
        or "__vite" in lowered
    )


def _shannon_entropy(value: str) -> float:
    frequencies = {char: value.count(char) for char in set(value)}
    length = len(value)
    entropy = 0.0
    for count in frequencies.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy


def _overlaps(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(
        start < existing_end and end > existing_start for existing_start, existing_end in spans
    )


def _line_and_column(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_newline = text.rfind("\n", 0, offset)
    column = offset + 1 if last_newline < 0 else offset - last_newline
    return line, column


__all__ = [
    "RedactedTarget",
    "RedactionPipelineResult",
    "ScanTarget",
    "SecretFinding",
    "apply_redactions",
    "redaction_pipeline",
    "scan_target_for_secrets",
    "scan_text_for_secrets",
]
