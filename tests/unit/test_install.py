from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from ahadiff.cli import app

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
