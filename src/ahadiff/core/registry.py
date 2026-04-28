from __future__ import annotations

import errno
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import portalocker

from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import global_config_dir

_REGISTRY_FILENAME = "registry.json"
_REGISTRY_LOCK_FILENAME = "registry.lock"
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class RegistryEntry:
    repo_path: str
    state_dir: str
    last_seen: str


def _registry_path() -> Path:
    from pathlib import Path as _Path

    return _Path(str(global_config_dir())) / _REGISTRY_FILENAME


def _registry_lock_path() -> Path:
    from pathlib import Path as _Path

    return _Path(str(global_config_dir())) / _REGISTRY_LOCK_FILENAME


@contextmanager
def _registry_lock() -> Any:
    lock_path = _registry_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        portalocker.lock(handle, portalocker.LOCK_EX)
        yield
    finally:
        try:
            portalocker.unlock(handle)
        finally:
            handle.close()


def _normalize_entry_path(path: Path) -> str:
    resolved = path.expanduser().resolve(strict=False)
    return os.path.normcase(str(resolved))


def _load_registry_unlocked(path: Path) -> list[RegistryEntry]:
    try:
        raw = _read_text_no_follow(path)
    except FileNotFoundError:
        return []
    except OSError:
        return []
    try:
        data: Any = safe_json_loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    items = cast("list[Any]", data)
    entries: list[RegistryEntry] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        item = cast("dict[str, Any]", raw_item)
        try:
            entries.append(
                RegistryEntry(
                    repo_path=str(item["repo_path"]),
                    state_dir=str(item["state_dir"]),
                    last_seen=str(item["last_seen"]),
                )
            )
        except (KeyError, TypeError):
            continue
    return entries


def _read_text_no_follow(path: Path) -> str:
    path_stat = path.lstat()
    if stat.S_ISLNK(path_stat.st_mode) or _has_windows_reparse_point(path_stat):
        raise OSError(errno.ELOOP, "refusing to follow registry.json symlink", str(path))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    try:
        opened_stat = os.fstat(fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise OSError(errno.EINVAL, "registry.json must be a regular file", str(path))
        if _has_windows_reparse_point(opened_stat):
            raise OSError(errno.ELOOP, "refusing to follow registry.json reparse point", str(path))
        if (opened_stat.st_dev, opened_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise OSError(errno.ELOOP, "registry.json changed during validation", str(path))
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd != -1:
            os.close(fd)


def _has_windows_reparse_point(path_stat: os.stat_result) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def load_registry() -> list[RegistryEntry]:
    path = _registry_path()
    with _registry_lock():
        return _load_registry_unlocked(path)


def _save_registry_unlocked(path: Path, entries: list[RegistryEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([asdict(e) for e in entries], indent=2, ensure_ascii=False)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload + "\n")
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def save_registry(entries: list[RegistryEntry]) -> None:
    path = _registry_path()
    with _registry_lock():
        _save_registry_unlocked(path, entries)


def register_repo(repo_path: Path, state_dir: Path) -> None:
    path = _registry_path()
    rp = _normalize_entry_path(repo_path)
    normalized_state_dir = _normalize_entry_path(state_dir)
    now = datetime.now(UTC).isoformat()
    with _registry_lock():
        entries = _load_registry_unlocked(path)
        updated: list[RegistryEntry] = []
        found = False
        for entry in entries:
            if _normalize_entry_path(Path(entry.repo_path)) == rp:
                updated.append(
                    RegistryEntry(repo_path=rp, state_dir=normalized_state_dir, last_seen=now)
                )
                found = True
            else:
                updated.append(entry)
        if not found:
            updated.append(
                RegistryEntry(repo_path=rp, state_dir=normalized_state_dir, last_seen=now)
            )
        _save_registry_unlocked(path, updated)


def unregister_repo(repo_path: Path) -> None:
    path = _registry_path()
    rp = _normalize_entry_path(repo_path)
    with _registry_lock():
        entries = _load_registry_unlocked(path)
        filtered = [e for e in entries if _normalize_entry_path(Path(e.repo_path)) != rp]
        if len(filtered) != len(entries):
            _save_registry_unlocked(path, filtered)


def list_registered_repos() -> list[RegistryEntry]:
    from pathlib import Path as _Path

    entries = load_registry()
    return [e for e in entries if _Path(e.state_dir).is_dir()]


__all__ = [
    "RegistryEntry",
    "list_registered_repos",
    "load_registry",
    "register_repo",
    "save_registry",
    "unregister_repo",
]
