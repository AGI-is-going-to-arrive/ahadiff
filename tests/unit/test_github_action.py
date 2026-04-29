from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import yaml
from typer.testing import CliRunner

from ahadiff.cli import app
from ahadiff.contracts import ResultEvent
from ahadiff.eval.results import finalized_artifact_digest
from ahadiff.review.database import initialize_review_db, sync_result_event

_RUNNER = CliRunner()


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


def _load_workflow(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    workflow = cast("dict[Any, Any]", loaded)
    if True in workflow and "on" not in workflow:
        workflow["on"] = workflow.pop(True)
    return cast("dict[str, Any]", workflow)


def _assert_linux_macos_matrix(workflow: dict[str, Any], job_name: str) -> None:
    job = cast("dict[str, Any]", cast("dict[str, Any]", workflow["jobs"])[job_name])
    strategy = cast("dict[str, Any]", job["strategy"])
    matrix = cast("dict[str, Any]", strategy["matrix"])
    assert job["runs-on"] == "${{ matrix.os }}"
    assert strategy["fail-fast"] is False
    assert matrix["os"] == ["macos-latest", "ubuntu-latest"]
    assert "windows-latest" not in matrix["os"]


def _assert_platform_bootstrap_steps(workflow_text: str) -> None:
    assert "if: runner.os == 'macOS'" in workflow_text
    assert "if: runner.os == 'Linux'" in workflow_text
    assert "actions/setup-python@v5" in workflow_text
    assert "sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}.tar.gz" in workflow_text
    assert "LD_LIBRARY_PATH=$RUNNER_TEMP/sqlite/lib" in workflow_text


def _assert_repository_backend_ci_matrix(workflow: dict[str, Any]) -> None:
    job = cast("dict[str, Any]", cast("dict[str, Any]", workflow["jobs"])["backend"])
    strategy = cast("dict[str, Any]", job["strategy"])
    matrix = cast("dict[str, Any]", strategy["matrix"])
    include = cast("list[dict[str, Any]]", matrix["include"])

    assert job["runs-on"] == "${{ matrix.os }}"
    assert strategy["fail-fast"] is False
    assert include == [
        {"name": "ubuntu-py311", "os": "ubuntu-latest", "python_version": "3.11"},
        {"name": "ubuntu-py312", "os": "ubuntu-latest", "python_version": "3.12"},
        {"name": "macos-py312", "os": "macos-latest", "python_version": "3.12"},
    ]


def _assert_windows_runtime_guard(
    workflow: dict[str, Any],
    workflow_text: str,
    *,
    job_name: str,
    python_version: str,
) -> None:
    job = cast("dict[str, Any]", cast("dict[str, Any]", workflow["jobs"])[job_name])
    env = cast("dict[str, Any]", job["env"])

    assert job["runs-on"] == "windows-latest"
    assert env["PYTHON_VERSION"] == python_version
    assert "shell: bash" in workflow_text
    assert "tests/unit/test_cross_platform_static.py" in workflow_text
    assert "test_usage_db_rejects_unsupported_sqlite_runtime" in workflow_text
    assert "test_cli_doctor_exits_non_zero_when_sqlite_gate_fails" in workflow_text


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
    assert "uvx --python python3.12 --from ahadiff ahadiff verify --ci" in verify_text
    assert "uv sync" not in verify_text
    assert "pytest" not in verify_text
    assert "--cov" not in verify_text
    assert "tests/unit" not in verify_text
    assert "tests/integration" not in verify_text
    assert "src/ahadiff" not in verify_text
    assert "python -m ahadiff" not in verify_text
    assert "AHADIFF_API_KEY" not in verify_text
    assert "AHADIFF_PROVIDER_API_KEY" not in verify_text
    verify_workflow = _load_workflow(verify_path)
    assert verify_workflow["name"] == "AhaDiff Verify"
    _assert_linux_macos_matrix(verify_workflow, "verify")
    _assert_platform_bootstrap_steps(verify_text)


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
    assert "AHADIFF_PROVIDER_API_KEY: ${{ secrets.AHADIFF_PROVIDER_API_KEY }}" in generate_text
    assert "AHADIFF_API_KEY" not in generate_text
    assert "pull_request" not in generate_text
    assert 'ahadiff learn "$AHADIFF_DIFF_REF"' in generate_text
    assert '--provider-class "$AHADIFF_PROVIDER_CLASS"' in generate_text
    assert '--base-url "$AHADIFF_PROVIDER_BASE_URL"' in generate_text
    assert '--model "$AHADIFF_PROVIDER_MODEL"' in generate_text
    assert "--api-key-env AHADIFF_PROVIDER_API_KEY" in generate_text
    assert '--privacy-mode "$AHADIFF_PRIVACY_MODE"' in generate_text
    assert "actions/upload-artifact@v4" in generate_text
    assert ".ahadiff/runs/**" in generate_text
    assert "uv sync" not in generate_text
    assert "python -m ahadiff" not in generate_text
    assert "sk-12345678" not in generate_text
    generate_workflow = _load_workflow(generate_path)
    workflow_on = generate_workflow["on"]
    assert isinstance(workflow_on, dict)
    assert generate_workflow["name"] == "AhaDiff Generate"
    workflow_dispatch = cast("dict[str, Any]", workflow_on)["workflow_dispatch"]
    assert isinstance(workflow_dispatch, dict)
    workflow_inputs = cast("dict[str, Any]", workflow_dispatch)["inputs"]
    assert isinstance(workflow_inputs, dict)
    workflow_inputs_map = cast("dict[str, Any]", workflow_inputs)
    assert set(workflow_inputs_map) == {
        "diff_ref",
        "provider_class",
        "provider_base_url",
        "provider_model",
        "privacy_mode",
    }
    assert (
        generate_workflow["jobs"]["generate"]["env"]["AHADIFF_PROVIDER_API_KEY"]
        == "${{ secrets.AHADIFF_PROVIDER_API_KEY }}"
    )
    assert (
        generate_workflow["jobs"]["generate"]["env"]["AHADIFF_PROVIDER_BASE_URL"]
        == "${{ inputs.provider_base_url }}"
    )
    _assert_linux_macos_matrix(generate_workflow, "generate")
    _assert_platform_bootstrap_steps(generate_text)


def test_repository_backend_ci_uses_linux_macos_matrix() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflow_path = repo_root / ".github" / "workflows" / "ci.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = _load_workflow(workflow_path)

    assert workflow["name"] == "Backend CI"
    _assert_repository_backend_ci_matrix(workflow)
    _assert_platform_bootstrap_steps(workflow_text)
    _assert_windows_runtime_guard(
        workflow,
        workflow_text,
        job_name="windows-runtime",
        python_version="3.11",
    )
    assert "tests/integration/test_learn_pipeline.py" in workflow_text


def test_repository_nightly_eval_uses_job_level_live_llm_env() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflow_path = repo_root / ".github" / "workflows" / "nightly-eval.yml"
    workflow = _load_workflow(workflow_path)

    assert workflow["name"] == "Nightly Eval"
    job = cast("dict[str, Any]", cast("dict[str, Any]", workflow["jobs"])["eval"])
    env = cast("dict[str, Any]", job["env"])
    assert env["AHADIFF_LIVE_LLM_API_KEY"] == "${{ secrets.AHADIFF_LIVE_LLM_API_KEY }}"
    assert env["AHADIFF_LIVE_LLM_BASE_URL"] == "${{ secrets.AHADIFF_LIVE_LLM_BASE_URL }}"

    steps = cast("list[dict[str, Any]]", job["steps"])
    live_step = next(
        step for step in steps if step.get("name") == "Run eval tests (if LLM key available)"
    )
    assert live_step["if"] == "env.AHADIFF_LIVE_LLM_API_KEY != ''"
    live_env = cast("dict[str, Any]", live_step["env"])
    assert live_env == {"AHADIFF_LIVE_LLM_JUDGE": "1"}


def test_repository_release_gate_has_blocking_doctor_and_windows_runtime() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflow_path = repo_root / ".github" / "workflows" / "release.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = _load_workflow(workflow_path)

    assert workflow["name"] == "Release"
    jobs = cast("dict[str, Any]", workflow["jobs"])
    assert "gate-linux" in jobs
    assert "gate-windows-runtime" in jobs
    assert "uv run python -m ahadiff doctor || true" not in workflow_text
    assert "ahadiff doctor --repo-root ." in workflow_text
    assert 'python -m venv "$RUNNER_TEMP/wheel-smoke"' in workflow_text
    assert (
        "uv run pytest --cov=src/ahadiff --cov-report=term-missing "
        "--cov-fail-under=85 tests -q --tb=long"
    ) in workflow_text
    _assert_windows_runtime_guard(
        workflow,
        workflow_text,
        job_name="gate-windows-runtime",
        python_version="3.11",
    )

    publish = cast("dict[str, Any]", jobs["publish"])
    assert publish["needs"] == ["gate-linux", "gate-windows-runtime"]


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


def test_github_action_uninstall_preserves_user_workflows_directory(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    user_workflow = repo_root / ".github" / "workflows" / "user-managed.yml"
    user_workflow.parent.mkdir(parents=True)
    user_workflow.write_text("name: user workflow\n", encoding="utf-8")

    install_result = _RUNNER.invoke(
        app(),
        ["install", "github-action", "--repo-root", str(repo_root), "--layer2"],
    )
    uninstall_result = _RUNNER.invoke(
        app(),
        ["uninstall", "github-action", "--repo-root", str(repo_root)],
    )

    assert install_result.exit_code == 0
    assert uninstall_result.exit_code == 0
    assert user_workflow.exists()
    assert (repo_root / ".github").exists()
    assert (repo_root / ".github" / "workflows").exists()


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
