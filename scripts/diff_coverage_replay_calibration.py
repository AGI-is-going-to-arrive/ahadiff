#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from ahadiff.core.errors import InputError
from ahadiff.core.paths import validate_run_id
from ahadiff.eval.evaluator import evaluate_run

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@runtime_checkable
class _ReconfigurableTextIO(Protocol):
    def reconfigure(self, *, encoding: str) -> None: ...


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdout_utf8()
    args = _parse_args(argv)
    runs_dir = args.runs_dir
    if args.target_run is not None:
        target_path = _target_run_path(runs_dir, args.target_run)
        if target_path is None:
            return 4
        run_paths = (target_path,)
    else:
        run_paths = tuple(sorted(path for path in runs_dir.glob("run_*") if not path.is_symlink()))

    checked = 0
    skipped: list[str] = []
    warnings: list[str] = []
    fail_to_pass: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    pass_to_fail: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []

    print("run_id\ttransition\told_verdict\tnew_verdict\told_failed\tnew_failed")
    for run_path in run_paths:
        score_path = run_path / "score.json"
        if not score_path.is_file():
            skipped.append(f"{run_path.name}: no score.json")
            continue
        try:
            raw_old_payload = json.loads(score_path.read_text(encoding="utf-8"))
            if not isinstance(raw_old_payload, dict):
                warnings.append(f"{run_path.name}: score.json is not an object")
                continue
            old_payload = cast("dict[str, object]", raw_old_payload)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{run_path.name}: {type(exc).__name__}: {exc}")
            continue

        old_verdict = str(old_payload.get("verdict"))
        old_failed = _failed_gates(old_payload)
        old_evidence_passed = _gate_passed(old_payload, "evidence_coverage")
        if old_evidence_passed is None:
            skipped.append(f"{run_path.name}: missing persisted evidence_coverage gate")
            continue

        try:
            new_payload = evaluate_run(run_path).to_payload()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{run_path.name}: {type(exc).__name__}: {exc}")
            continue

        new_verdict = str(new_payload.get("verdict"))
        new_failed = _failed_gates(new_payload)
        new_evidence_passed = _gate_passed(new_payload, "evidence_coverage")
        if new_evidence_passed is None:
            warnings.append(f"{run_path.name}: missing replayed evidence_coverage gate")
            continue
        checked += 1
        transition = "UNCHANGED"
        if old_evidence_passed and not new_evidence_passed:
            transition = "PASS_TO_FAIL"
            pass_to_fail.append((run_path.name, old_failed, new_failed))
        elif not old_evidence_passed and new_evidence_passed:
            transition = "FAIL_TO_PASS"
            fail_to_pass.append((run_path.name, old_failed, new_failed))
        print(
            "\t".join(
                (
                    run_path.name,
                    transition,
                    old_verdict,
                    new_verdict,
                    ",".join(old_failed) or "-",
                    ",".join(new_failed) or "-",
                )
            )
        )

    print(f"checked={checked}")
    print(f"skipped={len(skipped)}")
    for item in skipped[:10]:
        print(f"SKIPPED {item}")
    if warnings:
        print(f"warnings={len(warnings)}")
    for warning in warnings[:10]:
        print(f"WARNING {warning}")
    print(f"fail_to_pass={len(fail_to_pass)}")
    for run_id, old_failed, new_failed in fail_to_pass:
        print(f"FAIL_TO_PASS {run_id} old_failed={old_failed} new_failed={new_failed}")
    print(f"pass_to_fail={len(pass_to_fail)}")
    for run_id, old_failed, new_failed in pass_to_fail:
        print(f"PASS_TO_FAIL {run_id} old_failed={old_failed} new_failed={new_failed}")

    if checked == 0:
        return 4
    if pass_to_fail:
        return 2
    if len(fail_to_pass) > args.max_fail_to_pass:
        return 3
    if args.strict and warnings:
        return 1
    return 0


def _target_run_path(runs_dir: Path, run_id: str) -> Path | None:
    try:
        validate_run_id(run_id)
    except InputError as exc:
        print(f"target_run invalid: {exc}")
        return None
    target_path = runs_dir / run_id
    if target_path.is_symlink() or not target_path.is_dir():
        print(f"target_run missing: {run_id}")
        return None
    return target_path


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only replay calibration for diff_coverage hard gate changes."
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path(".ahadiff/runs"),
        help="Directory containing run_* folders.",
    )
    parser.add_argument("--target-run", help="Optional single run id to replay.")
    parser.add_argument(
        "--max-fail-to-pass",
        type=int,
        default=3,
        help="Maximum allowed historical FAIL runs that now replay as PASS.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Return a non-zero exit code when replay warnings are emitted.",
    )
    return parser.parse_args(argv)


def _failed_gates(payload: Mapping[str, object]) -> tuple[str, ...]:
    gates = payload.get("hard_gates")
    if not isinstance(gates, dict):
        return ()
    names: list[str] = []
    for name, raw_gate in cast("dict[object, object]", gates).items():
        if not isinstance(raw_gate, dict):
            continue
        gate = cast("Mapping[object, object]", raw_gate)
        if gate.get("passed") is False:
            names.append(str(name))
    return tuple(names)


def _gate_passed(payload: Mapping[str, object], gate_name: str) -> bool | None:
    gates = payload.get("hard_gates")
    if not isinstance(gates, dict):
        return None
    gate = cast("dict[object, object]", gates).get(gate_name)
    if not isinstance(gate, dict):
        return None
    passed = cast("dict[object, object]", gate).get("passed")
    return passed if isinstance(passed, bool) else None


def _configure_stdout_utf8() -> None:
    if isinstance(sys.stdout, _ReconfigurableTextIO):
        sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
