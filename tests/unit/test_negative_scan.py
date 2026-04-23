from __future__ import annotations

from ahadiff.claims.negative_scan import scan_negative_evidence
from ahadiff.contracts import ChangeKind, SourceHunk
from ahadiff.git.symbols import SymbolRange, SymbolRecord


def _symbol(
    *,
    path: str = "src/app.py",
    name: str = "retry_once",
    change_kind: ChangeKind | None = None,
) -> SymbolRecord:
    return SymbolRecord(
        path=path,
        qualified_name=name,
        kind="function",
        range=SymbolRange(1, 2),
        selection_range=SymbolRange(1, 1),
        parent=None,
        touched_lines=(1, 2),
        hunk_ids=("hunk_1",),
        hunk_hash="deadbeef1234",
        change_kind=change_kind,
        extractor="python_ast",
        confidence="high",
    )


def test_negative_scan_flags_risky_generalization_without_symbol_support() -> None:
    evidence = scan_negative_evidence(
        "always makes the module faster",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=1)],
        matched_symbols=[],
        before_text_by_path={},
        after_text_by_path={},
    )

    assert [item.code for item in evidence] == ["risky_generalization_without_symbol_support"]


def test_negative_scan_flags_missing_import_structure() -> None:
    evidence = scan_negative_evidence(
        "adds import dependency handling",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=2)],
        matched_symbols=[],
        before_text_by_path={"src/app.py": "def helper():\n    return 1\n"},
        after_text_by_path={"src/app.py": "def helper():\n    return 2\n"},
    )

    assert any(item.code == "missing_import_structure" for item in evidence)


def test_negative_scan_flags_missing_test_structure() -> None:
    evidence = scan_negative_evidence(
        "adds regression test coverage",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=2)],
        matched_symbols=[],
        before_text_by_path={"src/app.py": "def helper():\n    return 1\n"},
        after_text_by_path={"src/app.py": "def helper():\n    return 2\n"},
    )

    assert any(item.code == "missing_test_structure" for item in evidence)


def test_negative_scan_flags_missing_security_structure() -> None:
    evidence = scan_negative_evidence(
        "adds security sanitization for user input",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=2)],
        matched_symbols=[],
        before_text_by_path={"src/app.py": "def helper():\n    return 1\n"},
        after_text_by_path={"src/app.py": "def helper():\n    return 2\n"},
    )

    assert any(item.code == "missing_security_structure" for item in evidence)


def test_negative_scan_prefers_old_side_text_when_requested() -> None:
    evidence = scan_negative_evidence(
        "adds import dependency handling",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=1, side="old")],
        matched_symbols=[],
        before_text_by_path={"src/app.py": "def helper():\n    return 1\n"},
        after_text_by_path={"src/app.py": "import retry\nvalue = 1\n"},
    )

    assert any(item.code == "missing_import_structure" for item in evidence)


def test_negative_scan_flags_deleted_symbol_reference_without_ack() -> None:
    evidence = scan_negative_evidence(
        "keeps using retry_once for failures",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=2)],
        matched_symbols=[_symbol(change_kind="deleted")],
        before_text_by_path={"src/app.py": "def retry_once():\n    return 1\n"},
        after_text_by_path={},
    )

    assert any(item.code == "deleted_symbol_reference" for item in evidence)


def test_negative_scan_skips_deleted_symbol_reference_with_ack() -> None:
    evidence = scan_negative_evidence(
        "renames retry_once to retry_later",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=2)],
        matched_symbols=[_symbol(change_kind="deleted")],
        before_text_by_path={"src/app.py": "def retry_once():\n    return 1\n"},
        after_text_by_path={},
    )

    assert all(item.code != "deleted_symbol_reference" for item in evidence)
