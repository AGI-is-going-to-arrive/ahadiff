from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from typer.testing import CliRunner

from ahadiff.cli import app
from ahadiff.contracts import ClaimRecord, ProviderConfig, SourceHunk, compute_eval_bundle_version
from ahadiff.contracts.eval_bundle import compute_runtime_eval_bundle_version
from ahadiff.core.config import SecurityConfig
from ahadiff.core.errors import InputError
from ahadiff.eval import evaluate_run, write_score_report
from ahadiff.eval.evaluator import evaluate_run_for_replay_calibration, run_llm_judge_for_run
from ahadiff.eval.spec_alignment import (
    merge_semantic_review_into_artifact,
    parse_semantic_alignment_output,
    read_spec_source,
    run_semantic_alignment_review_for_run,
    write_spec_alignment_artifact,
)
from ahadiff.git.line_map import build_line_map, serialize_line_map_payload
from ahadiff.llm.schemas import ProviderRequest, ProviderResponse

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import TypedDict

    class _DimensionPayload(TypedDict):
        score: float
        max_score: float
        reason: str


_RUNNER = CliRunner()
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_run_fixture(
    workspace_root: Path,
    *,
    run_id: str,
    claims: list[ClaimRecord],
    patch_text: str,
    learnability_score: float,
    with_lesson: bool,
    with_quiz: bool,
    quiz_entries: list[dict[str, object]] | None = None,
) -> Path:
    run_path = workspace_root / ".ahadiff" / "runs" / run_id
    run_path.mkdir(parents=True, exist_ok=True)
    metadata = {
        "run_id": run_id,
        "source_kind": "git_ref",
        "source_ref": "abc123",
        "capability_level": 3,
        "degraded_flags": {},
        "learnability": {"score": learnability_score},
        "source_detail": {},
        "privacy_mode": "strict_local",
    }
    (run_path / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text(patch_text, encoding="utf-8")
    line_map_payload = serialize_line_map_payload(build_line_map(patch_text))
    (run_path / "line_map.json").write_text(
        json.dumps(line_map_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_path / "claims.jsonl").write_text(
        "\n".join(json.dumps(claim.model_dump(mode="json"), ensure_ascii=False) for claim in claims)
        + "\n",
        encoding="utf-8",
    )
    if with_lesson:
        lesson_dir = run_path / "lesson"
        lesson_dir.mkdir()
        (lesson_dir / "lesson.full.md").write_text(
            "TL;DR\n\nWhat Changed\n\nWhy\n\nWalkthrough\n\nClaims\n\nSources\n",
            encoding="utf-8",
        )
        (lesson_dir / "lesson.hint.md").write_text("Hint view\n", encoding="utf-8")
        (lesson_dir / "lesson.compact.md").write_text("Compact card\n", encoding="utf-8")
    if with_quiz:
        quiz_dir = run_path / "quiz"
        quiz_dir.mkdir()
        entries = (
            quiz_entries
            if quiz_entries is not None
            else [
                {
                    "question": "What changed?",
                    "source_claims": [claims[0].claim_id],
                    "evidence": [{"file": "src/app.py", "line": 2}],
                    "concepts": ["retry"],
                },
                {
                    "question": "Why does it matter?",
                    "source_claims": [claims[0].claim_id],
                    "evidence": [{"file": "src/app.py", "line": 3}],
                    "concepts": ["control-flow"],
                },
                {
                    "question": "What edge case is covered?",
                    "source_claims": [claims[-1].claim_id],
                    "evidence": [{"file": "src/app.py", "line": 4}],
                    "concepts": ["exception"],
                },
            ]
        )
        (quiz_dir / "quiz.jsonl").write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in entries) + "\n",
            encoding="utf-8",
        )
    return run_path


def _write_spec_alignment_artifact(
    run_path: Path,
    *,
    score: float,
    summary: dict[str, int] | None = None,
) -> None:
    payload = {
        "artifact": "spec_alignment",
        "schema": "ahadiff.spec_alignment",
        "schema_version": 1,
        "applicability": "applicable",
        "status": "scored",
        "spec_source": {
            "path": "SPEC.md",
            "ref": "SPEC.md",
            "sha256": "0" * 64,
            "bytes": 128,
        },
        "spec_digest": "0" * 64,
        "requirements": [
            {
                "id": "REQ-001",
                "text": "Retry helper must attempt three times.",
                "classification": "implemented",
                "severity": "medium",
                "evidence_refs": [
                    {
                        "type": "claim",
                        "claim_id": "claim_retry_loop",
                        "file": "src/app.py",
                        "start": 1,
                        "end": 6,
                        "side": "new",
                    }
                ],
                "confidence": 0.9,
                "reason": "Verified claim overlaps the requirement.",
            }
        ],
        "summary": summary
        or {
            "implemented": 1,
            "partial": 0,
            "missing": 0,
            "unknown": 0,
        },
        "score": score,
        "max_score": 10.0,
        "confidence": 0.9,
        "known_limitations": ["Deterministic lexical matching only."],
    }
    (run_path / "spec_alignment.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _standard_quiz_patch_text() -> str:
    return """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,8 @@
-def retry_once():
-    return 1
+def retry_once():
+    for attempt in range(3):
+        try:
+            return attempt
+        except Exception:
+            continue
+    return 0
+# end
"""


def _many_hunk_patch_text(hunk_count: int) -> str:
    hunks: list[str] = []
    for index in range(hunk_count):
        line_number = index * 10 + 1
        hunks.append(
            f"""@@ -{line_number} +{line_number} @@
-old_{index}
+new_{index}
"""
        )
    return "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n" + "".join(
        hunks
    )


def _current_large_run_shape_patch_text() -> str:
    sections: list[str] = []
    global_hunk_index = 0
    for file_index in range(44):
        path = f"src/file_{file_index:02d}.py"
        sections.append(f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n")
        file_hunks = 4 if file_index < 32 else 3
        for local_hunk_index in range(file_hunks):
            old_count = 8
            new_count = 9 if global_hunk_index < 132 else 8
            start = local_hunk_index * 24 + 1
            sections.append(f"@@ -{start},{old_count} +{start},{new_count} @@\n")
            sections.extend(
                f"-old_{global_hunk_index}_{line_index}\n" for line_index in range(old_count)
            )
            sections.extend(
                f"+new_{global_hunk_index}_{line_index}\n" for line_index in range(new_count)
            )
            global_hunk_index += 1
    return "".join(sections)


def _rename_patch_text() -> str:
    return """\
diff --git a/src/old.py b/src/new.py
similarity index 90%
rename from src/old.py
rename to src/new.py
--- a/src/old.py
+++ b/src/new.py
@@ -1 +1 @@
-old_value = 1
+new_value = 2
"""


def _standard_quiz_claims(run_id: str) -> list[ClaimRecord]:
    return [
        ClaimRecord(
            claim_id="claim_retry_loop",
            run_id=run_id,
            text="The retry helper now iterates up to three attempts.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
        ),
        ClaimRecord(
            claim_id="claim_default_return",
            run_id=run_id,
            text="The helper now returns 0 after exhausting attempts.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=7, end=8, side="new")],
        ),
    ]


def _mostly_verified_claims_with_one_contradiction(run_id: str) -> list[ClaimRecord]:
    return [
        ClaimRecord(
            claim_id="claim_retry_loop",
            run_id=run_id,
            text="The retry helper now iterates up to three attempts.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
        ),
        ClaimRecord(
            claim_id="claim_success_return",
            run_id=run_id,
            text="The retry helper can return a successful attempt.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=2, end=4, side="new")],
        ),
        ClaimRecord(
            claim_id="claim_default_return",
            run_id=run_id,
            text="The helper now returns 0 after exhausting attempts.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=7, end=8, side="new")],
        ),
        ClaimRecord(
            claim_id="claim_removed_retry",
            run_id=run_id,
            text="The retry helper was removed.",
            status="contradicted",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=1, end=8, side="new")],
        ),
    ]


