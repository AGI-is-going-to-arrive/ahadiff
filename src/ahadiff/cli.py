from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table
from typer import Exit

from . import __version__
from .claims import (
    extract_claim_candidates_from_run,
    load_claim_candidates,
    load_line_map_records,
    load_symbol_records,
    load_text_map,
    verify_claim_candidates,
    write_verified_claims_jsonl,
)
from .contracts import ProviderConfig
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
    assert_local_repo_path,
    find_repo_root,
    find_workspace_root,
    global_config_dir,
    inspect_repo_path,
    lock_file_path,
    project_state_dir,
    repo_config_path,
    review_db_path,
    run_dir,
    validate_run_id,
)
from .eval import (
    append_result,
    decide_learn_ratchet,
    evaluate_run,
    export_results,
    load_result_events,
    publish_result_artifacts,
    rollback_result_event,
)
from .git.capture import (
    capture_patch,
    detect_graphify_status,
    import_graphify_artifact,
    write_input_artifacts,
)
from .git.repo import repo_write_lock, unlock_repo_write_lock
from .lesson import generate_lessons_from_run
from .lesson.learnability import assess_learnability
from .llm import probe_provider
from .llm.provider import transport_target_for_base_url
from .quiz import generate_cards_for_run, generate_quiz_from_run, load_quiz_questions
from .review.database import (
    backup_review_db,
    check_review_db,
    finalize_targeted_verify_event,
    import_cards_from_jsonl,
    import_cards_from_runs,
    import_results_tsv_lossy,
    initialize_review_db,
    list_due_cards,
    mark_run_cards_stale,
    record_card_review,
    restore_review_db,
    set_card_queue_state,
    upgrade_review_db,
)
from .review.signal import mark_claim_wrong
from .wiki import append_concepts

if TYPE_CHECKING:
    from .contracts import PrivacyMode
    from .review.schemas import ReviewAnswer
    from .safety.gates import TransportTarget

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
_DB_APP = typer.Typer(help="Manage review.sqlite migrations, backup, restore, and checks.")
_APP.add_typer(_CONFIG_APP, name="config")
_APP.add_typer(_GRAPH_APP, name="graph")
_APP.add_typer(_MAINT_APP, name="maint")
_APP.add_typer(_PROVIDER_APP, name="provider")
_APP.add_typer(_DB_APP, name="db")
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


def _state_dir_for_root(root: Path, *, has_git_repo: bool) -> Path:
    return project_state_dir(root) if has_git_repo else root / ".ahadiff"


def _normalize_provider_base_url(base_url: str, *, provider_class: str) -> str:
    normalized = base_url.rstrip("/")
    suffixes: tuple[str, ...] = ()
    if provider_class in {"openai", "newapi", "cherryin"}:
        suffixes = ("/v1/chat/completions", "/chat/completions")
    elif provider_class == "openai_responses":
        suffixes = ("/v1/responses", "/responses")
    for suffix in suffixes:
        if normalized.endswith(suffix):
            trimmed = normalized[: -len(suffix)]
            if trimmed:
                return trimmed
    return normalized


def _provider_config_from_payload(payload: dict[str, Any]) -> ProviderConfig:
    try:
        return ProviderConfig.model_validate(payload)
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "invalid provider configuration")
        raise AhaDiffError(f"invalid provider configuration: {message}") from exc


def _resolve_runtime_provider(
    *,
    snapshot: Any,
    operation_label: str,
    provider_name: str | None,
    provider_class: str,
    base_url: str | None,
    model: str | None,
    api_key_env: str,
    privacy_mode: str,
    stdin_interactive: bool,
    local_hosts: tuple[str, ...],
) -> tuple[ProviderConfig, str | None, TransportTarget, bool]:
    llm_config = cast("dict[str, Any]", snapshot.values["llm"])
    resolved_model = model or str(llm_config["generate_model"])
    provider_selection_explicit = base_url is not None or provider_name is not None
    if base_url is not None:
        normalized_base_url = _normalize_provider_base_url(base_url, provider_class=provider_class)
        provider_config = _provider_config_from_payload(
            {
                "provider_class": provider_class,
                "model_name": resolved_model,
                "base_url": normalized_base_url,
                "api_key_env": api_key_env,
            }
        )
    else:
        raw_providers_table = snapshot.values.get("providers")
        if not isinstance(raw_providers_table, dict) or not raw_providers_table:
            raise AhaDiffError(
                f"{operation_label} requires --base-url or a configured [providers.<name>] entry"
            )
        providers_table = cast("dict[str, Any]", raw_providers_table)
        resolved_name = provider_name
        if resolved_name is None:
            configured_names = sorted(providers_table.keys())
            if len(configured_names) != 1:
                raise AhaDiffError(
                    f"{operation_label} requires --provider when multiple providers are configured"
                )
            resolved_name = configured_names[0]
        raw_config_payload = providers_table.get(resolved_name)
        if not isinstance(raw_config_payload, dict):
            raise AhaDiffError(f"configured provider is missing or invalid: {resolved_name}")
        config_payload = cast("dict[str, Any]", raw_config_payload)
        normalized_payload = dict(config_payload)
        normalized_payload["base_url"] = _normalize_provider_base_url(
            str(normalized_payload["base_url"]),
            provider_class=str(normalized_payload["provider_class"]),
        )
        if model is not None:
            normalized_payload["model_name"] = model
        provider_config = _provider_config_from_payload(normalized_payload)

    transport_target = transport_target_for_base_url(
        provider_config.base_url,
        local_hosts=local_hosts,
    )
    if (
        not provider_selection_explicit
        and privacy_mode == "strict_local"
        and transport_target == "remote"
    ):
        raise AhaDiffError(
            f"{operation_label} requires --provider or --base-url to use a remote provider "
            "while privacy_mode is strict_local"
        )
    effective_api_key = os.environ.get(provider_config.api_key_env)
    if (
        effective_api_key is None
        and provider_config.provider_class != "ollama"
        and transport_target == "remote"
    ):
        if stdin_interactive:
            effective_api_key = typer.prompt("Provider API key", hide_input=True)
        else:
            raise AhaDiffError(
                "--api-key-env must point to a set env var when stdin is non-interactive"
            )
    return provider_config, effective_api_key, transport_target, provider_selection_explicit


