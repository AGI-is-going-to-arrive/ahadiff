# pyright: reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

import json
import os
import stat
import subprocess
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from starlette.testclient import TestClient

from ahadiff.contracts import ErrorCode
from ahadiff.contracts.run_source import ProviderCapabilities, ProviderConfig
from ahadiff.core import config as config_module
from ahadiff.core.config import (
    apply_repo_env_file,
    iter_resolved_settings,
    load_config,
    load_repo_env_file,
    resolve_provider_api_key,
    write_repo_env_var,
)
from ahadiff.core.errors import ConfigError, ProviderError
from ahadiff.llm.schemas import ProbeReport
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


def _successful_probe_report(
    *,
    provider_name: str,
    provider_class: str,
    model_name: str,
    model_limits_name: str | None,
    base_url: str,
    api_key_env: str,
) -> ProbeReport:
    return ProbeReport(
        provider_name=provider_name,
        config=ProviderConfig(
            provider_class=cast("Any", provider_class),
            model_name=model_name,
            model_limits_name=model_limits_name,
            base_url=base_url,
            api_key_env=api_key_env,
        ),
        capabilities=ProviderCapabilities(
            supports_stream=True,
            supports_json_mode=True,
            supports_tool_use=False,
            supports_temperature=True,
            supports_rate_limit_headers=False,
            supports_context_probe=True,
            tokenizer_estimation="tiktoken",
            api_family="openai",
            api_family_version="chat_completions",
            provider_kind="remote",
        ),
        connectivity_ok=True,
        transport_target="remote",
        notes=("provider probe succeeded",),
    )


def test_repo_env_file_write_upserts_quotes_and_chmods(tmp_path: Path) -> None:
    env_path = tmp_path / ".ahadiff" / ".env"
    env_path.parent.mkdir()
    env_path.write_text(
        "# keep comment\n"
        "AHADIFF_OTHER_KEY=old\n"
        "AHADIFF_DEMO_KEY=old-value\n"
        "export AHADIFF_DEMO_KEY=stale-wins-before-fix\n",
        encoding="utf-8",
    )

    write_repo_env_var(env_path, "AHADIFF_DEMO_KEY", ' sk-test#with"quote" ')
    write_repo_env_var(env_path, "AHADIFF_NEW_KEY", "plain-token")

    text = env_path.read_text(encoding="utf-8")
    assert "# keep comment\n" in text
    assert "AHADIFF_OTHER_KEY=old\n" in text
    assert 'AHADIFF_DEMO_KEY=" sk-test#with\\"quote\\" "\n' in text
    assert text.count("AHADIFF_DEMO_KEY=") == 1
    assert "stale-wins-before-fix" not in text
    assert "AHADIFF_NEW_KEY=plain-token\n" in text
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600

    with pytest.raises(ConfigError, match="must not contain newlines"):
        write_repo_env_var(env_path, "AHADIFF_BAD_KEY", "line1\nline2")


def test_repo_env_file_write_retries_transient_windows_sharing_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".ahadiff" / ".env"
    env_path.parent.mkdir()
    original_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(src: Any, dst: Any) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            error = PermissionError("sharing violation")
            error.winerror = 32  # type: ignore[attr-defined]
            raise error
        original_replace(src, dst)

    monkeypatch.setattr(config_module.os, "replace", flaky_replace)
    monkeypatch.setattr(config_module.time, "sleep", lambda _seconds: None)

    write_repo_env_var(env_path, "AHADIFF_DEMO_KEY", "plain-token")

    assert calls["count"] == 2
    assert load_repo_env_file(env_path) == {"AHADIFF_DEMO_KEY": "plain-token"}


def test_repo_env_file_loads_and_preserves_system_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".ahadiff" / ".env"
    env_path.parent.mkdir()
    env_path.write_text(
        "# comment\n"
        'export AHADIFF_DEMO_KEY="from-file"\n'
        "AHADIFF_OTHER_KEY=plain-value # trailing comment\n"
        "not a valid env line\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AHADIFF_DEMO_KEY", "from-system")
    monkeypatch.delenv("AHADIFF_OTHER_KEY", raising=False)

    loaded = load_repo_env_file(env_path)
    apply_repo_env_file(env_path)

    assert loaded == {
        "AHADIFF_DEMO_KEY": "from-file",
        "AHADIFF_OTHER_KEY": "plain-value",
    }
    assert os.environ["AHADIFF_DEMO_KEY"] == "from-system"
    assert os.environ["AHADIFF_OTHER_KEY"] == "plain-value"


