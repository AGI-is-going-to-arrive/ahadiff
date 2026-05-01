from __future__ import annotations

import collections.abc as _collections_abc
import errno
import hashlib
import json
import logging
import os
import pathlib as _pathlib
import selectors
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import unified_diff
from queue import Queue
from typing import TYPE_CHECKING, Any, BinaryIO, Literal, cast

from ahadiff.contracts import RunSource
from ahadiff.core.config import DEFAULT_CONFIG, load_config, load_workspace_config
from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.ids import make_run_id
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import (
    ensure_state_parent_dir,
    project_state_dir,
    run_dir,
    validate_state_dir_path,
    validate_state_path_no_symlinks,
)
from ahadiff.graphify import parse_graph_json_text
from ahadiff.safety.audit import append_audit_record, build_redaction_audit_record
from ahadiff.safety.ignore import (
    AllowlistPolicy,
    IgnoreMatcher,
    canonicalize_path_text,
    is_ignored_path,
    load_ignore_matcher,
    load_workspace_allowlist_policy,
    resolve_safe_path_from_root,
)
from ahadiff.safety.injection import protect_untrusted_text
from ahadiff.safety.redact import RedactionPipelineResult, redaction_pipeline

from .download import download_patch_url
from .line_map import build_line_map, serialize_line_map_payload
from .parser import parse_unified_diff, split_unified_diff_segments
from .path_tokens import normalize_diff_path_token, parse_diff_git_header_paths
from .repo import (
    GitRepo,
    ensure_head_exists,
    ensure_no_merge_conflicts,
    first_parent_or_empty_tree,
    open_repo,
    parent_count,
    resolve_commitish,
    resolve_ref_range,
    run_git,
    run_git_bytes,
)
from .symbols import SymbolExtractorMode, extract_symbols, serialize_symbols_payload

if TYPE_CHECKING:
    from collections.abc import Iterable
else:
    Iterable = _collections_abc.Iterable

Path = _pathlib.Path

ContractSourceKind = Literal[
    "git_ref",
    "git_staged",
    "git_staged_unstaged",
    "git_unstaged",
    "git_since",
    "patch_file",
    "patch_stdin",
    "file_compare",
]

_COMPARE_DIR_MAX_FILES = 10_000
_COMPARE_DIR_MAX_DIRS = 1_000
_COMPARE_DIR_MAX_DEPTH = 64
_MAX_PATCH_BYTES_HARD_CAP = 50 * 1024 * 1024
_PATCH_URL_MAX_BYTES = 512 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_GIT_PATCH_PROCESS_WAIT_TIMEOUT_SECONDS = 300


def _empty_metadata_texts() -> dict[str, str]:
    return {}


@dataclass(frozen=True)
class GraphifyStatus:
    source_path: Path
    imported_path: Path
    enabled: bool
    source_exists: bool
    imported_exists: bool
    has_graph: bool
    freshness: str | None
    provenance: dict[str, str]


@dataclass(frozen=True)
class CapturedDiff:
    run_id: str
    workspace_root: Path
    state_dir: Path
    run_source: RunSource
    raw_patch_text: str
    persisted_patch_text: str
    metadata: dict[str, Any]
    redaction_result: RedactionPipelineResult
    graphify_status: GraphifyStatus
    before_text_by_path: dict[str, str]
    after_text_by_path: dict[str, str]
    symbol_extractor: SymbolExtractorMode


@dataclass(frozen=True)
class _RawCapture:
    source_kind: ContractSourceKind
    source_ref: str
    capability_level: Literal[1, 2, 3]
    raw_patch_text: str
    base_ref: str | None
    head_ref: str | None
    source_detail: dict[str, Any]
    branch_names: tuple[str, ...]
    tag_names: tuple[str, ...]
    resolved_files: dict[str, str]
    before_text_by_path: dict[str, str]
    after_text_by_path: dict[str, str]
    metadata_texts: dict[str, str] = field(default_factory=_empty_metadata_texts)


@dataclass(frozen=True)
class _PatchSegment:
    path: str
    text: str
    line_count: int
    changed_lines: int
    hunk_count: int
    binary_only: bool


_GRAPHIFY_RELATIVE_PATH = Path("graphify-out") / "graph.json"
_GRAPHIFY_REV_LIST_MAX_COUNT = 51
_TRUNCATED_MARKER = "[truncated]\n"
_ARTIFACT_SET_SCHEMA = "ahadiff.artifact_set"
_ARTIFACT_SET_SCHEMA_VERSION = 1
_TEXT_MAP_SCHEMA = "ahadiff.text_map"
_TEXT_MAP_SCHEMA_VERSION = 1
log = logging.getLogger(__name__)


def capture_patch(
    *,
    workspace_root: Path,
    revision: str | None = None,
    last: bool = False,
    since: str | None = None,
    author: str | None = None,
    staged: bool = False,
    unstaged: bool = False,
    include_untracked: bool = False,
    patch: str | None = None,
    compare: tuple[Path, Path] | None = None,
    compare_dir: tuple[Path, Path] | None = None,
    patch_url: str | None = None,
    use_graphify: bool | None = None,
    max_files: int | None = None,
    hard_limit: int | None = None,
    max_patch_bytes: int | None = None,
    symbol_extractor: SymbolExtractorMode | None = None,
    privacy_mode: str = "strict_local",
    content_lang: str = "en",
) -> CapturedDiff:
    effective_max_files = (
        int(DEFAULT_CONFIG["capture"]["max_files"]) if max_files is None else max_files
    )
    effective_hard_limit = (
        int(DEFAULT_CONFIG["capture"]["hard_limit"]) if hard_limit is None else hard_limit
    )
    effective_max_patch_bytes = _effective_max_patch_bytes(max_patch_bytes)
    _validate_capture_limits(
        max_files=effective_max_files,
        hard_limit=effective_hard_limit,
        max_patch_bytes=effective_max_patch_bytes,
    )
    workspace_root = workspace_root.expanduser().resolve()
    effective_symbol_extractor = _effective_symbol_extractor(
        workspace_root,
        symbol_extractor=symbol_extractor,
    )
    raw_capture = _capture_input(
        workspace_root=workspace_root,
        revision=revision,
        last=last,
        since=since,
        author=author,
        staged=staged,
        unstaged=unstaged,
        include_untracked=include_untracked,
        patch=patch,
        compare=compare,
        compare_dir=compare_dir,
        patch_url=patch_url,
        max_files=effective_max_files,
        max_patch_bytes=effective_max_patch_bytes,
    )
    raw_capture = _filter_ignored_capture(workspace_root, raw_capture)
    _repo: GitRepo | None = None
    if _has_git_root(workspace_root):
        with suppress(InputError, OSError):
            _repo = open_repo(workspace_root)
    graphify_status = detect_graphify_status(
        workspace_root,
        use_graphify=use_graphify,
        repo=_repo,
    )

    redaction_result = redaction_pipeline(
        raw_capture.raw_patch_text,
        repo_root=workspace_root if _has_git_root(workspace_root) else None,
        policy=_resolve_policy(workspace_root),
        resolved_files=raw_capture.resolved_files,
        branch_names=raw_capture.branch_names,
        tag_names=raw_capture.tag_names,
        metadata_texts=raw_capture.metadata_texts,
    )
    protected_patch = protect_untrusted_text(
        redaction_result.redacted_text,
        source_name="patch.diff",
        source_kind="raw_patch",
    ).protected_text
    persisted_patch_text, selection = _apply_capture_limits(
        protected_patch,
        max_files=effective_max_files,
        hard_limit=effective_hard_limit,
    )

    degraded_flags = dict(raw_capture_extra_degraded_flags(raw_capture))
    if selection["binary_only"]:
        degraded_flags["binary_only"] = True
    if selection["diff_clipped"]:
        degraded_flags["diff_clipped"] = True
    if selection["file_count_exceeded"]:
        degraded_flags["file_count_exceeded"] = True

    run_source = RunSource(
        source_kind=raw_capture.source_kind,
        source_ref=raw_capture.source_ref,
        capability_level=raw_capture.capability_level,
        degraded_flags=cast("dict[Any, bool]", degraded_flags),
    )

    state_dir = _state_dir(workspace_root)
    metadata: dict[str, Any] = {
        "run_id": make_run_id(),
        "repo": str(workspace_root.name) if _has_git_root(workspace_root) else None,
        "base_ref": raw_capture.base_ref,
        "head_ref": raw_capture.head_ref,
        "source_kind": run_source.source_kind,
        "source_ref": run_source.source_ref,
        "capability_level": run_source.capability_level,
        "source_detail": raw_capture.source_detail,
        "created_at": _utc_now(),
        "mode": "learn",
        "privacy_mode": privacy_mode,
        "content_lang": content_lang,
        "allowlist_digest": redaction_result.allowlist_digest,
        "degraded_flags": run_source.degraded_flags,
        "capability_flags": _capability_flags(
            run_source.capability_level,
            graphify_status.has_graph,
        ),
        "selected_files": selection["selected_files"],
        "omitted_files": selection["omitted_files"],
        "ranking_version": "v1",
        "has_graph": graphify_status.has_graph,
        "graphify": {
            "enabled": graphify_status.enabled,
            "source_exists": graphify_status.source_exists,
            "freshness": graphify_status.freshness,
            "provenance": graphify_status.provenance,
        },
    }

    return CapturedDiff(
        run_id=metadata["run_id"],
        workspace_root=workspace_root,
        state_dir=state_dir,
        run_source=run_source,
        raw_patch_text=raw_capture.raw_patch_text,
        persisted_patch_text=persisted_patch_text,
        metadata=metadata,
        redaction_result=redaction_result,
        graphify_status=graphify_status,
        before_text_by_path=raw_capture.before_text_by_path,
        after_text_by_path=raw_capture.after_text_by_path,
        symbol_extractor=effective_symbol_extractor,
    )


