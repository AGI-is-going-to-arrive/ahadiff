from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from starlette.testclient import TestClient

from ahadiff.contracts import ProviderCapabilities, ProviderConfig
from ahadiff.contracts.serve_providers import ProviderProbeSubmitResponse
from ahadiff.core.config import read_config_data
from ahadiff.core.task_runner import TaskRunner, TaskStatus
from ahadiff.llm.schemas import ProbeReport
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


_AUTH = {"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"}


def _write_provider_config(
    state_dir: Path,
    *,
    alias: str = "demo",
    model_limits_name: str | None = None,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    model_limits_line = (
        f'model_limits_name = "{model_limits_name}"\n' if model_limits_name is not None else ""
    )
    (state_dir / "config.toml").write_text(
        f"[providers.{alias}]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        f"{model_limits_line}"
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n',
        encoding="utf-8",
    )


def _client(state_dir: Path, *, runner: TaskRunner | None = None) -> TestClient:
    state = ServeState(
        state_dir=state_dir,
        token="test-token",
        task_runner=runner,
    )
    return TestClient(create_app(state), base_url="http://localhost:8765")


def _json_object(response: Any) -> dict[str, object]:
    payload = response.json()
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _wait_for_task(runner: TaskRunner, task_id: str, expected_status: TaskStatus) -> object:
    deadline = time.monotonic() + 2.0
    last_status: TaskStatus | None = None
    while time.monotonic() < deadline:
        info = runner.get_task(task_id)
        assert info is not None
        last_status = info.status
        if info.status == expected_status:
            return info.result
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not reach {expected_status}; last={last_status}")


def test_probe_provider_route_submits_task_and_persists_probe_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ahadiff.serve.routes_providers as routes_providers

    state_dir = tmp_path / ".ahadiff"
    _write_provider_config(state_dir, model_limits_name="openai/gpt-5.4-mini")
    runner = TaskRunner()
    captured: dict[str, object] = {}

    def fake_probe_provider(**kwargs: object) -> ProbeReport:
        captured.update(kwargs)
        return ProbeReport(
            provider_name=str(kwargs["provider_name"]),
            config=ProviderConfig(
                provider_class="openai",
                model_name="gpt-5.4-mini",
                model_limits_name=cast("str", kwargs.get("model_limits_name")),
                base_url="https://api.example.test/v1",
                api_key_env="AHADIFF_PROVIDER_API_KEY",
                probed_max_context=12345,
                probed_tpm=678,
                probed_rpm=9,
                probe_timestamp="2026-05-04T00:00:00Z",
            ),
            capabilities=ProviderCapabilities(
                supports_stream=True,
                supports_json_mode=True,
                supports_tool_use=False,
                supports_temperature=True,
                supports_rate_limit_headers=True,
                supports_context_probe=True,
                tokenizer_estimation="probe_cached",
                api_family="openai",
                api_family_version="v1",
                provider_kind="remote",
            ),
            connectivity_ok=True,
            transport_target="remote",
            notes=("ok",),
        )

    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "placeholder-token")
    monkeypatch.setattr(routes_providers, "probe_provider", fake_probe_provider)
    with _client(state_dir, runner=runner) as client:
        response = client.post("/api/providers/demo/probe", headers=_AUTH)
        assert response.status_code == 202
        submit = ProviderProbeSubmitResponse.model_validate(_json_object(response))
        result = _wait_for_task(runner, submit.task_id, TaskStatus.COMPLETED)

    assert isinstance(result, dict)
    assert result["alias"] == "demo"
    assert result["connectivity_ok"] is True
    assert result["stale"] is False
    assert captured["api_key"] == "placeholder-token"
    assert captured["persist_result"] is False
    assert captured["model_limits_name"] == "openai/gpt-5.4-mini"
    assert cast("dict[str, object]", result["config"])["model_limits_name"] == (
        "openai/gpt-5.4-mini"
    )

    config = read_config_data(state_dir / "config.toml")
    provider = cast("dict[str, object]", cast("dict[str, object]", config["providers"])["demo"])
    assert provider["probed_max_context"] == 12345
    assert provider["model_limits_name"] == "openai/gpt-5.4-mini"


def test_probe_provider_route_alias_not_found_returns_404(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.post("/api/providers/missing/probe", headers=_AUTH)

    assert response.status_code == 404
    assert _json_object(response)["error"] == "provider_not_found"


def test_probe_provider_route_task_runner_unavailable_returns_503(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    _write_provider_config(state_dir)
    app = create_app(ServeState(state_dir=state_dir, token="test-token"))
    app.state.ahadiff = ServeState(state_dir=state_dir, token="test-token", task_runner=None)
    client = TestClient(app, base_url="http://localhost:8765")

    response = client.post("/api/providers/demo/probe", headers=_AUTH)

    assert response.status_code == 503
    assert _json_object(response)["error"] == "task_runner_unavailable"


def test_probe_provider_route_capacity_rejection_returns_503(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ahadiff.serve.routes_providers as routes_providers

    state_dir = tmp_path / ".ahadiff"
    _write_provider_config(state_dir)
    monkeypatch.setattr(routes_providers, "_MAX_PENDING_PROVIDER_PROBE_TASKS", 0)
    client = _client(state_dir)

    response = client.post("/api/providers/demo/probe", headers=_AUTH)

    assert response.status_code == 503
    assert _json_object(response)["error"] == "too_many_pending_provider_probe_tasks"
