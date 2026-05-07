from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
from typer.testing import CliRunner

from ahadiff.cli import app
from ahadiff.contracts import ClaimRecord, ProviderConfig, SourceHunk, compute_eval_bundle_version
from ahadiff.contracts.eval_bundle import compute_runtime_eval_bundle_version
from ahadiff.core.config import SecurityConfig
from ahadiff.eval import evaluate_run
from ahadiff.eval.evaluator import run_llm_judge_for_run
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
        dimension.name: {"score": dimension.max_score, "reason": "ok"}
        for dimension in deterministic_report.dimensions
    }
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
    payload = json.loads((run_path / "judge.json").read_text(encoding="utf-8"))
    assert payload["artifact"] == "llm_judge"
    assert payload["model_id"] == "gpt-5.5"
    assert payload["usage"] == {"input_tokens": 11, "output_tokens": 22}


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