def test_repo_env_file_only_applies_provider_keys_not_config_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    env_path = tmp_path / ".ahadiff" / ".env"
    env_path.parent.mkdir()
    env_path.write_text(
        "AHADIFF_PRIVACY_MODE=explicit_remote\nAHADIFF_LANG=zh-CN\nAHADIFF_DEMO_KEY=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("AHADIFF_PRIVACY_MODE", raising=False)
    monkeypatch.delenv("AHADIFF_LANG", raising=False)
    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    apply_repo_env_file(env_path)
    snapshot = load_config(tmp_path, cli_overrides={"privacy_mode": "strict_local"})

    assert os.environ["AHADIFF_DEMO_KEY"] == "from-file"
    assert "AHADIFF_PRIVACY_MODE" not in os.environ
    assert "AHADIFF_LANG" not in os.environ
    assert snapshot.resolved["privacy_mode"].value == "strict_local"
    assert snapshot.resolved["privacy_mode"].source == "cli"


def test_repo_env_file_load_tolerates_utf8_bom_first_key(tmp_path: Path) -> None:
    env_path = tmp_path / ".ahadiff" / ".env"
    env_path.parent.mkdir()
    env_path.write_bytes(b"\xef\xbb\xbfAHADIFF_X_KEY=from-bom\nAHADIFF_OTHER_KEY=plain\n")

    assert load_repo_env_file(env_path) == {
        "AHADIFF_X_KEY": "from-bom",
        "AHADIFF_OTHER_KEY": "plain",
    }


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_missing_repo_env_file_under_symlink_parent_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_repo = tmp_path / "real-repo"
    (real_repo / ".ahadiff").mkdir(parents=True)
    link_repo = tmp_path / "link-repo"
    link_repo.symlink_to(real_repo, target_is_directory=True)
    env_path = link_repo / ".ahadiff" / ".env"
    monkeypatch.delenv("AHADIFF_LINKED_KEY", raising=False)

    assert load_repo_env_file(env_path) == {}
    apply_repo_env_file(env_path)

    assert "AHADIFF_LINKED_KEY" not in os.environ


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_repo_env_file_load_rejects_symlink_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".ahadiff" / ".env"
    env_path.parent.mkdir()
    outside_env = tmp_path / "outside.env"
    outside_env.write_text("AHADIFF_LINKED_KEY=from-outside\n", encoding="utf-8")
    env_path.symlink_to(outside_env)
    monkeypatch.delenv("AHADIFF_LINKED_KEY", raising=False)

    with pytest.raises(ConfigError, match="symlink"):
        load_repo_env_file(env_path)
    with pytest.raises(ConfigError, match="symlink"):
        apply_repo_env_file(env_path)
    assert "AHADIFF_LINKED_KEY" not in os.environ


def test_repo_env_file_load_rejects_reparse_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".ahadiff" / ".env"
    env_path.parent.mkdir()
    env_path.write_text("AHADIFF_LINKED_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setattr(
        "ahadiff.core.config._repo_env_stat_has_windows_reparse_point",
        lambda _path_stat: True,
    )

    with pytest.raises(ConfigError, match="Windows reparse point"):
        load_repo_env_file(env_path)


@pytest.mark.skipif(not hasattr(os, "link"), reason="requires hardlink support")
def test_repo_env_file_load_rejects_hardlink_leaf(tmp_path: Path) -> None:
    env_path = tmp_path / ".ahadiff" / ".env"
    env_path.parent.mkdir()
    outside_env = tmp_path / "outside.env"
    outside_env.write_text("AHADIFF_LINKED_KEY=from-outside\n", encoding="utf-8")
    try:
        os.link(outside_env, env_path)
    except OSError as exc:
        pytest.skip(f"hardlink creation failed: {exc}")

    with pytest.raises(ConfigError, match="hardlink"):
        load_repo_env_file(env_path)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlink support")
def test_repo_env_file_write_rejects_symlink_leaf(tmp_path: Path) -> None:
    env_path = tmp_path / ".ahadiff" / ".env"
    env_path.parent.mkdir()
    outside_env = tmp_path / "outside.env"
    outside_env.write_text("AHADIFF_EXTERNAL_KEY=external-secret\n", encoding="utf-8")
    env_path.symlink_to(outside_env)

    with pytest.raises(ConfigError, match="symlink"):
        write_repo_env_var(env_path, "AHADIFF_DEMO_KEY", "sk-safe-secret")

    assert outside_env.read_text(encoding="utf-8") == "AHADIFF_EXTERNAL_KEY=external-secret\n"
    assert env_path.is_symlink()


def test_provider_create_with_plain_api_key_stores_env_reference_and_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    raw_key = "sk-create-secret-1234567890"
    captured: dict[str, object] = {}

    def probe_spy(**kwargs: object) -> ProbeReport:
        captured.update(kwargs)
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=raw_key, api_key_env=None),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["provider"]["api_key_env"] == "AHADIFF_DEMO_KEY"
    assert payload["provider"]["key_status"] == "configured"
    assert payload["verification"] == {
        "ok": True,
        "error": None,
        "detail": "provider probe succeeded",
    }
    assert captured["api_key"] == raw_key
    assert captured["api_key_env"] == "AHADIFF_DEMO_KEY"
    assert captured["request_timeout_seconds"] == 5

    env_path = state_dir / ".env"
    assert env_path.read_text(encoding="utf-8") == f"AHADIFF_DEMO_KEY={raw_key}\n"
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    gitignore_text = (state_dir / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore_text.splitlines()
    assert ".env.*" in gitignore_text.splitlines()
    assert "audit.private.jsonl" in gitignore_text.splitlines()
    assert "config.toml" not in gitignore_text
    assert not (tmp_path / ".gitignore").exists()
    assert os.environ["AHADIFF_DEMO_KEY"] == raw_key
    assert load_config(tmp_path).values["providers"]["demo"]["api_key_env"] == "AHADIFF_DEMO_KEY"
    assert raw_key not in (state_dir / "config.toml").read_text(encoding="utf-8")
    assert raw_key not in json.dumps(payload, sort_keys=True)
    assert raw_key not in json.dumps(client.get("/api/providers", headers=_AUTH).json())
    assert raw_key not in json.dumps(client.get("/api/config", headers=_AUTH).json())
    assert raw_key not in json.dumps(client.get("/api/doctor", headers=_AUTH).json())
    assert raw_key not in (state_dir / "audit.jsonl").read_text(encoding="utf-8")


def test_provider_create_plain_api_key_extends_existing_state_gitignore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    existing_gitignore = "# user-owned\ncustom.log\n"
    (state_dir / ".gitignore").write_text(existing_gitignore, encoding="utf-8")
    client = _client(state_dir)

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key="sk-existing-ignore-secret-1234567890", api_key_env=None),
    )

    assert response.status_code == 201
    gitignore_text = (state_dir / ".gitignore").read_text(encoding="utf-8")
    assert gitignore_text.startswith(existing_gitignore)
    assert gitignore_text.count("custom.log") == 1
    for pattern in (".env", ".env.*", "audit.private.jsonl", "*.lock", "*.log"):
        assert pattern in gitignore_text.splitlines()
    check_ignore = subprocess.run(
        ["git", "-C", str(tmp_path), "check-ignore", ".ahadiff/.env"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert check_ignore.returncode == 0, check_ignore.stderr


def test_provider_create_plain_api_key_avoids_system_and_repo_env_collisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / ".env").write_text(
        "AHADIFF_DEMO_2_KEY=from-repo-env\n",
        encoding="utf-8",
    )
    client = _client(state_dir)
    raw_key = "sk-created-with-unique-env-1234567890"
    monkeypatch.setenv("AHADIFF_DEMO_KEY", "from-system-env")
    monkeypatch.delenv("AHADIFF_DEMO_2_KEY", raising=False)
    monkeypatch.delenv("AHADIFF_DEMO_3_KEY", raising=False)

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=raw_key, api_key_env=None),
    )

    assert response.status_code == 201
    assert response.json()["provider"]["api_key_env"] == "AHADIFF_DEMO_3_KEY"
    assert os.environ["AHADIFF_DEMO_KEY"] == "from-system-env"
    assert "AHADIFF_DEMO_2_KEY" not in os.environ
    assert os.environ["AHADIFF_DEMO_3_KEY"] == raw_key
    assert load_repo_env_file(state_dir / ".env") == {
        "AHADIFF_DEMO_2_KEY": "from-repo-env",
        "AHADIFF_DEMO_3_KEY": raw_key,
    }
    assert load_config(tmp_path).values["providers"]["demo"]["api_key_env"] == (
        "AHADIFF_DEMO_3_KEY"
    )


