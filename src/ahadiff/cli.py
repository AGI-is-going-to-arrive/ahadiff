from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import webbrowser
from contextlib import ExitStack, suppress
from functools import cache
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast
from urllib.parse import quote

import typer
from rich.console import Console
from rich.table import Table
from typer import Exit

from . import __version__
from .contracts import ProviderConfig
from .core.config import (
    SecurityConfig,
    iter_resolved_settings,
    load_config,
    load_security_config,
    load_workspace_config,
    load_workspace_security_config,
    local_hosts_for_privacy_mode,
    normalize_provider_base_url,
    resolve_provider_api_key,
    write_default_config,
)
from .core.errors import AhaDiffError, ConfigError, InputError, StorageError
from .core.json_util import safe_json_loads
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
    validate_state_dir_path,
)
from .core.sqlite_util import safe_sqlite_connect
from .i18n import normalize_locale, resolve_locale

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

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
_CONCEPTS_APP = typer.Typer(help="Export, rollback, and verify the concepts derived cache.")
_EXPORT_APP = typer.Typer(help="Static preview and review export bundles.")
_CHALLENGE_APP = typer.Typer(
    help=(
        "Opt-in Diffity-style challenge loop (CLI: build/status; WebUI/API: advance/abort/review)."
    ),
)
_APP.add_typer(_CONFIG_APP, name="config")
_APP.add_typer(_GRAPH_APP, name="graph")
_APP.add_typer(_MAINT_APP, name="maint")
_APP.add_typer(_PROVIDER_APP, name="provider")
_APP.add_typer(_DB_APP, name="db")
_APP.add_typer(_CONCEPTS_APP, name="concepts")
_APP.add_typer(_EXPORT_APP, name="export")
_APP.add_typer(_CHALLENGE_APP, name="challenge")
_INSTALL_TARGET_HELP = (
    "Install target: aider, claude, cline, codex, continue, copilot, cursor, gemini, "
    "github-action, hooks, opencode, roo, or windsurf. hooks uses POSIX shell hooks; "
    "Windows hooks are not supported in v0.1."
)
_SQLITE_MIN_VERSION = (3, 51, 3)
_SQLITE_ALLOWED_BACKPORTS = {(3, 50, 7), (3, 44, 6)}


@cache
def _lazy_module(module_name: str) -> Any:
    return import_module(f"{__package__}.{module_name}")


