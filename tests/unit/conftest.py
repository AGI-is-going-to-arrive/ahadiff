from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, cast

import pytest

from ahadiff.core import config as config_module
from ahadiff.core import paths as paths_module
from ahadiff.git import tree_sitter_runtime

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path
    from types import ModuleType

_original_global_config_dir = paths_module.global_config_dir
_original_default_config_dir = _original_global_config_dir()
_unit_config_dir: Path | None = None


def _isolated_global_config_dir(
    *, platform: str | None = None, env: Mapping[str, str] | None = None
) -> Path:
    resolved = _original_global_config_dir(platform=platform, env=env)
    # The loader forwards os.environ itself when callers omit env. Explicit test
    # environments and platforms keep the real path-resolution behavior.
    if (
        _unit_config_dir is not None
        and platform is None
        and (env is None or env is os.environ)
        and resolved == _original_default_config_dir
    ):
        return _unit_config_dir
    return resolved


@pytest.fixture(autouse=True)
def isolate_user_global_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Path:
    target = tmp_path / "global-config"
    # A shared target also covers provider worker threads and aliases imported
    # during a previous test; they must not retain that previous test's directory.
    monkeypatch.setattr(sys.modules[__name__], "_unit_config_dir", target)
    for module in (
        paths_module,
        config_module,
        sys.modules.get("ahadiff.core.registry"),
        sys.modules.get("ahadiff.cli"),
        cast("ModuleType | None", getattr(request, "module", None)),
    ):
        if module is None:
            continue
        current = getattr(module, "global_config_dir", None)
        if current is _original_global_config_dir or current is _isolated_global_config_dir:
            monkeypatch.setattr(module, "global_config_dir", _isolated_global_config_dir)
    return target


@pytest.fixture(autouse=True)
def reset_tree_sitter_runtime_caches() -> Iterator[None]:
    tree_sitter_runtime.reset_caches()
    try:
        yield
    finally:
        tree_sitter_runtime.reset_caches()
