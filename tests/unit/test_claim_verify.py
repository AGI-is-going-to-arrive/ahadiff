from __future__ import annotations

import pytest
from pydantic import ValidationError

from ahadiff.claims.schema import ClaimCandidate
from ahadiff.claims.verify import verify_claim_candidate
from ahadiff.contracts import SourceHunk
from ahadiff.git.line_map import build_line_map
from ahadiff.git.parser import parse_unified_diff
from ahadiff.git.symbols import extract_symbols


def _build_context(
    patch: str,
    *,
    before_text_by_path: dict[str, str] | None = None,
    after_text_by_path: dict[str, str] | None = None,
):
    changed_files = parse_unified_diff(patch)
    return (
        build_line_map(changed_files),
        extract_symbols(
            changed_files,
            before_text_by_path=before_text_by_path or {},
            after_text_by_path=after_text_by_path or {},
        ),
    )


def _numbered_text(prefix: str, count: int) -> str:
    return "".join(f"{prefix}_{line_number}\n" for line_number in range(1, count + 1))


def _truncated_context_patch(
    *,
    parsed_line_count: int = 120,
    header_count: int = 121,
) -> str:
    body = "".join(f" line_{line_number}\n" for line_number in range(1, parsed_line_count + 1))
    return (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        f"@@ -1,{header_count} +1,{header_count} @@\n"
        f"{body}"
        "[truncated]\n"
    )


@pytest.mark.parametrize(("start", "end"), [(0, 1), (-5, -1), (1, 0)])
def test_source_hunk_rejects_non_positive_line_ranges(start: int, end: int) -> None:
    with pytest.raises(ValidationError, match="source hunk start and end must be positive"):
        SourceHunk(file="src/app.py", start=start, end=end)


def test_verify_claim_rejects_file_not_in_patch() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old = 1
+new = 2
"""
    line_maps, symbols = _build_context(patch, after_text_by_path={"src/app.py": "new = 2\n"})
    claim = ClaimCandidate(
        claim_id="c1",
        run_id="run-1",
        text="updates the config loader",
        source_hunks=[SourceHunk(file="src/missing.py", start=1, end=1)],
    )

    result = verify_claim_candidate(claim, line_maps=line_maps, symbols=symbols)

    assert result.record.status == "rejected"
    assert result.record.reason_code == "file_not_in_patch"


def test_verify_claim_rejects_line_outside_hunk() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old = 1
+new = 2
"""
    line_maps, symbols = _build_context(patch, after_text_by_path={"src/app.py": "new = 2\n"})
    claim = ClaimCandidate(
        claim_id="c1",
        run_id="run-1",
        text="updates the app constant",
        source_hunks=[SourceHunk(file="src/app.py", start=9, end=9)],
    )

    result = verify_claim_candidate(claim, line_maps=line_maps, symbols=symbols)

    assert result.record.status == "rejected"
    assert result.record.reason_code == "line_outside_hunk"


def test_verify_claim_rejects_hunk_id_mismatch() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old = 1
+new = 2
"""
    line_maps, symbols = _build_context(patch, after_text_by_path={"src/app.py": "new = 2\n"})
    claim = ClaimCandidate(
        claim_id="c-hunk-id",
        run_id="run-1",
        text="updates the app constant",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=1, side="new")],
        hunk_ids=["hunk_missing"],
    )

    result = verify_claim_candidate(claim, line_maps=line_maps, symbols=symbols)

    assert result.record.status == "rejected"
    assert result.record.reason_code == "hunk_id_mismatch"


def test_verify_claim_marks_symbol_not_found_as_not_proven() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
-def retry_once():
-    return 1
+def retry_once():
+    return 2
"""
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": "def retry_once():\n    return 1\n"},
        after_text_by_path={"src/app.py": "def retry_once():\n    return 2\n"},
    )
    claim = ClaimCandidate(
        claim_id="c1",
        run_id="run-1",
        text="changes retry behavior",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=2)],
        symbols=["missing_symbol"],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": "def retry_once():\n    return 1\n"},
        after_text_by_path={"src/app.py": "def retry_once():\n    return 2\n"},
    )

    assert result.record.status == "not_proven"
    assert result.record.reason_code is None
    assert result.record.confidence == "low"


