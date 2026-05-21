"""Tests for GET /api/install/targets endpoint."""

from __future__ import annotations

import sys
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
    for expected in (
        "antigravity",
        "antigravity-cli",
        "claude",
        "codex",
        "gemini",
        "hooks",
        "github-action",
    ):
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


def test_hooks_target_is_unsupported_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    monkeypatch.setattr(sys, "platform", "win32")
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    targets_by_name = {t["name"]: t for t in response.json()["targets"]}
    hooks = targets_by_name["hooks"]
    assert hooks["platform_supported"] is False
    assert hooks["status"] == "unsupported"
    assert hooks["detected"] is False
    for target_name in ("antigravity", "antigravity-cli", "codex", "gemini", "copilot"):
        assert targets_by_name[target_name]["platform_supported"] is True
        assert targets_by_name[target_name]["status"] == "available"


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
        "install_command",
        "uninstall_command",
        "manifest",
        "manifest_hash",
        "manifest_error",
        "error_message",
    }
    for target in response.json()["targets"]:
        assert set(target.keys()) == expected_keys
        assert target["description"]
        assert target["install_command"] == f"ahadiff install {target['name']}"
        assert target["uninstall_command"] == f"ahadiff uninstall {target['name']}"
        assert target["status"] in {"installed", "available", "unsupported", "error"}
        if target["manifest"] is not None:
            assert isinstance(target["manifest_hash"], str)
            assert len(target["manifest_hash"]) == 64


