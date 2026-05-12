"""Verify version numbers across pyproject.toml, __init__.py, uv.lock, and viewer/package.json are normalized-equivalent."""  # noqa: E501

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
PEP_PRERELEASE_RE = re.compile(r"^(?P<release>\d+(?:\.\d+)*)(?P<tag>a|b|rc)(?P<number>\d+)$")
SEMVER_RE = re.compile(r"^(?P<release>\d+(?:\.\d+)*)(?:-(?P<prerelease>[0-9A-Za-z.-]+))?$")
TAG_ALIASES = {
    "a": "alpha",
    "b": "beta",
    "rc": "rc",
}

TomlTable = dict[str, object]


def _read_toml(path: Path) -> TomlTable:
    with path.open("rb") as handle:
        return cast("TomlTable", tomllib.load(handle))


def _expect_table(value: object, name: str) -> TomlTable:
    assert isinstance(value, dict), f"{name} must be a TOML table"
    return cast("TomlTable", value)


def _expect_str(value: object, name: str) -> str:
    assert isinstance(value, str), f"{name} must be a string"
    return value


def _normalize_prerelease(parts: list[str]) -> str:
    expanded = [TAG_ALIASES.get(part, part) for part in parts]
    return "-".join(expanded)


def _normalize_version(version: str) -> str:
    version = version.removeprefix("v")
    pep_match = PEP_PRERELEASE_RE.fullmatch(version)
    if pep_match is not None:
        release = pep_match.group("release")
        prerelease = _normalize_prerelease([pep_match.group("tag"), pep_match.group("number")])
        return f"{release}-{prerelease}"

    semver_match = SEMVER_RE.fullmatch(version)
    assert semver_match is not None, f"unsupported version format: {version}"
    prerelease = semver_match.group("prerelease")
    if prerelease is None:
        return semver_match.group("release")
    return f"{semver_match.group('release')}-{_normalize_prerelease(re.split(r'[.-]', prerelease))}"


def _pyproject_version() -> str:
    pyproject = _read_toml(ROOT / "pyproject.toml")
    project = _expect_table(pyproject.get("project"), "pyproject.toml project")
    return _expect_str(project.get("version"), "pyproject.toml project.version")


def _init_version() -> str:
    init_path = ROOT / "src" / "ahadiff" / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__version__":
                value = ast.literal_eval(node.value)
                return _expect_str(value, "__version__")
    raise AssertionError("__version__ assignment not found")


def _uv_lock_version() -> str:
    lock = _read_toml(ROOT / "uv.lock")
    packages = lock.get("package")
    assert isinstance(packages, list), "uv.lock package list must be present"
    for package in cast("list[object]", packages):
        package_table = _expect_table(package, "uv.lock package")
        if package_table.get("name") == "ahadiff":
            return _expect_str(package_table.get("version"), "uv.lock ahadiff.version")
    raise AssertionError("ahadiff package not found in uv.lock")


def _viewer_package_version() -> str:
    package_json = cast(
        "dict[str, object]",
        json.loads((ROOT / "viewer" / "package.json").read_text(encoding="utf-8")),
    )
    return _expect_str(package_json.get("version"), "viewer package.json version")


def _viewer_sidebar_version() -> str:
    sidebar_path = ROOT / "viewer" / "src" / "components" / "Sidebar.tsx"
    match = re.search(
        r"const\s+VIEWER_VERSION\s*=\s*(['\"])(?P<version>[^'\"]+)\1",
        sidebar_path.read_text(encoding="utf-8"),
    )
    assert match is not None, "Sidebar VIEWER_VERSION constant not found"
    return match.group("version")


def test_versions_are_normalized_equivalent() -> None:
    versions = {
        "pyproject.toml": _pyproject_version(),
        "src/ahadiff/__init__.py": _init_version(),
        "uv.lock": _uv_lock_version(),
        "viewer/package.json": _viewer_package_version(),
        "viewer/src/components/Sidebar.tsx": _viewer_sidebar_version(),
    }
    normalized = {source: _normalize_version(version) for source, version in versions.items()}

    assert len(set(normalized.values())) == 1, {
        source: {"raw": versions[source], "normalized": normalized[source]}
        for source in sorted(versions)
    }