def test_provider_create_plain_api_key_keeps_alias_collision_env_names_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)
    monkeypatch.delenv("AHADIFF_FOO_BAR_KEY", raising=False)
    monkeypatch.delenv("AHADIFF_FOO_BAR_2_KEY", raising=False)

    first = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(
            alias="foo-bar",
            api_key="sk-first-secret-1234567890",
            api_key_env=None,
        ),
    )
    second = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(
            alias="foo_bar",
            api_key="sk-second-secret-1234567890",
            api_key_env=None,
        ),
    )

    assert first.status_code == 201
    assert second.status_code == 201
    providers = load_config(tmp_path).values["providers"]
    assert providers["foo-bar"]["api_key_env"] == "AHADIFF_FOO_BAR_KEY"
    assert providers["foo_bar"]["api_key_env"] == "AHADIFF_FOO_BAR_2_KEY"
    assert load_repo_env_file(state_dir / ".env") == {
        "AHADIFF_FOO_BAR_KEY": "sk-first-secret-1234567890",
        "AHADIFF_FOO_BAR_2_KEY": "sk-second-secret-1234567890",
    }
    assert os.environ["AHADIFF_FOO_BAR_KEY"] == "sk-first-secret-1234567890"
    assert os.environ["AHADIFF_FOO_BAR_2_KEY"] == "sk-second-secret-1234567890"


def test_provider_create_plain_api_key_rolls_back_env_when_config_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    raw_key = "sk-create-rollback-secret-1234567890"

    def fail_write_config_data(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated config write failure")

    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "write_config_data", fail_write_config_data)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=raw_key, api_key_env=None),
    )

    assert response.status_code == 500
    assert load_repo_env_file(state_dir / ".env") == {}
    assert "AHADIFF_DEMO_KEY" not in (state_dir / ".env").read_text(encoding="utf-8")
    assert "AHADIFF_DEMO_KEY" not in os.environ
    assert not (state_dir / "config.toml").exists()


def test_provider_create_plain_api_key_rolls_back_env_when_audit_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    raw_key = "sk-create-audit-rollback-secret-1234567890"

    def fail_audit_write(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated audit write failure")

    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "_append_provider_audit_event", fail_audit_write)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=raw_key, api_key_env=None),
    )

    assert response.status_code == 500
    assert load_repo_env_file(state_dir / ".env") == {}
    assert "AHADIFF_DEMO_KEY" not in (state_dir / ".env").read_text(encoding="utf-8")
    assert "AHADIFF_DEMO_KEY" not in os.environ


