from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from ahadiff import cli as cli_module
from ahadiff.claims import extract as extract_module
from ahadiff.claims import runtime as claim_runtime_module
from ahadiff.claims.extract import (
    load_claim_candidates,
    load_line_map_records,
    load_symbol_records,
    load_text_map,
    parse_claim_candidates_text,
    write_claim_candidates_jsonl,
)
from ahadiff.claims.runtime import extract_claim_candidates_from_run, load_claim_extract_prompt
from ahadiff.claims.schema import ClaimCandidate
from ahadiff.cli import app
from ahadiff.contracts import ProviderConfig, SourceHunk
from ahadiff.core.config import SecurityConfig
from ahadiff.core.errors import InputError
from ahadiff.git.line_map import build_line_map, serialize_line_map_payload
from ahadiff.git.parser import parse_unified_diff
from ahadiff.git.symbols import (
    SymbolRange,
    SymbolRecord,
    extract_symbols,
    serialize_symbols_payload,
)


def _write_claim_run_artifacts(
    workspace_root: Path,
    run_id: str,
    *,
    run_path: Path | None = None,
    metadata_overrides: dict[str, object] | None = None,
) -> Path:
    target_run_path = run_path or workspace_root / ".ahadiff" / "runs" / run_id
    target_run_path.mkdir(parents=True)
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
    before_text = "def retry_once():\n    return 1\n"
    after_text = "def retry_once():\n    return 2\n"
    changed_files = parse_unified_diff(patch)
    line_maps = build_line_map(changed_files)
    symbols = extract_symbols(
        changed_files,
        before_text_by_path={"src/app.py": before_text},
        after_text_by_path={"src/app.py": after_text},
    )
    metadata: dict[str, object] = {
        "run_id": run_id,
        "source_kind": "git_ref",
        "source_ref": "abc1234",
        "capability_level": 3,
        "degraded_flags": {},
        "privacy_mode": "strict_local",
    }
    if metadata_overrides:
        metadata.update(metadata_overrides)
    (target_run_path / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target_run_path / "patch.diff").write_text(patch, encoding="utf-8")
    (target_run_path / "line_map.json").write_text(
        json.dumps(serialize_line_map_payload(line_maps), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target_run_path / "symbols.json").write_text(
        json.dumps(serialize_symbols_payload(symbols), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target_run_path / "before_text_by_path.json").write_text(
        json.dumps(
            {
                "artifact": "before_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": {"src/app.py": before_text},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (target_run_path / "after_text_by_path.json").write_text(
        json.dumps(
            {
                "artifact": "after_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": {"src/app.py": after_text},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return target_run_path


def _write_verified_candidate(run_path: Path, run_id: str) -> Path:
    output_path = run_path / "claims.raw.jsonl"
    write_claim_candidates_jsonl(
        output_path,
        [
            ClaimCandidate(
                claim_id=f"{run_id}-claim-1",
                run_id=run_id,
                text="updates retry logic",
                source_hunks=[SourceHunk(file="src/app.py", start=1, end=2, side="new")],
                symbols=["retry_once"],
            )
        ],
        overwrite=True,
    )
    return output_path


def _claim_extract_response(run_id: str) -> dict[str, object]:
    return {
        "model": "gpt-5.4-mini",
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "claims": [
                                {
                                    "claim_id": f"{run_id}-claim-1",
                                    "run_id": run_id,
                                    "text": "updates retry logic",
                                    "source_hunks": [
                                        {
                                            "file": "src/app.py",
                                            "start": 1,
                                            "end": 2,
                                            "side": "new",
                                        }
                                    ],
                                    "symbols": ["retry_once"],
                                }
                            ]
                        }
                    )
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
    }


def test_packaged_claim_extract_prompt_matches_repo_prompt() -> None:
    repo_prompt = Path("prompts/claim_extract.md").read_text(encoding="utf-8")
    package_prompt = files("ahadiff").joinpath("prompts", "claim_extract.md")

    assert package_prompt.is_file()
    assert package_prompt.read_text(encoding="utf-8") == repo_prompt
    assert load_claim_extract_prompt() == repo_prompt


def test_load_json_rejects_symlink_artifact(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text('{"ok": true}', encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(InputError, match="must not be a symlink"):
        extract_module._load_json(link)  # pyright: ignore[reportPrivateUsage]


def test_load_claim_candidates_rejects_symlink_artifact(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text(
        json.dumps(
            {
                "claim_id": "claim-1",
                "run_id": "run-1",
                "text": "updates retry logic",
                "source_hunks": [{"file": "src/app.py", "start": 1, "end": 1}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    link = tmp_path / "claims.raw.jsonl"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(InputError, match="must not be a symlink"):
        load_claim_candidates(link, default_run_id="run-1")


def test_load_json_rejects_file_swapped_after_lstat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.json"
    replacement = tmp_path / "replacement.json"
    target.write_text('{"ok": true}', encoding="utf-8")
    replacement.write_text('{"evil": true}', encoding="utf-8")
    real_open = extract_module.os.open

    def fake_open(
        path_arg: str | bytes | os.PathLike[str],
        flags: int,
        *args: Any,
        **kwargs: Any,
    ) -> int:
        if os.fspath(path_arg) == str(target):
            return real_open(str(replacement), flags, *args, **kwargs)
        return real_open(path_arg, flags, *args, **kwargs)

    monkeypatch.setattr(extract_module.os, "open", fake_open)

    with pytest.raises(InputError, match="changed during validation"):
        extract_module._load_json(target)  # pyright: ignore[reportPrivateUsage]


def test_load_json_rejects_oversized_artifact_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.json"
    target.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(extract_module, "_MAX_ARTIFACT_BYTES", 4)

    def fail_open(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("oversized artifact should be rejected before open")

    monkeypatch.setattr(extract_module.os, "open", fail_open)

    with pytest.raises(InputError, match="artifact file too large"):
        extract_module._load_json(target)  # pyright: ignore[reportPrivateUsage]


def test_extract_claim_candidates_from_run_rejects_symlink_patch_before_provider(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_symlink_patch"
    run_path = _write_claim_run_artifacts(workspace_root, run_id)
    external = tmp_path / "outside.diff"
    external.write_text("SECRET-FROM-OUTSIDE\n", encoding="utf-8")
    (run_path / "patch.diff").unlink()
    try:
        (run_path / "patch.diff").symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    provider_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_called
        provider_called = True
        return httpx.Response(200, json=_claim_extract_response(run_id))

    with (
        httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client,
        pytest.raises(InputError, match="must not be a symlink"),
    ):
        extract_claim_candidates_from_run(
            run_id=run_id,
            run_path=run_path,
            workspace_root=workspace_root,
            provider_config=ProviderConfig(
                provider_class="openai",
                model_name="gpt-5.4-mini",
                base_url="http://127.0.0.1:8000",
                api_key_env="AHADIFF_PROVIDER_API_KEY",
            ),
            api_key="test-key",
            security_config=SecurityConfig(),
            output_path=run_path / "claims.raw.jsonl",
            client=client,
        )

    assert provider_called is False


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


def test_parse_claim_candidates_text_accepts_tree_sitter_extractor() -> None:
    payload = json.dumps(
        {
            "text": "updates renderCard behavior",
            "extractor": "tree_sitter",
            "source_hunks": [{"file": "src/widget.ts", "start": 1, "end": 3}],
            "symbols": ["renderCard"],
        }
    )

    candidates = parse_claim_candidates_text(payload, default_run_id="run-tree")

    assert len(candidates) == 1
    assert candidates[0].extractor == "tree_sitter"


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


def test_parse_claim_candidates_text_prefers_later_real_claims_over_schema_example() -> None:
    payload = """\
The response contains an example first.

```json
{
  "claims": [
    {
      "text": "SCHEMA EXAMPLE SHOULD NOT WIN",
      "source_hunks": [{"file": "schema.py", "start": 1, "end": 1}]
    }
  ]
}
```

Final answer:
{
  "claims": [
    {
      "text": "real generated claim",
      "source_hunks": [{"file": "src/app.py", "start": 2, "end": 3, "side": "new"}]
    }
  ]
}
"""

    candidates = parse_claim_candidates_text(payload, default_run_id="run-final")

    assert len(candidates) == 1
    assert candidates[0].text == "real generated claim"
    assert candidates[0].source_hunks[0].file == "src/app.py"


def test_parse_claim_candidates_text_unwraps_provider_output_claims() -> None:
    payload = json.dumps(
        {
            "output": {
                "claims": [
                    {
                        "text": "wrapped claim",
                        "source_hunks": [
                            {"file": "src/app.py", "start": 4, "end": 5, "side": "new"}
                        ],
                    }
                ]
            }
        }
    )

    candidates = parse_claim_candidates_text(payload, default_run_id="run-wrapper")

    assert len(candidates) == 1
    assert candidates[0].text == "wrapped claim"
    assert candidates[0].run_id == "run-wrapper"


def test_parse_claim_candidates_text_rejects_invalid_jsonl() -> None:
    with pytest.raises(Exception, match="invalid claim candidate JSONL line 1"):
        parse_claim_candidates_text("not-json")


def test_parse_claim_candidates_text_recovers_truncated_envelope() -> None:
    """Truncated JSON envelope with complete claims should recover."""
    truncated = (
        '{"claims":['
        '{"claim_id":"c1","run_id":"run-t","text":"first claim",'
        '"source_hunks":[{"file":"a.py","start":1,"end":2}]},'
        '{"claim_id":"c2","run_id":"run-t","text":"second claim",'
        '"source_hunks":[{"file":"b.py","start":3,"end":4}]},'
        '{"claim_id":"c3","run_id":"run-t","text":"truncat'
    )
    candidates = parse_claim_candidates_text(truncated, default_run_id="run-t")
    assert len(candidates) == 2
    assert candidates[0].claim_id == "c1"
    assert candidates[1].claim_id == "c2"


def test_parse_claim_candidates_text_recovers_truncated_array() -> None:
    """Truncated top-level array with complete claims should recover."""
    truncated = (
        '[{"claim_id":"c1","run_id":"run-a","text":"claim one",'
        '"source_hunks":[{"file":"x.py","start":1,"end":2}]},'
        '{"claim_id":"c2","run_id":"run-a","text":"inc'
    )
    candidates = parse_claim_candidates_text(truncated, default_run_id="run-a")
    assert len(candidates) == 1
    assert candidates[0].claim_id == "c1"


def test_parse_claim_candidates_text_recovers_truncated_with_braces_in_strings() -> None:
    """Braces inside JSON string values must not confuse delimiter counting."""
    truncated = (
        '{"claims":['
        '{"claim_id":"c1","run_id":"run-b","text":"added {init} block",'
        '"source_hunks":[{"file":"a.py","start":1,"end":2}]},'
        '{"claim_id":"c2","run_id":"run-b","text":"trunc'
    )
    candidates = parse_claim_candidates_text(truncated, default_run_id="run-b")
    assert len(candidates) == 1
    assert candidates[0].claim_id == "c1"
    assert "{init}" in candidates[0].text


def test_parse_claim_candidates_text_recovers_leading_truncated_claim_array() -> None:
    """A token-capped response can start in the middle of the first claim."""
    truncated = (
        'part of a broken first claim","source_hunks":['
        '{"file":"broken.py","start":1,"end":2}]},'
        '{"text":"second complete claim",'
        '"source_hunks":[{"file":"b.py","start":3,"end":4,"side":"new"}]},'
        '{"text":"third complete claim",'
        '"source_hunks":[{"file":"c.py","start":5,"end":6,"side":"new"}]}]}'
    )

    candidates = parse_claim_candidates_text(truncated, default_run_id="run-leading")

    assert [candidate.text for candidate in candidates] == [
        "second complete claim",
        "third complete claim",
    ]
    assert candidates[0].claim_id == "run-leading-claim-001"


def test_parse_claim_candidates_text_escapes_invalid_json_backslashes() -> None:
    payload = (
        '{"claims":[{"text":"regex `<think\\b[^>]*>[\\s\\S]*?</think>` is used",'
        '"source_hunks":[{"file":"src/app.py","start":1,"end":2,"side":"new"}]}]}'
    )

    candidates = parse_claim_candidates_text(payload, default_run_id="run-regex")

    assert len(candidates) == 1
    assert "\\s\\S" in candidates[0].text


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


def test_claim_runtime_rejects_oversized_required_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_claim_run_artifacts(workspace_root, "run_oversized")
    monkeypatch.setattr(claim_runtime_module, "_MAX_RUN_ARTIFACT_TEXT_BYTES", 8)

    with pytest.raises(InputError, match="artifact exceeds size limit"):
        extract_claim_candidates_from_run(
            run_id="run_oversized",
            run_path=run_path,
            workspace_root=workspace_root,
            provider_config=ProviderConfig(
                provider_class="openai",
                model_name="gpt-5.4-mini",
                base_url="http://127.0.0.1:8318",
                api_key_env="AHADIFF_PROVIDER_API_KEY",
            ),
            api_key=None,
            security_config=SecurityConfig(),
            output_path=run_path / "claims.raw.jsonl",
        )


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


def test_extract_claim_candidates_from_run_writes_claims_raw_jsonl(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = workspace_root / ".ahadiff" / "runs" / "run_extract"
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
    (run_path / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": "run_extract",
                "source_kind": "git_ref",
                "source_ref": "abc1234",
                "content_lang": "zh-CN",
                "capability_level": 3,
                "degraded_flags": {},
                "privacy_mode": "strict_local",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text(patch, encoding="utf-8")
    (run_path / "line_map.json").write_text(
        json.dumps(serialize_line_map_payload(line_maps), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_path / "symbols.json").write_text(
        json.dumps(serialize_symbols_payload(symbols), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert "Claim Extract Prompt" in payload["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "model": "gpt-5.4-mini",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "claims": [
                                        {
                                            "text": "updates retry_once return value",
                                            "source_hunks": [
                                                {
                                                    "file": "src/app.py",
                                                    "start": 1,
                                                    "end": 2,
                                                    "side": "new",
                                                }
                                            ],
                                            "symbols": ["retry_once"],
                                        }
                                    ]
                                }
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    output_path, candidates = extract_claim_candidates_from_run(
        run_id="run_extract",
        run_path=run_path,
        workspace_root=workspace_root,
        provider_config=ProviderConfig(
            provider_class="openai",
            model_name="gpt-5.4-mini",
            base_url="http://127.0.0.1:8000",
            api_key_env="AHADIFF_PROVIDER_API_KEY",
        ),
        api_key="test-key",
        security_config=SecurityConfig(),
        output_path=run_path / "claims.raw.jsonl",
        overwrite=False,
        client=client,
    )

    assert output_path.exists()
    assert len(candidates) == 1
    raw_payload = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
    assert raw_payload["run_id"] == "run_extract"
    assert raw_payload["symbols"] == ["retry_once"]


@pytest.mark.parametrize(
    (
        "provider_max_output_tokens",
        "output_token_budget",
        "claim_output_token_cap",
        "expected_max_tokens",
    ),
    [
        (131_072, 50_000, None, 16_000),
        (0, 50_000, None, 16_000),
        (None, 3_000, None, 3_000),
        (131_072, 50_000, 7_000, 7_000),
        (None, -1, -1, 16_000),
    ],
)
def test_extract_claim_candidates_from_run_caps_request_max_output_tokens(
    tmp_path: Path,
    provider_max_output_tokens: int | None,
    output_token_budget: int,
    claim_output_token_cap: int | None,
    expected_max_tokens: int,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = f"run_extract_cap_{expected_max_tokens}"
    run_path = _write_claim_run_artifacts(workspace_root, run_id)
    sent_max_tokens: list[int | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        sent_max_tokens.append(payload.get("max_tokens"))
        assert payload["max_tokens"] == expected_max_tokens
        return httpx.Response(200, json=_claim_extract_response(run_id))

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        extract_claim_candidates_from_run(
            run_id=run_id,
            run_path=run_path,
            workspace_root=workspace_root,
            provider_config=ProviderConfig(
                provider_class="openai",
                model_name="gpt-5.4-mini",
                base_url="http://127.0.0.1:8000",
                api_key_env="AHADIFF_PROVIDER_API_KEY",
                max_output_tokens=provider_max_output_tokens,
            ),
            api_key="test-key",
            security_config=SecurityConfig(),
            output_path=run_path / "claims.raw.jsonl",
            output_token_budget=output_token_budget,
            claim_output_token_cap=claim_output_token_cap,
            client=client,
        )

    assert sent_max_tokens == [expected_max_tokens]


def test_claims_cli_extracts_with_one_off_provider_and_normalizes_chat_completions_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = workspace_root / ".ahadiff" / "runs" / "run_cli_extract"
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
    (run_path / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": "run_cli_extract",
                "source_kind": "git_ref",
                "source_ref": "abc1234",
                "content_lang": "zh-CN",
                "capability_level": 3,
                "degraded_flags": {},
                "privacy_mode": "strict_local",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text(patch, encoding="utf-8")
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
    captured: dict[str, object] = {}

    def fake_extract_claim_candidates_from_run(**kwargs: object):
        captured["provider_config"] = kwargs["provider_config"]
        captured["output_lang"] = kwargs["output_lang"]
        write_claim_candidates_jsonl(
            run_path / "claims.raw.jsonl",
            [
                ClaimCandidate(
                    claim_id="claim-cli",
                    run_id="run_cli_extract",
                    text="updates retry logic",
                    source_hunks=[SourceHunk(file="src/app.py", start=1, end=2, side="new")],
                    symbols=["retry_once"],
                )
            ],
            overwrite=True,
        )
        return run_path / "claims.raw.jsonl", ()

    monkeypatch.setattr(
        cli_module,
        "extract_claim_candidates_from_run",
        fake_extract_claim_candidates_from_run,
    )

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "claims",
            "run_cli_extract",
            "--extract",
            "--base-url",
            "http://127.0.0.1:8318/v1/chat/completions",
            "--model",
            "gpt-5.4-mini",
            "--repo-root",
            str(workspace_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    provider_config = captured["provider_config"]
    assert isinstance(provider_config, ProviderConfig)
    assert provider_config.base_url == "http://127.0.0.1:8318"
    assert captured["output_lang"] == "zh-CN"
    payload = json.loads((run_path / "claims.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert payload["status"] == "verified"


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


def test_claims_cli_rejects_dot_dot_run_id(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    escaped_run_path = workspace_root / ".ahadiff"
    _write_claim_run_artifacts(
        workspace_root,
        "..",
        run_path=escaped_run_path,
        metadata_overrides={"run_id": ".."},
    )
    _write_verified_candidate(escaped_run_path, "..")

    runner = CliRunner()
    result = runner.invoke(
        app(),
        ["claims", "..", "--repo-root", str(workspace_root)],
    )

    assert result.exit_code == 1
    assert not (escaped_run_path / "claims.jsonl").exists()


def test_claims_cli_rejects_non_git_traversal_run_id_even_when_target_exists(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    outside_run_path = workspace_root / ".ahadiff" / "outside-run"
    _write_claim_run_artifacts(
        workspace_root,
        "outside-run",
        run_path=outside_run_path,
    )
    _write_verified_candidate(outside_run_path, "outside-run")

    runner = CliRunner()
    result = runner.invoke(
        app(),
        ["claims", "../outside-run", "--repo-root", str(workspace_root)],
    )

    assert result.exit_code == 1
    assert not (outside_run_path / "claims.jsonl").exists()


def test_claims_cli_promotes_remote_extract_privacy_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_remote_extract"
    run_path = _write_claim_run_artifacts(workspace_root, run_id)
    captured: dict[str, object] = {}

    def fake_extract_claim_candidates_from_run(**kwargs: object):
        captured["api_key"] = kwargs["api_key"]
        captured["privacy_mode"] = kwargs["privacy_mode"]
        captured["provider_config"] = kwargs["provider_config"]
        return _write_verified_candidate(run_path, run_id), ()

    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")
    monkeypatch.setattr(
        cli_module,
        "extract_claim_candidates_from_run",
        fake_extract_claim_candidates_from_run,
    )

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "claims",
            run_id,
            "--extract",
            "--base-url",
            "https://8.8.8.8/v1/chat/completions",
            "--model",
            "gpt-5.4-mini",
            "--repo-root",
            str(workspace_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["api_key"] == "test-key"
    assert captured["privacy_mode"] == "explicit_remote"
    provider_config = captured["provider_config"]
    assert isinstance(provider_config, ProviderConfig)
    assert provider_config.base_url == "https://8.8.8.8"


def test_claims_cli_preserves_run_redacted_remote_for_explicit_remote_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_remote_redacted_extract"
    run_path = _write_claim_run_artifacts(
        workspace_root,
        run_id,
        metadata_overrides={"privacy_mode": "redacted_remote"},
    )
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    (run_path / "patch.diff").write_text(
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1 +1 @@\n"
        f'-API_KEY = "{secret}"\n'
        '+API_KEY = "safe"\n',
        encoding="utf-8",
    )
    sent_payloads: list[str] = []
    real_httpx_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        sent_payloads.append(payload["messages"][0]["content"])
        return httpx.Response(200, json=_claim_extract_response(run_id))

    def client_factory(*args: object, **kwargs: object) -> httpx.Client:
        assert kwargs.get("trust_env") is False
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_httpx_client(*args, **kwargs)

    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")
    monkeypatch.setattr("ahadiff.llm.provider.httpx.Client", client_factory)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "claims",
            run_id,
            "--extract",
            "--base-url",
            "https://8.8.8.8/v1/chat/completions",
            "--model",
            "gpt-5.4-mini",
            "--repo-root",
            str(workspace_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert len(sent_payloads) == 1
    assert secret not in sent_payloads[0]
    assert "[REDACTED:openai_api_key]" in sent_payloads[0]


def test_claims_cli_requires_explicit_remote_provider_under_strict_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_implicit_remote_provider"
    _write_claim_run_artifacts(workspace_root, run_id)
    (workspace_root / ".ahadiff" / "config.toml").write_text(
        "[providers.remote]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "https://api.example.invalid/v1/chat/completions"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n',
        encoding="utf-8",
    )
    provider_called = False

    def fake_extract_claim_candidates_from_run(**kwargs: object):
        nonlocal provider_called
        provider_called = True
        return _write_verified_candidate(workspace_root / ".ahadiff" / "runs" / run_id, run_id), ()

    monkeypatch.setenv("AHADIFF_PROVIDER_API_KEY", "test-key")
    monkeypatch.setattr(
        cli_module,
        "extract_claim_candidates_from_run",
        fake_extract_claim_candidates_from_run,
    )

    runner = CliRunner()
    result = runner.invoke(
        app(),
        ["claims", run_id, "--extract", "--repo-root", str(workspace_root)],
    )

    assert result.exit_code == 1
    assert "requires --provider or --base-url" in result.stderr
    assert provider_called is False


def test_claims_cli_extracts_configured_provider_through_mocktransport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_configured_mocktransport"
    run_path = _write_claim_run_artifacts(workspace_root, run_id)
    (workspace_root / ".ahadiff" / "config.toml").write_text(
        "[providers.demo]\n"
        'provider_class = "openai"\n'
        'model_name = "gpt-5.4-mini"\n'
        'base_url = "http://127.0.0.1:8323/v1/chat/completions"\n'
        'api_key_env = "AHADIFF_PROVIDER_API_KEY"\n',
        encoding="utf-8",
    )
    captured_urls: list[str] = []
    real_httpx_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(200, json=_claim_extract_response(run_id))

    def client_factory(*args: object, **kwargs: object) -> httpx.Client:
        assert kwargs.get("trust_env") is False
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_httpx_client(*args, **kwargs)

    monkeypatch.setattr("ahadiff.llm.provider.httpx.Client", client_factory)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        ["claims", run_id, "--extract", "--provider", "demo", "--repo-root", str(workspace_root)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured_urls == ["http://127.0.0.1:8323/v1/chat/completions"]
    payload = json.loads((run_path / "claims.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert payload["status"] == "verified"


def test_claims_cli_rejects_invalid_extract_provider_class_as_cli_error(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_invalid_provider_class"
    _write_claim_run_artifacts(workspace_root, run_id)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "claims",
            run_id,
            "--extract",
            "--provider-class",
            "bogus",
            "--base-url",
            "http://127.0.0.1:8318",
            "--repo-root",
            str(workspace_root),
        ],
    )

    assert result.exit_code == 1
    assert "invalid provider configuration" in result.stderr
    assert "Unexpected error" not in result.stderr


def test_claims_cli_does_not_call_provider_when_raw_exists_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_existing_raw_no_force"
    run_path = _write_claim_run_artifacts(workspace_root, run_id)
    original_raw = _write_verified_candidate(run_path, run_id).read_text(encoding="utf-8")
    provider_called = False

    def fake_extract_claim_candidates_from_run(**kwargs: object):
        nonlocal provider_called
        provider_called = True
        return _write_verified_candidate(run_path, run_id), ()

    monkeypatch.setattr(
        cli_module,
        "extract_claim_candidates_from_run",
        fake_extract_claim_candidates_from_run,
    )

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "claims",
            run_id,
            "--extract",
            "--base-url",
            "http://127.0.0.1:8318",
            "--repo-root",
            str(workspace_root),
        ],
    )

    assert result.exit_code == 1
    assert "refusing to overwrite existing file" in result.stderr
    assert provider_called is False
    assert (run_path / "claims.raw.jsonl").read_text(encoding="utf-8") == original_raw


def test_claims_cli_removes_new_raw_claims_when_verify_stage_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_cleanup"
    run_path = _write_claim_run_artifacts(workspace_root, run_id)
    (run_path / "line_map.json").write_text(
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

    def fake_extract_claim_candidates_from_run(**kwargs: object):
        assert kwargs["output_path"] == run_path / "claims.raw.jsonl"
        return _write_verified_candidate(run_path, run_id), ()

    monkeypatch.setattr(
        cli_module,
        "extract_claim_candidates_from_run",
        fake_extract_claim_candidates_from_run,
    )

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "claims",
            run_id,
            "--extract",
            "--base-url",
            "http://127.0.0.1:8318",
            "--model",
            "gpt-5.4-mini",
            "--repo-root",
            str(workspace_root),
        ],
    )

    assert result.exit_code == 1
    assert not (run_path / "claims.raw.jsonl").exists()
    assert not (run_path / "claims.jsonl").exists()


def test_claims_cli_preserves_existing_raw_when_force_verify_stage_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_force_preserves_existing_raw"
    run_path = _write_claim_run_artifacts(workspace_root, run_id)
    existing_raw = _write_verified_candidate(run_path, run_id).read_text(encoding="utf-8")
    (run_path / "line_map.json").write_text(
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

    def fake_extract_claim_candidates_from_run(**kwargs: object):
        output_path = kwargs["output_path"]
        assert isinstance(output_path, Path)
        assert output_path != run_path / "claims.raw.jsonl"
        candidate = ClaimCandidate(
            claim_id=f"{run_id}-claim-1",
            run_id=run_id,
            text="updates retry logic",
            source_hunks=[SourceHunk(file="src/app.py", start=1, end=2, side="new")],
            symbols=["retry_once"],
        )
        write_claim_candidates_jsonl(output_path, [candidate], overwrite=False)
        return output_path, ()

    monkeypatch.setattr(
        cli_module,
        "extract_claim_candidates_from_run",
        fake_extract_claim_candidates_from_run,
    )

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "claims",
            run_id,
            "--extract",
            "--force",
            "--base-url",
            "http://127.0.0.1:8318",
            "--repo-root",
            str(workspace_root),
        ],
    )

    assert result.exit_code == 1
    assert (run_path / "claims.raw.jsonl").read_text(encoding="utf-8") == existing_raw
    assert not any(run_path.glob("*.extract.tmp"))


def test_claims_cli_rejects_same_claims_file_and_output(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_same_output"
    run_path = _write_claim_run_artifacts(workspace_root, run_id)
    raw_path = _write_verified_candidate(run_path, run_id)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "claims",
            run_id,
            "--claims-file",
            str(raw_path),
            "--output",
            str(raw_path),
            "--force",
            "--repo-root",
            str(workspace_root),
        ],
    )

    assert result.exit_code == 1
    assert "must point to different files" in result.stderr


def test_claims_cli_extracts_through_mocktransport_without_stubbing_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_mocktransport"
    run_path = _write_claim_run_artifacts(workspace_root, run_id)
    captured_urls: list[str] = []
    real_httpx_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        payload = json.loads(request.content.decode("utf-8"))
        assert request.method == "POST"
        assert payload["model"] == "gpt-5.4-mini"
        assert payload["response_format"] == {"type": "json_object"}
        assert "Claim Extract Prompt" in payload["messages"][0]["content"]
        return httpx.Response(200, json=_claim_extract_response(run_id))

    def client_factory(*args: object, **kwargs: object) -> httpx.Client:
        assert kwargs.get("trust_env") is False
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_httpx_client(*args, **kwargs)

    monkeypatch.setattr("ahadiff.llm.provider.httpx.Client", client_factory)

    runner = CliRunner()
    result = runner.invoke(
        app(),
        [
            "claims",
            run_id,
            "--extract",
            "--base-url",
            "http://127.0.0.1:8322",
            "--model",
            "gpt-5.4-mini",
            "--repo-root",
            str(workspace_root),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured_urls == ["http://127.0.0.1:8322/v1/chat/completions"]
    assert (run_path / "claims.raw.jsonl").exists()
    payload = json.loads((run_path / "claims.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert payload["status"] == "verified"


def test_extract_claim_candidates_from_run_redacts_redacted_remote_payload(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_redacted_remote"
    run_path = _write_claim_run_artifacts(
        workspace_root,
        run_id,
        metadata_overrides={"privacy_mode": "redacted_remote"},
    )
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    (run_path / "patch.diff").write_text(
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1 +1 @@\n"
        f'-API_KEY = "{secret}"\n'
        '+API_KEY = "safe"\n',
        encoding="utf-8",
    )
    sent_payloads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        sent_payloads.append(payload["messages"][0]["content"])
        return httpx.Response(200, json=_claim_extract_response(run_id))

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        extract_claim_candidates_from_run(
            run_id=run_id,
            run_path=run_path,
            workspace_root=workspace_root,
            provider_config=ProviderConfig(
                provider_class="openai",
                model_name="gpt-5.4-mini",
                base_url="http://127.0.0.1:8000",
                api_key_env="AHADIFF_PROVIDER_API_KEY",
            ),
            api_key="test-key",
            security_config=SecurityConfig(),
            output_path=run_path / "claims.raw.jsonl",
            client=client,
        )

    assert len(sent_payloads) == 1
    assert secret not in sent_payloads[0]
    assert "[REDACTED:openai_api_key]" in sent_payloads[0]


def test_extract_claim_candidates_from_run_requires_context_metadata_fields(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run_missing_metadata"
    run_path = _write_claim_run_artifacts(workspace_root, run_id)
    metadata = json.loads((run_path / "metadata.json").read_text(encoding="utf-8"))
    del metadata["source_ref"]
    (run_path / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    provider_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_called
        provider_called = True
        return httpx.Response(200, json=_claim_extract_response(run_id))

    with (
        httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client,
        pytest.raises(Exception, match="source_ref"),
    ):
        extract_claim_candidates_from_run(
            run_id=run_id,
            run_path=run_path,
            workspace_root=workspace_root,
            provider_config=ProviderConfig(
                provider_class="openai",
                model_name="gpt-5.4-mini",
                base_url="http://127.0.0.1:8000",
                api_key_env="AHADIFF_PROVIDER_API_KEY",
            ),
            api_key="test-key",
            security_config=SecurityConfig(),
            output_path=run_path / "claims.raw.jsonl",
            overwrite=False,
            client=client,
        )

    assert provider_called is False
    assert not (run_path / "claims.raw.jsonl").exists()


def test_parse_claim_candidates_deduplicates_claim_ids() -> None:
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

    candidates = parse_claim_candidates_text(json.dumps(payload))
    assert len(candidates) == 2
    assert candidates[0].claim_id == "dup"
    assert candidates[1].claim_id == "dup_2"


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


def test_load_symbol_records_round_trips_tree_sitter_extractor(tmp_path: Path) -> None:
    path = tmp_path / "symbols.json"
    payload = serialize_symbols_payload(
        (
            SymbolRecord(
                path="src/widget.ts",
                qualified_name="Widget.renderCard",
                kind="method",
                range=SymbolRange(start=1, end=3),
                selection_range=SymbolRange(start=1, end=1),
                parent="Widget",
                touched_lines=(2,),
                hunk_ids=("hunk_1",),
                hunk_hash="abc123def456",
                change_kind=None,
                extractor="tree_sitter",
                confidence="high",
                error=None,
            ),
        )
    )
    path.write_text(json.dumps(payload), encoding="utf-8")

    records = load_symbol_records(path)

    assert len(records) == 1
    assert records[0].extractor == "tree_sitter"
    assert records[0].qualified_name == "Widget.renderCard"