def _resolve_claim_extract_provider(
    *,
    snapshot: Any,
    provider_name: str | None,
    provider_class: str,
    base_url: str | None,
    model: str | None,
    api_key_env: str,
    privacy_mode: str,
    stdin_interactive: bool,
    local_hosts: tuple[str, ...],
) -> tuple[ProviderConfig, str | None, TransportTarget, bool]:
    return _resolve_runtime_provider(
        snapshot=snapshot,
        operation_label="claim extraction",
        provider_name=provider_name,
        provider_class=provider_class,
        base_url=base_url,
        model=model,
        api_key_env=api_key_env,
        privacy_mode=privacy_mode,
        stdin_interactive=stdin_interactive,
        local_hosts=local_hosts,
    )


def _privacy_mode_for_explicit_provider_call(
    privacy_mode: str,
    *,
    transport_target: TransportTarget,
    provider_selection_explicit: bool,
) -> PrivacyMode:
    resolved_privacy_mode = cast("PrivacyMode", privacy_mode)
    if (
        provider_selection_explicit
        and resolved_privacy_mode == "strict_local"
        and transport_target == "remote"
    ):
        return "explicit_remote"
    return resolved_privacy_mode


def _paths_refer_to_same_location(left: Path, right: Path) -> bool:
    return left.expanduser().resolve(strict=False) == right.expanduser().resolve(strict=False)


def _temporary_sibling_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".extract.tmp",
        dir=path.parent,
    )
    os.close(fd)
    temp_path = Path(raw_path)
    temp_path.unlink()
    return temp_path


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


def _cleanup_lesson_generation_artifacts(
    *,
    run_path: Path,
    raw_claims_path: Path | None,
    claims_output_path: Path | None,
) -> None:
    for target in (
        raw_claims_path,
        claims_output_path,
        run_path / "lesson",
        run_path / "quiz",
        run_path / "concepts_local.jsonl",
    ):
        if target is None or not target.exists():
            continue
        _remove_state_path(target)


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
        workspace_root = find_workspace_root(repo_root)
        assert_local_repo_path(workspace_root)
        return workspace_root, False


