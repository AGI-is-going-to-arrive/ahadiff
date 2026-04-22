from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from rich.console import Console
from rich.table import Table
from typer import Exit

from . import __version__
from .core.config import DEFAULT_CONFIG, iter_resolved_settings, load_config, write_default_config
from .core.errors import AhaDiffError
from .core.paths import (
    find_repo_root,
    global_config_dir,
    inspect_repo_path,
    lock_file_path,
    project_state_dir,
    repo_config_path,
    review_db_path,
)
from .git.capture import (
    capture_patch,
    detect_graphify_status,
    import_graphify_artifact,
    write_input_artifacts,
)
from .git.repo import repo_write_lock, unlock_repo_write_lock

console = Console()
error_console = Console(stderr=True)
_APP = typer.Typer(
    help="AhaDiff local-first verified diff learning CLI.",
    invoke_without_command=True,
    no_args_is_help=False,
)
_CONFIG_APP = typer.Typer(help="Inspect configuration and precedence.")
_GRAPH_APP = typer.Typer(help="Inspect Graphify source and imported artifacts.")
_APP.add_typer(_CONFIG_APP, name="config")
_APP.add_typer(_GRAPH_APP, name="graph")
_SQLITE_MIN_VERSION = (3, 51, 3)
_SQLITE_ALLOWED_BACKPORTS = {(3, 50, 7), (3, 44, 6)}


def app() -> typer.Typer:
    return _APP


def _cli_overrides(
    *,
    lang: str | None = None,
    privacy_mode: str | None = None,
    generate_model: str | None = None,
    judge_model: str | None = None,
    serve_port: int | None = None,
    no_browser: bool | None = None,
) -> dict[str, Any]:
    return {
        "lang": lang,
        "privacy_mode": privacy_mode,
        "llm.generate_model": generate_model,
        "llm.judge_model": judge_model,
        "serve.port": serve_port,
        "serve.no_browser": no_browser,
    }


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        rendered = ", ".join(str(item) for item in cast("tuple[Any, ...]", value))
        return f"[{rendered}]"
    return str(value)


def _sqlite_version_tuple() -> tuple[int, int, int]:
    parts = sqlite3.sqlite_version.split(".")
    major, minor, patch = (int(part) for part in parts[:3])
    return major, minor, patch


def _sqlite_gate_ok(version: tuple[int, int, int]) -> bool:
    return version >= _SQLITE_MIN_VERSION or version in _SQLITE_ALLOWED_BACKPORTS


def _handle_cli_error(error: Exception) -> None:
    if isinstance(error, AhaDiffError):
        error_console.print(f"[red]Error:[/red] {error}")
        raise Exit(code=1) from error
    error_console.print(f"[red]Unexpected error:[/red] {error}")
    raise Exit(code=2) from error


def _resolve_learn_workspace_root(
    repo_root: Path,
    *,
    allow_non_git: bool,
) -> tuple[Path, bool]:
    try:
        return find_repo_root(repo_root), True
    except AhaDiffError:
        if not allow_non_git:
            raise
        root = repo_root.expanduser()
        if root.is_file():
            root = root.parent
        return root.resolve(), False


@_APP.callback()
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show the installed AhaDiff version."),
) -> None:
    if version:
        console.print(f"ahadiff {__version__}")
        raise Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise Exit()


