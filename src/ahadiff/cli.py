from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

import typer
from rich.console import Console
from rich.table import Table
from typer import Exit

from . import __version__
from .core.config import (
    iter_resolved_settings,
    load_config,
    load_security_config,
    load_workspace_config,
    load_workspace_security_config,
    write_default_config,
)
from .core.errors import AhaDiffError
from .core.paths import (
    find_repo_root,
    find_workspace_root,
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
from .llm import probe_provider
from .llm.provider import transport_target_for_base_url

if TYPE_CHECKING:
    from .contracts import PrivacyMode

console = Console()
error_console = Console(stderr=True)
_APP = typer.Typer(
    help="AhaDiff local-first verified diff learning CLI.",
    invoke_without_command=True,
    no_args_is_help=False,
)
_CONFIG_APP = typer.Typer(help="Inspect configuration and precedence.")
_GRAPH_APP = typer.Typer(help="Inspect Graphify source and imported artifacts.")
_MAINT_APP = typer.Typer(help="Mutating maintenance tasks kept separate from doctor diagnostics.")
_PROVIDER_APP = typer.Typer(help="Probe and persist LLM provider capabilities.")
_APP.add_typer(_CONFIG_APP, name="config")
_APP.add_typer(_GRAPH_APP, name="graph")
_APP.add_typer(_MAINT_APP, name="maint")
_APP.add_typer(_PROVIDER_APP, name="provider")
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


def _state_dir_and_lock_path(repo_root: Path) -> tuple[Path, Path]:
    root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
    if has_git_repo:
        return project_state_dir(root), lock_file_path(root)
    state_dir = root / ".ahadiff"
    return state_dir, state_dir / "ahadiff.lock"


def _iter_orphan_state_paths(state_dir: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    runs_dir = state_dir / "runs"
    if runs_dir.exists():
        candidates.extend(
            path
            for path in runs_dir.iterdir()
            if path.name.endswith(".tmp") and (path.is_dir() or path.is_file())
        )
    candidates.extend(sorted(state_dir.glob("audit*.jsonl.gz.tmp")))
    return tuple(sorted(candidates))


def _remove_state_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink(missing_ok=True)


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
        return find_workspace_root(repo_root), False


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


@_MAINT_APP.command("clean-orphans")
def maint_clean_orphans_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report orphaned state artifacts without removing them."),
    ] = False,
) -> None:
    try:
        state_dir, lock_path = _state_dir_and_lock_path(repo_root)
        if not state_dir.exists():
            console.print("[green]State dir[/green]: not initialized; nothing to clean")
            return

        with repo_write_lock(lock_path, command="maint clean-orphans") as _:
            orphan_paths = _iter_orphan_state_paths(state_dir)
            if not orphan_paths:
                console.print("[green]Clean[/green]: no orphaned state artifacts found")
                return

            action = "Would remove" if dry_run else "Removed"
            console.print(
                f"[yellow]{action}[/yellow] {len(orphan_paths)} orphaned state artifact(s)"
            )
            for orphan_path in orphan_paths:
                console.print(f"  - {orphan_path.relative_to(state_dir.parent)}")
                if not dry_run:
                    _remove_state_path(orphan_path)
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
        snapshot = (
            load_config(root, cli_overrides=_cli_overrides(privacy_mode=privacy_mode))
            if has_git_repo
            else load_workspace_config(
                root,
                cli_overrides=_cli_overrides(privacy_mode=privacy_mode),
            )
        )
        capture_config = cast("dict[str, Any]", snapshot.values["capture"])
        effective_privacy_mode = str(snapshot.values["privacy_mode"])
        repo_lock_path = (
            lock_file_path(root) if has_git_repo else root / ".ahadiff" / "ahadiff.lock"
        )

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


