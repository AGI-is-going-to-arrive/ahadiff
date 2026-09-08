"""Token-protected explicit local snapshot endpoints."""

from __future__ import annotations

from json import JSONDecodeError
from typing import TYPE_CHECKING

from anyio import to_thread
from pydantic import ValidationError
from starlette.responses import JSONResponse

from ahadiff.contracts import ErrorCode
from ahadiff.contracts.snapshots import (
    SnapshotDeleteRequest,
    SnapshotDeleteResponse,
    SnapshotListResponse,
    SnapshotSaveRequest,
    SnapshotSummary,
)
from ahadiff.core.errors import AhaDiffError
from ahadiff.core.paths import validate_state_path_no_symlinks
from ahadiff.core.snapshots import (
    delete_snapshot,
    list_snapshots,
    load_snapshot,
    save_snapshot,
)

from ._errors import error_response
from .auth import require_write_token, serve_state
from .lock import serve_repo_write_lock

if TYPE_CHECKING:
    from starlette.requests import Request

    from ahadiff.contracts.snapshots import SnapshotRecord

    from .state import ServeState


def _snapshot_error(exc: AhaDiffError) -> JSONResponse:
    message = str(exc)
    # Never project path-bearing helper errors, untrusted inputs or tracebacks.
    if not message.startswith("snapshot_") or not all(
        char.isascii() and (char.islower() or char == "_") for char in message
    ):
        message = "snapshot_operation_failed"
    return error_response(exc.code, message)


def _save(state: ServeState, body: SnapshotSaveRequest) -> SnapshotSummary:
    _validate_repo_lock_path(state)
    with serve_repo_write_lock(state, command="serve snapshot save"):
        record = save_snapshot(state.state_dir.parent, name=body.name, file=body.file)
    return record.to_summary()


def _load(state: ServeState, snapshot_id: str, expected_hash: str | None) -> SnapshotRecord:
    return load_snapshot(state.state_dir.parent, snapshot_id, expected_hash=expected_hash)


def _delete(state: ServeState, snapshot_id: str, body: SnapshotDeleteRequest) -> None:
    _validate_repo_lock_path(state)
    with serve_repo_write_lock(state, command="serve snapshot delete"):
        delete_snapshot(state.state_dir.parent, snapshot_id, expected_hash=body.expected_hash)


def _validate_repo_lock_path(state: ServeState) -> None:
    from ahadiff.core.errors import InputError

    assert state.repo_lock_path is not None
    validate_state_path_no_symlinks(state.repo_lock_path, allow_missing_leaf=True)
    try:
        lock_stat = state.repo_lock_path.lstat()
    except FileNotFoundError:
        return
    if lock_stat.st_nlink != 1:
        raise InputError("snapshot_repo_lock_must_not_be_hardlinked")


async def get_snapshots(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    try:
        summaries = await to_thread.run_sync(list_snapshots, state.state_dir.parent)
    except AhaDiffError as exc:
        return _snapshot_error(exc)
    return JSONResponse(SnapshotListResponse(snapshots=summaries).model_dump(mode="json"))


async def post_snapshot(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    try:
        body = SnapshotSaveRequest.model_validate(await request.json())
    except (ValidationError, JSONDecodeError, UnicodeError):
        return error_response(ErrorCode.INPUT_VALIDATION, "snapshot_input_invalid")
    try:
        summary = await to_thread.run_sync(_save, state, body)
    except AhaDiffError as exc:
        return _snapshot_error(exc)
    return JSONResponse(summary.model_dump(mode="json"), status_code=201)


async def get_snapshot(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    try:
        record = await to_thread.run_sync(
            _load,
            state,
            str(request.path_params["snapshot_id"]),
            request.query_params.get("expected_hash"),
        )
    except AhaDiffError as exc:
        return _snapshot_error(exc)
    return JSONResponse(record.model_dump(mode="json"))


async def delete_snapshot_route(request: Request) -> JSONResponse:
    require_write_token(request)
    state = serve_state(request)
    snapshot_id = str(request.path_params["snapshot_id"])
    try:
        body = SnapshotDeleteRequest.model_validate(await request.json())
    except (ValidationError, JSONDecodeError, UnicodeError):
        return error_response(ErrorCode.INPUT_VALIDATION, "snapshot_input_invalid")
    try:
        await to_thread.run_sync(_delete, state, snapshot_id, body)
    except AhaDiffError as exc:
        return _snapshot_error(exc)
    return JSONResponse(SnapshotDeleteResponse(snapshot_id=snapshot_id).model_dump(mode="json"))


__all__ = ["delete_snapshot_route", "get_snapshot", "get_snapshots", "post_snapshot"]
