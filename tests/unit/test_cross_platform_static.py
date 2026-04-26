from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src" / "ahadiff"


def test_src_ahadiff_does_not_use_datetime_utcnow() -> None:
    python_files = sorted(SOURCE_ROOT.rglob("*.py"))
    assert python_files, "expected src/ahadiff Python files to scan"

    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in python_files
        if "datetime.utcnow()" in path.read_text(encoding="utf-8")
    ]

    assert not offenders, (
        "datetime.utcnow() returns a naive datetime and is deprecated; "
        f"use datetime.now(UTC) instead. Offenders: {', '.join(offenders)}"
    )
