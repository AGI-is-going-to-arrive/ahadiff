from __future__ import annotations

from ahadiff.git.hunk_hash import compute_hunk_hash, normalize_hunk_for_hash


def test_hunk_hash_is_stable_across_lf_and_crlf() -> None:
    lf_hash = compute_hunk_hash(
        header="@@ -1 +1 @@ def demo():",
        body_lines=["-    value = 1\n", "+    value = 2\n"],
    )
    crlf_hash = compute_hunk_hash(
        header="@@ -1 +1 @@ def demo():",
        body_lines=["-    value = 1\r\n", "+    value = 2\r\n"],
    )

    assert lf_hash == crlf_hash


def test_hunk_hash_ignores_truncated_marker_and_no_newline_marker() -> None:
    normalized = normalize_hunk_for_hash(
        header="@@ -1 +1 @@ def demo():",
        body_lines=["+    value = 2\n", "[truncated]", "\\ No newline at end of file"],
    )

    assert normalized == ("section:def demo():", "+    value = 2")


def test_hunk_hash_is_invariant_to_marker_injection_matrix() -> None:
    header = "@@ -1 +1 @@ def demo():"
    baseline = compute_hunk_hash(
        header=header,
        body_lines=["-    value = 1\n", "+    value = 2\n"],
    )

    variants = (
        ["-    value = 1\n", "+    value = 2\n"],
        ["-    value = 1\r\n", "[truncated]", "+    value = 2\r\n"],
        ["-    value = 1\n", "\\ No newline at end of file", "+    value = 2\n"],
        ["[truncated]", "-    value = 1\r\n", "+    value = 2\n", "[truncated]"],
    )

    for body_lines in variants:
        assert compute_hunk_hash(header=header, body_lines=body_lines) == baseline


def test_hunk_hash_ignores_hunk_numeric_ranges_when_body_and_section_match() -> None:
    left = compute_hunk_hash(
        header="@@ -1 +1 @@ def demo():",
        body_lines=["-    value = 1\n", "+    value = 2\n"],
    )
    right = compute_hunk_hash(
        header="@@ -100 +250 @@ def demo():",
        body_lines=["-    value = 1\n", "+    value = 2\n"],
    )

    assert left == right
