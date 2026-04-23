from __future__ import annotations

import csv
import json
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ahadiff import cli as cli_module
from ahadiff.cli import app
from ahadiff.contracts import ClaimRecord, SourceHunk
from ahadiff.eval.evaluator import ScoreReport, evaluate_run
from ahadiff.eval.results import (
    append_result,
    compute_prompt_version,
    export_results,
    finalized_artifact_digest,
    finalized_marker_path,
    load_result_events,
    publish_result_artifacts,
    results_tsv_path_for_run,
    review_db_path_for_run,
    rollback_result_event,
)
from ahadiff.git.line_map import build_line_map, serialize_line_map_payload
from ahadiff.review import database as review_database_module

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

_RUNNER = CliRunner()


def _write_run_fixture(workspace_root: Path, run_id: str = "run_results") -> Path:
    run_path = workspace_root / ".ahadiff" / "runs" / run_id
    run_path.mkdir(parents=True, exist_ok=True)
    patch_text = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
-value = 1
+value = 2
+print(value)
"""
    metadata = {
        "run_id": run_id,
        "source_kind": "patch_file",
        "source_ref": "sha256:fixture",
        "capability_level": 1,
        "degraded_flags": {},
        "learnability": {"score": 0.7},
        "source_detail": {},
        "privacy_mode": "strict_local",
    }
    claim = ClaimRecord(
        claim_id="claim_fixture",
        run_id=run_id,
        text="The module now prints the updated value.",
        status="verified",
        confidence="high",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=2, side="new")],
    )
    lesson_dir = run_path / "lesson"
    lesson_dir.mkdir()
    (lesson_dir / "lesson.full.md").write_text("full lesson\n", encoding="utf-8")
    (lesson_dir / "lesson.hint.md").write_text("hint lesson\n", encoding="utf-8")
    (lesson_dir / "lesson.compact.md").write_text("compact lesson\n", encoding="utf-8")
    quiz_dir = run_path / "quiz"
    quiz_dir.mkdir()
    (quiz_dir / "quiz.jsonl").write_text(
        json.dumps({"question": "What changed?", "source_claims": ["claim_fixture"]}) + "\n",
        encoding="utf-8",
    )
    (run_path / "metadata.json").write_text(json.dumps(metadata) + "\n", encoding="utf-8")
    (run_path / "patch.diff").write_text(patch_text, encoding="utf-8")
    (run_path / "line_map.json").write_text(
        json.dumps(serialize_line_map_payload(build_line_map(patch_text))) + "\n",
        encoding="utf-8",
    )
    (run_path / "claims.jsonl").write_text(
        json.dumps(claim.model_dump(mode="json")) + "\n",
        encoding="utf-8",
    )
    return run_path


def _report_for_run(run_path: Path) -> ScoreReport:
    report = evaluate_run(run_path)
    return ScoreReport(
        run_id=report.run_id,
        source_ref=report.source_ref,
        source_kind=report.source_kind,
        capability_level=report.capability_level,
        degraded_flags=report.degraded_flags,
        overall=report.overall,
        verdict=report.verdict,
        weakest_dim=report.weakest_dim,
        eval_bundle_version=report.eval_bundle_version,
        rubric_version=report.rubric_version,
        dimensions=report.dimensions,
        hard_gates=report.hard_gates,
        notes=report.notes,
    )


def test_append_result_writes_sqlite_tsv_and_finalized_marker(tmp_path: Path) -> None:
    run_path = _write_run_fixture(tmp_path)
    report = _report_for_run(run_path)

    outcome = append_result(
        run_path=run_path,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="verify",
        note_payload={"ratchet_reason": "no_git_ancestry"},
        event_id="018f0f52-91c0-7abc-8123-000000000001",
    )

    assert outcome.sqlite_inserted is True
    assert outcome.tsv_appended is True
    assert outcome.finalized_written is True
    assert finalized_marker_path(run_path).exists()
    marker = json.loads(finalized_marker_path(run_path).read_text(encoding="utf-8"))
    artifact_count, checksum = finalized_artifact_digest(run_path)
    assert marker["finalized_at"] == outcome.event.timestamp
    assert marker["artifact_count"] == artifact_count
    assert marker["checksum"] == checksum
    assert len(marker["checksum"]) == 64
    assert results_tsv_path_for_run(run_path).exists()
    assert outcome.event.prompt_version != "no-prompts"
    rows = load_result_events(review_db_path_for_run(run_path))
    assert len(rows) == 1
    assert rows[0].status == "non_ratcheted"


def test_prompt_version_ignores_workspace_prompts_directory(tmp_path: Path) -> None:
    run_path = _write_run_fixture(tmp_path, run_id="run_prompt_version")
    workspace_prompts = tmp_path / "prompts"
    workspace_prompts.mkdir()
    (workspace_prompts / "lesson_hint.md").write_text(
        "workspace-specific prompt\n",
        encoding="utf-8",
    )
    report = _report_for_run(run_path)

    outcome = append_result(
        run_path=run_path,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="verify",
        event_id="018f0f52-91c0-7abc-8123-000000000007",
    )

    assert outcome.event.prompt_version == compute_prompt_version(tmp_path / "another-workspace")
    assert outcome.event.prompt_version != "no-prompts"


def test_append_result_is_idempotent_for_same_event_id(tmp_path: Path) -> None:
    run_path = _write_run_fixture(tmp_path)
    report = _report_for_run(run_path)

    first = append_result(
        run_path=run_path,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="verify",
        event_id="018f0f52-91c0-7abc-8123-000000000002",
    )
    second = append_result(
        run_path=run_path,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="verify",
        event_id="018f0f52-91c0-7abc-8123-000000000002",
    )

    assert first.sqlite_inserted is True
    assert second.sqlite_inserted is False
    assert second.tsv_appended is False
    assert second.finalized_written is False
    rows = load_result_events(review_db_path_for_run(run_path))
    assert len(rows) == 1
    with results_tsv_path_for_run(run_path).open("r", encoding="utf-8", newline="") as handle:
        tsv_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(tsv_rows) == 1
    finalized_payload = json.loads(finalized_marker_path(run_path).read_text(encoding="utf-8"))
    assert finalized_payload["event_id"] == first.event.event_id


def test_export_results_rebuilds_tsv_from_sqlite(tmp_path: Path) -> None:
    run_path = _write_run_fixture(tmp_path)
    report = _report_for_run(run_path)
    append_result(
        run_path=run_path,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="verify",
        event_id="018f0f52-91c0-7abc-8123-000000000003",
    )

    output_path = tmp_path / "rebuilt.tsv"
    export_results(
        db_path=review_db_path_for_run(run_path),
        output_path=output_path,
    )

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run_results"


def test_rollback_result_event_uses_single_review_db_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_path = _write_run_fixture(tmp_path, run_id="run_rollback")
    report = _report_for_run(run_path)
    outcome = append_result(
        run_path=run_path,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="verify",
        event_id="018f0f52-91c0-7abc-8123-000000000008",
    )
    connection_count = 0
    real_connect = review_database_module.connect_review_db

    def counting_connect(db_path: Path) -> sqlite3.Connection:
        nonlocal connection_count
        connection_count += 1
        return real_connect(db_path)

    monkeypatch.setattr(review_database_module, "connect_review_db", counting_connect)

    rollback_result_event(run_path=run_path, event_id=outcome.event.event_id)

    assert connection_count == 1
    assert load_result_events(review_db_path_for_run(run_path)) == ()
    with results_tsv_path_for_run(run_path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows == []


def test_export_results_cli_uses_workspace_review_db(tmp_path: Path) -> None:
    run_path = _write_run_fixture(tmp_path, run_id="run_cli_export")
    report = _report_for_run(run_path)
    append_result(
        run_path=run_path,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="verify",
        event_id="018f0f52-91c0-7abc-8123-000000000004",
    )

    output_path = tmp_path / "custom-results.tsv"
    result = _RUNNER.invoke(
        app(),
        ["export-results", "--repo-root", str(tmp_path), "--output", str(output_path)],
    )

    assert result.exit_code == 0
    assert output_path.exists()
    with output_path.open("r", encoding="utf-8") as handle:
        text = handle.read()
    assert "run_cli_export" in text


def test_score_command_writes_custom_output_and_finalized_reference(tmp_path: Path) -> None:
    run_path = _write_run_fixture(tmp_path, run_id="run_cli_score")
    custom_output = tmp_path / "artifacts" / "custom-score.json"

    result = _RUNNER.invoke(
        app(),
        [
            "score",
            "run_cli_score",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(custom_output),
        ],
    )

    assert result.exit_code == 0
    assert custom_output.exists()
    payload = json.loads(finalized_marker_path(run_path).read_text(encoding="utf-8"))
    assert payload["score_path"] == str(custom_output.resolve())


def test_export_results_cli_acquires_repo_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_path = _write_run_fixture(tmp_path, run_id="run_lock_export")
    report = _report_for_run(run_path)
    append_result(
        run_path=run_path,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="verify",
        event_id="018f0f52-91c0-7abc-8123-000000000005",
    )
    commands: list[str] = []

    @contextmanager
    def fake_repo_write_lock(lock_path: Path, *, command: str) -> Iterator[Path]:
        commands.append(command)
        yield lock_path

    monkeypatch.setattr(cli_module, "repo_write_lock", fake_repo_write_lock)

    output_path = tmp_path / "locked-results.tsv"
    result = _RUNNER.invoke(
        app(),
        ["export-results", "--repo-root", str(tmp_path), "--output", str(output_path)],
    )

    assert result.exit_code == 0
    assert commands == ["export-results"]


def test_score_command_rolls_back_result_event_when_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_path = _write_run_fixture(tmp_path, run_id="run_publish_fail")

    def fail_publish_result_artifacts(**kwargs: object) -> None:
        raise OSError("simulated publish failure")

    monkeypatch.setattr(cli_module, "publish_result_artifacts", fail_publish_result_artifacts)

    result = _RUNNER.invoke(
        app(),
        ["score", "run_publish_fail", "--repo-root", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "failed to publish score artifacts" in result.output
    assert load_result_events(review_db_path_for_run(run_path)) == ()
    with results_tsv_path_for_run(run_path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows == []
    assert not finalized_marker_path(run_path).exists()
    assert not (run_path / "score.json").exists()


def test_publish_result_artifacts_restores_backups_when_temp_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_path = _write_run_fixture(tmp_path, run_id="run_publish_restore")
    report = _report_for_run(run_path)
    outcome = append_result(
        run_path=run_path,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="verify",
        event_id="018f0f52-91c0-7abc-8123-000000000006",
        write_finalized=False,
    )
    original_score = '{"old": true}\n'
    original_finalized = '{"old": "finalized"}\n'
    score_path = run_path / "score.json"
    finalized_path = finalized_marker_path(run_path)
    score_path.write_text(original_score, encoding="utf-8")
    finalized_path.write_text(original_finalized, encoding="utf-8")

    real_write_text = Path.write_text
    failure_injected = False

    def flaky_write_text(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        nonlocal failure_injected
        if not failure_injected and str(self).endswith(".finalized.tmp"):
            failure_injected = True
            raise OSError("simulated finalized temp write failure")
        return real_write_text(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", flaky_write_text)

    with pytest.raises(OSError, match="simulated finalized temp write failure"):
        publish_result_artifacts(
            run_path=run_path,
            report=report,
            event=outcome.event,
            score_path=score_path,
            overwrite=True,
        )

    assert failure_injected is True
    assert score_path.read_text(encoding="utf-8") == original_score
    assert finalized_path.read_text(encoding="utf-8") == original_finalized
