"""Tests for GET /api/config and GET /api/doctor endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from starlette.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

import ahadiff.serve.routes_config as routes_config_module
from ahadiff.serve import ServeState, create_app


def _client(
    state_dir: Path,
    *,
    token: str = "test-token",
    locale: Literal["en", "zh-CN"] = "en",
) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token=token, locale=locale))
    return TestClient(app, base_url="http://localhost:8765")


@dataclass
class _FakeLlm:
    generate_provider: str = ""
    generate_model: str | None = "fake-gen"
    judge_provider: str = ""
    judge_model: str | None = "fake-judge"
    api_key_env: str | None = None


@dataclass
class _FakeServe:
    port: int | None = 8765


@dataclass
class _FakeConfig:
    lang: str | None = "en"
    privacy_mode: str | None = "strict_local"
    llm: _FakeLlm | None = None
    serve: _FakeServe | None = None


@dataclass
class _FakeSnapshot:
    values: dict[str, Any]


def _mock_load_config_factory(
    config: _FakeConfig | None = None,
) -> Any:
    """Return a callable that replaces load_config for tests."""
    cfg = config or _FakeConfig(llm=_FakeLlm(), serve=_FakeServe())

    def _mock_load_config(*_args: Any, **_kwargs: Any) -> _FakeConfig:
        return cfg

    return _mock_load_config


# ---------------------------------------------------------------------------
# GET /api/config
# ---------------------------------------------------------------------------


def test_get_config_returns_json_with_expected_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    monkeypatch.setattr(
        "ahadiff.core.config.load_config",
        _mock_load_config_factory(),
    )
    client = _client(state_dir)

    response = client.get("/api/config")

    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    payload = response.json()
    for key in (
        "lang",
        "privacy_mode",
        "generate_model",
        "judge_model",
        "serve_port",
        "key_status",
    ):
        assert key in payload


def test_get_config_returns_actual_config_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    fake_cfg = _FakeConfig(
        llm=_FakeLlm(generate_model="test-gen", judge_model="test-judge"),
        serve=_FakeServe(),
    )
    monkeypatch.setattr(
        "ahadiff.core.config.load_config",
        _mock_load_config_factory(fake_cfg),
    )
    client = _client(state_dir)

    response = client.get("/api/config")

    payload = response.json()
    assert payload["generate_model"] == "test-gen"
    assert payload["judge_model"] == "test-judge"


def test_get_config_reads_nested_config_snapshot_values_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()

    def _mock_load_config(*_args: Any, **_kwargs: Any) -> _FakeSnapshot:
        return _FakeSnapshot(
            values={
                "lang": "auto",
                "privacy_mode": "strict_local",
                "llm": {
                    "generate_model": "gpt-5.4-mini",
                    "judge_model": "gpt-5.4-mini",
                    "api_key_env": "AHADIFF_PROVIDER_API_KEY",
                },
                "serve": {"port": 8765},
            }
        )

    monkeypatch.setattr("ahadiff.core.config.load_config", _mock_load_config)
    client = _client(state_dir)

    payload = client.get("/api/config").json()

    assert payload["lang"] == "auto"
    assert payload["privacy_mode"] == "strict_local"
    assert payload["generate_model"] == "gpt-5.4-mini"
    assert payload["judge_model"] == "gpt-5.4-mini"
    assert payload["serve_port"] == 8765


def test_get_config_key_status_reads_dynamic_provider_envs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()

    def _mock_load_config(*_args: Any, **_kwargs: Any) -> _FakeSnapshot:
        return _FakeSnapshot(
            values={
                "providers": {
                    "openai": {"api_key_env": "AHADIFF_OPENAI_KEY"},
                    "gemini": {"api_key_env": "AHADIFF_GEMINI_KEY"},
                    "local": {"api_key_env": ""},
                },
            }
        )

    monkeypatch.setattr("ahadiff.core.config.load_config", _mock_load_config)
    monkeypatch.setenv("AHADIFF_OPENAI_KEY", "sk-test")
    monkeypatch.delenv("AHADIFF_GEMINI_KEY", raising=False)
    client = _client(state_dir)

    payload = client.get("/api/config").json()

    assert payload["key_status"] == {
        "openai": "configured",
        "gemini": "missing",
    }


def test_get_config_handles_load_failure_gracefully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()

    def _raise_boom(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("ahadiff.core.config.load_config", _raise_boom)
    client = _client(state_dir)

    response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    _LLM_DEFAULTS = {
        "input_token_budget": 200_000,
        "output_token_budget": 50_000,
        "request_timeout_seconds": 30,
        "max_concurrent": 3,
        "retry_attempts": 3,
        "output_lang": "auto",
    }
    _CAPTURE_DEFAULTS = {
        "max_files": 30,
        "hard_limit": 3000,
        "max_patch_bytes": 5_000_000,
        "file_ranking": "learning_value",
        "symbol_extractor": "auto",
    }
    assert payload == {
        "lang": None,
        "privacy_mode": None,
        "generate_provider": None,
        "generate_model": None,
        "judge_provider": None,
        "judge_model": None,
        "serve_port": None,
        "key_status": {},
        "capture": _CAPTURE_DEFAULTS,
        "llm": _LLM_DEFAULTS,
        "learn": {"learnability_threshold": 0.3},
    }


def test_get_config_returns_nullable_shape_when_no_git_repo(tmp_path: Path) -> None:
    """tmp_path is not a git repo, so load_config fails and returns the fallback shape."""
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/config")

    payload = response.json()
    assert response.status_code == 200
    assert payload == {
        "lang": None,
        "privacy_mode": None,
        "generate_provider": None,
        "generate_model": None,
        "judge_provider": None,
        "judge_model": None,
        "serve_port": None,
        "key_status": {},
        "capture": {
            "max_files": 30,
            "hard_limit": 3000,
            "max_patch_bytes": 5_000_000,
            "file_ranking": "learning_value",
            "symbol_extractor": "auto",
        },
        "llm": {
            "input_token_budget": 200_000,
            "output_token_budget": 50_000,
            "request_timeout_seconds": 30,
            "max_concurrent": 3,
            "retry_attempts": 3,
            "output_lang": "auto",
        },
        "learn": {"learnability_threshold": 0.3},
    }


def test_get_config_key_status_shows_configured_when_env_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    fake_cfg = _FakeConfig(
        llm=_FakeLlm(api_key_env="AHADIFF_TEST_KEY_CFG"),
        serve=_FakeServe(),
    )
    monkeypatch.setattr(
        "ahadiff.core.config.load_config",
        _mock_load_config_factory(fake_cfg),
    )
    monkeypatch.setenv("AHADIFF_TEST_KEY_CFG", "sk-secret")
    client = _client(state_dir)

    response = client.get("/api/config")

    payload = response.json()
    assert payload["key_status"]["llm"] == "configured"


def test_get_config_key_status_shows_missing_when_env_not_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    fake_cfg = _FakeConfig(
        llm=_FakeLlm(api_key_env="AHADIFF_MISSING_KEY_CFG"),
        serve=_FakeServe(),
    )
    monkeypatch.setattr(
        "ahadiff.core.config.load_config",
        _mock_load_config_factory(fake_cfg),
    )
    monkeypatch.delenv("AHADIFF_MISSING_KEY_CFG", raising=False)
    client = _client(state_dir)

    response = client.get("/api/config")

    payload = response.json()
    assert payload["key_status"]["llm"] == "missing"


def test_get_config_key_status_empty_when_no_api_key_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    fake_cfg = _FakeConfig(
        llm=_FakeLlm(api_key_env=None),
        serve=_FakeServe(),
    )
    monkeypatch.setattr(
        "ahadiff.core.config.load_config",
        _mock_load_config_factory(fake_cfg),
    )
    client = _client(state_dir)

    response = client.get("/api/config")

    payload = response.json()
    assert payload["key_status"] == {}


def test_get_config_none_llm_and_serve_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    fake_cfg = _FakeConfig(llm=None, serve=None)
    monkeypatch.setattr(
        "ahadiff.core.config.load_config",
        _mock_load_config_factory(fake_cfg),
    )
    client = _client(state_dir)

    response = client.get("/api/config")

    payload = response.json()
    assert payload["generate_model"] is None
    assert payload["judge_model"] is None
    assert payload["serve_port"] is None
    assert payload["key_status"] == {}


def test_get_config_is_public_no_token_required(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/config")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/doctor
# ---------------------------------------------------------------------------


def test_get_doctor_returns_checks_list(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/doctor")

    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    payload = response.json()
    assert "checks" in payload
    assert payload["summary_status"] in {"pass", "warn", "fail"}
    assert isinstance(payload["checks"], list)


def test_get_doctor_repo_root_pass_when_ahadiff_dir_exists(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/doctor")

    checks = {c["name"]: c for c in response.json()["checks"]}
    assert checks["repo_root"]["status"] == "pass"
    assert ".ahadiff/ exists" in checks["repo_root"]["message"]


def test_get_doctor_repo_root_fail_when_ahadiff_dir_missing(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = _client(state_dir)

    response = client.get("/api/doctor")

    checks = {c["name"]: c for c in response.json()["checks"]}
    assert checks["repo_root"]["status"] == "fail"
    assert ".ahadiff/ not found" in checks["repo_root"]["message"]


def test_get_doctor_sqlite_version_always_pass(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/doctor")

    checks = {c["name"]: c for c in response.json()["checks"]}
    assert checks["sqlite_version"]["status"] == "pass"
    assert "SQLite" in checks["sqlite_version"]["message"]


def test_get_doctor_config_valid_pass_when_config_loads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    monkeypatch.setattr(
        "ahadiff.core.config.load_config",
        _mock_load_config_factory(),
    )
    client = _client(state_dir)

    response = client.get("/api/doctor")

    checks = {c["name"]: c for c in response.json()["checks"]}
    assert checks["config_valid"]["status"] == "pass"
    assert "Config loaded successfully" in checks["config_valid"]["message"]


def test_get_doctor_config_valid_fail_when_no_git_repo(tmp_path: Path) -> None:
    """Without a git repo, load_config raises and doctor reports config_valid=fail."""
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/doctor")

    checks = {c["name"]: c for c in response.json()["checks"]}
    assert checks["config_valid"]["status"] == "fail"
    assert "Config error:" in checks["config_valid"]["message"]


def test_get_doctor_config_valid_fail_when_config_malformed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()

    def _raise_bad(*_a: Any, **_kw: Any) -> None:
        raise ValueError("bad config")

    monkeypatch.setattr("ahadiff.core.config.load_config", _raise_bad)
    client = _client(state_dir)

    response = client.get("/api/doctor")

    checks = {c["name"]: c for c in response.json()["checks"]}
    assert checks["config_valid"]["status"] == "fail"
    assert "Config error: ValueError" in checks["config_valid"]["message"]


def test_get_doctor_review_db_pass_when_present(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "review.sqlite").write_bytes(b"")
    client = _client(state_dir)

    response = client.get("/api/doctor")

    checks = {c["name"]: c for c in response.json()["checks"]}
    assert checks["review_db"]["status"] == "pass"
    assert "review.sqlite present" in checks["review_db"]["message"]


def test_get_doctor_review_db_oserror_reports_generic_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "review.sqlite").write_bytes(b"not sqlite")

    def blocked_connect(*_args: Any, **_kwargs: Any) -> Any:
        raise PermissionError(str(state_dir / "review.sqlite"))

    monkeypatch.setattr(routes_config_module, "safe_sqlite_connect", blocked_connect)
    client = _client(state_dir)

    response = client.get("/api/doctor")

    assert response.status_code == 200
    checks = {c["name"]: c for c in response.json()["checks"]}
    assert checks["review_db_quick_check"]["status"] == "fail"
    assert checks["review_db_quick_check"]["message"] == "review.sqlite quick_check failed"
    assert str(state_dir) not in response.text


def test_get_doctor_review_db_warn_when_missing(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/doctor")

    checks = {c["name"]: c for c in response.json()["checks"]}
    assert checks["review_db"]["status"] == "warn"
    assert "review.sqlite not found" in checks["review_db"]["message"]


def test_get_doctor_check_entries_have_required_fields(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/doctor")

    for check in response.json()["checks"]:
        assert "name" in check
        assert "status" in check
        assert "message" in check
        assert "category" in check
        assert "details" in check
        assert check["status"] in {"pass", "fail", "warn"}


def test_get_doctor_includes_4d_prerequisite_checks(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/doctor")

    names = {check["name"] for check in response.json()["checks"]}
    assert {
        "state_dir_path",
        "sqlite_runtime_gate",
        "config_unknown_keys",
        "config_sensitive_keys",
        "config_precedence_conflicts",
        "review_db_quick_check",
        "usage_db",
        "audit_file",
    }.issubset(names)


def test_get_doctor_is_public_no_token_required(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/doctor")

    assert response.status_code == 200


def test_get_doctor_uses_anyio_threadpool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    calls: list[str] = []

    async def recording_run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
        del kwargs
        calls.append(getattr(func, "__name__", repr(func)))
        return func(*args)

    monkeypatch.setattr(routes_config_module.to_thread, "run_sync", recording_run_sync)
    client = _client(state_dir)

    assert client.get("/api/config").status_code == 200
    assert client.get("/api/doctor").status_code == 200

    assert "_safe_config_snapshot" in calls
    assert "_run_doctor_checks" in calls
