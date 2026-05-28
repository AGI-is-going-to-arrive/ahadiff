"""Tests for GET /api/config and GET /api/doctor endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path

import ahadiff.serve.routes_config as routes_config_module
from ahadiff.contracts.serve_app import LearnConfig, QuizConfig
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


def _validate_quiz_update_for_test(
    payload: object,
    *,
    current_quiz: object | None = None,
) -> dict[str, Any] | str:
    return cast("Any", routes_config_module)._validate_quiz_update(
        payload,
        current_quiz=current_quiz,
    )


def _validate_llm_update_for_test(payload: object) -> dict[str, Any] | str:
    return cast("Any", routes_config_module)._validate_llm_update(payload)


# ---------------------------------------------------------------------------
# GET /api/config
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_learn_config_contract_rejects_invalid_threshold(value: float) -> None:
    with pytest.raises(ValidationError, match="learnability_threshold"):
        LearnConfig.model_validate({"learnability_threshold": value})


@pytest.mark.parametrize("value", [0, 31, True, "3"])
def test_quiz_config_contract_rejects_invalid_question_count(value: object) -> None:
    with pytest.raises(ValidationError, match="quiz_question_count"):
        QuizConfig.model_validate({"quiz_question_count": value})


def test_quiz_config_contract_accepts_max_question_count() -> None:
    config = QuizConfig.model_validate(
        {
            "quiz_question_count": 30,
            "quiz_auto_range_min": 30,
            "quiz_auto_range_max": 30,
        }
    )

    assert config.quiz_question_count == 30
    assert config.quiz_auto_range_min == 30
    assert config.quiz_auto_range_max == 30


@pytest.mark.parametrize("value", ["adaptive", "", 3, True])
def test_quiz_config_contract_rejects_invalid_question_count_mode(value: object) -> None:
    with pytest.raises(ValidationError, match="quiz_question_count_mode"):
        QuizConfig.model_validate({"quiz_question_count_mode": value})


@pytest.mark.parametrize("field", ["quiz_auto_range_min", "quiz_auto_range_max"])
@pytest.mark.parametrize("value", [0, 31, True, "3"])
def test_quiz_config_contract_rejects_invalid_auto_range(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError, match=field):
        QuizConfig.model_validate({field: value})


def test_quiz_config_contract_rejects_auto_range_min_above_max() -> None:
    with pytest.raises(ValidationError, match="quiz_auto_range_min"):
        QuizConfig.model_validate({"quiz_auto_range_min": 8, "quiz_auto_range_max": 3})


def test_validate_llm_update_accepts_structured_output_controls() -> None:
    assert _validate_llm_update_for_test(
        {
            "structured_output_mode": "native_json_schema",
            "structured_validation_retries": 2,
        }
    ) == {
        "structured_output_mode": "native_json_schema",
        "structured_validation_retries": 2,
    }


@pytest.mark.parametrize("value", ["auto", "", 3, True])
def test_validate_llm_update_rejects_unknown_structured_output_mode(value: object) -> None:
    result = _validate_llm_update_for_test({"structured_output_mode": value})

    assert isinstance(result, str)
    assert "llm.structured_output_mode" in result


@pytest.mark.parametrize("value", [-1, 3, True, "1"])
def test_validate_llm_update_rejects_invalid_validation_retries(value: object) -> None:
    result = _validate_llm_update_for_test({"structured_validation_retries": value})

    assert isinstance(result, str)
    assert "llm.structured_validation_retries" in result


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

    monkeypatch.setattr("ahadiff.serve.config_runtime.load_serve_config_snapshot", _raise_boom)
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
        "mode": "auto",
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
        "learn": {"learnability_threshold": 0.3, "desired_retention": 0.9},
        "quiz": {
            "quiz_question_count": 3,
            "quiz_question_count_mode": "fixed",
            "quiz_auto_range_min": 3,
            "quiz_auto_range_max": 12,
        },
        "model_limits": {"generate": None, "judge": None},
    }


def test_get_config_returns_nullable_shape_when_no_git_repo(tmp_path: Path) -> None:
    """Non-git workspaces still expose defaults through load_workspace_config."""
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/config")

    payload = response.json()
    assert response.status_code == 200
    assert payload["lang"] == "auto"
    assert payload["privacy_mode"] == "strict_local"
    assert payload["generate_model"] == "gpt-5.4-mini"
    assert payload["judge_model"] == "gpt-5.4-mini"
    assert payload["serve_port"] == 8765
    assert payload["learn"] == {"learnability_threshold": 0.3, "desired_retention": 0.9}
    assert payload["quiz"] == {
        "quiz_question_count": 3,
        "quiz_question_count_mode": "fixed",
        "quiz_auto_range_min": 3,
        "quiz_auto_range_max": 12,
    }


def test_get_config_reads_workspace_config_when_no_git_repo(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[learn]\ndesired_retention = 0.84\n\n[quiz]\nquiz_question_count = 6\n",
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["learn"]["desired_retention"] == 0.84
    assert response.json()["quiz"]["quiz_question_count"] == 6
    assert response.json()["quiz"]["quiz_question_count_mode"] == "fixed"
    assert response.json()["quiz"]["quiz_auto_range_min"] == 3
    assert response.json()["quiz"]["quiz_auto_range_max"] == 12


def test_validate_capture_update_accepts_auto_mode_without_numeric_validation() -> None:
    result = cast("Any", routes_config_module)._validate_capture_update(
        {"mode": "auto", "max_files": "computed"}
    )

    assert result == {"mode": "auto"}


def test_validate_capture_update_rejects_invalid_mode() -> None:
    result = cast("Any", routes_config_module)._validate_capture_update({"mode": "adaptive"})

    assert isinstance(result, str)
    assert "capture.mode" in result


def test_put_config_rejects_invalid_capture_mode_without_writing_config(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir()
    config_path = state_dir / "config.toml"
    original = '[capture]\nmode = "manual"\nmax_files = 9\n'
    config_path.write_text(original, encoding="utf-8")
    client = _client(state_dir)

    response = client.put(
        "/api/config",
        json={"capture": {"mode": "invalid"}},
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
    )

    assert response.status_code == 400
    assert "capture.mode" in response.json()["error"]
    assert config_path.read_text(encoding="utf-8") == original


def test_put_config_persists_under_repo_write_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "repo" / ".ahadiff"
    state_dir.mkdir(parents=True)
    events: list[str] = []

    class RecordingLock:
        def __enter__(self) -> None:
            events.append("enter")

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb
            events.append("exit")

    def fake_lock(_state: object, *, command: str) -> RecordingLock:
        events.append(command)
        return RecordingLock()

    monkeypatch.setattr(routes_config_module, "serve_repo_write_lock", fake_lock)
    client = _client(state_dir)

    response = client.put(
        "/api/config",
        json={"generate_model": "gpt-5.5-mini"},
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
    )

    assert response.status_code == 200
    assert events == ["serve config update", "enter", "exit"]
    assert 'generate_model = "gpt-5.5-mini"' in (state_dir / "config.toml").read_text(
        encoding="utf-8"
    )


def test_put_config_reads_validates_and_persists_under_repo_write_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ahadiff.core import config as config_module

    repo_root = tmp_path / "repo"
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir(parents=True)
    config_path = state_dir / "config.toml"
    config_path.write_text(
        "[quiz]\n"
        "quiz_auto_range_max = 10\n\n"
        "[providers.local]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.5"\n'
        'base_url = "http://127.0.0.1:8318"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n',
        encoding="utf-8",
    )
    lock_depth = 0
    read_depths: list[int] = []

    class RecordingLock:
        def __enter__(self) -> None:
            nonlocal lock_depth
            lock_depth += 1

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            nonlocal lock_depth
            del exc_type, exc, tb
            lock_depth -= 1

    def fake_lock(_state: object, *, command: str) -> RecordingLock:
        assert command == "serve config update"
        return RecordingLock()

    real_read_config_data = config_module.read_config_data

    def recording_read_config_data(path: Path) -> dict[str, Any]:
        if path == config_path:
            read_depths.append(lock_depth)
        return real_read_config_data(path)

    monkeypatch.setattr(routes_config_module, "serve_repo_write_lock", fake_lock)
    monkeypatch.setattr(config_module, "read_config_data", recording_read_config_data)
    client = _client(state_dir)

    response = client.put(
        "/api/config",
        json={"generate_provider": "local", "quiz": {"quiz_auto_range_min": 9}},
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
    )

    assert response.status_code == 200
    assert read_depths
    assert set(read_depths) == {1}


def test_put_config_updates_runtime_locale_under_repo_write_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir(parents=True)
    state = ServeState(state_dir=state_dir, token="test-token")
    lock_depth = 0
    locale_update_depths: list[int] = []

    class RecordingAppState:
        def __init__(self, initial: ServeState) -> None:
            self._ahadiff = initial

        @property
        def ahadiff(self) -> ServeState:
            return self._ahadiff

        @ahadiff.setter
        def ahadiff(self, value: ServeState) -> None:
            locale_update_depths.append(lock_depth)
            self._ahadiff = value

    class RecordingLock:
        def __enter__(self) -> None:
            nonlocal lock_depth
            lock_depth += 1

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            nonlocal lock_depth
            del exc_type, exc, tb
            lock_depth -= 1

    def fake_lock(_state: object, *, command: str) -> RecordingLock:
        assert command == "serve config update"
        return RecordingLock()

    monkeypatch.setattr(routes_config_module, "serve_repo_write_lock", fake_lock)
    app_state = RecordingAppState(state)

    result = cast("Any", routes_config_module)._validate_and_persist_config_with_lock(
        app_state,
        state,
        {"lang": "zh-CN"},
        {},
        False,
        None,
        "zh-CN",
    )

    assert result is None
    assert locale_update_depths == [1]
    assert app_state.ahadiff.locale == "zh-CN"
    assert 'lang = "zh-CN"' in (state_dir / "config.toml").read_text(encoding="utf-8")


def test_put_config_validation_errors_use_error_code(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.put(
        "/api/config",
        json={"serve_port": 80},
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "INPUT_BAD_FIELD"


def test_validate_quiz_update_accepts_auto_fields() -> None:
    assert _validate_quiz_update_for_test(
        {
            "quiz_question_count_mode": "auto",
            "quiz_auto_range_min": 2,
            "quiz_auto_range_max": 9,
        }
    ) == {
        "quiz_question_count_mode": "auto",
        "quiz_auto_range_min": 2,
        "quiz_auto_range_max": 9,
    }


def test_validate_quiz_update_accepts_max_count_and_range() -> None:
    assert _validate_quiz_update_for_test(
        {
            "quiz_question_count": 30,
            "quiz_auto_range_min": 30,
            "quiz_auto_range_max": 30,
        }
    ) == {
        "quiz_question_count": 30,
        "quiz_auto_range_min": 30,
        "quiz_auto_range_max": 30,
    }


def test_put_config_partial_auto_range_min_uses_current_max_and_threadpool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[quiz]\nquiz_auto_range_max = 10\n",
        encoding="utf-8",
    )
    calls: list[str] = []

    async def recording_run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
        del kwargs
        calls.append(getattr(func, "__name__", repr(func)))
        return func(*args)

    monkeypatch.setattr(routes_config_module.to_thread, "run_sync", recording_run_sync)
    client = _client(state_dir)

    response = client.put(
        "/api/config",
        json={"quiz": {"quiz_auto_range_min": 9}},
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
    )

    assert response.status_code == 200
    assert "_validate_and_persist_config_with_lock" in calls


def test_put_config_rejects_partial_quiz_update_when_existing_range_is_invalid(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[quiz]\nquiz_auto_range_min = 9\nquiz_auto_range_max = 3\n",
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.put(
        "/api/config",
        json={"quiz": {"quiz_question_count": 4}},
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
    )

    assert response.status_code == 400
    assert "quiz.quiz_auto_range_min" in response.json()["error"]


def test_validate_quiz_update_allows_payload_to_fix_existing_invalid_range() -> None:
    assert _validate_quiz_update_for_test(
        {"quiz_auto_range_max": 10},
        current_quiz={"quiz_auto_range_min": 9, "quiz_auto_range_max": 3},
    ) == {"quiz_auto_range_max": 10}


def test_validate_quiz_update_rejects_unknown_quiz_keys() -> None:
    result = _validate_quiz_update_for_test({"extra": 1})

    assert isinstance(result, str)
    assert "unknown quiz keys" in result


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"quiz_question_count_mode": "adaptive"}, "quiz.quiz_question_count_mode"),
        ({"quiz_question_count_mode": 3}, "quiz.quiz_question_count_mode"),
        ({"quiz_question_count_mode": True}, "quiz.quiz_question_count_mode"),
        ({"quiz_auto_range_min": 0}, "quiz.quiz_auto_range_min"),
        ({"quiz_auto_range_max": 31}, "quiz.quiz_auto_range_max"),
        ({"quiz_auto_range_min": True}, "quiz.quiz_auto_range_min"),
        ({"quiz_auto_range_max": True}, "quiz.quiz_auto_range_max"),
        ({"quiz_auto_range_max": "8"}, "quiz.quiz_auto_range_max"),
        (
            {"quiz_auto_range_min": 8, "quiz_auto_range_max": 3},
            "quiz.quiz_auto_range_min must be <= quiz.quiz_auto_range_max",
        ),
    ],
)
def test_validate_quiz_update_rejects_invalid_auto_fields(
    payload: dict[str, object],
    expected: str,
) -> None:
    result = _validate_quiz_update_for_test(payload)

    assert isinstance(result, str)
    assert expected in result


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


def test_get_config_includes_generate_model_limits_when_provider_configured(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[llm]\n"
        'generate_provider = "gen"\n'
        'generate_model = "gpt-5.4-mini"\n'
        "\n[providers.gen]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n',
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.get("/api/config")

    assert response.status_code == 200
    generate_limits = response.json()["model_limits"]["generate"]
    assert generate_limits["alias"] == "gen"
    assert generate_limits["model_name"] == "gpt-5.4-mini"
    assert generate_limits["max_output_tokens"] == 128000
    assert response.json()["model_limits"]["judge"]["alias"] == "gen"


def test_get_config_model_limits_use_provider_model_when_role_model_is_default(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[llm]\n"
        'generate_provider = "gen"\n'
        "\n[providers.gen]\n"
        'provider_class = "gemini"\n'
        'model_name = "gemini-2.5-pro"\n'
        'base_url = "https://generativelanguage.googleapis.com/v1beta"\n'
        'api_key_env = "GEMINI_API_KEY"\n',
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["generate_model"] == "gpt-5.4-mini"
    generate_limits = payload["model_limits"]["generate"]
    assert generate_limits["alias"] == "gen"
    assert generate_limits["model_name"] == "gemini-2.5-pro"
    assert generate_limits["max_output_tokens"] == 65536


def test_get_config_model_limits_ignore_provider_limits_profile_for_role_model_override(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[llm]\n"
        'generate_provider = "gen"\n'
        'generate_model = "gpt-4o"\n'
        "\n[providers.gen]\n"
        'provider_class = "openai"\n'
        'model_name = "deployment-name"\n'
        'model_limits_name = "openai/gpt-5"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n',
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.get("/api/config")

    assert response.status_code == 200
    generate_limits = response.json()["model_limits"]["generate"]
    assert generate_limits["model_name"] == "gpt-4o"
    assert generate_limits["max_output_tokens"] == 16384


def test_get_config_model_limits_use_single_provider_when_role_provider_is_default(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    state_dir = repo_root / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        "[providers.only]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-4o"\n'
        'base_url = "https://api.example.test/v1"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n',
        encoding="utf-8",
    )
    client = _client(state_dir)

    response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["generate_provider"] == ""
    assert payload["judge_provider"] == ""
    generate_limits = payload["model_limits"]["generate"]
    judge_limits = payload["model_limits"]["judge"]
    assert generate_limits["alias"] == "only"
    assert generate_limits["model_name"] == "gpt-4o"
    assert judge_limits["alias"] == "only"
    assert judge_limits["model_name"] == "gpt-4o"


def test_get_config_model_limits_are_null_without_selected_provider(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["model_limits"] == {"generate": None, "judge": None}


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
