from __future__ import annotations

import errno
import hashlib
import html
import json
import os
import stat
import unicodedata
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from ahadiff.core.config import load_security_config, load_workspace_security_config
from ahadiff.core.errors import SafetyError
from ahadiff.core.paths import find_repo_root, ignore_file_path

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_IGNORE_FILE_MAX_BYTES = 1_000_000


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
    text = _read_ignore_file_no_follow(path)
    if text is None:
        return IgnoreMatcher()

    patterns: list[str] = []
    for raw_line in text.splitlines():
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
    if _has_windows_drive_or_unc_syntax(str(candidate)):
        raise SafetyError("path must not use Windows drive or UNC syntax")
    candidate_path = Path(candidate).expanduser()
    absolute_candidate = candidate_path if candidate_path.is_absolute() else root / candidate_path

    _reject_symlink_or_special_path(root, absolute_candidate)
    resolved = absolute_candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SafetyError("path escapes repo root") from exc
    return resolved


def _has_windows_drive_or_unc_syntax(path_text: str) -> bool:
    return path_text.startswith(("\\\\", "//")) or (
        len(path_text) >= 2 and path_text[1] == ":" and path_text[0].isalpha()
    )


def _reject_symlink_or_special_path(root: Path, candidate: Path) -> None:
    path_chain = [candidate, *candidate.parents]
    repo_anchor_index = next(
        (
            index
            for index, current in enumerate(path_chain)
            if current.resolve(strict=False) == root
        ),
        None,
    )
    if repo_anchor_index is None:
        raise SafetyError("path is outside repo root")

    for current in path_chain[:repo_anchor_index]:
        if current.is_symlink():
            raise SafetyError(f"symlink paths are not allowed: {current}")
        if not current.exists():
            continue
        mode = current.lstat().st_mode
        if stat.S_ISFIFO(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISSOCK(mode):
            raise SafetyError(f"special files are not allowed: {current}")


def _read_ignore_file_no_follow(path: Path) -> str | None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SafetyError(".ahadiffignore is unreadable") from exc
    _validate_ignore_file_stat(path_stat)

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise SafetyError(".ahadiffignore must not be a symlink") from exc
        raise SafetyError(".ahadiffignore is unreadable") from exc

    try:
        file_stat = os.fstat(fd)
        _validate_ignore_file_stat(file_stat)
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise SafetyError(".ahadiffignore changed during validation")
        chunks: list[bytes] = []
        total_bytes = 0
        while True:
            chunk = os.read(fd, min(65_536, _IGNORE_FILE_MAX_BYTES + 1 - total_bytes))
            if chunk == b"":
                break
            chunks.append(chunk)
            total_bytes += len(chunk)
            if total_bytes > _IGNORE_FILE_MAX_BYTES:
                raise SafetyError(f".ahadiffignore exceeds {_IGNORE_FILE_MAX_BYTES} bytes")
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SafetyError(".ahadiffignore must be valid UTF-8") from exc
    finally:
        os.close(fd)


def _validate_ignore_file_stat(path_stat: os.stat_result) -> None:
    if stat.S_ISLNK(path_stat.st_mode):
        raise SafetyError(".ahadiffignore must not be a symlink")
    if _has_windows_reparse_point(path_stat):
        raise SafetyError(".ahadiffignore must not be a Windows reparse point or junction")
    if not stat.S_ISREG(path_stat.st_mode):
        raise SafetyError(".ahadiffignore must be a regular file")
    if getattr(path_stat, "st_nlink", 1) > 1:
        raise SafetyError(".ahadiffignore must not be a hardlink")
    if path_stat.st_size > _IGNORE_FILE_MAX_BYTES:
        raise SafetyError(f".ahadiffignore exceeds {_IGNORE_FILE_MAX_BYTES} bytes")


def _has_windows_reparse_point(path_stat: object) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


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
