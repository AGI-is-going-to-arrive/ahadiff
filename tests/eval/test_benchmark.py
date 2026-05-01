from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from ahadiff.cli import app
from ahadiff.core.errors import InputError
from ahadiff.eval.benchmark import (
    compute_suite_digest,
    load_benchmark_manifest,
    run_benchmark_suite,
    verify_suite_digest,
)

_RUNNER = CliRunner()
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO_ROOT / "benchmarks" / "manifest.json"
_EXPECTED_REPORT_KEYS_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "benchmark" / "expected_report_keys.json"
)


def test_benchmark_manifest_digest_is_frozen() -> None:
    manifest = load_benchmark_manifest(_MANIFEST_PATH)

    assert manifest.suite_id == "ahadiff-local-v1"
    assert manifest.visibility == "private"
    assert len([entry for entry in manifest.entries if entry.kind == "eval"]) == 20
    assert len([entry for entry in manifest.entries if entry.kind == "integration"]) == 11
    assert verify_suite_digest(manifest) == manifest.suite_digest


def test_benchmark_digest_detects_fixture_drift(tmp_path: Path) -> None:
    local_benchmarks = tmp_path / "benchmarks"
    shutil.copytree(_REPO_ROOT / "benchmarks", local_benchmarks)
    manifest_path = local_benchmarks / "manifest.json"
    fixture = local_benchmarks / "fixtures" / "eval" / "eval_001_python_retry" / "ground_truth.md"
    fixture.write_text(fixture.read_text(encoding="utf-8") + "\nDrift.\n", encoding="utf-8")
    manifest = load_benchmark_manifest(manifest_path)

    assert compute_suite_digest(manifest) != manifest.suite_digest


def test_benchmark_digest_detects_graph_fixture_drift(tmp_path: Path) -> None:
    local_benchmarks = tmp_path / "benchmarks"
    shutil.copytree(_REPO_ROOT / "benchmarks", local_benchmarks)
    manifest_path = local_benchmarks / "manifest.json"
    fixture = (
        local_benchmarks / "fixtures" / "integration" / "pinned_011_graph_present" / "graph.json"
    )
    fixture.write_text(
        fixture.read_text(encoding="utf-8").replace("AuthMiddleware", "AuthMiddlewareDrift"),
        encoding="utf-8",
    )
    manifest = load_benchmark_manifest(manifest_path)

    assert compute_suite_digest(manifest) != manifest.suite_digest


def test_benchmark_rejects_ground_truth_concept_drift(tmp_path: Path) -> None:
    local_benchmarks = tmp_path / "benchmarks"
    shutil.copytree(_REPO_ROOT / "benchmarks", local_benchmarks)
    manifest_path = local_benchmarks / "manifest.json"
    fixture = local_benchmarks / "fixtures" / "eval" / "eval_001_python_retry" / "ground_truth.md"
    fixture.write_text(
        fixture.read_text(encoding="utf-8").replace(
            "Expected concepts: retry-loop, exception-flow.",
            "Expected concepts: wrong-concept, exception-flow.",
        ),
        encoding="utf-8",
    )
    manifest = load_benchmark_manifest(manifest_path)
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_payload["suite_digest"] = compute_suite_digest(manifest)
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(InputError, match="ground_truth expected concepts"):
        run_benchmark_suite(manifest_path, suite="local")


def test_run_benchmark_suite_reports_comparable_metrics() -> None:
    report = run_benchmark_suite(_MANIFEST_PATH, suite="local")
    payload = report.to_payload()
    expected_report_keys = json.loads(_EXPECTED_REPORT_KEYS_PATH.read_text(encoding="utf-8"))
    assert isinstance(expected_report_keys, dict)
    expected_report_keys_map = cast("dict[str, object]", expected_report_keys)

    assert payload["suite_id"] == "ahadiff-local-v1"
    assert payload["api_family_version"] == "none"
    assert payload["comparable_entry_count"] == 14
    assert payload["excluded_degraded_count"] == 6
    assert isinstance(payload["mean_score"], int | float)
    assert payload["mean_score"] >= 80.0
    assert payload["claim_verification_rate"] == 1.0
    entries = payload["entries"]
    assert isinstance(entries, list)
    first_entry = cast("dict[str, object]", entries[0])
    assert isinstance(first_entry["ground_truth_digest"], str)
    assert len(first_entry["ground_truth_digest"]) == 64
    dimensions = payload["dimension_means"]
    assert isinstance(dimensions, dict)
    dimension_map = cast("dict[str, object]", dimensions)
    required_keys = expected_report_keys_map["required_keys"]
    assert isinstance(required_keys, list)
    assert set(cast("list[str]", required_keys)).issubset(payload)
    assert set(dimension_map) == {
        "accuracy",
        "evidence",
        "diff_coverage",
        "learnability",
        "quiz_transfer",
        "spec_alignment",
        "conciseness",
        "safety_privacy",
    }


def test_benchmark_cli_writes_report(tmp_path: Path) -> None:
    output_path = tmp_path / "report.json"

    result = _RUNNER.invoke(
        app(),
        [
            "benchmark",
            "--repo-root",
            str(_REPO_ROOT),
            "--suite",
            "local",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["suite_id"] == "ahadiff-local-v1"
    assert payload["api_family_version"] == "none"
    assert "Suite digest" in result.output


def test_benchmark_cli_rejects_manifest_outside_workspace(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / ".ahadiff").mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "manifest.json").write_text("{}\n", encoding="utf-8")

    result = _RUNNER.invoke(
        app(),
        [
            "benchmark",
            "--repo-root",
            str(workspace_root),
            "--manifest",
            "../outside/manifest.json",
            "--output",
            str(tmp_path / "report.json"),
        ],
    )

    assert result.exit_code == 1
    assert "benchmark manifest path must be inside workspace root" in (
        result.stderr + result.output
    )