def write_input_artifacts(capture: CapturedDiff) -> tuple[Path, Path]:
    line_map_payload, symbols_payload = _structured_artifact_payloads(capture)
    metadata_text = _redact_json_artifact(
        _render_json_text(_metadata_with_symbol_extractor(capture, symbols_payload)),
        capture.workspace_root,
    )
    redacted_line_map = _redact_json_artifact(
        _render_json_text(line_map_payload),
        capture.workspace_root,
    )
    redacted_symbols = _redact_json_artifact(
        _render_json_text(symbols_payload),
        capture.workspace_root,
    )
    before_text_payload = _text_map_payload(
        artifact="before_text_by_path",
        texts=capture.before_text_by_path,
    )
    after_text_payload = _text_map_payload(
        artifact="after_text_by_path",
        texts=capture.after_text_by_path,
    )
    redacted_before_text = _redact_json_artifact(
        _render_json_text(before_text_payload),
        capture.workspace_root,
    )
    redacted_after_text = _redact_json_artifact(
        _render_json_text(after_text_payload),
        capture.workspace_root,
    )

    artifact_texts: dict[str, str] = {
        "patch.diff": capture.persisted_patch_text,
        "metadata.json": metadata_text,
        "line_map.json": redacted_line_map,
        "symbols.json": redacted_symbols,
        "before_text_by_path.json": redacted_before_text,
        "after_text_by_path.json": redacted_after_text,
    }
    artifact_set_payload = _artifact_set_payload(
        capture,
        artifact_texts,
        line_map_payload,
        symbols_payload,
        before_text_payload,
        after_text_payload,
    )
    artifact_texts["artifact_set.json"] = _redact_json_artifact(
        _render_json_text(artifact_set_payload),
        capture.workspace_root,
    )

    artifacts_dir = _artifacts_dir(capture)
    _publish_artifact_directory(artifacts_dir, artifact_texts)
    patch_path = artifacts_dir / "patch.diff"
    metadata_path = artifacts_dir / "metadata.json"

    audit_path = capture.state_dir / "audit.jsonl"
    private_audit_path = capture.state_dir / "audit.private.jsonl"
    audit_record = build_redaction_audit_record(
        capture.redaction_result,
        privacy_mode=str(capture.metadata["privacy_mode"]),
    )
    append_audit_record(audit_path, audit_record)
    if capture.metadata["privacy_mode"] == "strict_local":
        append_audit_record(private_audit_path, audit_record)
    return patch_path, metadata_path


def _artifacts_dir(capture: CapturedDiff) -> Path:
    return (
        run_dir(capture.run_id, capture.workspace_root)
        if _has_git_root(capture.workspace_root)
        else capture.state_dir / "runs" / capture.run_id
    )


def _publish_artifact_directory(artifacts_dir: Path, artifact_texts: dict[str, str]) -> None:
    ensure_state_parent_dir(artifacts_dir)
    validate_state_path_no_symlinks(artifacts_dir, allow_missing_leaf=True)
    tmp_dir = artifacts_dir.parent / f".{artifacts_dir.name}.tmp"
    validate_state_path_no_symlinks(tmp_dir, allow_missing_leaf=True)
    if tmp_dir.exists():
        _remove_tree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=False)
    validate_state_path_no_symlinks(tmp_dir, allow_missing_leaf=False)
    try:
        for name, text in artifact_texts.items():
            _atomic_write_text(tmp_dir / name, text)
        validate_state_path_no_symlinks(artifacts_dir, allow_missing_leaf=True)
        if artifacts_dir.exists():
            raise StorageError(f"run artifacts already exist: {artifacts_dir}")
        tmp_dir.rename(artifacts_dir)
        validate_state_path_no_symlinks(artifacts_dir, allow_missing_leaf=False)
    except Exception as exc:
        _remove_tree(tmp_dir)
        if isinstance(exc, StorageError):
            raise
        raise StorageError(f"failed to publish run artifacts for {artifacts_dir.name}") from exc


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _render_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _artifact_set_payload(
    capture: CapturedDiff,
    artifact_texts: dict[str, str],
    line_map_payload: dict[str, Any],
    symbols_payload: dict[str, Any],
    before_text_payload: dict[str, Any],
    after_text_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "artifacts": [
            _artifact_descriptor(
                artifact_type="patch",
                path="patch.diff",
                media_type="text/x-diff",
                text=artifact_texts["patch.diff"],
            ),
            _artifact_descriptor(
                artifact_type="metadata",
                path="metadata.json",
                media_type="application/json",
                text=artifact_texts["metadata.json"],
            ),
            _artifact_descriptor(
                artifact_type="line_map",
                path="line_map.json",
                media_type="application/json",
                text=artifact_texts["line_map.json"],
                schema=line_map_payload["schema"],
                schema_version=line_map_payload["schema_version"],
            ),
            _artifact_descriptor(
                artifact_type="symbols",
                path="symbols.json",
                media_type="application/json",
                text=artifact_texts["symbols.json"],
                schema=symbols_payload["schema"],
                schema_version=symbols_payload["schema_version"],
            ),
            _artifact_descriptor(
                artifact_type="before_text_by_path",
                path="before_text_by_path.json",
                media_type="application/json",
                text=artifact_texts["before_text_by_path.json"],
                schema=before_text_payload["schema"],
                schema_version=before_text_payload["schema_version"],
            ),
            _artifact_descriptor(
                artifact_type="after_text_by_path",
                path="after_text_by_path.json",
                media_type="application/json",
                text=artifact_texts["after_text_by_path.json"],
                schema=after_text_payload["schema"],
                schema_version=after_text_payload["schema_version"],
            ),
        ],
        "created_at": capture.metadata["created_at"],
        "generation": {
            "redaction": {
                "json_artifacts": "redaction_pipeline",
                "patch": "redaction_pipeline+protect_untrusted_text",
            },
            "selection_source": "persisted_patch_text",
            "line_map_from": "persisted_patch_text",
            "symbols_from": [
                "persisted_patch_text",
                "before_text_by_path",
                "after_text_by_path",
            ],
            "before_text_by_path_from": "capture.before_text_by_path",
            "after_text_by_path_from": "capture.after_text_by_path",
        },
        "manifest_type": "artifact_set",
        "run_id": capture.run_id,
        "schema": _ARTIFACT_SET_SCHEMA,
        "schema_version": _ARTIFACT_SET_SCHEMA_VERSION,
        "selection": {
            "degraded_flags": capture.metadata["degraded_flags"],
            "omitted_files": capture.metadata["omitted_files"],
            "selected_files": capture.metadata["selected_files"],
        },
        "source_kind": capture.run_source.source_kind,
        "source_ref": capture.run_source.source_ref,
    }


