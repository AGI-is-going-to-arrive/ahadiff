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


def test_parse_unified_diff_tolerates_index_line_in_body() -> None:
    patch = (
        "diff --git a/file.py b/file.py\n"
        "index abc1234..def5678 100644\n"
        "--- a/file.py\n"
        "+++ b/file.py\n"
        "@@ -1,3 +1,4 @@\n"
        "index abc1234..def5678 100644\n"
        "--- a/file.py\n"
        "+++ b/file.py\n"
        " line1\n"
        "+added\n"
        " line2\n"
        " line3\n"
        "diff --git a/other.py b/other.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/other.py\n"
        "+++ b/other.py\n"
        "@@ -5,2 +5,3 @@\n"
        " keep\n"
        "+extra\n"
        " still\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 2
    leaked_metadata_file, normal_file = changed_files
    assert leaked_metadata_file.display_path == "file.py"
    assert normal_file.display_path == "other.py"

    leaked_hunk = leaked_metadata_file.hunks[0]
    assert leaked_hunk.added_lines == (2,)
    assert leaked_hunk.context_old_lines == (1, 2, 3)
    assert leaked_hunk.context_new_lines == (1, 3, 4)
    assert len(leaked_hunk.lines) == 4

    normal_hunk = normal_file.hunks[0]
    assert normal_hunk.added_lines == (6,)
    assert normal_hunk.context_old_lines == (5, 6)
    assert normal_hunk.context_new_lines == (5, 7)


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


def test_parse_unified_diff_preserves_quoted_literal_backslash_paths() -> None:
    patch = (
        'diff --git "a/my\\\\file.py" "b/my\\\\file.py"\n'
        '--- "a/my\\\\file.py"\n'
        '+++ "b/my\\\\file.py"\n'
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 1
    assert changed_files[0].old_path == r"my\file.py"
    assert changed_files[0].new_path == r"my\file.py"
    assert changed_files[0].display_path == r"my\file.py"
    assert changed_files[0].hunks[0].path == r"my\file.py"


def test_parse_unified_diff_normalizes_backslash_paths() -> None:
    patch = (
        r"diff --git a\src\old.py b\src\new.py"
        "\n"
        r"--- a\src\old.py"
        "\n"
        r"+++ b\src\new.py"
        "\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 1
    assert changed_files[0].old_path == "src/old.py"
    assert changed_files[0].new_path == "src/new.py"
    assert changed_files[0].display_path == "src/new.py"
    assert changed_files[0].hunks[0].path == "src/new.py"


def test_parse_unified_diff_handles_crlf_plain_headers() -> None:
    patch = (
        "diff --git a/src/crlf.py b/src/crlf.py\r\n"
        "--- a/src/crlf.py\r\n"
        "+++ b/src/crlf.py\r\n"
        "@@ -1 +1 @@\r\n"
        "-value = 1\r\n"
        "+value = 2\r\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 1
    assert changed_files[0].display_path == "src/crlf.py"
    assert changed_files[0].hunks[0].raw_lines == ("-value = 1", "+value = 2")


def test_parse_unified_diff_strips_utf8_bom_from_first_header() -> None:
    patch = (
        "\ufeffdiff --git a/src/bom.py b/src/bom.py\n"
        "--- a/src/bom.py\n"
        "+++ b/src/bom.py\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 1
    assert changed_files[0].display_path == "src/bom.py"
    assert changed_files[0].headers[0] == "diff --git a/src/bom.py b/src/bom.py"


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
    assert normalize_diff_path_token('"a/my\\\\file.py"', prefix="a/") == r"my\file.py"
    assert normalize_diff_path_token('"a/tab\\tname.py"', prefix="a/") == "tab\tname.py"
    assert normalize_diff_path_token('"a/new\\nline.py"', prefix="a/") == "new\nline.py"
    assert normalize_diff_path_token('"a/car\\rriage.py"', prefix="a/") == "car\rriage.py"


def test_normalize_diff_path_token_converts_windows_separators_to_posix() -> None:
    assert normalize_diff_path_token(r"a\src\demo.py", prefix="a/") == "src/demo.py"
    assert normalize_diff_path_token(r"b\src\..\demo.py", prefix="b/") == "demo.py"
    assert normalize_diff_path_token(r"C:\repo\demo.py") is None
    assert normalize_diff_path_token(r"\\server\share\demo.py") is None


def test_normalize_diff_path_token_collapses_path_traversal_segments() -> None:
    assert normalize_diff_path_token("b/src/../safe/demo.py", prefix="b/") == "safe/demo.py"
    assert normalize_diff_path_token("a/src/../demo.py", prefix="a/") == "demo.py"
    assert normalize_diff_path_token("../../outside.py") is None
    assert normalize_diff_path_token("/etc/passwd") is None
    assert normalize_diff_path_token("../..") is None


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


def test_parse_unified_diff_rejects_combined_diff() -> None:
    patch = (
        "diff --git a/demo.py b/demo.py\n"
        "index 1111111,2222222..3333333\n"
        "--- a/demo.py\n"
        "+++ b/demo.py\n"
        "@@@ -1,1 -1,1 +1,2 @@@ def demo():\n"
        "  value = 1\n"
        "+ value = 2\n"
    )

    with pytest.raises(InputError, match="combined diff format is not supported"):
        parse_unified_diff(patch)


def test_parse_unified_diff_allows_triple_at_in_content_line() -> None:
    """Content starting with @@@ after a +/- prefix is NOT a combined diff marker."""
    patch = (
        "diff --git a/demo.py b/demo.py\n"
        "--- a/demo.py\n"
        "+++ b/demo.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-old = 1\n"
        "+@@@ not a combined diff marker\n"
        " keep\n"
    )
    files = parse_unified_diff(patch)
    assert len(files) == 1
    hunk = files[0].hunks[0]
    assert hunk.added_lines == (1,)
    assert hunk.lines[0].content == "old = 1"
    assert hunk.lines[1].content == "@@@ not a combined diff marker"


def test_parse_unified_diff_rejects_non_truncated_hunk_body_count_mismatch() -> None:
    patch = "--- a/demo.py\n+++ b/demo.py\n@@ -1,1 +1,3 @@\n-old = 1\n+value = 2\n+extra = 3\n"

    with pytest.raises(InputError, match="hunk body does not match header counts"):
        parse_unified_diff(patch)


def test_parse_unified_diff_rejects_hunk_lines_missing_prefix() -> None:
    patch = (
        "--- a/demo.py\n+++ b/../safe/demo.py\n@@ -1,2 +1,2 @@\n-old = 1\nshared = 2\n+new = 3\n"
    )

    with pytest.raises(InputError, match="missing prefix"):
        parse_unified_diff(patch)


def test_parse_unified_diff_scrubs_traversal_only_paths_to_unknown() -> None:
    patch = (
        "diff --git a/../../etc/passwd b/../../etc/passwd\n"
        "--- a/../../etc/passwd\n"
        "+++ b/../../etc/passwd\n"
        "@@ -1 +1 @@\n"
        "-root:x\n"
        "+root:*:x\n"
    )

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 1
    assert changed_files[0].old_path is None
    assert changed_files[0].new_path is None
    assert changed_files[0].display_path == "__unknown__"


def test_parse_unified_diff_allows_truncated_hunk_body_count_mismatch() -> None:
    patch = "--- a/demo.py\n+++ b/../demo.py\n@@ -1,1 +1,3 @@\n-old = 1\n+value = 2\n[truncated]\n"

    changed_files = parse_unified_diff(patch)

    assert len(changed_files) == 1
    assert changed_files[0].display_path == "demo.py"
    assert changed_files[0].hunks[0].added_lines == (1,)


def test_parse_unicode_filenames() -> None:
    patch = (
        "diff --git a/文档/说明.md b/文档/说明.md\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        "+++ b/文档/说明.md\n"
        "@@ -0,0 +1 @@\n"
        "+你好\n"
    )

    result = parse_unified_diff(patch)

    assert len(result) == 1
    assert result[0].new_path == "文档/说明.md"


def test_parse_emoji_filenames() -> None:
    patch = (
        "diff --git a/🚀/launch.py b/🚀/launch.py\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        "+++ b/🚀/launch.py\n"
        "@@ -0,0 +1 @@\n"
        "+print('launch')\n"
    )

    result = parse_unified_diff(patch)

    assert len(result) == 1
    assert result[0].new_path is not None
    assert "🚀" in result[0].new_path
