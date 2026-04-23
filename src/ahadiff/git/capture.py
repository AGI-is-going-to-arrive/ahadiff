from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib as _pathlib
import selectors
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import unified_diff
from queue import Queue
from typing import TYPE_CHECKING, Any, BinaryIO, Literal, cast

from ahadiff.contracts import RunSource
from ahadiff.core.config import DEFAULT_CONFIG
from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.ids import make_run_id
from ahadiff.core.paths import project_state_dir, run_dir
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

from .line_map import build_line_map, serialize_line_map_payload
from .parser import parse_unified_diff
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
from .symbols import extract_symbols, serialize_symbols_payload

if TYPE_CHECKING:
    from collections.abc import Iterable

    Path = _pathlib.Path
else:
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


@dataclass(frozen=True)
class _PatchSegment:
    path: str
    text: str
    line_count: int
    changed_lines: int
    hunk_count: int
    binary_only: bool


_GRAPHIFY_RELATIVE_PATH = Path("graphify-out") / "graph.json"
_TRUNCATED_MARKER = "[truncated]\n"
_ARTIFACT_SET_SCHEMA = "ahadiff.artifact_set"
_ARTIFACT_SET_SCHEMA_VERSION = 1
_TEXT_MAP_SCHEMA = "ahadiff.text_map"
_TEXT_MAP_SCHEMA_VERSION = 1


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
    use_graphify: bool | None = None,
    max_files: int | None = None,
    hard_limit: int | None = None,
    max_patch_bytes: int | None = None,
    privacy_mode: str = "strict_local",
) -> CapturedDiff:
    workspace_root = workspace_root.expanduser().resolve()
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
        max_patch_bytes=max_patch_bytes,
    )
    raw_capture = _filter_ignored_capture(workspace_root, raw_capture)
    graphify_status = detect_graphify_status(workspace_root, use_graphify=use_graphify)

    redaction_result = redaction_pipeline(
        raw_capture.raw_patch_text,
        repo_root=workspace_root if _has_git_root(workspace_root) else None,
        policy=_resolve_policy(workspace_root),
        resolved_files=raw_capture.resolved_files,
        branch_names=raw_capture.branch_names,
        tag_names=raw_capture.tag_names,
    )
    protected_patch = protect_untrusted_text(
        redaction_result.redacted_text,
        source_name="patch.diff",
        source_kind="raw_patch",
    ).protected_text
    persisted_patch_text, selection = _apply_capture_limits(
        protected_patch,
        max_files=max_files or int(DEFAULT_CONFIG["capture"]["max_files"]),
        hard_limit=hard_limit or int(DEFAULT_CONFIG["capture"]["hard_limit"]),
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
    )


def write_input_artifacts(capture: CapturedDiff) -> tuple[Path, Path]:
    metadata_text = _redact_json_artifact(
        _render_json_text(capture.metadata),
        capture.workspace_root,
    )
    line_map_payload, symbols_payload = _structured_artifact_payloads(capture)
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
    artifacts_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = artifacts_dir.parent / f".{artifacts_dir.name}.tmp"
    if tmp_dir.exists():
        _remove_tree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=False)
    try:
        for name, text in artifact_texts.items():
            _atomic_write_text(tmp_dir / name, text)
        if artifacts_dir.exists():
            raise StorageError(f"run artifacts already exist: {artifacts_dir}")
        tmp_dir.rename(artifacts_dir)
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


def detect_graphify_status(workspace_root: Path, *, use_graphify: bool | None) -> GraphifyStatus:
    source_path = _graphify_source_path(workspace_root)
    imported_path = _state_dir(workspace_root) / "graphify" / "graph.json"
    source_exists = source_path.exists()
    imported_exists = imported_path.exists()
    if use_graphify is True and not source_exists:
        raise InputError("graphify-out/graph.json is required when --use-graphify is set")

    enabled = source_exists if use_graphify is None else use_graphify and source_exists
    has_graph = enabled and source_exists
    freshness = "source_present" if source_exists else None
    provenance = {"source": str(source_path.relative_to(workspace_root))}
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