def _normalize_quiz_answer(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _parse_review_answer(value: str) -> ReviewAnswer:
    normalized = value.strip().casefold()
    if normalized in {"good", "hard", "wrong"}:
        return cast("ReviewAnswer", normalized)
    raise AhaDiffError("review answer must be one of: good, hard, wrong")


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
    force_learn: Annotated[
        bool,
        typer.Option(
            "--force-learn",
            help="Override low learnability gating for downstream lesson/quiz generation.",
        ),
    ] = False,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Configured provider alias under [providers.<name>]."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="One-off provider API base URL for lesson generation."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model override for lesson generation."),
    ] = None,
    provider_class: Annotated[
        str,
        typer.Option("--provider-class", help="Provider class for one-off lesson generation."),
    ] = "openai",
    api_key_env: Annotated[
        str,
        typer.Option(
            "--api-key-env",
            help="Env var name used to resolve the API key for lesson generation.",
        ),
    ] = "AHADIFF_PROVIDER_API_KEY",
) -> None:
    try:
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
        learn_config = cast("dict[str, Any]", snapshot.values["learn"])
        llm_config = cast("dict[str, Any]", snapshot.values["llm"])
        provider_limits = cast("dict[str, Any]", snapshot.values["provider"])
        effective_privacy_mode = str(snapshot.values["privacy_mode"])
        security_config = (
            load_security_config(root) if has_git_repo else load_workspace_security_config(root)
        )
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
            learnability = assess_learnability(
                capture.persisted_patch_text,
                threshold=float(learn_config["learnability_threshold"]),
                force_learn=force_learn,
            )
            capture.metadata["learnability"] = learnability.as_metadata()
            patch_path, metadata_path = write_input_artifacts(capture)
            run_path = (
                run_dir(capture.run_id, root)
                if has_git_repo
                else (root / ".ahadiff" / "runs" / capture.run_id)
            )
            raw_claims_path: Path | None = None
            claims_output_path: Path | None = None
            lesson_paths = None
            quiz_path: Path | None = None
            cards_path: Path | None = None
            concepts_path: Path | None = None
            lesson_skip_reason: str | None = None
            learn_report = None
            learn_outcome = None
            learn_warnings: list[str] = []
            if not dry_run and not learnability.skip_lesson_quiz:
                try:
                    (
                        provider_config,
                        effective_api_key,
                        transport_target,
                        provider_selection_explicit,
                    ) = _resolve_runtime_provider(
                        snapshot=snapshot,
                        operation_label="lesson generation",
                        provider_name=provider,
                        provider_class=provider_class,
                        base_url=base_url,
                        model=model,
                        api_key_env=api_key_env,
                        privacy_mode=effective_privacy_mode,
                        stdin_interactive=sys.stdin.isatty(),
                        local_hosts=security_config.local_hosts,
                    )
                    resolved_privacy_mode = _privacy_mode_for_explicit_provider_call(
                        effective_privacy_mode,
                        transport_target=transport_target,
                        provider_selection_explicit=provider_selection_explicit,
                    )
                    raw_claims_path, _ = extract_claim_candidates_from_run(
                        run_id=capture.run_id,
                        run_path=run_path,
                        workspace_root=root,
                        provider_config=provider_config,
                        api_key=effective_api_key,
                        security_config=security_config,
                        output_path=run_path / "claims.raw.jsonl",
                        overwrite=False,
                        privacy_mode=resolved_privacy_mode,
                        max_concurrent=int(llm_config["max_concurrent"]),
                        qps_limit=int(provider_limits["qps_limit"]),
                        retry_attempts=int(llm_config["retry_attempts"]),
                        request_timeout_seconds=int(llm_config["request_timeout_seconds"]),
                    )
                    candidates = load_claim_candidates(
                        raw_claims_path,
                        default_run_id=capture.run_id,
                    )
                    line_maps = load_line_map_records(run_path / "line_map.json")
                    symbols = load_symbol_records(run_path / "symbols.json")
                    before_text_by_path = load_text_map(
                        run_path / "before_text_by_path.json",
                        expected_artifact="before_text_by_path",
                    )
                    after_text_by_path = load_text_map(
                        run_path / "after_text_by_path.json",
                        expected_artifact="after_text_by_path",
                    )
                    verified = verify_claim_candidates(
                        candidates,
                        line_maps=line_maps,
                        symbols=symbols,
                        before_text_by_path=before_text_by_path,
                        after_text_by_path=after_text_by_path,
                    )
                    claims_output_path = run_path / "claims.jsonl"
                    write_verified_claims_jsonl(claims_output_path, verified, overwrite=False)
                    verified_claim_count = sum(
                        1 for item in verified if item.record.status == "verified"
                    )
                    if verified_claim_count == 0:
                        lesson_skip_reason = "no verified claims survived verification"
                    else:
                        lesson_paths = generate_lessons_from_run(
                            run_id=capture.run_id,
                            run_path=run_path,
                            workspace_root=root,
                            provider_config=provider_config,
                            api_key=effective_api_key,
                            security_config=security_config,
                            request_timeout_seconds=int(llm_config["request_timeout_seconds"]),
                            max_concurrent=int(llm_config["max_concurrent"]),
                            qps_limit=int(provider_limits["qps_limit"]),
                            retry_attempts=int(llm_config["retry_attempts"]),
                            privacy_mode=resolved_privacy_mode,
                        )
                        quiz_artifacts, quiz_questions = generate_quiz_from_run(
                            run_id=capture.run_id,
                            run_path=run_path,
                            workspace_root=root,
                            provider_config=provider_config,
                            api_key=effective_api_key,
                            security_config=security_config,
                            request_timeout_seconds=int(llm_config["request_timeout_seconds"]),
                            max_concurrent=int(llm_config["max_concurrent"]),
                            qps_limit=int(provider_limits["qps_limit"]),
                            retry_attempts=int(llm_config["retry_attempts"]),
                            privacy_mode=resolved_privacy_mode,
                        )
                        quiz_path = quiz_artifacts.quiz_path
                        learn_report = evaluate_run(run_path)
                        cards_path = generate_cards_for_run(
                            run_path=run_path,
                            questions=quiz_questions,
                            verdict=learn_report.verdict,
                        )
                        learn_outcome, learn_warnings = _persist_evaluated_run(
                            run_path=run_path,
                            report=learn_report,
                            workspace_root=root,
                            event_type="learn",
                            output_path=run_path / "score.json",
                            force=False,
                            note_payload={"learnability": learnability.as_metadata()},
                        )
                        try:
                            concepts_path = append_concepts(
                                workspace_root=root,
                                run_path=run_path,
                                run_id=capture.run_id,
                                source_kind=str(capture.run_source.source_kind),
                                source_ref=str(capture.run_source.source_ref),
                                questions=quiz_questions,
                            )
                        except Exception as concept_error:
                            learn_warnings.append(f"concepts append failed: {concept_error}")
                except Exception as exc:
                    _cleanup_lesson_generation_artifacts(
                        run_path=run_path,
                        raw_claims_path=raw_claims_path,
                        claims_output_path=claims_output_path,
                    )
                    if isinstance(exc, AhaDiffError):
                        raise
                    raise AhaDiffError(f"lesson generation failed: {exc}") from exc

        console.print(f"[green]Captured[/green] {capture.run_source.source_kind}")
        console.print(f"[bold]Run ID[/bold]: {capture.run_id}")
        console.print(f"[bold]Patch[/bold]: {patch_path}")
        console.print(f"[bold]Metadata[/bold]: {metadata_path}")
        console.print(f"[bold]Source ref[/bold]: {capture.run_source.source_ref}")
        console.print(f"[bold]Capability level[/bold]: {capture.run_source.capability_level}")
        console.print(
            f"[bold]Learnability[/bold]: {learnability.score:.3f} / {learnability.threshold:.3f}"
        )
        if learnability.skip_lesson_quiz:
            console.print(
                "[yellow]Learnability[/yellow]: low learning value; lesson/quiz would be skipped"
            )
        elif learnability.forced and learnability.score < learnability.threshold:
            console.print(
                "[yellow]Learnability[/yellow]: low learning value, "
                "but --force-learn overrides the skip"
            )
        if raw_claims_path is not None:
            console.print(f"[bold]Raw claims[/bold]: {raw_claims_path}")
        if claims_output_path is not None:
            console.print(f"[bold]Claims[/bold]: {claims_output_path}")
        if lesson_paths is not None:
            console.print(f"[bold]Lesson[/bold]: {lesson_paths.full_path}")
            console.print(f"[bold]Hint[/bold]: {lesson_paths.hint_path}")
            console.print(f"[bold]Compact[/bold]: {lesson_paths.compact_path}")
            if quiz_path is not None:
                console.print(f"[bold]Quiz[/bold]: {quiz_path}")
            if cards_path is not None:
                console.print(f"[bold]Cards[/bold]: {cards_path}")
            elif learn_report is not None and learn_report.verdict == "FAIL":
                console.print("[bold]Cards[/bold]: skipped because verdict is FAIL")
            if concepts_path is not None:
                console.print(f"[bold]Concepts[/bold]: {concepts_path}")
            if learn_report is not None and learn_outcome is not None:
                console.print(f"[bold]Score[/bold]: {learn_report.overall:.2f}")
                console.print(f"[bold]Verdict[/bold]: {learn_report.verdict}")
                console.print(f"[bold]Status[/bold]: {learn_outcome.event.status}")
                console.print(f"[bold]Score Output[/bold]: {run_path / 'score.json'}")
                for warning in learn_warnings:
                    console.print(f"[yellow]Warning[/yellow]: {warning}")
        elif lesson_skip_reason is not None:
            console.print(f"[bold]Lesson[/bold]: skipped because {lesson_skip_reason}")
        elif not dry_run and learnability.skip_lesson_quiz:
            console.print("[bold]Lesson[/bold]: skipped by learnability gate")
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