class _LazyCallable:
    def __init__(self, module_name: str, attr_name: str) -> None:
        self._module_name = module_name
        self._attr_name = attr_name

    def _resolve(self) -> Any:
        return getattr(_lazy_module(self._module_name), self._attr_name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._resolve()(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __repr__(self) -> str:
        return repr(self._resolve())


def _lazy_attr(module_name: str, attr_name: str) -> Any:
    # Keep CLI monkeypatch targets stable without importing heavy modules on startup.
    return _LazyCallable(module_name, attr_name)


def _install_context_cls() -> type[Any]:
    return cast("type[Any]", _lazy_module("install").InstallContext)


def _serve_state_cls() -> type[Any]:
    return cast("type[Any]", _lazy_module("serve").ServeState)


extract_claim_candidates_from_run = _lazy_attr("claims", "extract_claim_candidates_from_run")
load_claim_candidates = _lazy_attr("claims", "load_claim_candidates")
load_line_map_records = _lazy_attr("claims", "load_line_map_records")
load_symbol_records = _lazy_attr("claims", "load_symbol_records")
load_text_map = _lazy_attr("claims", "load_text_map")
verify_claim_candidates = _lazy_attr("claims", "verify_claim_candidates")
write_verified_claims_jsonl = _lazy_attr("claims", "write_verified_claims_jsonl")
append_result = _lazy_attr("eval", "append_result")
decide_learn_ratchet = _lazy_attr("eval", "decide_learn_ratchet")
evaluate_run = _lazy_attr("eval", "evaluate_run")
export_results = _lazy_attr("eval", "export_results")
load_result_events = _lazy_attr("eval", "load_result_events")
publish_result_artifacts = _lazy_attr("eval", "publish_result_artifacts")
rollback_result_event = _lazy_attr("eval", "rollback_result_event")
run_benchmark_suite = _lazy_attr("eval", "run_benchmark_suite")
write_benchmark_report = _lazy_attr("eval", "write_benchmark_report")
finalized_artifact_digest = _lazy_attr("eval.results", "finalized_artifact_digest")
spec_source_reference = _lazy_attr("eval.spec_alignment", "spec_source_reference")
write_spec_alignment_artifact = _lazy_attr(
    "eval.spec_alignment",
    "write_spec_alignment_artifact",
)
mark_semantic_alignment_review_degraded = _lazy_attr(
    "eval.spec_alignment",
    "mark_semantic_alignment_review_degraded",
)
run_semantic_alignment_review_for_run = _lazy_attr(
    "eval.spec_alignment",
    "run_semantic_alignment_review_for_run",
)
capture_patch = _lazy_attr("git.capture", "capture_patch")
detect_graphify_status = _lazy_attr("git.capture", "detect_graphify_status")
import_graphify_artifact = _lazy_attr("git.capture", "import_graphify_artifact")
write_input_artifacts = _lazy_attr("git.capture", "write_input_artifacts")
repo_write_lock = _lazy_attr("git.repo", "repo_write_lock")
unlock_repo_write_lock = _lazy_attr("git.repo", "unlock_repo_write_lock")
run_improve_loop = _lazy_attr("improve", "run_improve_loop")
persist_skipped_run = _lazy_attr("core.orchestrator", "_persist_skipped_run")
available_targets = _lazy_attr("install", "available_targets")
get_target = _lazy_attr("install", "get_target")
manifest_preview_for = _lazy_attr("install", "manifest_preview_for")
target_detection = _lazy_attr("install", "target_detection")
generate_lessons_from_run = _lazy_attr("lesson", "generate_lessons_from_run")
assess_learnability = _lazy_attr("lesson.learnability", "assess_learnability")
probe_provider = _lazy_attr("llm", "probe_provider")
transport_target_for_base_url = _lazy_attr("llm.provider", "transport_target_for_base_url")
generate_cards_for_run = _lazy_attr("quiz", "generate_cards_for_run")
generate_quiz_from_run = _lazy_attr("quiz", "generate_quiz_from_run")
load_quiz_questions = _lazy_attr("quiz", "load_quiz_questions")
resolve_question_count = _lazy_attr("quiz.adaptive", "resolve_question_count")
backup_review_db = _lazy_attr("review.database", "backup_review_db")
check_review_db = _lazy_attr("review.database", "check_review_db")
finalize_targeted_verify_event = _lazy_attr("review.database", "finalize_targeted_verify_event")
import_cards_from_jsonl = _lazy_attr("review.database", "import_cards_from_jsonl")
import_cards_from_runs = _lazy_attr("review.database", "import_cards_from_runs")
import_results_tsv_lossy = _lazy_attr("review.database", "import_results_tsv_lossy")
initialize_review_db = _lazy_attr("review.database", "initialize_review_db")
list_due_cards = _lazy_attr("review.database", "list_due_cards")
load_result_event_by_run_and_id = _lazy_attr("review.database", "load_result_event_by_run_and_id")
mark_run_cards_stale = _lazy_attr("review.database", "mark_run_cards_stale")
optimize_review_weights = _lazy_attr("review.optimizer", "optimize_weights")
record_card_review = _lazy_attr("review.database", "record_card_review")
restore_review_db = _lazy_attr("review.database", "restore_review_db")
set_card_queue_state = _lazy_attr("review.database", "set_card_queue_state")
upgrade_review_db = _lazy_attr("review.database", "upgrade_review_db")
mark_claim_wrong = _lazy_attr("review.signal", "mark_claim_wrong")
create_app = _lazy_attr("serve", "create_app")
run_mcp_server = _lazy_attr("mcp.server", "run_mcp_server")
append_concepts = _lazy_attr("wiki", "append_concepts")


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
    quiz_mode: Literal["fixed", "auto"] | None = None,
) -> dict[str, Any]:
    return {
        "lang": lang,
        "privacy_mode": privacy_mode,
        "llm.generate_model": generate_model,
        "llm.judge_model": judge_model,
        "serve.port": serve_port,
        "serve.no_browser": no_browser,
        "quiz.quiz_question_count_mode": quiz_mode,
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
    state_dir = validate_state_dir_path(root / ".ahadiff")
    return state_dir, state_dir / "ahadiff.lock"


def _should_open_serve_browser(*, no_browser: bool) -> bool:
    if no_browser:
        return False
    if os.environ.get("CI"):
        return False
    return not (
        sys.platform.startswith("linux")
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
    )


def _viewer_url_for_learn_open(
    *,
    bind_host: str,
    port: int,
    run_id: str | None,
) -> str:
    base_url = f"http://{bind_host}:{port}"
    if run_id is None:
        return base_url
    return f"{base_url}/#/run/{quote(run_id, safe='')}/lesson"


def _open_learn_viewer(
    *,
    serve_config: dict[str, Any],
    run_id: str | None,
) -> None:
    bind_host = str(serve_config["bind_host"])
    port = int(serve_config["port"])
    url = _viewer_url_for_learn_open(bind_host=bind_host, port=port, run_id=run_id)
    console.print(f"[bold]Viewer URL[/bold]: {url}")
    if bind_host != "127.0.0.1":
        console.print("[yellow]Open skipped[/yellow]: serve.bind_host must be 127.0.0.1")
        return
    if not _should_open_serve_browser(no_browser=False):
        console.print("[yellow]Open skipped[/yellow]: headless or CI environment detected")
        return
    try:
        opened = webbrowser.open(url)
    except Exception as exc:
        console.print(f"[yellow]Open skipped[/yellow]: {exc}")
        return
    if not opened:
        console.print("[yellow]Open warning[/yellow]: browser did not report success")


def _state_dir_for_root(root: Path, *, has_git_repo: bool) -> Path:
    return project_state_dir(root) if has_git_repo else validate_state_dir_path(root / ".ahadiff")


def _resolve_output_lang_from_snapshot(snapshot: Any, *, cli_lang: str | None) -> str:
    llm_config = cast("dict[str, Any]", snapshot.values["llm"])
    configured_output_lang = str(llm_config.get("output_lang", "auto"))
    configured_content_lang = (
        configured_output_lang if configured_output_lang != "auto" else str(snapshot.values["lang"])
    )
    return resolve_locale(cli_lang=cli_lang, config_lang=configured_content_lang)


def _structured_output_mode(llm_config: dict[str, Any]) -> Any:
    return llm_config.get("structured_output_mode", "json_object")


def _structured_validation_retries(llm_config: dict[str, Any]) -> int:
    return int(llm_config.get("structured_validation_retries", 0))


def _normalize_provider_base_url(base_url: str, *, provider_class: str) -> str:
    return normalize_provider_base_url(base_url, provider_class=provider_class)


def _provider_config_from_payload(payload: dict[str, Any]) -> ProviderConfig:
    from pydantic import ValidationError

    runtime_payload = {
        key: value for key, value in payload.items() if key in ProviderConfig.model_fields
    }
    try:
        return ProviderConfig.model_validate(runtime_payload)
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
    strict_local_hosts: tuple[str, ...],
    role: str = "generate",
) -> tuple[ProviderConfig, str | None, TransportTarget, bool]:
    llm_config = cast("dict[str, Any]", snapshot.values["llm"])
    model_key = f"{role}_model"
    resolved_model = model or str(llm_config.get(model_key, llm_config["generate_model"]))
    configured_model_override = _configured_model_override_from_snapshot(
        snapshot=snapshot,
        role=role,
        model=model,
    )
    provider_selection_explicit = base_url is not None or provider_name is not None
    provider_selection_from_config = False
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
            config_provider_key = f"{role}_provider"
            config_provider = str(llm_config.get(config_provider_key, "")).strip()
            if config_provider and config_provider in providers_table:
                resolved_name = config_provider
                provider_selection_from_config = True
            elif config_provider and config_provider not in providers_table:
                raise AhaDiffError(
                    f"{role}_provider '{config_provider}' not found in configured providers"
                )
        if resolved_name is None:
            configured_names = sorted(providers_table.keys())
            if len(configured_names) != 1:
                from ahadiff.core.orchestrator import implicit_duplicate_provider_name

                resolved_name = implicit_duplicate_provider_name(
                    providers_table=providers_table,
                    configured_names=configured_names,
                    model=configured_model_override or resolved_model,
                )
                if resolved_name is None:
                    raise AhaDiffError(
                        f"{operation_label} requires --provider when multiple providers "
                        "are configured"
                    )
                provider_selection_from_config = True
            else:
                resolved_name = configured_names[0]
                provider_selection_from_config = True
        raw_config_payload = providers_table.get(resolved_name)
        if not isinstance(raw_config_payload, dict):
            raise AhaDiffError(f"configured provider is missing or invalid: {resolved_name}")
        config_payload = cast("dict[str, Any]", raw_config_payload)
        normalized_payload = dict(config_payload)
        normalized_payload["base_url"] = _normalize_provider_base_url(
            str(normalized_payload["base_url"]),
            provider_class=str(normalized_payload["provider_class"]),
        )
        if configured_model_override is not None:
            normalized_payload["model_name"] = configured_model_override
        provider_config = _provider_config_from_payload(normalized_payload)

    transport_target = transport_target_for_base_url(
        provider_config.base_url,
        local_hosts=local_hosts_for_privacy_mode(
            SecurityConfig(
                local_hosts=local_hosts,
                strict_local_hosts=strict_local_hosts,
            ),
            privacy_mode,
        ),
        strict_local=privacy_mode == "strict_local",
    )
    if provider_selection_from_config and transport_target == "remote":
        provider_selection_explicit = True
    if (
        not provider_selection_explicit
        and privacy_mode == "strict_local"
        and transport_target == "remote"
    ):
        raise AhaDiffError(
            f"{operation_label} requires --provider or --base-url to use a remote provider "
            "while privacy_mode is strict_local"
        )
    effective_api_key = resolve_provider_api_key(provider_config.api_key_env)
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


def _configured_model_override_from_snapshot(
    *,
    snapshot: Any,
    role: str,
    model: str | None,
) -> str | None:
    if model is not None:
        return model
    resolved = getattr(snapshot, "resolved", None)
    if not isinstance(resolved, dict):
        return None
    resolved_settings = cast("dict[str, Any]", resolved)
    setting = resolved_settings.get(f"llm.{role}_model")
    if setting is None or getattr(setting, "source", "default") == "default":
        return None
    value = str(getattr(setting, "value", "")).strip()
    return value or None


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
    strict_local_hosts: tuple[str, ...],
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
        strict_local_hosts=strict_local_hosts,
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


def _normalize_quiz_choice_label(value: str) -> str | None:
    normalized = value.strip().upper()
    if normalized in {"A", "B", "C", "D"}:
        return normalized
    return None


def _prompt_quiz_choice_label() -> str:
    while True:
        label = _normalize_quiz_choice_label(typer.prompt("Your answer"))
        if label is not None:
            return label
        console.print("[red]Please answer A, B, C, or D.[/red]")


def _parse_review_answer(value: str) -> ReviewAnswer:
    normalized = value.strip().casefold()
    if normalized in {"easy", "good", "hard", "wrong"}:
        return cast("ReviewAnswer", normalized)
    raise AhaDiffError("review answer must be one of: easy, good, hard, wrong")


def _validate_review_cli_options(
    *,
    optimize: bool,
    action: str | None,
    card_id: str | None,
    answer: str | None,
) -> None:
    if optimize and (action is not None or card_id is not None or answer is not None):
        raise AhaDiffError("--optimize cannot be combined with --action, --card-id, or --answer")


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
        if review_path.exists() or review_path.is_symlink():
            try:
                with safe_sqlite_connect(review_path) as connection:
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
            except OSError as error:
                raise AhaDiffError(
                    f"review.sqlite could not be opened safely: {review_path} ({error})"
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
    changed_paths: Annotated[
        list[str] | None,
        typer.Option(
            "--changed-path",
            help=(
                "Limit a worktree learn run to this repo-relative path. Repeat for multiple paths."
            ),
        ),
    ] = None,
    patch: Annotated[
        str | None,
        typer.Option("--patch", help="Read a unified diff from FILE or '-' for stdin."),
    ] = None,
    compare: Annotated[
        tuple[Path, Path] | None,
        typer.Option("--compare", help="Compare two files with unified diff semantics."),
    ] = None,
    compare_dir: Annotated[
        tuple[Path, Path] | None,
        typer.Option("--compare-dir", help="Recursively compare two directories."),
    ] = None,
    against_spec: Annotated[
        Path | None,
        typer.Option(
            "--against-spec",
            help="Evaluate this learn run against a repo-local Markdown/text spec.",
        ),
    ] = None,
    spec_semantic_review: Annotated[
        bool,
        typer.Option(
            "--spec-semantic-review",
            help="Opt in to an LLM semantic review layer for --against-spec.",
        ),
    ] = False,
    patch_url: Annotated[
        str | None,
        typer.Option("--patch-url", help="Download a unified diff from an HTTP(S) URL."),
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
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Temporary output language override."),
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
    open_viewer: Annotated[
        bool,
        typer.Option(
            "--open",
            help="Open the local viewer after learn completes.",
        ),
    ] = False,
    quiz_mode: Annotated[
        Literal["fixed", "auto"] | None,
        typer.Option(
            "--quiz-mode",
            help="Override quiz question count mode for this run.",
        ),
    ] = None,
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
        allow_non_git = (
            patch is not None
            or compare is not None
            or compare_dir is not None
            or patch_url is not None
        )
        root, has_git_repo = _resolve_learn_workspace_root(
            repo_root,
            allow_non_git=allow_non_git,
        )
        snapshot = (
            load_config(
                root,
                cli_overrides=_cli_overrides(
                    privacy_mode=privacy_mode,
                    lang=lang,
                    quiz_mode=quiz_mode,
                ),
            )
            if has_git_repo
            else load_workspace_config(
                root,
                cli_overrides=_cli_overrides(
                    privacy_mode=privacy_mode,
                    lang=lang,
                    quiz_mode=quiz_mode,
                ),
            )
        )
        capture_config = cast("dict[str, Any]", snapshot.values["capture"])
        learn_config = cast("dict[str, Any]", snapshot.values["learn"])
        quiz_config = cast("dict[str, Any]", snapshot.values["quiz"])
        llm_config = cast("dict[str, Any]", snapshot.values["llm"])
        provider_limits = cast("dict[str, Any]", snapshot.values["provider"])
        effective_privacy_mode = str(snapshot.values["privacy_mode"])
        resolved_content_lang = _resolve_output_lang_from_snapshot(snapshot, cli_lang=lang)
        security_config = (
            load_security_config(root) if has_git_repo else load_workspace_security_config(root)
        )
        if spec_semantic_review and against_spec is None:
            raise InputError("--spec-semantic-review requires --against-spec")
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
                changed_paths=changed_paths,
                patch=patch,
                compare=compare,
                compare_dir=compare_dir,
                patch_url=patch_url,
                use_graphify=use_graphify,
                max_files=int(capture_config["max_files"]),
                hard_limit=int(capture_config["hard_limit"]),
                max_patch_bytes=int(capture_config["max_patch_bytes"]),
                privacy_mode=effective_privacy_mode,
                content_lang=resolved_content_lang,
            )
            learnability = assess_learnability(
                capture.persisted_patch_text,
                threshold=float(learn_config["learnability_threshold"]),
                force_learn=force_learn,
            )
            capture.metadata["learnability"] = learnability.as_metadata()
            if against_spec is not None:
                source_detail = cast(
                    "dict[str, Any]",
                    capture.metadata.setdefault("source_detail", {}),
                )
                source_detail["against_spec"] = spec_source_reference(
                    workspace_root=root,
                    spec_path=against_spec,
                )
            patch_path, metadata_path = write_input_artifacts(capture)
            run_path = (
                run_dir(capture.run_id, root)
                if has_git_repo
                else (root / ".ahadiff" / "runs" / capture.run_id)
            )
            raw_claims_path: Path | None = None
            claims_output_path: Path | None = None
            lesson_paths = None
            quiz_artifacts = None
            quiz_path: Path | None = None
            cards_path: Path | None = None
            concepts_path: Path | None = None
            lesson_skip_reason: str | None = None
            learn_report = None
            learn_outcome = None
            learn_warnings: list[str] = []
            skipped_run_persisted = False
            if not dry_run and learnability.skip_lesson_quiz:
                learn_warnings.extend(
                    persist_skipped_run(
                        run_path=run_path,
                        run_id=capture.run_id,
                        source_ref=str(capture.run_source.source_ref),
                        learnability_metadata=learnability.as_metadata(),
                        workspace_root=root,
                    )
                )
                skipped_run_persisted = (run_path / "finalized.json").is_file()
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
                        strict_local_hosts=security_config.strict_local_hosts,
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
                        output_lang=resolved_content_lang,
                        structured_output_mode=_structured_output_mode(llm_config),
                        structured_validation_retries=_structured_validation_retries(llm_config),
                    )
                    candidates = load_claim_candidates(
                        raw_claims_path,
                        default_run_id=capture.run_id,
                        enforce_run_id_match=True,
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
                            output_lang=resolved_content_lang,
                            structured_output_mode=_structured_output_mode(llm_config),
                            structured_validation_retries=_structured_validation_retries(
                                llm_config
                            ),
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
                            output_lang=resolved_content_lang,
                            question_count=_effective_quiz_question_count(
                                quiz_config,
                                capture.metadata.get("diff_stats"),
                            ),
                            structured_output_mode=_structured_output_mode(llm_config),
                            structured_validation_retries=_structured_validation_retries(
                                llm_config
                            ),
                        )
                        quiz_path = quiz_artifacts.quiz_path
                        if against_spec is not None:
                            write_spec_alignment_artifact(
                                run_path=run_path,
                                workspace_root=root,
                                spec_path=against_spec,
                            )
                            if spec_semantic_review:
                                judge_provider_name = str(
                                    llm_config.get("judge_provider", "")
                                ).strip()
                                try:
                                    (
                                        semantic_provider_config,
                                        semantic_api_key,
                                        semantic_transport_target,
                                        semantic_provider_selection_explicit,
                                    ) = _resolve_runtime_provider(
                                        snapshot=snapshot,
                                        operation_label="semantic spec alignment review",
                                        provider_name=judge_provider_name or None,
                                        provider_class=provider_class,
                                        base_url=None,
                                        model=None,
                                        api_key_env=api_key_env,
                                        privacy_mode=effective_privacy_mode,
                                        stdin_interactive=sys.stdin.isatty(),
                                        local_hosts=security_config.local_hosts,
                                        strict_local_hosts=security_config.strict_local_hosts,
                                        role="judge",
                                    )
                                    semantic_privacy_mode = (
                                        _privacy_mode_for_explicit_provider_call(
                                            effective_privacy_mode,
                                            transport_target=semantic_transport_target,
                                            provider_selection_explicit=(
                                                semantic_provider_selection_explicit
                                            ),
                                        )
                                    )
                                    run_semantic_alignment_review_for_run(
                                        run_path=run_path,
                                        workspace_root=root,
                                        provider_config=semantic_provider_config,
                                        api_key=semantic_api_key,
                                        security_config=security_config,
                                        privacy_mode=semantic_privacy_mode,
                                        output_lang=resolved_content_lang,
                                        request_timeout_seconds=int(
                                            llm_config["request_timeout_seconds"]
                                        ),
                                        max_concurrent=int(llm_config["max_concurrent"]),
                                        qps_limit=int(provider_limits["qps_limit"]),
                                        retry_attempts=int(llm_config["retry_attempts"]),
                                        input_token_budget=int(
                                            llm_config.get("input_token_budget", 200000)
                                        ),
                                        output_token_budget=int(
                                            llm_config.get("output_token_budget", 50000)
                                        ),
                                    )
                                except Exception as semantic_error:
                                    mark_semantic_alignment_review_degraded(
                                        run_path=run_path,
                                        provider_name=judge_provider_name or "unconfigured",
                                        model_name=str(llm_config.get("judge_model", "")),
                                        reason=str(semantic_error),
                                    )
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
                        if cards_path is not None:
                            try:
                                import_cards_from_jsonl(
                                    _state_dir_for_root(root, has_git_repo=has_git_repo)
                                    / "review.sqlite",
                                    cards_path,
                                    desired_retention=float(learn_config["desired_retention"]),
                                )
                            except Exception as review_import_error:
                                learn_warnings.append(
                                    f"review card import failed: {review_import_error}"
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

        try:
            from ahadiff.core.registry import register_repo

            register_repo(root, capture.state_dir)
        except Exception as reg_error:
            learn_warnings.append(f"registry auto-register failed: {reg_error}")

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
            if quiz_artifacts is not None and quiz_artifacts.misconception_path is not None:
                console.print(
                    f"[bold]Misconception cards[/bold]: {quiz_artifacts.misconception_path}"
                )
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
            for warning in learn_warnings:
                console.print(f"[yellow]Warning[/yellow]: {warning}")
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
        if open_viewer:
            serve_config = cast("dict[str, Any]", snapshot.values["serve"])
            _open_learn_viewer(
                serve_config=serve_config,
                run_id=(
                    capture.run_id if learn_outcome is not None or skipped_run_persisted else None
                ),
            )
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
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Temporary output language override."),
    ] = None,
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        snapshot = (
            load_config(root, cli_overrides=_cli_overrides(lang=lang))
            if has_git_repo
            else load_workspace_config(root, cli_overrides=_cli_overrides(lang=lang))
        )
        _ = resolve_locale(
            cli_lang=lang,
            config_lang=str(snapshot.values["lang"]),
        )  # wired in a future task.
        validate_run_id(run_id)
        run_path = run_dir(run_id, root) if has_git_repo else (root / ".ahadiff" / "runs" / run_id)
        questions = load_quiz_questions(run_path / "quiz" / "quiz.jsonl")
        correct = 0
        for index, question in enumerate(questions, start=1):
            console.print(f"[bold]Question {index}[/bold]: {question.question}")
            if question.answer_mode == "multiple_choice" and question.choices:
                for choice in question.choices:
                    console.print(f"  [bold]{choice.label}[/bold]. {choice.text}")
                selected_label = _prompt_quiz_choice_label()
                selected_choice = next(
                    choice for choice in question.choices if choice.label == selected_label
                )
                if selected_choice.is_correct:
                    correct += 1
                    console.print("[green]Correct[/green]")
                else:
                    expected_choice = next(
                        choice for choice in question.choices if choice.is_correct
                    )
                    console.print(
                        f"[yellow]Expected[/yellow]: "
                        f"{expected_choice.label}. {expected_choice.text}"
                    )
            else:
                answer = typer.prompt("Your answer")
                if _normalize_quiz_answer(answer) == _normalize_quiz_answer(
                    question.expected_answer
                ):
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


@_APP.command("install")
def install_cmd(
    target: Annotated[
        str | None,
        typer.Argument(help=_INSTALL_TARGET_HELP),
    ] = None,
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview writes without changing files."),
    ] = False,
    manifest: Annotated[
        bool,
        typer.Option(
            "--manifest",
            help="Show machine-readable preview/write/uninstall action manifest.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite generated target files when needed."),
    ] = False,
    detect: Annotated[
        bool,
        typer.Option("--detect", help="Show detected AhaDiff install targets."),
    ] = False,
    layer2: Annotated[
        bool,
        typer.Option("--layer2", help="Install opt-in GitHub Action generation workflow."),
    ] = False,
) -> None:
    try:
        root = find_repo_root(repo_root)
        context = _install_context_cls()(repo_root=root, force=force, layer2=layer2)
        if detect:
            table = Table(title="AhaDiff install targets")
            table.add_column("Target")
            table.add_column("Installed")
            for name, installed in target_detection(context).items():
                table.add_row(name, "yes" if installed else "no")
            console.print(table)
            return
        if target is None:
            allowed = ", ".join(available_targets())
            raise AhaDiffError(f"install target is required; expected one of: {allowed}")
        if layer2 and target != "github-action":
            raise AhaDiffError("--layer2 is only supported for: ahadiff install github-action")
        installer = get_target(target)
        if manifest:
            console.print(manifest_preview_for(installer, context))
            return
        if dry_run:
            console.print(installer.preview(context))
            return
        written_paths = installer.write(context)
        console.print(f"[green]Installed[/green] {target}")
        for path in written_paths:
            console.print(f"  - {_display_install_path(path, root)}")
    except ValueError as error:
        _handle_cli_error(AhaDiffError(str(error)))
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_APP.command("uninstall")
def uninstall_cmd(
    target: Annotated[
        str,
        typer.Argument(help=_INSTALL_TARGET_HELP),
    ],
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview removals without changing files."),
    ] = False,
) -> None:
    try:
        root = find_repo_root(repo_root)
        context = _install_context_cls()(repo_root=root)
        installer = get_target(target)
        if dry_run:
            console.print(installer.preview_uninstall(context))
            return
        removed_paths = installer.uninstall(context)
        console.print(f"[green]Uninstalled[/green] {target}")
        if not removed_paths:
            console.print("  - nothing to remove")
        for path in removed_paths:
            console.print(f"  - {_display_install_path(path, root)}")
    except ValueError as error:
        _handle_cli_error(AhaDiffError(str(error)))
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