@_APP.command("init")
def init_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing repo config."),
    ] = False,
) -> None:
    try:
        root = find_repo_root(repo_root)
        state_dir = project_state_dir(root)
        created_paths: list[Path] = []
        for target in (state_dir, state_dir / "runs", state_dir / "graphify"):
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                created_paths.append(target)

        config_path = repo_config_path(root)
        existed = config_path.exists()
        write_default_config(config_path, overwrite=force)
        if force or not existed:
            created_paths.append(config_path)

        console.print(f"[green]Initialized[/green] {state_dir}")
        for created_path in created_paths:
            console.print(f"  - {created_path.relative_to(root)}")
        if existed and not force:
            console.print("  - config.toml already existed; kept current contents")
        console.print(f"Global config directory: {global_config_dir()}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_APP.command("doctor")
def doctor_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    deep: Annotated[
        bool,
        typer.Option("--deep", help="Run extra SQLite checks when review.sqlite exists."),
    ] = False,
) -> None:
    try:
        root = find_repo_root(repo_root)
        snapshot = load_config(root)
        sqlite_gate_ok = True

        console.print(f"[bold]Repo root[/bold]: {root}")
        console.print(f"[bold]State dir[/bold]: {project_state_dir(root)}")
        console.print(f"[bold]Repo config[/bold]: {snapshot.repo_config_path}")
        console.print(f"[bold]Global config[/bold]: {snapshot.global_config_path}")
        console.print(f"[bold]SQLite runtime[/bold]: {sqlite3.sqlite_version} ({sqlite3.__file__})")
        sqlite_version = _sqlite_version_tuple()
        sqlite_gate_ok = _sqlite_gate_ok(sqlite_version)
        if sqlite_gate_ok:
            console.print("[green]SQLite gate[/green]: compatible with the frozen contract")
        else:
            minimum = ".".join(str(part) for part in _SQLITE_MIN_VERSION)
            backports = ", ".join(
                ".".join(str(part) for part in item) for item in sorted(_SQLITE_ALLOWED_BACKPORTS)
            )
            console.print(
                "[red]SQLite gate[/red]: "
                f"{sqlite3.sqlite_version} is below {minimum}; allowed backports are {backports}"
            )

        warnings = inspect_repo_path(root)
        if warnings:
            console.print("[yellow]Path warnings[/yellow]:")
            for warning in warnings:
                console.print(f"  - {warning.code}: {warning.message}")
        else:
            console.print("[green]Path warnings[/green]: none")

        if snapshot.precedence_conflicts:
            console.print("[yellow]Precedence conflicts[/yellow]:")
            for conflict in snapshot.precedence_conflicts:
                shadowed = ", ".join(conflict.shadowed)
                console.print(f"  - {conflict.key}: winner={conflict.winner}; shadowed={shadowed}")
        else:
            console.print("[green]Precedence conflicts[/green]: none")

        if snapshot.repo_unknown_keys:
            console.print("[yellow]Unknown repo keys[/yellow]:")
            for key in snapshot.repo_unknown_keys:
                console.print(f"  - {key}")
        else:
            console.print("[green]Unknown repo keys[/green]: none")

        if snapshot.global_unknown_keys:
            console.print("[yellow]Unknown global keys[/yellow]:")
            for key in snapshot.global_unknown_keys:
                console.print(f"  - {key}")
        else:
            console.print("[green]Unknown global keys[/green]: none")

        if snapshot.repo_sensitive_keys:
            console.print("[red]Sensitive repo config keys[/red]:")
            for key in snapshot.repo_sensitive_keys:
                console.print(f"  - {key}")
        else:
            console.print("[green]Sensitive repo config keys[/green]: none")

        review_path = review_db_path(root)
        if review_path.exists():
            try:
                with sqlite3.connect(review_path) as connection:
                    quick_check = connection.execute("PRAGMA quick_check").fetchone()
                    quick_check_value = quick_check[0] if quick_check else "unknown"
                    console.print(f"[bold]SQLite quick_check[/bold]: {quick_check_value}")
                    if deep:
                        integrity = connection.execute("PRAGMA integrity_check").fetchone()
                        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                        integrity_value = integrity[0] if integrity else "unknown"
                        console.print(f"[bold]SQLite integrity_check[/bold]: {integrity_value}")
                        foreign_key_count = len(foreign_keys)
                        console.print(
                            f"[bold]SQLite foreign_key_check[/bold]: {foreign_key_count} issue(s)"
                        )
            except sqlite3.DatabaseError as error:
                raise AhaDiffError(
                    f"review.sqlite is not a valid SQLite database: {review_path} ({error})"
                ) from error
        else:
            console.print("[bold]review.sqlite[/bold]: not initialized yet")
            if deep:
                console.print("Deep SQLite checks skipped because review.sqlite does not exist yet")
        if not sqlite_gate_ok:
            raise AhaDiffError(
                f"SQLite runtime {sqlite3.sqlite_version} does not satisfy the frozen doctor gate"
            )
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_APP.command("learn")
def learn_cmd(
    revision: Annotated[
        str | None,
        typer.Argument(help="Commit range such as HEAD~1..HEAD, or a single commit sha."),
    ] = None,
    last: Annotated[bool, typer.Option("--last", help="Capture the last commit.")] = False,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help='Capture a first-parent ancestry window such as "2 hours ago".',
        ),
    ] = None,
    author: Annotated[
        str | None,
        typer.Option(
            "--author",
            help="Optional git --author regex filter for --since windows.",
        ),
    ] = None,
    staged: Annotated[bool, typer.Option("--staged", help="Capture staged changes.")] = False,
    unstaged: Annotated[bool, typer.Option("--unstaged", help="Capture unstaged changes.")] = False,
    include_untracked: Annotated[
        bool,
        typer.Option("--include-untracked", help="Include untracked files in worktree capture."),
    ] = False,
    patch: Annotated[
        str | None,
        typer.Option("--patch", help="Read a unified diff from FILE or '-' for stdin."),
    ] = None,
    compare: Annotated[
        tuple[Path, Path] | None,
        typer.Option("--compare", help="Compare two files with unified diff semantics."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Only capture diff artifacts; do not run downstream stages.",
        ),
    ] = False,
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    privacy_mode: Annotated[
        str | None,
        typer.Option("--privacy-mode", help="Temporary CLI override."),
    ] = None,
    use_graphify: Annotated[
        bool | None,
        typer.Option(
            "--use-graphify/--no-graphify",
            help="Force Graphify on or off for this run.",
        ),
    ] = None,
) -> None:
    try:
        if not dry_run:
            raise AhaDiffError(
                "Stage 2 / Task 5 currently supports capture-only flow; use --dry-run"
            )
        allow_non_git = patch is not None or compare is not None
        root, has_git_repo = _resolve_learn_workspace_root(
            repo_root,
            allow_non_git=allow_non_git,
        )
        if has_git_repo:
            snapshot = load_config(root, cli_overrides=_cli_overrides(privacy_mode=privacy_mode))
            capture_config = cast("dict[str, Any]", snapshot.values["capture"])
            effective_privacy_mode = str(snapshot.values["privacy_mode"])
            repo_lock_path = lock_file_path(root)
        else:
            capture_config = cast("dict[str, Any]", DEFAULT_CONFIG["capture"])
            effective_privacy_mode = privacy_mode or str(DEFAULT_CONFIG["privacy_mode"])
            repo_lock_path = root / ".ahadiff" / "ahadiff.lock"

        with repo_write_lock(repo_lock_path, command="learn") as _:
            capture = capture_patch(
                workspace_root=root,
                revision=revision,
                last=last,
                since=since,
                author=author,
                staged=staged,
                unstaged=unstaged,
                include_untracked=include_untracked,
                patch=patch,
                compare=compare,
                use_graphify=use_graphify,
                max_files=int(capture_config["max_files"]),
                hard_limit=int(capture_config["hard_limit"]),
                max_patch_bytes=int(capture_config["max_patch_bytes"]),
                privacy_mode=effective_privacy_mode,
            )
            patch_path, metadata_path = write_input_artifacts(capture)

        console.print(f"[green]Captured[/green] {capture.run_source.source_kind}")
        console.print(f"[bold]Run ID[/bold]: {capture.run_id}")
        console.print(f"[bold]Patch[/bold]: {patch_path}")
        console.print(f"[bold]Metadata[/bold]: {metadata_path}")
        console.print(f"[bold]Source ref[/bold]: {capture.run_source.source_ref}")
        console.print(f"[bold]Capability level[/bold]: {capture.run_source.capability_level}")
        if capture.run_source.degraded_flags:
            console.print(f"[yellow]Degraded flags[/yellow]: {capture.run_source.degraded_flags}")
        else:
            console.print("[green]Degraded flags[/green]: none")
        if capture.graphify_status.has_graph:
            console.print(
                f"[bold]Graphify[/bold]: detected at {capture.graphify_status.source_path}"
            )
        else:
            console.print("[bold]Graphify[/bold]: not detected")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_APP.command("unlock")