@_APP.command("quiz")
def quiz_cmd(
    run_id: Annotated[
        str,
        typer.Argument(help="Run id under .ahadiff/runs/<run_id>."),
    ],
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        validate_run_id(run_id)
        run_path = run_dir(run_id, root) if has_git_repo else (root / ".ahadiff" / "runs" / run_id)
        questions = load_quiz_questions(run_path / "quiz" / "quiz.jsonl")
        correct = 0
        for index, question in enumerate(questions, start=1):
            console.print(f"[bold]Question {index}[/bold]: {question.question}")
            answer = typer.prompt("Your answer")
            if _normalize_quiz_answer(answer) == _normalize_quiz_answer(question.expected_answer):
                correct += 1
                console.print("[green]Correct[/green]")
            else:
                console.print(f"[yellow]Expected[/yellow]: {question.expected_answer}")
            claims_text = ", ".join(question.source_claims)
            evidence_text = ", ".join(f"{item.file}:{item.line}" for item in question.evidence)
            console.print(f"[bold]Claims[/bold]: {claims_text}")
            console.print(f"[bold]Evidence[/bold]: {evidence_text}")
            if question.concepts:
                console.print(f"[bold]Concepts[/bold]: {', '.join(question.concepts)}")
            if question.explanation:
                console.print(f"[bold]Why[/bold]: {question.explanation}")
            console.print("")
        console.print(f"[bold]Score[/bold]: {correct}/{len(questions)}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


def _backup_artifact_for_rollback(path: Path) -> Path | None:
    if not path.exists():
        return None
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".rollback.bak",
        delete=False,
    ) as handle:
        backup_path = Path(handle.name)
    shutil.copy2(path, backup_path)
    return backup_path


def _restore_artifact_from_backup(*, target: Path, backup_path: Path | None) -> None:
    if backup_path is None:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_path.replace(target)


@_APP.command("regenerate")
def regenerate_cmd(
    run_id: Annotated[
        str,
        typer.Argument(help="Run id under .ahadiff/runs/<run_id>."),
    ],
    only: Annotated[
        str,
        typer.Option("--only", help="Artifact subset to regenerate. Only 'quiz' is supported."),
    ],
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Configured provider alias under [providers.<name>]."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="One-off provider API base URL for regeneration."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model override for regeneration."),
    ] = None,
    provider_class: Annotated[
        str,
        typer.Option("--provider-class", help="Provider class for one-off regeneration."),
    ] = "openai",
    api_key_env: Annotated[
        str,
        typer.Option("--api-key-env", help="Env var name used to resolve the provider API key."),
    ] = "AHADIFF_PROVIDER_API_KEY",
) -> None:
    try:
        if only != "quiz":
            raise AhaDiffError("regenerate currently supports only: --only quiz")
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        validate_run_id(run_id)
        run_path = run_dir(run_id, root) if has_git_repo else (root / ".ahadiff" / "runs" / run_id)
        if not run_path.exists():
            raise AhaDiffError(f"run artifacts do not exist: {run_path}")
        snapshot = load_config(root) if has_git_repo else load_workspace_config(root)
        llm_config = cast("dict[str, Any]", snapshot.values["llm"])
        provider_limits = cast("dict[str, Any]", snapshot.values["provider"])
        effective_privacy_mode = str(snapshot.values["privacy_mode"])
        security_config = (
            load_security_config(root) if has_git_repo else load_workspace_security_config(root)
        )
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="regenerate quiz") as _:
            quiz_path = run_path / "quiz" / "quiz.jsonl"
            cards_target_path = run_path / "quiz" / "cards.jsonl"
            quiz_backup = _backup_artifact_for_rollback(quiz_path)
            cards_backup = _backup_artifact_for_rollback(cards_target_path)
            (
                provider_config,
                effective_api_key,
                transport_target,
                provider_selection_explicit,
            ) = _resolve_runtime_provider(
                snapshot=snapshot,
                operation_label="quiz regeneration",
                provider_name=provider,
                provider_class=provider_class,
                base_url=base_url,
                model=model,
                api_key_env=api_key_env,
                privacy_mode=effective_privacy_mode,
                stdin_interactive=sys.stdin.isatty(),
                local_hosts=security_config.local_hosts,
            )
            resolved_privacy_mode = _privacy_mode_for_explicit_provider_call(
                effective_privacy_mode,
                transport_target=transport_target,
                provider_selection_explicit=provider_selection_explicit,
            )
            cards_path: Path | None = None
            try:
                quiz_artifacts, questions = generate_quiz_from_run(
                    run_id=run_id,
                    run_path=run_path,
                    workspace_root=root,
                    provider_config=provider_config,
                    api_key=effective_api_key,
                    security_config=security_config,
                    request_timeout_seconds=int(llm_config["request_timeout_seconds"]),
                    max_concurrent=int(llm_config["max_concurrent"]),
                    qps_limit=int(provider_limits["qps_limit"]),
                    retry_attempts=int(llm_config["retry_attempts"]),
                    privacy_mode=resolved_privacy_mode,
                    overwrite=True,
                )
                report = evaluate_run(run_path)
                cards_path = generate_cards_for_run(
                    run_path=run_path,
                    questions=questions,
                    verdict=report.verdict,
                    overwrite=True,
                )
                if cards_path is None:
                    cards_target_path.unlink(missing_ok=True)
                    mark_run_cards_stale(state_dir / "review.sqlite", run_id=run_id)
                else:
                    import_cards_from_jsonl(state_dir / "review.sqlite", cards_path)
            except Exception:
                _restore_artifact_from_backup(target=quiz_path, backup_path=quiz_backup)
                _restore_artifact_from_backup(target=cards_target_path, backup_path=cards_backup)
                raise
            finally:
                if quiz_backup is not None:
                    quiz_backup.unlink(missing_ok=True)
                if cards_backup is not None:
                    cards_backup.unlink(missing_ok=True)
        console.print(f"[green]Regenerated quiz[/green]: {quiz_artifacts.quiz_path}")
        if cards_path is not None:
            console.print(f"[bold]Cards[/bold]: {cards_path}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_APP.command("review")
def review_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, help="Maximum due cards to display."),
    ] = 20,
    card_id: Annotated[
        str | None,
        typer.Option("--card-id", help="Record a review for this card id."),
    ] = None,
    answer: Annotated[
        str | None,
        typer.Option("--answer", help="Review answer: good, hard, or wrong."),
    ] = None,
    peeked: Annotated[
        bool,
        typer.Option("--peeked", help="Apply peek guard for this review attempt."),
    ] = False,
    action: Annotated[
        str | None,
        typer.Option("--action", help="Queue action: archive or suspend."),
    ] = None,
    scheduler: Annotated[
        str,
        typer.Option("--scheduler", help="Scheduler feature flag; fsrs is the v0.1 default."),
    ] = "fsrs",
    optimize: Annotated[
        bool,
        typer.Option("--optimize", help="Check FSRS optimizer readiness."),
    ] = False,
) -> None:
    try:
        if scheduler != "fsrs":
            raise AhaDiffError("only the FSRS scheduler is implemented in v0.1")
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        db_path = state_dir / "review.sqlite"
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="review") as _:
            initialize_review_db(db_path)
            import_warnings: list[str] = []

            def _on_card_import_error(path: Path, exc: Exception) -> None:
                import_warnings.append(f"skipped {path.name}: {exc}")

            imported = import_cards_from_runs(db_path, state_dir, on_error=_on_card_import_error)
            if action is not None:
                if not card_id:
                    raise AhaDiffError("--action requires --card-id")
                if answer is not None:
                    raise AhaDiffError("--action cannot be combined with --answer")
                normalized_action = action.strip().casefold()
                if normalized_action not in {"archive", "suspend"}:
                    raise AhaDiffError("review action must be one of: archive, suspend")
                queue_state = "archived" if normalized_action == "archive" else "suspended"
                set_card_queue_state(db_path, card_id=card_id, state=queue_state)
                rendered_action = "Archived" if normalized_action == "archive" else "Suspended"
                console.print(f"[green]{rendered_action}[/green] {card_id}")
                return
            if card_id is not None or answer is not None:
                if not card_id or not answer:
                    raise AhaDiffError("--card-id and --answer must be provided together")
                normalized_answer = _parse_review_answer(answer)
                update = record_card_review(
                    db_path,
                    card_id=card_id,
                    answer=normalized_answer,
                    peeked_this_session=peeked,
                )
                console.print(f"[green]Reviewed[/green] {update.card_id}")
                console.print(f"[bold]Rating[/bold]: {update.rating}")
                console.print(f"[bold]Next due[/bold]: {update.due_date}")
                console.print(f"[bold]Scaffolding[/bold]: {update.scaffolding_level}")
                return
            if optimize:
                check = check_review_db(db_path)
                console.print(
                    "[yellow]Optimizer[/yellow]: cold-start mode; "
                    "requires at least 500 effective reviews before training"
                )
                console.print(f"[bold]Result events[/bold]: {check.event_count}")
                return
            due_cards = list_due_cards(db_path, limit=limit)
        console.print(f"[bold]Imported cards[/bold]: {imported}")
        for warning in import_warnings:
            error_console.print(f"[yellow]Warning[/yellow]: {warning}")
        if not due_cards:
            console.print("[green]Review queue[/green]: no due cards")
            return
        table = Table(title="Due review cards")
        table.add_column("Card", style="cyan")
        table.add_column("Concept", style="magenta")
        table.add_column("Due", style="green")
        table.add_column("Scaffold", style="yellow")
        table.add_column("Path")
        for card in due_cards:
            table.add_row(
                card.card_id,
                card.concept,
                card.due_date,
                card.scaffolding_level,
                card.display_path,
            )
        console.print(table)
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_APP.command("mark")
def mark_cmd(
    claim_id: Annotated[
        str,
        typer.Argument(help="Claim id to mark."),
    ],
    action: Annotated[
        str,
        typer.Argument(help="Only 'wrong' is supported in v0.1."),
    ],
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
) -> None:
    try:
        if action != "wrong":
            raise AhaDiffError("mark currently supports only: wrong")
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        db_path = state_dir / "review.sqlite"
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="mark wrong") as _:
            initialize_review_db(db_path)
            inserted = mark_claim_wrong(db_path=db_path, claim_id=claim_id)
        if inserted:
            console.print(f"[green]Marked wrong[/green]: {claim_id}")
        else:
            console.print(f"[yellow]Already marked wrong[/yellow]: {claim_id}")
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


