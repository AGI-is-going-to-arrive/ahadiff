from __future__ import annotations

import ast
from pathlib import Path
from typing import TypeGuard, get_type_hints

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src" / "ahadiff"
PYTHON_ROOTS = (SOURCE_ROOT, REPO_ROOT / "tests")


def test_src_ahadiff_does_not_use_datetime_utcnow() -> None:
    python_files = sorted(SOURCE_ROOT.rglob("*.py"))
    assert python_files, "expected src/ahadiff Python files to scan"

    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in python_files
        if "datetime.utcnow()" in path.read_text(encoding="utf-8")
    ]

    assert not offenders, (
        "datetime.utcnow() returns a naive datetime and is deprecated; "
        f"use datetime.now(UTC) instead. Offenders: {', '.join(offenders)}"
    )


def test_is_wsl2_mnt_only_matches_windows_drive_mounts() -> None:
    from ahadiff.core.paths import is_wsl2_mnt

    wsl_env = {"WSL_DISTRO_NAME": "Ubuntu"}

    assert is_wsl2_mnt(Path("/mnt/c/project"), platform="linux", env=wsl_env) is True
    assert is_wsl2_mnt(Path("/mnt/wsl/project"), platform="linux", env=wsl_env) is False
    assert is_wsl2_mnt(Path("/mnt/wslg/runtime"), platform="linux", env=wsl_env) is False
    assert is_wsl2_mnt(Path("/mnt/data/project"), platform="linux", env=wsl_env) is False
    assert is_wsl2_mnt(Path("/mnt/"), platform="linux", env=wsl_env) is False


def test_subprocess_run_text_true_sets_utf8_encoding() -> None:
    offenders: list[str] = []
    for root in PYTHON_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not _is_subprocess_run_with_text_true(node):
                    continue
                keywords = {keyword.arg for keyword in node.keywords if keyword.arg}
                missing = {"encoding", "errors"} - keywords
                if missing:
                    relative = path.relative_to(REPO_ROOT).as_posix()
                    missing_text = ", ".join(sorted(missing))
                    offenders.append(f"{relative}:{node.lineno} missing {missing_text}")

    assert not offenders, (
        "subprocess.run(text=True) must set encoding='utf-8' and errors='replace'. "
        f"Offenders: {'; '.join(offenders)}"
    )


def test_touched_runtime_annotations_are_resolvable() -> None:
    from ahadiff.git import capture as capture_module
    from ahadiff.git import download as download_module
    from ahadiff.git import repo as repo_module
    from ahadiff.llm import usage as usage_module
    from ahadiff.llm.schemas import CacheKeyInput, ProviderRequest
    from ahadiff.serve import routes_review as routes_review_module
    from ahadiff.serve import routes_runs as routes_runs_module
    from ahadiff.serve.state import ServeState

    targets = [
        CacheKeyInput,
        ProviderRequest,
        ServeState,
        capture_module.capture_patch,
        capture_module._run_git_patch_text,  # pyright: ignore[reportPrivateUsage]
        download_module.download_patch_url,
        repo_module.repo_write_lock,
        usage_module.connect_usage_db,
        routes_review_module._review_queue_sync,  # pyright: ignore[reportPrivateUsage]
        routes_runs_module._list_runs_payload,  # pyright: ignore[reportPrivateUsage]
    ]

    for target in targets:
        get_type_hints(target)


def _is_subprocess_run_with_text_true(node: ast.AST) -> TypeGuard[ast.Call]:
    if not isinstance(node, ast.Call):
        return False
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ):
        return False
    return any(
        keyword.arg == "text"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in node.keywords
    )