def _display_install_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


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


def _run_content_lang(run_path: Path) -> str:
    return _run_content_lang_or_none(run_path) or "en"


def _run_content_lang_or_none(run_path: Path) -> str | None:
    metadata_path = run_path / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        payload = safe_json_loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    metadata = cast("dict[str, object]", payload)
    value = metadata.get("content_lang")
    return normalize_locale(value) if isinstance(value, str) else None


def _run_diff_stats_or_none(run_path: Path) -> dict[str, int] | None:
    metadata_path = run_path / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        payload = safe_json_loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    metadata = cast("dict[str, object]", payload)
    diff_stats = metadata.get("diff_stats")
    if not isinstance(diff_stats, dict):
        return None
    return cast("dict[str, int]", diff_stats)


def _effective_quiz_question_count(
    quiz_config: dict[str, Any],
    diff_stats: object,
) -> int:
    return int(
        resolve_question_count(
            str(quiz_config.get("quiz_question_count_mode", "fixed")),
            fixed_count=int(quiz_config["quiz_question_count"]),
            diff_stats=cast("dict[str, int]", diff_stats) if isinstance(diff_stats, dict) else None,
            auto_range_min=int(quiz_config.get("quiz_auto_range_min", 3)),
            auto_range_max=int(quiz_config.get("quiz_auto_range_max", 8)),
        )
    )


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
    quiz_mode: Annotated[
        Literal["fixed", "auto"] | None,
        typer.Option(
            "--quiz-mode",
            help="Override quiz question count mode for regeneration.",
        ),
    ] = None,
) -> None:
    try:
        if only != "quiz":
            raise AhaDiffError("regenerate currently supports only: --only quiz")
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        validate_run_id(run_id)
        run_path = run_dir(run_id, root) if has_git_repo else (root / ".ahadiff" / "runs" / run_id)
        if not run_path.exists():
            raise AhaDiffError(f"run artifacts do not exist: {run_path}")
        snapshot = (
            load_config(root, cli_overrides=_cli_overrides(quiz_mode=quiz_mode))
            if has_git_repo
            else load_workspace_config(root, cli_overrides=_cli_overrides(quiz_mode=quiz_mode))
        )
        llm_config = cast("dict[str, Any]", snapshot.values["llm"])
        learn_config = cast("dict[str, Any]", snapshot.values["learn"])
        quiz_config = cast("dict[str, Any]", snapshot.values["quiz"])
        provider_limits = cast("dict[str, Any]", snapshot.values["provider"])
        effective_privacy_mode = str(snapshot.values["privacy_mode"])
        security_config = (
            load_security_config(root) if has_git_repo else load_workspace_security_config(root)
        )
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        lock_path = lock_file_path(root) if has_git_repo else state_dir / "ahadiff.lock"
        with ExitStack() as lock_stack:
            try:
                lock_stack.enter_context(repo_write_lock(lock_path, command="regenerate quiz"))
            except StorageError as error:
                raise InputError(
                    "another ahadiff session is already running; "
                    "wait for it to finish before regenerating quiz"
                ) from error
            quiz_path = run_path / "quiz" / "quiz.jsonl"
            cards_target_path = run_path / "quiz" / "cards.jsonl"
            misconception_target_path = run_path / "quiz" / "misconception_cards.jsonl"
            quiz_backup = _backup_artifact_for_rollback(quiz_path)
            cards_backup = _backup_artifact_for_rollback(cards_target_path)
            misconception_backup = _backup_artifact_for_rollback(misconception_target_path)
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
                strict_local_hosts=security_config.strict_local_hosts,
            )
            resolved_privacy_mode = _privacy_mode_for_explicit_provider_call(
                effective_privacy_mode,
                transport_target=transport_target,
                provider_selection_explicit=provider_selection_explicit,
            )
            cards_path: Path | None = None
            try:
                output_lang = _run_content_lang(run_path)
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
                    output_lang=output_lang,
                    question_count=_effective_quiz_question_count(
                        quiz_config,
                        _run_diff_stats_or_none(run_path),
                    ),
                    overwrite=True,
                    structured_output_mode=_structured_output_mode(llm_config),
                    structured_validation_retries=_structured_validation_retries(llm_config),
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
                    import_cards_from_jsonl(
                        state_dir / "review.sqlite",
                        cards_path,
                        desired_retention=float(learn_config["desired_retention"]),
                    )
            except Exception:
                _restore_artifact_from_backup(target=quiz_path, backup_path=quiz_backup)
                _restore_artifact_from_backup(target=cards_target_path, backup_path=cards_backup)
                _restore_artifact_from_backup(
                    target=misconception_target_path,
                    backup_path=misconception_backup,
                )
                raise
            finally:
                if quiz_backup is not None:
                    quiz_backup.unlink(missing_ok=True)
                if cards_backup is not None:
                    cards_backup.unlink(missing_ok=True)
                if misconception_backup is not None:
                    misconception_backup.unlink(missing_ok=True)
        console.print(f"[green]Regenerated quiz[/green]: {quiz_artifacts.quiz_path}")
        if quiz_artifacts.misconception_path is not None:
            console.print(f"[bold]Misconception cards[/bold]: {quiz_artifacts.misconception_path}")
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
        typer.Option("--answer", help="Review answer: easy, good, hard, or wrong."),
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
        typer.Option(
            "--optimize",
            help=(
                "Optimize FSRS weights from accumulated review logs "
                "(requires optional optimizer deps)."
            ),
        ),
    ] = False,
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Temporary output language override."),
    ] = None,
) -> None:
    try:
        if scheduler != "fsrs":
            raise AhaDiffError("only the FSRS scheduler is implemented in v0.1")
        _validate_review_cli_options(
            optimize=optimize,
            action=action,
            card_id=card_id,
            answer=answer,
        )
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        snapshot = (
            load_config(root, cli_overrides=_cli_overrides(lang=lang))
            if has_git_repo
            else load_workspace_config(root, cli_overrides=_cli_overrides(lang=lang))
        )
        _ = resolve_locale(
            cli_lang=lang,
            config_lang=str(snapshot.values["lang"]),
        )  # wired in a future task.
        learn_config = cast("dict[str, Any]", snapshot.values["learn"])
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        db_path = state_dir / "review.sqlite"
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="review") as _:
            initialize_review_db(db_path)
            import_warnings: list[str] = []

            def _on_card_import_error(path: Path, exc: Exception) -> None:
                import_warnings.append(f"skipped {path.name}: {exc}")

            imported = import_cards_from_runs(
                db_path,
                state_dir,
                desired_retention=float(learn_config["desired_retention"]),
                on_error=_on_card_import_error,
            )
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
                    desired_retention=float(learn_config["desired_retention"]),
                )
                console.print(f"[green]Reviewed[/green] {update.card_id}")
                console.print(f"[bold]Rating[/bold]: {update.rating}")
                console.print(f"[bold]Next due[/bold]: {update.due_date}")
                console.print(f"[bold]Scaffolding[/bold]: {update.scaffolding_level}")
                return
            if optimize:
                result = optimize_review_weights(db_path)
                weights_text = json.dumps(result.weights, ensure_ascii=False)
                table = Table(title="FSRS optimizer")
                table.add_column("Field", style="cyan")
                table.add_column("Value", style="green")
                table.add_row("Stage", result.stage)
                table.add_row("Reviews", str(result.review_count))
                table.add_row("Effective reviews", str(result.effective_review_count))
                table.add_row("Message", result.message)
                table.add_row("Weights", weights_text)
                console.print(table)
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


