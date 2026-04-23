from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ahadiff.claims.extract import (
    load_line_map_records,
    load_symbol_records,
    load_text_map,
    parse_claim_candidates_text,
    write_claim_candidates_jsonl,
)
from ahadiff.claims.schema import ClaimCandidate
from ahadiff.cli import app
from ahadiff.contracts import SourceHunk
from ahadiff.git.line_map import build_line_map, serialize_line_map_payload
from ahadiff.git.parser import parse_unified_diff
from ahadiff.git.symbols import extract_symbols, serialize_symbols_payload

if TYPE_CHECKING:
    from pathlib import Path


def test_parse_claim_candidates_text_handles_fenced_json() -> None:
    payload = """\
```json
{
  "claims": [
    {
      "text": "updates retry behavior",
      "source_hunks": [{"file": "src/app.py", "start": 1, "end": 2, "side": "new"}],
      "symbols": ["retry_once"]
    }
  ]
}
```
"""

    candidates = parse_claim_candidates_text(payload, default_run_id="run-1")

    assert len(candidates) == 1
    assert candidates[0].run_id == "run-1"
    assert candidates[0].claim_id == "run-1-claim-001"
    assert candidates[0].source_hunks[0].side == "new"


def test_parse_claim_candidates_text_handles_jsonl() -> None:
    payload = "\n".join(
        [
            json.dumps(
                {
                    "text": "updates retry behavior",
                    "source_hunks": [{"file": "src/app.py", "start": 1, "end": 2}],
                }
            ),
            json.dumps(
                {
                    "text": "adds retry symbol",
                    "source_hunks": [{"file": "src/app.py", "start": 1, "end": 2}],
                    "symbols": ["retry_once"],
                }
            ),
        ]
    )

    candidates = parse_claim_candidates_text(payload, default_run_id="run-2")

    assert [item.claim_id for item in candidates] == [
        "run-2-claim-001",
        "run-2-claim-002",
    ]


def test_parse_claim_candidates_text_ignores_non_json_fence_before_json() -> None:
    payload = """\
```python
print("not json")
```

```json
[
  {
    "text": "updates retry behavior",
    "source_hunks": [{"file": "src/app.py", "start": 1, "end": 2}]
  }
]
```
"""

    candidates = parse_claim_candidates_text(payload, default_run_id="run-fence")

    assert len(candidates) == 1
    assert candidates[0].run_id == "run-fence"


def test_parse_claim_candidates_text_rejects_invalid_jsonl() -> None:
    with pytest.raises(Exception, match="invalid claim candidate JSONL line 1"):
        parse_claim_candidates_text("not-json")


def test_parse_claim_candidates_text_requires_run_id_without_default() -> None:
    payload = json.dumps(
        [
            {
                "claim_id": "claim-1",
                "text": "updates retry behavior",
                "source_hunks": [{"file": "src/app.py", "start": 1, "end": 2}],
            }
        ]
    )

    with pytest.raises(Exception, match="missing run_id"):
        parse_claim_candidates_text(payload)


