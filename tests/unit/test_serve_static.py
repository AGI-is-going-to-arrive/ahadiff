from __future__ import annotations

# pyright: reportPrivateUsage=false
import importlib
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

import ahadiff.serve.static as static_module
from ahadiff.core.watcher import is_watchdog_available
from ahadiff.git import tree_sitter_runtime
from ahadiff.review import apkg_export
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from pathlib import Path


class _PackageFiles:
    def __init__(self, candidate: object) -> None:
        self._candidate = candidate

    def joinpath(self, *_parts: str) -> object:
        return self._candidate


class _NonFilesystemTraversable:
    def __init__(self, value: str) -> None:
        self._value = value

    def __str__(self) -> str:
        return self._value


def _patch_packaged_webui(monkeypatch: pytest.MonkeyPatch, candidate: object) -> None:
    def fake_files(package: str) -> _PackageFiles:
        assert package == "ahadiff"
        return _PackageFiles(candidate)

    monkeypatch.setattr(static_module, "files", fake_files, raising=False)


def _clear_viewer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AHADIFF_VIEWER_DIST", raising=False)


def _write_viewer_dist(repo_root: Path, body: str = "<h1>dev</h1>\n") -> Path:
    viewer_dist = repo_root / "viewer" / "dist"
    viewer_dist.mkdir(parents=True)
    (viewer_dist / "index.html").write_text(body, encoding="utf-8")
    return viewer_dist


def _write_ahadiff_source_signals(repo_root: Path) -> None:
    package_dir = repo_root / "src" / "ahadiff"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text('"""AhaDiff test package."""\n', encoding="utf-8")
    (repo_root / "pyproject.toml").write_text(
        '[project]\nname = "ahadiff"\n',
        encoding="utf-8",
    )


def _patch_module_file(monkeypatch: pytest.MonkeyPatch, module_file: Path) -> None:
    monkeypatch.setattr(static_module, "__file__", str(module_file), raising=False)


def test_resolve_viewer_dist_prefers_packaged_webui_with_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_viewer_env(monkeypatch)
    packaged = tmp_path / "package" / "_webui"
    packaged.mkdir(parents=True)
    (packaged / "index.html").write_text("<h1>packaged</h1>\n", encoding="utf-8")
    repo_root = tmp_path / "repo"
    _write_ahadiff_source_signals(repo_root)
    _write_viewer_dist(repo_root)
    _patch_packaged_webui(monkeypatch, packaged)

    assert static_module._resolve_viewer_dist() == packaged


def test_resolve_viewer_dist_ignores_spoofed_served_workspace_source_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_viewer_env(monkeypatch)
    served_workspace = tmp_path / "served-workspace"
    _write_ahadiff_source_signals(served_workspace)
    _write_viewer_dist(served_workspace, "<h1>attacker ui</h1>\n")
    _patch_packaged_webui(monkeypatch, tmp_path / "missing" / "_webui")
    _patch_module_file(
        monkeypatch,
        tmp_path / "site-packages" / "ahadiff" / "serve" / "static.py",
    )

    assert static_module._resolve_viewer_dist() is None


def test_resolve_viewer_dist_falls_back_to_module_source_checkout_dist_when_packaged_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_viewer_env(monkeypatch)
    source_checkout = tmp_path / "source-checkout"
    module_dist = _write_viewer_dist(source_checkout)
    module_file = source_checkout / "src" / "ahadiff" / "serve" / "static.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("# test module path\n", encoding="utf-8")
    _patch_packaged_webui(monkeypatch, tmp_path / "missing" / "_webui")
    _patch_module_file(monkeypatch, module_file)

    assert static_module._resolve_viewer_dist() == module_dist


def test_resolve_viewer_dist_returns_none_and_mount_noops_when_assets_are_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_viewer_env(monkeypatch)
    _patch_packaged_webui(monkeypatch, tmp_path / "missing" / "_webui")
    _patch_module_file(
        monkeypatch,
        tmp_path / "site-packages" / "ahadiff" / "serve" / "static.py",
    )

    viewer_dist = static_module._resolve_viewer_dist()
    app = create_app(
        ServeState(state_dir=tmp_path / ".ahadiff", token="test-token"),
        viewer_dist=viewer_dist,
    )
    client = TestClient(app, base_url="http://localhost:8765")

    assert viewer_dist is None
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/").status_code == 404


def test_resolve_viewer_dist_rejects_packaged_dir_missing_index_and_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_viewer_env(monkeypatch)
    packaged = tmp_path / "package" / "_webui"
    packaged.mkdir(parents=True)
    repo_root = tmp_path / "repo"
    module_dist = _write_viewer_dist(repo_root)
    module_file = repo_root / "src" / "ahadiff" / "serve" / "static.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("# test module path\n", encoding="utf-8")
    _patch_packaged_webui(monkeypatch, packaged)
    _patch_module_file(monkeypatch, module_file)

    assert static_module._resolve_viewer_dist() == module_dist


