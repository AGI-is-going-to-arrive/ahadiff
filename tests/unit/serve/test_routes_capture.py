from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from starlette.testclient import TestClient

from ahadiff.core.errors import StorageError
from ahadiff.serve import ServeState, create_app, routes_capture

if TYPE_CHECKING:
    from pathlib import Path


def _client(state_dir: Path) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token="test-token", locale="en"))
    return TestClient(app, base_url="http://localhost:8765")


def test_capture_recommended_returns_404_without_configured_provider(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/capture/recommended")

    assert response.status_code == 404
    payload = cast("dict[str, Any]", response.json())
    assert payload["error"] == "capture_recommendation_requires_configured_provider"
    assert "details" not in payload


def test_capture_recommended_returns_422_for_ambiguous_configured_providers(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    state_dir = repo / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        """
[providers.local_a]
provider_class = "ollama"
model_name = "local-a"
base_url = "http://127.0.0.1:11434"
api_key_env = ""

[providers.local_b]
provider_class = "ollama"
model_name = "local-b"
base_url = "http://127.0.0.1:11435"
api_key_env = ""
""",
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.get("/api/capture/recommended")

    assert response.status_code == 422
    payload = cast("dict[str, Any]", response.json())
    assert payload["error_code"] == "INPUT_VALIDATION"
    assert payload["error"] == "capture_recommendation_requires_generate_provider"
    assert "details" not in payload
    assert "requires --provider" not in response.text
    assert str(state_dir) not in response.text


def test_capture_recommended_maps_typed_errors_without_path_leak(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)
    private_path = tmp_path / "private" / "config.toml"

    def fail_recommendation(state: Any) -> dict[str, Any]:
        raise StorageError(f"failed to read {private_path}")

    monkeypatch.setattr(routes_capture, "_recommended_capture_payload", fail_recommendation)

    response = client.get("/api/capture/recommended")

    assert response.status_code == 500
    payload = cast("dict[str, Any]", response.json())
    assert payload["error_code"] == "STORAGE_FS"
    assert payload["error"] == "capture_recommendation_failed"
    assert str(private_path) not in response.text


def test_capture_recommended_returns_budget_from_configured_provider(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    state_dir = repo / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        """
[providers.local]
provider_class = "ollama"
model_name = "local-model"
base_url = "http://127.0.0.1:11434"
api_key_env = ""
probed_max_context = 32768
probed_max_input_tokens = 28672
probed_max_output_tokens = 4096
probed_limits_source = "live"
""",
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.get("/api/capture/recommended")

    assert response.status_code == 200
    payload = cast("dict[str, Any]", response.json())
    assert payload["mode"] == "auto"
    assert payload["model_name"] == "local-model"
    assert payload["context_window"] == 32768
    assert payload["max_output_tokens"] == 4096
    assert payload["runtime_max_patch_bytes"] == 50 * 1024 * 1024
    assert payload["hard_limit"] >= 100