@_APP.command("improve")
def improve_cmd(
    suite: Annotated[
        str,
        typer.Option("--suite", help="Improve suite name. Only 'local' is implemented."),
    ] = "local",
    rounds: Annotated[
        int,
        typer.Option("--rounds", min=1, max=20, help="Maximum improve rounds to run."),
    ] = 1,
    resume: Annotated[
        str | None,
        typer.Option("--resume", help="Resume a previous improve session id."),
    ] = None,
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    privacy_mode: Annotated[
        str | None,
        typer.Option("--privacy-mode", help="Temporary CLI override."),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Configured provider alias under [providers.<name>]."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="One-off provider API base URL for improve."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model override for improve."),
    ] = None,
    provider_class: Annotated[
        str,
        typer.Option("--provider-class", help="Provider class for one-off improve."),
    ] = "openai",
    api_key_env: Annotated[
        str,
        typer.Option(
            "--api-key-env",
            help="Env var name used to resolve the API key for improve.",
        ),
    ] = "AHADIFF_PROVIDER_API_KEY",
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Temporary output language override."),
    ] = None,
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=False)
        if not has_git_repo:
            raise AhaDiffError("improve requires a git repository")
        snapshot = load_config(
            root,
            cli_overrides=_cli_overrides(privacy_mode=privacy_mode, lang=lang),
        )
        llm_config = cast("dict[str, Any]", snapshot.values["llm"])
        provider_limits = cast("dict[str, Any]", snapshot.values["provider"])
        effective_privacy_mode = str(snapshot.values["privacy_mode"])
        if effective_privacy_mode == "redacted_remote":
            raise ConfigError(
                "improve does not support redacted_remote privacy mode; "
                "use strict_local or explicit_remote"
            )
        resolved_output_lang = _resolve_output_lang_from_snapshot(snapshot, cli_lang=lang)
        security_config = load_security_config(root)
        state_dir = project_state_dir(root)
        db_path = state_dir / "review.sqlite"
        (
            provider_config,
            effective_api_key,
            transport_target,
            provider_selection_explicit,
        ) = _resolve_runtime_provider(
            snapshot=snapshot,
            operation_label="improve",
            provider_name=provider,
            provider_class=provider_class,
            base_url=base_url,
            model=model,
            api_key_env=api_key_env,
            privacy_mode=effective_privacy_mode,
            stdin_interactive=sys.stdin.isatty(),
            local_hosts=security_config.local_hosts,
            strict_local_hosts=security_config.strict_local_hosts,
        )
        resolved_privacy_mode = _privacy_mode_for_explicit_provider_call(
            effective_privacy_mode,
            transport_target=transport_target,
            provider_selection_explicit=provider_selection_explicit,
        )

        with repo_write_lock(lock_file_path(root), command="improve") as _:
            initialize_review_db(db_path)
            result = run_improve_loop(
                repo_root=root,
                state_dir=state_dir,
                db_path=db_path,
                rounds=rounds,
                suite=suite,
                provider_config=provider_config,
                api_key=effective_api_key,
                security_config=security_config,
                resume_session_id=resume,
                request_timeout_seconds=int(llm_config["request_timeout_seconds"]),
                max_concurrent=int(llm_config["max_concurrent"]),
                qps_limit=int(provider_limits["qps_limit"]),
                retry_attempts=int(llm_config["retry_attempts"]),
                privacy_mode=resolved_privacy_mode,
                output_lang=resolved_output_lang,
            )

        console.print(f"[green]Improve session[/green]: {result.session_id}")
        console.print(f"[bold]Anchor run[/bold]: {result.anchor_run_id}")
        console.print(f"[bold]Rounds completed[/bold]: {result.rounds_completed}")
        if result.outcomes:
            table = Table(title="Improve rounds")
            table.add_column("Round", style="cyan")
            table.add_column("Run", style="magenta")
            table.add_column("Prompt", style="yellow")
            table.add_column("Dimension", style="green")
            table.add_column("Status")
            table.add_column("Score", justify="right")
            for item in result.outcomes:
                table.add_row(
                    str(item.round_index),
                    item.run_id,
                    item.target_prompt,
                    item.target_dimension,
                    item.status,
                    f"{item.overall:.2f}",
                )
            console.print(table)
        else:
            console.print("[yellow]Improve[/yellow]: no new rounds were executed")
        for warning in result.warnings:
            error_console.print(f"[yellow]Warning[/yellow]: {warning}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_APP.command("serve")
def serve_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    port: Annotated[
        int | None,
        typer.Option("--port", min=1, max=65535, help="Port for the local serve API."),
    ] = None,
    no_browser: Annotated[
        bool | None,
        typer.Option("--no-browser", help="Do not open the browser automatically."),
    ] = None,
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Temporary serve locale override."),
    ] = None,
    watch: Annotated[
        bool,
        typer.Option("--watch/--no-watch", help="Watch repo for changes and auto-learn."),
    ] = False,
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        base_snapshot = load_workspace_config(root)
        snapshot = load_workspace_config(
            root,
            cli_overrides=_cli_overrides(serve_port=port, no_browser=no_browser, lang=lang),
        )
        serve_config = cast("dict[str, Any]", snapshot.values["serve"])
        bind_host = str(serve_config["bind_host"])
        if bind_host != "127.0.0.1":
            raise AhaDiffError("serve bind_host must be 127.0.0.1 in v0.1")
        resolved_port = int(serve_config["port"])
        resolved_no_browser = bool(serve_config["no_browser"])
        config_lang = str(base_snapshot.values["lang"])
        resolved_locale = resolve_locale(cli_lang=lang, config_lang=config_lang)
        state_dir.mkdir(parents=True, exist_ok=True)

        serve_state = _serve_state_cls()(
            state_dir=state_dir,
            token=secrets.token_urlsafe(24),
            locale=resolved_locale,
            cli_lang=lang,
            config_lang=config_lang,
            bind_host=bind_host,
            port=resolved_port,
            repo_lock_path=lock_file_path(root) if has_git_repo else state_dir / "ahadiff.lock",
        )
        app_instance = create_app(
            serve_state,
            viewer_dist=root / "viewer" / "dist",
        )

        file_watcher = None
        if watch and has_git_repo:
            from .core.watcher import FileWatcher, WatcherConfig, is_watchdog_available

            if is_watchdog_available():
                watcher_config = WatcherConfig()

                def _on_watch_change(event: Any) -> None:
                    token = serve_state.token
                    try:
                        self_origin = f"http://127.0.0.1:{resolved_port}"
                        status_code = _post_watch_learn_request(
                            self_origin,
                            token,
                            event.changed_paths,
                        )
                        if status_code == 202:
                            console.print(
                                f"[dim]Watch: learn submitted "
                                f"({len(event.changed_paths)} files changed)[/dim]"
                            )
                        else:
                            console.print(f"[dim]Watch: learn request returned {status_code}[/dim]")
                    except Exception as exc:
                        console.print(f"[dim]Watch: learn request failed: {exc}[/dim]")

                file_watcher = FileWatcher(
                    root,
                    on_change=_on_watch_change,
                    config=watcher_config,
                )
                app_instance.state.file_watcher = file_watcher
            else:
                console.print(
                    "[yellow]Warning[/yellow]: watchdog not installed; "
                    "--watch requires: pip install ahadiff[watchdog]"
                )

        url = f"http://127.0.0.1:{resolved_port}"
        console.print(f"[green]Serving[/green] {url}")
        console.print("[bold]Bind[/bold]: 127.0.0.1 only")
        console.print("[bold]Write token header[/bold]: X-AhaDiff-Token")
        if file_watcher is not None:
            console.print("[bold]Watch mode[/bold]: enabled")
        if _should_open_serve_browser(no_browser=resolved_no_browser):
            webbrowser.open(url)

        if file_watcher is not None:
            file_watcher.start()

        import uvicorn

        try:
            uvicorn.run(app_instance, host=bind_host, port=resolved_port, log_level="info")
        finally:
            if file_watcher is not None:
                file_watcher.stop()
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_APP.command("mcp-server")
def mcp_server_cmd(
    repo_root: Annotated[
        Path | None,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = None,
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(
            Path() if repo_root is None else repo_root,
            allow_non_git=True,
        )
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        run_mcp_server(state_dir)
    except Exception as error:  # pragma: no cover - exercised through MCP clients
        _handle_cli_error(error)


def _run_watch_learn(
    wroot: Path,
    dr: bool,
    fl: bool,
    ln: str | None,
    changed_paths: frozenset[str],
) -> bool:
    from .core.orchestrator import LearnRequest, run_learn_pipeline

    try:
        request = LearnRequest(
            workspace_root=wroot,
            unstaged=True,
            include_untracked=True,
            changed_paths=tuple(sorted(changed_paths)),
            dry_run=dr,
            force_learn=fl,
            lang=ln,
        )
        result = run_learn_pipeline(request)
        console.print(
            f"  [bold]Result[/bold]: {result.status}"
            f" (score={result.overall},"
            f" errors={result.recoverable_errors})"
        )
        if result.warnings:
            for w in result.warnings:
                console.print(f"  [yellow]Warning[/yellow]: {w}")
        return True
    except AhaDiffError as exc:
        console.print(f"  [red]Learn failed[/red]: {exc}")
        return False
    except Exception as exc:
        console.print(f"  [red]Unexpected error[/red]: {exc}")
        return False


def _post_watch_learn_request(
    self_origin: str,
    token: str,
    changed_paths: Iterable[str],
) -> int:
    import httpx

    resp = httpx.post(
        f"{self_origin}/api/learn",
        json={
            "changed_paths": list(changed_paths),
            "unstaged": True,
            "include_untracked": True,
        },
        headers={
            "X-AhaDiff-Token": token,
            "Origin": self_origin,
        },
        timeout=5.0,
    )
    return resp.status_code


_WATCH_RETRY_DELAYS = (5.0, 15.0, 30.0)
_WATCH_LEARN_TIMEOUT_SECONDS = 660.0
_WATCH_LEARN_POLL_SECONDS = 0.05


class _WatchLearnRunner:
    def __init__(
        self,
        run_learn: Callable[[frozenset[str]], bool],
        *,
        run_timeout_seconds: float = _WATCH_LEARN_TIMEOUT_SECONDS,
    ) -> None:
        if run_timeout_seconds <= 0:
            raise ValueError("run_timeout_seconds must be positive")
        self._run_learn = run_learn
        self._run_timeout_seconds = run_timeout_seconds
        self._lock = threading.Lock()
        self._running = False
        self._retrigger_pending = False
        self._active_changed_paths: frozenset[str] = frozenset()
        self._queued_changed_paths: set[str] = set()
        self._stop_requested = threading.Event()
        self._consecutive_failures = 0

    def request(self, event: Any) -> None:
        event_paths = frozenset(str(path) for path in event.changed_paths)
        with self._lock:
            if self._stop_requested.is_set():
                return
            if self._running:
                self._retrigger_pending = True
                self._queued_changed_paths.update(event_paths)
                console.print(
                    f"[dim]Queued retrigger ({len(event.changed_paths)} files)"
                    " — learn already in progress[/dim]"
                )
                return
            self._running = True
            self._active_changed_paths = event_paths
        console.print(
            f"[green]Changes detected[/green]: "
            f"{len(event.changed_paths)} file(s), triggering learn..."
        )
        worker = threading.Thread(target=self._run_loop, daemon=True)
        worker.start()

    def stop(self) -> None:
        self._stop_requested.set()

    def _run_loop(self) -> None:
        first_run = True
        try:
            while True:
                if self._stop_requested.is_set():
                    with self._lock:
                        self._running = False
                        self._retrigger_pending = False
                        self._queued_changed_paths.clear()
                    return
                if not first_run:
                    console.print(
                        "[green]Re-triggering[/green] for changes queued during previous learn..."
                    )
                first_run = False
                with self._lock:
                    active_changed_paths = self._active_changed_paths
                outcome = self._run_learn_with_timeout(active_changed_paths)
                if outcome is False:
                    self._consecutive_failures += 1
                    retry_idx = min(self._consecutive_failures - 1, len(_WATCH_RETRY_DELAYS) - 1)
                    if self._consecutive_failures <= len(_WATCH_RETRY_DELAYS):
                        delay = _WATCH_RETRY_DELAYS[retry_idx]
                        console.print(
                            f"[yellow]Retry {self._consecutive_failures}/{len(_WATCH_RETRY_DELAYS)}"
                            f" in {delay:.0f}s[/yellow]"
                        )
                        if self._stop_requested.wait(timeout=delay):
                            with self._lock:
                                self._running = False
                                self._retrigger_pending = False
                                self._queued_changed_paths.clear()
                            return
                        continue
                    console.print("[red]Exhausted retries[/red] — waiting for next file change.")
                    self._consecutive_failures = 0
                else:
                    self._consecutive_failures = 0
                with self._lock:
                    if self._stop_requested.is_set() or not self._retrigger_pending:
                        self._running = False
                        self._retrigger_pending = False
                        self._queued_changed_paths.clear()
                        return
                    self._active_changed_paths = frozenset(self._queued_changed_paths)
                    self._queued_changed_paths.clear()
                    self._retrigger_pending = False
        finally:
            with self._lock:
                self._running = False

    def _run_learn_with_timeout(self, changed_paths: frozenset[str]) -> bool | None:
        done = threading.Event()
        result: bool | None = None
        errors: list[BaseException] = []
        timeout_reported = False

        def _target() -> None:
            nonlocal result
            try:
                result = self._run_learn(changed_paths)
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()

        worker = threading.Thread(target=_target, daemon=True)
        worker.start()
        deadline = time.monotonic() + self._run_timeout_seconds
        while True:
            if self._stop_requested.is_set():
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if not timeout_reported:
                    console.print(
                        "[yellow]Learn run timed out; background worker is still draining[/yellow]"
                    )
                    timeout_reported = True
                wait_for = _WATCH_LEARN_POLL_SECONDS
            else:
                wait_for = min(_WATCH_LEARN_POLL_SECONDS, remaining)
            if done.wait(timeout=wait_for):
                if errors:
                    raise errors[0]
                return bool(result)


def _print_watcher_stop_status(watcher: Any) -> None:
    status = watcher.status()
    if bool(status.get("stop_timed_out")):
        console.print("[yellow]Watcher stop timed out; observer may still be running[/yellow]")
        return
    console.print("[green]Watcher stopped[/green]")


@_APP.command("watch")
def watch_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    debounce: Annotated[
        float,
        typer.Option("--debounce", min=0.1, max=60.0, help="Debounce seconds."),
    ] = 2.0,
    cooldown: Annotated[
        float,
        typer.Option("--cooldown", min=1.0, max=600.0, help="Cooldown seconds."),
    ] = 30.0,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Capture-only, skip lesson generation."),
    ] = False,
    force_learn: Annotated[
        bool,
        typer.Option("--force-learn", help="Skip learnability gate."),
    ] = False,
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="Output language override."),
    ] = None,
) -> None:
    """Watch repository for file changes and auto-trigger learn."""
    import time as _time

    from .core.watcher import FileWatcher, WatcherConfig, is_watchdog_available

    try:
        if not is_watchdog_available():
            raise AhaDiffError(
                "watchdog is not installed; install with: pip install ahadiff[watchdog]"
            )
        root, _has_git = _resolve_learn_workspace_root(repo_root, allow_non_git=False)
        config = WatcherConfig(
            debounce_seconds=debounce,
            cooldown_seconds=cooldown,
        )
        runner = _WatchLearnRunner(
            lambda paths: _run_watch_learn(root, dry_run, force_learn, lang, paths)
        )

        watcher = FileWatcher(root, on_change=runner.request, config=config)
        watcher.start()
        console.print(
            f"[green]Watching[/green] {root} (debounce={debounce}s, cooldown={cooldown}s)"
        )
        console.print("[dim]Press Ctrl+C to stop[/dim]")
        try:
            while watcher.is_running:
                _time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            runner.stop()
            watcher.stop()
            _print_watcher_stop_status(watcher)
    except Exception as error:
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
                strict_local_hosts=security_config.strict_local_hosts,
            )
            resolved_privacy_mode = _privacy_mode_for_explicit_provider_call(
                str(snapshot.values["privacy_mode"]),
                transport_target=transport_target,
                provider_selection_explicit=provider_selection_explicit,
            )
            extract_output_path = candidate_path
            if candidate_path_preexisted:
                extract_output_path = _temporary_sibling_path(candidate_path)
            verify_content_lang = _run_content_lang_or_none(
                run_path
            ) or _resolve_output_lang_from_snapshot(
                snapshot,
                cli_lang=None,
            )
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
                output_lang=verify_content_lang,
                structured_output_mode=_structured_output_mode(llm_config),
                structured_validation_retries=_structured_validation_retries(llm_config),
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
    except Exception as exc:
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