def test_verify_claim_accepts_fuzzy_symbol_match() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
-def retry_once():
-    return 1
+def retry_once():
+    return 2
"""
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": "def retry_once():\n    return 1\n"},
        after_text_by_path={"src/app.py": "def retry_once():\n    return 2\n"},
    )
    claim = ClaimCandidate(
        claim_id="c1",
        run_id="run-1",
        text="updates retry logic",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=2)],
        symbols=["Retry Once"],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": "def retry_once():\n    return 1\n"},
        after_text_by_path={"src/app.py": "def retry_once():\n    return 2\n"},
    )

    assert result.record.status == "verified"
    assert result.record.confidence == "high"
    assert result.record.extractor == "python_ast"


def test_verify_claim_accepts_scoped_fuzzy_symbol_match() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,3 @@
 class Foo:
     def run(self):
-        return 1
+        return 2
"""
    before_text = "class Foo:\n    def run(self):\n        return 1\n"
    after_text = "class Foo:\n    def run(self):\n        return 2\n"
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )
    claim = ClaimCandidate(
        claim_id="c-scope-ok",
        run_id="run-1",
        text="updates Foo run behavior",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=3)],
        symbols=["Foo::Run"],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )

    assert result.record.status == "verified"
    assert result.matched_symbols == ["Foo.run"]


def test_verify_claim_requires_explicit_side_for_ambiguous_single_line_match() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-value = 1
+value = 2
"""
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": "value = 1\n"},
        after_text_by_path={"src/app.py": "value = 2\n"},
    )
    claim = ClaimCandidate(
        claim_id="c-side-ambiguous",
        run_id="run-1",
        text="updates the value assignment",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=1)],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": "value = 1\n"},
        after_text_by_path={"src/app.py": "value = 2\n"},
    )

    assert result.record.status == "rejected"
    assert result.record.reason_code == "evidence_missing"


def test_verify_claim_accepts_explicit_new_side_for_single_line_match() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-value = 1
+value = 2
"""
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": "value = 1\n"},
        after_text_by_path={"src/app.py": "value = 2\n"},
    )
    claim = ClaimCandidate(
        claim_id="c-side-new",
        run_id="run-1",
        text="updates the value assignment",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=1, side="new")],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": "value = 1\n"},
        after_text_by_path={"src/app.py": "value = 2\n"},
    )

    assert result.record.status == "weak"
    source_hunk = result.record.source_hunks[0]
    assert source_hunk.side == "new"
    assert source_hunk.display_path == "src/app.py"
    assert source_hunk.file_id is not None
    assert len(source_hunk.file_id) == 12
    assert source_hunk.hunk_id is not None
    assert source_hunk.hunk_id.startswith("hunk_")
    assert source_hunk.hunk_hash is not None
    assert len(source_hunk.hunk_hash) == 12


def test_verify_claim_normalizes_multi_hunk_same_file_same_side_range() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old_first = 1
+new_first = 1
@@ -2 +2 @@
-old_second = 1
+new_second = 1
"""
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": "old_first = 1\nold_second = 1\n"},
        after_text_by_path={"src/app.py": "new_first = 1\nnew_second = 1\n"},
    )
    claim = ClaimCandidate(
        claim_id="c-multi-hunk",
        run_id="run-1",
        text="updates both app constants",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=2, side="new")],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": "old_first = 1\nold_second = 1\n"},
        after_text_by_path={"src/app.py": "new_first = 1\nnew_second = 1\n"},
    )

    assert result.record.status == "weak"
    assert result.record.reason_code is None
    assert [(hunk.start, hunk.end, hunk.side) for hunk in result.record.source_hunks] == [
        (1, 1, "new"),
        (2, 2, "new"),
    ]
    assert len(result.matched_hunk_ids) == 2
    assert all(hunk.hunk_id is not None for hunk in result.record.source_hunks)
    assert all(hunk.hunk_hash is not None for hunk in result.record.source_hunks)


def test_verify_claim_normalizes_multi_hunk_range_and_drops_context_gap() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
-old_first = 1
+new_first = 1
 keep_first()
@@ -8,2 +8,2 @@
-old_second = 1
+new_second = 1
 keep_second()
"""
    before_text = (
        "old_first = 1\n"
        "keep_first()\n"
        "gap_3()\n"
        "gap_4()\n"
        "gap_5()\n"
        "gap_6()\n"
        "gap_7()\n"
        "old_second = 1\n"
        "keep_second()\n"
    )
    after_text = (
        "new_first = 1\n"
        "keep_first()\n"
        "gap_3()\n"
        "gap_4()\n"
        "gap_5()\n"
        "gap_6()\n"
        "gap_7()\n"
        "new_second = 1\n"
        "keep_second()\n"
    )
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )
    claim = ClaimCandidate(
        claim_id="c-multi-hunk-gap",
        run_id="run-1",
        text="updates both app regions",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=9, side="new")],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )

    assert result.record.status == "weak"
    assert [(hunk.start, hunk.end, hunk.side) for hunk in result.record.source_hunks] == [
        (1, 2, "new"),
        (8, 9, "new"),
    ]
    assert len(result.matched_hunk_ids) == 2


