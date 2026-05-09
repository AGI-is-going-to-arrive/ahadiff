from __future__ import annotations

import inspect
import json
import stat
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import ahadiff.install.hooks as hooks_module
from ahadiff.cli import app
from ahadiff.install.base import InstallContext
from ahadiff.install.template_loader import render_template

_RUNNER = CliRunner()
_V02_INSTALL_TARGET_CASES = (
    ("aider", "CONVENTIONS.md", "AHADIFF:BEGIN target=aider", False),
    ("cline", ".clinerules/ahadiff.md", "AHADIFF:GENERATED", True),
    ("continue", ".continue/rules/ahadiff.md", "AHADIFF:GENERATED", True),
    ("copilot", ".github/copilot-instructions.md", "AHADIFF:BEGIN target=copilot", False),
    ("cursor", ".cursor/rules/ahadiff.mdc", "AHADIFF:GENERATED", True),
    ("roo", ".roo/rules/ahadiff.md", "AHADIFF:GENERATED", True),
    ("windsurf", ".windsurf/rules/ahadiff.md", "AHADIFF:GENERATED", True),
)


def test_install_reexports_manifest_helpers() -> None:
    from ahadiff import install as install_package
    from ahadiff.install.base import (
        InstallFileStrategy as BaseInstallFileStrategy,
    )
    from ahadiff.install.base import (
        InstallManifest as BaseInstallManifest,
    )
    from ahadiff.install.common import manifest_preview_for as common_manifest_preview_for

    assert install_package.InstallManifest is BaseInstallManifest
    assert install_package.InstallFileStrategy == BaseInstallFileStrategy
    assert install_package.manifest_preview_for is common_manifest_preview_for


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


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