def _verify_ci_artifacts(repo_root: Path) -> None:
    root = find_workspace_root(repo_root)
    state_dir = root / ".ahadiff"
    runs_dir = state_dir / "runs"
    db_path = state_dir / "review.sqlite"
    if not runs_dir.exists():
        console.print("[green]AhaDiff CI verify complete[/green]: no run artifacts found")
        return
    checked = 0
    for run_path in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        marker_path = run_path / "finalized.json"
        if not marker_path.exists():
            continue
        marker = _load_ci_finalized_marker(run_path)
        event_id = marker["event_id"]
        event = load_result_event_by_run_and_id(
            db_path,
            run_id=run_path.name,
            event_id=str(event_id),
        )
        if event is None:
            raise AhaDiffError(f"finalized result event does not exist for run: {run_path.name}")
        checked += 1
    console.print(f"[green]AhaDiff CI verify complete[/green]: {checked} finalized runs checked")


def _load_ci_finalized_marker(run_path: Path) -> dict[str, str | int]:
    marker_path = run_path / "finalized.json"
    try:
        raw_payload: Any = safe_json_loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AhaDiffError(f"finalized marker is invalid for run: {run_path.name}") from exc
    if not isinstance(raw_payload, dict):
        raise AhaDiffError(f"finalized marker is invalid for run: {run_path.name}")
    payload = cast("dict[str, object]", raw_payload)
    if payload.get("run_id") != run_path.name:
        raise AhaDiffError(f"finalized marker run_id mismatch for run: {run_path.name}")
    event_id = payload.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise AhaDiffError(f"finalized marker is missing event_id for run: {run_path.name}")
    finalized_at = payload.get("finalized_at")
    if not isinstance(finalized_at, str) or not finalized_at:
        raise AhaDiffError(f"finalized marker is missing finalized_at for run: {run_path.name}")
    artifact_count = payload.get("artifact_count")
    if not isinstance(artifact_count, int) or artifact_count < 0:
        raise AhaDiffError(f"finalized marker is missing artifact_count for run: {run_path.name}")
    checksum = payload.get("checksum")
    if not isinstance(checksum, str) or not checksum:
        raise AhaDiffError(f"finalized marker is missing checksum for run: {run_path.name}")
    try:
        actual_count, actual_checksum = finalized_artifact_digest(run_path)
    except Exception as exc:
        raise AhaDiffError(
            f"finalized artifacts are invalid for run: {run_path.name}: {exc}"
        ) from exc
    if artifact_count != actual_count or checksum != actual_checksum:
        raise AhaDiffError(f"finalized marker checksum mismatch for run: {run_path.name}")
    return {
        "run_id": run_path.name,
        "event_id": event_id,
        "finalized_at": finalized_at,
        "artifact_count": artifact_count,
        "checksum": checksum,
    }


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


