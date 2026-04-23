from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from typer.testing import CliRunner

from ahadiff.cli import app
from ahadiff.contracts import ClaimRecord, SourceHunk, compute_eval_bundle_version
from ahadiff.contracts.eval_bundle import compute_runtime_eval_bundle_version
from ahadiff.eval import evaluate_run
from ahadiff.git.line_map import build_line_map, serialize_line_map_payload

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
        entries = [
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
        (quiz_dir / "quiz.jsonl").write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in entries) + "\n",
            encoding="utf-8",
        )
    return run_path


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

    assert dimensions["quiz_transfer"]["score"] == 4.0
    assert report.verdict == "CAUTION"


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
