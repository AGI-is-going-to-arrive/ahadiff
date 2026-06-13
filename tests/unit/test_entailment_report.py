from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from typing import TYPE_CHECKING, Any

import pytest

from ahadiff.claims.entailment_report import (
    scan_entailment_corpus,
    wilson_95_ci,
    write_entailment_report,
)
from ahadiff.contracts import ClaimRecord, SourceHunk
from ahadiff.git.line_map import FileLineMap, HunkLineMap, serialize_line_map_payload
from ahadiff.git.symbols import serialize_symbols_payload

if TYPE_CHECKING:
    from pathlib import Path


def _claim(
    *,
    claim_id: str,
    run_id: str,
    text: str = 'adds return literal "ok"',
    status: str = "verified",
    file: str = "src/app.py",
    start: int = 2,
    end: int = 2,
) -> dict[str, Any]:
    return ClaimRecord(
        claim_id=claim_id,
        run_id=run_id,
        text=text,
        status=status,  # type: ignore[arg-type]
        confidence="medium",
        source_hunks=[SourceHunk(file=file, start=start, end=end, side="new")],
        extractor="python_ast",
    ).model_dump(mode="json")


def _line_map(path: str = "src/app.py") -> FileLineMap:
    return FileLineMap(
        file_id="file-app",
        display_path=path,
        path_identity_key=path.casefold(),
        old_path=path,
        new_path=path,
        change_kind="modified",
        hunks=(
            HunkLineMap(
                file_id="file-app",
                display_path=path,
                hunk_id="h1",
                hunk_hash="hash1",
                change_kind="modified",
                old_start=1,
                old_end=2,
                new_start=1,
                new_end=2,
                section_header=None,
                added_lines=(2,),
                deleted_lines=(2,),
                context_old_lines=(1,),
                context_new_lines=(1,),
            ),
        ),
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_text_map(path: Path, *, artifact: str, texts: dict[str, str]) -> None:
    _write_json(
        path,
        {
            "artifact": artifact,
            "schema": "ahadiff.text_map",
            "schema_version": 1,
            "texts": texts,
        },
    )


def _write_finalized_marker(run_path: Path) -> None:
    chunks: list[bytes] = []
    for path in sorted(item for item in run_path.rglob("*") if item.is_file()):
        relative = path.relative_to(run_path).as_posix()
        if relative == "finalized.json" or path.name.startswith("."):
            continue
        chunks.append(
            relative.encode("utf-8")
            + b"\n"
            + hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii")
        )
    checksum = hashlib.sha256(b"\n---\n".join(chunks)).hexdigest()
    _write_json(
        run_path / "finalized.json",
        {
            "artifact_count": len(chunks),
            "checksum": checksum,
            "event_id": f"event-{run_path.name}",
            "finalized_at": "2026-06-12T00:00:00Z",
            "run_id": run_path.name,
        },
    )


def _write_run(
    runs_dir: Path,
    run_id: str,
    *,
    claims: list[dict[str, Any]] | None = None,
    before_text: str = "def run():\n    return None\n",
    after_text: str = 'def run():\n    return "ok"\n',
    line_map_payload: dict[str, Any] | None = None,
    symbols_payload: dict[str, Any] | None = None,
    finalized: bool = True,
) -> Path:
    run_path = runs_dir / run_id
    run_path.mkdir(parents=True)
    _write_json(run_path / "metadata.json", {"run_id": run_id, "source": "unit-test"})
    (run_path / "patch.diff").write_text(
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def run():\n"
        "-    return None\n"
        '+    return "ok"\n',
        encoding="utf-8",
    )
    _write_json(
        run_path / "line_map.json",
        line_map_payload
        if line_map_payload is not None
        else serialize_line_map_payload([_line_map()]),
    )
    _write_json(
        run_path / "symbols.json",
        symbols_payload if symbols_payload is not None else serialize_symbols_payload(()),
    )
    _write_text_map(
        run_path / "before_text_by_path.json",
        artifact="before_text_by_path",
        texts={"src/app.py": before_text},
    )
    _write_text_map(
        run_path / "after_text_by_path.json",
        artifact="after_text_by_path",
        texts={"src/app.py": after_text},
    )
    if claims is not None:
        run_path.joinpath("claims.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in claims),
            encoding="utf-8",
        )
    if finalized:
        _write_finalized_marker(run_path)
    return run_path


def test_report_counts_total_runs_claim_runs_verified_and_route_hits_separately(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    run_id = "run-counts"
    _write_run(
        runs_dir,
        run_id,
        claims=[
            _claim(claim_id="c1", run_id=run_id),
            _claim(claim_id="c2", run_id=run_id, text="updates the module"),
            _claim(claim_id="c3", run_id=run_id, status="weak", text="adds call emit_metric"),
        ],
    )
    _write_run(runs_dir, "run-without-claims", claims=None)

    report = scan_entailment_corpus(runs_dir)

    assert report.metrics.total_runs == 2
    assert report.metrics.claim_runs == 1
    assert report.metrics.verified_claims == 2
    assert report.metrics.route_hit_verified_claims == 1
    assert report.metrics.false_positive_claims == 0


def test_report_uses_route_hit_verified_as_fp_denominator(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    run_id = "run-denominator"
    _write_run(
        runs_dir,
        run_id,
        claims=[
            _claim(claim_id="supported", run_id=run_id),
            _claim(claim_id="fp", run_id=run_id, text='adds return literal "missing"'),
            _claim(claim_id="not-routed", run_id=run_id, text="updates the module"),
        ],
    )

    report = scan_entailment_corpus(runs_dir)

    assert report.metrics.verified_claims == 3
    assert report.metrics.route_hit_verified_claims == 2
    assert report.metrics.false_positive_claims == 1
    assert math.isclose(report.metrics.fp_rate, 0.5)


def test_report_excludes_syntax_inconclusive_rows_from_route_hit_denominator(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    run_id = "run-syntax"
    _write_run(
        runs_dir,
        run_id,
        claims=[_claim(claim_id="c1", run_id=run_id)],
        after_text='def run(:\n    return "ok"\n',
    )

    report = scan_entailment_corpus(runs_dir)

    assert report.metrics.verified_claims == 1
    assert report.metrics.route_hit_verified_claims == 0
    assert report.metrics.false_positive_claims == 0


def test_report_does_not_count_supported_route_rows_as_false_positive(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    run_id = "run-multi-hunk"
    claim = ClaimRecord(
        claim_id="c1",
        run_id=run_id,
        text="adds import json",
        status="verified",
        confidence="medium",
        source_hunks=[
            SourceHunk(file="src/app.py", start=1, end=1, side="new"),
        ],
        extractor="python_ast",
    ).model_dump(mode="json")
    _write_run(
        runs_dir,
        run_id,
        claims=[claim],
        before_text="def run():\n    return None\n",
        after_text='import json\n\n\ndef run():\n    return "ok"\n',
    )

    report = scan_entailment_corpus(runs_dir)

    assert report.metrics.route_hit_verified_claims == 1
    assert report.metrics.false_positive_claims == 0
    row = next(item for item in report.manifest_rows if item["run_id"] == run_id)
    assert row["false_positive_claims"] == 0


def test_report_counts_mixed_route_rows_with_not_supported_as_false_positive(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    run_id = "run-mixed-route"
    claim = ClaimRecord(
        claim_id="c1",
        run_id=run_id,
        text='adds import json and return literal "missing"',
        status="verified",
        confidence="medium",
        source_hunks=[
            SourceHunk(file="src/app.py", start=1, end=1, side="new"),
            SourceHunk(file="src/app.py", start=5, end=5, side="new"),
        ],
        extractor="python_ast",
    ).model_dump(mode="json")
    _write_run(
        runs_dir,
        run_id,
        claims=[claim],
        before_text="def run():\n    return None\n",
        after_text='import json\n\n\ndef run():\n    return "ok"\n',
    )

    report = scan_entailment_corpus(runs_dir)

    assert report.metrics.route_hit_verified_claims == 1
    assert report.metrics.false_positive_claims == 1
    assert math.isclose(report.metrics.fp_rate, 1.0)
    row = next(item for item in report.manifest_rows if item["run_id"] == run_id)
    assert row["false_positive_claims"] == 1


def test_report_does_not_count_claim_when_each_route_predicate_is_supported(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    run_id = "run-multi-hunk-route-supported"
    claim = ClaimRecord(
        claim_id="c1",
        run_id=run_id,
        text='adds import json and return literal "ok"',
        status="verified",
        confidence="medium",
        source_hunks=[
            SourceHunk(file="src/app.py", start=1, end=1, side="new"),
            SourceHunk(file="src/app.py", start=5, end=5, side="new"),
        ],
        extractor="python_ast",
    ).model_dump(mode="json")
    _write_run(
        runs_dir,
        run_id,
        claims=[claim],
        before_text="def run():\n    return None\n",
        after_text='import json\n\n\ndef run():\n    return "ok"\n',
    )

    report = scan_entailment_corpus(runs_dir)

    assert report.metrics.route_hit_verified_claims == 1
    assert report.metrics.false_positive_claims == 0
    assert math.isclose(report.metrics.fp_rate, 0.0)
    row = next(item for item in report.manifest_rows if item["run_id"] == run_id)
    assert row["false_positive_claims"] == 0


def test_report_counts_missing_target_with_same_route_predicate_as_false_positive(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    run_id = "run-same-predicate-missing-target"
    claim = ClaimRecord(
        claim_id="c1",
        run_id=run_id,
        text='adds return literal "ok" and return literal "missing"',
        status="verified",
        confidence="medium",
        source_hunks=[
            SourceHunk(file="src/app.py", start=2, end=2, side="new"),
        ],
        extractor="python_ast",
    ).model_dump(mode="json")
    _write_run(
        runs_dir,
        run_id,
        claims=[claim],
        before_text="def run():\n    return None\n",
        after_text='def run():\n    return "ok"\n',
    )

    report = scan_entailment_corpus(runs_dir)

    assert report.metrics.route_hit_verified_claims == 1
    assert report.metrics.false_positive_claims == 1
    assert math.isclose(report.metrics.fp_rate, 1.0)
    row = next(item for item in report.manifest_rows if item["run_id"] == run_id)
    assert row["false_positive_claims"] == 1


def test_report_marks_enforce_blocked_when_route_hits_below_200(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    run_id = "run-blocked"
    _write_run(runs_dir, run_id, claims=[_claim(claim_id="c1", run_id=run_id)])
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    manifest = tmp_path / "manifest.jsonl"

    report = write_entailment_report(
        runs_dir=runs_dir,
        out_json=out_json,
        out_markdown=out_md,
        sample_manifest=manifest,
    )

    assert report.metrics.route_hit_verified_claims == 1
    assert report.metrics.enforce == "blocked"
    assert "enforce=blocked" in out_md.read_text(encoding="utf-8")


def test_report_computes_wilson_95_ci_for_false_positive_rate() -> None:
    low, high = wilson_95_ci(1, 2)

    assert math.isclose(low, 0.0945, abs_tol=0.0001)
    assert math.isclose(high, 0.9055, abs_tol=0.0001)


def test_report_skips_missing_malformed_stale_bad_schema_symlink_reparse_hardlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_dir = tmp_path / "runs"
    _write_run(runs_dir, "run-missing", claims=None)

    malformed = _write_run(runs_dir, "run-malformed", claims=[])
    (malformed / "claims.jsonl").write_text("{not-json}\n", encoding="utf-8")
    _write_finalized_marker(malformed)

    stale = _write_run(runs_dir, "run-stale", claims=[])
    _write_json(stale / "finalized.json", {"run_id": "other-run"})

    bad_schema = _write_run(
        runs_dir,
        "run-bad-schema",
        claims=[_claim(claim_id="c1", run_id="run-bad-schema")],
        line_map_payload={"artifact": "line_map", "schema": "wrong", "schema_version": 1},
    )
    _write_finalized_marker(bad_schema)

    if hasattr(os, "symlink"):
        symlink_run = _write_run(
            runs_dir,
            "run-symlink",
            claims=[_claim(claim_id="c1", run_id="run-symlink")],
        )
        outside = tmp_path / "outside-claims.jsonl"
        outside.write_text(
            (symlink_run / "claims.jsonl").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (symlink_run / "claims.jsonl").unlink()
        (symlink_run / "claims.jsonl").symlink_to(outside)

    if hasattr(os, "link"):
        hardlink_run = _write_run(
            runs_dir,
            "run-hardlink",
            claims=[_claim(claim_id="c1", run_id="run-hardlink")],
        )
        outside_hardlink = tmp_path / "outside-hardlink-claims.jsonl"
        outside_hardlink.write_text(
            (hardlink_run / "claims.jsonl").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (hardlink_run / "claims.jsonl").unlink()
        try:
            os.link(outside_hardlink, hardlink_run / "claims.jsonl")
        except OSError as exc:
            pytest.skip(f"hardlink creation failed: {exc}")

    report = scan_entailment_corpus(runs_dir)

    assert report.skip_reasons["missing_claims"] == 1
    assert report.skip_reasons["malformed_claims"] == 1
    assert report.skip_reasons["stale_finalized_marker"] == 1
    assert report.skip_reasons["bad_schema_line_map"] == 1
    if hasattr(os, "symlink"):
        assert report.skip_reasons["unsafe_artifact_symlink"] == 1
    if hasattr(os, "link"):
        assert report.skip_reasons["unsafe_artifact_hardlink"] == 1

    reparse_dir = tmp_path / "reparse-runs"
    _write_run(
        reparse_dir,
        "run-reparse",
        claims=[_claim(claim_id="c1", run_id="run-reparse")],
    )

    def _is_regular_file_reparse(path_stat: object) -> bool:
        return stat.S_ISREG(int(getattr(path_stat, "st_mode", 0)))

    monkeypatch.setattr(
        "ahadiff.claims.entailment_report._has_windows_reparse_point",
        _is_regular_file_reparse,
    )
    reparse_report = scan_entailment_corpus(reparse_dir)
    assert reparse_report.skip_reasons["unsafe_artifact_reparse"] == 1


def test_report_rejects_symlink_run_directory_before_hashing_artifacts(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not available on this platform")

    outside_parent = tmp_path / "outside"
    outside_run = _write_run(
        outside_parent,
        "run-symlink-dir",
        claims=[_claim(claim_id="c1", run_id="run-symlink-dir")],
    )
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    symlink_run = runs_dir / "run-symlink-dir"
    try:
        symlink_run.symlink_to(outside_run, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation failed: {exc}")

    report = scan_entailment_corpus(runs_dir)

    assert report.metrics.total_runs == 1
    assert report.metrics.claim_runs == 0
    assert report.skip_reasons["unsafe_run_directory_symlink"] == 1
    row = report.manifest_rows[0]
    assert row["skip_reason"] == "unsafe_run_directory_symlink"
    for key in (
        "metadata_sha256",
        "claims_sha256",
        "patch_sha256",
        "line_map_sha256",
        "symbols_sha256",
    ):
        assert row[key] is None


def test_report_rejects_symlink_runs_root_before_listing_entries(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not available on this platform")

    outside_parent = tmp_path / "outside"
    _write_run(
        outside_parent,
        "run-outside",
        claims=[_claim(claim_id="c1", run_id="run-outside")],
    )
    runs_dir = tmp_path / "runs-link"
    try:
        runs_dir.symlink_to(outside_parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation failed: {exc}")

    report = scan_entailment_corpus(runs_dir)

    assert report.metrics.total_runs == 0
    assert report.metrics.claim_runs == 0
    assert report.manifest_rows == ()


def test_report_records_input_sha256_for_every_sampled_run(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    run_id = "run-hashes"
    _write_run(runs_dir, run_id, claims=[_claim(claim_id="c1", run_id=run_id)])
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    manifest = tmp_path / "manifest.jsonl"

    write_entailment_report(
        runs_dir=runs_dir,
        out_json=out_json,
        out_markdown=out_md,
        sample_manifest=manifest,
    )

    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    row = next(item for item in rows if item["run_id"] == run_id)
    for artifact, key in (
        ("metadata.json", "metadata_sha256"),
        ("claims.jsonl", "claims_sha256"),
        ("patch.diff", "patch_sha256"),
        ("line_map.json", "line_map_sha256"),
        ("symbols.json", "symbols_sha256"),
    ):
        assert row[key] == hashlib.sha256((runs_dir / run_id / artifact).read_bytes()).hexdigest()
    assert row["skip_reason"] is None

    combined = (
        out_json.read_text(encoding="utf-8")
        + out_md.read_text(encoding="utf-8")
        + manifest.read_text(encoding="utf-8")
    )
    assert 'adds return literal "ok"' not in combined
    assert str(tmp_path) not in combined
