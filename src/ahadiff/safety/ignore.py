from __future__ import annotations

import hashlib
import html
import json
import stat
import unicodedata
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from ahadiff.core.config import load_security_config, load_workspace_security_config
from ahadiff.core.errors import SafetyError
from ahadiff.core.paths import find_repo_root, ignore_file_path


@dataclass(frozen=True)
class AllowlistPolicy:
    allow_exact: tuple[str, ...] = ()
    allow_paths: tuple[str, ...] = ()
    suppress_rules: tuple[str, ...] = ()


class IgnoreMatcher(tuple[str, ...]):
    __slots__ = ()

    @property
    def patterns(self) -> tuple[str, ...]:
        return tuple(self)


def canonicalize_path_text(path: str | Path) -> str:
    normalized = unicodedata.normalize("NFC", str(path).replace("\\", "/")).strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def load_ignore_matcher(repo_root: Path | None = None) -> IgnoreMatcher:
    root = find_repo_root(repo_root)
    path = ignore_file_path(root)
    if not path.exists():
        return IgnoreMatcher()

    patterns: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        normalized = canonicalize_path_text(stripped)
        if normalized.endswith("/"):
            normalized = f"{normalized}**"
        patterns.append(normalized)
    return IgnoreMatcher(patterns)


def is_ignored_path(path: str | Path, matcher: IgnoreMatcher) -> bool:
    normalized = canonicalize_path_text(path)
    return any(fnmatchcase(normalized, pattern) for pattern in matcher.patterns)


def load_allowlist_policy(repo_root: Path | None = None) -> AllowlistPolicy:
    config = load_security_config(repo_root)
    return AllowlistPolicy(
        allow_exact=config.allow_exact,
        allow_paths=tuple(canonicalize_path_text(value) for value in config.allow_paths),
        suppress_rules=config.suppress_rules,
    )


def load_workspace_allowlist_policy(workspace_root: Path) -> AllowlistPolicy:
    config = load_workspace_security_config(workspace_root)
    return AllowlistPolicy(
        allow_exact=config.allow_exact,
        allow_paths=tuple(canonicalize_path_text(value) for value in config.allow_paths),
        suppress_rules=config.suppress_rules,
    )


def compute_allowlist_digest(policy: AllowlistPolicy) -> str:
    payload = {
        "allow_exact": sorted(policy.allow_exact),
        "allow_paths": sorted(policy.allow_paths),
        "suppress_rules": sorted(policy.suppress_rules),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def is_finding_allowlisted(
    *,
    severity: str,
    rule_id: str,
    raw_value: str,
    path: str | None,
    policy: AllowlistPolicy,
) -> bool:
    if severity != "soft_detect":
        return False
    if rule_id in policy.suppress_rules:
        return True
    if any(_matches_exact_entry(raw_value, entry) for entry in policy.allow_exact):
        return True
    if path is not None:
        normalized_path = canonicalize_path_text(path)
        return any(fnmatchcase(normalized_path, pattern) for pattern in policy.allow_paths)
    return False


def _matches_exact_entry(raw_value: str, entry: str) -> bool:
    if entry.startswith("sha256:"):
        digest = hashlib.sha256(raw_value.encode("utf-8")).hexdigest()
        return digest == entry.removeprefix("sha256:")
    return raw_value == entry


def resolve_safe_path(repo_root: Path | None, candidate: str | Path) -> Path:
    root = find_repo_root(repo_root).resolve()
    return resolve_safe_path_from_root(root, candidate)


def resolve_safe_path_from_root(root: Path, candidate: str | Path) -> Path:
    root = root.resolve()
    candidate_path = Path(candidate).expanduser()
    absolute_candidate = candidate_path if candidate_path.is_absolute() else root / candidate_path

    _reject_symlink_or_special_path(root, absolute_candidate)
    resolved = absolute_candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SafetyError(f"path escapes repo root: {candidate}") from exc
    return resolved


def _reject_symlink_or_special_path(root: Path, candidate: Path) -> None:
    for current in (candidate, *candidate.parents):
        if current == current.parent:
            break
        if current.is_symlink():
            raise SafetyError(f"symlink paths are not allowed: {current}")
        if not current.exists():
            if current == root:
                break
            continue
        mode = current.lstat().st_mode
        if current != root and (
            stat.S_ISFIFO(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISSOCK(mode)
        ):
            raise SafetyError(f"special files are not allowed: {current}")
        if current == root:
            break


def escape_html_text(text: str) -> str:
    return html.escape(text, quote=True)


def escape_json_text(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def escape_terminal_text(text: str) -> str:
    escaped: list[str] = []
    for char in text:
        code_point = ord(char)
        if char in "\n\r\t" or (0x20 <= code_point < 0x7F):
            escaped.append(char)
            continue
        if code_point <= 0xFF:
            escaped.append(f"\\x{code_point:02x}")
            continue
        if code_point <= 0xFFFF:
            escaped.append(f"\\u{code_point:04x}")
            continue
        escaped.append(f"\\U{code_point:08x}")
    return "".join(escaped)


__all__ = [
    "AllowlistPolicy",
    "IgnoreMatcher",
    "canonicalize_path_text",
    "compute_allowlist_digest",
    "escape_html_text",
    "escape_json_text",
    "escape_terminal_text",
    "is_finding_allowlisted",
    "is_ignored_path",
    "load_allowlist_policy",
    "load_workspace_allowlist_policy",
    "load_ignore_matcher",
    "resolve_safe_path",
    "resolve_safe_path_from_root",
]