def test_provider_create_plain_api_key_rolls_back_config_when_audit_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    raw_key = "sk-create-audit-config-rollback-secret-1234567890"

    def fail_audit_write(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated audit write failure")

    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "_append_provider_audit_event", fail_audit_write)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=raw_key, api_key_env=None),
    )

    assert response.status_code == 500
    assert "demo" not in load_config(tmp_path).values.get("providers", {})
    assert load_repo_env_file(state_dir / ".env") == {}
    assert "AHADIFF_DEMO_KEY" not in os.environ


def test_provider_create_unexpected_persist_failure_returns_envelope_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    raw_key = "sk-create-runtime-rollback-secret-1234567890"

    def fail_audit_write(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated unexpected audit failure")

    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "_append_provider_audit_event", fail_audit_write)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=raw_key, api_key_env=None),
    )

    assert response.status_code == 500
    assert response.json() == {
        "error_code": ErrorCode.INTERNAL_ERROR.value,
        "error": "provider_persist_failed",
        "status": 500,
    }
    assert "demo" not in load_config(tmp_path).values.get("providers", {})
    assert load_repo_env_file(state_dir / ".env") == {}
    assert "AHADIFF_DEMO_KEY" not in os.environ


def test_provider_create_invalid_security_rolls_back_before_secret_persist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        '[security]\nlocal_hosts = "bad"\n',
        encoding="utf-8",
    )
    client = _client(state_dir)
    raw_key = "sk-create-invalid-security-secret-1234567890"
    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=raw_key, api_key_env=None),
    )

    assert response.status_code == 500
    assert response.json() == {
        "error_code": ErrorCode.INTERNAL_ERROR.value,
        "error": "security.local_hosts must be an array of strings",
        "status": 500,
    }
    assert load_repo_env_file(state_dir / ".env") == {}
    config_text = (state_dir / "config.toml").read_text(encoding="utf-8")
    assert "[providers.demo]" not in config_text
    assert raw_key not in config_text
    assert "AHADIFF_DEMO_KEY" not in os.environ


def test_provider_create_plain_api_key_restores_config_when_env_rollback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    raw_key = "sk-create-rollback-exception-secret-1234567890"

    def fail_audit_write(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated audit write failure")

    def fail_env_rollback(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated env rollback failure")

    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "_append_provider_audit_event", fail_audit_write)
    monkeypatch.setattr(
        routes_provider_module,
        "_rollback_saved_repo_env_value",
        fail_env_rollback,
    )

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=raw_key, api_key_env=None),
    )

    assert response.status_code == 500
    assert response.json()["error"] == "simulated audit write failure"
    assert "demo" not in load_config(tmp_path).values.get("providers", {})


def test_provider_update_plain_api_key_mask_round_trip_and_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    calls: list[str | None] = []

    def probe_spy(**kwargs: object) -> ProbeReport:
        calls.append(kwargs["api_key"] if isinstance(kwargs["api_key"], str) else None)
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)
    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)

    created = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key="sk-old-secret-1234567890", api_key_env=None),
    )
    empty_round_trip = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"api_key": ""},
    )
    masked_round_trip = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"api_key": "********"},
    )
    overwritten = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"api_key": "sk-new-secret-1234567890"},
    )

    assert created.status_code == 201
    assert empty_round_trip.status_code == 200
    assert empty_round_trip.json()["verification"] is None
    assert masked_round_trip.status_code == 200
    assert masked_round_trip.json()["verification"] is None
    assert overwritten.status_code == 200
    assert overwritten.json()["verification"]["ok"] is True
    assert calls == ["sk-old-secret-1234567890", "sk-new-secret-1234567890"]
    assert (state_dir / ".env").read_text(encoding="utf-8") == (
        "AHADIFF_DEMO_KEY=sk-new-secret-1234567890\n"
    )


def test_provider_update_plain_api_key_rolls_back_env_when_config_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    old_key = "sk-update-old-secret-1234567890"
    new_key = "sk-update-new-secret-1234567890"

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)
    created = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=old_key, api_key_env=None),
    )
    assert created.status_code == 201

    def fail_write_config_data(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated config write failure")

    monkeypatch.setattr(routes_provider_module, "write_config_data", fail_write_config_data)
    response = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"api_key": new_key},
    )

    assert response.status_code == 500
    assert load_repo_env_file(state_dir / ".env") == {"AHADIFF_DEMO_KEY": old_key}
    assert (state_dir / ".env").read_text(encoding="utf-8") == f"AHADIFF_DEMO_KEY={old_key}\n"
    assert os.environ["AHADIFF_DEMO_KEY"] == old_key


def test_provider_update_plain_api_key_rolls_back_env_when_audit_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    old_key = "sk-update-audit-old-secret-1234567890"
    new_key = "sk-update-audit-new-secret-1234567890"

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)
    created = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=old_key, api_key_env=None),
    )
    assert created.status_code == 201

    def fail_audit_write(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated audit write failure")

    monkeypatch.setattr(routes_provider_module, "_append_provider_audit_event", fail_audit_write)
    response = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"api_key": new_key},
    )

    assert response.status_code == 500
    assert load_repo_env_file(state_dir / ".env") == {"AHADIFF_DEMO_KEY": old_key}
    assert (state_dir / ".env").read_text(encoding="utf-8") == f"AHADIFF_DEMO_KEY={old_key}\n"
    assert os.environ["AHADIFF_DEMO_KEY"] == old_key