def _artifact_descriptor(
    *,
    artifact_type: str,
    path: str,
    media_type: str,
    text: str,
    schema: str | None = None,
    schema_version: int | None = None,
) -> dict[str, Any]:
    encoded = text.encode("utf-8")
    descriptor: dict[str, Any] = {
        "artifact_type": artifact_type,
        "bytes": len(encoded),
        "media_type": media_type,
        "path": path,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
    if schema is not None:
        descriptor["schema"] = schema
    if schema_version is not None:
        descriptor["schema_version"] = schema_version
    return descriptor


def _text_map_payload(*, artifact: str, texts: dict[str, str]) -> dict[str, Any]:
    return {
        "artifact": artifact,
        "schema": _TEXT_MAP_SCHEMA,
        "schema_version": _TEXT_MAP_SCHEMA_VERSION,
        "texts": texts,
    }


def detect_graphify_status(
    workspace_root: Path,
    *,
    use_graphify: bool | None,
    repo: GitRepo | None = None,
) -> GraphifyStatus:
    source_path = _graphify_source_path(workspace_root)
    imported_path = _state_dir(workspace_root) / "graphify" / "graph.json"
    source_exists = source_path.exists()
    imported_exists = imported_path.exists()
    if use_graphify is True and not source_exists:
        raise InputError("graphify-out/graph.json is required when --use-graphify is set")

    enabled = source_exists if use_graphify is None else use_graphify and source_exists
    has_graph = enabled and source_exists
    freshness = _resolve_graphify_freshness(
        workspace_root,
        repo=repo,
        source_exists=source_exists,
        enabled=enabled,
    )
    provenance = {"source": canonicalize_path_text(_GRAPHIFY_RELATIVE_PATH)}
    return GraphifyStatus(
        source_path=source_path,
        imported_path=imported_path,
        enabled=enabled,
        source_exists=source_exists,
        imported_exists=imported_exists,
        has_graph=has_graph,
        freshness=freshness,
        provenance=provenance,
    )


def _resolve_graphify_freshness(
    workspace_root: Path,
    *,
    repo: GitRepo | None,
    source_exists: bool,
    enabled: bool,
) -> str | None:
    from ahadiff.graphify.freshness import FreshnessState, compute_freshness, project_freshness

    if not enabled:
        return project_freshness(FreshnessState.DISABLED) if source_exists else None
    if not source_exists:
        return project_freshness(FreshnessState.UNAVAILABLE)
    if repo is None or repo.head_sha is None:
        return project_freshness(FreshnessState.UNKNOWN)

    try:
        graphify_pathspec = canonicalize_path_text(_GRAPHIFY_RELATIVE_PATH)
        graph_log = run_git(
            workspace_root,
            "log",
            "-1",
            "--format=%H",
            "--",
            graphify_pathspec,
            check=False,
        )
        graph_commit = graph_log.stdout.strip() if graph_log.returncode == 0 else None
        graph_commit = graph_commit or None

        commit_count: int | None = None
        if graph_commit is not None:
            count_result = run_git(
                workspace_root,
                "rev-list",
                "--count",
                f"--max-count={_GRAPHIFY_REV_LIST_MAX_COUNT}",
                f"{graph_commit}..{repo.head_sha}",
                check=False,
            )
            if count_result.returncode == 0:
                commit_count = int(count_result.stdout.strip())

        state = compute_freshness(graph_commit, repo.head_sha, commit_count)
    except (InputError, ValueError, OSError):
        state = FreshnessState.UNKNOWN

    return project_freshness(state)


def import_graphify_artifact(workspace_root: Path, *, force: bool = False) -> GraphifyStatus:
    _repo: GitRepo | None = None
    with suppress(InputError, OSError):
        _repo = open_repo(workspace_root)
    status = detect_graphify_status(workspace_root, use_graphify=True, repo=_repo)
    if status.imported_exists and not force:
        return status

    imported_dir = status.imported_path.parent
    imported_dir.mkdir(parents=True, exist_ok=True)
    graph_limit = _effective_max_patch_bytes(None)
    graph_bytes = _read_regular_file_no_follow_bounded(
        status.source_path,
        max_bytes=graph_limit,
        total_budget_bytes=graph_limit,
        label="graphify graph",
    )
    if len(graph_bytes) > graph_limit:
        raise InputError(f"graphify graph exceeds {graph_limit} bytes")
    graph_sha256 = hashlib.sha256(graph_bytes).hexdigest()
    graph_text = _decode_text_bytes(graph_bytes, description="graphify graph")
    try:
        raw_graph = safe_json_loads(graph_text)
    except (TypeError, ValueError) as exc:
        raise InputError(f"Invalid graph JSON: {exc}") from exc
    protected_graph = _sanitize_graphify_value(raw_graph, workspace_root=workspace_root)
    graph_text = json.dumps(protected_graph, ensure_ascii=False)
    sanitized_graph = parse_graph_json_text(graph_text)
    from ahadiff.review.database import import_graph_nodes

    import_graph_nodes(
        workspace_root / ".ahadiff" / "review.sqlite",
        [node.model_dump(mode="json") for node in sanitized_graph.nodes],
    )
    _atomic_write_text(
        status.imported_path,
        json.dumps(sanitized_graph.model_dump(mode="json"), ensure_ascii=False),
    )
    final_status = detect_graphify_status(workspace_root, use_graphify=True, repo=_repo)
    final_status.provenance["graph_sha256"] = graph_sha256
    return final_status


def _sanitize_graphify_value(value: object, *, workspace_root: Path) -> object:
    if isinstance(value, str):
        redacted = redaction_pipeline(value, repo_root=workspace_root).redacted_text
        return protect_untrusted_text(
            redacted,
            source_name="graphify graph",
            source_kind="string",
        ).protected_text
    if isinstance(value, list):
        return [
            _sanitize_graphify_value(item, workspace_root=workspace_root)
            for item in cast("list[object]", value)
        ]
    if isinstance(value, dict):
        return {
            _sanitize_graphify_key(key, workspace_root=workspace_root): _sanitize_graphify_value(
                item,
                workspace_root=workspace_root,
            )
            for key, item in cast("dict[object, object]", value).items()
        }
    return value


def _sanitize_graphify_key(key: object, *, workspace_root: Path) -> str:
    redacted = redaction_pipeline(str(key), repo_root=workspace_root).redacted_text
    return protect_untrusted_text(
        redacted,
        source_name="graphify graph",
        source_kind="string",
    ).protected_text


def raw_capture_extra_degraded_flags(raw_capture: _RawCapture) -> dict[str, bool]:
    degraded: dict[str, bool] = {}
    if raw_capture.source_detail.get("binary_only") is True:
        degraded["binary_only"] = True
    return degraded


def _capture_input(
    *,
    workspace_root: Path,
    revision: str | None,
    last: bool,
    since: str | None,
    author: str | None,
    staged: bool,
    unstaged: bool,
    include_untracked: bool,
    patch: str | None,
    compare: tuple[Path, Path] | None,
    compare_dir: tuple[Path, Path] | None,
    patch_url: str | None,
    max_files: int,
    max_patch_bytes: int | None,
) -> _RawCapture:
    effective_max_patch_bytes = _effective_max_patch_bytes(max_patch_bytes)
    selections = [
        revision is not None,
        last,
        since is not None,
        patch is not None,
        compare is not None,
        compare_dir is not None,
        patch_url is not None,
        staged or unstaged,
    ]
    if sum(1 for item in selections if item) != 1:
        raise InputError(
            "choose exactly one input mode: revision range/single commit, --last, "
            "--since, --staged/--unstaged, --patch, --patch-url, --compare, or --compare-dir"
        )
    if author is not None and since is None:
        raise InputError("--author can only be used together with --since")

    if patch is not None:
        return _capture_patch_input(
            workspace_root=workspace_root,
            patch=patch,
            max_patch_bytes=effective_max_patch_bytes,
        )
    if patch_url is not None:
        return _capture_patch_url_input(
            patch_url,
            max_patch_bytes=effective_max_patch_bytes,
        )
    if compare is not None:
        return _capture_compare_input(
            workspace_root,
            compare,
            max_patch_bytes=effective_max_patch_bytes,
        )
    if compare_dir is not None:
        return _capture_compare_dir_input(
            workspace_root,
            compare_dir,
            max_patch_bytes=effective_max_patch_bytes,
        )

    repo = open_repo(workspace_root)
    ensure_no_merge_conflicts(repo)
    if since is not None:
        return _capture_since(
            repo,
            since=since,
            author=author,
            max_files=max_files,
            max_patch_bytes=effective_max_patch_bytes,
        )
    if last:
        return _capture_last(
            repo,
            max_files=max_files,
            max_patch_bytes=effective_max_patch_bytes,
        )
    if staged or unstaged:
        return _capture_worktree(
            repo,
            staged=staged,
            unstaged=unstaged,
            include_untracked=include_untracked,
            max_files=max_files,
            max_patch_bytes=effective_max_patch_bytes,
        )
    if revision is None:
        raise InputError("revision input was not provided")
    return _capture_revision(
        repo,
        revision,
        max_files=max_files,
        max_patch_bytes=effective_max_patch_bytes,
    )


def _capture_revision(
    repo: GitRepo,
    revision: str,
    *,
    max_files: int,
    max_patch_bytes: int,
) -> _RawCapture:
    if ".." in revision:
        base_ref, head_ref = resolve_ref_range(repo, revision)
        raw_patch = _run_git_patch_text(
            repo.root,
            "diff",
            "--no-ext-diff",
            base_ref,
            head_ref,
            max_patch_bytes=max_patch_bytes,
        )
        changed_paths = _limit_text_map_paths(
            _changed_paths_between(repo.root, base_ref, head_ref),
            max_files=max_files,
        )
        before_text_by_path = _resolve_git_files(
            repo.root,
            base_ref,
            changed_paths,
            max_file_bytes=max_patch_bytes,
        )
        after_text_by_path = _resolve_git_files(
            repo.root,
            head_ref,
            changed_paths,
            max_file_bytes=max_patch_bytes,
        )
        return _RawCapture(
            source_kind="git_ref",
            source_ref=head_ref,
            capability_level=3,
            raw_patch_text=raw_patch,
            base_ref=base_ref,
            head_ref=head_ref,
            source_detail={"type": "range", "revision": revision},
            branch_names=_branch_names(repo),
            tag_names=(),
            resolved_files=after_text_by_path,
            before_text_by_path=before_text_by_path,
            after_text_by_path=after_text_by_path,
        )

    sha = resolve_commitish(repo, revision)
    raw_patch, base_ref = _single_commit_patch(repo, sha, max_patch_bytes=max_patch_bytes)
    changed_paths = _limit_text_map_paths(
        _changed_paths_for_commit(repo.root, sha),
        max_files=max_files,
    )
    before_text_by_path = _resolve_git_files(
        repo.root,
        base_ref,
        changed_paths,
        max_file_bytes=max_patch_bytes,
    )
    after_text_by_path = _resolve_git_files(
        repo.root,
        sha,
        changed_paths,
        max_file_bytes=max_patch_bytes,
    )
    return _RawCapture(
        source_kind="git_ref",
        source_ref=sha,
        capability_level=3,
        raw_patch_text=raw_patch,
        base_ref=base_ref,
        head_ref=sha,
        source_detail={"type": "single_commit", "sha": sha},
        branch_names=_branch_names(repo),
        tag_names=(),
        resolved_files=after_text_by_path,
        before_text_by_path=before_text_by_path,
        after_text_by_path=after_text_by_path,
    )


def _capture_last(repo: GitRepo, *, max_files: int, max_patch_bytes: int) -> _RawCapture:
    sha = ensure_head_exists(repo)
    raw_patch, base_ref = _single_commit_patch(repo, sha, max_patch_bytes=max_patch_bytes)
    changed_paths = _limit_text_map_paths(
        _changed_paths_for_commit(repo.root, sha),
        max_files=max_files,
    )
    before_text_by_path = _resolve_git_files(
        repo.root,
        base_ref,
        changed_paths,
        max_file_bytes=max_patch_bytes,
    )
    after_text_by_path = _resolve_git_files(
        repo.root,
        sha,
        changed_paths,
        max_file_bytes=max_patch_bytes,
    )
    return _RawCapture(
        source_kind="git_ref",
        source_ref=sha,
        capability_level=3,
        raw_patch_text=raw_patch,
        base_ref=base_ref,
        head_ref=sha,
        source_detail={"type": "last"},
        branch_names=_branch_names(repo),
        tag_names=(),
        resolved_files=after_text_by_path,
        before_text_by_path=before_text_by_path,
        after_text_by_path=after_text_by_path,
    )


def _capture_since(
    repo: GitRepo,
    *,
    since: str,
    author: str | None,
    max_files: int,
    max_patch_bytes: int,
) -> _RawCapture:
    ensure_head_exists(repo)
    args = ["rev-list", "--first-parent", f"--since={since}", "HEAD"]
    if author is not None:
        args.insert(2, f"--author={author}")
    result = run_git(repo.root, *args)
    matched_commits = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not matched_commits:
        raise InputError("no commits found in the requested time range")

    if len(matched_commits) == 1:
        capture = _capture_revision(
            repo,
            matched_commits[0],
            max_files=max_files,
            max_patch_bytes=max_patch_bytes,
        )
        detail = dict(capture.source_detail)
        detail.update({"type": "since", "since": since, "matched_commits": matched_commits})
        return _RawCapture(
            source_kind="git_since",
            source_ref=capture.source_ref,
            capability_level=3,
            raw_patch_text=capture.raw_patch_text,
            base_ref=capture.base_ref,
            head_ref=capture.head_ref,
            source_detail=detail,
            branch_names=capture.branch_names,
            tag_names=capture.tag_names,
            resolved_files=capture.resolved_files,
            before_text_by_path=capture.before_text_by_path,
            after_text_by_path=capture.after_text_by_path,
        )

    oldest_commit = matched_commits[-1]
    base_ref = first_parent_or_empty_tree(repo.root, oldest_commit)
    head_ref = ensure_head_exists(repo)
    raw_patch = _run_git_patch_text(
        repo.root,
        "diff",
        "--no-ext-diff",
        base_ref,
        head_ref,
        max_patch_bytes=max_patch_bytes,
    )
    changed_paths = _limit_text_map_paths(
        _changed_paths_between(repo.root, base_ref, head_ref),
        max_files=max_files,
    )
    before_text_by_path = _resolve_git_files(
        repo.root,
        base_ref,
        changed_paths,
        max_file_bytes=max_patch_bytes,
    )
    after_text_by_path = _resolve_git_files(
        repo.root,
        head_ref,
        changed_paths,
        max_file_bytes=max_patch_bytes,
    )
    return _RawCapture(
        source_kind="git_since",
        source_ref=head_ref,
        capability_level=3,
        raw_patch_text=raw_patch,
        base_ref=base_ref,
        head_ref=head_ref,
        source_detail={
            "type": "since",
            "since": since,
            "matched_commits": matched_commits,
            "window_base": base_ref,
            "window_head": head_ref,
            "commit_count": len(matched_commits),
        },
        branch_names=_branch_names(repo),
        tag_names=(),
        resolved_files=after_text_by_path,
        before_text_by_path=before_text_by_path,
        after_text_by_path=after_text_by_path,
    )


def _capture_worktree(
    repo: GitRepo,
    *,
    staged: bool,
    unstaged: bool,
    include_untracked: bool,
    max_files: int,
    max_patch_bytes: int,
) -> _RawCapture:
    head_sha = ensure_head_exists(repo)
    combined_mode = staged and unstaged
    args = ["diff", "--no-ext-diff"]
    if combined_mode:
        args.append("HEAD")
        source_kind: ContractSourceKind = "git_staged_unstaged"
        base_ref = "HEAD"
        head_ref = "WORKTREE"
    elif staged:
        args.append("--cached")
        source_kind = "git_staged"
        base_ref = "HEAD"
        head_ref = "INDEX"
    else:
        source_kind = "git_unstaged"
        base_ref = "INDEX"
        head_ref = "WORKTREE"
    patch_text = _run_git_patch_text(repo.root, *args, max_patch_bytes=max_patch_bytes)
    untracked_files = _list_untracked_files(repo.root) if include_untracked else []
    if untracked_files:
        patch_text = patch_text + _build_untracked_patch(
            repo.root,
            untracked_files,
            max_patch_bytes=max_patch_bytes,
        )
        _ensure_patch_text_size(patch_text, max_patch_bytes=max_patch_bytes)

    changed_paths = _limit_text_map_paths(
        _changed_paths_in_worktree(repo.root, staged, unstaged),
        max_files=max_files,
    )
    if combined_mode:
        before_text_by_path = _resolve_git_files(
            repo.root,
            head_sha,
            changed_paths,
            max_file_bytes=max_patch_bytes,
        )
        after_text_by_path = _resolve_worktree_files(
            repo.root,
            changed_paths,
            max_file_bytes=max_patch_bytes,
        )
    elif staged:
        before_text_by_path = _resolve_git_files(
            repo.root,
            head_sha,
            changed_paths,
            max_file_bytes=max_patch_bytes,
        )
        after_text_by_path = _resolve_index_files(
            repo.root,
            changed_paths,
            max_file_bytes=max_patch_bytes,
        )
    else:
        before_text_by_path = _resolve_index_files(
            repo.root,
            changed_paths,
            max_file_bytes=max_patch_bytes,
        )
        after_text_by_path = _resolve_worktree_files(
            repo.root,
            changed_paths,
            max_file_bytes=max_patch_bytes,
        )
    after_text_by_path.update(
        _resolve_worktree_files(
            repo.root,
            _limit_text_map_paths(untracked_files, max_files=max_files),
            max_file_bytes=max_patch_bytes,
        )
    )
    source_ref = head_sha if combined_mode or staged else f"{head_sha}:unstaged"
    source_detail: dict[str, Any] = {
        "type": "worktree",
        "combined_mode": combined_mode,
        "include_untracked": include_untracked,
    }
    if repo.head_detached:
        source_detail["head_detached"] = True
    if untracked_files:
        source_detail["untracked_count"] = len(untracked_files)
    return _RawCapture(
        source_kind=source_kind,
        source_ref=source_ref,
        capability_level=3,
        raw_patch_text=patch_text,
        base_ref=base_ref,
        head_ref=head_ref,
        source_detail=source_detail,
        branch_names=_branch_names(repo),
        tag_names=(),
        resolved_files=after_text_by_path,
        before_text_by_path=before_text_by_path,
        after_text_by_path=after_text_by_path,
    )


def _capture_patch_input(
    *,
    workspace_root: Path,
    patch: str,
    max_patch_bytes: int,
) -> _RawCapture:
    if patch == "-":
        if sys.stdin.isatty():
            raise InputError(
                "stdin patch input requires a pipe, e.g. `git diff | ahadiff learn --patch -`"
            )
        data = _read_stdin_bytes(
            max_patch_bytes=max_patch_bytes,
            timeout_seconds=30.0,
            stream=sys.stdin.buffer,
        )
        source_kind: ContractSourceKind = "patch_stdin"
        source_name = "stdin"
    else:
        patch_path = resolve_safe_path_from_root(workspace_root, patch)
        if not patch_path.exists():
            raise InputError(f"patch file does not exist: {patch}")
        data = _read_regular_file_no_follow_bounded(
            patch_path,
            max_bytes=max_patch_bytes,
            total_budget_bytes=max_patch_bytes,
            label="patch file",
        )
        source_kind = "patch_file"
        source_name = Path(canonicalize_path_text(patch_path.relative_to(workspace_root))).name

    return _build_patch_input_capture(
        data,
        source_kind=source_kind,
        source_name=source_name,
        source_detail={"type": source_kind, "name": source_name},
        max_patch_bytes=max_patch_bytes,
    )


def _capture_patch_url_input(patch_url: str, *, max_patch_bytes: int) -> _RawCapture:
    url_cap_bytes = min(max_patch_bytes, _PATCH_URL_MAX_BYTES)
    downloaded = download_patch_url(patch_url, max_patch_bytes=url_cap_bytes)
    url_hash = f"sha256:{hashlib.sha256(patch_url.encode('utf-8')).hexdigest()}"
    final_url_hash = f"sha256:{hashlib.sha256(downloaded.final_url.encode('utf-8')).hexdigest()}"
    return _build_patch_input_capture(
        downloaded.body,
        source_kind="patch_file",
        source_name="patch-url",
        source_detail={
            "type": "patch_url",
            "url_hash": url_hash,
            "final_url_hash": final_url_hash,
            "redirect_count": downloaded.redirect_count,
            "content_type": downloaded.content_type,
        },
        max_patch_bytes=max_patch_bytes,
        metadata_texts={
            "patch_url": patch_url,
            "patch_url_final": downloaded.final_url,
        },
    )


def _build_patch_input_capture(
    data: bytes,
    *,
    source_kind: ContractSourceKind,
    source_name: str,
    source_detail: dict[str, Any],
    max_patch_bytes: int,
    metadata_texts: dict[str, str] | None = None,
) -> _RawCapture:
    if b"\x00" in data:
        raise InputError("patch input must be text, not binary")
    raw_patch = _decode_text_bytes(data, description="patch input")
    raw_patch = _normalize_newlines(raw_patch)
    source_ref = f"sha256:{hashlib.sha256(raw_patch.encode('utf-8')).hexdigest()}"
    detail = dict(source_detail)
    detail.setdefault("name", source_name)
    detail["patch_hash"] = source_ref
    return _RawCapture(
        source_kind=source_kind,
        source_ref=source_ref,
        capability_level=1,
        raw_patch_text=raw_patch,
        base_ref=None,
        head_ref=None,
        source_detail=detail,
        branch_names=(),
        tag_names=(),
        resolved_files={},
        before_text_by_path={},
        after_text_by_path={},
        metadata_texts=metadata_texts or {},
    )


def _read_stdin_bytes(
    *,
    max_patch_bytes: int,
    timeout_seconds: float,
    stream: BinaryIO,
) -> bytes:
    if os.name == "nt":
        return _read_stream_bytes_with_timeout(
            stream,
            max_patch_bytes=max_patch_bytes,
            timeout_seconds=timeout_seconds,
        )
    try:
        file_descriptor = stream.fileno()
    except (AttributeError, OSError):
        return _read_stream_bytes_with_timeout(
            stream,
            max_patch_bytes=max_patch_bytes,
            timeout_seconds=timeout_seconds,
        )

    chunks: list[bytes] = []
    total_bytes = 0
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(file_descriptor, selectors.EVENT_READ)
            while True:
                ready = selector.select(timeout_seconds)
                if not ready:
                    raise InputError("stdin patch read timed out after 30 seconds")
                chunk = os.read(file_descriptor, 65_536)
                if chunk == b"":
                    break
                chunks.append(chunk)
                total_bytes += len(chunk)
                if total_bytes > max_patch_bytes:
                    raise InputError(f"stdin patch exceeds {max_patch_bytes} bytes")
    except OSError as exc:
        raise InputError("stdin patch read failed") from exc
    return b"".join(chunks)


def _read_stream_bytes_with_timeout(
    stream: BinaryIO,
    *,
    max_patch_bytes: int,
    timeout_seconds: float,
) -> bytes:
    result_queue: Queue[bytes | BaseException] = Queue(maxsize=1)

    def _read_worker() -> None:
        try:
            result_queue.put(stream.read(max_patch_bytes + 1))
        except OSError as exc:
            result_queue.put(exc)

    worker = threading.Thread(target=_read_worker, daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise InputError("stdin patch read timed out after 30 seconds")

    result = result_queue.get()
    if isinstance(result, BaseException):
        raise InputError("stdin patch read failed") from result
    if len(result) > max_patch_bytes:
        raise InputError(f"stdin patch exceeds {max_patch_bytes} bytes")
    return result


def _capture_compare_input(
    workspace_root: Path,
    compare: tuple[Path, Path],
    *,
    max_patch_bytes: int,
) -> _RawCapture:
    old_path = resolve_safe_path_from_root(workspace_root, compare[0])
    new_path = resolve_safe_path_from_root(workspace_root, compare[1])
    old_bytes = _read_regular_file_no_follow_bounded(
        old_path,
        max_bytes=max_patch_bytes,
        total_budget_bytes=max_patch_bytes,
    )
    new_bytes = _read_regular_file_no_follow_bounded(
        new_path,
        max_bytes=max_patch_bytes - len(old_bytes),
        total_budget_bytes=max_patch_bytes,
    )
    old_binary = b"\x00" in old_bytes
    new_binary = b"\x00" in new_bytes
    old_rel = old_path.relative_to(workspace_root).as_posix()
    new_rel = new_path.relative_to(workspace_root).as_posix()

    if old_binary or new_binary:
        raw_patch = f"Binary files a/{old_rel} and b/{new_rel} differ\n"
        _ensure_patch_text_size(raw_patch, max_patch_bytes=max_patch_bytes)
        source_ref = f"sha256:{hashlib.sha256(old_bytes + b'::' + new_bytes).hexdigest()}"
        return _RawCapture(
            source_kind="file_compare",
            source_ref=source_ref,
            capability_level=2,
            raw_patch_text=raw_patch,
            base_ref=None,
            head_ref=None,
            source_detail={
                "type": "compare",
                "old_name": Path(old_rel).name,
                "new_name": Path(new_rel).name,
                "binary_only": True,
            },
            branch_names=(),
            tag_names=(),
            resolved_files={},
            before_text_by_path={},
            after_text_by_path={},
        )

    old_text = _normalize_newlines(_decode_text_bytes(old_bytes, description=f"{old_rel}"))
    new_text = _normalize_newlines(_decode_text_bytes(new_bytes, description=f"{new_rel}"))
    if old_text == new_text:
        raise InputError("compare input files are identical")

    diff_lines = unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{old_rel}",
        tofile=f"b/{new_rel}",
        lineterm="",
    )
    raw_patch = _render_unified_diff(diff_lines)
    if raw_patch and not raw_patch.endswith("\n"):
        raw_patch += "\n"
    _ensure_patch_text_size(raw_patch, max_patch_bytes=max_patch_bytes)
    source_ref = f"sha256:{hashlib.sha256(old_bytes + b'::' + new_bytes).hexdigest()}"
    return _RawCapture(
        source_kind="file_compare",
        source_ref=source_ref,
        capability_level=2,
        raw_patch_text=raw_patch,
        base_ref=None,
        head_ref=None,
        source_detail={
            "type": "compare",
            "old_name": Path(old_rel).name,
            "new_name": Path(new_rel).name,
        },
        branch_names=(),
        tag_names=(),
        resolved_files={old_rel: old_text, new_rel: new_text},
        before_text_by_path={old_rel: old_text},
        after_text_by_path={new_rel: new_text},
    )


def _capture_compare_dir_input(
    workspace_root: Path,
    compare_dir: tuple[Path, Path],
    *,
    max_patch_bytes: int,
) -> _RawCapture:
    old_dir = resolve_safe_path_from_root(workspace_root, compare_dir[0])
    new_dir = resolve_safe_path_from_root(workspace_root, compare_dir[1])
    _ensure_compare_directory(old_dir)
    _ensure_compare_directory(new_dir)

    old_files, remaining_bytes = _read_compare_dir_tree(
        old_dir,
        max_bytes=max_patch_bytes,
        total_budget_bytes=max_patch_bytes,
    )
    new_files, remaining_bytes = _read_compare_dir_tree(
        new_dir,
        max_bytes=remaining_bytes,
        total_budget_bytes=max_patch_bytes,
    )
    all_paths = sorted(set(old_files) | set(new_files))
    if not all_paths:
        raise InputError("directories have no comparable files")

    patch_chunks: list[str] = []
    before_text_by_path: dict[str, str] = {}
    after_text_by_path: dict[str, str] = {}
    digest = hashlib.sha256()
    changed_count = 0
    binary_count = 0
    running_patch_bytes = 0
    for relative_path in all_paths:
        old_exists = relative_path in old_files
        new_exists = relative_path in new_files
        old_bytes = old_files.get(relative_path, b"")
        new_bytes = new_files.get(relative_path, b"")
        if old_exists and new_exists and old_bytes == new_bytes:
            continue

        digest.update(relative_path.as_posix().encode("utf-8"))
        digest.update(b"\0old\0")
        digest.update(old_bytes)
        digest.update(b"\0new\0")
        digest.update(new_bytes)
        changed_count += 1

        old_text = _decode_compare_dir_text(old_bytes, relative_path.as_posix())
        new_text = _decode_compare_dir_text(new_bytes, relative_path.as_posix())
        if old_text is None or new_text is None:
            binary_count += 1
            relative_posix = relative_path.as_posix()
            chunk = f"Binary files a/{relative_posix} and b/{relative_posix} differ\n"
            running_patch_bytes += len(chunk.encode("utf-8"))
            if running_patch_bytes > max_patch_bytes:
                raise InputError(f"compare-dir patch exceeds {max_patch_bytes} bytes")
            patch_chunks.append(chunk)
            continue

        if old_exists:
            before_text_by_path[relative_path.as_posix()] = old_text
        if new_exists:
            after_text_by_path[relative_path.as_posix()] = new_text
        diff_lines = unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{relative_path.as_posix()}",
            tofile=f"b/{relative_path.as_posix()}",
            lineterm="",
        )
        rendered = _render_unified_diff(diff_lines)
        if rendered and not rendered.endswith("\n"):
            rendered += "\n"
        running_patch_bytes += len(rendered.encode("utf-8"))
        if running_patch_bytes > max_patch_bytes:
            raise InputError(f"compare-dir patch exceeds {max_patch_bytes} bytes")
        patch_chunks.append(rendered)

    if changed_count == 0:
        raise InputError("directories have no differences")

    raw_patch = "".join(patch_chunks)
    _ensure_patch_text_size(raw_patch, max_patch_bytes=max_patch_bytes)
    source_ref = f"sha256:{digest.hexdigest()}"
    return _RawCapture(
        source_kind="file_compare",
        source_ref=source_ref,
        capability_level=2,
        raw_patch_text=raw_patch,
        base_ref=None,
        head_ref=None,
        source_detail={
            "type": "compare_dir",
            "old_name": old_dir.name,
            "new_name": new_dir.name,
            "changed_files": changed_count,
            "binary_files": binary_count,
        },
        branch_names=(),
        tag_names=(),
        resolved_files=after_text_by_path,
        before_text_by_path=before_text_by_path,
        after_text_by_path=after_text_by_path,
    )