def test_get_install_targets_returns_manifest_preview(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    targets_by_name = {t["name"]: t for t in response.json()["targets"]}
    expected_manifests = {
        "codex": (
            "Codex CLI",
            ".agents/skills/ahadiff/SKILL.md",
            "AGENTS.md",
        ),
        "gemini": (
            "Gemini CLI",
            ".gemini/skills/ahadiff/SKILL.md",
            "GEMINI.md",
        ),
        "copilot": (
            "Copilot / VS Code",
            ".github/instructions/ahadiff.instructions.md",
            ".github/copilot-instructions.md",
        ),
    }
    for name, (display_name, generated_path, section_path) in expected_manifests.items():
        target = targets_by_name[name]
        assert target["display_name"] == display_name
        assert target["manifest_error"] is None
        assert len(target["manifest_hash"]) == 64
        assert target["manifest"]["write"] == [
            {"action": "write", "file_strategy": "generated", "path": generated_path},
            {"action": "merge-section", "file_strategy": "user-managed", "path": section_path},
        ]
        assert target["manifest"]["uninstall"] == [
            {"action": "remove", "file_strategy": "generated", "path": generated_path},
            {"action": "remove-section", "file_strategy": "user-managed", "path": section_path},
        ]

    antigravity = targets_by_name["antigravity"]
    assert antigravity["display_name"] == "Antigravity IDE"
    assert antigravity["manifest_error"] is None
    assert len(antigravity["manifest_hash"]) == 64
    assert antigravity["manifest"]["write"] == [
        {
            "action": "write",
            "file_strategy": "generated",
            "path": ".agents/skills/ahadiff-antigravity/SKILL.md",
        },
        {"action": "write", "file_strategy": "generated", "path": ".agents/rules/ahadiff.md"},
    ]
    assert antigravity["manifest"]["uninstall"] == [
        {
            "action": "remove",
            "file_strategy": "generated",
            "path": ".agents/skills/ahadiff-antigravity/SKILL.md",
        },
        {"action": "remove", "file_strategy": "generated", "path": ".agents/rules/ahadiff.md"},
    ]

    antigravity_cli = targets_by_name["antigravity-cli"]
    assert antigravity_cli["display_name"] == "Antigravity CLI"
    assert antigravity_cli["manifest_error"] is None
    assert len(antigravity_cli["manifest_hash"]) == 64
    assert antigravity_cli["manifest"]["write"] == [
        {
            "action": "write",
            "file_strategy": "generated",
            "path": ".agents/skills/ahadiff-antigravity-cli/SKILL.md",
        },
        {"action": "merge-section", "file_strategy": "user-managed", "path": "GEMINI.md"},
    ]
    assert antigravity_cli["manifest"]["uninstall"] == [
        {
            "action": "remove",
            "file_strategy": "generated",
            "path": ".agents/skills/ahadiff-antigravity-cli/SKILL.md",
        },
        {"action": "remove-section", "file_strategy": "user-managed", "path": "GEMINI.md"},
    ]


def test_all_registered_targets_appear_in_response(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    from ahadiff.install.registry import available_targets

    response = client.get("/api/install/targets")

    response_names = {t["name"] for t in response.json()["targets"]}
    for name in available_targets():
        assert name in response_names


def test_detect_timeout_marks_error_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    original_get_target = routes_install_module.get_target

    def timeout_get_target(name: str) -> Any:
        target = original_get_target(name)
        if name == "codex":

            class TimeoutTarget:
                def detect(self, _ctx: Any) -> bool:
                    raise routes_install_module.subprocess.TimeoutExpired(["detect"], 1)

            return TimeoutTarget()
        return target

    monkeypatch.setattr(routes_install_module, "get_target", timeout_get_target)
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    codex = {t["name"]: t for t in response.json()["targets"]}["codex"]
    assert codex["status"] == "error"
    assert codex["error_message"] == "target detection timed out"


def test_manifest_preview_exception_sets_manifest_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    original_get_target = routes_install_module.get_target

    def failing_manifest_get_target(name: str) -> Any:
        target = original_get_target(name)
        if name == "codex":

            class FailingManifestTarget:
                name = "codex"

                def detect(self, _ctx: Any) -> bool:
                    return False

                def preview(self, _ctx: Any) -> str:
                    raise RuntimeError("preview failed")

            return FailingManifestTarget()
        return target

    monkeypatch.setattr(routes_install_module, "get_target", failing_manifest_get_target)
    client = _client(state_dir)

    response = client.get("/api/install/targets")

    codex = {t["name"]: t for t in response.json()["targets"]}["codex"]
    assert codex["status"] == "available"
    assert codex["manifest"] is None
    assert codex["manifest_hash"] is None
    assert codex["manifest_error"] == "target manifest preview failed"


def test_install_preview_returns_manifest_hash_and_is_read_only(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)

    response = client.post(
        "/api/install/codex/preview",
        headers={"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"},
        json={},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target"]["name"] == "codex"
    assert len(payload["manifest_hash"]) == 64
    assert payload["manifest_hash"] == payload["target"]["manifest_hash"]
    assert not (state_dir.parent / "AGENTS.md").exists()


def test_install_mutation_requires_token_and_manifest_confirmation(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)
    headers = {"origin": "http://localhost:8765"}

    denied = client.post(
        "/api/install/codex",
        headers=headers,
        json={"confirmed_manifest_hash": "0" * 64},
    )
    mismatch = client.post(
        "/api/install/codex",
        headers={**headers, "X-AhaDiff-Token": "test-token"},
        json={"confirmed_manifest_hash": "0" * 64},
    )

    assert denied.status_code == 401
    assert mismatch.status_code == 400
    assert "confirmed_manifest_hash" in mismatch.json()["error"]
    assert not (state_dir.parent / "AGENTS.md").exists()


def test_install_mutation_rejects_manifest_hash_when_force_option_changes(tmp_path: Path) -> None:
    state_dir = tmp_path / "repo" / ".ahadiff"
    state_dir.mkdir(parents=True)
    skill_path = state_dir.parent / ".agents" / "skills" / "ahadiff" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("user-managed\n", encoding="utf-8")
    client = _client(state_dir)
    headers = {"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"}

    default_preview = client.post("/api/install/codex/preview", headers=headers, json={}).json()
    mismatched_force = client.post(
        "/api/install/codex",
        headers=headers,
        json={"confirmed_manifest_hash": default_preview["manifest_hash"], "force": True},
    )
    assert mismatched_force.status_code == 400
    assert skill_path.read_text(encoding="utf-8") == "user-managed\n"

    force_preview = client.post(
        "/api/install/codex/preview",
        headers=headers,
        json={"force": True},
    ).json()
    installed = client.post(
        "/api/install/codex",
        headers=headers,
        json={"confirmed_manifest_hash": force_preview["manifest_hash"], "force": True},
    )

    assert force_preview["manifest_hash"] != default_preview["manifest_hash"]
    assert installed.status_code == 200
    assert "<!-- AHADIFF:GENERATED -->" in skill_path.read_text(encoding="utf-8")


def test_install_and_uninstall_mutations_write_only_tmp_repo(tmp_path: Path) -> None:
    state_dir = tmp_path / "repo" / ".ahadiff"
    state_dir.mkdir(parents=True)
    client = _client(state_dir)
    headers = {"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"}

    preview = client.post("/api/install/codex/preview", headers=headers, json={}).json()
    installed = client.post(
        "/api/install/codex",
        headers=headers,
        json={"confirmed_manifest_hash": preview["manifest_hash"]},
    )
    uninstall_preview = client.post("/api/install/codex/preview", headers=headers, json={}).json()
    uninstalled = client.post(
        "/api/install/codex/uninstall",
        headers=headers,
        json={"confirmed_manifest_hash": uninstall_preview["manifest_hash"]},
    )

    agents_path = state_dir.parent / "AGENTS.md"
    assert installed.status_code == 200
    assert installed.json()["operation"] == "install"
    expected_paths = [".agents/skills/ahadiff/SKILL.md", "AGENTS.md"]
    assert sorted(installed.json()["updated_paths"]) == sorted(expected_paths)
    assert installed.json()["target"]["status"] == "installed"
    assert agents_path.exists()
    assert uninstalled.status_code == 200
    assert uninstalled.json()["operation"] == "uninstall"
    assert sorted(uninstalled.json()["updated_paths"]) == sorted(expected_paths)
    assert "AHADIFF:BEGIN target=codex" not in agents_path.read_text(encoding="utf-8")
    assert uninstalled.json()["target"]["detected"] is False


def test_install_mutation_rejects_repo_root_override(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = _client(state_dir)
    headers = {"origin": "http://localhost:8765", "X-AhaDiff-Token": "test-token"}
    preview = client.post("/api/install/codex/preview", headers=headers, json={}).json()

    response = client.post(
        "/api/install/codex",
        headers=headers,
        json={
            "confirmed_manifest_hash": preview["manifest_hash"],
            "repo_root": str(tmp_path / "other"),
        },
    )

    assert response.status_code == 422
    assert not (tmp_path / "other" / "AGENTS.md").exists()
