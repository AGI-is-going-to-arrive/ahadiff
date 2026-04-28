from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, cast

import pytest

import ahadiff.install.hooks as hooks_module
from ahadiff.core.errors import InputError
from ahadiff.install.hooks import (
    HookContext,
    build_hook_context,
    load_hooks,
    validate_hooks,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_load_hooks_valid(tmp_path: Path) -> None:
    hooks_data = {"pre_learn": ["echo hello"], "post_learn": ["echo done"]}
    (tmp_path / "hooks.json").write_text(json.dumps(hooks_data), encoding="utf-8")
    result = load_hooks(tmp_path)
    assert result == hooks_data


def test_load_hooks_missing_file(tmp_path: Path) -> None:
    assert load_hooks(tmp_path) == {}


def test_load_hooks_empty_object(tmp_path: Path) -> None:
    (tmp_path / "hooks.json").write_text("{}", encoding="utf-8")
    assert load_hooks(tmp_path) == {}


def test_load_hooks_invalid_json_raises_input_error(tmp_path: Path) -> None:
    (tmp_path / "hooks.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(InputError, match="hooks.json is not valid JSON"):
        load_hooks(tmp_path)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_load_hooks_does_not_follow_hooks_json_symlink(tmp_path: Path) -> None:
    external = tmp_path / "external-hooks.json"
    external.write_text(json.dumps({"pre_learn": ["echo leaked"]}), encoding="utf-8")
    (tmp_path / "hooks.json").symlink_to(external)

    assert load_hooks(tmp_path) == {}


def test_validate_hooks_valid() -> None:
    hooks: dict[str, Any] = {"pre_learn": ["a"], "post_improve": ["b", "c"]}
    result = validate_hooks(hooks)
    assert result == hooks


def test_validate_hooks_rejects_invalid_key() -> None:
    with pytest.raises(InputError, match="Unknown hook name"):
        validate_hooks({"pre_deploy": ["x"]})


def test_validate_hooks_rejects_non_array() -> None:
    with pytest.raises(InputError, match="must be an array"):
        validate_hooks({"pre_learn": "not_a_list"})


def test_validate_hooks_rejects_non_string_items() -> None:
    with pytest.raises(InputError, match="non-string item"):
        validate_hooks({"pre_learn": [123]})


def test_validate_hooks_all_valid_names() -> None:
    hooks: dict[str, Any] = {
        "pre_learn": [],
        "post_learn": [],
        "pre_improve": [],
        "post_improve": [],
        "pre_review": [],
        "post_review": [],
    }
    result = validate_hooks(hooks)
    assert len(result) == 6


def test_hooks_schema_keys_match_valid_names() -> None:
    schema_properties = hooks_module.HOOKS_JSON_SCHEMA["properties"]
    assert isinstance(schema_properties, dict)
    properties = cast("dict[str, object]", schema_properties)
    assert set(properties) == {
        "pre_learn",
        "post_learn",
        "pre_improve",
        "post_improve",
        "pre_review",
        "post_review",
    }


def test_build_hook_context(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "repo" / ".ahadiff"
    ctx = build_hook_context(
        hook_name="pre_learn",
        tool_name="learn",
        repo_path_val=repo,
        state_dir=state,
        run_id="run-001",
    )
    assert isinstance(ctx, HookContext)
    assert ctx.hook_name == "pre_learn"
    assert ctx.tool_name == "learn"
    assert ctx.repo_path == str(repo)
    assert ctx.state_dir == str(state)
    assert ctx.run_id == "run-001"


def test_build_hook_context_no_run_id(tmp_path: Path) -> None:
    ctx = build_hook_context(
        hook_name="post_review",
        tool_name="review",
        repo_path_val=tmp_path,
        state_dir=tmp_path / ".ahadiff",
    )
    assert ctx.run_id is None