@_PROVIDER_APP.command("test")
def provider_test_cmd(
    name: Annotated[
        str,
        typer.Option("--name", help="Provider alias persisted under [providers.<name>]."),
    ],
    base_url: Annotated[
        str,
        typer.Option("--base-url", help="Provider API base URL."),
    ],
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            help="Deprecated: avoid plaintext CLI keys; prefer --api-key-env or hidden prompt.",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model name to probe; defaults to llm.generate_model."),
    ] = None,
    provider_class: Annotated[
        str,
        typer.Option("--provider-class", help="Frozen provider class."),
    ] = "openai",
    api_key_env: Annotated[
        str,
        typer.Option(
            "--api-key-env",
            help="Env var name persisted into config.toml instead of the raw key.",
        ),
    ] = "AHADIFF_PROVIDER_API_KEY",
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    privacy_mode: Annotated[
        str | None,
        typer.Option("--privacy-mode", help="Temporary CLI override."),
    ] = None,
    ) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        snapshot = (
            load_config(root, cli_overrides=_cli_overrides(privacy_mode=privacy_mode))
            if has_git_repo
            else load_workspace_config(
                root,
                cli_overrides=_cli_overrides(privacy_mode=privacy_mode),
            )
        )
        security_config = (
            load_security_config(root) if has_git_repo else load_workspace_security_config(root)
        )
        llm_config = cast("dict[str, Any]", snapshot.values["llm"])
        provider_limits = cast("dict[str, Any]", snapshot.values["provider"])
        resolved_model = model or str(llm_config["generate_model"])
        resolved_privacy_mode = cast("PrivacyMode", str(snapshot.values["privacy_mode"]))
        transport_target = transport_target_for_base_url(
            base_url,
            local_hosts=security_config.local_hosts,
        )
        if (
            privacy_mode is None
            and resolved_privacy_mode == "strict_local"
            and transport_target == "remote"
        ):
            # Invoking a remote provider probe is itself an explicit remote action.
            resolved_privacy_mode = "explicit_remote"
        if "." in name:
            raise AhaDiffError("--name must not contain '.' because it becomes a TOML table path")
        if api_key is not None:
            raise AhaDiffError(
                "Passing raw API keys on the command line is not allowed; use --api-key-env "
                "or interactive hidden input instead"
            )
        effective_api_key = os.environ.get(api_key_env)
        if (
            effective_api_key is None
            and provider_class != "ollama"
            and transport_target == "remote"
        ):
            if sys.stdin.isatty():
                effective_api_key = typer.prompt("Provider API key", hide_input=True)
            else:
                raise AhaDiffError(
                    "--api-key-env must point to a set env var when stdin is non-interactive"
                )

        report = probe_provider(
            provider_name=name,
            provider_class=provider_class,
            model_name=resolved_model,
            base_url=base_url,
            api_key=effective_api_key,
            api_key_env=api_key_env,
            workspace_root=root,
            security_config=security_config,
            max_concurrent=int(llm_config["max_concurrent"]),
            qps_limit=int(provider_limits["qps_limit"]),
            retry_attempts=int(llm_config["retry_attempts"]),
            request_timeout_seconds=int(llm_config["request_timeout_seconds"]),
            privacy_mode=resolved_privacy_mode,
        )

        console.print(f"[green]Provider probe succeeded[/green] for {report.provider_name}")
        console.print(f"[bold]Transport[/bold]: {report.transport_target}")
        console.print(f"[bold]Model[/bold]: {report.config.model_name}")
        console.print(f"[bold]Config path[/bold]: {root / '.ahadiff' / 'config.toml'}")
        capabilities = Table(title="Provider capabilities")
        capabilities.add_column("Field", style="cyan")
        capabilities.add_column("Value", style="magenta")
        capabilities.add_row("provider_class", report.config.provider_class)
        capabilities.add_row("supports_stream", str(report.capabilities.supports_stream))
        capabilities.add_row("supports_json_mode", str(report.capabilities.supports_json_mode))
        capabilities.add_row("supports_tool_use", str(report.capabilities.supports_tool_use))
        capabilities.add_row("supports_temperature", str(report.config.supports_temperature))
        capabilities.add_row(
            "supports_rate_limit_headers",
            str(report.capabilities.supports_rate_limit_headers),
        )
        capabilities.add_row(
            "supports_context_probe",
            str(report.capabilities.supports_context_probe),
        )
        capabilities.add_row("tokenizer_estimation", report.capabilities.tokenizer_estimation)
        capabilities.add_row(
            "probed_max_context",
            "unknown"
            if report.config.probed_max_context is None
            else str(
                report.config.probed_max_context,
            ),
        )
        capabilities.add_row("context_window_source", report.context_window_source)
        capabilities.add_row(
            "probed_tpm",
            "unknown" if report.config.probed_tpm is None else str(report.config.probed_tpm),
        )
        capabilities.add_row(
            "probed_rpm",
            "unknown" if report.config.probed_rpm is None else str(report.config.probed_rpm),
        )
        console.print(capabilities)
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
    "maint_clean_orphans_cmd",
    "provider_test_cmd",
    "unlock_cmd",
]
