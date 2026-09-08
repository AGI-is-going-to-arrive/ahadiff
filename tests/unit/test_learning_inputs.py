from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Literal

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from ahadiff.cli import app
from ahadiff.contracts.run_source import CompareFileInput
from ahadiff.core import learn_inputs
from ahadiff.core.errors import AhaDiffError, InputError
from ahadiff.core.snapshots import load_snapshot, save_snapshot
from ahadiff.git.repo import repo_write_lock
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_HEADERS = {"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"}


def _client(root: Path, locale: Literal["en", "zh-CN"] = "en") -> TestClient:
    state_dir = root / ".ahadiff"
    state_dir.mkdir(exist_ok=True)
    return TestClient(
        create_app(
            ServeState(
                state_dir=state_dir,
                token="test-token",
                locale=locale,
                global_config_root=root / "global-config",
            )
        ),
        base_url="http://localhost:8765",
    )


@pytest.mark.parametrize("fallback", [False, True])
def test_selected_file_read_is_bounded_and_unicode_portable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fallback: bool
) -> None:
    if fallback:
        monkeypatch.setattr(learn_inputs, "_HAS_DIR_FD", False)
    source = tmp_path / "学习.md"
    source.write_text("# 学习\r\n\r\nQueue order.\r\n", encoding="utf-8", newline="")
    value = learn_inputs.read_learning_file(tmp_path, source)
    assert value.name == "学习.md"
    assert "Queue order." in value.content
    with pytest.raises(InputError, match="byte limit"):
        learn_inputs.read_learning_text(tmp_path, source, max_bytes=2)


@pytest.mark.parametrize("fallback", [False, True])
def test_parent_swapped_after_path_validation_cannot_read_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fallback: bool
) -> None:
    root = tmp_path / "workspace"
    parent = root / "sub"
    parent.mkdir(parents=True)
    (parent / "source.md").write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    external = outside / "source.md"
    external.write_text("must not be read", encoding="utf-8")
    resolve = learn_inputs.resolve_safe_path_from_root
    if fallback:
        monkeypatch.setattr(learn_inputs, "_HAS_DIR_FD", False)

    def switch_parent(workspace: Path, file: str | Path) -> Path:
        resolved = resolve(workspace, file)
        parent.rename(root / "original")
        try:
            parent.symlink_to(outside, target_is_directory=True)
        except OSError:
            (root / "original").rename(parent)
            pytest.skip("symlink creation is unavailable on this filesystem")
        return resolved

    monkeypatch.setattr(learn_inputs, "resolve_safe_path_from_root", switch_parent)
    with pytest.raises(InputError):
        learn_inputs.read_learning_file(root, parent / "source.md")
    assert external.read_text(encoding="utf-8") == "must not be read"


def test_file_changed_during_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.md"
    source.write_text("before", encoding="utf-8")
    read = os.read
    changed = False

    def race_read(fd: int, count: int) -> bytes:
        nonlocal changed
        data = read(fd, count)
        if data and not changed:
            changed = True
            source.write_text("different contents", encoding="utf-8")
        return data

    monkeypatch.setattr(learn_inputs.os, "read", race_read)
    with pytest.raises(InputError, match="changed"):
        learn_inputs.read_learning_file(tmp_path, source)


def test_repo_lock_rejects_hardlink_without_modifying_target(tmp_path: Path) -> None:
    state = tmp_path / ".ahadiff"
    state.mkdir()
    external = tmp_path / "valuable.txt"
    external.write_text("retain exactly", encoding="utf-8")
    try:
        os.link(external, state / "ahadiff.lock")
    except OSError:
        pytest.skip("hardlink creation is unavailable on this filesystem")
    with (
        pytest.raises(InputError, match="hardlink"),
        repo_write_lock(state / "ahadiff.lock", command="snapshot save"),
    ):
        pytest.fail("unsafe lock acquired")
    assert external.read_text(encoding="utf-8") == "retain exactly"


def test_repo_lock_rejects_parent_link_before_any_external_write(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / ".ahadiff").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this filesystem")
    with (
        pytest.raises(InputError),
        repo_write_lock(root / ".ahadiff" / "ahadiff.lock", command="snapshot save"),
    ):
        pytest.fail("unsafe lock acquired")
    assert list(outside.iterdir()) == []