@_APP.command("claims")
def claims_cmd(
    run_id: Annotated[
        str,
        typer.Argument(help="Run id under .ahadiff/runs/<run_id>."),
    ],
    extract: Annotated[
        bool,
        typer.Option(
            "--extract",
            help="Generate claim candidates with an LLM before deterministic verification.",
        ),
    ] = False,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Configured provider alias under [providers.<name>]."),
    ] = None,
    claims_file: Annotated[
        Path | None,
        typer.Option(
            "--claims-file",
            help=(
                "Raw claim candidate JSON/JSONL file. Defaults to claims.raw.jsonl in the run dir."
            ),
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            help="Verified claims JSONL output path. Defaults to claims.jsonl in the run dir.",
        ),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="One-off provider API base URL for claim extraction."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model override for claim extraction."),
    ] = None,
    provider_class: Annotated[
        str,
        typer.Option("--provider-class", help="Provider class for one-off claim extraction."),
    ] = "openai",
    api_key_env: Annotated[
        str,
        typer.Option(
            "--api-key-env",
            help="Env var name used to resolve the API key for one-off claim extraction.",
        ),
    ] = "AHADIFF_PROVIDER_API_KEY",
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing verified claims file."),
    ] = False,
) -> None:
    candidate_path: Path | None = None
    extracted_candidate_path: Path | None = None
    candidate_path_preexisted = True
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        if has_git_repo:
            run_path = run_dir(run_id, root)
        else:
            validate_run_id(run_id)
            run_path = state_dir / "runs" / run_id
        if not run_path.exists():
            raise AhaDiffError(f"run artifacts do not exist: {run_path}")

        candidate_path = claims_file or run_path / "claims.raw.jsonl"
        output_path = output or run_path / "claims.jsonl"
        if _paths_refer_to_same_location(candidate_path, output_path):
            raise AhaDiffError("--claims-file and --output must point to different files")
        if output_path.exists() and not force:
            raise AhaDiffError(f"refusing to overwrite existing file: {output_path}")
        line_map_path = run_path / "line_map.json"
        symbols_path = run_path / "symbols.json"
        before_text_path = run_path / "before_text_by_path.json"
        after_text_path = run_path / "after_text_by_path.json"
        candidate_path_preexisted = candidate_path.exists()
        candidate_load_path = candidate_path
        pending_candidate_commit: tuple[Path, Path] | None = None
        if extract:
            if candidate_path_preexisted and not force:
                raise AhaDiffError(f"refusing to overwrite existing file: {candidate_path}")
            snapshot = load_config(root) if has_git_repo else load_workspace_config(root)
            security_config = (
                load_security_config(root) if has_git_repo else load_workspace_security_config(root)
            )
            llm_config = cast("dict[str, Any]", snapshot.values["llm"])
            provider_limits = cast("dict[str, Any]", snapshot.values["provider"])
            (
                provider_config,
                effective_api_key,
                transport_target,
                provider_selection_explicit,
            ) = _resolve_claim_extract_provider(
                snapshot=snapshot,
                provider_name=provider,
                provider_class=provider_class,
                base_url=base_url,
                model=model,
                api_key_env=api_key_env,
                privacy_mode=str(snapshot.values["privacy_mode"]),
                stdin_interactive=sys.stdin.isatty(),
                local_hosts=security_config.local_hosts,
            )
            resolved_privacy_mode = _privacy_mode_for_explicit_provider_call(
                str(snapshot.values["privacy_mode"]),
                transport_target=transport_target,
                provider_selection_explicit=provider_selection_explicit,
            )
            extract_output_path = candidate_path
            if candidate_path_preexisted:
                extract_output_path = _temporary_sibling_path(candidate_path)
            raw_claims_path, _ = extract_claim_candidates_from_run(
                run_id=run_id,
                run_path=run_path,
                workspace_root=root,
                provider_config=provider_config,
                api_key=effective_api_key,
                security_config=security_config,
                output_path=extract_output_path,
                overwrite=False,
                privacy_mode=resolved_privacy_mode,
                max_concurrent=int(llm_config["max_concurrent"]),
                qps_limit=int(provider_limits["qps_limit"]),
                retry_attempts=int(llm_config["retry_attempts"]),
                request_timeout_seconds=int(llm_config["request_timeout_seconds"]),
            )
            extracted_candidate_path = raw_claims_path
            candidate_load_path = raw_claims_path
            if candidate_path_preexisted:
                pending_candidate_commit = (raw_claims_path, candidate_path)
            console.print(f"[bold]Raw claims[/bold]: {raw_claims_path}")

        candidates = load_claim_candidates(candidate_load_path, default_run_id=run_id)
        mismatched_run_ids = sorted(
            {candidate.run_id for candidate in candidates if candidate.run_id != run_id}
        )
        if mismatched_run_ids:
            raise AhaDiffError(
                f"claims payload run_id does not match CLI run_id {run_id!r}: "
                + ", ".join(repr(item) for item in mismatched_run_ids)
            )
        line_maps = load_line_map_records(line_map_path)
        symbols = load_symbol_records(symbols_path)
        before_text_by_path: dict[str, str] = {}
        after_text_by_path: dict[str, str] = {}
        if before_text_path.exists():
            before_text_by_path = load_text_map(
                before_text_path,
                expected_artifact="before_text_by_path",
            )
        if after_text_path.exists():
            after_text_by_path = load_text_map(
                after_text_path,
                expected_artifact="after_text_by_path",
            )
        if not before_text_by_path or not after_text_by_path:
            console.print(
                "[yellow]Warning[/yellow]: some before/after text artifacts are missing; "
                "structural negative scan is partially degraded"
            )

        lock_path = lock_file_path(root) if has_git_repo else state_dir / "ahadiff.lock"
        with repo_write_lock(lock_path, command="claims verify") as _:
            verified = verify_claim_candidates(
                candidates,
                line_maps=line_maps,
                symbols=symbols,
                before_text_by_path=before_text_by_path,
                after_text_by_path=after_text_by_path,
            )
            write_verified_claims_jsonl(output_path, verified, overwrite=force)
            if pending_candidate_commit is not None:
                temporary_path, final_path = pending_candidate_commit
                temporary_path.replace(final_path)

        summary = Table(title="Claim verification summary")
        summary.add_column("Claim", style="cyan")
        summary.add_column("Status", style="magenta")
        summary.add_column("Confidence", style="green")
        for item in verified:
            summary.add_row(
                item.record.claim_id,
                item.record.status,
                item.record.confidence,
            )
        console.print(summary)
        console.print(f"[bold]Verified claims[/bold]: {output_path}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        if extracted_candidate_path is not None and (
            not candidate_path_preexisted
            or candidate_path is None
            or extracted_candidate_path != candidate_path
        ):
            with suppress(OSError):
                extracted_candidate_path.unlink()
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