def _write_score_json(
    run_path: Path,
    *,
    eval_bundle_version: str,
    verdict: str,
    hard_gates: Mapping[str, Mapping[str, object]],
    run_id: str | None = None,
    source_ref: str = "abc123",
    source_kind: str = "git_ref",
) -> None:
    payload: dict[str, object] = {
        "run_id": run_id or run_path.name,
        "source_ref": source_ref,
        "source_kind": source_kind,
        "capability_level": 3,
        "degraded_flags": {},
        "overall": 90.0,
        "verdict": verdict,
        "weakest_dim": "safety_privacy",
        "eval_bundle_version": eval_bundle_version,
        "rubric_version": "legacy-rubric",
        "dimensions": {},
        "hard_gates": {name: dict(gate) for name, gate in hard_gates.items()},
        "notes": [],
    }
    (run_path / "score.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _choice_options(correct_text: str) -> list[dict[str, object]]:
    return [
        {"label": "A", "text": correct_text, "is_correct": True},
        {"label": "B", "text": "It removes the retry helper.", "is_correct": False},
        {"label": "C", "text": "It changes the module import path.", "is_correct": False},
        {"label": "D", "text": "It updates only comments.", "is_correct": False},
    ]


def _anchored_quiz_entries(
    claims: list[ClaimRecord],
    *,
    include_choices: bool,
    invalid_choices: bool = False,
) -> list[dict[str, object]]:
    rows = (
        (
            "What changed?",
            claims[0].claim_id,
            2,
            "retry",
            "The retry helper now iterates up to three attempts.",
        ),
        (
            "Why does it matter?",
            claims[0].claim_id,
            3,
            "control-flow",
            "The loop can return a successful attempt before falling back.",
        ),
        (
            "What edge case is covered?",
            claims[-1].claim_id,
            4,
            "exception",
            "The helper now returns 0 after exhausting attempts.",
        ),
    )
    entries: list[dict[str, object]] = []
    for question, claim_id, line, concept, expected_answer in rows:
        entry: dict[str, object] = {
            "question": question,
            "expected_answer": expected_answer,
            "source_claims": [claim_id],
            "evidence": [{"file": "src/app.py", "line": line}],
            "concepts": [concept],
        }
        if include_choices:
            choices = _choice_options(expected_answer)
            entry["choices"] = choices[:3] if invalid_choices else choices
        entries.append(entry)
    return entries


def test_evaluate_run_requires_lesson_and_quiz_to_reach_pass(tmp_path: Path) -> None:
    patch_text = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,6 @@
-def retry_once():
-    return 1
+def retry_once():
+    for attempt in range(3):
+        try:
+            return attempt
+        except Exception:
+            continue
"""
    claim = ClaimRecord(
        claim_id="claim_retry_loop",
        run_id="run_partial",
        text="The retry helper now iterates up to three attempts.",
        status="verified",
        confidence="high",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
    )
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run_partial",
        claims=[claim],
        patch_text=patch_text,
        learnability_score=0.8,
        with_lesson=False,
        with_quiz=False,
    )

    report = evaluate_run(run_path)
    dimensions = report.to_payload()["dimensions"]

    assert report.verdict == "CAUTION"
    assert report.eval_bundle_version == compute_eval_bundle_version(_REPO_ROOT)
    assert isinstance(dimensions, dict)
    dimensions_map = cast("dict[str, dict[str, object]]", dimensions)
    quiz_transfer = dimensions_map["quiz_transfer"]
    conciseness = dimensions_map["conciseness"]
    assert quiz_transfer["score"] == 0.0
    assert conciseness["score"] == 0.0


def test_evaluate_run_can_pass_when_stage3_artifacts_exist(tmp_path: Path) -> None:
    patch_text = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,8 @@
-def retry_once():
-    return 1
+def retry_once():
+    for attempt in range(3):
+        try:
+            return attempt
+        except Exception:
+            continue
+    return 0
+# end
"""
    claims = [
        ClaimRecord(
            claim_id="claim_retry_loop",
            run_id="run_pass",
            text="The retry helper now iterates up to three attempts.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
        ),
        ClaimRecord(
            claim_id="claim_default_return",
            run_id="run_pass",
            text="The helper now returns 0 after exhausting attempts.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=7, end=8, side="new")],
        ),
    ]
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run_pass",
        claims=claims,
        patch_text=patch_text,
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )

    report = evaluate_run(run_path)

    assert report.verdict == "PASS"
    assert report.overall >= 80.0
    assert report.hard_gates.passed is True


def test_evaluate_run_fails_contradicted_claims_end_to_end(tmp_path: Path) -> None:
    run_id = "run-current-contradicted"
    run_path = _write_run_fixture(
        tmp_path,
        run_id=run_id,
        claims=_mostly_verified_claims_with_one_contradiction(run_id),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )

    report = evaluate_run(run_path)

    assert report.verdict == "FAIL"
    assert report.hard_gates.failed_names() == ("contradicted_claims",)