def test_claims_cli_verifies_candidates_and_writes_claims_jsonl(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = workspace_root / ".ahadiff" / "runs" / "run_1"
    run_path.mkdir(parents=True)
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
    changed_files = parse_unified_diff(patch)
    line_maps = build_line_map(changed_files)
    symbols = extract_symbols(
        changed_files,
        before_text_by_path={"src/app.py": "def retry_once():\n    return 1\n"},
        after_text_by_path={"src/app.py": "def retry_once():\n    return 2\n"},
    )
    (run_path / "line_map.json").write_text(
        json.dumps(serialize_line_map_payload(line_maps), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "symbols.json").write_text(
        json.dumps(serialize_symbols_payload(symbols), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "before_text_by_path.json").write_text(
        json.dumps(
            {
                "artifact": "before_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": {"src/app.py": "def retry_once():\n    return 1\n"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_path / "after_text_by_path.json").write_text(
        json.dumps(
            {
                "artifact": "after_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": {"src/app.py": "def retry_once():\n    return 2\n"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_claim_candidates_jsonl(
        run_path / "claims.raw.jsonl",
        [
            ClaimCandidate(
                claim_id="claim-1",
                run_id="run_1",
                text="updates retry logic",
                source_hunks=[SourceHunk(file="src/app.py", start=1, end=2)],
                symbols=["Retry Once"],
            )
        ],
    )

    runner = CliRunner()
    result = runner.invoke(
        app(),
        ["claims", "run_1", "--repo-root", str(workspace_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output_path = run_path / "claims.jsonl"
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["status"] == "verified"
    assert "Claim verification summary" in result.stdout


def test_claims_cli_uses_persisted_text_maps_for_negative_scan(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = workspace_root / ".ahadiff" / "runs" / "run_2"
    run_path.mkdir(parents=True)
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
    changed_files = parse_unified_diff(patch)
    line_maps = build_line_map(changed_files)
    symbols = extract_symbols(
        changed_files,
        before_text_by_path={"src/app.py": "def helper():\n    return 1\n"},
        after_text_by_path={"src/app.py": "def helper():\n    return 2\n"},
    )
    (run_path / "line_map.json").write_text(
        json.dumps(serialize_line_map_payload(line_maps), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "symbols.json").write_text(
        json.dumps(serialize_symbols_payload(symbols), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "before_text_by_path.json").write_text(
        json.dumps(
            {
                "artifact": "before_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": {"src/app.py": "def helper():\n    return 1\n"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_path / "after_text_by_path.json").write_text(
        json.dumps(
            {
                "artifact": "after_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": {"src/app.py": "def helper():\n    return 2\n"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_claim_candidates_jsonl(
        run_path / "claims.raw.jsonl",
        [
            ClaimCandidate(
                claim_id="claim-2",
                run_id="run_2",
                text="always adds retry backoff for every failure path",
                source_hunks=[SourceHunk(file="src/app.py", start=1, end=2)],
            )
        ],
    )

    runner = CliRunner()
    result = runner.invoke(
        app(),
        ["claims", "run_2", "--repo-root", str(workspace_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    payload = json.loads((run_path / "claims.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert payload["status"] == "contradicted"
    assert any(item.startswith("missing_retry_structure:") for item in payload["negative_evidence"])


def test_claims_cli_uses_available_single_side_text_map(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = workspace_root / ".ahadiff" / "runs" / "run_3"
    run_path.mkdir(parents=True)
    patch = """\
diff --git a/src/legacy.py b/src/legacy.py
deleted file mode 100644
--- a/src/legacy.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def helper():
-    return 1
"""
    changed_files = parse_unified_diff(patch)
    line_maps = build_line_map(changed_files)
    symbols = extract_symbols(
        changed_files,
        before_text_by_path={"src/legacy.py": "def helper():\n    return 1\n"},
    )
    (run_path / "line_map.json").write_text(
        json.dumps(serialize_line_map_payload(line_maps), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "symbols.json").write_text(
        json.dumps(serialize_symbols_payload(symbols), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "before_text_by_path.json").write_text(
        json.dumps(
            {
                "artifact": "before_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": {"src/legacy.py": "def helper():\n    return 1\n"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_claim_candidates_jsonl(
        run_path / "claims.raw.jsonl",
        [
            ClaimCandidate(
                claim_id="claim-3",
                run_id="run_3",
                text="adds import dependency handling",
                source_hunks=[SourceHunk(file="src/legacy.py", start=1, end=2)],
            )
        ],
    )

    runner = CliRunner()
    result = runner.invoke(
        app(),
        ["claims", "run_3", "--repo-root", str(workspace_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    payload = json.loads((run_path / "claims.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert payload["status"] == "contradicted"
    assert any(
        item.startswith("missing_import_structure:") for item in payload["negative_evidence"]
    )
    assert "partially degraded" in result.stdout


def test_claims_cli_rejects_mismatched_run_id_payload(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = workspace_root / ".ahadiff" / "runs" / "run_4"
    run_path.mkdir(parents=True)
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old = 1
+new = 2
"""
    changed_files = parse_unified_diff(patch)
    line_maps = build_line_map(changed_files)
    symbols = extract_symbols(changed_files, after_text_by_path={"src/app.py": "new = 2\n"})
    (run_path / "line_map.json").write_text(
        json.dumps(serialize_line_map_payload(line_maps), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "symbols.json").write_text(
        json.dumps(serialize_symbols_payload(symbols), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "before_text_by_path.json").write_text(
        json.dumps(
            {
                "artifact": "before_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": {"src/app.py": "old = 1\n"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_path / "after_text_by_path.json").write_text(
        json.dumps(
            {
                "artifact": "after_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": {"src/app.py": "new = 2\n"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_claim_candidates_jsonl(
        run_path / "claims.raw.jsonl",
        [
            ClaimCandidate(
                claim_id="claim-4",
                run_id="other_run",
                text="updates app constant",
                source_hunks=[SourceHunk(file="src/app.py", start=1, end=1)],
            )
        ],
    )

    runner = CliRunner()
    result = runner.invoke(
        app(),
        ["claims", "run_4", "--repo-root", str(workspace_root)],
    )

    assert result.exit_code == 1
    assert not (run_path / "claims.jsonl").exists()


def test_claims_cli_rejects_path_traversal_run_id(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    (workspace_root / ".ahadiff" / "runs").mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        ["claims", "../outside-run", "--repo-root", str(workspace_root)],
    )

    assert result.exit_code == 1
    assert not (tmp_path / "outside-run" / "claims.jsonl").exists()


def test_parse_claim_candidates_rejects_duplicate_claim_ids() -> None:
    payload = [
        {
            "claim_id": "dup",
            "run_id": "run-dup",
            "text": "first",
            "source_hunks": [{"file": "src/app.py", "start": 1, "end": 1}],
        },
        {
            "claim_id": "dup",
            "run_id": "run-dup",
            "text": "second",
            "source_hunks": [{"file": "src/app.py", "start": 1, "end": 1}],
        },
    ]

    with pytest.raises(Exception, match="duplicate claim_id"):
        parse_claim_candidates_text(json.dumps(payload))


def test_load_text_map_rejects_wrong_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "before_text_by_path.json"
    path.write_text(
        json.dumps(
            {
                "artifact": "before_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 999,
                "texts": {"src/app.py": "value = 1\n"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="schema_version"):
        load_text_map(path, expected_artifact="before_text_by_path")


def test_load_text_map_rejects_wrong_artifact(tmp_path: Path) -> None:
    path = tmp_path / "before_text_by_path.json"
    path.write_text(
        json.dumps(
            {
                "artifact": "wrong_artifact",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": {"src/app.py": "value = 1\n"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="unexpected text map artifact"):
        load_text_map(path, expected_artifact="before_text_by_path")


def test_load_text_map_rejects_non_string_entries(tmp_path: Path) -> None:
    path = tmp_path / "before_text_by_path.json"
    path.write_text(
        json.dumps(
            {
                "artifact": "before_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": {"src/app.py": 123},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="string-to-string"):
        load_text_map(path, expected_artifact="before_text_by_path")


def test_load_line_map_records_rejects_wrong_schema(tmp_path: Path) -> None:
    path = tmp_path / "line_map.json"
    path.write_text(
        json.dumps(
            {
                "artifact": "line_map",
                "schema": "wrong.line_map",
                "schema_version": 1,
                "files": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="unexpected line_map schema"):
        load_line_map_records(path)


def test_load_symbol_records_rejects_wrong_schema(tmp_path: Path) -> None:
    path = tmp_path / "symbols.json"
    path.write_text(
        json.dumps(
            {
                "artifact": "symbols",
                "schema": "wrong.symbols",
                "schema_version": 1,
                "symbols": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="unexpected symbols schema"):
        load_symbol_records(path)
