from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from starlette.testclient import TestClient

from ahadiff.contracts.serve_app import LearnEstimateResponse
from ahadiff.core.orchestrator import LearnRequest, run_learn_pipeline
from ahadiff.serve import ServeState, create_app, routes_learn

if TYPE_CHECKING:
    import pytest


_AUTH_HEADERS = {
    "X-AhaDiff-Token": "test-token",
    "origin": "http://localhost:8765",
}
_PATCH_TEXT = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-print("old")
+print("new")
"""
_AUTO_128K_EXPECTED = {
    "context_window": 128_000,
    "max_input_tokens": 128_000,
    "max_output_tokens": 50_000,
    "diff_token_budget": 53_620,
    "hard_limit": 2_234,
    "max_files": 45,
    "payload_byte_budget": 170_609,
    "max_patch_bytes": 1_364_872,
}
_MANUAL_LIMITS = {
    "max_files": 7,
    "hard_limit": 222,
    "max_patch_bytes": 123_456,
}


def _isolate_global_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("AHADIFF_PROVIDER_API_KEY", raising=False)


def _provider_config() -> str:
    return (
        "[llm]\n"
        'generate_provider = "demo"\n'
        'generate_model = "unknown-auto-capture-model"\n\n'
        "[providers.demo]\n"
        'provider_class = "openai"\n'
        'model_name = "unknown-auto-capture-model"\n'
        'base_url = "http://127.0.0.1:8000"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n'
        "probed_max_context = 128000\n"
    )


def _repo_with_config(tmp_path: Path, config_text: str) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".ahadiff").mkdir()
    (repo / ".ahadiff" / "config.toml").write_text(config_text, encoding="utf-8")
    return repo


def _auto_repo(tmp_path: Path) -> Path:
    return _repo_with_config(
        tmp_path,
        '[capture]\nmode = "auto"\n\n' + _provider_config(),
    )


def _manual_repo(tmp_path: Path) -> Path:
    return _repo_with_config(
        tmp_path,
        (
            "[capture]\n"
            'mode = "manual"\n'
            f"max_files = {_MANUAL_LIMITS['max_files']}\n"
            f"hard_limit = {_MANUAL_LIMITS['hard_limit']}\n"
            f"max_patch_bytes = {_MANUAL_LIMITS['max_patch_bytes']}\n\n" + _provider_config()
        ),
    )


def _write_patch(repo: Path) -> Path:
    patch_path = repo / "change.patch"
    patch_path.write_text(_PATCH_TEXT, encoding="utf-8")
    return patch_path


def _metadata_for(result_artifacts_path: str | None) -> dict[str, Any]:
    assert result_artifacts_path is not None
    payload = json.loads((Path(result_artifacts_path) / "metadata.json").read_text("utf-8"))
    assert isinstance(payload, dict)
    return cast("dict[str, Any]", payload)


def _client(repo: Path) -> TestClient:
    return TestClient(
        create_app(ServeState(state_dir=repo / ".ahadiff", token="test-token", locale="en")),
        base_url="http://localhost:8765",
    )


def _post_estimate(
    repo: Path,
    body: dict[str, object] | None = None,
) -> tuple[dict[str, Any], LearnEstimateResponse]:
    response = _client(repo).post(
        "/api/learn/estimate",
        json={} if body is None else body,
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200, response.text
    raw_payload = response.json()
    assert isinstance(raw_payload, dict)
    payload = cast("dict[str, Any]", raw_payload)
    return payload, LearnEstimateResponse.model_validate(payload)


def _estimate_ten_tokens(_text: str, _strategy: object) -> int:
    return 10


def _assert_auto_128k_limits(effective: dict[str, Any]) -> None:
    assert effective["mode"] == "auto"
    for key, value in _AUTO_128K_EXPECTED.items():
        assert effective[key] == value


def test_run_learn_pipeline_dry_run_auto_mode_records_effective_capture_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_global_config(tmp_path, monkeypatch)
    repo = _auto_repo(tmp_path)
    patch_path = _write_patch(repo)

    import ahadiff.git.capture as capture_module

    monkeypatch.setattr(capture_module, "make_run_id", lambda: "auto-capture-dry-run")

    result = run_learn_pipeline(
        LearnRequest(
            workspace_root=repo,
            patch=patch_path.name,
            dry_run=True,
        )
    )

    assert result.run_id == "auto-capture-dry-run"
    assert result.status == "dry_run"
    metadata = _metadata_for(result.artifacts_path)
    assert "effective_capture_limits" in metadata
    _assert_auto_128k_limits(cast("dict[str, Any]", metadata["effective_capture_limits"]))


def test_run_learn_pipeline_dry_run_manual_mode_preserves_configured_capture_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_global_config(tmp_path, monkeypatch)
    repo = _manual_repo(tmp_path)
    patch_path = _write_patch(repo)

    import ahadiff.git.capture as capture_module

    monkeypatch.setattr(capture_module, "make_run_id", lambda: "manual-capture-dry-run")

    result = run_learn_pipeline(
        LearnRequest(
            workspace_root=repo,
            patch=patch_path.name,
            dry_run=True,
        )
    )

    assert result.run_id == "manual-capture-dry-run"
    assert result.status == "dry_run"
    effective = cast(
        "dict[str, Any]",
        _metadata_for(result.artifacts_path)["effective_capture_limits"],
    )
    assert effective["mode"] == "manual"
    for key, value in _MANUAL_LIMITS.items():
        assert effective[key] == value
    assert effective["context_window"] == 128_000
    assert effective["diff_token_budget"] == _MANUAL_LIMITS["hard_limit"] * 24


def test_learn_estimate_auto_mode_reports_effective_limits_and_clipping_without_file_count_danger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_global_config(tmp_path, monkeypatch)
    repo = _auto_repo(tmp_path)
    captured_kwargs: dict[str, object] = {}

    def fake_capture_patch(**kwargs: object) -> SimpleNamespace:
        captured_kwargs.update(kwargs)
        return SimpleNamespace(
            persisted_patch_text=_PATCH_TEXT,
            metadata={
                "selected_files": [f"src/f{i}.py" for i in range(100)],
                "omitted_files": ["src/omitted_a.py", "src/omitted_b.py"],
                "degraded_flags": {"diff_clipped": True},
            },
        )

    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", _estimate_ten_tokens)

    raw_payload, payload = _post_estimate(repo)

    effective = cast("dict[str, Any]", raw_payload["effective_capture_limits"])
    _assert_auto_128k_limits(effective)
    assert captured_kwargs["max_files"] == effective["max_files"]
    assert captured_kwargs["hard_limit"] == effective["hard_limit"]
    assert captured_kwargs["max_patch_bytes"] == effective["max_patch_bytes"]
    assert payload.provider_context_window == 128_000
    assert payload.provider_max_output == 50_000
    assert payload.file_count == 100
    assert payload.diff_clipped is True
    assert payload.omitted_files_count == 2
    assert payload.risk_level == "warn"
    assert any("Capture omitted 2 files" in warning for warning in payload.warnings)
    assert any("Diff was clipped" in warning for warning in payload.warnings)
    assert all("File count" not in warning for warning in payload.warnings)


def test_auto_mode_estimate_and_dry_run_metadata_use_same_effective_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_global_config(tmp_path, monkeypatch)
    repo = _auto_repo(tmp_path)
    patch_path = _write_patch(repo)

    import ahadiff.git.capture as capture_module

    monkeypatch.setattr(capture_module, "make_run_id", lambda: "auto-capture-consistency")
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", _estimate_ten_tokens)

    raw_payload, _payload = _post_estimate(repo, body={"patch": patch_path.name})
    result = run_learn_pipeline(
        LearnRequest(
            workspace_root=repo,
            patch=patch_path.name,
            dry_run=True,
        )
    )

    metadata = _metadata_for(result.artifacts_path)
    estimate_limits = cast("dict[str, Any]", raw_payload["effective_capture_limits"])
    metadata_limits = cast("dict[str, Any]", metadata["effective_capture_limits"])
    for key in (
        "mode",
        "context_window",
        "max_input_tokens",
        "max_output_tokens",
        "diff_token_budget",
        "hard_limit",
        "max_files",
        "payload_byte_budget",
        "max_patch_bytes",
        "runtime_max_patch_bytes",
    ):
        assert metadata_limits[key] == estimate_limits[key]


def test_learn_estimate_manual_mode_preserves_old_file_count_risk_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_global_config(tmp_path, monkeypatch)
    repo = _manual_repo(tmp_path)
    captured_kwargs: dict[str, object] = {}

    def fake_capture_patch(**kwargs: object) -> SimpleNamespace:
        captured_kwargs.update(kwargs)
        return SimpleNamespace(
            persisted_patch_text=_PATCH_TEXT,
            metadata={
                "selected_files": [f"src/f{i}.py" for i in range(51)],
                "omitted_files": ["src/omitted.py"],
                "degraded_flags": {"diff_clipped": True},
            },
        )

    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", _estimate_ten_tokens)

    raw_payload, payload = _post_estimate(repo)

    effective = cast("dict[str, Any]", raw_payload["effective_capture_limits"])
    assert effective["mode"] == "manual"
    for key, value in _MANUAL_LIMITS.items():
        assert effective[key] == value
        assert captured_kwargs[key] == value
    assert payload.diff_clipped is True
    assert payload.omitted_files_count == 1
    assert payload.risk_level == "danger"
    assert any("File count 51 exceeds 50" in warning for warning in payload.warnings)
    assert all("Capture omitted" not in warning for warning in payload.warnings)
    assert all("Diff was clipped" not in warning for warning in payload.warnings)