@_APP.command("benchmark")
def benchmark_cmd(
    suite: Annotated[
        str,
        typer.Option("--suite", help="Benchmark suite to run."),
    ] = "local",
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    manifest: Annotated[
        Path,
        typer.Option("--manifest", help="Benchmark manifest path."),
    ] = Path("benchmarks/manifest.json"),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Output path for benchmark report JSON."),
    ] = None,
    model_id: Annotated[
        str,
        typer.Option("--model-id", help="Model identifier recorded for comparability."),
    ] = "deterministic-fixture",
    api_family_version: Annotated[
        str,
        typer.Option("--api-family-version", help="API family/version recorded for comparability."),
    ] = "none",
    output_lang: Annotated[
        str,
        typer.Option("--output-lang", help="Output language key recorded for comparability."),
    ] = "en",
) -> None:
    try:
        root = find_workspace_root(repo_root)
        manifest_path = manifest if manifest.is_absolute() else root / manifest
        manifest_path = manifest_path.resolve()
        if not manifest_path.is_relative_to(root):
            raise InputError(
                f"benchmark manifest path must be inside workspace root: {manifest_path}"
            )
        output_path = output or root / ".ahadiff" / "benchmarks" / f"{suite}-report.json"
        if not output_path.is_absolute():
            output_path = root / output_path
        resolved_output_lang = normalize_locale(output_lang)
        if resolved_output_lang is None:
            console.print(
                f"[yellow]Warning[/yellow]: unsupported --output-lang {output_lang!r}; "
                "falling back to 'en'"
            )
            resolved_output_lang = "en"
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="benchmark") as _:
            report = run_benchmark_suite(
                manifest_path,
                suite=suite,
                model_id=model_id,
                api_family_version=api_family_version,
                output_lang=resolved_output_lang,
            )
            write_benchmark_report(output_path, report)
        console.print(f"[green]Benchmark complete[/green]: {report.suite_id}")
        console.print(f"[bold]Suite digest[/bold]: {report.suite_digest}")
        console.print(f"[bold]Eval bundle[/bold]: {report.eval_bundle_version}")
        console.print(f"[bold]API family[/bold]: {report.api_family_version}")
        console.print(f"[bold]Comparable entries[/bold]: {report.comparable_entry_count}")
        console.print(f"[bold]Excluded degraded[/bold]: {report.excluded_degraded_count}")
        console.print(f"[bold]Mean score[/bold]: {report.mean_score:.2f}")
        console.print(f"[bold]Claim verification rate[/bold]: {report.claim_verification_rate:.4f}")
        console.print(f"[bold]Output[/bold]: {output_path}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_APP.command("verify")
def verify_cmd(
    run_id: Annotated[
        str | None,
        typer.Argument(help="Run id under .ahadiff/runs/<run_id>."),
    ] = None,
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
    ci: Annotated[
        bool,
        typer.Option("--ci", help="Validate persisted AhaDiff artifacts for CI."),
    ] = False,
) -> None:
    try:
        if ci:
            _verify_ci_artifacts(repo_root)
            return
        if run_id is None:
            raise AhaDiffError("verify requires RUN_ID unless --ci is used")
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


@_EXPORT_APP.command("preview")
def export_preview_cmd(
    run_id: Annotated[
        str,
        typer.Argument(help="Run ID (e.g. run_019dc3...)."),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", help="Output directory for the static preview bundle."),
    ],
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
    privacy_mode: Annotated[
        str,
        typer.Option(
            "--privacy-mode",
            help="strict_local | redacted_remote | explicit_remote.",
        ),
    ] = "strict_local",
) -> None:
    from .export.preview import build_zip_bytes, export_preview
    from .export.writer import safe_write_export_file

    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        output_dir = out.expanduser().resolve()
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="export preview") as _:
            manifest = export_preview(
                run_id=run_id,
                output_path=output_dir,
                state_dir=state_dir,
                privacy_mode=privacy_mode,
            )
            zip_bytes = build_zip_bytes(output_dir)
            zip_path = output_dir.with_suffix(output_dir.suffix + ".zip")
            safe_write_export_file(zip_path.parent, zip_path.name, zip_bytes)
        console.print(f"[green]Preview[/green] {output_dir}")
        console.print(f"[green]Archive[/green] {zip_path}")
        console.print(f"[dim]digest[/dim] {manifest.digest}")
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
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="db check") as _:
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
        _repo = None
        try:
            from ahadiff.git.repo import open_repo as _open_repo

            _repo = _open_repo(root)
        except InputError:
            pass
        status = detect_graphify_status(root, use_graphify=None, repo=_repo)
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