def test_verify_claim_rejects_truncated_hunk_uncaptured_lines() -> None:
    patch = _truncated_context_patch()
    file_text = _numbered_text("line", 121)
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": file_text},
        after_text_by_path={"src/app.py": file_text},
    )
    claim = ClaimCandidate(
        claim_id="c-truncated-uncaptured",
        run_id="run-1",
        text="claims an uncaptured line from a truncated hunk",
        source_hunks=[SourceHunk(file="src/app.py", start=121, end=121, side="new")],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": file_text},
        after_text_by_path={"src/app.py": file_text},
    )

    assert result.record.status == "rejected"
    assert result.record.reason_code == "line_outside_hunk"
    assert result.matched_hunk_ids == []
    assert all(
        hunk.hunk_id is None and hunk.hunk_hash is None for hunk in result.record.source_hunks
    )


def test_verify_claim_rejects_truncated_hunk_overlap_with_uncaptured_lines() -> None:
    patch = _truncated_context_patch()
    file_text = _numbered_text("line", 121)
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": file_text},
        after_text_by_path={"src/app.py": file_text},
    )
    claim = ClaimCandidate(
        claim_id="c-truncated-overlap",
        run_id="run-1",
        text="claims a range that overlaps captured and uncaptured lines",
        source_hunks=[SourceHunk(file="src/app.py", start=120, end=121, side="new")],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": file_text},
        after_text_by_path={"src/app.py": file_text},
    )

    assert result.record.status == "rejected"
    assert result.record.reason_code == "line_outside_hunk"
    assert result.matched_hunk_ids == []
    assert all(
        hunk.hunk_id is None and hunk.hunk_hash is None for hunk in result.record.source_hunks
    )


def test_verify_claim_accepts_truncated_hunk_captured_lines() -> None:
    patch = _truncated_context_patch()
    file_text = _numbered_text("line", 121)
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": file_text},
        after_text_by_path={"src/app.py": file_text},
    )
    claim = ClaimCandidate(
        claim_id="c-truncated-captured",
        run_id="run-1",
        text="claims captured lines from a truncated hunk",
        source_hunks=[SourceHunk(file="src/app.py", start=119, end=120, side="new")],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": file_text},
        after_text_by_path={"src/app.py": file_text},
    )

    assert result.record.status == "weak"
    assert [(hunk.start, hunk.end, hunk.side) for hunk in result.record.source_hunks] == [
        (119, 120, "new")
    ]
    assert result.record.source_hunks[0].hunk_id is not None
    assert result.record.source_hunks[0].hunk_hash is not None


@pytest.mark.parametrize(
    ("line_number", "expected_status"),
    [
        (119, "weak"),
        (120, "weak"),
        (121, "rejected"),
    ],
)
def test_verify_claim_respects_truncated_hunk_parsed_upper_boundary(
    line_number: int,
    expected_status: str,
) -> None:
    patch = _truncated_context_patch()
    file_text = _numbered_text("line", 121)
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": file_text},
        after_text_by_path={"src/app.py": file_text},
    )
    claim = ClaimCandidate(
        claim_id=f"c-truncated-boundary-{line_number}",
        run_id="run-1",
        text=f"claims boundary line {line_number}",
        source_hunks=[
            SourceHunk(file="src/app.py", start=line_number, end=line_number, side="new")
        ],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": file_text},
        after_text_by_path={"src/app.py": file_text},
    )

    assert result.record.status == expected_status
    if expected_status == "weak":
        assert [(hunk.start, hunk.end, hunk.side) for hunk in result.record.source_hunks] == [
            (line_number, line_number, "new")
        ]
        assert result.record.source_hunks[0].hunk_id is not None
        assert result.record.source_hunks[0].hunk_hash is not None
    else:
        assert result.record.reason_code == "line_outside_hunk"
        assert result.matched_hunk_ids == []
        assert all(
            hunk.hunk_id is None and hunk.hunk_hash is None for hunk in result.record.source_hunks
        )