def import_graphify_artifact(workspace_root: Path, *, force: bool = False) -> GraphifyStatus:
    status = detect_graphify_status(workspace_root, use_graphify=True)
    if status.imported_exists and not force:
        return status

    imported_dir = status.imported_path.parent
    imported_dir.mkdir(parents=True, exist_ok=True)
    graph_bytes = status.source_path.read_bytes()
    graph_limit = int(DEFAULT_CONFIG["capture"]["max_patch_bytes"])
    if len(graph_bytes) > graph_limit:
        raise InputError(f"graphify graph exceeds {graph_limit} bytes")
    graph_text = _decode_text_bytes(graph_bytes, description="graphify graph")
    graph_text = protect_untrusted_text(
        redaction_pipeline(graph_text, repo_root=workspace_root).redacted_text,
        source_name="graphify graph",
        source_kind="string",
    ).protected_text
    _atomic_write_text(status.imported_path, graph_text)
    return detect_graphify_status(workspace_root, use_graphify=True)


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
    max_patch_bytes: int | None,
) -> _RawCapture:
    selections = [
        revision is not None,
        last,
        since is not None,
        patch is not None,
        compare is not None,
        staged or unstaged,
    ]
    if sum(1 for item in selections if item) != 1:
        raise InputError(
            "choose exactly one input mode: revision range/single commit, --last, "
            "--since, --staged/--unstaged, --patch, or --compare"
        )
    if author is not None and since is None:
        raise InputError("--author can only be used together with --since")

    if patch is not None:
        return _capture_patch_input(
            workspace_root=workspace_root,
            patch=patch,
            max_patch_bytes=max_patch_bytes or int(DEFAULT_CONFIG["capture"]["max_patch_bytes"]),
        )
    if compare is not None:
        return _capture_compare_input(workspace_root, compare)

    repo = open_repo(workspace_root)
    ensure_no_merge_conflicts(repo)
    if since is not None:
        return _capture_since(
            repo,
            since=since,
            author=author,
            max_patch_bytes=max_patch_bytes or int(DEFAULT_CONFIG["capture"]["max_patch_bytes"]),
        )
    if last:
        return _capture_last(
            repo,
            max_patch_bytes=max_patch_bytes or int(DEFAULT_CONFIG["capture"]["max_patch_bytes"]),
        )
    if staged or unstaged:
        return _capture_worktree(
            repo,
            staged=staged,
            unstaged=unstaged,
            include_untracked=include_untracked,
            max_patch_bytes=max_patch_bytes or int(DEFAULT_CONFIG["capture"]["max_patch_bytes"]),
        )
    if revision is None:
        raise InputError("revision input was not provided")
    return _capture_revision(
        repo,
        revision,
        max_patch_bytes=max_patch_bytes or int(DEFAULT_CONFIG["capture"]["max_patch_bytes"]),
    )


def _capture_revision(repo: GitRepo, revision: str, *, max_patch_bytes: int) -> _RawCapture:
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
        changed_paths = _changed_paths_between(repo.root, base_ref, head_ref)
        before_text_by_path = _resolve_git_files(repo.root, base_ref, changed_paths)
        after_text_by_path = _resolve_git_files(repo.root, head_ref, changed_paths)
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
    changed_paths = _changed_paths_for_commit(repo.root, sha)
    before_text_by_path = _resolve_git_files(repo.root, base_ref, changed_paths)
    after_text_by_path = _resolve_git_files(repo.root, sha, changed_paths)
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