def test_replay_calibration_preserves_legacy_hard_gates_explicitly(
    tmp_path: Path,
) -> None:
    run_id = "run-legacy-contradicted-pass"
    run_path = _write_run_fixture(
        tmp_path,
        run_id=run_id,
        claims=_mostly_verified_claims_with_one_contradiction(run_id),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    legacy_gates = {
        "accuracy": {"passed": True, "detail": "accuracy >= 14.00", "score": 20.0},
        "evidence": {"passed": True, "detail": "evidence >= 12.60", "score": 18.0},
        "contradicted_claims": {
            "passed": True,
            "detail": "1 contradicted claim(s) (max 2)",
        },
    }
    _write_score_json(
        run_path,
        eval_bundle_version="legacy-eval-bundle",
        verdict="PASS",
        hard_gates=legacy_gates,
    )

    current_report = evaluate_run(run_path)
    calibration_report = evaluate_run_for_replay_calibration(run_path)

    assert current_report.verdict == "FAIL"
    assert calibration_report.verdict == "PASS"
    assert calibration_report.hard_gates.as_payload() == legacy_gates
    assert any("legacy replay calibration" in note for note in calibration_report.notes)


def test_replay_calibration_does_not_override_current_bundle_score(
    tmp_path: Path,
) -> None:
    run_id = "run-current-score-contradicted"
    run_path = _write_run_fixture(
        tmp_path,
        run_id=run_id,
        claims=_mostly_verified_claims_with_one_contradiction(run_id),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    _write_score_json(
        run_path,
        eval_bundle_version=compute_runtime_eval_bundle_version(),
        verdict="PASS",
        hard_gates={
            "contradicted_claims": {
                "passed": True,
                "detail": "legacy data cannot override current bundle",
            }
        },
    )

    calibration_report = evaluate_run_for_replay_calibration(run_path)

    assert calibration_report.verdict == "FAIL"
    assert calibration_report.hard_gates.failed_names() == ("contradicted_claims",)


def test_replay_calibration_ignores_malformed_legacy_hard_gates(
    tmp_path: Path,
) -> None:
    run_id = "run-malformed-legacy-score"
    run_path = _write_run_fixture(
        tmp_path,
        run_id=run_id,
        claims=_mostly_verified_claims_with_one_contradiction(run_id),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    _write_score_json(
        run_path,
        eval_bundle_version="legacy-eval-bundle",
        verdict="PASS",
        hard_gates={
            "contradicted_claims": {
                "passed": "yes",
                "detail": "malformed legacy gate must not override current scoring",
            }
        },
    )

    calibration_report = evaluate_run_for_replay_calibration(run_path)

    assert calibration_report.verdict == "FAIL"
    assert calibration_report.hard_gates.failed_names() == ("contradicted_claims",)
    assert any("ignored persisted score" in note for note in calibration_report.notes)


def test_replay_calibration_ignores_legacy_score_for_mismatched_run_identity(
    tmp_path: Path,
) -> None:
    run_id = "run-mismatched-legacy-score"
    run_path = _write_run_fixture(
        tmp_path,
        run_id=run_id,
        claims=_mostly_verified_claims_with_one_contradiction(run_id),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    _write_score_json(
        run_path,
        eval_bundle_version="legacy-eval-bundle",
        verdict="PASS",
        hard_gates={
            "contradicted_claims": {
                "passed": True,
                "detail": "mismatched legacy score must not override current scoring",
            }
        },
        run_id="run-from-a-different-directory",
    )

    calibration_report = evaluate_run_for_replay_calibration(run_path)

    assert calibration_report.verdict == "FAIL"
    assert calibration_report.hard_gates.failed_names() == ("contradicted_claims",)
    assert any("identity mismatch" in note for note in calibration_report.notes)


def test_evaluate_run_exposes_adaptive_diff_coverage_gate_basis(tmp_path: Path) -> None:
    patch_text = _many_hunk_patch_text(21)
    claim = ClaimRecord(
        claim_id="claim_first_hunk",
        run_id="run_adaptive_gate",
        text="The first hunk changes an app value.",
        status="verified",
        confidence="high",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=1, side="new")],
    )
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run_adaptive_gate",
        claims=[claim],
        patch_text=patch_text,
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )

    payload = evaluate_run(run_path).to_payload()
    hard_gates = cast("dict[str, dict[str, object]]", payload["hard_gates"])
    dimensions = cast("dict[str, dict[str, object]]", payload["dimensions"])
    evidence_coverage = hard_gates["evidence_coverage"]

    assert evidence_coverage["threshold"] == 7.28
    assert "adaptive_ratio=0.52" in str(evidence_coverage["detail"])
    assert "regime=medium" in str(evidence_coverage["detail"])
    assert "visible_files=1" in str(evidence_coverage["detail"])
    assert "visible_hunks=21" in str(evidence_coverage["detail"])
    assert "visible_changed_lines=42" in str(evidence_coverage["detail"])
    assert isinstance(evidence_coverage["threshold"], float)
    assert "adaptive_ratio" not in str(dimensions["diff_coverage"]["reason"])


def test_evaluate_run_uses_very_large_accuracy_evidence_policy_for_current_run_shape(
    tmp_path: Path,
) -> None:
    run_id = "run_current_large_shape"
    patch_text = _current_large_run_shape_patch_text()
    claim = ClaimRecord(
        claim_id="claim_first_file",
        run_id=run_id,
        text="The first generated file changes several values.",
        status="verified",
        confidence="high",
        source_hunks=[SourceHunk(file="src/file_00.py", start=1, end=8, side="new")],
    )
    run_path = _write_run_fixture(
        tmp_path,
        run_id=run_id,
        claims=[claim],
        patch_text=patch_text,
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=False,
    )

    payload = evaluate_run(run_path).to_payload()
    hard_gates = cast("dict[str, dict[str, object]]", payload["hard_gates"])
    accuracy_policy = hard_gates["accuracy"]["policy"]
    evidence_policy = hard_gates["evidence"]["policy"]

    assert accuracy_policy == {
        "kind": "adaptive_threshold",
        "ratio": 0.85,
        "regime": "very_large",
        "basis": {
            "visible_files": 44,
            "visible_hunks": 164,
            "visible_changed_lines": 2756,
        },
    }
    assert evidence_policy == accuracy_policy
    assert hard_gates["accuracy"]["threshold"] == 11.90
    assert hard_gates["evidence"]["threshold"] == 10.20


def test_diff_coverage_matches_renamed_old_side_source_hunks(tmp_path: Path) -> None:
    run_id = "run_renamed_old_side"
    claim = ClaimRecord(
        claim_id="claim_old_rename_side",
        run_id=run_id,
        text="The old file value is replaced during the rename.",
        status="weak",
        confidence="medium",
        source_hunks=[SourceHunk(file="src/old.py", start=1, end=1, side="old")],
    )
    run_path = _write_run_fixture(
        tmp_path,
        run_id=run_id,
        claims=[claim],
        patch_text=_rename_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
        quiz_entries=[
            {
                "question": "What changed?",
                "source_claims": [claim.claim_id],
                "evidence": [{"file": "src/old.py", "line": 1}],
                "concepts": ["rename"],
            }
        ],
    )

    report = evaluate_run(run_path)
    dimensions = cast("dict[str, dict[str, object]]", report.to_payload()["dimensions"])
    hard_gates = cast("dict[str, dict[str, object]]", report.to_payload()["hard_gates"])

    assert dimensions["diff_coverage"]["score"] == 14.0
    assert hard_gates["evidence_coverage"]["passed"] is True


def test_spec_alignment_without_spec_is_not_applicable_score_zero(tmp_path: Path) -> None:
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run-no-spec",
        claims=_standard_quiz_claims("run-no-spec"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )

    assert not (run_path / "spec_alignment.json").exists()

    report = evaluate_run(run_path)
    dimensions = cast("dict[str, _DimensionPayload]", report.to_payload()["dimensions"])
    spec_dimension = dimensions["spec_alignment"]
    applicable_dimensions = [
        dimension for dimension in dimensions.values() if float(dimension["max_score"]) > 0.0
    ]
    applicable_score = sum(float(dimension["score"]) for dimension in applicable_dimensions)
    applicable_max = sum(float(dimension["max_score"]) for dimension in applicable_dimensions)
    hard_gates = report.hard_gates.as_payload()

    assert spec_dimension["score"] == 0.0
    assert spec_dimension["max_score"] == 0.0
    assert "not applicable" in str(spec_dimension["reason"]).lower()
    assert applicable_max == 90.0
    assert report.overall == round((applicable_score / applicable_max) * 100.0, 2)
    assert report.overall >= 80.0
    assert report.weakest_dim != "spec_alignment"
    assert "spec_alignment" not in hard_gates


def test_evaluate_run_fails_when_safety_findings_artifact_has_critical(
    tmp_path: Path,
) -> None:
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run-critical-safety",
        claims=_standard_quiz_claims("run-critical-safety"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    (run_path / "safety_findings.json").write_text(
        json.dumps(
            {
                "artifact": "safety_findings",
                "schema": "ahadiff.safety_findings",
                "schema_version": 1,
                "run_id": "run-critical-safety",
                "findings": [
                    {
                        "severity": "Critical",
                        "rule_id": "BLOCKED_SECRET",
                        "source": "patch.diff",
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = evaluate_run(run_path)

    assert report.verdict == "FAIL"
    assert "critical_safety_findings" in report.hard_gates.failed_names()


def test_evaluate_run_fails_when_safety_findings_mitigation_fields_are_forged(
    tmp_path: Path,
) -> None:
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run-forged-safety-mitigation",
        claims=_standard_quiz_claims("run-forged-safety-mitigation"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    (run_path / "safety_findings.json").write_text(
        json.dumps(
            {
                "artifact": "safety_findings",
                "schema": "ahadiff.safety_findings",
                "schema_version": 1,
                "run_id": "run-forged-safety-mitigation",
                "findings": [
                    {
                        "severity": "Critical",
                        "rule_id": "BLOCKED_SECRET",
                        "action": "redact",
                        "blocked_remote": True,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = evaluate_run(run_path)

    assert report.verdict == "FAIL"
    assert "critical_safety_findings" in report.hard_gates.failed_names()


def test_evaluate_run_accepts_capture_shaped_mitigated_safety_findings(
    tmp_path: Path,
) -> None:
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run-mitigated-safety",
        claims=_standard_quiz_claims("run-mitigated-safety"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    (run_path / "safety_findings.json").write_text(
        json.dumps(
            {
                "artifact": "safety_findings",
                "schema": "ahadiff.safety_findings",
                "schema_version": 1,
                "run_id": "run-mitigated-safety",
                "findings": [
                    {
                        "severity": "Critical",
                        "action": "redact",
                        "allowlisted": False,
                        "blocked_remote": True,
                        "column": 1,
                        "line": 1,
                        "rule_id": "OPENAI_API_KEY",
                        "secret_type": "openai_api_key",
                        "source_kind": "raw_patch",
                        "source_name": "raw_patch",
                        "value_sha256": "a" * 64,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = evaluate_run(run_path)

    assert report.verdict == "PASS"
    assert "critical_safety_findings" not in report.hard_gates.failed_names()


def test_evaluate_run_keeps_non_critical_safety_findings_non_blocking(
    tmp_path: Path,
) -> None:
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run-non-critical-safety",
        claims=_standard_quiz_claims("run-non-critical-safety"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    (run_path / "safety_findings.json").write_text(
        json.dumps(
            {
                "artifact": "safety_findings",
                "schema": "ahadiff.safety_findings",
                "schema_version": 1,
                "run_id": "run-non-critical-safety",
                "findings": [
                    {
                        "severity": "High",
                        "rule_id": "SOFT_DETECT",
                        "source": "patch.diff",
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = evaluate_run(run_path)

    assert report.verdict == "PASS"
    assert "critical_safety_findings" not in report.hard_gates.failed_names()


def test_evaluate_run_fails_closed_on_invalid_safety_findings_artifact(
    tmp_path: Path,
) -> None:
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run-invalid-safety",
        claims=_standard_quiz_claims("run-invalid-safety"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    (run_path / "safety_findings.json").write_text("{not json\n", encoding="utf-8")

    report = evaluate_run(run_path)

    assert report.verdict == "FAIL"
    assert "critical_safety_findings" in report.hard_gates.failed_names()


def test_spec_alignment_uses_artifact_score_and_summary(tmp_path: Path) -> None:
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run-spec",
        claims=_standard_quiz_claims("run-spec"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    _write_spec_alignment_artifact(
        run_path,
        score=7.5,
        summary={"implemented": 1, "partial": 1, "missing": 1, "unknown": 0},
    )

    report = evaluate_run(run_path)
    dimensions = cast("dict[str, dict[str, object]]", report.to_payload()["dimensions"])
    spec_dimension = dimensions["spec_alignment"]

    assert spec_dimension["score"] == 7.5
    assert "implemented=1" in str(spec_dimension["reason"])
    assert "missing=1" in str(spec_dimension["reason"])


def test_spec_alignment_bad_artifact_degrades_to_zero(tmp_path: Path) -> None:
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run-bad-spec",
        claims=_standard_quiz_claims("run-bad-spec"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    (run_path / "spec_alignment.json").write_text("{not json\n", encoding="utf-8")

    report = evaluate_run(run_path)
    dimensions = cast("dict[str, dict[str, object]]", report.to_payload()["dimensions"])
    spec_dimension = dimensions["spec_alignment"]

    assert spec_dimension["score"] == 0.0
    assert "unreadable" in str(spec_dimension["reason"]).lower()


def test_spec_alignment_hardlink_artifact_degrades_to_zero(tmp_path: Path) -> None:
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run-hardlink-spec",
        claims=_standard_quiz_claims("run-hardlink-spec"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    external = tmp_path / "external-spec-alignment.json"
    _write_spec_alignment_artifact(run_path, score=9.0)
    external.write_text(
        (run_path / "spec_alignment.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (run_path / "spec_alignment.json").unlink()
    try:
        os.link(external, run_path / "spec_alignment.json")
    except OSError:
        pytest.skip("hardlinks are not available on this filesystem")

    report = evaluate_run(run_path)
    dimensions = cast("dict[str, dict[str, object]]", report.to_payload()["dimensions"])
    spec_dimension = dimensions["spec_alignment"]

    assert spec_dimension["score"] == 0.0
    assert "unreadable" in str(spec_dimension["reason"]).lower()


def test_against_spec_rejects_invalid_utf8(tmp_path: Path) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    spec_path = workspace_root / "SPEC.md"
    spec_path.write_bytes(b"\xff\xfe invalid")

    with pytest.raises(InputError, match="valid UTF-8"):
        read_spec_source(workspace_root=workspace_root, spec_path=Path("SPEC.md"))


def test_spec_alignment_uses_patch_anchors_without_claims(tmp_path: Path) -> None:
    workspace_root = tmp_path / "repo"
    run_path = workspace_root / ".ahadiff" / "runs" / "run-spec-patch"
    run_path.mkdir(parents=True)
    spec_text = "- The CLI must expose `--against-spec` and write `spec_alignment.json`.\n"
    (workspace_root / "SPEC.md").write_text(spec_text, encoding="utf-8")
    (run_path / "patch.diff").write_text(
        """\
diff --git a/src/ahadiff/cli.py b/src/ahadiff/cli.py
--- a/src/ahadiff/cli.py
+++ b/src/ahadiff/cli.py
@@ -1,2 +1,4 @@
+option = "--against-spec"
+artifact = "spec_alignment.json"
""",
        encoding="utf-8",
    )

    payload = write_spec_alignment_artifact(
        run_path=run_path,
        workspace_root=workspace_root,
        spec_path=Path("SPEC.md"),
    )

    requirement = payload["requirements"][0]
    assert requirement["classification"] == "implemented"
    assert requirement["evidence_refs"] == [
        {
            "type": "patch",
            "file": "src/ahadiff/cli.py",
            "lines": [1, 2],
            "anchors": ["--against-spec", "spec_alignment.json"],
            "side": "new",
        }
    ]
    assert "code anchors" in requirement["reason"]
    assert payload["matcher"]["mode"] == "deterministic_structured"
    assert payload["matcher"]["claim_count"] == 0
    assert payload["spec_source"]["sha256"] == hashlib.sha256(spec_text.encode("utf-8")).hexdigest()


def test_spec_alignment_marks_forbidden_anchor_added_as_missing(tmp_path: Path) -> None:
    workspace_root = tmp_path / "repo"
    run_path = workspace_root / ".ahadiff" / "runs" / "run-spec-forbidden"
    run_path.mkdir(parents=True)
    (workspace_root / "SPEC.md").write_text(
        "- Must not import `DOMPurify`.\n",
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text(
        """\
diff --git a/viewer/src/App.tsx b/viewer/src/App.tsx
--- a/viewer/src/App.tsx
+++ b/viewer/src/App.tsx
@@ -1 +1,2 @@
+import DOMPurify from 'dompurify';
 export function App() {}
""",
        encoding="utf-8",
    )
    (run_path / "claims.jsonl").write_text(
        json.dumps(
            {
                "claim_id": "claim_dom",
                "text": "The app imports DOMPurify.",
                "status": "verified",
                "source_hunks": [
                    {"file": "viewer/src/App.tsx", "start": 1, "end": 1, "side": "new"}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = write_spec_alignment_artifact(
        run_path=run_path,
        workspace_root=workspace_root,
        spec_path=Path("SPEC.md"),
    )

    requirement = payload["requirements"][0]
    assert requirement["classification"] == "missing"
    assert requirement["confidence"] >= 0.8
    assert "Forbidden requirement anchor was added" in requirement["reason"]
    assert requirement["evidence_refs"][0]["type"] == "patch_forbidden"
    assert requirement["evidence_refs"][0]["anchors"] == ["DOMPurify"]
    assert payload["summary"] == {"implemented": 0, "partial": 0, "missing": 1, "unknown": 0}
    assert payload["score"] == 0.0


def test_semantic_review_without_bound_evidence_stays_unknown() -> None:
    deterministic: dict[str, Any] = {
        "artifact": "spec_alignment",
        "schema": "ahadiff.spec_alignment",
        "score": 0.0,
        "summary": {"implemented": 0, "partial": 0, "missing": 1, "unknown": 0},
        "requirements": [
            {
                "id": "REQ-001",
                "text": "The CLI must expose --spec-semantic-review.",
                "classification": "missing",
                "severity": "medium",
                "evidence_refs": [],
                "confidence": 0.55,
                "reason": "No matching claim or diff evidence was found.",
            }
        ],
    }

    review = parse_semantic_alignment_output(
        json.dumps(
            {
                "requirements": [
                    {
                        "id": "REQ-001",
                        "classification": "implemented",
                        "confidence": 0.95,
                        "rationale": "Looks implemented semantically.",
                        "evidence_refs": [],
                    }
                ]
            }
        ),
        deterministic_artifact=deterministic,
        provider=cast("Any", type("Provider", (), {"provider": "openai", "model": "gpt-5.5"})()),
        prompt_digest="abc123",
        input_digest="def456",
    )
    merged = merge_semantic_review_into_artifact(deterministic, review)

    requirement = merged["semantic_review"]["requirements"][0]
    assert requirement["classification"] == "unknown"
    assert requirement["confidence"] <= 0.35
    assert merged["score"] == 0.0
    assert merged["semantic_adjustment"]["delta"] == 0.0


def test_semantic_review_forbidden_violation_lowers_score_when_evidence_bound() -> None:
    evidence_ref = {
        "type": "patch_forbidden",
        "file": "viewer/src/App.tsx",
        "lines": [2],
        "anchors": ["DOMPurify"],
        "side": "new",
    }
    deterministic = {
        "artifact": "spec_alignment",
        "schema": "ahadiff.spec_alignment",
        "score": 10.0,
        "summary": {"implemented": 1, "partial": 0, "missing": 0, "unknown": 0},
        "requirements": [
            {
                "id": "REQ-001",
                "text": "Do not add `DOMPurify` unless HTML rendering exists.",
                "classification": "implemented",
                "severity": "high",
                "evidence_refs": [evidence_ref],
                "confidence": 0.9,
                "reason": "Fixture deterministic result.",
            }
        ],
    }

    review = parse_semantic_alignment_output(
        json.dumps(
            {
                "requirements": [
                    {
                        "id": "REQ-001",
                        "classification": "violated",
                        "confidence": 0.9,
                        "rationale": (
                            "The forbidden anchor is present in the listed patch evidence."
                        ),
                        "evidence_refs": [evidence_ref],
                    }
                ]
            }
        ),
        deterministic_artifact=deterministic,
        provider=cast("Any", type("Provider", (), {"provider": "openai", "model": "gpt-5.5"})()),
        prompt_digest="abc123",
        input_digest="def456",
    )
    merged = merge_semantic_review_into_artifact(deterministic, review)

    assert merged["semantic_review"]["requirements"][0]["classification"] == "violated"
    assert merged["score"] < 10.0
    assert merged["semantic_adjustment"]["delta"] < 0


def test_run_semantic_alignment_review_for_run_writes_optional_artifact_field(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    spec_path = workspace_root / "SPEC.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("- The retry helper must attempt three times.\n", encoding="utf-8")
    run_path = _write_run_fixture(
        workspace_root,
        run_id="run-semantic",
        claims=_standard_quiz_claims("run-semantic"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    deterministic = write_spec_alignment_artifact(
        run_path=run_path,
        workspace_root=workspace_root,
        spec_path=Path("SPEC.md"),
    )
    evidence_refs = deterministic["requirements"][0]["evidence_refs"]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "gpt-5.5"
        return httpx.Response(
            200,
            json={
                "id": "resp_semantic",
                "model": "gpt-5.5",
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "requirements": [
                            {
                                "id": "REQ-001",
                                "classification": "implemented",
                                "confidence": 0.88,
                                "rationale": "The evidence supports the retry requirement.",
                                "evidence_refs": evidence_refs,
                            }
                        ],
                        "limitations": ["Fixture limitation."],
                    }
                ),
                "usage": {"input_tokens": 33, "output_tokens": 44},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        merged = run_semantic_alignment_review_for_run(
            run_path=run_path,
            workspace_root=workspace_root,
            provider_config=ProviderConfig(
                provider_class="openai_responses",
                model_name="gpt-5.5",
                base_url="http://127.0.0.1:8318",
                api_key_env="AHADIFF_GPT55_KEY",
            ),
            api_key="test-key",
            security_config=SecurityConfig(),
            privacy_mode="strict_local",
            output_lang="en",
            request_timeout_seconds=30,
            max_concurrent=1,
            qps_limit=10,
            retry_attempts=0,
            client=client,
        )

    payload = json.loads((run_path / "spec_alignment.json").read_text(encoding="utf-8"))
    assert merged["semantic_review"]["model"] == "gpt-5.5"
    assert payload["semantic_review"]["aggregate"]["implemented"] == 1
    assert payload["semantic_review"]["degraded"] is False
    assert payload["deterministic_result"]["score"] == deterministic["score"]


def test_run_semantic_alignment_review_bad_json_degrades_without_changing_score(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    spec_path = workspace_root / "SPEC.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("- The retry helper must attempt three times.\n", encoding="utf-8")
    run_path = _write_run_fixture(
        workspace_root,
        run_id="run-semantic-bad-json",
        claims=_standard_quiz_claims("run-semantic-bad-json"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    deterministic = write_spec_alignment_artifact(
        run_path=run_path,
        workspace_root=workspace_root,
        spec_path=Path("SPEC.md"),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_semantic_bad",
                "model": "gpt-5.5",
                "status": "completed",
                "output_text": "{not-json",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        merged = run_semantic_alignment_review_for_run(
            run_path=run_path,
            workspace_root=workspace_root,
            provider_config=ProviderConfig(
                provider_class="openai_responses",
                model_name="gpt-5.5",
                base_url="http://127.0.0.1:8318",
                api_key_env="AHADIFF_GPT55_KEY",
            ),
            api_key="test-key",
            security_config=SecurityConfig(),
            privacy_mode="strict_local",
            output_lang="en",
            request_timeout_seconds=30,
            max_concurrent=1,
            qps_limit=10,
            retry_attempts=0,
            client=client,
        )

    assert merged["semantic_review"]["degraded"] is True
    assert merged["score"] == deterministic["score"]


def test_semantic_alignment_request_stays_json_object_without_schema_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    spec_path = workspace_root / "SPEC.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("- The retry helper must attempt three times.\n", encoding="utf-8")
    run_path = _write_run_fixture(
        workspace_root,
        run_id="run-semantic-json-object",
        claims=_standard_quiz_claims("run-semantic-json-object"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    deterministic = write_spec_alignment_artifact(
        run_path=run_path,
        workspace_root=workspace_root,
        spec_path=Path("SPEC.md"),
    )
    seen_requests: list[ProviderRequest] = []

    class FakeProvider:
        def __enter__(self) -> FakeProvider:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def generate(self, request: ProviderRequest) -> ProviderResponse:
            seen_requests.append(request)
            return ProviderResponse(
                content="{not-json",
                model_id="gpt-5.5",
                input_tokens=1,
                output_tokens=1,
            )

    def fake_make_provider(*_args: object, **_kwargs: object) -> FakeProvider:
        return FakeProvider()

    monkeypatch.setattr("ahadiff.llm.provider.make_provider", fake_make_provider)

    merged = run_semantic_alignment_review_for_run(
        run_path=run_path,
        workspace_root=workspace_root,
        provider_config=ProviderConfig(
            provider_class="openai_responses",
            model_name="gpt-5.5",
            base_url="http://127.0.0.1:8318",
            api_key_env="AHADIFF_GPT55_KEY",
        ),
        api_key="test-key",
        security_config=SecurityConfig(),
        privacy_mode="strict_local",
        output_lang="en",
        request_timeout_seconds=30,
        max_concurrent=1,
        qps_limit=10,
        retry_attempts=0,
    )

    assert merged["semantic_review"]["degraded"] is True
    assert merged["score"] == deterministic["score"]
    assert len(seen_requests) == 1
    assert seen_requests[0].response_format == "json"
    assert seen_requests[0].enforcement_mode == "json_object"
    assert seen_requests[0].output_schema_id is None
    assert seen_requests[0].output_schema is None


def test_run_llm_judge_for_run_writes_judge_artifact(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_run_fixture(
        workspace_root,
        run_id="run-judge",
        claims=_standard_quiz_claims("run-judge"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    deterministic_report = evaluate_run(run_path)
    dimensions = {
        dimension.name: {"score": round(dimension.max_score / 2, 2), "reason": "ok"}
        for dimension in deterministic_report.dimensions
        if dimension.name != "spec_alignment"
    }
    dimensions["spec_alignment"] = {"score": 10, "reason": "judge treated no-spec as aligned"}
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"x-request-id": "req-judge"},
            json={
                "id": "resp_judge",
                "model": "gpt-5.5",
                "status": "completed",
                "output_text": json.dumps({"dimensions": dimensions}),
                "usage": {"input_tokens": 11, "output_tokens": 22},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        report = run_llm_judge_for_run(
            run_path=run_path,
            workspace_root=workspace_root,
            provider_config=ProviderConfig(
                provider_class="openai_responses",
                model_name="gpt-5.5",
                base_url="http://127.0.0.1:8318",
                api_key_env="AHADIFF_GPT55_KEY",
            ),
            api_key="test-key",
            security_config=SecurityConfig(),
            privacy_mode="strict_local",
            output_lang="en",
            deterministic_report=deterministic_report,
            request_timeout_seconds=30,
            max_concurrent=1,
            qps_limit=10,
            retry_attempts=0,
            client=client,
        )

    assert captured["url"] == "http://127.0.0.1:8318/v1/responses"
    request_payload = cast("dict[str, object]", captured["payload"])
    assert request_payload["model"] == "gpt-5.5"
    assert request_payload["text"] == {"format": {"type": "json_object"}}
    assert report.model_id == "gpt-5.5"
    assert report.overall == 50.0
    payload = json.loads((run_path / "judge.json").read_text(encoding="utf-8"))
    assert payload["artifact"] == "llm_judge"
    assert payload["model_id"] == "gpt-5.5"
    assert payload["dimensions"]["spec_alignment"]["score"] == 0.0
    assert payload["dimensions"]["spec_alignment"]["max_score"] == 0.0
    assert (
        "judge reason: judge treated no-spec as aligned"
        in payload["dimensions"]["spec_alignment"]["reason"]
    )
    assert payload["usage"] == {"input_tokens": 11, "output_tokens": 22}


def test_high_llm_judge_scores_do_not_change_deterministic_score_json_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_id = "run-judge-advisory-only"
    run_path = _write_run_fixture(
        workspace_root,
        run_id=run_id,
        claims=_mostly_verified_claims_with_one_contradiction(run_id),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    deterministic_report = evaluate_run(run_path)
    assert deterministic_report.verdict == "FAIL"
    assert deterministic_report.hard_gates.failed_names() == ("contradicted_claims",)
    write_score_report(run_path / "score.json", deterministic_report)
    score_before = json.loads((run_path / "score.json").read_text(encoding="utf-8"))
    high_dimensions = {
        dimension.name: {
            "score": dimension.max_score if dimension.max_score > 0.0 else 10.0,
            "reason": "judge awarded a high score",
        }
        for dimension in deterministic_report.dimensions
    }
    seen_requests: list[ProviderRequest] = []

    class FakeProvider:
        def generate(self, request: ProviderRequest) -> ProviderResponse:
            seen_requests.append(request)
            return ProviderResponse(
                content=json.dumps({"dimensions": high_dimensions}),
                model_id="gpt-5.5",
                input_tokens=1,
                output_tokens=1,
            )

        def close(self) -> None:
            return None

    def fake_make_provider(*_args: object, **_kwargs: object) -> FakeProvider:
        return FakeProvider()

    monkeypatch.setattr("ahadiff.llm.provider.make_provider", fake_make_provider)

    judge_report = run_llm_judge_for_run(
        run_path=run_path,
        workspace_root=workspace_root,
        provider_config=ProviderConfig(
            provider_class="openai_responses",
            model_name="gpt-5.5",
            base_url="http://127.0.0.1:8318",
            api_key_env="AHADIFF_GPT55_KEY",
        ),
        api_key="test-key",
        security_config=SecurityConfig(),
        privacy_mode="strict_local",
        output_lang="en",
        deterministic_report=deterministic_report,
        request_timeout_seconds=30,
        max_concurrent=1,
        qps_limit=10,
        retry_attempts=0,
    )

    assert len(seen_requests) == 1
    assert judge_report.overall == 100.0
    judge_payload = json.loads((run_path / "judge.json").read_text(encoding="utf-8"))
    score_after = json.loads((run_path / "score.json").read_text(encoding="utf-8"))
    assert judge_payload["overall"] == 100.0
    assert judge_payload["dimensions"]["spec_alignment"]["score"] == 0.0
    assert judge_payload["dimensions"]["spec_alignment"]["max_score"] == 0.0
    assert score_after == score_before
    assert score_after["verdict"] == "FAIL"
    assert score_after["hard_gates"]["contradicted_claims"]["passed"] is False


def test_llm_judge_request_stays_json_object_without_schema_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    run_path = _write_run_fixture(
        workspace_root,
        run_id="run-judge-json-object",
        claims=_standard_quiz_claims("run-judge-json-object"),
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    deterministic_report = evaluate_run(run_path)
    seen_requests: list[ProviderRequest] = []
    dimensions = {
        dimension.name: {"score": round(dimension.max_score / 2, 2), "reason": "ok"}
        for dimension in deterministic_report.dimensions
        if dimension.max_score > 0
    }

    class FakeProvider:
        def generate(self, request: ProviderRequest) -> ProviderResponse:
            seen_requests.append(request)
            return ProviderResponse(
                content=json.dumps({"dimensions": dimensions}),
                model_id="gpt-5.5",
                input_tokens=1,
                output_tokens=1,
            )

        def close(self) -> None:
            return None

    def fake_make_provider(*_args: object, **_kwargs: object) -> FakeProvider:
        return FakeProvider()

    monkeypatch.setattr("ahadiff.llm.provider.make_provider", fake_make_provider)

    run_llm_judge_for_run(
        run_path=run_path,
        workspace_root=workspace_root,
        provider_config=ProviderConfig(
            provider_class="openai_responses",
            model_name="gpt-5.5",
            base_url="http://127.0.0.1:8318",
            api_key_env="AHADIFF_GPT55_KEY",
        ),
        api_key="test-key",
        security_config=SecurityConfig(),
        privacy_mode="strict_local",
        output_lang="en",
        deterministic_report=deterministic_report,
        request_timeout_seconds=30,
        max_concurrent=1,
        qps_limit=10,
        retry_attempts=0,
    )

    assert len(seen_requests) == 1
    assert seen_requests[0].response_format == "json"
    assert seen_requests[0].enforcement_mode == "json_object"
    assert seen_requests[0].output_schema_id is None
    assert seen_requests[0].output_schema is None


def test_evaluate_run_does_not_pass_with_unlinked_quiz_artifacts(
    tmp_path: Path,
) -> None:
    patch_text = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,8 @@
-def retry_once():
-    return 1
+def retry_once():
+    for attempt in range(3):
+        try:
+            return attempt
+        except Exception:
+            continue
+    return 0
+# end
"""
    claims = [
        ClaimRecord(
            claim_id="claim_retry_loop",
            run_id="run_fake_quiz",
            text="The retry helper now iterates up to three attempts.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=1, end=6, side="new")],
        ),
        ClaimRecord(
            claim_id="claim_default_return",
            run_id="run_fake_quiz",
            text="The helper now returns 0 after exhausting attempts.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=7, end=8, side="new")],
        ),
    ]
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run_fake_quiz",
        claims=claims,
        patch_text=patch_text,
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
    )
    (run_path / "quiz" / "quiz.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "question": f"Fake question {index}",
                    "source_claims": [f"missing-claim-{index}"],
                    "evidence": [{"file": "nope.py", "line": 999}],
                    "concepts": ["placeholder"],
                }
            )
            for index in range(1, 4)
        )
        + "\n",
        encoding="utf-8",
    )

    report = evaluate_run(run_path)
    dimensions = cast("dict[str, dict[str, object]]", report.to_payload()["dimensions"])

    assert dimensions["quiz_transfer"]["score"] == 3.0
    assert report.verdict == "CAUTION"


def test_quiz_transfer_open_quiz_keeps_choice_subscores_zero(tmp_path: Path) -> None:
    run_id = "run_open_quiz"
    claims = _standard_quiz_claims(run_id)
    run_path = _write_run_fixture(
        tmp_path,
        run_id=run_id,
        claims=claims,
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
        quiz_entries=_anchored_quiz_entries(claims, include_choices=False),
    )

    report = evaluate_run(run_path)
    dimensions = cast("dict[str, dict[str, object]]", report.to_payload()["dimensions"])
    quiz_transfer = dimensions["quiz_transfer"]

    assert report.rubric_version == "v0.2"
    assert quiz_transfer["score"] == 7.5
    assert "choice_shape=0.00" in str(quiz_transfer["reason"])
    assert "choice_answer=0.00" in str(quiz_transfer["reason"])


def test_quiz_transfer_valid_multiple_choice_scores_above_equal_open_quiz(
    tmp_path: Path,
) -> None:
    open_run_id = "run_open_quiz_baseline"
    open_claims = _standard_quiz_claims(open_run_id)
    open_run_path = _write_run_fixture(
        tmp_path,
        run_id=open_run_id,
        claims=open_claims,
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
        quiz_entries=_anchored_quiz_entries(open_claims, include_choices=False),
    )
    choice_run_id = "run_choice_quiz"
    choice_claims = _standard_quiz_claims(choice_run_id)
    choice_run_path = _write_run_fixture(
        tmp_path,
        run_id=choice_run_id,
        claims=choice_claims,
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
        quiz_entries=_anchored_quiz_entries(choice_claims, include_choices=True),
    )

    open_report = evaluate_run(open_run_path)
    choice_report = evaluate_run(choice_run_path)
    open_dimensions = cast("dict[str, dict[str, object]]", open_report.to_payload()["dimensions"])
    choice_dimensions = cast(
        "dict[str, dict[str, object]]",
        choice_report.to_payload()["dimensions"],
    )

    assert open_dimensions["quiz_transfer"]["score"] == 7.5
    assert choice_dimensions["quiz_transfer"]["score"] == 10.0
    assert choice_report.overall > open_report.overall


def test_quiz_transfer_invalid_choice_shape_lowers_score_without_crashing(
    tmp_path: Path,
) -> None:
    valid_run_id = "run_valid_choice_quiz"
    valid_claims = _standard_quiz_claims(valid_run_id)
    valid_run_path = _write_run_fixture(
        tmp_path,
        run_id=valid_run_id,
        claims=valid_claims,
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
        quiz_entries=_anchored_quiz_entries(valid_claims, include_choices=True),
    )
    invalid_run_id = "run_invalid_choice_quiz"
    invalid_claims = _standard_quiz_claims(invalid_run_id)
    invalid_run_path = _write_run_fixture(
        tmp_path,
        run_id=invalid_run_id,
        claims=invalid_claims,
        patch_text=_standard_quiz_patch_text(),
        learnability_score=0.9,
        with_lesson=True,
        with_quiz=True,
        quiz_entries=_anchored_quiz_entries(
            invalid_claims,
            include_choices=True,
            invalid_choices=True,
        ),
    )

    valid_report = evaluate_run(valid_run_path)
    invalid_report = evaluate_run(invalid_run_path)
    valid_dimensions = cast("dict[str, dict[str, object]]", valid_report.to_payload()["dimensions"])
    invalid_dimensions = cast(
        "dict[str, dict[str, object]]",
        invalid_report.to_payload()["dimensions"],
    )
    valid_score = cast("float", valid_dimensions["quiz_transfer"]["score"])
    invalid_score = cast("float", invalid_dimensions["quiz_transfer"]["score"])

    assert invalid_score == 7.5
    assert invalid_score < valid_score
    assert invalid_report.verdict in {"PASS", "CAUTION"}


def test_evaluate_run_does_not_pass_without_lesson_and_quiz_even_when_other_dims_are_high(
    tmp_path: Path,
) -> None:
    patch_text = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,8 @@
-def retry_once():
-    return 1
+def retry_once():
+    for attempt in range(3):
+        try:
+            return attempt
+        except Exception:
+            continue
+    return 0
+# end
"""
    claims = [
        ClaimRecord(
            claim_id="claim_retry_flow",
            run_id="run_no_stage3",
            text="The retry helper now loops, handles exceptions, and falls back to 0.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=1, end=8, side="new")],
        ),
    ]
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run_no_stage3",
        claims=claims,
        patch_text=patch_text,
        learnability_score=1.0,
        with_lesson=False,
        with_quiz=False,
    )
    _write_spec_alignment_artifact(run_path, score=10.0)

    report = evaluate_run(run_path)

    assert report.overall >= 80.0
    assert report.verdict == "CAUTION"


def test_evaluate_run_does_not_pass_with_partial_lesson_artifacts(
    tmp_path: Path,
) -> None:
    patch_text = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,8 @@
-def retry_once():
-    return 1
+def retry_once():
+    for attempt in range(3):
+        try:
+            return attempt
+        except Exception:
+            continue
+    return 0
+# end
"""
    claims = [
        ClaimRecord(
            claim_id="claim_retry_loop",
            run_id="run_partial_stage3",
            text="The retry helper now loops, handles exceptions, and falls back to 0.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=1, end=8, side="new")],
        ),
    ]
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run_partial_stage3",
        claims=claims,
        patch_text=patch_text,
        learnability_score=1.0,
        with_lesson=True,
        with_quiz=True,
    )
    (run_path / "lesson" / "lesson.hint.md").unlink()

    report = evaluate_run(run_path)

    assert report.overall >= 80.0
    assert report.verdict == "CAUTION"


def test_runtime_eval_bundle_version_matches_repo_bundle() -> None:
    assert compute_runtime_eval_bundle_version() == compute_eval_bundle_version(_REPO_ROOT)


def test_verify_command_writes_score_json_for_workspace_run(tmp_path: Path) -> None:
    patch_text = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
-value = 1
+value = 2
+print(value)
"""
    claim = ClaimRecord(
        claim_id="claim_value_update",
        run_id="run_cli",
        text="The module now prints the updated value.",
        status="verified",
        confidence="high",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=2, side="new")],
    )
    run_path = _write_run_fixture(
        tmp_path,
        run_id="run_cli",
        claims=[claim],
        patch_text=patch_text,
        learnability_score=0.7,
        with_lesson=True,
        with_quiz=True,
    )

    result = _RUNNER.invoke(app(), ["verify", "run_cli", "--repo-root", str(tmp_path)])

    assert result.exit_code == 0
    payload = json.loads((run_path / "score.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "run_cli"
    assert payload["eval_bundle_version"] == compute_eval_bundle_version(_REPO_ROOT)
