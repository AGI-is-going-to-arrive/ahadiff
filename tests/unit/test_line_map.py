from __future__ import annotations

import pytest

from ahadiff.core.errors import InputError
from ahadiff.git.line_map import (
    LINE_MAP_SCHEMA,
    LINE_MAP_SCHEMA_VERSION,
    build_file_id_index,
    build_line_map,
    serialize_line_map_payload,
)


def test_build_line_map_uses_casefolded_file_identity_and_hunk_ranges() -> None:
    patch = (
        "diff --git a/src/App.py b/src/App.py\n"
        "--- a/src/App.py\n"
        "+++ b/src/App.py\n"
        "@@ -3,2 +3,3 @@ def render_card():\n"
        "-    return old_value\n"
        "+    card = new_value\n"
        "+    return card\n"
    )

    line_map = build_line_map(patch)

    assert len(line_map) == 1
    file_map = line_map[0]
    assert file_map.display_path == "src/App.py"
    assert len(file_map.file_id) == 12
    assert file_map.path_identity_key == "src/app.py"
    assert len(file_map.hunks) == 1

    hunk = file_map.hunks[0]
    assert hunk.old_start == 3
    assert hunk.old_end == 4
    assert hunk.new_start == 3
    assert hunk.new_end == 5
    assert hunk.added_lines == (3, 4)
    assert hunk.deleted_lines == (3,)


def test_build_file_id_index_rejects_case_insensitive_collisions() -> None:
    with pytest.raises(InputError, match="case-insensitive path collision"):
        build_file_id_index(["src/Foo.py", "src/foo.py"])


def test_build_line_map_uses_old_span_for_deleted_files() -> None:
    patch = (
        "diff --git a/src/obsolete.py b/src/obsolete.py\n"
        "deleted file mode 100644\n"
        "--- a/src/obsolete.py\n"
        "+++ /dev/null\n"
        "@@ -7,2 +0,0 @@ class Obsolete:\n"
        "-    first = 1\n"
        "-    second = 2\n"
    )

    file_map = build_line_map(patch)[0]
    hunk = file_map.hunks[0]

    assert file_map.change_kind == "deleted"
    assert hunk.old_start == 7
    assert hunk.old_end == 8
    assert hunk.new_start == 0
    assert hunk.new_end == -1
    assert hunk.deleted_lines == (7, 8)


def test_serialize_line_map_payload_wraps_schema_and_files() -> None:
    patch = (
        "diff --git a/src/demo.py b/src/demo.py\n"
        "--- a/src/demo.py\n"
        "+++ b/src/demo.py\n"
        "@@ -1 +1 @@ def demo():\n"
        "-    return 1\n"
        "+    return 2\n"
    )

    payload = serialize_line_map_payload(build_line_map(patch))

    assert payload["artifact"] == "line_map"
    assert payload["schema"] == LINE_MAP_SCHEMA
    assert payload["schema_version"] == LINE_MAP_SCHEMA_VERSION
    assert payload["files"][0]["display_path"] == "src/demo.py"
    assert payload["files"][0]["hunks"][0]["added_lines"] == [1]
