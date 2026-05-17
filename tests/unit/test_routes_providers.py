# pyright: reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from starlette.testclient import TestClient

from ahadiff.core.config import load_config
from ahadiff.serve import ServeState, create_app
from ahadiff.serve import routes_providers as routes_provider_module

if TYPE_CHECKING:
    from collections.abc import Callable
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


class _AsyncChunkedByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> Any:  # type: ignore[override]
        for chunk in self._chunks:
            yield chunk


class _AsyncStreamContext:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def __aenter__(self) -> httpx.Response:
        return self._response

    async def __aexit__(self, *args: object) -> None:
        del args


def _install_async_client_stub(
    monkeypatch: pytest.MonkeyPatch,
    response_factory: Callable[[str], httpx.Response],
) -> dict[str, Any]:
    captured: dict[str, Any] = {"client_kwargs": None, "requests": []}

    class FakeAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            captured["client_kwargs"] = kwargs

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def get(
            self,
            url: str,
            *,
            headers: dict[str, str] | None = None,
        ) -> httpx.Response:
            captured["requests"].append({"method": "GET", "url": url, "headers": headers or {}})
            return response_factory(url)

        def stream(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str] | None = None,
            extensions: dict[str, Any] | None = None,
        ) -> _AsyncStreamContext:
            captured["requests"].append(
                {
                    "method": method,
                    "url": url,
                    "headers": headers or {},
                    "extensions": extensions,
                }
            )
            return _AsyncStreamContext(response_factory(url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return captured


def _models_response(url: str, model_id: str = "gpt-test") -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(200, json={"data": [{"id": model_id}]}, request=request)


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


def test_discover_models_uses_hardened_transport_and_validates_base_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    captured = _install_async_client_stub(monkeypatch, _models_response)
    validated: list[str] = []

    def validate_spy(base_url: str, *, allowed_local_hosts: tuple[str, ...] = ()) -> str:
        assert {"localhost", "127.0.0.1", "::1"}.issubset(set(allowed_local_hosts))
        validated.append(base_url)
        return base_url

    monkeypatch.setattr(routes_provider_module, "validate_provider_base_url", validate_spy)
    monkeypatch.setattr(
        routes_provider_module.provider_module,
        "validate_remote_url",
        lambda _url: None,
    )

    response = client.post(
        "/api/providers/discover-models",
        headers=_AUTH,
        json={
            "provider_class": "openai",
            "base_url": "https://api.example.test/v1",
            "api_key": "test-key",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"models": ["gpt-test"]}
    assert validated == ["https://api.example.test/v1"]
    assert captured["client_kwargs"] == {
        "trust_env": False,
        "follow_redirects": False,
        "timeout": 5.0,
    }
    request = captured["requests"][0]
    headers = {key.lower(): value for key, value in request["headers"].items()}
    assert request["method"] == "GET"
    assert request["url"] == "https://api.example.test/v1/models"
    assert headers["accept-encoding"] == "identity"
    assert headers["authorization"] == "Bearer test-key"


def test_discover_models_allows_loopback_provider_without_remote_dns_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    captured = _install_async_client_stub(monkeypatch, _models_response)

    def fail_remote_validation(_url: str) -> None:
        raise AssertionError("loopback discovery must not call remote DNS guard")

    monkeypatch.setattr(
        routes_provider_module.provider_module,
        "validate_remote_url",
        fail_remote_validation,
    )

    response = client.post(
        "/api/providers/discover-models",
        headers=_AUTH,
        json={
            "provider_class": "openai",
            "base_url": "http://localhost:1234/v1",
            "api_key": "test-key",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"models": ["gpt-test"]}
    request = captured["requests"][0]
    assert request["url"] == "http://localhost:1234/v1/models"
    assert "host" not in {key.lower() for key in request["headers"]}


def test_fetch_provider_models_uses_same_hardened_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.demo]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "env-key")
    monkeypatch.setattr(
        routes_provider_module.provider_module,
        "validate_remote_url",
        lambda _url: None,
    )
    captured = _install_async_client_stub(
        monkeypatch,
        lambda url: _models_response(url, model_id="from-config"),
    )
    client = _client(state_dir)

    response = client.get("/api/providers/demo/models", headers=_AUTH)

    assert response.status_code == 200
    assert response.json() == {"models": ["from-config"]}
    assert captured["client_kwargs"] == {
        "trust_env": False,
        "follow_redirects": False,
        "timeout": 5.0,
    }
    request = captured["requests"][0]
    headers = {key.lower(): value for key, value in request["headers"].items()}
    assert request["url"] == "https://api.example.test/v1/models"
    assert headers["accept-encoding"] == "identity"
    assert headers["authorization"] == "Bearer env-key"


def test_fetch_provider_models_allows_saved_loopback_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.local]\n"
        'provider_class = "ollama"\n'
        'model_name = "llama3"\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = "AHADIFF_LOCAL_PROVIDER_KEY"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AHADIFF_LOCAL_PROVIDER_KEY", "local-key")
    captured = _install_async_client_stub(
        monkeypatch,
        lambda url: httpx.Response(
            200,
            json={"models": [{"name": "llama3"}]},
            request=httpx.Request("GET", url),
        ),
    )

    def fail_remote_validation(_url: str) -> None:
        raise AssertionError("loopback discovery must not call remote DNS guard")

    monkeypatch.setattr(
        routes_provider_module.provider_module,
        "validate_remote_url",
        fail_remote_validation,
    )
    client = _client(state_dir)

    response = client.get("/api/providers/local/models", headers=_AUTH)

    assert response.status_code == 200
    assert response.json() == {"models": ["llama3"]}
    request = captured["requests"][0]
    assert request["url"] == "http://localhost:11434/api/tags"


def test_save_provider_models_survives_config_reload(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.demo]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n',
        encoding="utf-8",
    )
    client = _client(state_dir)

    saved = client.put(
        "/api/providers/demo/models",
        headers=_AUTH,
        json={"models": ["gpt-5.5", "gpt-5.5", "gpt-5.4-mini"]},
    )
    loaded = client.get("/api/providers", headers=_AUTH)
    snapshot = load_config(tmp_path)

    expected_models = ["gpt-5.5", "gpt-5.4-mini"]
    assert saved.status_code == 200
    assert saved.json()["available_models"] == expected_models
    assert loaded.status_code == 200
    assert loaded.json()["providers"][0]["available_models"] == expected_models
    assert snapshot.values["providers"]["demo"]["available_models"] == tuple(expected_models)


@pytest.mark.parametrize(
    "base_url",
    (
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.7:8000/v1",
    ),
)
def test_discover_models_rejects_private_and_metadata_ranges_via_dns_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    _install_async_client_stub(monkeypatch, _models_response)

    response = client.post(
        "/api/providers/discover-models",
        headers=_AUTH,
        json={"provider_class": "openai", "base_url": base_url, "api_key": "test-key"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == 400
    assert base_url not in body["error"]


def test_discover_models_caps_response_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    def over_cap_response(url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            stream=_AsyncChunkedByteStream((b"x" * 1_048_576, b"x")),
            request=request,
        )

    _install_async_client_stub(monkeypatch, over_cap_response)
    monkeypatch.setattr(
        routes_provider_module.provider_module,
        "validate_remote_url",
        lambda _url: None,
    )

    response = client.post(
        "/api/providers/discover-models",
        headers=_AUTH,
        json={
            "provider_class": "openai",
            "base_url": "https://api.example.test/v1",
            "api_key": "test-key",
        },
    )

    assert response.status_code == 502
    assert response.json()["error"] == "Failed to fetch models: ProviderError"