def test_provider_update_plain_api_key_rolls_back_config_when_audit_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    old_key = "sk-update-audit-config-old-secret-1234567890"
    new_key = "sk-update-audit-config-new-secret-1234567890"

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)
    created = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=old_key, api_key_env=None),
    )
    assert created.status_code == 201

    def fail_audit_write(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated audit write failure")

    monkeypatch.setattr(routes_provider_module, "_append_provider_audit_event", fail_audit_write)
    response = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"api_key": new_key, "model_name": "gpt-5.4-updated"},
    )

    provider = load_config(tmp_path).values["providers"]["demo"]
    assert response.status_code == 500
    assert provider["model_name"] == "gpt-5.4-mini"
    assert provider["api_key_env"] == "AHADIFF_DEMO_KEY"
    assert load_repo_env_file(state_dir / ".env") == {"AHADIFF_DEMO_KEY": old_key}
    assert os.environ["AHADIFF_DEMO_KEY"] == old_key


def test_provider_update_plain_api_key_restores_config_when_env_rollback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    old_key = "sk-update-rollback-exception-old-secret-1234567890"
    new_key = "sk-update-rollback-exception-new-secret-1234567890"

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)
    created = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=old_key, api_key_env=None),
    )
    assert created.status_code == 201

    def fail_audit_write(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated audit write failure")

    def fail_env_rollback(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated env rollback failure")

    monkeypatch.setattr(routes_provider_module, "_append_provider_audit_event", fail_audit_write)
    monkeypatch.setattr(
        routes_provider_module,
        "_rollback_saved_repo_env_value",
        fail_env_rollback,
    )
    response = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"api_key": new_key, "model_name": "gpt-5.4-updated"},
    )

    provider = load_config(tmp_path).values["providers"]["demo"]
    assert response.status_code == 500
    assert response.json()["error"] == "simulated audit write failure"
    assert provider["model_name"] == "gpt-5.4-mini"
    assert provider["api_key_env"] == "AHADIFF_DEMO_KEY"


def test_provider_update_plain_api_key_replaces_legacy_env_name_with_ahadiff_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.demo]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "OPENAI_API_KEY"\n',
        encoding="utf-8",
    )
    write_repo_env_var(state_dir / ".env", "OPENAI_API_KEY", "sk-old-legacy-secret-1234567890")
    client = _client(state_dir)
    raw_key = "sk-legacy-update-secret-1234567890"

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)

    updated = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"api_key": raw_key},
    )

    assert updated.status_code == 200
    assert updated.json()["provider"]["api_key_env"] == "AHADIFF_DEMO_KEY"
    assert load_config(tmp_path).values["providers"]["demo"]["api_key_env"] == ("AHADIFF_DEMO_KEY")
    assert load_repo_env_file(state_dir / ".env") == {"AHADIFF_DEMO_KEY": raw_key}
    assert "OPENAI_API_KEY" not in (state_dir / ".env").read_text(encoding="utf-8")


def test_provider_update_plain_api_key_keeps_shared_legacy_env_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.demo]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "OPENAI_API_KEY"\n'
        "\n"
        "[providers.shared]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.shared.example.test/v1"\n'
        'api_key_env = "OPENAI_API_KEY"\n',
        encoding="utf-8",
    )
    write_repo_env_var(state_dir / ".env", "OPENAI_API_KEY", "sk-shared-legacy-secret-1234567890")
    client = _client(state_dir)
    raw_key = "sk-shared-update-secret-1234567890"

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)

    updated = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"api_key": raw_key},
    )

    providers = load_config(tmp_path).values["providers"]
    assert updated.status_code == 200
    assert providers["demo"]["api_key_env"] == "AHADIFF_DEMO_KEY"
    assert providers["shared"]["api_key_env"] == "OPENAI_API_KEY"
    assert load_repo_env_file(state_dir / ".env") == {
        "OPENAI_API_KEY": "sk-shared-legacy-secret-1234567890",
        "AHADIFF_DEMO_KEY": raw_key,
    }


def test_provider_create_verification_failure_does_not_block_or_leak_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    raw_key = "sk-failed-secret-1234567890"

    def fail_probe(**_kwargs: object) -> ProbeReport:
        raise ProviderError(f"transport failed for {raw_key}")

    monkeypatch.setattr(routes_provider_module, "probe_provider", fail_probe)
    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=raw_key, api_key_env=None),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["verification"] == {
        "ok": False,
        "error": "provider_probe_failed",
        "detail": "ProviderError",
    }
    assert raw_key not in json.dumps(payload, sort_keys=True)
    assert raw_key not in (state_dir / "config.toml").read_text(encoding="utf-8")
    assert (state_dir / ".env").read_text(encoding="utf-8") == f"AHADIFF_DEMO_KEY={raw_key}\n"


def test_provider_plain_api_key_rejects_newlines_before_env_write(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    created = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key="sk-line\nbreak", api_key_env=None),
    )

    assert created.status_code == 422
    assert "api_key" in created.json()["error"]
    assert not (state_dir / ".env").exists()
    assert not (state_dir / "config.toml").exists()