def _resolve_existing_run_path(repo_root: Path, run_id: str) -> Path:
    root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
    state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
    if has_git_repo:
        target = run_dir(run_id, root)
    else:
        validate_run_id(run_id)
        target = state_dir / "runs" / run_id
    if not target.exists():
        raise AhaDiffError(f"run artifacts do not exist: {target}")
    return target


def _persist_evaluated_run(
    *,
    run_path: Path,
    report: Any,
    workspace_root: Path,
    event_type: str,
    output_path: Path,
    force: bool,
    note_payload: dict[str, object] | None = None,
) -> tuple[Any, list[str]]:
    db_path = run_path.parent.parent / "review.sqlite"
    decision = decide_learn_ratchet(
        workspace_root=workspace_root,
        report=report,
        prior_events=load_result_events(db_path),
    )
    combined_note_payload = dict(decision.note_payload or {})
    if note_payload:
        combined_note_payload.update(note_payload)
    outcome = append_result(
        run_path=run_path,
        report=report,
        status=decision.status,
        base_ref=decision.base_ref,
        event_type=event_type,
        note_payload=combined_note_payload or None,
        score_path=output_path,
        write_finalized=False,
    )
    warnings = list(outcome.warnings)
    try:
        publish_result_artifacts(
            run_path=run_path,
            report=report,
            event=outcome.event,
            score_path=output_path,
            overwrite=force,
        )
    except OSError as exc:
        if outcome.sqlite_inserted:
            try:
                rollback_result_event(run_path=run_path, event_id=outcome.event.event_id)
            except Exception as rollback_error:
                raise AhaDiffError(
                    "failed to publish score artifacts and failed to roll back "
                    f"result event {outcome.event.event_id}: {rollback_error}"
                ) from rollback_error
        raise AhaDiffError(f"failed to publish score artifacts: {exc}") from exc
    return outcome, warnings


