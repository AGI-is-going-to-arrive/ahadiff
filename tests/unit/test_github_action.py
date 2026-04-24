from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any, cast

import yaml
from typer.testing import CliRunner

from ahadiff.cli import app
from ahadiff.contracts import ResultEvent
from ahadiff.eval.results import finalized_artifact_digest
from ahadiff.review.database import initialize_review_db, sync_result_event

if TYPE_CHECKING:
    from pathlib import Path

_RUNNER = CliRunner()


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True, text=True)


def _init_git_repo(repo_root: Path) -> None:
    _git(repo_root, "init", "-q")
    _git(repo_root, "config", "user.name", "AhaDiff Test")
    _git(repo_root, "config", "user.email", "test@example.com")


def _load_workflow(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast("dict[str, Any]", loaded)


def test_github_action_install_default_writes_verify_only_workflow(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    dry_run = _RUNNER.invoke(
        app(),
        ["install", "github-action", "--repo-root", str(repo_root), "--dry-run"],
    )
    result = _RUNNER.invoke(app(), ["install", "github-action", "--repo-root", str(repo_root)])

    verify_path = repo_root / ".github" / "workflows" / "ahadiff-verify.yml"
    generate_path = repo_root / ".github" / "workflows" / "ahadiff-generate.yml"
    verify_text = verify_path.read_text(encoding="utf-8")

    assert dry_run.exit_code == 0
    assert "ahadiff-verify.yml" in dry_run.output
    assert "ahadiff-generate.yml" not in dry_run.output
    assert result.exit_code == 0
    assert verify_path.exists()
    assert not generate_path.exists()
    assert "AHADIFF:GENERATED" in verify_text
    assert "python -m ahadiff verify --ci" in verify_text
    assert "tests/integration/test_learn_pipeline.py -m pinned" in verify_text
    assert "--cov-fail-under=85" in verify_text
    assert "AHADIFF_API_KEY" not in verify_text
    assert _load_workflow(verify_path)["name"] == "AhaDiff Verify"


def test_github_action_layer2_writes_opt_in_generate_workflow(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    result = _RUNNER.invoke(
        app(),
        ["install", "github-action", "--repo-root", str(repo_root), "--layer2"],
    )

    verify_path = repo_root / ".github" / "workflows" / "ahadiff-verify.yml"
    generate_path = repo_root / ".github" / "workflows" / "ahadiff-generate.yml"
    generate_text = generate_path.read_text(encoding="utf-8")

    assert result.exit_code == 0
    assert verify_path.exists()
    assert generate_path.exists()
    assert "secrets.AHADIFF_API_KEY" in generate_text
    assert "pull_request" not in generate_text
    assert 'learn "$AHADIFF_DIFF_REF"' in generate_text
    assert "sk-12345678" not in generate_text
    assert "python -m ahadiff learn" in generate_text
    assert _load_workflow(generate_path)["name"] == "AhaDiff Generate"


def test_github_action_refuses_user_workflow_without_force(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    verify_path = repo_root / ".github" / "workflows" / "ahadiff-verify.yml"
    verify_path.parent.mkdir(parents=True)
    verify_path.write_text("name: user workflow\n", encoding="utf-8")

    denied = _RUNNER.invoke(app(), ["install", "github-action", "--repo-root", str(repo_root)])
    forced = _RUNNER.invoke(
        app(),
        ["install", "github-action", "--repo-root", str(repo_root), "--force"],
    )

    assert denied.exit_code == 1
    assert "refusing to overwrite" in denied.output
    assert forced.exit_code == 0
    assert "AHADIFF:GENERATED" in verify_path.read_text(encoding="utf-8")


def test_github_action_uninstall_removes_generated_workflows(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)

    install_result = _RUNNER.invoke(
        app(),
        ["install", "github-action", "--repo-root", str(repo_root), "--layer2"],
    )
    dry_run = _RUNNER.invoke(
        app(),
        ["uninstall", "github-action", "--repo-root", str(repo_root), "--dry-run"],
    )
    uninstall_result = _RUNNER.invoke(
        app(),
        ["uninstall", "github-action", "--repo-root", str(repo_root)],
    )

    assert install_result.exit_code == 0
    assert dry_run.exit_code == 0
    assert "- remove: .github/workflows/ahadiff-verify.yml" in dry_run.output
    assert "- remove: .github/workflows/ahadiff-generate.yml" in dry_run.output
    assert uninstall_result.exit_code == 0
    assert not (repo_root / ".github").exists()


def test_verify_ci_validates_finalized_markers_and_checksums(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_path = state_dir / "runs" / "run_ci"
    run_path.mkdir(parents=True)
    (run_path / "score.json").write_text('{"overall": 90}\n', encoding="utf-8")
    (run_path / "patch.diff").write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
    event = ResultEvent(
        event_id="018f0f52-91c0-7abc-8123-000000000001",
        run_id="run_ci",
        event_type="learn",
        timestamp="2026-04-24T00:00:00Z",
        source_ref="HEAD",
        base_ref="HEAD~1",
        prompt_version="prompt123",
        eval_bundle_version="eval123",
        rubric_version="rubric-v1",
        overall=90.0,
        verdict="PASS",
        status="keep",
        weakest_dim="evidence",
        note_json=None,
    )
    initialize_review_db(state_dir / "review.sqlite")
    sync_result_event(state_dir / "review.sqlite", event)
    artifact_count, checksum = finalized_artifact_digest(run_path)
    (run_path / "finalized.json").write_text(
        json.dumps(
            {
                "run_id": "run_ci",
                "event_id": event.event_id,
                "finalized_at": "2026-04-24T00:00:01Z",
                "artifact_count": artifact_count,
                "checksum": checksum,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    passed = _RUNNER.invoke(app(), ["verify", "--ci", "--repo-root", str(tmp_path)])
    (run_path / "score.json").write_text('{"overall": 91}\n', encoding="utf-8")
    failed = _RUNNER.invoke(app(), ["verify", "--ci", "--repo-root", str(tmp_path)])

    assert passed.exit_code == 0
    assert "1 finalized runs checked" in passed.output
    assert failed.exit_code == 1
    assert "checksum mismatch" in failed.output


def test_verify_ci_rejects_missing_result_event_and_invalid_json(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_path = state_dir / "runs" / "run_ci"
    run_path.mkdir(parents=True)
    (run_path / "score.json").write_text('{"overall": 90}\n', encoding="utf-8")
    artifact_count, checksum = finalized_artifact_digest(run_path)
    (run_path / "finalized.json").write_text(
        json.dumps(
            {
                "run_id": "run_ci",
                "event_id": "018f0f52-91c0-7abc-8123-000000000001",
                "finalized_at": "2026-04-24T00:00:01Z",
                "artifact_count": artifact_count,
                "checksum": checksum,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    missing_event = _RUNNER.invoke(app(), ["verify", "--ci", "--repo-root", str(tmp_path)])
    (run_path / "finalized.json").write_text("{not-json", encoding="utf-8")
    invalid_json = _RUNNER.invoke(app(), ["verify", "--ci", "--repo-root", str(tmp_path)])

    assert missing_event.exit_code == 1
    assert "finalized result event does not exist" in missing_event.output
    assert invalid_json.exit_code == 1
    assert "finalized marker is invalid" in invalid_json.output


def test_verify_ci_passes_without_existing_artifacts(tmp_path: Path) -> None:
    result = _RUNNER.invoke(app(), ["verify", "--ci", "--repo-root", str(tmp_path)])

    assert result.exit_code == 0
    assert "no run artifacts found" in result.output