def test_provider_plain_api_key_rejects_nul_before_env_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)

    created = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key="sk-before\x00after", api_key_env=None),
    )

    assert created.status_code == 422
    assert "api_key" in created.json()["error"]
    assert not (state_dir / ".env").exists()
    assert not (state_dir / "config.toml").exists()
    assert "AHADIFF_DEMO_KEY" not in os.environ


def test_legacy_api_key_env_uses_system_env_over_repo_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".ahadiff" / ".env"
    write_repo_env_var(env_path, "OPENAI_API_KEY", "from-file")
    monkeypatch.setenv("OPENAI_API_KEY", "from-system")

    apply_repo_env_file(env_path)

    assert resolve_provider_api_key("OPENAI_API_KEY") == "from-system"


def test_iter_resolved_settings_masks_legacy_literal_provider_api_key_env(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.legacy]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "sk-legacy-secret-1234567890"\n',
        encoding="utf-8",
    )

    settings = {
        setting.key: setting.value for setting in iter_resolved_settings(load_config(tmp_path))
    }

    assert settings["providers.legacy.api_key_env"] == "********"
    assert "sk-legacy-secret-1234567890" not in repr(settings)


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
    assert response.json() == {
        "error": "invalid_alias",
        "error_code": "INPUT_BAD_FIELD",
        "status": 400,
    }
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
    assert response.json() == {
        "error": "invalid_alias",
        "error_code": "INPUT_BAD_FIELD",
        "status": 400,
    }
    assert not (state_dir / "config.toml").exists()


def test_provider_create_rejects_unsafe_api_key_env_before_registry_mutation(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key_env="AWS_SECRET_ACCESS_KEY"),
    )

    assert response.status_code == 422
    assert "api_key_env" in response.json()["error"]
    assert not (state_dir / "config.toml").exists()


def test_get_providers_tolerates_corrupt_providers_table(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text('providers = "not-a-table"\n', encoding="utf-8")
    client = _client(state_dir)

    response = client.get("/api/providers", headers=_AUTH)

    assert response.status_code == 200
    assert response.json() == {"providers": []}


def test_provider_create_rejects_corrupt_providers_table_without_mutation(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    config_path = state_dir / "config.toml"
    original = 'providers = "not-a-table"\n'
    config_path.write_text(original, encoding="utf-8")
    client = _client(state_dir)

    response = client.post("/api/providers", headers=_AUTH, json=_provider_payload())

    assert response.status_code == 500
    error = str(response.json()["error"])
    assert "providers" in error
    assert "table" in error
    assert config_path.read_text(encoding="utf-8") == original


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


def test_provider_update_rejects_unsafe_api_key_env_before_mutation(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    created = client.post("/api/providers", headers=_AUTH, json=_provider_payload())
    assert created.status_code == 201

    response = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"api_key_env": "GITHUB_TOKEN"},
    )

    assert response.status_code == 422
    assert "api_key_env" in response.json()["error"]
    providers = (state_dir / "config.toml").read_text(encoding="utf-8")
    assert "GITHUB_TOKEN" not in providers
    assert "AHADIFF_PROVIDER_API_KEY" in providers


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


def test_provider_delete_removes_unshared_ahadiff_owned_repo_env_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)
    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    write_repo_env_var(state_dir / ".env", "AHADIFF_OTHER_KEY", "keep-this-value")

    created = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key="sk-delete-secret-1234567890", api_key_env=None),
    )
    deleted = client.delete("/api/providers/demo", headers=_AUTH)

    assert created.status_code == 201
    assert deleted.status_code == 200
    assert load_repo_env_file(state_dir / ".env") == {"AHADIFF_OTHER_KEY": "keep-this-value"}
    assert "AHADIFF_DEMO_KEY" not in (state_dir / ".env").read_text(encoding="utf-8")
    assert "AHADIFF_DEMO_KEY" not in os.environ


def test_provider_delete_does_not_clobber_user_exported_matching_env_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.demo]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AHADIFF_DEMO_KEY"\n',
        encoding="utf-8",
    )
    write_repo_env_var(state_dir / ".env", "AHADIFF_DEMO_KEY", "repo-owned-secret")
    monkeypatch.setenv("AHADIFF_DEMO_KEY", "user-exported-secret")
    client = _client(state_dir)

    deleted = client.delete("/api/providers/demo", headers=_AUTH)

    assert deleted.status_code == 200
    assert load_repo_env_file(state_dir / ".env") == {}
    assert os.environ["AHADIFF_DEMO_KEY"] == "user-exported-secret"


