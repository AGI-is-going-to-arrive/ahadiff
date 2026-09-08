from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from ahadiff import cli as cli_module
from ahadiff.claims.extract import load_line_map_records, write_verified_claims_jsonl
from ahadiff.claims.schema import ClaimCandidate
from ahadiff.claims.verify import verify_claim_candidate
from ahadiff.cli import app
from ahadiff.contracts import ProviderConfig, ReviewCard, SourceHunk
from ahadiff.contracts.quiz_choice import QuizChoice
from ahadiff.contracts.run_source import CompareFileInput, DocumentInput
from ahadiff.core import card_sources
from ahadiff.core.card_sources import (
    declares_source_artifacts,
    load_card_sources,
    require_finalized_source,
)
from ahadiff.core.errors import AhaDiffError, InputError
from ahadiff.core.source_evidence import load_evidence_anchors
from ahadiff.eval.evaluator import (
    LlmJudgeReport,
    evaluate_run,
    write_llm_judge_report,
    write_score_report,
)
from ahadiff.eval.results import append_result, finalized_artifact_digest, write_finalized_result
from ahadiff.export.preview import export_preview
from ahadiff.git import capture as capture_module
from ahadiff.git.capture import capture_patch, write_input_artifacts
from ahadiff.lesson.generator import write_selected_lesson_artifacts
from ahadiff.lesson.schemas import LessonCompact, LessonFull, LessonHint
from ahadiff.mcp.server import (
    _ask_lesson,  # pyright: ignore[reportPrivateUsage]
    _list_due_cards,  # pyright: ignore[reportPrivateUsage]
)
from ahadiff.quiz.distractor_gate import build_distractor_gate_report, write_distractor_gate_report
from ahadiff.quiz.generator import (
    QuizArtifactPaths,
    write_quiz_questions_jsonl,
    write_review_cards_jsonl,
)
from ahadiff.quiz.schemas import QuizEvidence, QuizQuestion
from ahadiff.review.apkg_export import export_apkg
from ahadiff.review.database import (
    import_cards_from_jsonl,
    import_cards_from_runs,
    load_result_events_from_db,
    record_card_review_once,
)
from ahadiff.safety.ignore import AllowlistPolicy
from ahadiff.safety.redact import redaction_pipeline
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from ahadiff.contracts.source_anchor import SourceAnchor


def _finalize(run: Path) -> None:
    count, digest = finalized_artifact_digest(run)
    (run / "finalized.json").write_text(
        json.dumps(
            {
                "run_id": run.name,
                "artifact_count": count,
                "checksum": digest,
                "finalized_at": "2026-09-08T00:00:00Z",
                "status": "non_ratcheted",
            }
        ),
        encoding="utf-8",
    )


def _format_pair(kind: str) -> tuple[str, str, str]:
    if kind == "notebook":
        before = json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {},
                "cells": [
                    {
                        "cell_type": "code",
                        "id": "synthetic-cell",
                        "metadata": {},
                        "source": ["retries = 1\n"],
                        "outputs": [],
                        "execution_count": None,
                    }
                ],
            }
        )
        return "sample.ipynb", before, before.replace("retries = 1", "retries = 2")
    pairs = {
        "markdown": ("sample.md", "# Worker\n\nRetries: 1\n", "# Worker\n\nRetries: 2\n"),
        "json": ("sample.json", '{"worker":{"retries":1}}\n', '{"worker":{"retries":2}}\n'),
        "toml": ("sample.toml", "[worker]\nretries = 1\n", "[worker]\nretries = 2\n"),
        "yaml": ("sample.yaml", "worker:\n  retries: 1\n", "worker:\n  retries: 2\n"),
        "python": ("sample.py", "retries = 1\n", "retries = 2\n"),
    }
    return pairs[kind]


def _new_card_run(
    root: Path,
    *,
    kind: str = "document",
    lang: Literal["en", "zh-CN"] = "en",
    exercise: bool = True,
    auxiliary: bool = False,
    multiple_choice: bool = False,
    document_content: str | None = None,
) -> tuple[Path, ReviewCard, SourceAnchor | None]:
    if kind == "document":
        capture = capture_patch(
            workspace_root=root,
            document=DocumentInput(
                name="学习.md",
                content=document_content
                if document_content is not None
                else "# Queue\n\nUse retry_later() after <failure> & preserve order.\n",
            ),
            content_lang=lang,
            review_context="Synthetic reviewer context, kept out of the exported note."
            if auxiliary
            else None,
            use_graphify=False,
        )
    else:
        name, before, after = _format_pair(kind)
        capture = capture_patch(
            workspace_root=root,
            compare_files=(
                CompareFileInput(name=name, content=before),
                CompareFileInput(name=name, content=after),
            ),
            content_lang=lang,
            use_graphify=False,
        )
    source, _ = write_input_artifacts(capture)
    run = source.parent
    anchors = load_evidence_anchors(run)
    anchor = next((entry for entry in reversed(anchors) if entry.side in {"new", "document"}), None)
    suffix = run.name[-12:]
    card_id = ("card_exercise_" if exercise else "card_") + suffix
    assert not (exercise and multiple_choice)
    choices = (
        [
            QuizChoice(label="A", text="Retry immediately <without delay>."),
            QuizChoice(label="B", text="Discard the request."),
            QuizChoice(label="C", text="retry_later()", is_correct=True),
            QuizChoice(label="D", text="Raise an unrelated error."),
        ]
        if multiple_choice
        else None
    )
    question = QuizQuestion(
        question_id=("quiz_exercise_" if exercise else "quiz_") + suffix,
        review_card_id=card_id,
        question="Predict the missing call:\nif failed:\n    ____",
        expected_answer="retry_later()",
        quiz_kind="transfer" if exercise else "recall",
        exercise_kind="completion" if exercise else None,
        answer_mode="multiple_choice" if multiple_choice else "open",
        choices=choices,
        source_claims=["synthetic-claim"],
        concepts=["retry_later()"],
        source_anchors=[anchor] if anchor else [],
        evidence=[] if anchor else [QuizEvidence(file="after/sample.py", line=1)],
    )
    maps = load_line_map_records(run / "line_map.json")
    card = ReviewCard(
        card_id=card_id,
        concept="retry_later()",
        run_id=run.name,
        source_ref=capture.run_source.source_ref,
        fsrs_state="{}",
        file_id="synthetic-file",
        display_path=anchor.file if anchor else "after/sample.py",
        hunk_id=f"document-anchor:{anchor.anchor_id}"
        if kind == "document" and anchor
        else maps[0].hunks[0].hunk_id,
        hunk_hash=anchor.content_hash
        if kind == "document" and anchor
        else maps[0].hunks[0].hunk_hash,
        question=question.question,
        answer=question.expected_answer,
        answer_mode=question.answer_mode,
        choices=question.choices,
        source_anchors=[anchor] if anchor else [],
    )
    (run / "quiz").mkdir(exist_ok=True)
    write_quiz_questions_jsonl(run / "quiz" / "quiz.jsonl", [question])
    write_review_cards_jsonl(run / "quiz" / "cards.jsonl", [card])
    import_cards_from_jsonl(root / ".ahadiff" / "review.sqlite", run / "quiz" / "cards.jsonl")
    _finalize(run)
    return run, card, anchor


