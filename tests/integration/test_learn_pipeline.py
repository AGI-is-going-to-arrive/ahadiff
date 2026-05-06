from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from ahadiff.cli import app
from ahadiff.contracts import ClaimRecord, ReviewCard, SourceHunk
from ahadiff.eval.benchmark import load_benchmark_manifest, verify_suite_digest
from ahadiff.git.line_map import build_line_map, serialize_line_map_payload
from ahadiff.git.symbols import serialize_symbols_payload
from ahadiff.quiz.generator import generate_cards_for_run, load_quiz_questions

_RUNNER = CliRunner()
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO_ROOT / "benchmarks" / "manifest.json"


def _pinned_fixture_ids() -> list[str]:
    manifest = load_benchmark_manifest(_MANIFEST_PATH)
    verify_suite_digest(manifest)
    return [entry.entry_id for entry in manifest.entries if entry.kind == "integration"]


@pytest.mark.pinned
@pytest.mark.parametrize("fixture_id", _pinned_fixture_ids())
def test_pinned_learn_artifact_pipeline_reaches_ci_verified_state(
    tmp_path: Path,
    fixture_id: str,
) -> None:
    manifest = load_benchmark_manifest(_MANIFEST_PATH)
    fixture_entry = next(entry for entry in manifest.entries if entry.entry_id == fixture_id)
    fixture_root = manifest.root / fixture_entry.path
    run_path = _materialize_pinned_run(tmp_path, fixture_id, fixture_root)

    verify_result = _RUNNER.invoke(
        app(),
        ["verify", fixture_id, "--repo-root", str(tmp_path)],
    )
    assert verify_result.exit_code == 0, verify_result.output

    ci_result = _RUNNER.invoke(app(), ["verify", "--ci", "--repo-root", str(tmp_path)])
    assert ci_result.exit_code == 0, ci_result.output
    assert "1 finalized runs checked" in ci_result.output

    expected_manifest = json.loads(
        (fixture_root / "expected_artifacts_manifest.json").read_text(encoding="utf-8")
    )
    assert isinstance(expected_manifest, dict)
    expected_manifest_map = cast("dict[str, object]", expected_manifest)
    required_artifacts = expected_manifest_map["required_artifacts"]
    assert isinstance(required_artifacts, list)
    for raw_artifact in cast("list[object]", required_artifacts):
        assert isinstance(raw_artifact, str)
        if raw_artifact == "results.tsv":
            artifact_path = tmp_path / ".ahadiff" / raw_artifact
        else:
            artifact_path = run_path / raw_artifact
        assert artifact_path.exists(), f"missing pinned artifact: {raw_artifact}"

    graph_path = fixture_root / "graph.json"
    if graph_path.is_file():
        graph_context = json.loads((run_path / "graphify_context.json").read_text(encoding="utf-8"))
        graph_context_map = cast("dict[str, object]", graph_context)
        graph_text = graph_path.read_text(encoding="utf-8")
        assert graph_context_map["schema"] == "ahadiff.graphify_context"
        assert (
            graph_context_map["graph_sha256"]
            == hashlib.sha256(graph_text.encode("utf-8")).hexdigest()
        )
        assert graph_context_map["node_count"] == 15
        assert graph_context_map["edge_count"] == 17
        artifact_set = json.loads((run_path / "artifact_set.json").read_text(encoding="utf-8"))
        artifact_set_map = cast("dict[str, object]", artifact_set)
        assert artifact_set_map["manifest_type"] == "artifact_set"
        generation = artifact_set_map["generation"]
        assert isinstance(generation, dict)
        generation_map = cast("dict[str, object]", generation)
        assert generation_map["graphify_context_from"] == "benchmark.fixture.graph.json"

    score_payload = json.loads((run_path / "score.json").read_text(encoding="utf-8"))
    snapshot = json.loads(
        (fixture_root / "expected_results_snapshot.json").read_text(encoding="utf-8")
    )
    assert score_payload["verdict"] == snapshot["verdict"]
    assert score_payload["overall"] >= 80.0


