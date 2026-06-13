from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

import portalocker
import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

from ahadiff.core.errors import StorageError
from ahadiff.core.registry import (
    RegistryEntry,
    list_registered_repos,
    load_registry,
    register_repo,
    save_registry,
    unregister_repo,
)


@pytest.fixture()
def registry_dir(tmp_path: Path) -> Path:
    d = tmp_path / "global_config"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def _patch_global_config_dir(registry_dir: Path) -> Generator[None, None, None]:  # pyright: ignore[reportUnusedFunction]
    with patch("ahadiff.core.registry.global_config_dir", return_value=registry_dir):
        yield


def test_load_empty_registry() -> None:
    assert load_registry() == []


def test_save_and_load_roundtrip(registry_dir: Path) -> None:
    entries = [
        RegistryEntry(
            repo_path="/a/b", state_dir="/a/b/.ahadiff", last_seen="2026-01-01T00:00:00+00:00"
        ),
    ]
    save_registry(entries)
    loaded = load_registry()
    assert len(loaded) == 1
    assert loaded[0].repo_path == "/a/b"
    assert loaded[0].state_dir == "/a/b/.ahadiff"


def test_register_and_list_roundtrip(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = repo / ".ahadiff"
    state.mkdir(parents=True)
    register_repo(repo, state)
    entries = list_registered_repos()
    assert len(entries) == 1
    assert entries[0].repo_path == str(repo)


def test_unregister_removes_entry(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = repo / ".ahadiff"
    state.mkdir(parents=True)
    register_repo(repo, state)
    assert len(load_registry()) == 1
    unregister_repo(repo)
    assert len(load_registry()) == 0


def test_stale_entries_filtered(tmp_path: Path) -> None:
    repo_ok = tmp_path / "ok"
    state_ok = repo_ok / ".ahadiff"
    state_ok.mkdir(parents=True)
    repo_stale = tmp_path / "stale"
    state_stale = repo_stale / ".ahadiff"
    register_repo(repo_ok, state_ok)
    register_repo(repo_stale, state_stale)
    raw = load_registry()
    assert len(raw) == 2
    live = list_registered_repos()
    assert len(live) == 1
    assert live[0].repo_path == str(repo_ok)


def test_idempotent_register(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = repo / ".ahadiff"
    state.mkdir(parents=True)
    register_repo(repo, state)
    register_repo(repo, state)
    entries = load_registry()
    assert len(entries) == 1


def test_load_registry_malformed_json(registry_dir: Path) -> None:
    (registry_dir / "registry.json").write_text("{bad", encoding="utf-8")
    assert load_registry() == []


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_load_registry_does_not_follow_registry_json_symlink(registry_dir: Path) -> None:
    external = registry_dir / "external-registry.json"
    external.write_text(
        '[{"repo_path": "/outside", "state_dir": "/outside/.ahadiff",'
        ' "last_seen": "2026-01-01T00:00:00+00:00"}]',
        encoding="utf-8",
    )
    (registry_dir / "registry.json").symlink_to(external)

    assert load_registry() == []


def test_register_canonicalizes_repo_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = repo / ".ahadiff"
    state.mkdir(parents=True)
    alias = repo.parent / "alias" / ".." / repo.name

    register_repo(repo, state)
    register_repo(alias, state)

    entries = load_registry()
    assert len(entries) == 1
    assert entries[0].repo_path == os.path.normcase(str(repo.resolve()))


def test_load_registry_non_list(registry_dir: Path) -> None:
    (registry_dir / "registry.json").write_text('{"a": 1}', encoding="utf-8")
    assert load_registry() == []


def test_unregister_nonexistent_is_noop(tmp_path: Path) -> None:
    unregister_repo(tmp_path / "nonexistent")
    assert load_registry() == []


def test_register_repo_wraps_oserror_as_storage_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    state = repo / ".ahadiff"
    state.mkdir(parents=True)

    @contextmanager
    def broken_lock() -> Generator[None, None, None]:
        raise PermissionError("read-only registry")
        yield

    monkeypatch.setattr("ahadiff.core.registry._registry_lock", broken_lock)

    with pytest.raises(StorageError, match="failed to update repo registry"):
        register_repo(repo, state)


def test_register_repo_lock_contention_becomes_storage_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    state = repo / ".ahadiff"
    state.mkdir(parents=True)
    lock_flags: list[int] = []

    def busy_lock(_handle: object, flags: int) -> None:
        lock_flags.append(flags)
        if flags & portalocker.LOCK_NB:
            raise portalocker.AlreadyLocked()
        raise AssertionError("registry lock must be acquired with LOCK_NB")

    monkeypatch.setattr("ahadiff.core.registry.portalocker.lock", busy_lock)

    with pytest.raises(StorageError, match="failed to update repo registry"):
        register_repo(repo, state)

    assert lock_flags
    assert all(flags & portalocker.LOCK_NB for flags in lock_flags)