def test_verify_claim_rejects_old_side_when_truncated_hunk_only_parsed_new_lines() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,3 @@
+new_1
+new_2
+new_3
[truncated]
"""
    before_text = _numbered_text("old", 3)
    after_text = _numbered_text("new", 3)
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )
    claim = ClaimCandidate(
        claim_id="c-side-mismatch-old",
        run_id="run-1",
        text="claims old-side evidence from a new-only truncated body",
        source_hunks=[SourceHunk(file="src/app.py", start=2, end=2, side="old")],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )

    assert result.record.status == "rejected"
    assert result.record.reason_code == "line_outside_hunk"
    assert result.matched_hunk_ids == []
    assert all(
        hunk.hunk_id is None and hunk.hunk_hash is None for hunk in result.record.source_hunks
    )


def test_verify_claim_rejects_new_side_when_truncated_hunk_only_parsed_old_lines() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,3 @@
-old_1
-old_2
-old_3
[truncated]
"""
    before_text = _numbered_text("old", 3)
    after_text = _numbered_text("new", 3)
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )
    claim = ClaimCandidate(
        claim_id="c-side-mismatch-new",
        run_id="run-1",
        text="claims new-side evidence from an old-only truncated body",
        source_hunks=[SourceHunk(file="src/app.py", start=2, end=2, side="new")],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )

    assert result.record.status == "rejected"
    assert result.record.reason_code == "line_outside_hunk"
    assert result.matched_hunk_ids == []
    assert all(
        hunk.hunk_id is None and hunk.hunk_hash is None for hunk in result.record.source_hunks
    )


def test_verify_claim_rejects_ambiguous_old_path_alias_collision() -> None:
    patch = (
        "diff --git a/src/a.py b/src/b.py\n"
        "similarity index 100%\n"
        "rename from src/a.py\n"
        "rename to src/b.py\n"
        "diff --git a/src/a.py b/src/a.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/src/a.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+fresh = 1\n"
        "+fresh = 2\n"
    )
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/a.py": "def legacy():\n    return 1\n"},
        after_text_by_path={
            "src/b.py": "def legacy():\n    return 1\n",
            "src/a.py": "fresh = 1\nfresh = 2\n",
        },
    )
    claim = ClaimCandidate(
        claim_id="c-ambiguous-path",
        run_id="run-1",
        text="keeps legacy implementation",
        source_hunks=[SourceHunk(file="src/a.py", start=1, end=1)],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/a.py": "def legacy():\n    return 1\n"},
        after_text_by_path={
            "src/b.py": "def legacy():\n    return 1\n",
            "src/a.py": "fresh = 1\nfresh = 2\n",
        },
    )

    assert result.record.status == "rejected"
    assert result.record.reason_code == "evidence_missing"


def test_verify_claim_marks_risky_retry_without_structure_as_contradicted() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
-def helper():
-    return 1
+def helper():
+    return 2
"""
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": "def helper():\n    return 1\n"},
        after_text_by_path={"src/app.py": "def helper():\n    return 2\n"},
    )
    claim = ClaimCandidate(
        claim_id="c1",
        run_id="run-1",
        text="always adds retry backoff for every failure path",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=2)],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": "def helper():\n    return 1\n"},
        after_text_by_path={"src/app.py": "def helper():\n    return 2\n"},
    )

    assert result.record.status == "contradicted"
    assert any(
        item.startswith("missing_retry_structure:") for item in result.record.negative_evidence
    )


def test_verify_claim_flags_deleted_symbol_reference_as_contradicted() -> None:
    patch = """\
diff --git a/src/legacy.py b/src/legacy.py
deleted file mode 100644
--- a/src/legacy.py
+++ /dev/null
@@ -1,2 +0,0 @@ def legacy_api():
-def legacy_api():
-    return 1
"""
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/legacy.py": "def legacy_api():\n    return 1\n"},
    )
    claim = ClaimCandidate(
        claim_id="c1",
        run_id="run-1",
        text="keeps using legacy_api for request handling",
        source_hunks=[SourceHunk(file="src/legacy.py", start=1, end=2)],
        symbols=["legacy_api"],
    )

    result = verify_claim_candidate(claim, line_maps=line_maps, symbols=symbols)

    assert result.record.status == "contradicted"
    assert any(
        item.startswith("deleted_symbol_reference:") for item in result.record.negative_evidence
    )
    assert result.record.extractor == "python_ast"


def test_verify_claim_rejects_unbounded_source_hunk_span() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old = 1
+new = 2
"""
    line_maps, symbols = _build_context(patch, after_text_by_path={"src/app.py": "new = 2\n"})
    claim = ClaimCandidate(
        claim_id="c1",
        run_id="run-1",
        text="invalid huge claim span",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=20_500)],
    )

    result = verify_claim_candidate(claim, line_maps=line_maps, symbols=symbols)

    assert result.record.status == "rejected"
    assert result.record.reason_code == "evidence_missing"
    assert result.record.extractor == "section_header"