def _materialize_pinned_run(workspace_root: Path, run_id: str, fixture_root: Path) -> Path:
    run_path = workspace_root / ".ahadiff" / "runs" / run_id
    run_path.mkdir(parents=True, exist_ok=True)
    patch_text = (fixture_root / "diff.patch").read_text(encoding="utf-8")
    metadata = {
        "run_id": run_id,
        "source_kind": "patch_file",
        "source_ref": f"pinned:{run_id}",
        "capability_level": 3,
        "degraded_flags": {},
        "learnability": {"score": 0.94},
        "source_detail": {"fixture": run_id},
        "privacy_mode": "strict_local",
    }
    claims = (
        ClaimRecord(
            claim_id=f"{run_id}_claim_behavior",
            run_id=run_id,
            text="The pinned fixture records the changed behavior in src/app.py.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=1, end=5, side="new")],
            symbols=["pinned-pipeline"],
            extractor="python_ast",
        ),
        ClaimRecord(
            claim_id=f"{run_id}_claim_artifact",
            run_id=run_id,
            text="The pinned fixture produces lesson, quiz, score, and finalized artifacts.",
            status="verified",
            confidence="high",
            source_hunks=[SourceHunk(file="src/app.py", start=2, end=5, side="new")],
            symbols=["artifact-finalization"],
            extractor="section_header",
        ),
    )
    (run_path / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text(patch_text, encoding="utf-8")
    (run_path / "line_map.json").write_text(
        json.dumps(
            serialize_line_map_payload(build_line_map(patch_text)),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_path / "symbols.json").write_text(
        json.dumps(serialize_symbols_payload(()), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    _write_graphify_fixture_artifacts(run_path, run_id, fixture_root)
    (run_path / "claims.jsonl").write_text(
        "\n".join(json.dumps(claim.model_dump(mode="json"), ensure_ascii=False) for claim in claims)
        + "\n",
        encoding="utf-8",
    )
    _write_lesson(run_path, run_id)
    _write_quiz(run_path, run_id, claims)
    return run_path


def _write_graphify_fixture_artifacts(run_path: Path, run_id: str, fixture_root: Path) -> None:
    graph_path = fixture_root / "graph.json"
    if not graph_path.is_file():
        return

    from ahadiff.graphify import parse_graph_json
    from ahadiff.graphify.parser import PARSER_VERSION

    graph_text = graph_path.read_text(encoding="utf-8")
    graph = parse_graph_json(graph_path)
    graph_sha256 = hashlib.sha256(graph_text.encode("utf-8")).hexdigest()
    context_payload = {
        "edge_count": len(graph.links),
        "freshness": "fresh",
        "graph_sha256": graph_sha256,
        "graph_source": "fixture:graph.json",
        "import_time": "fixture",
        "node_count": len(graph.nodes),
        "parser_version": PARSER_VERSION,
        "schema": "ahadiff.graphify_context",
        "schema_version": 1,
    }
    context_text = json.dumps(context_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (run_path / "graphify_context.json").write_text(context_text, encoding="utf-8")
    artifact_set = {
        "artifacts": [
            {
                "artifact_type": "graphify_context",
                "bytes": len(context_text.encode("utf-8")),
                "media_type": "application/json",
                "path": "graphify_context.json",
                "schema": "ahadiff.graphify_context",
                "schema_version": 1,
                "sha256": hashlib.sha256(context_text.encode("utf-8")).hexdigest(),
            }
        ],
        "generation": {"graphify_context_from": "benchmark.fixture.graph.json"},
        "manifest_type": "artifact_set",
        "run_id": run_id,
        "schema": "ahadiff.artifact_set",
        "schema_version": 1,
    }
    (run_path / "artifact_set.json").write_text(
        json.dumps(artifact_set, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_lesson(run_path: Path, run_id: str) -> None:
    lesson_dir = run_path / "lesson"
    lesson_dir.mkdir()
    (lesson_dir / "lesson.full.md").write_text(
        f"TL;DR\n\n{run_id} completes the pinned backend artifact chain.\n\n"
        "What Changed\n\nA deterministic fixture patch is evaluated.\n\n"
        "Why\n\nThe run must create durable score and finalized markers.\n\n"
        "Walkthrough\n\nInspect src/app.py and the generated run artifacts.\n\n"
        "Claims\n\nBoth claims are anchored to changed lines.\n\nSources\n\nsrc/app.py:2\n",
        encoding="utf-8",
    )
    (lesson_dir / "lesson.hint.md").write_text(
        "Hint: inspect src/app.py line 2.\n",
        encoding="utf-8",
    )
    (lesson_dir / "lesson.compact.md").write_text(
        f"{run_id} verifies the pinned backend pipeline.\n",
        encoding="utf-8",
    )


def _quiz_choices(
    correct_answer: str,
    distractor_b: str,
    distractor_c: str,
    distractor_d: str,
) -> list[dict[str, object]]:
    return [
        {"label": "A", "text": correct_answer, "is_correct": True},
        {"label": "B", "text": distractor_b, "is_correct": False},
        {"label": "C", "text": distractor_c, "is_correct": False},
        {"label": "D", "text": distractor_d, "is_correct": False},
    ]


def _write_quiz(run_path: Path, run_id: str, claims: tuple[ClaimRecord, ...]) -> None:
    quiz_dir = run_path / "quiz"
    quiz_dir.mkdir()
    quiz_entries = [
        {
            "question": "Which file anchors the fixture?",
            "expected_answer": "src/app.py",
            "source_claims": [claims[0].claim_id],
            "evidence": [{"file": "src/app.py", "line": 2}],
            "concepts": ["pinned-pipeline"],
            "choices": _quiz_choices(
                "src/app.py",
                "README.md",
                "pyproject.toml",
                "tests/unit/test_cli.py",
            ),
        },
        {
            "question": "Which marker proves finalization?",
            "expected_answer": "finalized.json",
            "source_claims": [claims[1].claim_id],
            "evidence": [{"file": "src/app.py", "line": 3}],
            "concepts": ["artifact-finalization"],
            "choices": _quiz_choices(
                "finalized.json",
                "claims.raw.jsonl",
                "graph.json",
                "provider_probe.json",
            ),
        },
        {
            "question": "Which command re-checks finalized artifacts?",
            "expected_answer": "ahadiff verify --ci",
            "source_claims": [claims[1].claim_id],
            "evidence": [{"file": "src/app.py", "line": 4}],
            "concepts": ["ci-verify"],
            "choices": _quiz_choices(
                "ahadiff verify --ci",
                "ahadiff init --force",
                "ahadiff quiz --all",
                "ahadiff graph refresh",
            ),
        },
    ]
    (quiz_dir / "quiz.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in quiz_entries) + "\n",
        encoding="utf-8",
    )
    cards_path = generate_cards_for_run(
        run_path=run_path,
        questions=load_quiz_questions(quiz_dir / "quiz.jsonl"),
        verdict="PASS",
    )
    assert cards_path is not None
    cards = [
        ReviewCard.model_validate_json(line)
        for line in cards_path.read_text(encoding="utf-8").splitlines()
    ]
    questions = load_quiz_questions(quiz_dir / "quiz.jsonl")
    question_card_ids = [question.review_card_id for question in questions]
    card_ids = [card.card_id for card in cards]
    assert question_card_ids == card_ids
    for line in cards_path.read_text(encoding="utf-8").splitlines():
        ReviewCard.model_validate_json(line)