@pytest.mark.parametrize(
    ("target", "relative_path", "marker", "generated"),
    _V02_INSTALL_TARGET_CASES,
)
def test_v02_install_targets_write_detect_and_uninstall(
    tmp_path: Path,
    target: str,
    relative_path: str,
    marker: str,
    generated: bool,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    target_path = repo_root / relative_path

    install_result = _RUNNER.invoke(app(), ["install", target, "--repo-root", str(repo_root)])
    second_install = _RUNNER.invoke(app(), ["install", target, "--repo-root", str(repo_root)])
    detect_result = _RUNNER.invoke(app(), ["install", "--detect", "--repo-root", str(repo_root)])

    assert install_result.exit_code == 0, install_result.output
    assert second_install.exit_code == 0, second_install.output
    assert target_path.exists()
    assert marker in target_path.read_text(encoding="utf-8")
    assert detect_result.exit_code == 0, detect_result.output
    assert target in detect_result.output
    assert "yes" in detect_result.output

    uninstall_result = _RUNNER.invoke(
        app(),
        ["uninstall", target, "--repo-root", str(repo_root)],
    )

    assert uninstall_result.exit_code == 0, uninstall_result.output
    if generated:
        assert not target_path.exists()
    else:
        assert marker not in target_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("target", tuple(case[0] for case in _V02_INSTALL_TARGET_CASES))
def test_v02_install_targets_are_available_in_help(target: str) -> None:
    result = _RUNNER.invoke(app(), ["install", target, "--help"])

    assert result.exit_code == 0, result.output
    assert target in result.output


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


def test_install_manifest_preview_lists_file_strategies(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    result = _RUNNER.invoke(
        app(),
        ["install", "claude", "--repo-root", str(repo_root), "--manifest"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["target"] == "claude"
    assert payload["actions"]["preview"] == [
        {
            "action": "write",
            "file_strategy": "generated",
            "path": ".claude/skills/ahadiff/SKILL.md",
        },
        {"action": "merge-section", "file_strategy": "user-managed", "path": "CLAUDE.md"},
    ]
    assert payload["actions"]["write"] == payload["actions"]["preview"]
    assert payload["actions"]["uninstall"] == [
        {
            "action": "remove",
            "file_strategy": "generated",
            "path": ".claude/skills/ahadiff/SKILL.md",
        },
        {"action": "remove-section", "file_strategy": "user-managed", "path": "CLAUDE.md"},
    ]
    assert not (repo_root / ".claude").exists()
    assert not (repo_root / "CLAUDE.md").exists()

    github_result = _RUNNER.invoke(
        app(),
        ["install", "github-action", "--repo-root", str(repo_root), "--manifest"],
    )

    assert github_result.exit_code == 0
    github_payload = json.loads(github_result.output)
    assert github_payload["actions"]["uninstall"] == [
        {
            "action": "remove",
            "file_strategy": "generated",
            "path": ".github/workflows/ahadiff-verify.yml",
        },
        {
            "action": "remove",
            "file_strategy": "generated",
            "path": ".github/workflows/ahadiff-generate.yml",
        },
    ]


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


def test_codex_install_refuses_agents_symlink(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    outside_path = tmp_path / "outside-agents.md"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    outside_path.write_text("outside\n", encoding="utf-8")
    try:
        (repo_root / "AGENTS.md").symlink_to(outside_path)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    result = _RUNNER.invoke(app(), ["install", "codex", "--repo-root", str(repo_root)])

    assert result.exit_code != 0
    assert (repo_root / "AGENTS.md").is_symlink()
    assert outside_path.read_text(encoding="utf-8") == "outside\n"


def test_claude_install_refuses_generated_parent_symlink(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    outside_dir = tmp_path / "outside-claude"
    repo_root.mkdir()
    outside_dir.mkdir()
    _init_git_repo(repo_root)
    try:
        (repo_root / ".claude").symlink_to(outside_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    result = _RUNNER.invoke(app(), ["install", "claude", "--repo-root", str(repo_root)])

    assert result.exit_code != 0
    assert (repo_root / ".claude").is_symlink()
    assert not (outside_dir / "skills" / "ahadiff" / "SKILL.md").exists()


def test_claude_install_refuses_existing_symlinked_parent_chain(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    outside_dir = tmp_path / "outside-claude"
    repo_root.mkdir()
    (outside_dir / "skills" / "ahadiff").mkdir(parents=True)
    _init_git_repo(repo_root)
    try:
        (repo_root / ".claude").symlink_to(outside_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    result = _RUNNER.invoke(app(), ["install", "claude", "--repo-root", str(repo_root)])

    assert result.exit_code != 0
    assert (repo_root / ".claude").is_symlink()
    assert not (outside_dir / "skills" / "ahadiff" / "SKILL.md").exists()


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
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert "after-ahadiff" in hook_run.stdout
    uninstall_result = _RUNNER.invoke(app(), ["uninstall", "hooks", "--repo-root", str(repo_root)])
    assert uninstall_result.exit_code == 0
    assert "AHADIFF:BEGIN target=hooks" not in post_commit.read_text(encoding="utf-8")


def test_append_hook_section_preserves_existing_hook_mode(tmp_path: Path) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_path = hooks_dir / "post-commit"
    hook_path.write_text("#!/bin/sh\nprintf 'existing'\n", encoding="utf-8")
    hook_path.chmod(0o750)

    hooks_module._append_hook_section(  # pyright: ignore[reportPrivateUsage]
        hook_path,
        "hooks",
        "# AHADIFF:BEGIN target=hooks\necho hi\n# AHADIFF:END\n",
    )

    assert stat.S_IMODE(hook_path.stat().st_mode) == 0o750
    assert "echo hi" in hook_path.read_text(encoding="utf-8")


def test_append_hook_section_rejects_symlink_hook_path(tmp_path: Path) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_path = hooks_dir / "post-commit"
    linked_target = tmp_path / "real-post-commit"
    linked_target.write_text("#!/bin/sh\nprintf 'linked'\n", encoding="utf-8")
    try:
        hook_path.symlink_to(linked_target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(OSError, match="refusing to follow git hook symlink"):
        hooks_module._append_hook_section(  # pyright: ignore[reportPrivateUsage]
            hook_path,
            "hooks",
            "# AHADIFF:BEGIN target=hooks\necho hi\n# AHADIFF:END\n",
        )

    assert hook_path.is_symlink()
    assert linked_target.read_text(encoding="utf-8") == "#!/bin/sh\nprintf 'linked'\n"


def test_append_hook_section_does_not_follow_legacy_predictable_temp_symlink(
    tmp_path: Path,
) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_path = hooks_dir / "post-commit"
    victim_path = tmp_path / "victim.txt"
    victim_path.write_text("victim\n", encoding="utf-8")
    try:
        (hooks_dir / ".post-commit.ahadiff.tmp").symlink_to(victim_path)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    hooks_module._append_hook_section(  # pyright: ignore[reportPrivateUsage]
        hook_path,
        "hooks",
        "# AHADIFF:BEGIN target=hooks\necho hi\n# AHADIFF:END\n",
    )

    assert "echo hi" in hook_path.read_text(encoding="utf-8")
    assert victim_path.read_text(encoding="utf-8") == "victim\n"


def test_remove_hook_section_does_not_follow_legacy_predictable_temp_symlink(
    tmp_path: Path,
) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_path = hooks_dir / "pre-push"
    hook_path.write_text(
        "#!/bin/sh\n\n# AHADIFF:BEGIN target=hooks\necho hi\n# AHADIFF:END\n\nprintf 'after'\n",
        encoding="utf-8",
    )
    victim_path = tmp_path / "victim.txt"
    victim_path.write_text("victim\n", encoding="utf-8")
    try:
        (hooks_dir / ".pre-push.ahadiff.tmp").symlink_to(victim_path)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    assert hooks_module._remove_hook_section(hook_path, "hooks") is True  # pyright: ignore[reportPrivateUsage]
    assert "AHADIFF:BEGIN target=hooks" not in hook_path.read_text(encoding="utf-8")
    assert victim_path.read_text(encoding="utf-8") == "victim\n"


def test_remove_hook_section_rejects_symlink_hook_path(tmp_path: Path) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_path = hooks_dir / "pre-push"
    linked_target = tmp_path / "real-pre-push"
    linked_target.write_text(
        "#!/bin/sh\n\n# AHADIFF:BEGIN target=hooks\necho hi\n# AHADIFF:END\n",
        encoding="utf-8",
    )
    try:
        hook_path.symlink_to(linked_target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(OSError, match="refusing to follow git hook symlink"):
        hooks_module._remove_hook_section(hook_path, "hooks")  # pyright: ignore[reportPrivateUsage]

    assert hook_path.is_symlink()
    assert "AHADIFF:BEGIN target=hooks" in linked_target.read_text(encoding="utf-8")


def test_hooks_git_path_uses_utf8_when_cjk_locale_would_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    calls: dict[str, Any] = {}
    stdout_bytes = ".git/hooks/预推送😀\n".encode()

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls["command"] = command
        calls["kwargs"] = kwargs
        if kwargs.get("encoding") != "utf-8":
            stdout_bytes.decode("cp936")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr="",
        )

    monkeypatch.setattr(hooks_module.subprocess, "run", fake_run)

    hook_path = hooks_module._git_path(  # pyright: ignore[reportPrivateUsage]
        InstallContext(repo_root=repo_root),
        "hooks/pre-push",
    )

    assert calls["command"] == ["git", "rev-parse", "--git-path", "hooks/pre-push"]
    assert calls["kwargs"]["text"] is True
    assert calls["kwargs"]["encoding"] == "utf-8"
    assert calls["kwargs"]["errors"] == "replace"
    assert hook_path == repo_root / ".git" / "hooks" / "预推送😀"


def test_hooks_install_rejects_hooks_path_outside_repo_or_git_dir(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    outside_hooks = tmp_path / "outside-hooks"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    _git(repo_root, "config", "core.hooksPath", "../outside-hooks")

    result = _RUNNER.invoke(app(), ["install", "hooks", "--repo-root", str(repo_root)])

    assert result.exit_code == 1
    assert "repository root or git directory" in " ".join(result.output.split())
    assert not (outside_hooks / "post-commit").exists()
    assert not (outside_hooks / "pre-push").exists()


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
    manifest = _RUNNER.invoke(
        app(),
        ["install", "hooks", "--repo-root", str(repo_root), "--manifest"],
    )
    detect = _RUNNER.invoke(app(), ["install", "--detect", "--repo-root", str(repo_root)])
    uninstall_dry_run = _RUNNER.invoke(
        app(),
        ["uninstall", "hooks", "--repo-root", str(repo_root), "--dry-run"],
    )
    result = _RUNNER.invoke(app(), ["install", "hooks", "--repo-root", str(repo_root)])

    for failed in (dry_run, manifest, uninstall_dry_run, result):
        assert failed.exit_code == 1
        assert "v0.1 does not support Windows hooks" in failed.output
    assert detect.exit_code == 0
    assert "hooks" in detect.output
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
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    hook_path = Path(hook_path_result.stdout.strip())
    if not hook_path.is_absolute():
        hook_path = worktree_root / hook_path

    assert result.exit_code == 0
    assert "AHADIFF:BEGIN target=hooks" in hook_path.read_text(encoding="utf-8")


def test_hooks_detect_handles_oserror_gracefully(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    context = InstallContext(repo_root=repo_root)
    from unittest.mock import patch

    from ahadiff.install.hooks import HooksTarget

    target = HooksTarget()

    with (
        patch.object(Path, "read_text", side_effect=OSError("permission denied")),
        patch.object(Path, "exists", return_value=True),
    ):
        assert target.detect(context) is False