def test_provider_delete_restores_config_and_env_when_config_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    raw_key = "sk-delete-config-rollback-secret-1234567890"

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)
    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    created = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=raw_key, api_key_env=None),
    )
    assert created.status_code == 201

    def fail_write_config_data(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated config write failure")

    monkeypatch.setattr(routes_provider_module, "write_config_data", fail_write_config_data)
    deleted = client.delete("/api/providers/demo", headers=_AUTH)

    assert deleted.status_code == 500
    assert load_config(tmp_path).values["providers"]["demo"]["api_key_env"] == ("AHADIFF_DEMO_KEY")
    assert load_repo_env_file(state_dir / ".env") == {"AHADIFF_DEMO_KEY": raw_key}


def test_provider_delete_restores_config_and_env_when_audit_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    raw_key = "sk-delete-audit-rollback-secret-1234567890"

    def probe_spy(**kwargs: object) -> ProbeReport:
        return _successful_probe_report(
            provider_name=str(kwargs["provider_name"]),
            provider_class=str(kwargs["provider_class"]),
            model_name=str(kwargs["model_name"]),
            model_limits_name=kwargs["model_limits_name"]
            if isinstance(kwargs["model_limits_name"], str)
            else None,
            base_url=str(kwargs["base_url"]),
            api_key_env=str(kwargs["api_key_env"]),
        )

    monkeypatch.setattr(routes_provider_module, "probe_provider", probe_spy)
    monkeypatch.delenv("AHADIFF_DEMO_KEY", raising=False)
    created = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(api_key=raw_key, api_key_env=None),
    )
    assert created.status_code == 201

    def fail_audit_write(*_args: object, **_kwargs: object) -> None:
        raise ConfigError("simulated audit write failure")

    monkeypatch.setattr(routes_provider_module, "_append_provider_audit_event", fail_audit_write)
    deleted = client.delete("/api/providers/demo", headers=_AUTH)

    assert deleted.status_code == 500
    assert deleted.json()["error"] == "simulated audit write failure"
    assert load_config(tmp_path).values["providers"]["demo"]["api_key_env"] == ("AHADIFF_DEMO_KEY")
    assert load_repo_env_file(state_dir / ".env") == {"AHADIFF_DEMO_KEY": raw_key}


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


def test_fetch_provider_models_rejects_unsafe_repo_api_key_env_without_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.evil]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AWS_SECRET_ACCESS_KEY"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret-that-should-not-be-provider-key")
    monkeypatch.setattr(
        routes_provider_module.provider_module,
        "validate_remote_url",
        lambda _url: None,
    )
    captured = _install_async_client_stub(monkeypatch, _models_response)
    client = _client(state_dir)

    response = client.get("/api/providers/evil/models", headers=_AUTH)

    assert response.status_code == 422
    assert "api_key_env" in response.json()["error"]
    assert captured["requests"] == []


def test_probe_provider_rejects_unsafe_repo_api_key_env_before_task_submit(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.evil]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AWS_SECRET_ACCESS_KEY"\n',
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.post("/api/providers/evil/probe", headers=_AUTH, json={})

    assert response.status_code == 422
    assert "api_key_env" in response.json()["error"]


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