def _score_or_verify_run(
    *,
    command_name: str,
    run_id: str,
    repo_root: Path,
    output: Path | None,
    force: bool,
) -> None:
    run_path = _resolve_existing_run_path(repo_root, run_id)
    output_path = output or run_path / "score.json"
    workspace_root = run_path.parent.parent.parent
    _, lock_path = _state_dir_and_lock_path(repo_root)
    if output_path.exists() and not force:
        raise AhaDiffError(f"refusing to overwrite existing file: {output_path}")
    with repo_write_lock(lock_path, command=command_name) as _:
        report = evaluate_run(run_path)
        outcome, warnings = _persist_evaluated_run(
            run_path=run_path,
            report=report,
            event_type=command_name,
            workspace_root=workspace_root,
            output_path=output_path,
            force=force,
        )
    console.print(f"[green]{command_name.title()} complete[/green]: {run_id}")
    console.print(f"[bold]Score[/bold]: {report.overall:.2f}")
    console.print(f"[bold]Verdict[/bold]: {report.verdict}")
    console.print(f"[bold]Status[/bold]: {outcome.event.status}")
    console.print(f"[bold]Weakest dim[/bold]: {report.weakest_dim}")
    console.print(f"[bold]Eval bundle[/bold]: {report.eval_bundle_version}")
    console.print(f"[bold]Output[/bold]: {output_path}")
    if report.hard_gates.failed_names():
        failed = ", ".join(report.hard_gates.failed_names())
        console.print(f"[yellow]Failed hard gates[/yellow]: {failed}")
    for warning in warnings:
        console.print(f"[yellow]Warning[/yellow]: {warning}")


