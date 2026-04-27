#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"

if SRC_DIR.is_dir():
    sys.path.insert(0, str(SRC_DIR))

SIZE_TIERS = (
    ("1kb", 1_024, 500),
    ("10kb", 10_240, 200),
    ("100kb", 102_400, 40),
    ("1mb", 1_048_576, 5),
)


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _diff_segment(index: int, *, filler_width: int = 120) -> str:
    filler = f"payload_{index:05d}_" + ("x" * filler_width)
    return (
        f"diff --git a/src/file_{index:05d}.py b/src/file_{index:05d}.py\n"
        f"index 1111111..2222222 100644\n"
        f"--- a/src/file_{index:05d}.py\n"
        f"+++ b/src/file_{index:05d}.py\n"
        f"@@ -1,3 +1,3 @@\n"
        f"-def func_{index:05d}():\n"
        f'-    return "before_{index:05d}"\n'
        f"+def func_{index:05d}():\n"
        f'+    return "after_{index:05d}"\n'
        f' context_{index:05d} = "{filler}"\n'
    )


def _build_patch(target_bytes: int) -> str:
    segments: list[str] = []
    size = 0
    index = 0
    while size < target_bytes:
        segment = _diff_segment(index)
        segments.append(segment)
        size += len(segment.encode("utf-8"))
        index += 1
    return "".join(segments)


def main() -> dict[str, Any]:
    try:
        from ahadiff.git.parser import parse_unified_diff
    except Exception as exc:
        return {
            "benchmark": "diff_parse",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "status": "skipped",
        }

    results: dict[str, Any] = {}
    for label, target_bytes, iterations in SIZE_TIERS:
        patch_text = _build_patch(target_bytes)
        actual_bytes = len(patch_text.encode("utf-8"))
        actual_lines = len(patch_text.splitlines())

        parsed = parse_unified_diff(patch_text)
        started = time.perf_counter()
        for _ in range(iterations):
            parse_unified_diff(patch_text)
        elapsed_seconds = time.perf_counter() - started

        results[label] = {
            "actual_bytes": actual_bytes,
            "actual_lines": actual_lines,
            "bytes_per_sec": round((actual_bytes * iterations) / elapsed_seconds, 3),
            "files_parsed": len(parsed),
            "iterations": iterations,
            "lines_per_sec": round((actual_lines * iterations) / elapsed_seconds, 3),
            "target_bytes": target_bytes,
            "total_elapsed_ms": round(elapsed_seconds * 1000.0, 3),
        }

    return {
        "benchmark": "diff_parse",
        "status": "ok",
        "tiers": results,
        "working_directory": str(REPO_ROOT),
    }


if __name__ == "__main__":
    try:
        _emit(main())
    except Exception as exc:  # pragma: no cover - defensive JSON fallback
        _emit(
            {
                "benchmark": "diff_parse",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "status": "error",
            }
        )
