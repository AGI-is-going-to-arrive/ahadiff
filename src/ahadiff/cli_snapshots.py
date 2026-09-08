"""Explicit local learning-baseline commands. They never restore user files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console

from ahadiff.core.errors import AhaDiffError, InputError
from ahadiff.core.learn_inputs import read_learning_file
from ahadiff.core.paths import assert_local_repo_path, find_repo_root, find_workspace_root
from ahadiff.core.snapshots import delete_snapshot, list_snapshots, load_snapshot, save_snapshot
from ahadiff.git.repo import repo_write_lock
from ahadiff.i18n import resolve_locale

snapshot_app = typer.Typer(help="Save, inspect and delete sanitized local learning baselines.")
_console = Console()
_errors = Console(stderr=True)


def _root(value: Path) -> Path:
    try:
        root = find_repo_root(value)
    except InputError:
        root = find_workspace_root(value)
    assert_local_repo_path(root)
    return root


def _fail(error: Exception) -> NoReturn:
    # Validation errors may carry uploaded values; keep them out of the console.
    message = str(error) if isinstance(error, AhaDiffError) else "invalid snapshot operation"
    _errors.print(message, markup=False)
    raise typer.Exit(1) from None


def _json(payload: object) -> None:
    _console.print(json.dumps(payload, ensure_ascii=False, indent=2), markup=False, highlight=False)


@snapshot_app.command("save")
def save_command(
    file: Annotated[Path, typer.Argument(help="One selected UTF-8 text file, at most 256 KiB.")],
    name: Annotated[str, typer.Option("--name", help="Name for this learning baseline.")],
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path(),
    lang: Annotated[str | None, typer.Option("--lang")] = None,
) -> None:
    try:
        root = _root(repo_root)
        source = read_learning_file(root, file)
        with repo_write_lock(root / ".ahadiff" / "ahadiff.lock", command="snapshot save"):
            record = save_snapshot(root, name=name, file=source)
        _json(record.to_summary().model_dump(mode="json"))
        _errors.print(
            "已保存脱敏后的学习基准；这不是原文件备份，原文件未改写。"
            if resolve_locale(cli_lang=lang) == "zh-CN"
            else "Saved a sanitized learning baseline, not a file backup. Source unchanged.",
            markup=False,
        )
    except Exception as error:
        _fail(error)


@snapshot_app.command("list")
def list_command(
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path(),
) -> None:
    try:
        _json([record.model_dump(mode="json") for record in list_snapshots(_root(repo_root))])
    except Exception as error:
        _fail(error)


@snapshot_app.command("show")
def show_command(
    snapshot_id: Annotated[str, typer.Argument(help="Snapshot identifier from snapshot list.")],
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path(),
    expected_hash: Annotated[str | None, typer.Option("--expected-hash")] = None,
) -> None:
    try:
        record = load_snapshot(_root(repo_root), snapshot_id, expected_hash=expected_hash)
        _json(record.model_dump(mode="json"))
    except Exception as error:
        _fail(error)


@snapshot_app.command("delete")
def delete_command(
    snapshot_id: Annotated[str, typer.Argument(help="One snapshot to remove; runs are retained.")],
    expected_hash: Annotated[str, typer.Option("--expected-hash", help="record_hash from list.")],
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path(),
    yes: Annotated[
        bool, typer.Option("--yes", help="Confirm deleting this one saved baseline.")
    ] = False,
    lang: Annotated[str | None, typer.Option("--lang")] = None,
) -> None:
    try:
        root = _root(repo_root)
        if not yes:
            prompt = (
                f"删除快照 {snapshot_id}？原文件与课程保留"
                if resolve_locale(cli_lang=lang) == "zh-CN"
                else f"Delete snapshot {snapshot_id}? Source files and lessons are retained"
            )
            if not typer.confirm(prompt):
                raise typer.Exit(0)
        with repo_write_lock(root / ".ahadiff" / "ahadiff.lock", command="snapshot delete"):
            delete_snapshot(root, snapshot_id, expected_hash=expected_hash)
        _json({"snapshot_id": snapshot_id, "deleted": True})
    except typer.Exit:
        raise
    except Exception as error:
        _fail(error)