@_APP.command("score")
def score_cmd(
    run_id: Annotated[
        str,
        typer.Argument(help="Run id under .ahadiff/runs/<run_id>."),
    ],
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Output path for score.json."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing score output."),
    ] = False,
) -> None:
    try:
        _score_or_verify_run(
            command_name="score",
            run_id=run_id,
            repo_root=repo_root,
            output=output,
            force=force,
        )
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_APP.command("verify")
def verify_cmd(
    run_id: Annotated[
        str,
        typer.Argument(help="Run id under .ahadiff/runs/<run_id>."),
    ],
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Output path for score.json."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing score output."),
    ] = False,
) -> None:
    try:
        _score_or_verify_run(
            command_name="verify",
            run_id=run_id,
            repo_root=repo_root,
            output=output,
            force=force,
        )
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_APP.command("export-results")
def export_results_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Output path for results.tsv."),
    ] = None,
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        db_path = state_dir / "review.sqlite"
        output_path = output or state_dir / "results.tsv"
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="export-results") as _:
            export_results(db_path=db_path, output_path=output_path)
        console.print(f"[green]Exported[/green] {output_path}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_DB_APP.command("upgrade")
def db_upgrade_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        db_path = state_dir / "review.sqlite"
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="db upgrade") as _:
            outcome = upgrade_review_db(db_path)
        console.print(f"[green]Upgraded[/green] {outcome.db_path}")
        console.print(f"[bold]Schema version[/bold]: {outcome.schema_version}")
        console.print(f"[bold]Backup[/bold]: {outcome.backup_path}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_DB_APP.command("backup")
def db_backup_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Backup file path."),
    ] = None,
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        db_path = state_dir / "review.sqlite"
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="db backup") as _:
            backup_path = backup_review_db(db_path, backup_path=output)
        console.print(f"[green]Backed up[/green] {backup_path}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_DB_APP.command("restore")
def db_restore_cmd(
    backup_path: Annotated[
        Path,
        typer.Argument(help="Backup path created by `ahadiff db backup`."),
    ],
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        db_path = state_dir / "review.sqlite"
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="db restore") as _:
            restore_review_db(db_path=db_path, backup_path=backup_path)
        console.print(f"[green]Restored[/green] {db_path}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_DB_APP.command("check")
def db_check_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        db_path = state_dir / "review.sqlite"
        check = check_review_db(db_path)
        console.print(f"[bold]Schema version[/bold]: {check.schema_version}")
        console.print(f"[bold]SQLite quick_check[/bold]: {check.quick_check}")
        console.print(f"[bold]Foreign key issues[/bold]: {check.foreign_key_issues}")
        console.print(f"[bold]Result events[/bold]: {check.event_count}")
        console.print(f"[bold]Event id unique[/bold]: {check.event_id_unique}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_DB_APP.command("import-results")
def db_import_results_cmd(
    tsv_path: Annotated[
        Path,
        typer.Argument(help="Legacy results.tsv path to import lossy."),
    ],
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    understand_lossy: Annotated[
        bool,
        typer.Option(
            "--i-understand-this-is-lossy",
            help="Required because TSV lacks event_id/event_type/eval_bundle_version.",
        ),
    ] = False,
) -> None:
    try:
        if not understand_lossy:
            raise AhaDiffError(
                "db import-results is lossy; pass --i-understand-this-is-lossy to continue"
            )
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        db_path = state_dir / "review.sqlite"
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="db import-results --lossy") as _:
            outcome = import_results_tsv_lossy(db_path, tsv_path)
        console.print(f"[yellow]Lossy import[/yellow]: {outcome.imported} imported")
        console.print(f"[bold]Skipped[/bold]: {outcome.skipped}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_DB_APP.command("finalize-targeted")
def db_finalize_targeted_cmd(
    run_id: Annotated[
        str,
        typer.Argument(help="Run id with a targeted_verify event."),
    ],
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        db_path = state_dir / "review.sqlite"
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="db finalize-targeted") as _:
            event = finalize_targeted_verify_event(db_path, run_id=run_id)
        console.print(f"[green]Finalized targeted verify[/green]: {event.run_id}")
        console.print(f"[bold]Event[/bold]: {event.event_id}")
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
        normalized_base_url = _normalize_provider_base_url(base_url, provider_class=provider_class)
        _provider_config_from_payload(
            {
                "provider_class": provider_class,
                "model_name": resolved_model,
                "base_url": normalized_base_url,
                "api_key_env": api_key_env,
            }
        )
        resolved_privacy_mode = cast("PrivacyMode", str(snapshot.values["privacy_mode"]))
        transport_target = transport_target_for_base_url(
            normalized_base_url,
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
            base_url=normalized_base_url,
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
    "claims_cmd",
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
