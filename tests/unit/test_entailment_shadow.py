from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any

import pytest

from ahadiff.claims.entailment_shadow import (
    build_entailment_shadow_rows,
    write_entailment_shadow_from_run_artifacts,
    write_entailment_shadow_jsonl,
)
from ahadiff.contracts import ClaimRecord, SourceHunk
from ahadiff.git.line_map import (
    FileLineMap,
    HunkLineMap,
    serialize_line_map_payload,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ahadiff.contracts import ClaimStatus, SourceHunkSide


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _claim(
    *,
    claim_id: str = "c1",
    run_id: str = "run-shadow",
    text: str = 'adds return literal "ok"',
    file: str = "src/new_mod.py",
    side: SourceHunkSide = "new",
    status: ClaimStatus = "verified",
    negative_evidence: list[str] | None = None,
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        run_id=run_id,
        text=text,
        status=status,
        confidence="medium",
        source_hunks=[SourceHunk(file=file, start=1, end=2, side=side)],
        negative_evidence=list(negative_evidence or []),
        extractor="python_ast",
    )


def _added_file_map(path: str = "src/new_mod.py") -> FileLineMap:
    return FileLineMap(
        file_id="file-new",
        display_path=path,
        path_identity_key=path.casefold(),
        old_path=None,
        new_path=path,
        change_kind="added",
        hunks=(
            HunkLineMap(
                file_id="file-new",
                display_path=path,
                hunk_id="h1",
                hunk_hash="hash1",
                change_kind="added",
                old_start=0,
                old_end=0,
                new_start=1,
                new_end=2,
                section_header=None,
                added_lines=(1, 2),
                deleted_lines=(),
                context_old_lines=(),
                context_new_lines=(),
            ),
        ),
    )


def _write_run_artifacts(
    run_path: Path,
    *,
    run_id: str = "run-shadow",
    claims: list[ClaimRecord] | None = None,
    line_maps: list[FileLineMap] | None = None,
    before_texts: dict[str, str] | None = None,
    after_texts: dict[str, str] | None = None,
) -> None:
    run_path.mkdir(parents=True, exist_ok=True)
    claim_items = claims if claims is not None else [_claim(run_id=run_id)]
    (run_path / "claims.jsonl").write_text(
        "".join(
            json.dumps(claim.model_dump(mode="json"), sort_keys=True) + "\n"
            for claim in claim_items
        ),
        encoding="utf-8",
    )
    (run_path / "line_map.json").write_text(
        json.dumps(serialize_line_map_payload(line_maps or [_added_file_map()]), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (run_path / "before_text_by_path.json").write_text(
        json.dumps(
            {
                "artifact": "before_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": before_texts or {},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_path / "after_text_by_path.json").write_text(
        json.dumps(
            {
                "artifact": "after_text_by_path",
                "schema": "ahadiff.text_map",
                "schema_version": 1,
                "texts": after_texts or {"src/new_mod.py": 'def run():\n    return "ok"\n'},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_shadow_writer_creates_entailment_jsonl_without_mutating_claims(tmp_path: Path) -> None:
    claim = _claim()
    before_dump = claim.model_dump(mode="json")
    output_path = tmp_path / "run" / "entailment.jsonl"

    write_entailment_shadow_jsonl(
        output_path,
        run_id="run-shadow",
        claims=[claim],
        line_maps=[_added_file_map()],
        before_text_by_path={},
        after_text_by_path={"src/new_mod.py": 'def run():\n    return "ok"\n'},
    )

    assert claim.model_dump(mode="json") == before_dump
    rows = _read_jsonl(output_path)
    assert rows == [
        {
            "applicability": "applicable",
            "claim_id": "c1",
            "confidence": "medium",
            "end": 2,
            "file": "src/new_mod.py",
            "mode": "shadow",
            "outcome": "supported",
            "predicate": "return_literal_added",
            "reason": "return_literal_added",
            "run_id": "run-shadow",
            "schema": "ahadiff.entailment_shadow",
            "schema_version": 1,
            "side": "new",
            "start": 2,
        }
    ]

    unavailable_before_rows = build_entailment_shadow_rows(
        run_id="run-shadow",
        claims=[claim],
        line_maps=[],
        before_text_by_path={},
        after_text_by_path={"src/new_mod.py": 'def run():\n    return "ok"\n'},
    )
    assert unavailable_before_rows[0]["applicability"] == "inconclusive"
    assert unavailable_before_rows[0]["reason"] == "inconclusive"


def test_shadow_writer_redacts_source_literals_from_serialized_reason() -> None:
    sensitive_literal = "sk-ABC123"

    rows = build_entailment_shadow_rows(
        run_id="run-shadow",
        claims=[
            _claim(
                text=f'adds return literal "{sensitive_literal}"',
                file="src/secret.py",
            )
        ],
        line_maps=[_added_file_map("src/secret.py")],
        before_text_by_path={},
        after_text_by_path={"src/secret.py": f'def run():\n    return "{sensitive_literal}"\n'},
    )

    assert rows
    for row in rows:
        assert re.fullmatch(r"[a-z0-9_]+", str(row["reason"]))
        serialized = json.dumps(row, ensure_ascii=False, sort_keys=True)
        assert sensitive_literal not in serialized
        for value in row.values():
            assert sensitive_literal not in str(value)


def test_shadow_writer_redacts_unsafe_file_paths_at_serialization(tmp_path: Path) -> None:
    unsafe_path = "src/../secret.py"
    output_path = tmp_path / "entailment.jsonl"

    write_entailment_shadow_jsonl(
        output_path,
        run_id="run-shadow",
        claims=[
            _claim(
                text="adds call leak_secret",
                file=unsafe_path,
            )
        ],
        line_maps=[],
        before_text_by_path={},
        after_text_by_path={unsafe_path: "leak_secret()\n"},
    )

    rows = _read_jsonl(output_path)
    assert rows[0]["file"] == "unsafe_path_redacted"
    assert unsafe_path.encode("utf-8") not in output_path.read_bytes()

    from ahadiff.claims.entailment_shadow import (
        _serialized_file_path,  # pyright: ignore[reportPrivateUsage]
    )

    home_reference_path = "~/x.py"
    overlong_segment_path = "src/" + "a" * 1000 + ".py"
    overlong_total_path = "src/" + "b/" * 300 + "x.py"
    for boundary_unsafe in (home_reference_path, overlong_segment_path, overlong_total_path):
        assert _serialized_file_path(boundary_unsafe) == "unsafe_path_redacted"
    assert _serialized_file_path("src/app.py") == "src/app.py"

    happy_rows = build_entailment_shadow_rows(
        run_id="run-shadow",
        claims=[
            _claim(
                text="adds call process",
                file="src/app.py",
            )
        ],
        line_maps=[],
        before_text_by_path={},
        after_text_by_path={"src/app.py": "process()\n"},
    )

    assert happy_rows[0]["file"] == "src/app.py"


def test_shadow_writer_preserves_status_and_negative_evidence_for_verified_claims() -> None:
    claim = _claim(
        text="adds call emit_metric",
        file="src/app.py",
        side="old",
        negative_evidence=["deleted_symbol_reference:src/app.py:legacy"],
    )
    before_status = claim.status
    before_negative = list(claim.negative_evidence)

    rows = build_entailment_shadow_rows(
        run_id="run-shadow",
        claims=[claim],
        line_maps=[],
        before_text_by_path={"src/app.py": "def run():\n    return None\n"},
        after_text_by_path={"src/app.py": "def run():\n    emit_metric()\n"},
    )

    assert claim.status == before_status
    assert claim.negative_evidence == before_negative
    assert rows[0]["outcome"] == "inconclusive"
    assert rows[0]["reason"] == "inconclusive"
    assert rows[0]["confidence"] == "low"


def test_shadow_artifact_writer_preserves_claims_jsonl_bytes_status_and_negative_evidence(
    tmp_path: Path,
) -> None:
    run_path = tmp_path / "run-shadow"
    _write_run_artifacts(
        run_path,
        run_id=run_path.name,
        claims=[
            _claim(
                run_id=run_path.name,
                text="adds call emit_metric",
                file="src/app.py",
                negative_evidence=["old-side evidence remains unchanged"],
            )
        ],
        line_maps=[_added_file_map("src/app.py")],
        before_texts={},
        after_texts={"src/app.py": "emit_metric()\n"},
    )
    claims_path = run_path / "claims.jsonl"
    before_bytes = claims_path.read_bytes()
    before_records = _read_jsonl(claims_path)
    before_statuses = [record["status"] for record in before_records]
    before_negative = [record["negative_evidence"] for record in before_records]

    result = write_entailment_shadow_from_run_artifacts(run_path, run_id=run_path.name)

    after_records = _read_jsonl(claims_path)
    assert result.rows_written == 1
    assert claims_path.read_bytes() == before_bytes
    assert [record["status"] for record in after_records] == before_statuses
    assert [record["negative_evidence"] for record in after_records] == before_negative


def test_shadow_writer_skips_missing_malformed_stale_and_bad_schema_artifacts(
    tmp_path: Path,
) -> None:
    missing = write_entailment_shadow_from_run_artifacts(tmp_path / "missing", run_id="run-shadow")
    assert missing.rows_written == 0
    assert any("claims.jsonl" in warning for warning in missing.warnings)

    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "claims.jsonl").write_text("{not-json}\n", encoding="utf-8")
    malformed_result = write_entailment_shadow_from_run_artifacts(
        malformed,
        run_id="run-shadow",
    )
    assert malformed_result.rows_written == 0
    assert any("invalid" in warning for warning in malformed_result.warnings)

    stale = tmp_path / "stale"
    _write_run_artifacts(stale, run_id="other-run", claims=[_claim(run_id="other-run")])
    stale_result = write_entailment_shadow_from_run_artifacts(stale, run_id="run-shadow")
    assert stale_result.rows_written == 0
    assert any("stale" in warning for warning in stale_result.warnings)

    bad_schema = tmp_path / "bad-schema"
    _write_run_artifacts(bad_schema)
    (bad_schema / "line_map.json").write_text(
        json.dumps({"schema": "wrong", "schema_version": 1, "files": []}) + "\n",
        encoding="utf-8",
    )
    bad_schema_result = write_entailment_shadow_from_run_artifacts(
        bad_schema,
        run_id="run-shadow",
    )
    assert bad_schema_result.rows_written == 0
    assert any("line_map.json" in warning for warning in bad_schema_result.warnings)

    malformed_line_map = tmp_path / "malformed-line-map"
    _write_run_artifacts(malformed_line_map)
    (malformed_line_map / "line_map.json").write_text(
        json.dumps(
            {
                "artifact": "line_map",
                "schema": "ahadiff.line_map",
                "schema_version": 1,
                "files": [{}],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    malformed_line_map_result = write_entailment_shadow_from_run_artifacts(
        malformed_line_map,
        run_id="run-shadow",
    )
    assert malformed_line_map_result.rows_written == 0
    assert malformed_line_map_result.warnings == ("malformed_artifact",)
    assert not (malformed_line_map / "entailment.jsonl").exists()


def test_shadow_writer_refuses_finalized_runs_but_allows_in_flight_runs(tmp_path: Path) -> None:
    finalized_run = tmp_path / "finalized-run"
    _write_run_artifacts(finalized_run, run_id=finalized_run.name)
    (finalized_run / "finalized.json").write_text(
        json.dumps({"run_id": finalized_run.name}) + "\n",
        encoding="utf-8",
    )

    finalized_result = write_entailment_shadow_from_run_artifacts(
        finalized_run,
        run_id=finalized_run.name,
    )

    assert finalized_result.rows_written == 0
    assert finalized_result.warnings == ("finalized_run_write_refused",)
    assert not (finalized_run / "entailment.jsonl").exists()

    in_flight_run = tmp_path / "in-flight-run"
    _write_run_artifacts(in_flight_run, run_id=in_flight_run.name)

    in_flight_result = write_entailment_shadow_from_run_artifacts(
        in_flight_run,
        run_id=in_flight_run.name,
    )

    assert in_flight_result.rows_written == 1
    assert in_flight_result.warnings == ()
    assert (in_flight_run / "entailment.jsonl").is_file()


def test_shadow_writer_rechecks_finalized_marker_before_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ahadiff.claims.entailment_shadow as shadow_module

    run_path = tmp_path / "run"
    _write_run_artifacts(run_path, run_id=run_path.name)
    original_build_rows = shadow_module.build_entailment_shadow_rows

    def _build_rows_and_finalize(**kwargs: Any) -> tuple[dict[str, object], ...]:
        rows = original_build_rows(**kwargs)
        (run_path / "finalized.json").write_text(
            json.dumps({"run_id": run_path.name}) + "\n",
            encoding="utf-8",
        )
        return rows

    monkeypatch.setattr(shadow_module, "build_entailment_shadow_rows", _build_rows_and_finalize)

    result = write_entailment_shadow_from_run_artifacts(run_path, run_id=run_path.name)

    assert result.rows_written == 0
    assert result.warnings == ("finalized_run_write_refused",)
    assert not (run_path / "entailment.jsonl").exists()
    assert not tuple(run_path.glob(".entailment.jsonl.*.tmp"))


def test_lesson_failure_cleanup_removes_entailment_shadow_artifact(tmp_path: Path) -> None:
    import ahadiff.core.orchestrator as orchestrator_module

    cleanup = vars(orchestrator_module)["_cleanup_lesson_generation_artifacts"]

    run_path = tmp_path / "run"
    run_path.mkdir()
    raw_claims_path = run_path / "claims.raw.jsonl"
    claims_output_path = run_path / "claims.jsonl"
    raw_claims_path.write_text("{}\n", encoding="utf-8")
    claims_output_path.write_text("{}\n", encoding="utf-8")
    (run_path / "entailment.jsonl").write_text("{}\n", encoding="utf-8")
    (run_path / "lesson").mkdir()
    (run_path / "lesson" / "partial.md").write_text("partial\n", encoding="utf-8")
    (run_path / "quiz").mkdir()
    (run_path / "quiz" / "partial.jsonl").write_text("partial\n", encoding="utf-8")
    (run_path / "concepts_local.jsonl").write_text("{}\n", encoding="utf-8")

    cleanup(
        run_path=run_path,
        raw_claims_path=raw_claims_path,
        claims_output_path=claims_output_path,
    )

    assert not raw_claims_path.exists()
    assert not claims_output_path.exists()
    assert not (run_path / "entailment.jsonl").exists()
    assert not (run_path / "lesson").exists()
    assert not (run_path / "quiz").exists()
    assert not (run_path / "concepts_local.jsonl").exists()


def test_shadow_writer_rejects_symlink_reparse_and_hardlink_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if hasattr(os, "symlink"):
        symlink_run = tmp_path / "symlink-run"
        _write_run_artifacts(symlink_run)
        outside_claims = tmp_path / "outside-claims.jsonl"
        outside_claims.write_text("[]\n", encoding="utf-8")
        (symlink_run / "claims.jsonl").unlink()
        (symlink_run / "claims.jsonl").symlink_to(outside_claims)
        symlink_result = write_entailment_shadow_from_run_artifacts(
            symlink_run,
            run_id="run-shadow",
        )
        assert symlink_result.rows_written == 0
        assert any("symlink" in warning for warning in symlink_result.warnings)

    if hasattr(os, "link"):
        hardlink_run = tmp_path / "hardlink-run"
        _write_run_artifacts(hardlink_run)
        outside_claims = tmp_path / "outside-hardlink-claims.jsonl"
        outside_claims.write_text((hardlink_run / "claims.jsonl").read_text(), encoding="utf-8")
        (hardlink_run / "claims.jsonl").unlink()
        try:
            os.link(outside_claims, hardlink_run / "claims.jsonl")
        except OSError as exc:
            pytest.skip(f"hardlink creation failed: {exc}")
        hardlink_result = write_entailment_shadow_from_run_artifacts(
            hardlink_run,
            run_id="run-shadow",
        )
        assert hardlink_result.rows_written == 0
        assert any("hardlink" in warning for warning in hardlink_result.warnings)

    reparse_run = tmp_path / "reparse-run"
    _write_run_artifacts(reparse_run)

    def _is_reparse_point(_stat: object) -> bool:
        return True

    monkeypatch.setattr("ahadiff.claims.extract._has_windows_reparse_point", _is_reparse_point)
    reparse_result = write_entailment_shadow_from_run_artifacts(
        reparse_run,
        run_id="run-shadow",
    )
    assert reparse_result.rows_written == 0
    assert any("reparse" in warning for warning in reparse_result.warnings)


def test_shadow_writer_records_docs_binary_rename_as_not_applicable() -> None:
    rows = build_entailment_shadow_rows(
        run_id="run-shadow",
        claims=[
            _claim(
                text="renames the user guide",
                file="docs/guide.md",
                side="new",
            )
        ],
        line_maps=[],
        before_text_by_path={"docs/guide.md": "old\n"},
        after_text_by_path={"docs/guide.md": "new\n"},
    )

    assert rows[0]["applicability"] == "not_applicable"
    assert rows[0]["outcome"] == "inconclusive"
    assert rows[0]["reason"] == "not_applicable"
    assert rows[0]["confidence"] == "low"