def _ensure_compare_directory(path: Path) -> None:
    fd = _open_compare_directory_fd(
        path,
        missing_message="compare-dir input directory does not exist",
    )
    if fd is not None:
        os.close(fd)


def _open_compare_directory_fd(path: Path, *, missing_message: str) -> int | None:
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise InputError(missing_message) from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError("compare-dir input directory must not be a symlink")
    if _has_windows_reparse_point(path_stat):
        raise InputError(
            "compare-dir input directory must not be a Windows reparse point or junction"
        )
    if not stat.S_ISDIR(path_stat.st_mode):
        raise InputError("compare-dir input must be a directory")
    if sys.platform.startswith("win"):
        return None

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError("compare-dir input directory must not be a symlink") from exc
        raise InputError("compare-dir input directory is unreadable") from exc
    try:
        fd_stat = os.fstat(fd)
        if not stat.S_ISDIR(fd_stat.st_mode):
            raise InputError("compare-dir input must be a directory")
        if (fd_stat.st_dev, fd_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError("compare-dir input directory changed during validation")
    except Exception:
        os.close(fd)
        raise
    return fd


def _read_compare_dir_tree(
    root: Path,
    *,
    max_bytes: int,
    total_budget_bytes: int,
) -> tuple[dict[Path, bytes], int]:
    file_bytes_by_path: dict[Path, bytes] = {}
    remaining_bytes = max_bytes
    root_fd = _open_compare_directory_fd(
        root,
        missing_message="compare-dir input directory is unreadable",
    )
    if root_fd is None:
        raise InputError(
            "compare-dir is not supported on this platform without secure directory "
            "file descriptors"
        )
    stack = [(root, Path(), root_fd)]
    dirs_seen = 0
    try:
        while stack:
            current, relative_dir, fd = stack.pop()
            dirs_seen += 1
            if dirs_seen > _COMPARE_DIR_MAX_DIRS:
                os.close(fd)
                raise InputError(f"compare-dir exceeds {_COMPARE_DIR_MAX_DIRS} directories")
            try:
                entries = os.scandir(fd)
            except (OSError, TypeError) as exc:
                os.close(fd)
                if isinstance(exc, TypeError):
                    raise InputError(
                        "compare-dir is not supported on this platform without secure "
                        "directory file descriptors"
                    ) from exc
                raise InputError("compare-dir input directory is unreadable") from exc
            try:
                with entries:
                    for entry in entries:
                        try:
                            entry_stat = entry.stat(follow_symlinks=False)
                        except OSError as exc:
                            raise InputError("compare-dir input entry is unreadable") from exc
                        entry_path = current / entry.name
                        if stat.S_ISLNK(entry_stat.st_mode):
                            raise InputError("compare-dir input must not contain symlinks")
                        if _has_windows_reparse_point(entry_stat):
                            raise InputError(
                                "compare-dir input must not contain Windows reparse points "
                                "or junctions"
                            )
                        relative_path = relative_dir / entry.name
                        if len(relative_path.parts) > _COMPARE_DIR_MAX_DEPTH:
                            raise InputError(f"compare-dir exceeds depth {_COMPARE_DIR_MAX_DEPTH}")
                        if stat.S_ISDIR(entry_stat.st_mode):
                            child_fd = _open_child_compare_directory_fd(fd, entry.name, entry_stat)
                            stack.append((entry_path, relative_path, child_fd))
                            continue
                        if stat.S_ISREG(entry_stat.st_mode):
                            data = _read_regular_file_from_dir_fd(
                                fd,
                                entry.name,
                                entry_stat,
                                max_bytes=remaining_bytes,
                                total_budget_bytes=total_budget_bytes,
                            )
                            remaining_bytes -= len(data)
                            file_bytes_by_path[relative_path] = data
                            if len(file_bytes_by_path) > _COMPARE_DIR_MAX_FILES:
                                raise InputError(
                                    f"compare-dir exceeds {_COMPARE_DIR_MAX_FILES} files"
                                )
            finally:
                os.close(fd)
    except Exception:
        _close_compare_dir_stack(stack)
        raise
    return file_bytes_by_path, remaining_bytes


def _close_compare_dir_stack(stack: list[tuple[Path, Path, int]]) -> None:
    for _, _, fd in stack:
        os.close(fd)


def _open_child_compare_directory_fd(
    parent_fd: int,
    entry_name: str,
    expected_stat: os.stat_result,
) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
    try:
        child_fd = os.open(entry_name, flags, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError("compare-dir input must not contain symlinks") from exc
        raise InputError("compare-dir input directory is unreadable") from exc
    try:
        child_stat = os.fstat(child_fd)
        if not stat.S_ISDIR(child_stat.st_mode):
            raise InputError("compare-dir input must be a directory")
        if (child_stat.st_dev, child_stat.st_ino) != (expected_stat.st_dev, expected_stat.st_ino):
            raise InputError("compare-dir input directory changed during validation")
    except Exception:
        os.close(child_fd)
        raise
    return child_fd


def _has_windows_reparse_point(path_stat: object) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _decode_compare_dir_text(data: bytes, description: str) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return _normalize_newlines(_decode_text_bytes(data, description=description))
    except InputError:
        return None


def _read_regular_file_no_follow_bounded(
    path: Path,
    *,
    max_bytes: int,
    total_budget_bytes: int,
    label: str = "compare input file",
) -> bytes:
    if max_bytes < 0:
        raise InputError(_total_budget_exceeded_message(label, total_budget_bytes))
    try:
        path_stat = os.lstat(path)
    except OSError as exc:
        raise InputError(f"{label} is unreadable") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise InputError(f"{label} must not be a symlink")
    if _has_windows_reparse_point(path_stat):
        raise InputError(f"{label} must not be a Windows reparse point or junction")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(f"{label} must not be a symlink") from exc
        raise InputError(f"{label} is unreadable") from exc

    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise InputError(f"{label} must be a regular file")
        if _has_windows_reparse_point(file_stat):
            raise InputError(f"{label} must not be a Windows reparse point or junction")
        if (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise InputError(f"{label} changed during validation")
        if file_stat.st_size > max_bytes:
            if file_stat.st_size > total_budget_bytes:
                raise InputError(f"{label} exceeds {total_budget_bytes} bytes")
            raise InputError(_total_budget_exceeded_message(label, total_budget_bytes))

        chunks: list[bytes] = []
        total_bytes = 0
        while True:
            chunk_size = min(65_536, max_bytes + 1 - total_bytes)
            if chunk_size <= 0:
                break
            chunk = os.read(fd, chunk_size)
            if chunk == b"":
                break
            chunks.append(chunk)
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise InputError(_total_budget_exceeded_message(label, total_budget_bytes))
        return b"".join(chunks)
    except InputError:
        raise
    except OSError as exc:
        raise InputError(f"{label} is unreadable") from exc
    finally:
        os.close(fd)


def _read_regular_file_from_dir_fd(
    parent_fd: int,
    entry_name: str,
    expected_stat: os.stat_result,
    *,
    max_bytes: int,
    total_budget_bytes: int,
    label: str = "compare input file",
) -> bytes:
    if max_bytes < 0:
        raise InputError(_total_budget_exceeded_message(label, total_budget_bytes))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(entry_name, flags, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise InputError(f"{label} must not be a symlink") from exc
        raise InputError(f"{label} is unreadable") from exc

    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise InputError(f"{label} must be a regular file")
        if _has_windows_reparse_point(file_stat):
            raise InputError(f"{label} must not be a Windows reparse point or junction")
        if (file_stat.st_dev, file_stat.st_ino) != (expected_stat.st_dev, expected_stat.st_ino):
            raise InputError(f"{label} changed during validation")
        if file_stat.st_size > max_bytes:
            if file_stat.st_size > total_budget_bytes:
                raise InputError(f"{label} exceeds {total_budget_bytes} bytes")
            raise InputError(_total_budget_exceeded_message(label, total_budget_bytes))

        chunks: list[bytes] = []
        total_bytes = 0
        while True:
            chunk_size = min(65_536, max_bytes + 1 - total_bytes)
            if chunk_size <= 0:
                break
            chunk = os.read(fd, chunk_size)
            if chunk == b"":
                break
            chunks.append(chunk)
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise InputError(_total_budget_exceeded_message(label, total_budget_bytes))
        return b"".join(chunks)
    except InputError:
        raise
    except OSError as exc:
        raise InputError(f"{label} is unreadable") from exc
    finally:
        os.close(fd)


def _total_budget_exceeded_message(label: str, total_budget_bytes: int) -> str:
    if label == "compare input file":
        return f"compare input files exceed {total_budget_bytes} bytes total"
    return f"{label} exceeds {total_budget_bytes} bytes total"


def _filter_ignored_capture(workspace_root: Path, raw_capture: _RawCapture) -> _RawCapture:
    if not _has_git_root(workspace_root) or not raw_capture.source_kind.startswith("git_"):
        return raw_capture

    matcher = load_ignore_matcher(workspace_root)
    if not matcher.patterns:
        return raw_capture

    filtered_patch = _filter_ignored_patch_text(raw_capture.raw_patch_text, matcher)
    filtered_resolved_files = {
        path: text
        for path, text in raw_capture.resolved_files.items()
        if not is_ignored_path(path, matcher)
    }
    filtered_before = {
        path: text
        for path, text in raw_capture.before_text_by_path.items()
        if not is_ignored_path(path, matcher)
    }
    filtered_after = {
        path: text
        for path, text in raw_capture.after_text_by_path.items()
        if not is_ignored_path(path, matcher)
    }
    return _RawCapture(
        source_kind=raw_capture.source_kind,
        source_ref=raw_capture.source_ref,
        capability_level=raw_capture.capability_level,
        raw_patch_text=filtered_patch,
        base_ref=raw_capture.base_ref,
        head_ref=raw_capture.head_ref,
        source_detail=raw_capture.source_detail,
        branch_names=raw_capture.branch_names,
        tag_names=raw_capture.tag_names,
        resolved_files=filtered_resolved_files,
        before_text_by_path=filtered_before,
        after_text_by_path=filtered_after,
        metadata_texts=raw_capture.metadata_texts,
    )


def _filter_ignored_patch_text(text: str, matcher: IgnoreMatcher) -> str:
    segments = _split_patch_segments(text)
    if not segments:
        return text
    kept_segments = [
        segment
        for segment in segments
        if segment.path == "__unknown__" or not is_ignored_path(segment.path, matcher)
    ]
    return "".join(segment.text for segment in kept_segments)


def _apply_capture_limits(
    text: str,
    *,
    max_files: int,
    hard_limit: int,
) -> tuple[str, dict[str, Any]]:
    segments = _split_patch_segments(text)
    if not segments:
        return text, {
            "binary_only": False,
            "diff_clipped": False,
            "file_count_exceeded": False,
            "selected_files": [],
            "omitted_files": [],
        }

    ranked = sorted(
        segments,
        key=lambda item: (-item.changed_lines, -item.hunk_count, item.path),
    )
    selected = list(ranked)
    omitted: list[_PatchSegment] = []
    file_count_exceeded = False
    if len(selected) > max_files:
        file_count_exceeded = True
        omitted.extend(selected[max_files:])
        selected = selected[:max_files]

    diff_clipped = False
    total_lines = sum(item.line_count for item in selected)
    if total_lines > hard_limit:
        diff_clipped = True
        clipped: list[_PatchSegment] = []
        running = 0
        for item in selected:
            remaining_lines = hard_limit - running
            if remaining_lines <= 0:
                omitted.append(item)
                continue
            if item.line_count <= remaining_lines:
                clipped.append(item)
                running += item.line_count
                continue
            clipped.append(_truncate_segment(item, max_lines=remaining_lines))
            running += remaining_lines
        selected = clipped

    binary_only = all(item.binary_only for item in segments)
    selected_files = [item.path for item in selected]
    omitted_files = sorted({item.path for item in omitted if item.path not in selected_files})
    persisted = "".join(item.text for item in selected)
    return persisted, {
        "binary_only": binary_only,
        "diff_clipped": diff_clipped,
        "file_count_exceeded": file_count_exceeded,
        "selected_files": selected_files,
        "omitted_files": omitted_files,
    }


def _split_patch_segments(text: str) -> list[_PatchSegment]:
    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    segments = split_unified_diff_segments(lines, include_preamble=True)

    built: list[_PatchSegment] = []
    for raw_segment in segments:
        segment_text = "".join(raw_segment)
        path = _segment_path(raw_segment)
        built.append(
            _PatchSegment(
                path=path,
                text=segment_text,
                line_count=len(raw_segment),
                changed_lines=sum(
                    1
                    for line in raw_segment
                    if (line.startswith("+") or line.startswith("-"))
                    and not line.startswith("+++")
                    and not line.startswith("---")
                ),
                hunk_count=sum(1 for line in raw_segment if line.startswith("@@")),
                binary_only=any(
                    "Binary files " in line or line.startswith("GIT binary patch")
                    for line in raw_segment
                ),
            )
        )
    return built


def _segment_path(lines: list[str]) -> str:
    for line in lines:
        if line.startswith("+++ "):
            candidate = _normalize_segment_path_token(line.strip().split(" ", 1)[1], prefix="b/")
            if candidate is not None:
                return candidate
    for line in lines:
        if line.startswith("--- "):
            candidate = _normalize_segment_path_token(line.strip().split(" ", 1)[1], prefix="a/")
            if candidate is not None:
                return candidate
    for line in lines:
        if line.startswith("diff --git "):
            parsed_paths = parse_diff_git_header_paths(line.strip())
            if parsed_paths is not None:
                _, new_path = parsed_paths
                candidate = new_path
                if candidate is not None:
                    return candidate
    for line in lines:
        candidate = _binary_segment_path(line)
        if candidate is not None:
            return candidate
    return "__unknown__"


def _normalize_segment_path_token(value: str, *, prefix: str) -> str | None:
    return normalize_diff_path_token(value, prefix=prefix)


def _binary_segment_path(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("Binary files ") or not stripped.endswith(" differ"):
        return None
    body = stripped.removeprefix("Binary files ").removesuffix(" differ")
    old_token, separator, new_token = body.partition(" and ")
    if not separator:
        return None
    new_path = _normalize_segment_path_token(new_token, prefix="b/")
    if new_path is not None:
        return new_path
    return _normalize_segment_path_token(old_token, prefix="a/")


def _resolve_policy(workspace_root: Path) -> AllowlistPolicy | None:
    return (
        load_workspace_allowlist_policy(workspace_root)
        if not _has_git_root(workspace_root)
        else None
    )


def _has_git_root(workspace_root: Path) -> bool:
    return (workspace_root / ".git").exists()


def _state_dir(workspace_root: Path) -> Path:
    if _has_git_root(workspace_root):
        return project_state_dir(workspace_root)
    return validate_state_dir_path(workspace_root / ".ahadiff")


def _validate_capture_limits(*, max_files: int, hard_limit: int, max_patch_bytes: int) -> None:
    if max_files < 1:
        raise InputError("capture max_files must be >= 1")
    if hard_limit < 1:
        raise InputError("capture hard_limit must be >= 1")
    if max_patch_bytes < 1:
        raise InputError("capture max_patch_bytes must be >= 1")


def _effective_max_patch_bytes(max_patch_bytes: int | None) -> int:
    configured = (
        int(DEFAULT_CONFIG["capture"]["max_patch_bytes"])
        if max_patch_bytes is None
        else max_patch_bytes
    )
    return min(configured, _MAX_PATCH_BYTES_HARD_CAP)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _capability_flags(capability_level: int, has_graph: bool) -> dict[str, bool]:
    if capability_level == 3:
        return {
            "has_repo_context": True,
            "has_symbol_index": True,
            "has_cross_file_context": True,
            "has_source_ref": True,
            "has_graph": has_graph,
        }
    if capability_level == 2:
        return {
            "has_repo_context": True,
            "has_symbol_index": True,
            "has_cross_file_context": False,
            "has_source_ref": True,
            "has_graph": has_graph,
        }
    return {
        "has_repo_context": False,
        "has_symbol_index": False,
        "has_cross_file_context": False,
        "has_source_ref": True,
        "has_graph": False,
    }


def _single_commit_patch(
    repo: GitRepo,
    revision: str,
    *,
    max_patch_bytes: int,
) -> tuple[str, str]:
    parents = parent_count(repo.root, revision)
    if parents == 0:
        raw_patch = _run_git_patch_text(
            repo.root,
            "show",
            "--format=",
            "--root",
            revision,
            max_patch_bytes=max_patch_bytes,
        )
    elif parents > 1:
        raw_patch = _run_git_patch_text(
            repo.root,
            "show",
            "--format=",
            "--first-parent",
            revision,
            max_patch_bytes=max_patch_bytes,
        )
    else:
        raw_patch = _run_git_patch_text(
            repo.root,
            "show",
            "--format=",
            revision,
            max_patch_bytes=max_patch_bytes,
        )
    return raw_patch, first_parent_or_empty_tree(repo.root, revision)


def _run_git_patch_text(repo_root: Path, *args: str, max_patch_bytes: int) -> str:
    command = ["git", "-c", "core.quotePath=false", "-C", str(repo_root), *args]
    try:
        with subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ) as process:
            if process.stdout is None:
                raise InputError(f"git command failed: {' '.join(args)}")

            chunks: list[bytes] = []
            total_bytes = 0
            while True:
                chunk = process.stdout.read(65_536)
                if chunk == b"":
                    break
                total_bytes += len(chunk)
                if total_bytes > max_patch_bytes:
                    process.kill()
                    _wait_git_patch_process(process)
                    raise InputError(f"git patch exceeds {max_patch_bytes} bytes")
                chunks.append(chunk)

            output = b"".join(chunks)
            returncode = _wait_git_patch_process(process)
    except OSError as exc:
        raise InputError(f"git command failed: {' '.join(args)}") from exc

    if returncode != 0:
        message = _decode_text_bytes(output, description="git command output").strip()
        raise InputError(message or f"git command failed: {' '.join(args)}")
    if b"\x00" in output:
        raise InputError("git patch output must be text")
    return _normalize_newlines(_decode_text_bytes(output, description="git patch"))


def _wait_git_patch_process(process: subprocess.Popen[bytes]) -> int:
    try:
        return process.wait(timeout=_GIT_PATCH_PROCESS_WAIT_TIMEOUT_SECONDS)
    except TypeError:
        return process.wait()
    except subprocess.TimeoutExpired:
        process.kill()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        raise


def _ensure_patch_text_size(text: str, *, max_patch_bytes: int) -> None:
    if len(text.encode("utf-8")) > max_patch_bytes:
        raise InputError(f"git patch exceeds {max_patch_bytes} bytes")


def _branch_names(repo: GitRepo) -> tuple[str, ...]:
    return (repo.current_branch,) if repo.current_branch else ()


def _changed_paths_between(repo_root: Path, base_ref: str, head_ref: str) -> list[str]:
    result = run_git(repo_root, "diff", "--name-only", "--no-ext-diff", base_ref, head_ref)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _changed_paths_for_commit(repo_root: Path, revision: str) -> list[str]:
    args = ["show", "--format=", "--name-only"]
    if parent_count(repo_root, revision) > 1:
        args.append("--first-parent")
    args.append(revision)
    result = run_git(repo_root, *args)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _changed_paths_in_worktree(repo_root: Path, staged: bool, unstaged: bool) -> list[str]:
    if staged and unstaged:
        result = run_git(repo_root, "diff", "--name-only", "HEAD")
    elif staged:
        result = run_git(repo_root, "diff", "--cached", "--name-only")
    else:
        result = run_git(repo_root, "diff", "--name-only")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _limit_text_map_paths(paths: list[str], *, max_files: int) -> list[str]:
    return list(dict.fromkeys(paths))[:max_files]


def _resolve_git_files(
    repo_root: Path,
    revision: str,
    paths: list[str],
    *,
    max_file_bytes: int,
) -> dict[str, str]:
    unique_paths = list(dict.fromkeys(paths))
    if not unique_paths:
        return {}
    return _resolve_git_files_serial(
        repo_root,
        revision,
        unique_paths,
        max_file_bytes=max_file_bytes,
    )


def _resolve_git_files_serial(
    repo_root: Path,
    revision: str,
    paths: list[str],
    *,
    max_file_bytes: int,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for path in paths:
        object_spec = f"{revision}:{path}"
        size = _git_object_size(repo_root, object_spec)
        if size is None or size > max_file_bytes:
            continue
        result = run_git_bytes(repo_root, "show", f"{revision}:{path}")
        if result.returncode != 0 or b"\x00" in result.stdout:
            continue
        if len(result.stdout) > max_file_bytes:
            continue
        try:
            decoded = _decode_text_bytes(result.stdout, description=path)
            resolved[path] = _normalize_newlines(decoded)
        except InputError:
            continue
    return resolved


def _git_object_size(repo_root: Path, object_spec: str) -> int | None:
    result = run_git(repo_root, "cat-file", "-s", object_spec, check=False)
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def _resolve_worktree_files(
    repo_root: Path,
    paths: list[str],
    *,
    max_file_bytes: int,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for path in paths:
        target = _git_discovered_regular_file(repo_root, path)
        if target is None:
            continue
        try:
            payload = _read_regular_file_no_follow_bounded(
                target,
                max_bytes=max_file_bytes,
                total_budget_bytes=max_file_bytes,
                label="worktree file",
            )
        except InputError:
            continue
        if b"\x00" in payload:
            continue
        try:
            resolved[path] = _normalize_newlines(_decode_text_bytes(payload, description=path))
        except InputError:
            continue
    return resolved


def _resolve_index_files(
    repo_root: Path,
    paths: list[str],
    *,
    max_file_bytes: int,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for path in paths:
        object_spec = f":{path}"
        size = _git_object_size(repo_root, object_spec)
        if size is None or size > max_file_bytes:
            continue
        result = run_git_bytes(repo_root, "show", f":{path}")
        if result.returncode != 0 or b"\x00" in result.stdout:
            continue
        if len(result.stdout) > max_file_bytes:
            continue
        try:
            decoded = _decode_text_bytes(result.stdout, description=path)
            resolved[path] = _normalize_newlines(decoded)
        except InputError:
            continue
    return resolved


def _list_untracked_files(repo_root: Path) -> list[str]:
    result = run_git(repo_root, "ls-files", "--others", "--exclude-standard")
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.strip().startswith(".ahadiff/")
    ]


def _build_untracked_patch(repo_root: Path, paths: list[str], *, max_patch_bytes: int) -> str:
    chunks: list[str] = []
    remaining_bytes = max_patch_bytes
    for path in paths:
        target = _git_discovered_regular_file(repo_root, path)
        if target is None:
            continue
        data = _read_regular_file_no_follow_bounded(
            target,
            max_bytes=remaining_bytes,
            total_budget_bytes=max_patch_bytes,
            label="untracked file",
        )
        remaining_bytes -= len(data)
        header = f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        if b"\x00" in data:
            chunks.append(header + f"Binary files /dev/null and b/{path} differ\n")
            continue
        text = _normalize_newlines(_decode_text_bytes(data, description=path))
        diff_lines = unified_diff(
            [],
            text.splitlines(keepends=True),
            fromfile="/dev/null",
            tofile=f"b/{path}",
            lineterm="",
        )
        rendered = _render_unified_diff(diff_lines)
        if rendered and not rendered.endswith("\n"):
            rendered += "\n"
        chunks.append(header + rendered)
    return "".join(chunks)


def _git_discovered_regular_file(repo_root: Path, path: str) -> Path | None:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        log.warning("skipping unsafe git-discovered path: %s", path)
        return None
    target = repo_root
    for index, part in enumerate(relative.parts):
        target = target / part
        try:
            path_stat = target.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.warning("skipping unreadable git-discovered path: %s (%s)", path, exc)
            return None
        mode = path_stat.st_mode
        if stat.S_ISLNK(mode):
            log.warning("skipping git-discovered symlink path: %s", path)
            return None
        if _has_windows_reparse_point(path_stat):
            log.warning("skipping git-discovered Windows reparse point path: %s", path)
            return None
        is_final = index == len(relative.parts) - 1
        if is_final and not stat.S_ISREG(mode):
            return None
    return target


def _truncate_segment(segment: _PatchSegment, *, max_lines: int) -> _PatchSegment:
    raw_lines = segment.text.splitlines(keepends=True)[:max_lines]
    text = "".join(raw_lines)
    if text and not text.endswith("\n"):
        text += "\n"
    if text:
        text += _TRUNCATED_MARKER
    text_lines = text.splitlines(keepends=True)
    return _PatchSegment(
        path=segment.path,
        text=text,
        line_count=len(text_lines),
        changed_lines=sum(
            1
            for line in text_lines
            if (line.startswith("+") or line.startswith("-"))
            and not line.startswith("+++")
            and not line.startswith("---")
        ),
        hunk_count=sum(1 for line in text_lines if line.startswith("@@")),
        binary_only=segment.binary_only,
    )


def _graphify_source_path(workspace_root: Path) -> Path:
    return resolve_safe_path_from_root(workspace_root, _GRAPHIFY_RELATIVE_PATH)


def _atomic_write_text(path: Path, text: str) -> None:
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


def _render_unified_diff(lines: Iterable[str]) -> str:
    rendered: list[str] = []
    for line in lines:
        rendered.append(line)
        if not line.endswith("\n"):
            rendered.append("\n")
    return "".join(rendered)


def _decode_text_bytes(data: bytes, *, description: str) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise InputError(f"{description} is not valid UTF-8 or GBK text")


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def _structured_artifact_payloads(capture: CapturedDiff) -> tuple[dict[str, Any], dict[str, Any]]:
    changed_files = parse_unified_diff(capture.persisted_patch_text)
    line_map = build_line_map(changed_files)
    symbols = extract_symbols(
        changed_files,
        before_text_by_path=capture.before_text_by_path,
        after_text_by_path=capture.after_text_by_path,
        symbol_extractor=capture.symbol_extractor,
    )
    return serialize_line_map_payload(line_map), serialize_symbols_payload(symbols)


def _metadata_with_symbol_extractor(
    capture: CapturedDiff,
    symbols_payload: dict[str, Any],
) -> dict[str, Any]:
    resolved = sorted(
        {
            str(item["extractor"])
            for item in cast("list[dict[str, Any]]", symbols_payload.get("symbols", []))
            if item.get("extractor")
        }
    )
    metadata = dict(capture.metadata)
    metadata["symbol_extractor"] = {
        "requested": capture.symbol_extractor,
        "resolved": resolved,
    }
    return metadata


def _effective_symbol_extractor(
    workspace_root: Path,
    *,
    symbol_extractor: SymbolExtractorMode | None,
) -> SymbolExtractorMode:
    if symbol_extractor is not None:
        return symbol_extractor
    try:
        snapshot = (
            load_config(workspace_root)
            if _has_git_root(workspace_root)
            else load_workspace_config(workspace_root)
        )
    except StorageError:
        return cast("SymbolExtractorMode", DEFAULT_CONFIG["capture"]["symbol_extractor"])
    capture_config = cast("dict[str, Any]", snapshot.values["capture"])
    return cast("SymbolExtractorMode", capture_config["symbol_extractor"])


def _redact_json_artifact(raw_text: str, workspace_root: Path) -> str:
    return redaction_pipeline(
        raw_text,
        repo_root=workspace_root if _has_git_root(workspace_root) else None,
        policy=_resolve_policy(workspace_root),
    ).redacted_text


__all__ = [
    "CapturedDiff",
    "GraphifyStatus",
    "capture_patch",
    "detect_graphify_status",
    "import_graphify_artifact",
    "write_input_artifacts",
]
