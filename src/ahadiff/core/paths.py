from __future__ import annotations

import collections.abc as _collections_abc
import errno
import os
import re
import stat
import sys
import tempfile
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import InputError, StorageError

if TYPE_CHECKING:
    from collections.abc import Mapping
else:
    Mapping = _collections_abc.Mapping

_MACOS_LONG_PATH_WARNING = 180
_WINDOWS_LONG_PATH_WARNING = 240
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_STATE_GITIGNORE_TEXT = (
    "# AhaDiff local secrets & private state — auto-generated; do not commit secrets\n"
    ".env\n"
    ".env.*\n"
    "audit.private.jsonl\n"
    "*.lock\n"
    "*.log\n"
)
_STATE_GITIGNORE_PATTERNS = (".env", ".env.*", "audit.private.jsonl", "*.lock", "*.log")
_GLOBAL_CONFIG_GITIGNORE_TEXT = (
    "# AhaDiff global provider secrets — auto-generated; do not commit secrets\n.env\n.env.*\n"
)
_GLOBAL_CONFIG_GITIGNORE_PATTERNS = (".env", ".env.*")
_WINDOWS_RESERVED_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


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


def is_wsl2_mnt(
    path: Path,
    *,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    current_platform = _platform_name(platform)
    if not current_platform.startswith("linux"):
        return False
    normalized = _normalized_path_text(path)
    if not normalized.startswith("/mnt/") or normalized == "/mnt/":
        return False
    mount_name = normalized.removeprefix("/mnt/").split("/", 1)[0]
    if len(mount_name) != 1 or not ("a" <= mount_name <= "z"):
        return False
    env_map = os.environ if env is None else env
    return bool(
        env_map.get("WSL_DISTRO_NAME")
        or env_map.get("WSL_INTEROP")
        or env_map.get("WSL2_GUI_APPS_ENABLED")
    )


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


def workspace_identity_key(path: Path, *, platform: str | None = None) -> str:
    normalized = _normalized_path_text(path)
    current_platform = _platform_name(platform)
    if current_platform.startswith("win"):
        normalized = normalized.casefold()
    return f"workspace:v1:{normalized}"


def workspace_identity_lookup_keys(path: Path, *, platform: str | None = None) -> tuple[str, str]:
    return workspace_identity_key(path, platform=platform), path_identity_key(path)


def validate_run_id(run_id: str) -> None:
    if not _RUN_ID_RE.fullmatch(run_id) or run_id in {".", ".."}:
        raise InputError(
            "run_id must contain only letters, numbers, dot, underscore, or hyphen, "
            "and must not be '.' or '..'"
        )
    if _is_windows_reserved_device_name(run_id):
        raise InputError("run_id must not be a Windows reserved device name")


def _is_windows_reserved_device_name(value: str) -> bool:
    stem = value.split(".", 1)[0]
    return stem.upper() in _WINDOWS_RESERVED_DEVICE_NAMES


def find_repo_root(start: Path | None = None) -> Path:
    cursor = (Path.cwd() if start is None else start).expanduser()
    if cursor.is_file():
        cursor = cursor.parent
    cursor = cursor.resolve()
    for candidate in (cursor, *cursor.parents):
        if (candidate / ".git").exists():
            return candidate
    raise InputError(f"{cursor} is not inside a git repository")


def find_workspace_root(start: Path | None = None) -> Path:
    cursor = (Path.cwd() if start is None else start).expanduser()
    if cursor.is_file():
        cursor = cursor.parent
    cursor = cursor.resolve()
    for candidate in (cursor, *cursor.parents):
        state_dir = candidate / ".ahadiff"
        if state_dir.exists() or (state_dir / "config.toml").exists():
            return candidate
    return cursor


def global_config_dir(*, platform: str | None = None, env: Mapping[str, str] | None = None) -> Path:
    current_platform = _platform_name(platform)
    env_map = os.environ if env is None else env
    if current_platform.startswith("win"):
        # Windows must not require HOME — APPDATA is the documented anchor.
        appdata = env_map.get("APPDATA")
        if not appdata:
            raise StorageError("APPDATA is not set; cannot resolve global config directory")
        return Path(appdata) / "ahadiff"
    home = _home_dir(env_map)
    if current_platform == "darwin":
        return home / "Library" / "Application Support" / "ahadiff"
    xdg_config_home = env_map.get("XDG_CONFIG_HOME")
    base_dir = Path(xdg_config_home) if xdg_config_home else home / ".config"
    return base_dir / "ahadiff"


def project_state_dir(repo_root: Path | None = None) -> Path:
    root = find_repo_root(repo_root)
    assert_local_repo_path(root)
    return validate_state_dir_path(root / ".ahadiff")


def validate_state_dir_path(state_dir: Path) -> Path:
    try:
        state_stat = state_dir.lstat()
    except FileNotFoundError:
        return state_dir
    except OSError as exc:
        raise StorageError(f"state dir is unreadable: {state_dir}") from exc
    if stat.S_ISLNK(state_stat.st_mode):
        raise InputError("state dir must not be a symlink")
    if _has_windows_reparse_point(state_stat):
        raise InputError("state dir must not be a Windows reparse point or junction")
    if not stat.S_ISDIR(state_stat.st_mode):
        raise InputError("state dir must be a directory")
    return state_dir


def validate_state_path_no_symlinks(path: Path, *, allow_missing_leaf: bool = True) -> Path:
    absolute_path = path if path.is_absolute() else path.absolute()
    anchor = absolute_path.anchor
    if not anchor:
        raise InputError("state path must be absolute")
    cursor = Path(anchor)
    parts = absolute_path.parts[1:]
    for index, part in enumerate(parts):
        cursor = cursor / part
        is_leaf = index == len(parts) - 1
        try:
            path_stat = cursor.lstat()
        except FileNotFoundError:
            if allow_missing_leaf or not is_leaf:
                return path
            raise InputError(f"state path does not exist: {path}") from None
        except OSError as exc:
            raise StorageError(f"state path is unreadable: {cursor}") from exc
        if stat.S_ISLNK(path_stat.st_mode):
            raise InputError("state path must not contain symlinks")
        if _has_windows_reparse_point(path_stat):
            raise InputError("state path must not contain Windows reparse points or junctions")
        if not is_leaf and not stat.S_ISDIR(path_stat.st_mode):
            raise InputError("state path parent must be a directory")
    return path


def ensure_state_parent_dir(path: Path) -> Path:
    parent = path.parent
    validate_state_path_no_symlinks(parent, allow_missing_leaf=True)
    parent.mkdir(parents=True, exist_ok=True)
    validate_state_path_no_symlinks(parent, allow_missing_leaf=False)
    state_dir = _state_dir_ancestor(parent)
    if state_dir is not None:
        ensure_state_gitignore(state_dir)
    return parent


def _state_dir_ancestor(path: Path) -> Path | None:
    return next(
        (candidate for candidate in (path, *path.parents) if candidate.name == ".ahadiff"),
        None,
    )


def ensure_state_gitignore(state_dir: Path) -> Path:
    validate_state_dir_path(state_dir)
    gitignore_path = state_dir / ".gitignore"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(gitignore_path), flags, 0o644)
    except FileExistsError:
        _ensure_existing_state_gitignore_patterns(gitignore_path)
        return gitignore_path
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            _ensure_existing_state_gitignore_patterns(gitignore_path)
            return gitignore_path
        raise StorageError(f"failed to create state gitignore: {gitignore_path}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(_STATE_GITIGNORE_TEXT)
    finally:
        if fd != -1:
            os.close(fd)
    return gitignore_path


def ensure_global_config_gitignore(config_dir: Path) -> Path:
    validate_state_dir_path(config_dir)
    gitignore_path = config_dir / ".gitignore"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(gitignore_path), flags, 0o644)
    except FileExistsError:
        _ensure_existing_state_gitignore_patterns(
            gitignore_path,
            patterns=_GLOBAL_CONFIG_GITIGNORE_PATTERNS,
        )
        return gitignore_path
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            _ensure_existing_state_gitignore_patterns(
                gitignore_path,
                patterns=_GLOBAL_CONFIG_GITIGNORE_PATTERNS,
            )
            return gitignore_path
        raise StorageError(f"failed to create global config gitignore: {gitignore_path}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(_GLOBAL_CONFIG_GITIGNORE_TEXT)
    finally:
        if fd != -1:
            os.close(fd)
    return gitignore_path


def _ensure_existing_state_gitignore_patterns(
    gitignore_path: Path,
    *,
    patterns: tuple[str, ...] = _STATE_GITIGNORE_PATTERNS,
) -> None:
    expected_stat = _existing_state_gitignore_regular_stat(gitignore_path)
    if expected_stat is None:
        return
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(gitignore_path), flags)
    except OSError:
        return
    try:
        path_stat = os.fstat(fd)
        if not _state_gitignore_stat_is_safe(path_stat):
            return
        if (path_stat.st_dev, path_stat.st_ino) != (
            expected_stat.st_dev,
            expected_stat.st_ino,
        ):
            return
        try:
            raw_text = os.read(fd, max(path_stat.st_size, 0))
        except OSError:
            return
        try:
            text = raw_text.decode("utf-8")
        except UnicodeDecodeError:
            return
        existing_lines = set(text.splitlines())
        missing = [line for line in patterns if line not in existing_lines]
        if not missing:
            return
        prefix = "" if not text or text.endswith("\n") else "\n"
        append_text = prefix + "\n".join(missing) + "\n"
        os.lseek(fd, 0, os.SEEK_END)
        os.write(fd, append_text.encode("utf-8"))
    finally:
        os.close(fd)