def test_resolve_viewer_dist_ignores_non_filesystem_traversable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_viewer_env(monkeypatch)
    _patch_packaged_webui(monkeypatch, _NonFilesystemTraversable("multiplexed://ahadiff/_webui"))
    _patch_module_file(
        monkeypatch,
        tmp_path / "site-packages" / "ahadiff" / "serve" / "static.py",
    )

    assert static_module._resolve_viewer_dist() is None


def test_resolve_viewer_dist_prefers_valid_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_dist = tmp_path / "override"
    env_dist.mkdir()
    (env_dist / "index.html").write_text("<h1>override</h1>\n", encoding="utf-8")
    packaged = tmp_path / "package" / "_webui"
    packaged.mkdir(parents=True)
    (packaged / "index.html").write_text("<h1>packaged</h1>\n", encoding="utf-8")
    monkeypatch.setenv("AHADIFF_VIEWER_DIST", str(env_dist))
    _patch_packaged_webui(monkeypatch, packaged)

    assert static_module._resolve_viewer_dist() == env_dist


def test_resolve_viewer_dist_rejects_invalid_env_override_and_falls_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packaged = tmp_path / "package" / "_webui"
    packaged.mkdir(parents=True)
    (packaged / "index.html").write_text("<h1>packaged</h1>\n", encoding="utf-8")
    no_index = tmp_path / "no-index"
    no_index.mkdir()
    _patch_packaged_webui(monkeypatch, packaged)

    monkeypatch.setenv("AHADIFF_VIEWER_DIST", str(tmp_path / "missing"))
    assert static_module._resolve_viewer_dist() == packaged

    monkeypatch.setenv("AHADIFF_VIEWER_DIST", str(no_index))
    assert static_module._resolve_viewer_dist() == packaged


def test_resolve_viewer_dist_rejects_relative_env_override_from_served_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served_workspace = tmp_path / "served-workspace"
    _write_viewer_dist(served_workspace, "<h1>attacker ui</h1>\n")
    monkeypatch.chdir(served_workspace)
    monkeypatch.setenv("AHADIFF_VIEWER_DIST", "viewer/dist")
    _patch_packaged_webui(monkeypatch, tmp_path / "missing" / "_webui")
    _patch_module_file(
        monkeypatch,
        tmp_path / "site-packages" / "ahadiff" / "serve" / "static.py",
    )

    assert static_module._resolve_viewer_dist() is None


def test_spa_static_traversal_request_does_not_fall_back_to_index(tmp_path: Path) -> None:
    viewer_dist = tmp_path / "viewer" / "dist"
    viewer_dist.mkdir(parents=True)
    (viewer_dist / "index.html").write_text("<h1>AhaDiff</h1>\n", encoding="utf-8")
    app = create_app(
        ServeState(state_dir=tmp_path / ".ahadiff", token="test-token"),
        viewer_dist=viewer_dist,
    )
    client = TestClient(app, base_url="http://localhost:8765")

    response = client.get("/..%2f..%2fetc%2fpasswd")

    assert response.status_code == 404


def test_spa_static_backslash_traversal_request_does_not_fall_back_to_index(
    tmp_path: Path,
) -> None:
    viewer_dist = tmp_path / "viewer" / "dist"
    viewer_dist.mkdir(parents=True)
    (viewer_dist / "index.html").write_text("<h1>AhaDiff</h1>\n", encoding="utf-8")
    app = create_app(
        ServeState(state_dir=tmp_path / ".ahadiff", token="test-token"),
        viewer_dist=viewer_dist,
    )
    client = TestClient(app, base_url="http://localhost:8765")

    response = client.get("/..%5c..%5cetc%5cpasswd")

    assert response.status_code == 404


def test_tree_sitter_import_error_guard_still_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import_module = importlib.import_module

    def fake_import_module(name: str) -> Any:
        if name == "tree_sitter":
            raise ImportError("missing tree_sitter")
        return original_import_module(name)

    tree_sitter_runtime.reset_caches()
    monkeypatch.setattr(tree_sitter_runtime.importlib, "import_module", fake_import_module)

    try:
        result = tree_sitter_runtime.extract_tree_sitter_symbols(
            "src/widget.ts",
            "export const x = 1;\n",
        )

        assert result.records == ()
        assert result.available is False
        assert result.error == "tree_sitter runtime is not installed"
    finally:
        tree_sitter_runtime.reset_caches()


def test_watchdog_import_error_guard_still_reports_unavailable() -> None:
    with patch("importlib.util.find_spec", return_value=None):
        assert is_watchdog_available() is False


def test_genanki_import_error_guard_still_reports_install_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_import(name: str) -> object:
        assert name == "genanki"
        raise ImportError("missing genanki")

    monkeypatch.setattr(apkg_export, "import_module", fail_import)

    with pytest.raises(ImportError, match="genanki is required for .apkg export"):
        apkg_export.export_apkg(tmp_path / "review.sqlite")
