from __future__ import annotations

from pathlib import Path

from ahadiff.eval.benchmark import load_benchmark_manifest, run_benchmark_suite

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO_ROOT / "benchmarks" / "manifest.json"


def test_judge_stability_entries_are_separate_from_main_benchmark() -> None:
    manifest = load_benchmark_manifest(_MANIFEST_PATH)
    stability_entries = [
        entry
        for entry in manifest.entries
        if entry.kind == "eval" and entry.group == "judge_stability"
    ]
    main_entries = [
        entry
        for entry in manifest.entries
        if entry.kind == "eval" and entry.group == "benchmark_main"
    ]

    assert len(main_entries) == 10
    assert len(stability_entries) == 10
    assert {entry.entry_id for entry in stability_entries} == {
        "eval_011_patch_file",
        "eval_012_patch_stdin",
        "eval_013_file_compare",
        "eval_014_git_since",
        "eval_015_binary_guard",
        "eval_016_file_count_guard",
        "eval_017_token_guard",
        "eval_018_redaction",
        "eval_019_injection",
        "eval_020_i18n_non_ratcheted",
    }


def test_degraded_judge_stability_entries_are_excluded_from_aggregate() -> None:
    manifest = load_benchmark_manifest(_MANIFEST_PATH)
    degraded_ids = {
        entry.entry_id
        for entry in manifest.entries
        if entry.kind == "eval" and entry.group == "judge_stability" and entry.degraded
    }
    report = run_benchmark_suite(_MANIFEST_PATH, suite="local")
    aggregate_ids = {
        str(entry["id"])
        for entry in report.entries
        if entry["degraded"] is False and str(entry["id"]).startswith("eval_")
    }

    assert degraded_ids == {
        "eval_015_binary_guard",
        "eval_016_file_count_guard",
        "eval_017_token_guard",
    }
    assert degraded_ids.isdisjoint(aggregate_ids)