def test_verify_claim_rejects_multi_hunk_range_above_audit_limit() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old_first = 1
+new_first = 1
@@ -130 +130 @@
-old_second = 1
+new_second = 1
"""
    before_lines = [
        "old_first = 1",
        *(f"gap_{index}()" for index in range(2, 130)),
        "old_second = 1",
    ]
    after_lines = [
        "new_first = 1",
        *(f"gap_{index}()" for index in range(2, 130)),
        "new_second = 1",
    ]
    before_text = "\n".join(before_lines) + "\n"
    after_text = "\n".join(after_lines) + "\n"
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )
    claim = ClaimCandidate(
        claim_id="c-too-wide",
        run_id="run-1",
        text="claims a source range too wide for audit",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=121, side="new")],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )

    assert result.record.status == "rejected"
    assert result.record.reason_code == "evidence_missing"


def test_verify_claim_rejects_mode_only_file_without_diff_hunks() -> None:
    patch = """\
diff --git a/script.sh b/script.sh
old mode 100644
new mode 100755
"""
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"script.sh": "#!/bin/sh\n"},
        after_text_by_path={"script.sh": "#!/bin/sh\n"},
    )
    claim = ClaimCandidate(
        claim_id="c-mode-only",
        run_id="run-1",
        text="makes script executable",
        source_hunks=[SourceHunk(file="script.sh", start=1, end=1, side="new")],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"script.sh": "#!/bin/sh\n"},
        after_text_by_path={"script.sh": "#!/bin/sh\n"},
    )

    assert result.record.status == "rejected"
    assert result.record.reason_code == "line_outside_hunk"


def test_verify_claim_does_not_bind_ambiguous_fuzzy_basename() -> None:
    patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,8 +1,8 @@\n"
        " class Foo:\n"
        "     def run(self):\n"
        "-        return 1\n"
        "+        return 10\n"
        " \n"
        " class Bar:\n"
        "     def run(self):\n"
        "-        return 2\n"
        "+        return 20\n"
        " \n"
    )
    before_text = (
        "class Foo:\n"
        "    def run(self):\n"
        "        return 1\n\n"
        "class Bar:\n"
        "    def run(self):\n"
        "        return 2\n"
    )
    after_text = (
        "class Foo:\n"
        "    def run(self):\n"
        "        return 10\n\n"
        "class Bar:\n"
        "    def run(self):\n"
        "        return 20\n"
    )
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )
    claim = ClaimCandidate(
        claim_id="c-ambiguous",
        run_id="run-1",
        text="updates run behavior",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=8)],
        symbols=["run"],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )

    assert result.record.status == "not_proven"
    assert result.matched_symbols == []


def test_verify_claim_supports_rename_only_diff_without_hunks() -> None:
    patch = """\
diff --git a/src/old_name.py b/src/new_name.py
similarity index 100%
rename from src/old_name.py
rename to src/new_name.py
"""
    before_text = "def process():\n    return 1\n"
    after_text = "def process():\n    return 1\n"
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/old_name.py": before_text},
        after_text_by_path={"src/new_name.py": after_text},
    )
    claim = ClaimCandidate(
        claim_id="c-rename",
        run_id="run-1",
        text="renames process module without changing behavior",
        source_hunks=[SourceHunk(file="src/new_name.py", start=1, end=2)],
        symbols=["process"],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/old_name.py": before_text},
        after_text_by_path={"src/new_name.py": after_text},
    )

    assert result.record.status == "verified"
    assert result.record.extractor == "python_ast"
    assert result.matched_hunk_ids == []


def test_verify_claim_rejects_source_range_that_only_matches_mixed_old_new_lines() -> None:
    patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +2,2 @@\n"
        "-old = 1\n"
        "-old = 2\n"
        "+new = 1\n"
        "+new = 2\n"
    )
    line_maps, symbols = _build_context(
        patch,
        before_text_by_path={"src/app.py": "old = 1\nold = 2\n"},
        after_text_by_path={"src/app.py": "new = 1\nnew = 2\n"},
    )
    claim = ClaimCandidate(
        claim_id="c-mixed-sides",
        run_id="run-1",
        text="invalid mixed-side claim span",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=3)],
    )

    result = verify_claim_candidate(
        claim,
        line_maps=line_maps,
        symbols=symbols,
        before_text_by_path={"src/app.py": "old = 1\nold = 2\n"},
        after_text_by_path={"src/app.py": "new = 1\nnew = 2\n"},
    )

    assert result.record.status == "rejected"
    assert result.record.reason_code == "line_outside_hunk"