@_CONCEPTS_APP.command("verify")
def concepts_verify_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
) -> None:
    """Check JSONL ↔ SQLite consistency for the concepts derived cache."""
    try:
        from ahadiff.wiki.concepts import verify_concepts_consistency

        root = find_repo_root(repo_root)
        sd = project_state_dir(root)
        db_path = sd / "review.sqlite"
        jsonl_path = sd / "concepts.jsonl"
        ok, discrepancies = verify_concepts_consistency(db_path, jsonl_path)
        if ok:
            console.print("[green]Consistent[/green]: JSONL and SQLite match.")
        else:
            console.print(f"[yellow]Drift detected[/yellow]: {len(discrepancies)} discrepancies")
            for d in discrepancies[:20]:
                console.print(f"  • {d}")
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as error:
        _handle_cli_error(error)


@_CONCEPTS_APP.command("list")
def concepts_list_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=500, help="Maximum concepts to print."),
    ] = 50,
) -> None:
    """List concepts from review.sqlite, falling back to concepts.jsonl."""
    try:
        root = find_repo_root(repo_root)
        sd = project_state_dir(root)
        db_path = sd / "review.sqlite"
        rows: list[dict[str, object]] = []
        if db_path.exists():
            from ahadiff.review.database import load_concepts_from_db

            rows = list(load_concepts_from_db(db_path, limit=limit))
        if not rows:
            jsonl_path = sd / "concepts.jsonl"
            if jsonl_path.exists():
                with jsonl_path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        payload = safe_json_loads(stripped)
                        if isinstance(payload, dict):
                            rows.append(cast("dict[str, object]", payload))
                        if len(rows) >= limit:
                            break
        if not rows:
            console.print("[yellow]No concepts found[/yellow]")
            return
        table = Table(title="Concepts")
        table.add_column("term_key")
        table.add_column("display_name")
        table.add_column("lang")
        table.add_column("graphify")
        for row in rows:
            term_key = str(row.get("term_key", ""))
            display_name = str(row.get("display_name") or row.get("concept") or "")
            lang = str(row.get("lang") or "")
            graphify = str(row.get("graphify_node_id") or "")
            table.add_row(term_key, display_name, lang, graphify)
        console.print(table)
    except Exception as error:
        _handle_cli_error(error)


@_CONCEPTS_APP.command("export")
def concepts_export_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
) -> None:
    """Export concepts from SQLite back to concepts.jsonl (atomic overwrite)."""
    try:
        from ahadiff.wiki.concepts import export_concepts_from_db

        root = find_repo_root(repo_root)
        with repo_write_lock(lock_file_path(root), command="concepts export") as _:
            exported_path = export_concepts_from_db(project_state_dir(root))
        console.print(f"[green]Exported[/green] to {exported_path}")
    except Exception as error:
        _handle_cli_error(error)


@_CONCEPTS_APP.command("sync")
def concepts_sync_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
) -> None:
    """Sync concepts.jsonl into review.sqlite."""
    try:
        from ahadiff.review import import_concepts_from_jsonl

        root = find_repo_root(repo_root)
        sd = project_state_dir(root)
        db_path = sd / "review.sqlite"
        jsonl_path = sd / "concepts.jsonl"
        if not jsonl_path.exists():
            raise InputError(f"concepts JSONL does not exist: {jsonl_path}")
        with repo_write_lock(lock_file_path(root), command="concepts sync") as _:
            count = import_concepts_from_jsonl(db_path, jsonl_path)
        console.print(f"[green]Synced[/green] {count} concepts to {db_path}")
    except Exception as error:
        _handle_cli_error(error)


