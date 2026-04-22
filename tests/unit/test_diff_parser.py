from __future__ import annotations

import pytest

from ahadiff.core.errors import InputError
from ahadiff.git.parser import iter_hunks, parse_unified_diff
from ahadiff.git.path_tokens import normalize_diff_path_token


def test_parse_unified_diff_extracts_changed_files_and_section_header() -> None:
    patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -10 +10,2 @@ def retry_with_backoff(max_retries=3):\n"
        "-    return 1\n"
        "+    result = 1\n"
        "+    return result\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 1
    changed_file = changed_files[0]
    assert changed_file.display_path == "src/app.py"
    assert changed_file.change_kind == "modified"
    assert changed_file.is_binary is False
    assert len(changed_file.hunks) == 1

    hunk = changed_file.hunks[0]
    assert hunk.section_header == "def retry_with_backoff(max_retries=3):"
    assert hunk.added_lines == (10, 11)
    assert hunk.deleted_lines == (10,)
    assert hunk.hunk_id.startswith("hunk_")
    assert len(hunk.hunk_hash) == 12


def test_iter_hunks_handles_empty_section_header_and_implicit_counts() -> None:
    patch = (
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -0,0 +1 @@\n"
        "+value = 1\n"
        "@@ -1 +1,2 @@ class Demo:\n"
        "-value = 1\n"
        "+value = 2\n"
        "+extra = 3\n"
    )

    hunks = iter_hunks(patch)

    assert [hunk.section_header for hunk in hunks] == [None, "class Demo:"]
    assert hunks[0].old_count == 0
    assert hunks[0].new_count == 1
    assert hunks[0].added_lines == (1,)
    assert hunks[1].old_count == 1
    assert hunks[1].new_count == 2
    assert hunks[1].deleted_lines == (1,)
    assert hunks[1].added_lines == (1, 2)


def test_parse_unified_diff_marks_rename_and_binary_segments() -> None:
    patch = (
        "diff --git a/src/old_name.py b/src/new_name.py\n"
        "similarity index 100%\n"
        "rename from src/old_name.py\n"
        "rename to src/new_name.py\n"
        "diff --git a/assets/logo.png b/assets/logo.png\n"
        "new file mode 100644\n"
        "Binary files /dev/null and b/assets/logo.png differ\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 2
    renamed_file, binary_file = changed_files
    assert renamed_file.change_kind == "renamed"
    assert renamed_file.old_path == "src/old_name.py"
    assert renamed_file.new_path == "src/new_name.py"
    assert renamed_file.hunks == ()

    assert binary_file.display_path == "assets/logo.png"
    assert binary_file.is_binary is True
    assert binary_file.change_kind == "added"
    assert binary_file.hunks == ()


def test_parse_unified_diff_unquotes_paths_and_stops_hunk_at_next_diff_header() -> None:
    patch = (
        'diff --git "a/my file.py" "b/my file.py"\n'
        '--- "a/my file.py"\n'
        '+++ "b/my file.py"\n'
        "@@ -1 +1 @@ def demo():\n"
        "-    return 1\n"
        "+    return 2\n"
        "diff --git a/next.py b/next.py\n"
        "--- a/next.py\n"
        "+++ b/next.py\n"
        "@@ -1 +1 @@\n"
        "-old = 1\n"
        "+new = 1\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 2
    assert changed_files[0].display_path == "my file.py"
    assert changed_files[0].hunks[0].raw_lines == ("-    return 1", "+    return 2")
    assert changed_files[1].display_path == "next.py"


def test_parse_unified_diff_handles_octal_quoted_paths_and_crlf() -> None:
    patch = (
        'diff --git "a/my\\040file.py" "b/my\\040file.py"\r\n'
        '--- "a/my\\040file.py"\r\n'
        '+++ "b/my\\040file.py"\r\n'
        "@@ -1 +1 @@\r\n"
        "-value = 1\r\n"
        "+value = 2\r\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 1
    assert changed_files[0].display_path == "my file.py"
    assert changed_files[0].hunks[0].added_lines == (1,)


def test_parse_unified_diff_preserves_quoted_binary_paths_without_hunks() -> None:
    patch = (
        'diff --git "a/my file.png" "b/my file.png"\n'
        'Binary files "a/my file.png" and "b/my file.png" differ\n'
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 1
    assert changed_files[0].display_path == "my file.png"
    assert changed_files[0].old_path == "my file.png"
    assert changed_files[0].new_path == "my file.png"
    assert changed_files[0].hunks == ()


def test_normalize_diff_path_token_handles_literal_backslash_and_c_style_escapes() -> None:
    assert normalize_diff_path_token('"a/my\\\\040file.py"', prefix="a/") == r"my\040file.py"
    assert normalize_diff_path_token('"a/tab\\tname.py"', prefix="a/") == "tab\tname.py"
    assert normalize_diff_path_token('"a/new\\nline.py"', prefix="a/") == "new\nline.py"
    assert normalize_diff_path_token('"a/car\\rriage.py"', prefix="a/") == "car\rriage.py"


def test_parse_unified_diff_does_not_split_control_looking_added_lines() -> None:
    patch = (
        "diff --git a/demo.py b/demo.py\n"
        "--- a/demo.py\n"
        "+++ b/demo.py\n"
        "@@ -1 +1,3 @@ def demo():\n"
        '-    return "old"\n'
        '+    return "diff --git a/fake b/fake"\n'
        '+    marker = "@@ -1 +1 @@"\n'
        "+    return marker\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 1
    assert changed_files[0].display_path == "demo.py"
    assert changed_files[0].hunks[0].raw_lines == (
        '-    return "old"',
        '+    return "diff --git a/fake b/fake"',
        '+    marker = "@@ -1 +1 @@"',
        "+    return marker",
    )


def test_parse_unified_diff_rejects_malformed_hunk_header() -> None:
    patch = "--- a/demo.py\n+++ b/demo.py\n@@ invalid @@\n+value = 1\n"

    with pytest.raises(InputError, match="invalid unified diff hunk header"):
        parse_unified_diff(patch)


def test_parse_unified_diff_rejects_non_truncated_hunk_body_count_mismatch() -> None:
    patch = (
        "--- a/demo.py\n"
        "+++ b/demo.py\n"
        "@@ -1,1 +1,3 @@\n"
        "-old = 1\n"
        "value = 2\n"
        "extra = 3\n"
    )

    with pytest.raises(InputError, match="hunk body does not match header counts"):
        parse_unified_diff(patch)


def test_parse_unified_diff_allows_truncated_hunk_body_count_mismatch() -> None:
    patch = (
        "--- a/demo.py\n"
        "+++ b/demo.py\n"
        "@@ -1,1 +1,3 @@\n"
        "-old = 1\n"
        "+value = 2\n"
        "[truncated]\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 1
    assert changed_files[0].hunks[0].added_lines == (1,)