def test_get_provider_model_limits_returns_registry_metadata(tmp_path: Path) -> None:
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

    response = client.get("/api/providers/demo/model-limits", headers=_AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["alias"] == "demo"
    assert payload["provider_class"] == "openai"
    assert payload["model_name"] == "gpt-5.4-mini"
    assert payload["max_output_tokens"] == 128000
    assert payload["max_output_known"] is True
    assert payload["context_policy"] == "shared_pool"
    assert payload["confidence"] == "high"
    assert payload["thinking"]["supported"] is False
    assert "hint_key" not in payload["thinking"]


def test_get_provider_model_limits_returns_404_for_unknown_alias(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/providers/missing/model-limits", headers=_AUTH)

    assert response.status_code == 404
    assert response.json() == {
        "error": "provider_not_found",
        "error_code": "PROVIDER_NOT_FOUND",
        "status": 404,
    }


def test_model_limits_preview_reports_local_runtime_as_unknown_limits(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/providers/model-limits/preview",
        headers=_AUTH,
        json={"provider_class": "ollama", "model_name": "llama3"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["context_policy"] == "local_runtime"
    assert payload["max_context_tokens"] is None
    assert payload["max_input_tokens"] is None
    assert payload["max_output_tokens"] is None
    assert payload["max_context_known"] is False
    assert payload["max_input_known"] is False
    assert payload["max_output_known"] is False
    assert {warning["code"] for warning in payload["warnings"]} >= {
        "provider_limits.local_runtime",
        "provider_limits.default_fallback",
    }


def test_model_limits_preview_reports_split_envelope_and_thinking_support(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    gemini = client.post(
        "/api/providers/model-limits/preview",
        headers=_AUTH,
        json={"provider_class": "gemini", "model_name": "gemini-2.5-pro"},
    )
    anthropic = client.post(
        "/api/providers/model-limits/preview",
        headers=_AUTH,
        json={"provider_class": "anthropic", "model_name": "claude-sonnet-4-6"},
    )

    assert gemini.status_code == 200
    gemini_payload = gemini.json()
    assert gemini_payload["context_policy"] == "split_envelope"
    assert gemini_payload["max_input_tokens"] == 1048576
    assert gemini_payload["max_output_tokens"] == 65536
    assert gemini_payload["thinking"]["supported"] is True
    assert "hint_key" not in gemini_payload["thinking"]
    assert anthropic.status_code == 200
    assert anthropic.json()["thinking"]["supported"] is True


def test_model_limits_preview_warns_for_route_specific_and_low_confidence(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    route_specific = client.post(
        "/api/providers/model-limits/preview",
        headers=_AUTH,
        json={
            "provider_class": "newapi",
            "model_name": "served-model",
            "model_limits_name": "openrouter/qwen/qwen3.5-122b-a10b",
        },
    )
    low_confidence = client.post(
        "/api/providers/model-limits/preview",
        headers=_AUTH,
        json={
            "provider_class": "newapi",
            "model_name": "served-model",
            "model_limits_name": "openrouter/qwen/qwen3.5-35b-a3b",
        },
    )

    assert route_specific.status_code == 200
    assert {warning["code"] for warning in route_specific.json()["warnings"]} >= {
        "provider_limits.route_specific"
    }
    assert low_confidence.status_code == 200
    assert {warning["code"] for warning in low_confidence.json()["warnings"]} >= {
        "provider_limits.low_confidence"
    }


def test_provider_create_clamps_max_output_tokens_to_known_hard_limit(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(max_output_tokens=999999),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["provider"]["max_output_tokens"] == 128000
    assert payload["warnings"] == [
        {
            "code": "provider_limits.max_output_clamped",
            "params": {
                "requested": 999999,
                "clamped_to": 128000,
                "source": "registry",
                "max_output_known": True,
            },
        }
    ]
    snapshot = load_config(tmp_path)
    assert snapshot.values["providers"]["demo"]["max_output_tokens"] == 128000


def test_provider_update_clamps_and_null_clears_max_output_tokens(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    created = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(max_output_tokens=1000),
    )
    assert created.status_code == 201

    clamped = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"max_output_tokens": 999999},
    )
    cleared = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"max_output_tokens": None},
    )

    assert clamped.status_code == 200
    assert clamped.json()["provider"]["max_output_tokens"] == 128000
    assert clamped.json()["warnings"][0]["code"] == "provider_limits.max_output_clamped"
    assert cleared.status_code == 200
    assert cleared.json()["provider"]["max_output_tokens"] is None
    assert "max_output_tokens" not in load_config(tmp_path).values["providers"]["demo"]


@pytest.mark.parametrize("bad_value", (True, "123", 123.0))
def test_provider_create_rejects_non_strict_max_output_tokens(
    tmp_path: Path,
    bad_value: object,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(max_output_tokens=bad_value),
    )

    assert response.status_code == 422
    assert not (state_dir / "config.toml").exists()


@pytest.mark.parametrize("bad_value", (True, "123", 123.0))
def test_provider_update_rejects_non_strict_max_output_tokens(
    tmp_path: Path,
    bad_value: object,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)
    created = client.post("/api/providers", headers=_AUTH, json=_provider_payload())
    assert created.status_code == 201

    response = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"max_output_tokens": bad_value},
    )

    assert response.status_code == 422
    assert "max_output_tokens" not in load_config(tmp_path).values["providers"]["demo"]


def test_provider_update_clears_probe_fields_when_model_limits_name_changes(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.demo]\n"
        'provider_class = "openai"\n'
        'model_name = "served-model"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n'
        "probed_max_context = 300000\n"
        "probed_max_input_tokens = 300000\n"
        "probed_max_output_tokens = 300000\n"
        'probed_limits_source = "live"\n'
        "probed_tpm = 1000\n"
        "probed_rpm = 20\n"
        'probe_timestamp = "2026-05-23T00:00:00Z"\n',
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"model_limits_name": "openai/gpt-4o", "max_output_tokens": 200000},
    )

    assert response.status_code == 200
    payload = response.json()
    provider = payload["provider"]
    assert provider["model_limits_name"] == "openai/gpt-4o"
    assert provider["max_output_tokens"] == 16384
    assert payload["warnings"][0]["code"] == "provider_limits.max_output_clamped"
    persisted = load_config(tmp_path).values["providers"]["demo"]
    for field_name in (
        "probed_max_context",
        "probed_max_input_tokens",
        "probed_max_output_tokens",
        "probed_limits_source",
        "probed_tpm",
        "probed_rpm",
        "probe_timestamp",
    ):
        assert provider.get(field_name) is None
        assert field_name not in persisted


def test_provider_update_clears_probe_fields_when_model_limits_name_is_cleared(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.demo]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-4o"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n'
        'model_limits_name = "openai/gpt-5"\n'
        "probed_max_context = 300000\n"
        "probed_max_input_tokens = 300000\n"
        "probed_max_output_tokens = 300000\n"
        'probed_limits_source = "live"\n'
        'probe_timestamp = "2026-05-23T00:00:00Z"\n',
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.put(
        "/api/providers/demo",
        headers=_AUTH,
        json={"model_limits_name": None},
    )

    assert response.status_code == 200
    provider = response.json()["provider"]
    persisted = load_config(tmp_path).values["providers"]["demo"]
    assert provider["model_limits_name"] is None
    assert "model_limits_name" not in persisted
    for field_name in (
        "probed_max_context",
        "probed_max_input_tokens",
        "probed_max_output_tokens",
        "probed_limits_source",
        "probe_timestamp",
    ):
        assert provider.get(field_name) is None
        assert field_name not in persisted


def test_provider_create_keeps_valid_max_output_tokens_without_warning(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(max_output_tokens=1000),
    )

    assert response.status_code == 201
    assert response.json()["provider"]["max_output_tokens"] == 1000
    assert response.json()["warnings"] == []


def test_provider_create_warns_but_does_not_clamp_unverified_override(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.post(
        "/api/providers",
        headers=_AUTH,
        json=_provider_payload(
            provider_class="newapi",
            model_name="served-model",
            model_limits_name="openrouter/qwen/qwen3.5-35b-a3b",
            max_output_tokens=999999,
        ),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["provider"]["max_output_tokens"] == 999999
    assert payload["warnings"][0]["code"] == "provider_limits.unverified_override"


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
