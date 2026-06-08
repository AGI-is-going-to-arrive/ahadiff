from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

import pytest

from ahadiff.core import atomic_replace as atomic_replace_module
from ahadiff.core.atomic_replace import replace_with_retry

if TYPE_CHECKING:
    from pathlib import Path


def test_replace_with_retry_retries_transient_windows_sharing_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.tmp"
    destination = tmp_path / "destination.txt"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")
    original_replace = pathlib.Path.replace
    calls = {"count": 0}

    def flaky_replace(self: pathlib.Path, target: pathlib.Path | str) -> pathlib.Path:
        calls["count"] += 1
        if calls["count"] == 1:
            error = PermissionError("sharing violation")
            error.winerror = 32  # type: ignore[attr-defined]
            raise error
        return original_replace(self, target)

    def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(pathlib.Path, "replace", flaky_replace)
    monkeypatch.setattr(atomic_replace_module.time, "sleep", no_sleep)

    replace_with_retry(source, destination)

    assert calls["count"] == 2
    assert destination.read_text(encoding="utf-8") == "new"
    assert not source.exists()


def test_replace_with_retry_reraises_bare_oserror_winerror_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.tmp"
    destination = tmp_path / "destination.txt"
    source.write_text("new", encoding="utf-8")
    calls = {"replace": 0, "sleep": 0}
    error = OSError("sharing violation")
    error.winerror = 32  # type: ignore[attr-defined]

    def fail_replace(_self: pathlib.Path, _target: pathlib.Path | str) -> pathlib.Path:
        calls["replace"] += 1
        raise error

    def fail_sleep(_seconds: float) -> None:
        calls["sleep"] += 1

    monkeypatch.setattr(pathlib.Path, "replace", fail_replace)
    monkeypatch.setattr(atomic_replace_module.time, "sleep", fail_sleep)

    with pytest.raises(OSError) as captured:
        replace_with_retry(source, destination)

    assert captured.value is error
    assert calls == {"replace": 1, "sleep": 0}
    assert source.read_text(encoding="utf-8") == "new"
    assert not destination.exists()


def test_replace_with_retry_reraises_posix_permission_error_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.tmp"
    destination = tmp_path / "destination.txt"
    source.write_text("new", encoding="utf-8")
    calls = {"replace": 0, "sleep": 0}
    error = PermissionError("posix permission denied")

    def fail_replace(_self: pathlib.Path, _target: pathlib.Path | str) -> pathlib.Path:
        calls["replace"] += 1
        raise error

    def fail_sleep(_seconds: float) -> None:
        calls["sleep"] += 1

    monkeypatch.setattr(pathlib.Path, "replace", fail_replace)
    monkeypatch.setattr(atomic_replace_module.time, "sleep", fail_sleep)

    with pytest.raises(PermissionError) as captured:
        replace_with_retry(source, destination)

    assert captured.value is error
    assert calls == {"replace": 1, "sleep": 0}
    assert source.read_text(encoding="utf-8") == "new"
    assert not destination.exists()
