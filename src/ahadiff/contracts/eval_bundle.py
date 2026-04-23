from __future__ import annotations

import hashlib
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict

# These labels are the frozen logical hash inputs, not disk paths.
EVAL_BUNDLE_FILES: tuple[tuple[str, str], ...] = (
    ("eval/deterministic.py", "src/ahadiff/eval/deterministic.py"),
    ("eval/evaluator.py", "src/ahadiff/eval/evaluator.py"),
    ("eval/gates.py", "src/ahadiff/eval/gates.py"),
    ("eval/rubric.py", "src/ahadiff/eval/rubric.py"),
    ("eval/rubric.yaml", "src/ahadiff/eval/rubric.yaml"),
)

RUBRIC_WEIGHTS: dict[str, dict[str, int]] = {
    "accuracy": {"weight": 20, "hard_gate": 14},
    "evidence": {"weight": 18, "hard_gate": 12},
    "diff_coverage": {"weight": 14},
    "learnability": {"weight": 14},
    "quiz_transfer": {"weight": 10},
    "spec_alignment": {"weight": 10},
    "conciseness": {"weight": 8},
    "safety_privacy": {"weight": 6},
}


def compute_eval_bundle_version(repo_root: str | Path) -> str:
    """Compute the frozen eval bundle hash when the bundle files exist."""

    root = Path(repo_root)
    chunks: list[bytes] = []
    missing_paths: list[str] = []
    for logical_path, disk_path in sorted(EVAL_BUNDLE_FILES, key=lambda item: item[0]):
        target = root / disk_path
        if not target.is_file():
            missing_paths.append(disk_path)
            continue
        content = target.read_bytes()
        chunks.append(logical_path.encode("utf-8") + b"\n" + content)

    if missing_paths:
        raise FileNotFoundError(
            "eval bundle files are not available in this checkout yet: " + ", ".join(missing_paths)
        )
    return hashlib.sha256(b"\n---\n".join(chunks)).hexdigest()[:12]


def compute_runtime_eval_bundle_version() -> str:
    """Compute the frozen eval bundle hash from installed package resources."""

    package_root = files("ahadiff")
    chunks: list[bytes] = []
    missing_paths: list[str] = []
    for logical_path, disk_path in sorted(EVAL_BUNDLE_FILES, key=lambda item: item[0]):
        package_relative_parts = Path(disk_path).parts[2:]
        resource = package_root.joinpath(*package_relative_parts)
        if not resource.is_file():
            missing_paths.append("/".join(package_relative_parts))
            continue
        chunks.append(logical_path.encode("utf-8") + b"\n" + resource.read_bytes())

    if missing_paths:
        raise FileNotFoundError(
            "eval bundle files are not available in the installed package: "
            + ", ".join(missing_paths)
        )
    return hashlib.sha256(b"\n---\n".join(chunks)).hexdigest()[:12]


class EvalBundleInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eval_bundle_version: str
    rubric_version: str | None = None
    file_checksums: dict[str, str]


__all__ = [
    "EVAL_BUNDLE_FILES",
    "RUBRIC_WEIGHTS",
    "compute_eval_bundle_version",
    "compute_runtime_eval_bundle_version",
    "EvalBundleInfo",
]
