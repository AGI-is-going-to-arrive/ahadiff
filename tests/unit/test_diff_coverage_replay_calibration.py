from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from scripts import diff_coverage_replay_calibration as replay

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class _FakeReport:
    verdict: str
    failed_gate_names: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        hard_gates: dict[str, dict[str, object]] = {
            "evidence_coverage": {
                "passed": "evidence_coverage" not in self.failed_gate_names,
                "detail": "evidence gate",
            }
        }
        hard_gates.update(
            {
                name: {"passed": False, "detail": f"{name} failed"}
                for name in self.failed_gate_names
                if name != "evidence_coverage"
            }
        )
        return {
            "verdict": self.verdict,
            "hard_gates": hard_gates,
        }


def _write_run(runs_dir: Path, run_id: str, *, old_verdict: str) -> Path:
    run_path = runs_dir / run_id
    run_path.mkdir(parents=True)
    (run_path / "metadata.json").write_text(
        json.dumps({"run_id": run_id}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")
    (run_path / "line_map.json").write_text("[]\n", encoding="utf-8")
    (run_path / "claims.jsonl").write_text("", encoding="utf-8")
    (run_path / "score.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "verdict": old_verdict,
                "hard_gates": {
                    "evidence_coverage": {
                        "passed": old_verdict == "PASS",
                        "detail": "old gate",
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return run_path


def _snapshot_files(root: Path) -> dict[Path, tuple[int, str]]:
    snapshot: dict[Path, tuple[int, str]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        snapshot[path.relative_to(root)] = (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return snapshot


def test_replay_calibration_is_read_only_and_counts_fail_to_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs_dir = tmp_path / "runs"
    _write_run(runs_dir, "run_fail_old", old_verdict="FAIL")
    before = _snapshot_files(runs_dir)

    def fake_evaluate_run(run_path: Path) -> _FakeReport:
        assert run_path.name == "run_fail_old"
        return _FakeReport(verdict="PASS")

    monkeypatch.setattr(replay, "evaluate_run", fake_evaluate_run)

    exit_code = replay.main(["--runs-dir", str(runs_dir)])

    assert exit_code == 0
    assert _snapshot_files(runs_dir) == before
    output = capsys.readouterr().out
    assert "FAIL_TO_PASS" in output
    assert "run_fail_old" in output
    assert "fail_to_pass=1" in output


@pytest.mark.parametrize(
    ("old_verdict", "new_report", "extra_args", "expected_exit"),
    [
        ("PASS", _FakeReport(verdict="FAIL", failed_gate_names=("evidence_coverage",)), [], 2),
        ("FAIL", _FakeReport(verdict="PASS"), ["--max-fail-to-pass", "0"], 3),
    ],
)
def test_replay_calibration_exit_codes_for_verdict_transitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old_verdict: str,
    new_report: _FakeReport,
    extra_args: list[str],
    expected_exit: int,
) -> None:
    runs_dir = tmp_path / "runs"
    _write_run(runs_dir, "run_case", old_verdict=old_verdict)

    def fake_evaluate_run(_run_path: Path) -> _FakeReport:
        return new_report

    monkeypatch.setattr(replay, "evaluate_run", fake_evaluate_run)

    assert replay.main(["--runs-dir", str(runs_dir), *extra_args]) == expected_exit


def test_replay_calibration_ignores_non_evidence_gate_transitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs_dir = tmp_path / "runs"
    _write_run(runs_dir, "run_non_evidence", old_verdict="PASS")

    def fake_evaluate_run(_run_path: Path) -> _FakeReport:
        return _FakeReport(verdict="FAIL", failed_gate_names=("contradicted_claims",))

    monkeypatch.setattr(replay, "evaluate_run", fake_evaluate_run)

    assert replay.main(["--runs-dir", str(runs_dir)]) == 0
    output = capsys.readouterr().out
    assert "run_non_evidence\tUNCHANGED\tPASS\tFAIL" in output
    assert "pass_to_fail=0" in output


def test_replay_calibration_returns_target_missing_code(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    _write_run(runs_dir, "run_present", old_verdict="PASS")

    assert replay.main(["--runs-dir", str(runs_dir), "--target-run", "run_missing"]) == 4


@pytest.mark.parametrize("make_runs_dir", [False, True])
def test_replay_calibration_fails_when_no_runs_are_checked(
    tmp_path: Path,
    make_runs_dir: bool,
) -> None:
    runs_dir = tmp_path / "runs"
    if make_runs_dir:
        runs_dir.mkdir()

    assert replay.main(["--runs-dir", str(runs_dir)]) == 4


def test_replay_calibration_fails_when_all_runs_are_skipped(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    (runs_dir / "run_missing_score").mkdir(parents=True)

    assert replay.main(["--runs-dir", str(runs_dir)]) == 4


def test_replay_calibration_strict_ignores_historical_ineligible_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs_dir = tmp_path / "runs"
    (runs_dir / "run_missing_score").mkdir(parents=True)
    run_missing_gate = _write_run(runs_dir, "run_missing_gate", old_verdict="PASS")
    (run_missing_gate / "score.json").write_text(
        json.dumps({"verdict": "PASS", "hard_gates": {}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_run(runs_dir, "run_checked", old_verdict="PASS")

    def fake_evaluate_run(run_path: Path) -> _FakeReport:
        assert run_path.name in {"run_missing_gate", "run_checked"}
        return _FakeReport(verdict="PASS")

    monkeypatch.setattr(replay, "evaluate_run", fake_evaluate_run)

    exit_code = replay.main(["--runs-dir", str(runs_dir), "--strict"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "checked=1" in output
    assert "skipped=2" in output
    assert "SKIPPED run_missing_score: no score.json" in output
    assert "SKIPPED run_missing_gate: missing persisted evidence_coverage gate" in output


def test_replay_calibration_rejects_target_run_path_traversal(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    outside = tmp_path / "run_outside"
    _write_run(outside.parent, "run_outside", old_verdict="PASS")
    runs_dir.mkdir()

    assert replay.main(["--runs-dir", str(runs_dir), "--target-run", "../run_outside"]) == 4


def test_replay_calibration_skips_symlinked_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_dir = tmp_path / "runs"
    outside_runs = tmp_path / "outside"
    _write_run(outside_runs, "run_link", old_verdict="PASS")
    runs_dir.mkdir()
    (runs_dir / "run_link").symlink_to(outside_runs / "run_link", target_is_directory=True)
    visited: list[str] = []

    def fake_evaluate_run(run_path: Path) -> _FakeReport:
        visited.append(run_path.name)
        return _FakeReport(verdict="PASS")

    monkeypatch.setattr(replay, "evaluate_run", fake_evaluate_run)

    assert replay.main(["--runs-dir", str(runs_dir)]) == 4
    assert visited == []


def test_replay_calibration_happy_path_with_target_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_dir = tmp_path / "runs"
    _write_run(runs_dir, "run_target", old_verdict="PASS")
    _write_run(runs_dir, "run_other", old_verdict="PASS")
    visited: list[str] = []

    def fake_evaluate_run(run_path: Path) -> _FakeReport:
        visited.append(run_path.name)
        return _FakeReport(verdict="PASS")

    monkeypatch.setattr(replay, "evaluate_run", fake_evaluate_run)

    exit_code = replay.main(["--runs-dir", str(runs_dir), "--target-run", "run_target", "--strict"])

    assert exit_code == 0
    assert visited == ["run_target"]