@_CONCEPTS_APP.command("rollback")
def concepts_rollback_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be exported without writing."),
    ] = False,
) -> None:
    """Rollback: overwrite concepts.jsonl from SQLite (guarded, atomic)."""
    try:
        from ahadiff.wiki.concepts import rollback_concepts_to_jsonl, verify_concepts_consistency

        root = find_repo_root(repo_root)
        sd = project_state_dir(root)
        db_path = sd / "review.sqlite"
        jsonl_path = sd / "concepts.jsonl"
        if dry_run:
            ok, discrepancies = verify_concepts_consistency(db_path, jsonl_path)
            if ok:
                console.print("[green]Already consistent[/green] — rollback not needed.")
            else:
                msg = f"[yellow]Would rollback[/yellow]: {len(discrepancies)} discrepancies"
                console.print(msg)
                for d in discrepancies[:20]:
                    console.print(f"  • {d}")
                raise typer.Exit(code=1)
            return
        with repo_write_lock(lock_file_path(root), command="concepts rollback") as _:
            count = rollback_concepts_to_jsonl(db_path, jsonl_path)
        console.print(f"[green]Rolled back[/green] {count} concepts to {jsonl_path}")
    except typer.Exit:
        raise
    except Exception as error:
        _handle_cli_error(error)


@_CONCEPTS_APP.command("lint")
def concepts_lint_cmd(
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or any path inside it."),
    ] = Path(),
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Lint mode (only 'deterministic' is implemented).",
        ),
    ] = "deterministic",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print findings only; do not write to review.sqlite."),
    ] = False,
    orphan_threshold: Annotated[
        int,
        typer.Option(
            "--orphan-threshold",
            min=0,
            max=1000,
            help="Concept is orphaned if not referenced by the last N runs.",
        ),
    ] = 5,
    line_drift_threshold: Annotated[
        int,
        typer.Option(
            "--line-drift-threshold",
            min=0,
            max=10000,
            help="Mark stale when source_refs line drifts by more than N lines.",
        ),
    ] = 50,
) -> None:
    """Run deterministic concept health checks (orphan / stale)."""
    try:
        if mode != "deterministic":
            raise InputError("only --mode=deterministic is implemented in this phase")
        from ahadiff.review.database import (
            connect_review_db,
            load_concepts_from_db,
        )
        from ahadiff.wiki.lint import run_deterministic_lint

        root = find_repo_root(repo_root)
        sd = project_state_dir(root)
        db_path = sd / "review.sqlite"

        concepts: list[dict[str, Any]] = []
        if db_path.exists():
            cursor: str | None = None
            while True:
                rows = load_concepts_from_db(db_path, limit=500, after_term_key=cursor)
                if not rows:
                    break
                concepts.extend(dict(row) for row in rows)
                last_key = rows[-1].get("term_key")
                if not isinstance(last_key, str) or not last_key:
                    break
                cursor = last_key
        else:
            jsonl_path = sd / "concepts.jsonl"
            if jsonl_path.exists():
                with jsonl_path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        payload = safe_json_loads(stripped)
                        if isinstance(payload, dict):
                            concepts.append(cast("dict[str, Any]", payload))

        recent_runs: list[str] = []
        if db_path.exists():
            try:
                with connect_review_db(db_path) as connection:
                    rows_cursor = connection.execute(
                        """
                        SELECT DISTINCT run_id FROM result_events
                        ORDER BY timestamp DESC
                        LIMIT 50
                        """
                    )
                    for row in rows_cursor.fetchall():
                        run_id = row[0] if not hasattr(row, "keys") else row["run_id"]
                        if isinstance(run_id, str) and run_id:
                            recent_runs.append(run_id)
            except Exception:
                recent_runs = []

        if dry_run:
            summary = run_deterministic_lint(
                concepts=concepts,
                recent_runs=recent_runs,
                repo_root=root,
                db_path=None,
                dry_run=True,
                orphan_threshold=orphan_threshold,
                line_drift_threshold=line_drift_threshold,
            )
        else:
            with repo_write_lock(lock_file_path(root), command="concepts lint") as _:
                summary = run_deterministic_lint(
                    concepts=concepts,
                    recent_runs=recent_runs,
                    repo_root=root,
                    db_path=db_path,
                    dry_run=False,
                    orphan_threshold=orphan_threshold,
                    line_drift_threshold=line_drift_threshold,
                )

        if not summary.findings:
            console.print("[green]No concept health findings[/green]")
            console.print(f"lint_id: {summary.lint_id}")
            return

        table = Table(title=f"Concept lint findings ({len(summary.findings)})")
        table.add_column("term_key")
        table.add_column("current")
        table.add_column("new")
        table.add_column("reason")
        for finding in summary.findings:
            table.add_row(
                finding.term_key,
                finding.current_status,
                finding.new_status,
                finding.reason,
            )
        console.print(table)
        console.print(f"lint_id: {summary.lint_id} (mode={summary.mode})")
        if dry_run:
            console.print("[yellow]Dry run[/yellow]: no DB writes")
    except typer.Exit:
        raise
    except Exception as error:
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
            local_hosts=local_hosts_for_privacy_mode(security_config, resolved_privacy_mode),
            strict_local=resolved_privacy_mode == "strict_local",
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


@_CHALLENGE_APP.command("build")
def challenge_build_cmd(
    run_id: Annotated[str, typer.Argument(help="Source run id to challenge from.")],
    challenge_id: Annotated[
        str | None,
        typer.Option("--challenge-id", help="Optional preset challenge id."),
    ] = None,
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        snapshot = load_config(root) if has_git_repo else load_workspace_config(root)
        from ahadiff.challenge import (
            build_challenge,
            create_state,
            ensure_rebuild_allowed,
            is_feature_enabled,
            write_manifest,
            write_state,
        )

        if not is_feature_enabled(snapshot):
            raise InputError(
                "challenge engine is disabled; set [challenge] enabled = true in config.toml "
                "to opt in"
            )
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        _, lock_path = _state_dir_and_lock_path(repo_root)
        with repo_write_lock(lock_path, command="challenge build") as _:
            manifest = build_challenge(
                source_run_id=run_id,
                state_dir=state_dir,
                challenge_id=challenge_id,
            )
            ensure_rebuild_allowed(state_dir, manifest.challenge_id)
            challenge_state = create_state(
                challenge_id=manifest.challenge_id,
                source_run_id=run_id,
            )
            write_state(state_dir, challenge_state)
            write_manifest(state_dir, manifest)
        console.print(f"[green]Built challenge[/green] {manifest.challenge_id}")
        console.print(f"[bold]Source run[/bold]: {run_id}")
        console.print(f"[bold]Canonical claims[/bold]: {len(manifest.canonical_claim_ids)}")
        console.print(f"[bold]Stage[/bold]: {challenge_state.stage.value}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


@_CHALLENGE_APP.command("status")
def challenge_status_cmd(
    challenge_id: Annotated[
        str | None,
        typer.Argument(help="Challenge id to inspect; omit to list all challenges."),
    ] = None,
    repo_root: Annotated[
        Path,
        typer.Option("--repo-root", help="Repository root or workspace root."),
    ] = Path(),
) -> None:
    try:
        root, has_git_repo = _resolve_learn_workspace_root(repo_root, allow_non_git=True)
        snapshot = load_config(root) if has_git_repo else load_workspace_config(root)
        from ahadiff.challenge import is_feature_enabled, read_state
        from ahadiff.challenge.state import validate_challenge_id

        if not is_feature_enabled(snapshot):
            raise InputError(
                "challenge engine is disabled; set [challenge] enabled = true in config.toml "
                "to opt in"
            )
        state_dir = _state_dir_for_root(root, has_git_repo=has_git_repo)
        challenges_dir = state_dir / "challenges"
        if challenge_id is None:
            if not challenges_dir.exists():
                console.print("[yellow]no challenges found[/yellow]")
                return
            entries = sorted(p.name for p in challenges_dir.iterdir() if p.is_dir())
            if not entries:
                console.print("[yellow]no challenges found[/yellow]")
                return
            for entry in entries:
                try:
                    validate_challenge_id(entry)
                    challenge_state = read_state(state_dir, entry)
                except Exception:
                    continue
                console.print(
                    f"[bold]{challenge_state.challenge_id}[/bold]: "
                    f"stage={challenge_state.stage.value} "
                    f"source_run={challenge_state.source_run_id}"
                )
            return

        validate_challenge_id(challenge_id)
        challenge_state = read_state(state_dir, challenge_id)
        console.print(f"[bold]Challenge[/bold]: {challenge_state.challenge_id}")
        console.print(f"[bold]Stage[/bold]: {challenge_state.stage.value}")
        console.print(f"[bold]Source run[/bold]: {challenge_state.source_run_id}")
        console.print(f"[bold]Created[/bold]: {challenge_state.created_at_utc}")
        console.print(f"[bold]Updated[/bold]: {challenge_state.updated_at_utc}")
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        _handle_cli_error(error)


def main() -> None:
    app()()


__all__ = [
    "app",
    "challenge_build_cmd",
    "challenge_status_cmd",
    "claims_cmd",
    "config_show_cmd",
    "doctor_cmd",
    "graph_import_cmd",
    "graph_refresh_cmd",
    "graph_status_cmd",
    "improve_cmd",
    "init_cmd",
    "learn_cmd",
    "main",
    "maint_clean_orphans_cmd",
    "provider_test_cmd",
    "serve_cmd",
    "unlock_cmd",
]
