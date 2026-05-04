from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from starlette.testclient import TestClient

from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from pathlib import Path

_AUTH = {"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"}


def _client(state_dir: Path) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token="test-token"))
    return TestClient(app, base_url="http://localhost:8765")


def _provider_payload(**overrides: Any) -> dict[str, object]:
    payload: dict[str, object] = {
        "alias": "demo",
        "provider_class": "openai",
        "model_name": "gpt-5.4-mini",
        "base_url": "https://api.example.test/v1",
        "api_key_env": "AHADIFF_PROVIDER_API_KEY",
    }
    payload.update(overrides)
    return payload


def _audit_events(state_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (state_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def test_get_providers_masks_url_userinfo_from_config(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.demo]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://user:embedded-secret@api.example.test/v1"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n',
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.get("/api/providers", headers={"X-AhaDiff-Token": "test-token"})

    assert response.status_code == 200
    providers = response.json()["providers"]
    assert providers[0]["base_url"] == "https://***@api.example.test/v1"
    assert "embedded-secret" not in json.dumps(response.json())


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    (
        ("put", "/api/providers/9bad", {"model_name": "gpt-5.4"}),
        ("delete", "/api/providers/9bad", None),
        ("post", "/api/providers/9bad/probe", {}),
    ),
)
def test_provider_path_alias_validation_returns_400_before_registry_mutation(
    tmp_path: Path,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    if payload is None:
        response = getattr(client, method)(path, headers=_AUTH)
    else:
        response = getattr(client, method)(path, headers=_AUTH, json=payload)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_alias", "status": 400}
    assert not (state_dir / "config.toml").exists()


def test_provider_create_alias_validation_returns_400_before_registry_mutation(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(alias="9bad"),
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_alias", "status": 400}
    assert not (state_dir / "config.toml").exists()


@pytest.mark.parametrize(
    "base_url",
    (
        "ftp://api.example.test",
        "https://user:pass@api.example.test/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/computeMetadata/v1",
        "http://127.0.0.1:11434",
        "http://10.0.0.7:8000",
    ),
)
def test_provider_create_rejects_unsafe_base_urls(tmp_path: Path, base_url: str) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(base_url=base_url),
    )

    assert response.status_code == 422
    assert "base_url" in response.json()["error"]
    assert not (state_dir / "config.toml").exists()


def test_provider_update_rejects_unsafe_base_url_before_mutation(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    created = client.post("/api/providers", headers=_AUTH, json=_provider_payload())
    assert created.status_code == 201

    response = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"base_url": "https://user:secret@api.example.test/v1"},
    )

    assert response.status_code == 422
    assert "base_url" in response.json()["error"]
    providers = (state_dir / "config.toml").read_text(encoding="utf-8")
    assert "user:secret" not in providers
    assert "https://api.example.test/v1" in providers


def test_provider_crud_audit_events_are_redacted_and_do_not_log_api_keys(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    created = client.post("/api/providers", headers=_AUTH, json=_provider_payload())
    updated = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={
            "provider_class": "openai_responses",
            "model_name": "gpt-5.4",
            "base_url": "https://api2.example.test/v1/responses/",
        },
    )
    deleted = client.delete("/api/providers/demo", headers=_AUTH)

    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["provider"]["base_url"] == "https://api2.example.test"
    assert deleted.status_code == 200

    events = _audit_events(state_dir)
    assert [event["event_type"] for event in events] == [
        "provider_create",
        "provider_update",
        "provider_delete",
    ]
    assert [event["base_url"] for event in events] == [
        "https://api.example.test/v1",
        "https://api2.example.test",
        "https://api2.example.test",
    ]
    serialized_events = json.dumps(events, sort_keys=True)
    assert "api_key" not in serialized_events.lower()
    assert "AHADIFF_PROVIDER_API_KEY" not in serialized_events
