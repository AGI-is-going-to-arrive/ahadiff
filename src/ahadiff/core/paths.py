from __future__ import annotations

import os
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import InputError, StorageError

if TYPE_CHECKING:
    from collections.abc import Mapping

_MACOS_LONG_PATH_WARNING = 180
_WINDOWS_LONG_PATH_WARNING = 240


@dataclass(frozen=True)
class PathWarning:
    code: str
    message: str


def _platform_name(platform: str | None = None) -> str:
    return sys.platform if platform is None else platform


def _home_dir(env: Mapping[str, str] | None = None) -> Path:
    env_map = os.environ if env is None else env
    home = env_map.get("HOME")
    if home is not None:
        if home == "":
            raise StorageError("HOME is empty; cannot resolve global config directory")
        return Path(home)
    return Path.home()


def _normalized_path_text(path: Path) -> str:
    return unicodedata.normalize("NFC", str(path).replace("\\", "/"))


def is_network_path(path: Path, *, platform: str | None = None) -> bool:
    raw = str(path)
    current_platform = _platform_name(platform)
    if current_platform.startswith("win"):
        return raw.startswith("\\\\") or raw.startswith("//")
    return raw.startswith("//") and not raw.startswith("///")


def assert_local_repo_path(path: Path, *, platform: str | None = None) -> None:
    if is_network_path(path, platform=platform):
        raise StorageError(f"Refusing to place .ahadiff on a UNC or network-mounted path: {path}")


def inspect_repo_path(path: Path, *, platform: str | None = None) -> tuple[PathWarning, ...]:
    current_platform = _platform_name(platform)
    if not (current_platform.startswith("win") or current_platform == "darwin"):
        return ()

    raw = str(path).replace("\\", "/")
    normalized = _normalized_path_text(path)
    warnings: list[PathWarning] = []
    if normalized != raw:
        warnings.append(
            PathWarning(
                code="nfc_normalized",
                message=f"repo path is not NFC-normalized; identity key uses `{normalized}`",
            )
        )
    if normalized.casefold() != normalized:
        warnings.append(
            PathWarning(
                code="casefold_identity",
                message=(
                    "repo path changes under casefold; downstream anchors should use "
                    "case-insensitive identity"
                ),
            )
        )

    threshold = (
        _WINDOWS_LONG_PATH_WARNING
        if current_platform.startswith("win")
        else _MACOS_LONG_PATH_WARNING
    )
    if len(normalized) > threshold:
        warnings.append(
            PathWarning(
                code="long_path",
                message=(
                    f"repo path length is {len(normalized)}, "
                    f"above the advisory threshold {threshold}"
                ),
            )
        )

    return tuple(warnings)


def path_identity_key(path: Path) -> str:
    return _normalized_path_text(path).casefold()


def find_repo_root(start: Path | None = None) -> Path:
    cursor = (Path.cwd() if start is None else start).expanduser()
    if cursor.is_file():
        cursor = cursor.parent
    cursor = cursor.resolve()
    for candidate in (cursor, *cursor.parents):
        if (candidate / ".git").exists():
            return candidate
    raise InputError(f"{cursor} is not inside a git repository")


def global_config_dir(*, platform: str | None = None, env: Mapping[str, str] | None = None) -> Path:
    current_platform = _platform_name(platform)
    env_map = os.environ if env is None else env
    home = _home_dir(env_map)
    if current_platform == "darwin":
        return home / "Library" / "Application Support" / "ahadiff"
    if current_platform.startswith("win"):
        appdata = env_map.get("APPDATA")
        if not appdata:
            raise StorageError("APPDATA is not set; cannot resolve global config directory")
        return Path(appdata) / "ahadiff"
    xdg_config_home = env_map.get("XDG_CONFIG_HOME")
    base_dir = Path(xdg_config_home) if xdg_config_home else home / ".config"
    return base_dir / "ahadiff"


def project_state_dir(repo_root: Path | None = None) -> Path:
    root = find_repo_root(repo_root)
    assert_local_repo_path(root)
    return root / ".ahadiff"


def repo_config_path(repo_root: Path | None = None) -> Path:
    return project_state_dir(repo_root) / "config.toml"


def ignore_file_path(repo_root: Path | None = None) -> Path:
    root = find_repo_root(repo_root)
    return root / ".ahadiffignore"


def run_dir(run_id: str, repo_root: Path | None = None) -> Path:
    return project_state_dir(repo_root) / "runs" / run_id


def review_db_path(repo_root: Path | None = None) -> Path:
    return project_state_dir(repo_root) / "review.sqlite"


def audit_log_path(repo_root: Path | None = None) -> Path:
    return project_state_dir(repo_root) / "audit.jsonl"


def private_audit_log_path(repo_root: Path | None = None) -> Path:
    return project_state_dir(repo_root) / "audit.private.jsonl"


def lock_file_path(repo_root: Path | None = None) -> Path:
    return project_state_dir(repo_root) / "ahadiff.lock"


__all__ = [
    "PathWarning",
    "audit_log_path",
    "assert_local_repo_path",
    "find_repo_root",
    "global_config_dir",
    "ignore_file_path",
    "inspect_repo_path",
    "lock_file_path",
    "path_identity_key",
    "private_audit_log_path",
    "project_state_dir",
    "repo_config_path",
    "review_db_path",
    "run_dir",
]