def test_snapshot_cli_uses_git_root_from_uninitialized_subdirectory(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    sub = root / "sub"
    sub.mkdir(parents=True)
    (root / ".git").mkdir()
    source = sub / "before.md"
    source.write_text("# Local\n", encoding="utf-8")
    result = CliRunner().invoke(
        app(),
        ["snapshot", "save", str(source), "--name", "Before", "--repo-root", str(sub)],
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert load_snapshot(root, summary["snapshot_id"]).content == "# Local\n"
    assert not (sub / ".ahadiff").exists()


@pytest.mark.parametrize("chunked", [False, True])
def test_snapshot_delete_body_limit_includes_chunked_requests(
    tmp_path: Path, chunked: bool
) -> None:
    client = _client(tmp_path)
    headers = {**_HEADERS, "content-type": "application/json"}
    body = b'{"expected_hash":"' + b"0" * (1024 * 1024) + b'"}'

    def chunks() -> Iterator[bytes]:
        for index in range(0, len(body), 65_536):
            yield body[index : index + 65_536]

    response = client.request(
        "DELETE",
        "/api/snapshots/snap_" + "0" * 32,
        content=chunks() if chunked else body,
        headers=headers,
    )
    assert response.status_code == 413
    assert response.json()["error_code"] == "RUN_ARTIFACT_TOO_LARGE"


@pytest.mark.parametrize("locale", ["en", "zh-CN"])
def test_document_estimate_has_independent_source_preview(
    tmp_path: Path, locale: Literal["en", "zh-CN"]
) -> None:
    with _client(tmp_path, locale) as client:
        response = client.post(
            "/api/learn/estimate",
            json={
                "document": {
                    "name": "资料.md",
                    "content": "# Queue\n\nA queue keeps arrival order.\n",
                }
            },
            headers=_HEADERS,
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_kind"] == "document"
    assert payload["preview_patch"] == ""
    assert "A queue keeps arrival order." in payload["preview_document"]
    assert payload["patch_bytes"] == 0
    assert payload["source_bytes"] > 0
    assert not (tmp_path / ".ahadiff" / "runs").exists()


@pytest.mark.parametrize(
    "body",
    [
        {"document": {"name": "x.md", "content": "x"}, "staged": True},
        {"document": {"name": "x.md", "content": "x"}, "patch": ""},
        {"snapshot_id": "snap_" + "0" * 32},
        {"snapshot_after": {"name": "x.md", "content": "x"}},
        {"review_context": "x" * 8193},
        {"review_context": "\ud800"},
        {"document": {"name": "../x.md", "content": "x"}},
    ],
)
def test_new_input_validation_is_shared_by_estimate_and_submit(
    tmp_path: Path, body: object
) -> None:
    with _client(tmp_path) as client:
        for endpoint in ("/api/learn/estimate", "/api/learn"):
            response = client.post(
                endpoint,
                content=json.dumps(body, ensure_ascii=True),
                headers={**_HEADERS, "content-type": "application/json"},
            )
            assert response.status_code == 422, response.text
            assert response.json()["error_code"] == "INPUT_VALIDATION"


def test_snapshot_estimate_normalizes_both_secret_bearing_versions(tmp_path: Path) -> None:
    original = CompareFileInput(
        name="settings.md", content="token = sk-abcdefghijklmnopqrstuvwx\nvalue = 1\n"
    )
    record = save_snapshot(tmp_path, name="Before", file=original)
    with _client(tmp_path) as client:
        payload = {
            "snapshot_id": record.snapshot_id,
            "snapshot_hash": record.content_hash,
            "snapshot_after": original.model_dump(),
        }
        response = client.post("/api/learn/estimate", json=payload, headers=_HEADERS)
        assert response.status_code == 200, response.text
        assert response.json()["preview_patch"] == ""
        payload["snapshot_hash"] = "0" * 64
        mismatch = client.post("/api/learn/estimate", json=payload, headers=_HEADERS)
    assert mismatch.status_code == 400
    assert "sk-abcdefghijklmnopqrstuvwx" not in mismatch.text


def test_internal_file_and_hardlinked_inputs_remain_inaccessible(tmp_path: Path) -> None:
    internal = tmp_path / ".ahadiff"
    internal.mkdir()
    secret = internal / "private.md"
    secret.write_text("private synthetic content", encoding="utf-8")
    with pytest.raises(AhaDiffError):
        learn_inputs.read_learning_file(tmp_path, secret)
    try:
        os.link(secret, tmp_path / "selected.md")
    except OSError:
        pytest.skip("hardlink creation is unavailable on this filesystem")
    with pytest.raises(AhaDiffError):
        learn_inputs.read_learning_file(tmp_path, tmp_path / "selected.md")


@pytest.mark.parametrize("active", [False, True])
def test_active_practice_is_explicit_in_the_shared_estimate_contract(
    tmp_path: Path, active: bool
) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/learn/estimate",
            json={
                "document": {"name": "queue.md", "content": "# Queue\n\nArrival order matters.\n"},
                "active_practice": active,
            },
            headers=_HEADERS,
        )
    assert response.status_code == 200, response.text
    assert response.json()["active_practice"] is active
    assert response.json()["source_kind"] == "document"


def test_cli_learn_active_practice_persists_mode_without_a_model_call(tmp_path: Path) -> None:
    source = tmp_path / "queue.md"
    source.write_text("# Queue\n\nArrival order matters.\n", encoding="utf-8")
    result = CliRunner().invoke(
        app(),
        [
            "learn",
            "--document",
            str(source),
            "--active-practice",
            "--dry-run",
            "--repo-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    run = next((tmp_path / ".ahadiff" / "runs").iterdir())
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["active_practice"] is True
    assert (run / "document.md").is_file()
    assert not (run / "patch.diff").exists()
    assert not (run / "lesson").exists()
