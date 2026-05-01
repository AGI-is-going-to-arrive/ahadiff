from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ALL_SCRIPT = REPO_ROOT / "benchmarks" / "scripts" / "run_all.sh"
BASELINE_PATH = REPO_ROOT / "benchmarks" / "results" / "baseline_20260428.json"


def test_run_all_uses_configured_project_python(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text("#!/usr/bin/env bash\nexit 17\n", encoding="utf-8")
    fake_python.chmod(0o755)

    original_output = BASELINE_PATH.read_text(encoding="utf-8") if BASELINE_PATH.exists() else None

    env = os.environ.copy()
    env["AHADIFF_BENCH_PYTHON"] = sys.executable
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    try:
        completed = subprocess.run(
            ["bash", str(RUN_ALL_SCRIPT)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env=env,
        )

        assert completed.returncode == 0
        payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        assert payload["cli_startup"]["status"] == "ok"
        assert payload["diff_parse"]["status"] == "ok"
        assert payload["sqlite_queries"]["status"] == "ok"
        assert payload["graphify"]["status"] == "ok"
        assert payload["graphify"]["fixture"] == "large_graph.json"
    finally:
        if original_output is None:
            BASELINE_PATH.unlink(missing_ok=True)
        else:
            BASELINE_PATH.write_text(original_output, encoding="utf-8")
