"""Tests for GET /api/install/targets endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from starlette.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

import ahadiff.serve.routes_install as routes_install_module
from ahadiff.serve import ServeState, create_app


def _client(
    state_dir: Path,
    *,
    token: str = "test-token",
    locale: Literal["en", "zh-CN"] = "en",
) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token=token, locale=locale))
    return TestClient(app, base_url="http://localhost:8765")


# ---------------------------------------------------------------------------
# GET /api/install/targets — happy path
# ---------------------------------------------------------------------------


def test_get_install_targets_returns_json_list(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    payload = response.json()
    assert "targets" in payload
    assert isinstance(payload["targets"], list)


def test_get_install_targets_each_entry_has_expected_schema(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    targets = response.json()["targets"]
    assert len(targets) > 0
    for target in targets:
        assert "name" in target
        assert isinstance(target["name"], str)
        assert "detected" in target
        assert isinstance(target["detected"], bool)
        assert "platform_supported" in target
        assert isinstance(target["platform_supported"], bool)
        assert "description" in target


def test_get_install_targets_contains_known_targets(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    names = {t["name"] for t in response.json()["targets"]}
    for expected in ("claude", "codex", "gemini", "hooks", "github-action"):
        assert expected in names


def test_get_install_targets_is_public_no_token_required(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# detect() error handling
# ---------------------------------------------------------------------------


def test_get_install_targets_handles_detect_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()

    def patched_detect_all(state: Any) -> list[dict[str, Any]]:
        return [
            {"name": "claude", "detected": False, "platform_supported": True, "description": ""}
        ]

    monkeypatch.setattr(routes_install_module, "_detect_all_targets", patched_detect_all)
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    assert response.status_code == 200
    targets_by_name = {t["name"]: t for t in response.json()["targets"]}
    assert targets_by_name["claude"]["detected"] is False


def test_detect_exception_does_not_crash_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a target's detect() raises, the endpoint still returns, with detected=False."""
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()

    original_get_target = routes_install_module.get_target

    def exploding_get_target(name: str) -> Any:
        target = original_get_target(name)
        if name == "claude":

            class ExplodingTarget:
                def detect(self, _ctx: Any) -> bool:
                    raise RuntimeError("detect failed")

            return ExplodingTarget()
        return target

    monkeypatch.setattr(routes_install_module, "get_target", exploding_get_target)
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    assert response.status_code == 200
    targets_by_name = {t["name"]: t for t in response.json()["targets"]}
    assert targets_by_name["claude"]["detected"] is False


def test_detect_not_implemented_marks_platform_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a target's detect() raises NotImplementedError, platform_supported becomes False."""
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()

    original_get_target = routes_install_module.get_target

    def not_impl_get_target(name: str) -> Any:
        target = original_get_target(name)
        if name == "hooks":

            class NotImplTarget:
                def detect(self, _ctx: Any) -> bool:
                    raise NotImplementedError("not supported on this platform")

            return NotImplTarget()
        return target

    monkeypatch.setattr(routes_install_module, "get_target", not_impl_get_target)
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    targets_by_name = {t["name"]: t for t in response.json()["targets"]}
    assert targets_by_name["hooks"]["platform_supported"] is False
    assert targets_by_name["hooks"]["detected"] is False


# ---------------------------------------------------------------------------
# InstallContext failure
# ---------------------------------------------------------------------------


def test_get_install_targets_returns_empty_when_context_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()

    def _failing_context(**_kw: Any) -> None:
        raise RuntimeError("context init failed")

    monkeypatch.setattr(routes_install_module, "InstallContext", _failing_context)
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    assert response.status_code == 200
    assert response.json() == {"targets": [], "total": 0}


# ---------------------------------------------------------------------------
# available_targets returns empty
# ---------------------------------------------------------------------------


def test_get_install_targets_empty_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()

    monkeypatch.setattr(routes_install_module, "available_targets", lambda: ())
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    assert response.status_code == 200
    assert response.json() == {"targets": [], "total": 0}


# ---------------------------------------------------------------------------
# anyio threadpool delegation
# ---------------------------------------------------------------------------


def test_get_install_targets_uses_anyio_threadpool(
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

    monkeypatch.setattr(routes_install_module.to_thread, "run_sync", recording_run_sync)
    client = _client(state_dir)

    assert client.get("/api/install/targets").status_code == 200

    assert "_detect_all_targets" in calls


# ---------------------------------------------------------------------------
# Response schema alignment with frontend types.ts
# ---------------------------------------------------------------------------


def test_response_schema_matches_frontend_expectations(tmp_path: Path) -> None:
    """Each target entry should have the exact keys expected by viewer/src/api/types.ts."""
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    assert response.json()["total"] == len(response.json()["targets"])
    expected_keys = {
        "name",
        "display_name",
        "detected",
        "platform_supported",
        "status",
        "description",
        "error_message",
    }
    for target in response.json()["targets"]:
        assert set(target.keys()) == expected_keys
        assert target["description"]
        assert target["status"] in {"installed", "available", "unsupported", "error"}


def test_all_registered_targets_appear_in_response(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    from ahadiff.install.registry import available_targets

    response = client.get("/api/install/targets")

    response_names = {t["name"] for t in response.json()["targets"]}
    for name in available_targets():
        assert name in response_names
