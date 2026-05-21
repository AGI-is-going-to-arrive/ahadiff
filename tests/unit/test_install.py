from __future__ import annotations

import inspect
import json
import stat
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

import ahadiff.install.hooks as hooks_module
from ahadiff.cli import app
from ahadiff.core.errors import InputError
from ahadiff.install.base import InstallContext
from ahadiff.install.registry import get_target, target_detection
from ahadiff.install.template_loader import render_template

_RUNNER = CliRunner()
_INSTALL_TEMPLATE_NAMES = (
    "agents_section.md.j2",
    "ahadiff-generate.yml.j2",
    "ahadiff-verify.yml.j2",
    "aider_section.md.j2",
    "antigravity_cli_skill.md.j2",
    "antigravity_rule.md.j2",
    "antigravity_skill.md.j2",
    "claude_section.md.j2",
    "claude_skill.md.j2",
    "cline_rules.md.j2",
    "codex_skill.md.j2",
    "continue_rule.md.j2",
    "copilot_instruction.md.j2",
    "copilot_section.md.j2",
    "cursor_rule.mdc.j2",
    "gemini_section.md.j2",
    "gemini_skill.md.j2",
    "opencode_agent.md.j2",
    "post_commit_hook.sh.j2",
    "pre_push_hook.sh.j2",
    "roo_rules.md.j2",
    "windsurf_rule.md.j2",
)
_SKILL_TEMPLATE_NAMES = (
    "claude_skill.md.j2",
    "antigravity_cli_skill.md.j2",
    "antigravity_skill.md.j2",
    "codex_skill.md.j2",
    "gemini_skill.md.j2",
    "opencode_agent.md.j2",
)
_SECTION_TEMPLATE_NAMES = (
    "claude_section.md.j2",
    "agents_section.md.j2",
    "gemini_section.md.j2",
    "aider_section.md.j2",
    "copilot_section.md.j2",
)
_STANDARD_BOUNDARY_PHRASES = (
    "Keep provider credentials in environment variables",
    "Do not commit `.ahadiff/audit.private.jsonl`",
    "Treat `.ahadiff/` as local state",
    "Prefer verified claims with file-line evidence",
    "Do not upload `.ahadiff/` artifacts to external services without explicit user consent",
)
_SKILL_CORE_COMMANDS = (
    "`ahadiff learn HEAD~1..HEAD`",
    "`ahadiff quiz <run_id>`",
    "`ahadiff review`",
    "`ahadiff verify <run_id>`",
    "`ahadiff improve --rounds 1`",
    "`ahadiff serve`",
    "`ahadiff init`",
)
_SKILL_CAPTURE_COMMANDS = (
    "`ahadiff learn --last`",
    '`ahadiff learn --since "2 hours ago"`',
    "`ahadiff learn --unstaged`",
    "`ahadiff learn --patch FILE|-`",
    "`ahadiff learn --compare PATH1 PATH2`",
    "`ahadiff learn --compare-dir DIR1 DIR2`",
    "`ahadiff learn --patch-url URL`",
    "`ahadiff learn --against-spec PATH`",
    "`ahadiff learn --changed-path PATH`",
)
_SKILL_CURATED_ADVANCED_COMMANDS = (
    "`ahadiff doctor`",
    "`ahadiff config show --resolved`",
    "`ahadiff watch`",
    "`ahadiff export preview RUN_ID --out PATH`",
    "`ahadiff export-results`",
    "`ahadiff mcp-server`",
    "`ahadiff install --detect`",
    "`ahadiff graph status`",
    "`ahadiff graph import`",
    "`ahadiff graph refresh`",
    "`ahadiff concepts list`",
    "`ahadiff concepts verify`",
    "`ahadiff concepts lint`",
)
_SECTION_CAPTURE_COMMANDS = (
    "`ahadiff learn --last`",
    '`ahadiff learn --since "2 hours ago"`',
)
_TEMPLATE_CLI_HELP_CHECKS = (
    (
        ("--help",),
        (
            "init",
            "learn",
            "quiz",
            "review",
            "verify",
            "improve",
            "serve",
            "watch",
            "export-results",
        ),
    ),
    (
        ("learn", "--help"),
        (
            "--last",
            "--since",
            "--staged",
            "--unstaged",
            "--patch",
            "--compare",
            "--compare-dir",
            "--patch-url",
            "--against-spec",
            "--changed-path",
        ),
    ),
    (("improve", "--help"), ("--rounds",)),
    (("install", "--help"), ("--detect", "--dry-run")),
    (("export", "preview", "--help"), ("RUN_ID", "--out")),
    (("graph", "--help"), ("status", "import", "refresh")),
    (("concepts", "--help"), ("list", "verify", "lint")),
    (("mcp-server", "--help"), ("--repo-root",)),
)
_V02_INSTALL_TARGET_CASES = (
    ("aider", "CONVENTIONS.md", "AHADIFF:BEGIN target=aider", False),
    (
        "antigravity",
        ".agents/skills/ahadiff-antigravity/SKILL.md",
        "AHADIFF:GENERATED",
        True,
    ),
    (
        "antigravity-cli",
        ".agents/skills/ahadiff-antigravity-cli/SKILL.md",
        "AHADIFF:GENERATED",
        True,
    ),
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


def test_install_dry_run_lists_workspace_targets(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    dry_run_targets = {
        "antigravity": (
            ".agents/skills/ahadiff-antigravity/SKILL.md",
            ".agents/rules/ahadiff.md",
        ),
        "antigravity-cli": (
            ".agents/skills/ahadiff-antigravity-cli/SKILL.md",
            "GEMINI.md",
        ),
        "claude": (".claude/skills/ahadiff/SKILL.md", "CLAUDE.md"),
        "codex": (".agents/skills/ahadiff/SKILL.md", "AGENTS.md"),
        "gemini": (".gemini/skills/ahadiff/SKILL.md", "GEMINI.md"),
        "opencode": (".opencode/agents/ahadiff.md", "AGENTS.md"),
        "hooks": (".git/hooks/post-commit", ".git/hooks/pre-push"),
    }
    for target in dry_run_targets:
        result = _RUNNER.invoke(
            app(),
            ["install", target, "--repo-root", str(repo_root), "--dry-run"],
        )

        assert result.exit_code == 0
        assert "write" in result.output or "merge-section" in result.output

    assert not (repo_root / "AGENTS.md").exists()
    assert not (repo_root / ".claude").exists()
    for paths in dry_run_targets.values():
        for relative_path in paths:
            assert not (repo_root / relative_path).exists()


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
    assert sorted(
        template.name for template in templates_root.iterdir() if template.name.endswith(".j2")
    ) == sorted(_INSTALL_TEMPLATE_NAMES)
    for template in templates_root.iterdir():
        if not template.name.endswith(".j2"):
            continue
        template_text = template.read_text(encoding="utf-8")
        assert "[[" not in template_text
        assert "]]" not in template_text
        assert "{%" not in template_text
        assert "{#" not in template_text
        rendered = render_template(template.name)
        assert rendered
        if template.name.endswith(".yml.j2"):
            payload = yaml.safe_load(rendered)
            assert isinstance(payload, dict)
            assert "on" in payload
            assert True not in payload


@pytest.mark.parametrize("template_name", _INSTALL_TEMPLATE_NAMES)
def test_install_templates_use_standard_boundaries(template_name: str) -> None:
    rendered = render_template(template_name)

    assert "Boundaries" in rendered
    for phrase in _STANDARD_BOUNDARY_PHRASES:
        assert phrase in rendered


@pytest.mark.parametrize("template_name", _SKILL_TEMPLATE_NAMES)
def test_skill_templates_document_curated_safe_cli_surface(template_name: str) -> None:
    rendered = render_template(template_name)

    for heading in ("## Core Commands", "### Additional Capture Modes", "## Advanced"):
        assert heading in rendered
    assert "`ahadiff learn --staged`" in rendered
    for command in (
        _SKILL_CORE_COMMANDS + _SKILL_CAPTURE_COMMANDS + _SKILL_CURATED_ADVANCED_COMMANDS
    ):
        assert command in rendered
    for maintenance_command in (
        "`ahadiff db restore PATH/TO/review.sqlite.bak`",
        "`ahadiff unlock --force`",
        "`ahadiff mark CLAIM_ID wrong`",
    ):
        assert maintenance_command not in rendered


@pytest.mark.parametrize(("args", "snippets"), _TEMPLATE_CLI_HELP_CHECKS)
def test_skill_template_curated_commands_match_cli_help(
    args: tuple[str, ...],
    snippets: tuple[str, ...],
) -> None:
    result = _RUNNER.invoke(app(), list(args))

    assert result.exit_code == 0, result.output
    for snippet in snippets:
        assert snippet in result.output


@pytest.mark.parametrize("template_name", _SECTION_TEMPLATE_NAMES)
def test_section_templates_include_curated_learn_capture_modes(template_name: str) -> None:
    rendered = render_template(template_name)

    for command in _SECTION_CAPTURE_COMMANDS:
        assert command in rendered


def test_claude_skill_frontmatter_lists_safe_tools() -> None:
    rendered = render_template("claude_skill.md.j2")

    assert "allowed-tools: Read, Grep, Bash" in rendered


def test_opencode_agent_frontmatter_names_ahadiff_agent() -> None:
    rendered = render_template("opencode_agent.md.j2")

    assert "name: ahadiff" in rendered


def test_agents_section_notes_shared_codex_opencode_usage() -> None:
    rendered = render_template("agents_section.md.j2")

    assert "This section is shared by Codex CLI and OpenCode" in rendered


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


def test_install_detect_isolates_unreadable_target_files(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    outside_path = tmp_path / "outside-agents.md"
    repo_root.mkdir()
    outside_path.write_text("outside\n", encoding="utf-8")
    _init_git_repo(repo_root)
    try:
        (repo_root / "AGENTS.md").symlink_to(outside_path)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    detections = target_detection(InstallContext(repo_root=repo_root))
    detect_result = _RUNNER.invoke(app(), ["install", "--detect", "--repo-root", str(repo_root)])

    assert detections["codex"] is False
    assert detections["antigravity"] is False
    assert detect_result.exit_code == 0, detect_result.output
    assert "codex" in detect_result.output


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

    codex_result = _RUNNER.invoke(
        app(),
        ["install", "codex", "--repo-root", str(repo_root), "--manifest"],
    )

    assert codex_result.exit_code == 0
    codex_payload = json.loads(codex_result.output)
    assert codex_payload["actions"]["preview"] == [
        {
            "action": "write",
            "file_strategy": "generated",
            "path": ".agents/skills/ahadiff/SKILL.md",
        },
        {"action": "merge-section", "file_strategy": "user-managed", "path": "AGENTS.md"},
    ]
    assert codex_payload["actions"]["uninstall"] == [
        {
            "action": "remove",
            "file_strategy": "generated",
            "path": ".agents/skills/ahadiff/SKILL.md",
        },
        {"action": "remove-section", "file_strategy": "user-managed", "path": "AGENTS.md"},
    ]

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


def test_claude_install_creates_missing_claude_file_and_skill(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    install_result = _RUNNER.invoke(app(), ["install", "claude", "--repo-root", str(repo_root)])

    assert install_result.exit_code == 0, install_result.output
    claude_path = repo_root / "CLAUDE.md"
    skill_path = repo_root / ".claude" / "skills" / "ahadiff" / "SKILL.md"
    assert "AHADIFF:BEGIN target=claude" in claude_path.read_text(encoding="utf-8")
    assert "<!-- AHADIFF:GENERATED -->" in skill_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("target", "section_path", "generated_path", "section_marker", "generated_heading"),
    (
        (
            "codex",
            "AGENTS.md",
            ".agents/skills/ahadiff/SKILL.md",
            "AHADIFF:BEGIN target=codex",
            "Codex",
        ),
        (
            "gemini",
            "GEMINI.md",
            ".gemini/skills/ahadiff/SKILL.md",
            "AHADIFF:BEGIN target=gemini",
            "Gemini",
        ),
        (
            "copilot",
            ".github/copilot-instructions.md",
            ".github/instructions/ahadiff.instructions.md",
            "AHADIFF:BEGIN target=copilot",
            "AhaDiff",
        ),
        (
            "antigravity-cli",
            "GEMINI.md",
            ".agents/skills/ahadiff-antigravity-cli/SKILL.md",
            "AHADIFF:BEGIN target=antigravity-cli",
            "Antigravity CLI",
        ),
    ),
)
def test_workspace_install_targets_write_detect_and_uninstall_generated_skills(
    tmp_path: Path,
    target: str,
    section_path: str,
    generated_path: str,
    section_marker: str,
    generated_heading: str,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    user_managed_path = repo_root / section_path
    generated_file_path = repo_root / generated_path

    install_result = _RUNNER.invoke(app(), ["install", target, "--repo-root", str(repo_root)])
    second_install = _RUNNER.invoke(app(), ["install", target, "--repo-root", str(repo_root)])
    detect_result = _RUNNER.invoke(app(), ["install", "--detect", "--repo-root", str(repo_root)])

    assert install_result.exit_code == 0, install_result.output
    assert second_install.exit_code == 0, second_install.output
    assert user_managed_path.exists()
    assert generated_file_path.exists()
    generated_text = generated_file_path.read_text(encoding="utf-8")
    assert "AHADIFF:GENERATED" in generated_text
    assert generated_heading in generated_text
    assert section_marker in user_managed_path.read_text(encoding="utf-8")
    assert detect_result.exit_code == 0, detect_result.output
    assert target in detect_result.output
    assert "yes" in detect_result.output

    uninstall_result = _RUNNER.invoke(
        app(),
        ["uninstall", target, "--repo-root", str(repo_root)],
    )
    assert uninstall_result.exit_code == 0, uninstall_result.output
    assert not generated_file_path.exists()
    assert section_marker not in user_managed_path.read_text(encoding="utf-8")
    assert get_target(target).detect(InstallContext(repo_root=repo_root)) is False


@pytest.mark.parametrize(
    ("target", "section_path", "generated_path", "section_marker"),
    (
        ("codex", "AGENTS.md", ".agents/skills/ahadiff/SKILL.md", "codex"),
        ("gemini", "GEMINI.md", ".gemini/skills/ahadiff/SKILL.md", "gemini"),
        (
            "antigravity-cli",
            "GEMINI.md",
            ".agents/skills/ahadiff-antigravity-cli/SKILL.md",
            "antigravity-cli",
        ),
        (
            "copilot",
            ".github/copilot-instructions.md",
            ".github/instructions/ahadiff.instructions.md",
            "copilot",
        ),
    ),
)
def test_workspace_install_targets_detect_section_or_generated_file_only(
    tmp_path: Path,
    target: str,
    section_path: str,
    generated_path: str,
    section_marker: str,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    context = InstallContext(repo_root=repo_root)
    install_target = get_target(target)

    section_file = repo_root / section_path
    section_file.parent.mkdir(parents=True, exist_ok=True)
    section_file.write_text(
        f"before\n\n<!-- AHADIFF:BEGIN target={section_marker} -->\nbody\n<!-- AHADIFF:END -->\n",
        encoding="utf-8",
    )
    assert install_target.detect(context) is True

    section_file.unlink()
    generated_file = repo_root / generated_path
    generated_file.parent.mkdir(parents=True, exist_ok=True)
    template_name = (
        "copilot_instruction.md.j2"
        if target == "copilot"
        else f"{target.replace('-', '_')}_skill.md.j2"
    )
    generated_file.write_text(render_template(template_name), encoding="utf-8")

    assert install_target.detect(context) is True


def test_antigravity_detects_rule_or_workspace_skill_only(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    context = InstallContext(repo_root=repo_root)
    install_target = get_target("antigravity")

    rule_path = repo_root / ".agents" / "rules" / "ahadiff.md"
    rule_path.parent.mkdir(parents=True)
    rule_path.write_text(render_template("antigravity_rule.md.j2"), encoding="utf-8")
    assert install_target.detect(context) is True

    rule_path.unlink()
    skill_path = repo_root / ".agents" / "skills" / "ahadiff-antigravity" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(render_template("antigravity_skill.md.j2"), encoding="utf-8")
    assert install_target.detect(context) is True


@pytest.mark.parametrize(
    ("target", "generated_path"),
    (
        ("antigravity", ".agents/skills/ahadiff-antigravity/SKILL.md"),
        ("antigravity-cli", ".agents/skills/ahadiff-antigravity-cli/SKILL.md"),
        ("codex", ".agents/skills/ahadiff/SKILL.md"),
        ("gemini", ".gemini/skills/ahadiff/SKILL.md"),
        ("copilot", ".github/instructions/ahadiff.instructions.md"),
    ),
)
def test_workspace_install_targets_refuse_user_file_with_incidental_generated_token(
    tmp_path: Path,
    target: str,
    generated_path: str,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    generated_file = repo_root / generated_path
    generated_file.parent.mkdir(parents=True)
    generated_file.write_text(
        "# User-managed instructions\n\nThis file mentions AHADIFF:GENERATED in prose.\n",
        encoding="utf-8",
    )

    denied = _RUNNER.invoke(app(), ["install", target, "--repo-root", str(repo_root)])
    uninstall = _RUNNER.invoke(app(), ["uninstall", target, "--repo-root", str(repo_root)])

    assert denied.exit_code == 1
    assert "refusing to overwrite" in denied.output
    assert uninstall.exit_code == 0, uninstall.output
    assert generated_file.exists()
    assert generated_file.read_text(encoding="utf-8").startswith("# User-managed")

    forced = _RUNNER.invoke(app(), ["install", target, "--repo-root", str(repo_root), "--force"])

    assert forced.exit_code == 0, forced.output
    assert "<!-- AHADIFF:GENERATED -->" in generated_file.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("target", "symlink_name", "outside_generated_path"),
    (
        ("antigravity", ".agents", "skills/ahadiff-antigravity/SKILL.md"),
        ("antigravity-cli", ".agents", "skills/ahadiff-antigravity-cli/SKILL.md"),
        ("codex", ".agents", "skills/ahadiff/SKILL.md"),
        ("gemini", ".gemini", "skills/ahadiff/SKILL.md"),
        ("copilot", ".github", "instructions/ahadiff.instructions.md"),
    ),
)
def test_workspace_install_targets_do_not_detect_generated_file_through_symlink_parent(
    tmp_path: Path,
    target: str,
    symlink_name: str,
    outside_generated_path: str,
) -> None:
    repo_root = tmp_path / "repo"
    outside_dir = tmp_path / "outside"
    repo_root.mkdir()
    outside_file = outside_dir / outside_generated_path
    outside_file.parent.mkdir(parents=True)
    outside_file.write_text("<!-- AHADIFF:GENERATED -->\n# Outside\n", encoding="utf-8")
    _init_git_repo(repo_root)
    try:
        (repo_root / symlink_name).symlink_to(outside_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    assert get_target(target).detect(InstallContext(repo_root=repo_root)) is False


def test_antigravity_rule_is_isolated_from_codex_skill(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    codex_install = _RUNNER.invoke(app(), ["install", "codex", "--repo-root", str(repo_root)])
    antigravity_install = _RUNNER.invoke(
        app(),
        ["install", "antigravity", "--repo-root", str(repo_root)],
    )

    assert codex_install.exit_code == 0, codex_install.output
    assert antigravity_install.exit_code == 0, antigravity_install.output
    context = InstallContext(repo_root=repo_root)
    assert get_target("codex").detect(context) is True
    assert get_target("antigravity").detect(context) is True

    uninstall_antigravity = _RUNNER.invoke(
        app(),
        ["uninstall", "antigravity", "--repo-root", str(repo_root)],
    )

    assert uninstall_antigravity.exit_code == 0, uninstall_antigravity.output
    assert not (repo_root / ".agents" / "rules" / "ahadiff.md").exists()
    assert not (repo_root / ".agents" / "skills" / "ahadiff-antigravity" / "SKILL.md").exists()
    assert (repo_root / ".agents" / "skills" / "ahadiff" / "SKILL.md").exists()
    assert "AHADIFF:BEGIN target=codex" in (repo_root / "AGENTS.md").read_text(encoding="utf-8")
    assert get_target("codex").detect(context) is True
    assert get_target("antigravity").detect(context) is False


def test_antigravity_cli_marker_coexists_with_gemini_marker(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    gemini_install = _RUNNER.invoke(app(), ["install", "gemini", "--repo-root", str(repo_root)])
    antigravity_cli_install = _RUNNER.invoke(
        app(),
        ["install", "antigravity-cli", "--repo-root", str(repo_root)],
    )

    assert gemini_install.exit_code == 0, gemini_install.output
    assert antigravity_cli_install.exit_code == 0, antigravity_cli_install.output
    gemini_text = (repo_root / "GEMINI.md").read_text(encoding="utf-8")
    assert gemini_text.count("AHADIFF:BEGIN target=gemini") == 1
    assert gemini_text.count("AHADIFF:BEGIN target=antigravity-cli") == 1
    context = InstallContext(repo_root=repo_root)
    assert get_target("gemini").detect(context) is True
    assert get_target("antigravity-cli").detect(context) is True

    uninstall_antigravity_cli = _RUNNER.invoke(
        app(),
        ["uninstall", "antigravity-cli", "--repo-root", str(repo_root)],
    )

    assert uninstall_antigravity_cli.exit_code == 0, uninstall_antigravity_cli.output
    remaining_text = (repo_root / "GEMINI.md").read_text(encoding="utf-8")
    assert "AHADIFF:BEGIN target=gemini" in remaining_text
    assert "AHADIFF:BEGIN target=antigravity-cli" not in remaining_text
    assert not (repo_root / ".agents" / "skills" / "ahadiff-antigravity-cli" / "SKILL.md").exists()
    assert (repo_root / ".gemini" / "skills" / "ahadiff" / "SKILL.md").exists()
    assert get_target("gemini").detect(context) is True
    assert get_target("antigravity-cli").detect(context) is False


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

    assert len(calls["command"]) == 4
    assert Path(calls["command"][0]).name in {"git", "git.exe"}
    assert calls["command"][1:] == ["rev-parse", "--git-path", "hooks/pre-push"]
    assert calls["kwargs"]["text"] is True
    assert calls["kwargs"]["encoding"] == "utf-8"
    assert calls["kwargs"]["errors"] == "replace"
    assert calls["kwargs"]["timeout"] == 30
    assert hook_path == repo_root / ".git" / "hooks" / "预推送😀"


def test_hooks_git_path_preserves_legitimate_spaces_before_newline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=".git/hooks/pre push \n",
            stderr="",
        )

    monkeypatch.setattr(hooks_module.subprocess, "run", fake_run)

    hook_path = hooks_module._git_path(  # pyright: ignore[reportPrivateUsage]
        InstallContext(repo_root=repo_root),
        "hooks/pre-push",
    )

    assert hook_path == repo_root / ".git" / "hooks" / "pre push "


def test_hooks_git_path_reports_git_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout=30)

    monkeypatch.setattr(hooks_module.subprocess, "run", fake_run)

    with pytest.raises(InputError, match="hooks target requires a git repository"):
        hooks_module._git_path(  # pyright: ignore[reportPrivateUsage]
            InstallContext(repo_root=repo_root),
            "hooks/pre-push",
        )


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