def _notes(package: bytes, root: Path) -> tuple[list[tuple[str, str, str]], dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        collection = root / "exported-collection.sqlite"
        collection.write_bytes(archive.read("collection.anki2"))
    with sqlite3.connect(collection.as_uri() + "?mode=ro", uri=True) as database:
        rows = database.execute("SELECT guid, flds FROM notes ORDER BY id").fetchall()
        models = json.loads(database.execute("SELECT models FROM col").fetchone()[0])
    notes: list[tuple[str, str, str]] = []
    for guid, fields in rows:
        front, back = str(fields).split("\x1f")
        notes.append((str(guid), front, back))
    return notes, models


@pytest.mark.parametrize("lang", ["en", "zh-CN"])
def test_real_apkg_document_practice_preserves_guid_and_reveals_sources_only_on_back(
    tmp_path: Path, lang: Literal["en", "zh-CN"]
) -> None:
    root = tmp_path.resolve()
    run, card, anchor = _new_card_run(root, lang=lang, auxiliary=True)
    assert anchor is not None
    notes, models = _notes(export_apkg(root / ".ahadiff" / "review.sqlite"), root)
    guid, front, back = notes[0]
    assert guid == import_module("genanki").guid_for(card.card_id)
    assert "Predict the missing call:\nif failed:\n    ____" in front
    assert "retry_later()" not in front
    assert anchor.quote not in front
    assert "retry_later()" in back
    assert "&lt;failure&gt; &amp; preserve order." in back
    assert "<failure>" not in back
    assert anchor.content_hash in back
    assert anchor.file in back
    assert "paragraph" in back
    assert "markdown" in back
    assert "document-anchor:" not in back
    assert "hunk" not in back
    assert "auxiliary_untrusted" in back
    assert "Synthetic reviewer context" not in back
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["review_context_hash"] in back
    if lang == "zh-CN":
        assert "语义自评" in back and "未执行你的代码" in back
        assert "独立 Markdown 文档来源" in back
    else:
        assert "semantic self-assessment" in back and "did not execute your code" in back
        assert "independent Markdown document source" in back
    model = next(iter(models.values()))
    assert model["tmpls"][0]["qfmt"] == "{{Front}}"
    assert model["tmpls"][0]["afmt"] == '{{FrontSide}}<hr id="answer">{{Back}}'


@pytest.mark.parametrize("kind", ["markdown", "notebook", "json", "toml", "yaml"])
def test_real_apkg_exports_format_locator_side_and_exact_source_hash(
    tmp_path: Path, kind: str
) -> None:
    root = tmp_path.resolve()
    _, _, anchor = _new_card_run(root, kind=kind, exercise=False)
    assert anchor is not None
    notes, _ = _notes(export_apkg(root / ".ahadiff" / "review.sqlite"), root)
    back = notes[0][2]
    assert f":</strong> {kind}" in back
    assert "Side:</strong> new" in back
    assert anchor.content_hash in back
    assert anchor.locator.kind in back
    assert "semantic self-assessment" not in back
    if kind in {"json", "toml", "yaml"}:
        assert "key_path" in back and "retries" in back
    if kind == "notebook":
        assert "cell_index" in back and "synthetic-cell" in back


@pytest.mark.parametrize("lang", ["en", "zh-CN"])
def test_real_apkg_new_source_mcq_exports_all_options_and_correct_label_with_text(
    tmp_path: Path, lang: Literal["en", "zh-CN"]
) -> None:
    root = tmp_path.resolve()
    run, card, anchor = _new_card_run(root, lang=lang, exercise=False, multiple_choice=True)
    assert card.choices is not None and anchor is not None
    details = load_card_sources(root / ".ahadiff", run.name)[card.card_id]
    assert details.answer_mode == "multiple_choice"
    assert details.choices == tuple(card.choices)
    assert details.exercise_kind is None
    notes, _ = _notes(export_apkg(root / ".ahadiff" / "review.sqlite"), root)
    guid, front, back = notes[0]
    assert guid == import_module("genanki").guid_for(card.card_id)
    for choice in card.choices:
        assert f"<strong>{choice.label}.</strong>" in front
    assert "Retry immediately &lt;without delay&gt;." in front
    assert "Discard the request." in front
    assert "retry_later()" in front
    assert "Raise an unrelated error." in front
    assert "<without delay>" not in front
    assert "is_correct" not in front
    assert anchor.content_hash not in front
    assert "semantic self-assessment" not in back
    assert "C. retry_later()" in back
    assert anchor.content_hash in back


@pytest.mark.parametrize(
    "declaration",
    [
        {"source_evidence_version": None},
        {"source_evidence_version": 0},
        {"source_kind": "document"},
        {"review_context_used": True},
        {"review_context_hash": None},
        {"review_context_used": False, "review_context_hash": "orphan"},
    ],
)
def test_source_declaration_presence_requires_validation_even_when_values_are_invalid(
    tmp_path: Path, declaration: dict[str, object]
) -> None:
    state = tmp_path.resolve() / ".ahadiff"
    run = state / "runs" / "declared-run"
    run.mkdir(parents=True)
    metadata = {
        "run_id": run.name,
        "source_kind": "git_ref",
        "source_ref": "synthetic-ref",
        "content_lang": "en",
        **declaration,
    }
    (run / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    assert declares_source_artifacts(run, metadata) is True
    with pytest.raises(InputError, match="source evidence version"):
        load_card_sources(state, run.name)
    with pytest.raises(InputError, match="finalized"):
        require_finalized_source(run, metadata)


@pytest.mark.parametrize(
    "artifact", ["document.md", "evidence_anchors.json", "review_context.json"]
)
def test_source_declaration_detects_orphaned_artifact_entries(
    tmp_path: Path, artifact: str
) -> None:
    run = tmp_path.resolve() / "run"
    run.mkdir()
    path = run / artifact
    path.write_text("orphan", encoding="utf-8")
    assert declares_source_artifacts(run, {}) is True
    path.unlink()
    try:
        path.symlink_to(run / "missing-target")
    except OSError:
        pytest.skip("symlink creation unavailable on this platform")
    assert declares_source_artifacts(run, {}) is True


def test_legacy_source_without_declarations_keeps_compatibility(tmp_path: Path) -> None:
    run = tmp_path.resolve() / "missing-legacy-run"
    assert declares_source_artifacts(run, {"source_kind": "git_ref"}) is False
    assert declares_source_artifacts(run, {"review_context_used": False}) is False
    assert not run.exists()


def test_new_python_cards_keep_line_evidence_compatible(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    run, card, anchor = _new_card_run(root, kind="python", exercise=False)
    assert anchor is None
    source = load_card_sources(root / ".ahadiff", run.name)[card.card_id]
    assert source.source_anchors == ()
    notes, _ = _notes(export_apkg(root / ".ahadiff" / "review.sqlite"), root)
    assert "after/sample.py" in notes[0][2]


def test_old_card_front_back_and_guid_are_unchanged(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    state = root / ".ahadiff"
    state.mkdir()
    card = ReviewCard(
        card_id="old-card",
        concept="Old <concept>",
        run_id="old-run",
        source_ref="old-ref",
        fsrs_state="{}",
        file_id="old-file",
        display_path="src/old.py",
        hunk_id="old-hunk",
        hunk_hash="old-hash",
        answer="<old answer>",
    )
    path = root / "old-cards.jsonl"
    write_review_cards_jsonl(path, [card])
    import_cards_from_jsonl(state / "review.sqlite", path)
    old_run = state / "runs" / card.run_id
    old_run.mkdir(parents=True)
    (old_run / "metadata.json").write_text('{"source_kind":"git_ref"}', encoding="utf-8")
    (old_run / "finalized.json").write_text('{"old_marker":true}', encoding="utf-8")
    assert load_card_sources(state, card.run_id) == {}
    notes, _ = _notes(export_apkg(state / "review.sqlite"), root)
    assert notes == [
        (
            import_module("genanki").guid_for("old-card"),
            "Old &lt;concept&gt;",
            "<div>&lt;old answer&gt;</div>\n<hr>\n"
            "<div><strong>Source:</strong> old-ref</div>\n"
            "<div><strong>Path:</strong> src/old.py</div>",
        )
    ]


def test_card_sources_are_read_only_and_missing_old_runs_do_not_create_state(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    assert load_card_sources(root / "missing-state", "old-run") == {}
    assert not (root / "missing-state").exists()
    run, card, _ = _new_card_run(root)
    before = {str(path): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    details = load_card_sources(root / ".ahadiff", run.name)[card.card_id]
    assert details.question == card.question
    assert details.answer == card.answer
    assert details.exercise_kind == "completion"
    assert details.review_context_used is False
    assert details.review_context_hash is None
    assert before == {str(path): path.read_bytes() for path in run.rglob("*") if path.is_file()}


@pytest.mark.parametrize(
    "artifact",
    [
        "metadata.json",
        "document.md",
        "evidence_anchors.json",
        "quiz/quiz.jsonl",
        "quiz/cards.jsonl",
        "finalized.json",
    ],
)
def test_new_source_missing_artifacts_reject_export_without_replacing_output(
    tmp_path: Path, artifact: str
) -> None:
    root = tmp_path.resolve()
    run, _, _ = _new_card_run(root)
    (run / artifact).unlink()
    output = root / "existing.apkg"
    output.write_bytes(b"preserve existing export")
    with pytest.raises(InputError):
        export_apkg(root / ".ahadiff" / "review.sqlite", output)
    assert output.read_bytes() == b"preserve existing export"


@pytest.mark.parametrize("field,value", [("artifact_count", True), ("checksum", "0" * 64)])
def test_new_source_requires_real_finalized_count_and_checksum(
    tmp_path: Path, field: str, value: object
) -> None:
    root = tmp_path.resolve()
    run, _, _ = _new_card_run(root)
    marker_path = run / "finalized.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker[field] = value
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(InputError, match="finalized"):
        load_card_sources(root / ".ahadiff", run.name)


@pytest.mark.parametrize(
    "artifact", ["document.md", "evidence_anchors.json", "review_context.json"]
)
def test_source_semantics_remain_checked_even_after_resigning_finalized_marker(
    tmp_path: Path, artifact: str
) -> None:
    root = tmp_path.resolve()
    run, _, _ = _new_card_run(root, auxiliary=True)
    path = run / artifact
    if artifact == "review_context.json":
        context = json.loads(path.read_text(encoding="utf-8"))
        context["content"] += " changed"
        path.write_text(json.dumps(context), encoding="utf-8")
    else:
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    _finalize(run)
    with pytest.raises(InputError, match="hash mismatch|invalid"):
        load_card_sources(root / ".ahadiff", run.name)


@pytest.mark.parametrize("change", ["answer", "anchor", "membership", "duplicate"])
def test_card_and_quiz_identity_and_anchor_membership_are_checked(
    tmp_path: Path, change: str
) -> None:
    root = tmp_path.resolve()
    run, _, _ = _new_card_run(root)
    path = run / "quiz" / "cards.jsonl"
    card = json.loads(path.read_text(encoding="utf-8"))
    if change == "answer":
        card["answer"] = "wrong reference"
    elif change == "anchor":
        card["source_anchors"][0]["quote"] = "wrong quote"
    elif change == "membership":
        card["card_id"] = "unknown-card"
    rendered = json.dumps(card) + "\n"
    if change == "duplicate":
        rendered += rendered
    path.write_text(rendered, encoding="utf-8")
    _finalize(run)
    with pytest.raises(InputError, match="identity|mismatch|anchor|invalid"):
        load_card_sources(root / ".ahadiff", run.name)


@pytest.mark.parametrize("relative", ["runs", "run", "quiz"])
def test_card_source_directory_links_are_rejected(tmp_path: Path, relative: str) -> None:
    root = tmp_path.resolve()
    run, _, _ = _new_card_run(root)
    target = (
        root / ".ahadiff" / "runs"
        if relative == "runs"
        else run
        if relative == "run"
        else run / "quiz"
    )
    outside = root / "outside"
    target.rename(outside)
    try:
        target.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this platform")
    with pytest.raises(InputError):
        load_card_sources(root / ".ahadiff", run.name)


@pytest.mark.parametrize(
    "relative", ["metadata.json", "finalized.json", "quiz/cards.jsonl", "document.md"]
)
def test_card_source_hardlinked_leaves_are_rejected(tmp_path: Path, relative: str) -> None:
    root = tmp_path.resolve()
    run, _, _ = _new_card_run(root)
    path = run / relative
    outside = root / "outside.json"
    try:
        outside.hardlink_to(path)
    except OSError:
        pytest.skip("hardlink creation unavailable on this platform")
    with pytest.raises(InputError):
        load_card_sources(root / ".ahadiff", run.name)


def test_finalized_helper_rejects_metadata_changed_since_read(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    run, _, _ = _new_card_run(root)
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    metadata["content_lang"] = "zh-CN"
    with pytest.raises(InputError, match="metadata changed"):
        require_finalized_source(run, metadata)


def test_canonical_card_text_is_used_when_mutable_database_text_drifts(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    _, card, _ = _new_card_run(root)
    database_path = root / ".ahadiff" / "review.sqlite"
    with sqlite3.connect(database_path) as database:
        database.execute(
            "UPDATE cards SET question = ?, answer = ? WHERE id = ?",
            ("unexpected mutable question", "unexpected mutable answer", card.card_id),
        )
    notes, _ = _notes(export_apkg(database_path), root)
    assert card.question is not None and card.question in notes[0][1]
    assert card.answer is not None and card.answer in notes[0][2]
    assert "unexpected mutable" not in notes[0][1] + notes[0][2]


def test_card_source_safe_read_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path.resolve()
    run, _, _ = _new_card_run(root)
    original = card_sources.read_learning_text

    def bounded(root: Path, file: Path, *, max_bytes: int) -> str:
        assert 0 < max_bytes <= 16 * 1024 * 1024
        return original(root, file, max_bytes=max_bytes)

    monkeypatch.setattr(card_sources, "read_learning_text", bounded)
    assert load_card_sources(root / ".ahadiff", run.name)


def _publish_consumer_result(run: Path) -> None:
    # Publish an actual deterministic score, result event and full final marker.
    # There is no provider, score mock or hand-written PASS verdict in this fixture.
    report = evaluate_run(run)
    score_path = write_score_report(run / "score.json", report)
    outcome = append_result(
        run_path=run,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="learn",
        score_path=score_path,
    )
    assert outcome.sqlite_inserted and outcome.finalized_written
    assert outcome.warnings == ()
    marker = json.loads((run / "finalized.json").read_text(encoding="utf-8"))
    assert marker["event_id"] == outcome.event.event_id
    assert (marker["artifact_count"], marker["checksum"]) == finalized_artifact_digest(run)


def _consumer_document_run(
    root: Path,
    *,
    lang: Literal["en", "zh-CN"] = "en",
    document_content: str | None = None,
    exercise: bool = True,
    multiple_choice: bool = False,
) -> tuple[Path, ReviewCard, SourceAnchor]:
    run, card, primary = _new_card_run(
        root,
        lang=lang,
        auxiliary=True,
        document_content=document_content,
        exercise=exercise,
        multiple_choice=multiple_choice,
    )
    assert primary is not None
    anchors = load_evidence_anchors(run)
    verified = [
        verify_claim_candidate(
            ClaimCandidate(
                claim_id="synthetic-claim"
                if anchor.anchor_id == primary.anchor_id
                else f"synthetic-heading-{index}",
                run_id=run.name,
                text=anchor.quote,
                source_anchors=[anchor],
                assertion_kind="source_fact",
            ),
            line_maps=(),
            symbols=(),
            source_anchors=anchors,
            source_kind="document",
        )
        for index, anchor in enumerate(anchors)
    ]
    assert all(claim.record.status == "verified" for claim in verified)
    write_verified_claims_jsonl(run / "claims.jsonl", verified)
    sources = [f"{anchor.file}:document:{anchor.start}-{anchor.end}" for anchor in anchors]
    write_selected_lesson_artifacts(
        run_path=run,
        full=LessonFull(
            tl_dr="Retry ordering keeps transient failures in the queue.",
            what_changed=[anchor.quote for anchor in anchors],
            why=["Read the documented retry behavior."],
            walkthrough=["Find retry_later and preserve order in the source paragraph."],
            claims=[anchor.quote for anchor in anchors],
            concepts=["retry ordering"],
            not_proven=["No program execution is part of this source."],
            quiz=["Predict the missing retry call."],
            sources=sources,
        ),
        hint=LessonHint(
            tl_dr="Recall retry ordering.",
            key_points=[primary.quote],
            claims=[primary.quote],
            sources=sources,
        ),
        compact=LessonCompact(
            headline="Retry ordering",
            summary=[primary.quote],
            concepts=["retry ordering"],
            sources=sources,
        ),
        source_kind="document",
        output_lang=lang,
    )
    _publish_consumer_result(run)
    return run, card, primary


def _make_card_due(db_path: Path, card_id: str) -> None:
    with sqlite3.connect(db_path) as database:
        database.execute(
            "UPDATE cards SET due_date = ? WHERE id = ?",
            ("2000-01-01T00:00:00Z", card_id),
        )


def test_mcp_ask_lesson_returns_document_evidence_and_separate_auxiliary_metadata(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    run, _, anchor = _consumer_document_run(root)
    response = _ask_lesson(
        root / ".ahadiff",
        {"run_id": run.name, "question": "retry_later preserve order", "top_k": 3},
    )
    assert response["fragments"]
    assert response["evidence"]
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    run_meta = response["run_meta"]
    assert run_meta["source_kind"] == "document"
    assert run_meta["source_ref"] == metadata["source_ref"]
    assert run_meta["review_context_used"] is True
    assert run_meta["review_context"]["kind"] == "auxiliary_untrusted"
    assert run_meta["review_context"]["content_hash"] == metadata["review_context_hash"]
    assert "Synthetic reviewer context" in run_meta["review_context"]["excerpt"]
    evidence = next(
        entry for entry in response["evidence"] if entry["claim_id"] == "synthetic-claim"
    )
    assert evidence["source_hunks"] == []
    assert evidence["hunk_hash"] == ""
    assert evidence["assertion_kind"] == "source_fact"
    assert evidence["source_anchors"] == [anchor.model_dump(mode="json")]
    assert evidence["file"] == anchor.file
    assert evidence["line_start"] == anchor.start and evidence["line_end"] == anchor.end
    assert "Synthetic reviewer context" not in json.dumps(response["evidence"])
    assert "document-anchor:" not in json.dumps(response)


def test_mcp_due_active_document_cards_hide_reference_until_explicitly_requested(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    run, card, anchor = _consumer_document_run(root)
    db_path = root / ".ahadiff" / "review.sqlite"
    _make_card_due(db_path, card.card_id)
    public = _list_due_cards(db_path, {"limit": 10})["cards"]
    assert len(public) == 1
    assert public[0]["card_id"] == card.card_id
    assert public[0]["question"] == card.question
    assert public[0]["reference_available"] is True
    assert public[0]["feedback_kind"] == "semantic_self_assessment"
    assert set(public[0]).isdisjoint(
        {
            "answer",
            "concept",
            "symbol",
            "source_ref",
            "display_path",
            "source_anchors",
            "review_context_hash",
        }
    )
    assert "retry_later()" not in json.dumps(public)
    reference = _list_due_cards(db_path, {"limit": 10, "include_reference": True})["cards"][0]
    assert reference["answer"] == card.answer
    assert reference["source_kind"] == "document"
    assert reference["source_anchors"] == [anchor.model_dump(mode="json")]
    assert reference["feedback_kind"] == "semantic_self_assessment"
    assert reference["review_context_used"] is True
    assert reference["run_id"] == run.name
    assert "document-anchor:" not in json.dumps(reference)
    assert set(reference).isdisjoint({"file_id", "hunk_id", "hunk_hash"})
    with sqlite3.connect(db_path) as database:
        assert database.execute("SELECT COUNT(*) FROM review_logs").fetchone()[0] == 0
        assert database.execute("SELECT COUNT(*) FROM learning_signals").fetchone()[0] == 0


def test_mcp_old_due_cards_keep_their_default_payload(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    state = root / ".ahadiff"
    state.mkdir()
    card = ReviewCard(
        card_id="legacy-mcp-card",
        concept="Legacy concept",
        run_id="legacy-run",
        source_ref="legacy-ref",
        fsrs_state="{}",
        file_id="legacy-file",
        display_path="legacy.py",
        hunk_id="legacy-hunk",
        hunk_hash="legacy-hash",
        question="Legacy question?",
        answer="Legacy reference.",
        symbol="legacy_symbol",
    )
    cards = root / "legacy-cards.jsonl"
    write_review_cards_jsonl(cards, [card])
    import_cards_from_jsonl(state / "review.sqlite", cards)
    _make_card_due(state / "review.sqlite", card.card_id)
    default = _list_due_cards(state / "review.sqlite", {"limit": 10})
    explicit = _list_due_cards(state / "review.sqlite", {"limit": 10, "include_reference": True})
    assert default == explicit
    payload = default["cards"][0]
    assert payload["answer"] == card.answer
    assert payload["concept"] == card.concept
    assert payload["symbol"] == card.symbol
    assert payload["source_ref"] == card.source_ref
    assert "reference_available" not in payload
    assert "source_anchors" not in payload


def test_static_preview_exports_independent_document_and_hash_bound_provenance(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    run, _, anchor = _consumer_document_run(root)
    output = root / "document-preview"
    manifest = export_preview(run.name, output, root / ".ahadiff")
    payload = json.loads((output / "data" / "run.json").read_text(encoding="utf-8"))
    document = (run / "document.md").read_text(encoding="utf-8")
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    assert manifest.run_id == run.name
    assert payload["source"] == {
        "source_kind": "document",
        "artifact": "document.md",
        "text": document,
        "content_hash": hashlib.sha256(document.encode("utf-8")).hexdigest(),
    }
    assert payload["metadata"] == metadata
    assert anchor.model_dump(mode="json") in payload["source_anchors"]
    assert payload["review_context"]["kind"] == "auxiliary_untrusted"
    assert payload["review_context"]["content_hash"] == metadata["review_context_hash"]
    assert (
        hashlib.sha256(payload["review_context"]["content"].encode()).hexdigest()
        == metadata["review_context_hash"]
    )
    assert all(claim["source_hunks"] == [] for claim in payload["claims"])
    assert all(
        item["content_hash"] == hashlib.sha256(item["quote"].encode()).hexdigest()
        for item in payload["source_anchors"]
    )
    assert set(payload).isdisjoint({"patch", "patch_text", "diff"})
    assert not (run / "patch.diff").exists()
    assert not (output / "patch.diff").exists()


@pytest.mark.parametrize("consumer", ["mcp", "preview"])
@pytest.mark.parametrize(
    "artifact", ["metadata.json", "document.md", "evidence_anchors.json", "review_context.json"]
)
@pytest.mark.parametrize("damage", ["missing", "invalid"])
def test_source_consumers_fail_closed_on_missing_or_invalid_declared_artifacts(
    tmp_path: Path, consumer: str, artifact: str, damage: str
) -> None:
    root = tmp_path.resolve()
    run, _, _ = _consumer_document_run(root)
    path = run / artifact
    if damage == "missing":
        path.unlink()
    else:
        path.write_text("Invalid synthetic source artifact.", encoding="utf-8")
    # Keep final checksum current so this exercises source-level validation too.
    _finalize(run)
    with pytest.raises((AhaDiffError, ValueError)):
        if consumer == "mcp":
            _ask_lesson(root / ".ahadiff", {"run_id": run.name, "question": "retry_later"})
        else:
            export_preview(run.name, root / "rejected-preview", root / ".ahadiff")
    assert not (root / "rejected-preview").exists()


@pytest.mark.parametrize("consumer", ["mcp", "preview"])
def test_source_consumers_reject_claims_changed_after_finalization(
    tmp_path: Path, consumer: str
) -> None:
    root = tmp_path.resolve()
    run, _, _ = _consumer_document_run(root)
    claims = run / "claims.jsonl"
    rows = [json.loads(line) for line in claims.read_text(encoding="utf-8").splitlines()]
    rows[0]["text"] = "Forged source claim after finalization."
    claims.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(AhaDiffError, match="checksum"):
        if consumer == "mcp":
            _ask_lesson(root / ".ahadiff", {"run_id": run.name, "question": "retry_later"})
        else:
            export_preview(run.name, root / "rejected-preview", root / ".ahadiff")
    assert not (root / "rejected-preview").exists()


@pytest.mark.parametrize("lang", ["en", "zh-CN"])
def test_cli_document_exercise_records_one_semantic_attempt_and_one_real_srs_review(
    tmp_path: Path, lang: Literal["en", "zh-CN"]
) -> None:
    root = tmp_path.resolve()
    run, card, _ = _consumer_document_run(root, lang=lang)
    free_answer = "Synthetic learner wording: enqueue a retry after the transient failure."
    result = CliRunner().invoke(
        app(),
        ["quiz", run.name, "--repo-root", str(root), "--lang", lang],
        input=f"{free_answer}\n3\n",
    )
    assert result.exit_code == 0, result.output
    assert "retry_later()" in result.output
    if lang == "zh-CN":
        assert "语义反馈，未执行代码" in result.output
        assert "已完成 1 项练习自评" in result.output
        assert "答案匹配结果" not in result.output
    else:
        assert "semantic feedback; code was not executed" in result.output
        assert "Self-assessed 1 exercises" in result.output
        assert "Score (answer matches)" not in result.output
    with sqlite3.connect(root / ".ahadiff" / "review.sqlite") as database:
        assert database.execute("SELECT card_id, rating FROM review_logs").fetchall() == [
            (card.card_id, 3)
        ]
        assert database.execute("SELECT COUNT(*) FROM result_events").fetchone()[0] == 1
        signals = {
            kind: json.loads(payload)
            for kind, payload in database.execute(
                "SELECT signal_type, payload_json FROM learning_signals"
            ).fetchall()
        }
        assert database.execute("SELECT COUNT(*) FROM learning_signals").fetchone()[0] == 2
        assert set(signals) == {"srs_review", "quiz_answer"}
        assert signals["srs_review"]["card_id"] == card.card_id
        assert signals["srs_review"]["answer"] == "good"
        quiz = signals["quiz_answer"]
        assert quiz["run_id"] == run.name
        assert quiz["correct"] is None
        assert quiz["feedback_kind"] == "semantic_self_assessment"
        assert quiz["self_assessment"] == "independent" and quiz["error_type"] == "none"
        assert "choice" not in quiz
        assert free_answer not in "\n".join(database.iterdump())
        assert database.execute(
            "SELECT reps, last_rating FROM cards WHERE id = ?", (card.card_id,)
        ).fetchone() == (1, 3)


def test_source_artifact_api_reads_a_real_scored_finalized_document_run(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    run, _, anchor = _consumer_document_run(root)
    before = {str(path): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    client = TestClient(
        create_app(ServeState(state_dir=root / ".ahadiff", token="test-token", locale="en")),
        base_url="http://localhost:8765",
    )
    headers = {"X-AhaDiff-Token": "test-token"}
    detail = client.get(f"/api/run/{run.name}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["source_kind"] == "document"
    assert detail.json()["review_context_used"] is True
    document = client.get(f"/api/run/{run.name}/document", headers=headers)
    assert document.status_code == 200
    assert document.json()["content"] == (run / "document.md").read_text(encoding="utf-8")
    anchors = client.get(f"/api/run/{run.name}/anchors", headers=headers)
    assert anchors.status_code == 200
    assert anchor.model_dump(mode="json") in json.loads(anchors.json()["content"])["anchors"]
    auxiliary = client.get(f"/api/run/{run.name}/review-context", headers=headers)
    assert auxiliary.status_code == 200
    assert json.loads(auxiliary.json()["content"])["kind"] == "auxiliary_untrusted"
    assert before == {str(path): path.read_bytes() for path in run.rglob("*") if path.is_file()}


def test_review_queue_uses_immutable_source_question_when_database_text_drifts(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    _, card, anchor = _consumer_document_run(root, exercise=False, multiple_choice=True)
    db_path = root / ".ahadiff" / "review.sqlite"
    _make_card_due(db_path, card.card_id)
    with sqlite3.connect(db_path) as database:
        database.execute(
            "UPDATE cards SET question = ?, answer = ?, answer_mode = ?, choices_json = ? "
            "WHERE id = ?",
            ("Stale question?", "Stale reference.", "open", None, card.card_id),
        )
    client = TestClient(
        create_app(ServeState(state_dir=root / ".ahadiff", token="test-token", locale="en")),
        base_url="http://localhost:8765",
    )
    response = client.get("/api/review/queue")
    assert response.status_code == 200, response.text
    projected = response.json()["cards"][0]
    assert projected["question"] == card.question
    assert projected["answer"] == card.answer
    assert projected["answer_mode"] == card.answer_mode
    assert projected["choices"] == [choice.model_dump(mode="json") for choice in card.choices or ()]
    assert projected["source_anchors"] == [anchor.model_dump(mode="json")]
    assert "Stale" not in response.text
    rated = client.post(
        "/api/review/rate",
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
        json={
            "card_id": card.card_id,
            "answer": "good",
            "selected_choice_label": "C",
            "idempotency_key": "immutable-choice-rating",
        },
    )
    assert rated.status_code == 200, rated.text
    with sqlite3.connect(db_path) as database:
        raw = database.execute(
            "SELECT payload_json FROM learning_signals WHERE idempotency_key = ?",
            ("immutable-choice-rating",),
        ).fetchone()[0]
    assert json.loads(raw)["choice_correct"] is True
    archived = client.post(
        "/api/review/queue-state",
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
        json={"card_id": card.card_id, "state": "archived"},
    )
    assert archived.status_code == 200, archived.text
    replay = client.post(
        "/api/review/rate",
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
        json={
            "card_id": card.card_id,
            "answer": "good",
            "selected_choice_label": "C",
            "idempotency_key": "immutable-choice-rating",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == {"inserted": False}


@pytest.mark.parametrize("artifact", ["evidence_anchors.json", "finalized.json", "quiz/quiz.jsonl"])
def test_review_queue_hides_source_cards_when_declared_artifacts_are_missing(
    tmp_path: Path, artifact: str
) -> None:
    root = tmp_path.resolve()
    run, card, _ = _consumer_document_run(root, exercise=False, multiple_choice=True)
    _make_card_due(root / ".ahadiff" / "review.sqlite", card.card_id)
    client = TestClient(
        create_app(ServeState(state_dir=root / ".ahadiff", token="test-token", locale="en")),
        base_url="http://localhost:8765",
    )
    assert client.get("/api/review/queue").json()["cards"][0]["card_id"] == card.card_id
    (run / artifact).unlink()
    if artifact != "finalized.json":
        # A consistent outer digest must not permit a source-aware card to use
        # the compatibility path when its declared source/quiz is unavailable.
        _refresh_real_finalized_marker(run)
    response = client.get("/api/review/queue")
    assert response.status_code == 200, response.text
    assert response.json() == {"cards": []}
    rated = client.post(
        "/api/review/rate",
        headers={"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"},
        json={
            "card_id": card.card_id,
            "answer": "good",
            "selected_choice_label": "C",
            "idempotency_key": "missing-source-rating",
        },
    )
    assert rated.status_code == 400, rated.text
    with sqlite3.connect(root / ".ahadiff" / "review.sqlite") as database:
        assert database.execute("SELECT COUNT(*) FROM learning_signals").fetchone()[0] == 0


def test_review_queue_scans_past_missing_source_cards_for_valid_due_work(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    invalid_run, invalid_card, _ = _consumer_document_run(root)
    _, valid_card, _ = _consumer_document_run(root)
    db_path = root / ".ahadiff" / "review.sqlite"
    _make_card_due(db_path, valid_card.card_id)
    # A run whose artifacts were removed must not fill the queue with rejected
    # candidates and hide intact runs that are later in due order.
    missing_cards = [
        invalid_card.model_copy(update={"card_id": f"card_exercise_missing_{index}"})
        for index in range(20)
    ]
    missing_path = invalid_run / "quiz" / "cards.jsonl"
    write_review_cards_jsonl(missing_path, missing_cards, overwrite=True)
    import_cards_from_jsonl(db_path, missing_path)
    with sqlite3.connect(db_path) as database:
        database.execute(
            "UPDATE cards SET due_date = ? WHERE run_id = ?",
            ("1999-01-01T00:00:00Z", invalid_run.name),
        )
    (invalid_run / "finalized.json").unlink()
    client = TestClient(
        create_app(ServeState(state_dir=root / ".ahadiff", token="test-token", locale="en")),
        base_url="http://localhost:8765",
    )
    response = client.get("/api/review/queue")
    assert response.status_code == 200, response.text
    assert [card["card_id"] for card in response.json()["cards"]] == [valid_card.card_id]


def _legacy_comparison_consumer_run(root: Path) -> Path:
    run, _, _ = _new_card_run(root, kind="python", exercise=False)
    metadata_path = run / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    for name in (
        "source_evidence_version",
        "evidence_anchors_hash",
        "review_context_used",
        "review_context_hash",
    ):
        metadata.pop(name, None)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    (run / "evidence_anchors.json").unlink()
    line_maps = load_line_map_records(run / "line_map.json")
    file = line_maps[0]
    hunk = file.hunks[0]
    start = hunk.added_lines[0]
    source_hunk = SourceHunk(
        file=file.display_path,
        start=start,
        end=start,
        side="new",
        hunk_id=hunk.hunk_id,
        hunk_hash=hunk.hunk_hash,
    )
    verified = verify_claim_candidate(
        ClaimCandidate(
            claim_id="synthetic-claim",
            run_id=run.name,
            text="The retries value changes to 2.",
            source_hunks=[source_hunk],
        ),
        line_maps=line_maps,
        symbols=(),
    )
    assert verified.record.status != "rejected"
    write_verified_claims_jsonl(run / "claims.jsonl", [verified])
    write_selected_lesson_artifacts(
        run_path=run,
        full=LessonFull(
            tl_dr="Retries now use the updated value.",
            what_changed=["The retries value changes to 2."],
            why=["Keep retry configuration explicit."],
            walkthrough=["Read the changed retries assignment."],
            claims=[verified.record.text],
            concepts=["retries"],
            quiz=["What is the retries value?"],
            sources=[f"{file.display_path}:{start}"],
        ),
    )
    assert declares_source_artifacts(run, metadata) is False
    _publish_consumer_result(run)
    return run


def _refresh_real_finalized_marker(run: Path) -> None:
    event = next(
        event
        for event in load_result_events_from_db(run.parent.parent / "review.sqlite")
        if event.run_id == run.name
    )
    write_finalized_result(run_path=run, event=event, score_path=run / "score.json")
    marker = json.loads((run / "finalized.json").read_text(encoding="utf-8"))
    assert marker["event_id"] == event.event_id
    assert (marker["artifact_count"], marker["checksum"]) == finalized_artifact_digest(run)


@pytest.mark.parametrize(
    "declaration",
    [
        {"source_evidence_version": None},
        {"source_evidence_version": True},
        {"source_evidence_version": 1.0},
        {"evidence_anchors_hash": "a" * 64},
        {"review_context_used": True},
        {"review_context_hash": None},
        {"review_context_used": True, "review_context_hash": "f" * 64},
    ],
)
def test_orphan_source_declarations_cannot_enter_cli_api_mcp_or_export_legacy_fallback(
    tmp_path: Path, declaration: dict[str, object]
) -> None:
    root = tmp_path.resolve()
    state_dir = root / ".ahadiff"
    run = _legacy_comparison_consumer_run(root)
    headers = {"X-AhaDiff-Token": "test-token"}
    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token", locale="en")),
        base_url="http://localhost:8765",
    )
    # Establish that the legacy-shaped source is readable before introducing the
    # sole invalid declaration. Its score/event and common artifacts are real.
    assert client.get(f"/api/run/{run.name}", headers=headers).status_code == 200
    assert _ask_lesson(state_dir, {"run_id": run.name, "question": "retries"})["fragments"]
    export_preview(run.name, root / "legacy-preview", state_dir)
    baseline = CliRunner().invoke(
        app(),
        ["quiz", run.name, "--repo-root", str(root), "--lang", "en"],
        input="retry_later()\n",
    )
    assert baseline.exit_code == 0, baseline.output

    metadata_path = run / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(declaration)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    _refresh_real_finalized_marker(run)
    assert declares_source_artifacts(run, metadata) is True
    assert not (run / "evidence_anchors.json").exists()
    assert not (run / "review_context.json").exists()
    require_finalized_source(run, metadata)

    rejected = CliRunner().invoke(
        app(), ["quiz", run.name, "--repo-root", str(root), "--lang", "en"]
    )
    assert rejected.exit_code != 0
    assert "source evidence" in rejected.output or "review" in rejected.output
    assert "checksum mismatch" not in rejected.output
    assert "Question 1" not in rejected.output
    response = client.get(f"/api/run/{run.name}", headers=headers)
    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "INPUT_BAD_FIELD"
    assert "checksum mismatch" not in response.text
    for consumer in ("mcp", "preview"):
        with pytest.raises(InputError) as failed:
            if consumer == "mcp":
                _ask_lesson(state_dir, {"run_id": run.name, "question": "retries"})
            else:
                export_preview(run.name, root / "rejected-orphan-preview", state_dir)
        message = str(failed.value)
        assert "source evidence" in message or "review" in message
        assert "checksum mismatch" not in message
    assert not (root / "rejected-orphan-preview").exists()


def test_mcp_rejects_database_source_ref_that_disagrees_with_immutable_card(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    run, card, _ = _new_card_run(root, exercise=False, multiple_choice=True)
    db_path = root / ".ahadiff" / "review.sqlite"
    _make_card_due(db_path, card.card_id)
    original = _list_due_cards(db_path, {"include_reference": True})["cards"][0]
    assert original["source_ref"] == card.source_ref
    with sqlite3.connect(db_path) as database:
        database.execute(
            "UPDATE cards SET source_ref = ? WHERE id = ?", ("mutated-source-ref", card.card_id)
        )
    with pytest.raises(InputError, match="source identity"):
        _list_due_cards(db_path, {"include_reference": True})
    assert (
        load_card_sources(root / ".ahadiff", run.name)[card.card_id].source_ref == card.source_ref
    )


@pytest.mark.parametrize("original_multiple_choice", [False, True])
def test_mcp_projects_entire_immutable_question_when_database_answer_mode_and_choices_drift(
    tmp_path: Path, original_multiple_choice: bool
) -> None:
    root = tmp_path.resolve()
    _, card, _ = _new_card_run(root, exercise=False, multiple_choice=original_multiple_choice)
    db_path = root / ".ahadiff" / "review.sqlite"
    _make_card_due(db_path, card.card_id)
    alternate_choices = [
        {"label": "A", "text": "Mutated distractor A.", "is_correct": False},
        {"label": "B", "text": "Mutated reference.", "is_correct": True},
        {"label": "C", "text": "Mutated distractor C.", "is_correct": False},
        {"label": "D", "text": "Mutated distractor D.", "is_correct": False},
    ]
    with sqlite3.connect(db_path) as database:
        database.execute(
            "UPDATE cards SET question = ?, answer = ?, answer_mode = ?, choices_json = ? "
            "WHERE id = ?",
            (
                "Mutated question?",
                "Mutated reference.",
                "open" if original_multiple_choice else "multiple_choice",
                None if original_multiple_choice else json.dumps(alternate_choices),
                card.card_id,
            ),
        )
    reference = _list_due_cards(db_path, {"include_reference": True})["cards"][0]
    assert reference["source_ref"] == card.source_ref
    assert reference["question"] == card.question
    assert reference["answer"] == card.answer
    assert reference["answer_mode"] == card.answer_mode
    assert reference["choices"] == (
        [choice.model_dump(mode="json") for choice in card.choices] if card.choices else None
    )
    assert "Mutated" not in json.dumps(reference)


def test_export_rejects_second_pass_redaction_instead_of_exporting_stale_source_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve()
    synthetic_identifier = "Aa0Bb1Cc2Dd3Ee4Ff5Gg6Hh7Ii8Jj9KkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz"
    policy = AllowlistPolicy(allow_exact=(synthetic_identifier,))
    default_scan = redaction_pipeline(synthetic_identifier)
    permitted_scan = redaction_pipeline(synthetic_identifier, policy=policy)
    assert default_scan.redacted_text != synthetic_identifier
    assert permitted_scan.redacted_text == synthetic_identifier
    assert any(finding.allowlisted for finding in permitted_scan.findings)

    def permit_synthetic_example(_workspace_root: Path) -> AllowlistPolicy:
        return policy

    with monkeypatch.context() as capture_policy:
        # Use the real redactor with a real soft-detection allowlist during
        # capture only. The exporter later applies its default stricter policy.
        capture_policy.setattr(capture_module, "_resolve_policy", permit_synthetic_example)
        run, _, anchor = _consumer_document_run(
            root,
            document_content=(
                "# Queue\n\nUse retry_later() after failure. Synthetic example identifier: "
                + synthetic_identifier
                + "\n"
            ),
        )
    document = (run / "document.md").read_text(encoding="utf-8")
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    assert synthetic_identifier in document and synthetic_identifier in anchor.quote
    assert anchor in load_evidence_anchors(run)
    assert anchor.content_hash == hashlib.sha256(anchor.quote.encode("utf-8")).hexdigest()
    assert (
        metadata["source_detail"]["document"]["content_hash"]
        == hashlib.sha256(document.encode("utf-8")).hexdigest()
    )
    require_finalized_source(run, metadata)
    output = root / "rejected-filter-preview"
    with pytest.raises(InputError, match="export filtering would change source evidence"):
        export_preview(run.name, output, root / ".ahadiff")
    assert not output.exists()


def _mock_regeneration_boundary(
    monkeypatch: pytest.MonkeyPatch,
    expected_run: Path,
    *,
    fail_generation: bool = False,
) -> list[bool | None]:
    calls: list[bool | None] = []
    provider = ProviderConfig(
        provider_class="ollama",
        model_name="synthetic-regeneration",
        base_url="http://127.0.0.1:9",
        api_key_env="UNUSED_SYNTHETIC_KEY",
    )

    def resolve_provider(**_kwargs: object) -> tuple[ProviderConfig, None, Literal["local"], bool]:
        return provider, None, "local", True

    def generate(
        *,
        run_id: str,
        run_path: Path,
        overwrite: bool,
        active_practice: bool | None = None,
        **_kwargs: object,
    ) -> tuple[QuizArtifactPaths, tuple[QuizQuestion, ...]]:
        assert run_path == expected_run and run_id == expected_run.name
        assert overwrite is True
        calls.append(active_practice)
        assert active_practice is not None
        anchors = load_evidence_anchors(run_path)
        claims = [
            json.loads(line)
            for line in (run_path / "claims.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        primary = next(claim for claim in claims if claim["claim_id"] == "synthetic-claim")
        referenced_ids = {entry["anchor_id"] for entry in primary["source_anchors"]}
        selected = [anchor for anchor in anchors if anchor.anchor_id in referenced_ids]
        assert selected
        kinds: tuple[Literal["prediction", "completion", "error_reason"], ...] = (
            "prediction",
            "completion",
            "error_reason",
        )
        mixed_kinds: tuple[Literal["guided", "recall", "transfer"], ...] = (
            "guided",
            "recall",
            "transfer",
        )
        prompts = (
            "Predict the missing call for another transient failure:\nif retryable:\n    ____",
            "Complete a similar queued retry example:\nnext_action = ____",
            "Explain why discarding a transient failure loses the queued work.",
        )
        questions = tuple(
            QuizQuestion(
                question_id=(
                    "quiz_exercise_regenerated_" if active_practice else "quiz_regenerated_"
                )
                + f"{index}_{run_id[-12:]}",
                question=prompts[index],
                expected_answer="Use retry_later() to preserve ordering.",
                quiz_kind="transfer" if active_practice else mixed_kinds[index],
                exercise_kind=kind if active_practice else None,
                answer_mode="open",
                source_claims=[primary["claim_id"]],
                concepts=["retry ordering"],
                source_anchors=selected,
            )
            for index, kind in enumerate(kinds)
        )
        quiz_dir = run_path / "quiz"
        quiz_path = quiz_dir / "quiz.jsonl"
        gate_path = quiz_dir / "distractor_gate.json"
        misconception_path = quiz_dir / "misconception_cards.jsonl"
        write_quiz_questions_jsonl(quiz_path, questions, overwrite=True)
        write_distractor_gate_report(
            gate_path, build_distractor_gate_report(run_id=run_id, questions=questions)
        )
        misconception_path.write_text("", encoding="utf-8")
        if fail_generation:
            raise InputError("synthetic regeneration failed after writing quiz and gate")
        return (
            QuizArtifactPaths(
                quiz_dir=quiz_dir,
                quiz_path=quiz_path,
                misconception_path=misconception_path,
                distractor_gate_path=gate_path,
            ),
            questions,
        )

    monkeypatch.setattr(cli_module, "_resolve_runtime_provider", resolve_provider)
    monkeypatch.setattr(cli_module, "generate_quiz_from_run", generate)
    return calls


def _logical_review_snapshot(db_path: Path) -> dict[str, list[tuple[Any, ...]]]:
    with sqlite3.connect(db_path) as database:
        return {
            "result_events": database.execute(
                "SELECT * FROM result_events ORDER BY event_id"
            ).fetchall(),
            "review_logs": database.execute("SELECT * FROM review_logs ORDER BY rowid").fetchall(),
            "learning_signals": database.execute(
                "SELECT * FROM learning_signals ORDER BY event_id"
            ).fetchall(),
            "cards": database.execute("SELECT * FROM cards ORDER BY id").fetchall(),
        }


def _seed_prior_judge_artifacts(run: Path, db_path: Path) -> None:
    """Both legacy advisory artifacts must follow the original quiz on rollback."""
    report = evaluate_run(run)
    quiz_hash = hashlib.sha256((run / "quiz" / "quiz.jsonl").read_bytes()).hexdigest()
    write_llm_judge_report(
        run / "judge.json",
        LlmJudgeReport(
            run_id=run.name,
            source_ref=report.source_ref,
            source_kind=report.source_kind,
            model_id="synthetic-prior-judge",
            provider_class="openai",
            prompt_fingerprint="a" * 12,
            eval_bundle_version=report.eval_bundle_version,
            overall=report.overall,
            dimensions=report.dimensions,
            input_tokens=1,
            output_tokens=1,
            finish_reason="stop",
            request_id="synthetic-prior-judge",
            notes=("original_quiz_sha256=" + quiz_hash,),
        ),
    )
    (run / "judge_failure.json").write_text(
        json.dumps(
            {
                "schema": "ahadiff.judge_failure.v1",
                "provider_class": "openai",
                "model_name": "synthetic-prior-judge",
                "error_type": "InputError",
                "message": "Prior synthetic judge format failure.",
                "created_at": "2026-09-08T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    event = next(event for event in load_result_events_from_db(db_path) if event.run_id == run.name)
    write_finalized_result(run_path=run, event=event, score_path=run / "score.json")


def _assert_source_manifest_descriptors_match(run: Path) -> None:
    manifest = json.loads((run / "artifact_set.json").read_text(encoding="utf-8"))
    paths = [entry["path"] for entry in manifest["artifacts"]]
    assert len(paths) == len(set(paths))
    assert "metadata.json" in paths
    for descriptor in manifest["artifacts"]:
        content = (run / descriptor["path"]).read_bytes()
        assert descriptor["bytes"] == len(content), descriptor["path"]
        assert descriptor["sha256"] == hashlib.sha256(content).hexdigest(), descriptor["path"]


@pytest.mark.parametrize(
    "flag,expected_active",
    [("--active-practice", True), ("--mixed-practice", False)],
)
def test_cli_regenerate_quiz_seals_practice_mode_and_preserves_old_review_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str, expected_active: bool
) -> None:
    root = tmp_path.resolve()
    run, old_card, _ = _consumer_document_run(root)
    db_path = root / ".ahadiff" / "review.sqlite"
    _seed_prior_judge_artifacts(run, db_path)
    _assert_source_manifest_descriptors_match(run)
    assert (
        record_card_review_once(
            db_path,
            card_id=old_card.card_id,
            answer="good",
            idempotency_key="synthetic-before-regeneration",
            desired_retention=0.9,
        )
        is not None
    )
    before = _logical_review_snapshot(db_path)
    original_event = load_result_events_from_db(db_path)[0]
    calls = _mock_regeneration_boundary(monkeypatch, run)

    result = CliRunner().invoke(
        app(),
        ["regenerate", run.name, "--only", "quiz", flag, "--repo-root", str(root)],
    )

    assert result.exit_code == 0, result.output
    assert calls == [expected_active]
    assert "Regenerated quiz" in result.output
    assert "synchronization is pending" not in result.output
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["active_practice"] is expected_active
    questions = [
        QuizQuestion.model_validate_json(line)
        for line in (run / "quiz" / "quiz.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(questions) == 3
    if expected_active:
        assert {question.exercise_kind for question in questions} == {
            "prediction",
            "completion",
            "error_reason",
        }
    else:
        assert all(question.exercise_kind is None for question in questions)
        assert {question.quiz_kind for question in questions} == {"guided", "recall", "transfer"}
    assert all(question.review_card_id for question in questions)
    new_card_ids = {question.review_card_id for question in questions}
    assert old_card.card_id not in new_card_ids
    gate = json.loads((run / "quiz" / "distractor_gate.json").read_text(encoding="utf-8"))
    assert gate["questions_checked"] == 3
    events = load_result_events_from_db(db_path)
    assert len(events) == 2
    assert (
        next(event for event in events if event.event_id == original_event.event_id)
        == original_event
    )
    verification = next(event for event in events if event.event_type == "verify")
    assert json.loads(verification.note_json or "{}")["regenerated_artifact"] == "quiz"
    assert (
        json.loads(verification.note_json or "{}")["judge_status"]
        == "not_rerun_after_quiz_regeneration"
    )
    assert not (run / "judge.json").exists()
    assert not (run / "judge_failure.json").exists()
    _assert_source_manifest_descriptors_match(run)
    marker = json.loads((run / "finalized.json").read_text(encoding="utf-8"))
    assert marker["event_id"] == verification.event_id
    assert (marker["artifact_count"], marker["checksum"]) == finalized_artifact_digest(run)
    assert (
        json.loads((run / "score.json").read_text(encoding="utf-8"))
        == evaluate_run(run).to_payload()
    )
    require_finalized_source(run, metadata)
    assert set(load_card_sources(root / ".ahadiff", run.name)) == new_card_ids
    assert (
        _ask_lesson(
            root / ".ahadiff", {"run_id": run.name, "question": "retry_later preserve order"}
        )["run_meta"]["source_kind"]
        == "document"
    )
    with sqlite3.connect(db_path) as database:
        assert database.execute(
            "SELECT card_state, stale_reason, reps, last_rating FROM cards WHERE id = ?",
            (old_card.card_id,),
        ).fetchone() == ("stale", "staleness_unknown", 1, 3)
        assert {
            row[0]
            for row in database.execute(
                "SELECT id FROM cards WHERE run_id = ? AND card_state = 'active'", (run.name,)
            ).fetchall()
        } == new_card_ids
    after = _logical_review_snapshot(db_path)
    assert after["review_logs"] == before["review_logs"]
    assert after["learning_signals"] == before["learning_signals"]


@pytest.mark.parametrize(
    "failure_stage", ["generation", "publication", "interrupt_write", "interrupt_replace"]
)
def test_cli_regenerate_failure_restores_all_run_bytes_and_preserves_database_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    root = tmp_path.resolve()
    run, old_card, _ = _consumer_document_run(root)
    db_path = root / ".ahadiff" / "review.sqlite"
    _seed_prior_judge_artifacts(run, db_path)
    _assert_source_manifest_descriptors_match(run)
    assert (
        record_card_review_once(
            db_path,
            card_id=old_card.card_id,
            answer="good",
            idempotency_key="synthetic-before-failed-regeneration",
            desired_retention=0.9,
        )
        is not None
    )
    before_files = {
        str(path.relative_to(run)): path.read_bytes() for path in run.rglob("*") if path.is_file()
    }
    before_database = _logical_review_snapshot(db_path)
    history_path = root / ".ahadiff" / "results.tsv"
    history_before = history_path.read_bytes()
    calls = _mock_regeneration_boundary(
        monkeypatch, run, fail_generation=failure_stage == "generation"
    )
    publication_calls: list[bool] = []
    interruption_points: list[str] = []
    score_moved = False
    if failure_stage == "publication":

        def reject_publication(**_kwargs: object) -> None:
            publication_calls.append(True)
            raise InputError("synthetic score publication rejected")

        monkeypatch.setattr(cli_module, "publish_result_artifacts", reject_publication)
    elif failure_stage.startswith("interrupt_"):
        original_write = Path.write_text
        original_replace = Path.replace

        def interrupted_write(
            self: Path,
            data: str,
            encoding: str | None = None,
            errors: str | None = None,
            newline: str | None = None,
        ) -> int:
            if (
                failure_stage == "interrupt_write"
                and self.name.endswith(".finalized.tmp")
                and not interruption_points
            ):
                assert score_moved and (run / "score.json").is_file()
                interruption_points.append("after_score_move_before_finalized_write")
                raise KeyboardInterrupt("synthetic publication interruption")
            return original_write(self, data, encoding=encoding, errors=errors, newline=newline)

        def interrupted_replace(self: Path, target: str | Path) -> Path:
            nonlocal score_moved
            moved = original_replace(self, target)
            if self.name.endswith(".score.tmp") and Path(target) == run / "score.json":
                score_moved = True
            if (
                failure_stage == "interrupt_replace"
                and self.name.endswith(".finalized.tmp")
                and Path(target) == run / "finalized.json"
                and not interruption_points
            ):
                assert score_moved
                interruption_points.append("after_score_and_finalized_move")
                raise KeyboardInterrupt("synthetic publication interruption")
            return moved

        monkeypatch.setattr(Path, "write_text", interrupted_write)
        monkeypatch.setattr(Path, "replace", interrupted_replace)

    result = CliRunner().invoke(
        app(),
        ["regenerate", run.name, "--only", "quiz", "--active-practice", "--repo-root", str(root)],
    )

    assert result.exit_code != 0
    assert calls == [True]
    assert publication_calls == ([True] if failure_stage == "publication" else [])
    if failure_stage.startswith("interrupt_"):
        assert score_moved is True
        assert len(interruption_points) == 1
    else:
        assert "synthetic" in result.output
    assert {
        str(path.relative_to(run)): path.read_bytes() for path in run.rglob("*") if path.is_file()
    } == before_files
    assert _logical_review_snapshot(db_path) == before_database
    assert history_path.read_bytes() == history_before
    assert (run / "judge.json").read_bytes() == before_files["judge.json"]
    assert (run / "judge_failure.json").read_bytes() == before_files["judge_failure.json"]
    _assert_source_manifest_descriptors_match(run)
    assert set(load_card_sources(root / ".ahadiff", run.name)) == {old_card.card_id}


def test_cli_regenerate_keeps_committed_quiz_on_late_interrupt_and_lazy_import_recovers_srs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path.resolve()
    run, old_card, _ = _consumer_document_run(root)
    db_path = root / ".ahadiff" / "review.sqlite"
    _seed_prior_judge_artifacts(run, db_path)
    assert (
        record_card_review_once(
            db_path,
            card_id=old_card.card_id,
            answer="good",
            idempotency_key="synthetic-before-late-interruption",
            desired_retention=0.9,
        )
        is not None
    )
    before_database = _logical_review_snapshot(db_path)
    quiz_before = (run / "quiz" / "quiz.jsonl").read_bytes()
    calls = _mock_regeneration_boundary(monkeypatch, run)
    original_persist = cli_module._persist_evaluated_run  # pyright: ignore[reportPrivateUsage]
    committed_files: dict[str, bytes] = {}
    committed_event_ids: list[str] = []

    def persist_then_interrupt(**kwargs: Any) -> None:
        outcome, _warnings = original_persist(**kwargs)
        marker = json.loads((run / "finalized.json").read_text(encoding="utf-8"))
        assert marker["event_id"] == outcome.event.event_id
        assert (marker["artifact_count"], marker["checksum"]) == finalized_artifact_digest(run)
        _assert_source_manifest_descriptors_match(run)
        assert not (run / "judge.json").exists() and not (run / "judge_failure.json").exists()
        committed_event_ids.append(outcome.event.event_id)
        committed_files.update(
            {
                str(path.relative_to(run)): path.read_bytes()
                for path in run.rglob("*")
                if path.is_file()
                and not any(part.startswith(".") for part in path.relative_to(run).parts)
            }
        )
        raise KeyboardInterrupt("synthetic interruption after regenerate publication")

    monkeypatch.setattr(cli_module, "_persist_evaluated_run", persist_then_interrupt)
    result = CliRunner().invoke(
        app(),
        ["regenerate", run.name, "--only", "quiz", "--active-practice", "--repo-root", str(root)],
    )
    assert result.exit_code != 0
    assert calls == [True] and len(committed_event_ids) == 1
    assert (run / "quiz" / "quiz.jsonl").read_bytes() != quiz_before
    assert {
        str(path.relative_to(run)): path.read_bytes() for path in run.rglob("*") if path.is_file()
    } == committed_files
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["active_practice"] is True
    _assert_source_manifest_descriptors_match(run)
    assert not (run / "judge.json").exists() and not (run / "judge_failure.json").exists()
    questions = [
        QuizQuestion.model_validate_json(line)
        for line in (run / "quiz" / "quiz.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    new_card_ids = {question.review_card_id for question in questions}
    assert len(new_card_ids) == 3 and old_card.card_id not in new_card_ids
    marker = json.loads((run / "finalized.json").read_text(encoding="utf-8"))
    committed_digest = finalized_artifact_digest(run)
    assert (marker["artifact_count"], marker["checksum"]) == committed_digest
    assert marker["event_id"] == committed_event_ids[0]
    events = load_result_events_from_db(db_path)
    assert len(events) == 2
    verification = next(event for event in events if event.event_id == committed_event_ids[0])
    assert (
        json.loads(verification.note_json or "{}")["judge_status"]
        == "not_rerun_after_quiz_regeneration"
    )
    pending = _logical_review_snapshot(db_path)
    assert pending["cards"] == before_database["cards"]
    assert pending["review_logs"] == before_database["review_logs"]
    assert pending["learning_signals"] == before_database["learning_signals"]
    # This is the same local recovery path used when the user next opens review.
    assert import_cards_from_runs(db_path, root / ".ahadiff", desired_retention=0.9) == 3
    with sqlite3.connect(db_path) as database:
        assert {
            row[0]
            for row in database.execute(
                "SELECT id FROM cards WHERE run_id=? AND card_state='active'", (run.name,)
            )
        } == new_card_ids
        assert database.execute(
            "SELECT card_state,reps,last_rating FROM cards WHERE id=?", (old_card.card_id,)
        ).fetchone() == ("stale", 1, 3)
    recovered = _logical_review_snapshot(db_path)
    assert recovered["review_logs"] == before_database["review_logs"]
    assert recovered["learning_signals"] == before_database["learning_signals"]
    assert recovered["result_events"] == pending["result_events"]
    assert finalized_artifact_digest(run) == committed_digest
    require_finalized_source(run, metadata)
