from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, cast

import pytest
from starlette.testclient import TestClient

from ahadiff.core.errors import StorageError
from ahadiff.git.repo import repo_write_lock
from ahadiff.serve import ServeState, create_app
from ahadiff.serve import routes_snapshots as routes

if TYPE_CHECKING:
    from pathlib import Path

_HEADERS = {"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"}
_BODY = {"name": "Before", "file": {"name": "example.md", "content": "# Before\n"}}


def _client(root: Path, *, locale: Literal["en", "zh-CN"] = "en") -> TestClient:
    state_dir = root.resolve() / ".ahadiff"
    state_dir.mkdir(exist_ok=True)
    state = ServeState(state_dir=state_dir, token="test-token", locale=locale)
    return TestClient(create_app(state), base_url="http://localhost:8765")


@pytest.mark.parametrize("locale", ["en", "zh-CN"])
def test_snapshot_api_round_trip_and_deleted_baseline_missing(
    tmp_path: Path, locale: Literal["en", "zh-CN"]
) -> None:
    client = _client(tmp_path, locale=locale)
    empty = client.get("/api/snapshots", headers=_HEADERS)
    assert empty.status_code == 200
    assert empty.json() == {"snapshots": [], "max_count": 100, "max_bytes": 16 * 1024 * 1024}

    saved = client.post("/api/snapshots", json=_BODY, headers=_HEADERS)
    assert saved.status_code == 201
    summary = cast("dict[str, object]", saved.json())
    snapshot_id = str(summary["snapshot_id"])
    assert summary["status"] == "ready"
    assert summary["hash_scope"] == "sanitized_utf8_nfc_lf"
    assert "content" not in summary
    listed = client.get("/api/snapshots", headers=_HEADERS)
    assert listed.json()["snapshots"] == [summary]

    detail = client.get(
        f"/api/snapshots/{snapshot_id}",
        params={"expected_hash": str(summary["content_hash"])},
        headers=_HEADERS,
    )
    assert detail.status_code == 200
    assert detail.json()["content"] == "# Before\n"
    assert detail.json()["source"] == "explicit_file"
    assert "stored_bytes" not in detail.json()

    deleted = client.request(
        "DELETE",
        f"/api/snapshots/{snapshot_id}",
        json={"expected_hash": summary["record_hash"]},
        headers=_HEADERS,
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"snapshot_id": snapshot_id, "deleted": True}
    missing = client.get(f"/api/snapshots/{snapshot_id}", headers=_HEADERS)
    assert missing.status_code == 404
    assert missing.json()["error"] == "snapshot_not_found"


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/snapshots"),
        ("POST", "/api/snapshots"),
        ("GET", "/api/snapshots/snap_" + "0" * 32),
        ("DELETE", "/api/snapshots/snap_" + "0" * 32),
    ],
)
def test_every_snapshot_endpoint_requires_token(tmp_path: Path, method: str, path: str) -> None:
    client = _client(tmp_path)
    response = client.request(method, path, headers={"origin": "http://localhost:8765"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize("origin", [None, "https://untrusted.example"])
@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_snapshot_mutation_requires_trusted_origin(
    tmp_path: Path, origin: str | None, method: str
) -> None:
    client = _client(tmp_path)
    headers = {"X-AhaDiff-Token": "test-token"}
    if origin is not None:
        headers["origin"] = origin
    path = "/api/snapshots" if method == "POST" else "/api/snapshots/snap_" + "0" * 32
    response = client.request(method, path, json=_BODY, headers=headers)
    assert response.status_code == 403
    assert response.json()["error_code"] == "LOOPBACK_DENIED"


def test_saved_api_metadata_and_content_do_not_leak_secret(tmp_path: Path) -> None:
    client = _client(tmp_path)
    secret = "sk-" + "z" * 32
    response = client.post(
        "/api/snapshots",
        json={"name": secret, "file": {"name": secret + ".md", "content": f"token: {secret}\n"}},
        headers=_HEADERS,
    )
    assert response.status_code == 201
    assert secret not in response.text
    assert response.json()["sanitized"] is True
    snapshot_id = response.json()["snapshot_id"]
    detail = client.get(f"/api/snapshots/{snapshot_id}", headers=_HEADERS)
    assert detail.status_code == 200
    assert secret not in detail.text
    disk = tmp_path / ".ahadiff" / "snapshots" / f"{snapshot_id}.json"
    assert secret not in disk.read_text(encoding="utf-8")


def test_invalid_body_does_not_echo_values_or_unknown_field_names(tmp_path: Path) -> None:
    client = _client(tmp_path)
    secret = "sk-" + "q" * 32
    response = client.post(
        "/api/snapshots",
        json={"name": "Before", "file": {"name": "../bad", "content": secret}, secret: secret},
        headers=_HEADERS,
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert "../bad" not in response.text
    assert response.json() == {
        "error_code": "INPUT_VALIDATION",
        "error": "snapshot_input_invalid",
        "status": 422,
    }


def test_get_and_delete_reject_hash_mismatch(tmp_path: Path) -> None:
    client = _client(tmp_path)
    saved = client.post("/api/snapshots", json=_BODY, headers=_HEADERS).json()
    snapshot_id = saved["snapshot_id"]
    read = client.get(
        f"/api/snapshots/{snapshot_id}", params={"expected_hash": "0" * 64}, headers=_HEADERS
    )
    assert read.status_code == 400
    assert read.json()["error"] == "snapshot_hash_mismatch"
    deletion = client.request(
        "DELETE",
        f"/api/snapshots/{snapshot_id}",
        json={"expected_hash": "0" * 64},
        headers=_HEADERS,
    )
    assert deletion.status_code == 400
    assert deletion.json()["error"] == "snapshot_hash_mismatch"
    assert len(client.get("/api/snapshots", headers=_HEADERS).json()["snapshots"]) == 1


def test_unknown_version_summary_is_deletable_without_loading_text(tmp_path: Path) -> None:
    client = _client(tmp_path)
    saved = client.post("/api/snapshots", json=_BODY, headers=_HEADERS).json()
    snapshot_id = saved["snapshot_id"]
    path = tmp_path / ".ahadiff" / "snapshots" / f"{snapshot_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 42
    payload["name"] = "untrusted metadata"
    path.write_text(json.dumps(payload), encoding="utf-8")
    summary = client.get("/api/snapshots", headers=_HEADERS).json()["snapshots"][0]
    assert summary["status"] == "unsupported"
    assert summary["name"] is None
    assert "untrusted metadata" not in json.dumps(summary)
    assert client.get(f"/api/snapshots/{snapshot_id}", headers=_HEADERS).status_code == 501
    response = client.request(
        "DELETE",
        f"/api/snapshots/{snapshot_id}",
        json={"expected_hash": summary["record_hash"]},
        headers=_HEADERS,
    )
    assert response.status_code == 200


def test_snapshot_api_repo_lock_blocks_mutation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    with repo_write_lock(tmp_path.resolve() / ".ahadiff" / "ahadiff.lock", command="test lock"):
        response = client.post("/api/snapshots", json=_BODY, headers=_HEADERS)
    assert response.status_code == 409
    assert response.json()["error_code"] == "LOCK_CONFLICT"
    assert client.get("/api/snapshots", headers=_HEADERS).json()["snapshots"] == []


def test_storage_error_payload_has_no_private_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    private_path = str(tmp_path / "private" / "secret.txt")

    def fail_list(_root: Path) -> list[object]:
        raise StorageError(f"could not read {private_path}")

    monkeypatch.setattr(routes, "list_snapshots", fail_list)
    response = client.get("/api/snapshots", headers=_HEADERS)
    assert response.status_code == 500
    assert response.json()["error_code"] == "STORAGE_FS"
    assert response.json()["error"] == "snapshot_operation_failed"
    assert private_path not in response.text


def test_snapshot_write_rejects_linked_state_before_repo_lock(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    client = _client(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / ".ahadiff").rmdir()
    try:
        (root / ".ahadiff").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this platform")
    response = client.post("/api/snapshots", json=_BODY, headers=_HEADERS)
    assert response.status_code == 400
    assert list(outside.iterdir()) == []


def test_snapshot_write_rejects_hardlinked_repo_lock(tmp_path: Path) -> None:
    client = _client(tmp_path)
    outside = tmp_path / "outside.lock"
    outside.write_bytes(b"untouched")
    try:
        (tmp_path / ".ahadiff" / "ahadiff.lock").hardlink_to(outside)
    except OSError:
        pytest.skip("hardlink creation unavailable on this platform")
    response = client.post("/api/snapshots", json=_BODY, headers=_HEADERS)
    assert response.status_code == 400
    assert outside.read_bytes() == b"untouched"
