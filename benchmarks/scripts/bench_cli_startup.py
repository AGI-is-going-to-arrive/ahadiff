#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
DEFAULT_CLI_STARTUP_TIMEOUT_SECONDS = 120.0

if SRC_DIR.is_dir():
    sys.path.insert(0, str(SRC_DIR))


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _pythonpath() -> str:
    existing = os.environ.get("PYTHONPATH")
    if existing:
        return os.pathsep.join((str(SRC_DIR), existing))
    return str(SRC_DIR)


def _cli_startup_timeout_seconds() -> float:
    raw_value = os.environ.get("AHADIFF_BENCH_CLI_STARTUP_TIMEOUT_SECONDS")
    if raw_value is None:
        return DEFAULT_CLI_STARTUP_TIMEOUT_SECONDS
    try:
        timeout_seconds = float(raw_value)
    except ValueError:
        return DEFAULT_CLI_STARTUP_TIMEOUT_SECONDS
    if math.isfinite(timeout_seconds) and timeout_seconds > 0:
        return timeout_seconds
    return DEFAULT_CLI_STARTUP_TIMEOUT_SECONDS


def main() -> dict[str, Any]:
    python_executable = sys.executable
    command = [python_executable, "-m", "ahadiff", "--version"]
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath()
    # CI runners can be CPU-starved; keep failures real but avoid a tight startup cap.
    timeout_seconds = _cli_startup_timeout_seconds()
    samples_ms: list[float] = []
    version_output = ""

    for _ in range(10):
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if completed.returncode != 0:
            return {
                "benchmark": "cli_startup",
                "command": command,
                "returncode": completed.returncode,
                "status": "error",
                "stderr": completed.stderr.strip(),
                "stdout": completed.stdout.strip(),
            }
        version_output = completed.stdout.strip()
        samples_ms.append(elapsed_ms)

    return {
        "benchmark": "cli_startup",
        "command": command,
        "metrics": {
            "mean_ms": round(statistics.fmean(samples_ms), 3),
            "min_ms": round(min(samples_ms), 3),
            "p50_ms": round(_percentile(samples_ms, 0.50), 3),
            "p95_ms": round(_percentile(samples_ms, 0.95), 3),
        },
        "raw_samples_ms": [round(sample, 3) for sample in samples_ms],
        "runs": len(samples_ms),
        "status": "ok",
        "version_output": version_output,
        "working_directory": str(REPO_ROOT),
    }


if __name__ == "__main__":
    try:
        _emit(main())
    except Exception as exc:  # pragma: no cover - defensive JSON fallback
        _emit(
            {
                "benchmark": "cli_startup",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "status": "error",
            }
        )
