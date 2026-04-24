from __future__ import annotations

import inspect
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

import ahadiff.install.hooks as hooks_module
from ahadiff.cli import app
from ahadiff.install.template_loader import render_template

if TYPE_CHECKING:
    import pytest

_RUNNER = CliRunner()


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True, text=True)


def _init_git_repo(repo_root: Path) -> None:
    _git(repo_root, "init", "-q")
    _git(repo_root, "config", "user.name", "AhaDiff Test")
    _git(repo_root, "config", "user.email", "test@example.com")


def test_install_dry_run_lists_v01_targets(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    for target in ("claude", "codex", "gemini", "opencode", "hooks"):
        result = _RUNNER.invoke(
            app(),
            ["install", target, "--repo-root", str(repo_root), "--dry-run"],
        )

        assert result.exit_code == 0
        assert "write" in result.output or "merge-section" in result.output

    assert not (repo_root / "AGENTS.md").exists()
    assert not (repo_root / ".claude").exists()


def test_install_templates_are_static_and_render_without_values() -> None:
    assert tuple(inspect.signature(render_template).parameters) == ("name",)
    templates_root = files("ahadiff.install.templates")
    for template in templates_root.iterdir():
        if not template.name.endswith(".j2"):
            continue
        template_text = template.read_text(encoding="utf-8")
        assert "[[" not in template_text
        assert "]]" not in template_text
        assert "{%" not in template_text
        assert "{#" not in template_text
        assert render_template(template.name)


def test_install_detect_reports_written_targets(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    install_result = _RUNNER.invoke(app(), ["install", "codex", "--repo-root", str(repo_root)])
    detect_result = _RUNNER.invoke(app(), ["install", "--detect", "--repo-root", str(repo_root)])

    assert install_result.exit_code == 0
    assert detect_result.exit_code == 0
    assert "codex" in detect_result.output
    assert "yes" in detect_result.output


def test_codex_install_merges_and_uninstalls_agents_section(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    agents_path = repo_root / "AGENTS.md"
    agents_path.write_text("Existing instructions\n", encoding="utf-8")

    install_result = _RUNNER.invoke(app(), ["install", "codex", "--repo-root", str(repo_root)])
    second_install = _RUNNER.invoke(app(), ["install", "codex", "--repo-root", str(repo_root)])
    installed_text = agents_path.read_text(encoding="utf-8")
    uninstall_result = _RUNNER.invoke(
        app(),
        ["uninstall", "codex", "--repo-root", str(repo_root)],
    )

    assert install_result.exit_code == 0
    assert second_install.exit_code == 0
    assert installed_text.count("AHADIFF:BEGIN target=codex") == 1
    assert uninstall_result.exit_code == 0
    assert agents_path.read_text(encoding="utf-8").strip() == "Existing instructions"


def test_uninstall_dry_run_previews_removals_without_mutating(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    install_result = _RUNNER.invoke(app(), ["install", "codex", "--repo-root", str(repo_root)])
    dry_run = _RUNNER.invoke(
        app(),
        ["uninstall", "codex", "--repo-root", str(repo_root), "--dry-run"],
    )

    assert install_result.exit_code == 0
    assert dry_run.exit_code == 0
    assert "Remove codex AhaDiff install artifacts." in dry_run.output
    assert "- remove: AGENTS.md" in dry_run.output
    assert "AHADIFF:BEGIN target=codex" in (repo_root / "AGENTS.md").read_text(encoding="utf-8")


def test_claude_install_writes_generated_skill_and_refuses_user_file(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    skill_path = repo_root / ".claude" / "skills" / "ahadiff" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("user managed\n", encoding="utf-8")

    denied = _RUNNER.invoke(app(), ["install", "claude", "--repo-root", str(repo_root)])
    forced = _RUNNER.invoke(
        app(),
        ["install", "claude", "--repo-root", str(repo_root), "--force"],
    )

    assert denied.exit_code == 1
    assert "refusing to overwrite" in denied.output
    assert forced.exit_code == 0
    assert "AHADIFF:GENERATED" in skill_path.read_text(encoding="utf-8")
    uninstalled = _RUNNER.invoke(app(), ["uninstall", "claude", "--repo-root", str(repo_root)])
    assert uninstalled.exit_code == 0
    assert not skill_path.exists()


def test_opencode_install_writes_agents_and_agent_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    result = _RUNNER.invoke(app(), ["install", "opencode", "--repo-root", str(repo_root)])

    assert result.exit_code == 0
    assert "AHADIFF:BEGIN target=opencode" in (repo_root / "AGENTS.md").read_text(encoding="utf-8")
    assert (repo_root / ".opencode" / "agents" / "ahadiff.md").exists()


def test_hooks_install_is_non_blocking_and_uninstall_removes_sections(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    result = _RUNNER.invoke(app(), ["install", "hooks", "--repo-root", str(repo_root)])
    post_commit = repo_root / ".git" / "hooks" / "post-commit"
    pre_push = repo_root / ".git" / "hooks" / "pre-push"

    assert result.exit_code == 0
    assert post_commit.read_text(encoding="utf-8").startswith("#!/bin/sh\n")
    assert "AHADIFF:BEGIN target=hooks" in post_commit.read_text(encoding="utf-8")
    assert "|| true" in pre_push.read_text(encoding="utf-8")
    assert "exit 0" not in pre_push.read_text(encoding="utf-8")
    assert post_commit.stat().st_mode & 0o111
    assert pre_push.stat().st_mode & 0o111
    pre_push.write_text(
        f"{pre_push.read_text(encoding='utf-8')}printf '%s\\n' after-ahadiff\n",
        encoding="utf-8",
    )
    hook_run = subprocess.run(
        [str(pre_push)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "after-ahadiff" in hook_run.stdout
    uninstall_result = _RUNNER.invoke(app(), ["uninstall", "hooks", "--repo-root", str(repo_root)])
    assert uninstall_result.exit_code == 0
    assert "AHADIFF:BEGIN target=hooks" not in post_commit.read_text(encoding="utf-8")


def test_hooks_install_rejects_windows_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    monkeypatch.setattr(hooks_module.sys, "platform", "win32")

    dry_run = _RUNNER.invoke(
        app(),
        ["install", "hooks", "--repo-root", str(repo_root), "--dry-run"],
    )
    result = _RUNNER.invoke(app(), ["install", "hooks", "--repo-root", str(repo_root)])

    assert dry_run.exit_code == 1
    assert result.exit_code == 1
    assert "POSIX-shell only in v0.1" in dry_run.output
    assert "Windows is not supported yet" in result.output
    assert not (repo_root / ".git" / "hooks" / "post-commit").exists()
    assert not (repo_root / ".git" / "hooks" / "pre-push").exists()


def test_hooks_install_supports_git_worktree(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    worktree_root = tmp_path / "worktree"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo_root, "add", "tracked.txt")
    _git(repo_root, "commit", "-m", "base")
    _git(repo_root, "worktree", "add", "-q", str(worktree_root), "-b", "install-worktree")

    result = _RUNNER.invoke(app(), ["install", "hooks", "--repo-root", str(worktree_root)])
    hook_path_result = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks/pre-push"],
        cwd=worktree_root,
        check=True,
        capture_output=True,
        text=True,
    )
    hook_path = Path(hook_path_result.stdout.strip())
    if not hook_path.is_absolute():
        hook_path = worktree_root / hook_path

    assert result.exit_code == 0
    assert "AHADIFF:BEGIN target=hooks" in hook_path.read_text(encoding="utf-8")