def _existing_state_gitignore_regular_stat(gitignore_path: Path) -> os.stat_result | None:
    try:
        path_stat = reject_leaf_symlink_or_reparse(gitignore_path, label="state gitignore")
    except (InputError, StorageError):
        return None
    if not _state_gitignore_stat_is_safe(path_stat):
        return None
    return path_stat


def _state_gitignore_stat_is_safe(path_stat: os.stat_result) -> bool:
    return (
        stat.S_ISREG(path_stat.st_mode)
        and not _has_windows_reparse_point(path_stat)
        and getattr(path_stat, "st_nlink", 1) == 1
    )


def atomic_write_state_text(path: Path, text: str) -> None:
    ensure_state_parent_dir(path)
    validate_state_path_no_symlinks(path, allow_missing_leaf=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            validate_state_path_no_symlinks(tmp_path, allow_missing_leaf=True)
            tmp_file.write(text)
        validate_state_path_no_symlinks(path, allow_missing_leaf=True)
        tmp_path.replace(path)
        validate_state_path_no_symlinks(path, allow_missing_leaf=False)
    except Exception:
        if tmp_path is not None:
            with suppress(OSError):
                tmp_path.unlink(missing_ok=True)
        raise


def _has_windows_reparse_point(path_stat: object) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def reject_leaf_symlink_or_reparse(path: Path, *, label: str = "file") -> os.stat_result:
    """lstat a leaf path and reject symlinks / Windows reparse points."""
    try:
        leaf_stat = path.lstat()
    except FileNotFoundError:
        raise InputError(f"{label} does not exist: {path}") from None
    except OSError as exc:
        raise StorageError(f"{label} is unreadable: {path}") from exc
    if stat.S_ISLNK(leaf_stat.st_mode):
        raise InputError(f"{label} must not be a symlink")
    if _has_windows_reparse_point(leaf_stat):
        raise InputError(f"{label} must not be a Windows reparse point or junction")
    return leaf_stat


def repo_config_path(repo_root: Path | None = None) -> Path:
    return project_state_dir(repo_root) / "config.toml"


def ignore_file_path(repo_root: Path | None = None) -> Path:
    root = find_repo_root(repo_root)
    return root / ".ahadiffignore"


def run_dir(run_id: str, repo_root: Path | None = None) -> Path:
    validate_run_id(run_id)
    return project_state_dir(repo_root) / "runs" / run_id


def review_db_path(repo_root: Path | None = None) -> Path:
    return project_state_dir(repo_root) / "review.sqlite"


def usage_db_path(*, platform: str | None = None, env: Mapping[str, str] | None = None) -> Path:
    return global_config_dir(platform=platform, env=env) / "usage.sqlite"


def audit_log_path(repo_root: Path | None = None) -> Path:
    return project_state_dir(repo_root) / "audit.jsonl"


def private_audit_log_path(repo_root: Path | None = None) -> Path:
    return project_state_dir(repo_root) / "audit.private.jsonl"


def lock_file_path(repo_root: Path | None = None) -> Path:
    return project_state_dir(repo_root) / "ahadiff.lock"


__all__ = [
    "PathWarning",
    "atomic_write_state_text",
    "audit_log_path",
    "ensure_global_config_gitignore",
    "ensure_state_gitignore",
    "ensure_state_parent_dir",
    "assert_local_repo_path",
    "find_repo_root",
    "find_workspace_root",
    "global_config_dir",
    "ignore_file_path",
    "inspect_repo_path",
    "is_wsl2_mnt",
    "lock_file_path",
    "path_identity_key",
    "private_audit_log_path",
    "project_state_dir",
    "reject_leaf_symlink_or_reparse",
    "repo_config_path",
    "review_db_path",
    "run_dir",
    "usage_db_path",
    "validate_state_path_no_symlinks",
    "validate_state_dir_path",
    "workspace_identity_key",
    "workspace_identity_lookup_keys",
]