def unlock_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    force: Annotated[
        bool,
        typer.Option("--force", help="Remove the repo write lock file."),
    ] = False,
) -> None:
    try:
        if not force:
            raise AhaDiffError("unlock requires --force")
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        lock_path = lock_file_path(root) if has_git_repo else root / ".ahadiff" / "ahadiff.lock"
        removed = unlock_repo_write_lock(lock_path)
        if removed:
            console.print("[green]Removed[/green] repo write lock")
        else:
            console.print("No repo write lock was present")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_CONFIG_APP.command("show")
def config_show_cmd(
    resolved: Annotated[
        bool,
        typer.Option("--resolved", help="Show the source layer for every value."),
    ] = False,
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Temporary CLI override for language."),
    ] = None,
    privacy_mode: Annotated[
        str | None,
        typer.Option("--privacy-mode", help="Temporary CLI override."),
    ] = None,
    generate_model: Annotated[
        str | None,
        typer.Option("--generate-model", help="Temporary CLI override for llm.generate_model."),
    ] = None,
    judge_model: Annotated[
        str | None,
        typer.Option("--judge-model", help="Temporary CLI override for llm.judge_model."),
    ] = None,
    serve_port: Annotated[
        int | None,
        typer.Option("--serve-port", help="Temporary CLI override for serve.port."),
    ] = None,
    browser: Annotated[
        bool | None,
        typer.Option(
            "--browser/--no-browser",
            help="Temporary CLI override for browser opening behavior.",
        ),
    ] = None,
) -> None:
    try:
        no_browser = None if browser is None else not browser
        snapshot = load_config(
            repo_root,
            cli_overrides=_cli_overrides(
                lang=lang,
                privacy_mode=privacy_mode,
                generate_model=generate_model,
                judge_model=judge_model,
                serve_port=serve_port,
                no_browser=no_browser,
            ),
        )
        if resolved:
            table = Table(title="Resolved config")
            table.add_column("Key", style="cyan")
            table.add_column("Value", style="magenta")
            table.add_column("Source", style="green")
            for setting in iter_resolved_settings(snapshot):
                table.add_row(setting.key, _format_scalar(setting.value), setting.source)
            console.print(table)
            return

        for setting in iter_resolved_settings(snapshot):
            console.print(f"{setting.key} = {_format_scalar(setting.value)}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_GRAPH_APP.command("status")
def graph_status_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
) -> None:
    try:
        root = find_repo_root(repo_root)
        status = detect_graphify_status(root, use_graphify=None)
        console.print(f"[bold]Source[/bold]: {status.source_path}")
        console.print(f"[bold]Imported[/bold]: {status.imported_path}")
        console.print(f"[bold]Source exists[/bold]: {status.source_exists}")
        console.print(f"[bold]Imported exists[/bold]: {status.imported_exists}")
        console.print(f"[bold]Has graph[/bold]: {status.has_graph}")
        if status.freshness is not None:
            console.print(f"[bold]Freshness[/bold]: {status.freshness}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_GRAPH_APP.command("import")
def graph_import_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing imported graph artifact."),
    ] = False,
) -> None:
    try:
        root = find_repo_root(repo_root)
        with repo_write_lock(lock_file_path(root), command="graph import") as _:
            status = import_graphify_artifact(root, force=force)
        console.print(f"[green]Imported[/green] {status.imported_path}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_GRAPH_APP.command("refresh")
def graph_refresh_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
) -> None:
    try:
        root = find_repo_root(repo_root)
        with repo_write_lock(lock_file_path(root), command="graph refresh") as _:
            status = import_graphify_artifact(root, force=True)
        console.print(f"[green]Refreshed[/green] {status.imported_path}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


def main() -> None:
    app()()


__all__ = [
    "app",
    "config_show_cmd",
    "doctor_cmd",
    "graph_import_cmd",
    "graph_refresh_cmd",
    "graph_status_cmd",
    "init_cmd",
    "learn_cmd",
    "main",
    "unlock_cmd",
]