def _capture_last(repo: GitRepo, *, max_patch_bytes: int) -> _RawCapture:
    sha = ensure_head_exists(repo)
    raw_patch, base_ref = _single_commit_patch(repo, sha, max_patch_bytes=max_patch_bytes)
    changed_paths = _changed_paths_for_commit(repo.root, sha)
    before_text_by_path = _resolve_git_files(repo.root, base_ref, changed_paths)
    after_text_by_path = _resolve_git_files(repo.root, sha, changed_paths)
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
    max_patch_bytes: int,
) -> _RawCapture:
    ensure_head_exists(repo)
    args = ["rev-list", "--first-parent", f"--since={since}", "HEAD"]
    if author is not None:
        args.insert(2, f"--author={author}")
    result = run_git(repo.root, *args)
    matched_commits = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not matched_commits:
        raise InputError("该时间范围内无 commit")

    if len(matched_commits) == 1:
        capture = _capture_revision(repo, matched_commits[0], max_patch_bytes=max_patch_bytes)
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
    changed_paths = _changed_paths_between(repo.root, base_ref, head_ref)
    before_text_by_path = _resolve_git_files(repo.root, base_ref, changed_paths)
    after_text_by_path = _resolve_git_files(repo.root, head_ref, changed_paths)
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
        patch_text = patch_text + _build_untracked_patch(repo.root, untracked_files)
        _ensure_patch_text_size(patch_text, max_patch_bytes=max_patch_bytes)

    changed_paths = _changed_paths_in_worktree(repo.root, staged, unstaged)
    if combined_mode:
        before_text_by_path = _resolve_git_files(repo.root, head_sha, changed_paths)
        after_text_by_path = _resolve_worktree_files(repo.root, changed_paths)
    elif staged:
        before_text_by_path = _resolve_git_files(repo.root, head_sha, changed_paths)
        after_text_by_path = _resolve_index_files(repo.root, changed_paths)
    else:
        before_text_by_path = _resolve_index_files(repo.root, changed_paths)
        after_text_by_path = _resolve_worktree_files(repo.root, changed_paths)
    after_text_by_path.update(_resolve_worktree_files(repo.root, untracked_files))
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
            raise InputError("stdin 需要管道输入，如 `git diff | ahadiff learn --patch -`")
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
        try:
            data = patch_path.read_bytes()
        except OSError as exc:
            raise InputError(f"无法读取 patch 文件: {patch}") from exc
        if len(data) > max_patch_bytes:
            raise InputError(f"patch file exceeds {max_patch_bytes} bytes")
        source_kind = "patch_file"
        source_name = Path(canonicalize_path_text(patch_path.relative_to(workspace_root))).name

    if b"\x00" in data:
        raise InputError("patch input must be text, not binary")
    raw_patch = _decode_text_bytes(data, description="patch input")
    raw_patch = _normalize_newlines(raw_patch)
    source_ref = f"sha256:{hashlib.sha256(raw_patch.encode('utf-8')).hexdigest()}"
    return _RawCapture(
        source_kind=source_kind,
        source_ref=source_ref,
        capability_level=1,
        raw_patch_text=raw_patch,
        base_ref=None,
        head_ref=None,
        source_detail={
            "type": source_kind,
            "name": source_name,
            "patch_hash": source_ref,
        },
        branch_names=(),
        tag_names=(),
        resolved_files={},
        before_text_by_path={},
        after_text_by_path={},
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


def _capture_compare_input(workspace_root: Path, compare: tuple[Path, Path]) -> _RawCapture:
    old_path = resolve_safe_path_from_root(workspace_root, compare[0])
    new_path = resolve_safe_path_from_root(workspace_root, compare[1])
    try:
        old_bytes = old_path.read_bytes()
        new_bytes = new_path.read_bytes()
    except OSError as exc:
        raise InputError("无法读取文件") from exc
    old_binary = b"\x00" in old_bytes
    new_binary = b"\x00" in new_bytes
    old_rel = str(old_path.relative_to(workspace_root))
    new_rel = str(new_path.relative_to(workspace_root))

    if old_binary or new_binary:
        raw_patch = f"Binary files a/{old_rel} and b/{new_rel} differ\n"
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
        raise InputError("文件内容相同，无差异")

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

    segments: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("diff --git ") and current:
            segments.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        segments.append(current)

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
    return "__unknown__"


def _normalize_segment_path_token(value: str, *, prefix: str) -> str | None:
    return normalize_diff_path_token(value, prefix=prefix)


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
    return workspace_root / ".ahadiff"


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
    command = ["git", "-C", str(repo_root), *args]
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
                    process.wait()
                    raise InputError(f"git patch exceeds {max_patch_bytes} bytes")
                chunks.append(chunk)

            output = b"".join(chunks)
            returncode = process.wait()
    except OSError as exc:
        raise InputError(f"git command failed: {' '.join(args)}") from exc

    if returncode != 0:
        message = _decode_text_bytes(output, description="git command output").strip()
        raise InputError(message or f"git command failed: {' '.join(args)}")
    if b"\x00" in output:
        raise InputError("git patch output must be text")
    return _normalize_newlines(_decode_text_bytes(output, description="git patch"))


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


def _resolve_git_files(repo_root: Path, revision: str, paths: list[str]) -> dict[str, str]:
    unique_paths = list(dict.fromkeys(paths))
    if not unique_paths:
        return {}

    payload = "".join(f"{revision}:{path}\n" for path in unique_paths).encode("utf-8")
    result = run_git_bytes(repo_root, "cat-file", "--batch", input_bytes=payload)
    if result.returncode != 0:
        return _resolve_git_files_serial(repo_root, revision, unique_paths)

    stream = io.BytesIO(result.stdout)
    resolved: dict[str, str] = {}
    for path in unique_paths:
        header = stream.readline()
        if not header:
            return _resolve_git_files_serial(repo_root, revision, unique_paths)
        if header.endswith(b" missing\n"):
            continue
        parts = header.rstrip(b"\n").split(b" ", 2)
        if len(parts) != 3:
            return _resolve_git_files_serial(repo_root, revision, unique_paths)
        _, object_type, size_text = parts
        try:
            size = int(size_text)
        except ValueError:
            return _resolve_git_files_serial(repo_root, revision, unique_paths)
        payload = stream.read(size)
        stream.read(1)
        if object_type != b"blob" or b"\x00" in payload:
            continue
        try:
            decoded = _decode_text_bytes(payload, description=path)
            resolved[path] = _normalize_newlines(decoded)
        except InputError:
            continue
    return resolved


def _resolve_git_files_serial(repo_root: Path, revision: str, paths: list[str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for path in paths:
        result = run_git_bytes(repo_root, "show", f"{revision}:{path}")
        if result.returncode != 0 or b"\x00" in result.stdout:
            continue
        try:
            decoded = _decode_text_bytes(result.stdout, description=path)
            resolved[path] = _normalize_newlines(decoded)
        except InputError:
            continue
    return resolved


def _resolve_worktree_files(repo_root: Path, paths: list[str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for path in paths:
        target = repo_root / path
        if not target.exists() or not target.is_file():
            continue
        payload = target.read_bytes()
        if b"\x00" in payload:
            continue
        try:
            resolved[path] = _normalize_newlines(_decode_text_bytes(payload, description=path))
        except InputError:
            continue
    return resolved


def _resolve_index_files(repo_root: Path, paths: list[str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for path in paths:
        result = run_git_bytes(repo_root, "show", f":{path}")
        if result.returncode != 0 or b"\x00" in result.stdout:
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


def _build_untracked_patch(repo_root: Path, paths: list[str]) -> str:
    chunks: list[str] = []
    for path in paths:
        target = repo_root / path
        if not target.exists() or not target.is_file():
            continue
        data = target.read_bytes()
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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


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
    )
    return serialize_line_map_payload(line_map), serialize_symbols_payload(symbols)


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
