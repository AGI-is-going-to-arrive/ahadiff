from __future__ import annotations

import json
from pathlib import Path

from ahadiff.contracts import ResultEvent, RunStatus, Verdict
from ahadiff.eval.deterministic import DimensionScore
from ahadiff.eval.evaluator import ScoreReport
from ahadiff.eval.gates import HardGateResult, HardGateSummary
from ahadiff.eval.ratchet import (
    decide_learn_ratchet,
    has_git_ancestry,
    select_baseline_event,
    should_trigger_phase25,
)


def _score_report(
    *,
    source_kind: str,
    source_ref: str,
    overall: float,
    verdict: Verdict = "PASS",
    degraded_flags: dict[str, bool] | None = None,
    hard_gate_results: tuple[HardGateResult, ...] | None = None,
) -> ScoreReport:
    gate_results = hard_gate_results or (HardGateResult(name="accuracy", passed=True, detail="ok"),)
    return ScoreReport(
        run_id="run_now",
        source_ref=source_ref,
        source_kind=source_kind,
        capability_level=3,
        degraded_flags=degraded_flags or {},
        overall=overall,
        verdict=verdict,
        weakest_dim="conciseness",
        eval_bundle_version="bundle-v1",
        rubric_version="v0.1",
        dimensions=(DimensionScore(name="accuracy", score=20.0, max_score=20.0, reason="ok"),),
        hard_gates=HardGateSummary(results=gate_results),
        notes=(),
    )


def _event(
    *,
    source_ref: str,
    overall: float,
    verdict: Verdict = "PASS",
    status: RunStatus = "keep",
    event_type: str = "learn",
    run_id: str | None = None,
    workspace_root: Path | None = None,
) -> ResultEvent:
    event = ResultEvent(
        event_id=f"018f0f52-91c0-7abc-8123-{int(overall * 100):012d}",
        run_id=run_id or f"run_{overall}",
        event_type=event_type,
        timestamp="2026-04-23T00:00:00Z",
        source_ref=source_ref,
        base_ref=None,
        prompt_version="prompt-v1",
        eval_bundle_version="bundle-v1",
        rubric_version="v0.1",
        overall=overall,
        verdict=verdict,
        status=status,
        weakest_dim="conciseness",
        note_json=None,
    )
    if workspace_root is not None:
        _write_finalized_marker(workspace_root, event)
    return event


def _write_finalized_marker(workspace_root: Path, event: ResultEvent) -> None:
    marker_path = workspace_root / ".ahadiff" / "runs" / event.run_id / "finalized.json"
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps({"run_id": event.run_id, "event_id": event.event_id}) + "\n",
        encoding="utf-8",
    )


def _init_git_repo(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, timeout=30)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        timeout=30,
    )


def _commit_file(tmp_path: Path, name: str, content: str, message: str) -> str:
    import subprocess

    (tmp_path / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=tmp_path, check=True, timeout=30)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        timeout=30,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    ).stdout.strip()


def test_non_git_inputs_are_non_ratcheted() -> None:
    report = _score_report(source_kind="patch_file", source_ref="sha256:abc", overall=82.0)

    decision = decide_learn_ratchet(
        workspace_root=Path("/tmp"),
        report=report,
        prior_events=(),
    )

    assert decision.status == "non_ratcheted"


def test_git_input_without_prior_baseline_returns_baseline(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    head = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    report = _score_report(source_kind="git_ref", source_ref=head, overall=78.0)

    decision = decide_learn_ratchet(
        workspace_root=tmp_path,
        report=report,
        prior_events=(),
    )

    assert has_git_ancestry(tmp_path, "git_ref", head) is True
    assert decision.status == "baseline"


def test_failed_gate_without_prior_baseline_discards(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    head = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    report = _score_report(
        source_kind="git_ref",
        source_ref=head,
        overall=90.0,
        verdict="FAIL",
        hard_gate_results=(HardGateResult(name="accuracy", passed=False, detail="below gate"),),
    )

    decision = decide_learn_ratchet(
        workspace_root=tmp_path,
        report=report,
        prior_events=(),
    )

    assert decision.status == "discard"
    assert decision.base_ref is None
    assert decision.note_payload == {
        "ratchet_reason": "verdict_or_hard_gate_failed",
        "verdict": "FAIL",
        "failed_gates": ["accuracy"],
    }


def test_git_input_keeps_when_score_improves_over_ancestor(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    head = _commit_file(tmp_path, "app.py", "value = 2\n", "update")
    prior = (_event(source_ref=base, overall=70.0, status="baseline", workspace_root=tmp_path),)
    report = _score_report(source_kind="git_ref", source_ref=head, overall=81.0)

    decision = decide_learn_ratchet(
        workspace_root=tmp_path,
        report=report,
        prior_events=prior,
    )

    assert (
        select_baseline_event(
            workspace_root=tmp_path,
            source_ref=head,
            prior_events=prior,
        )
        == prior[0]
    )
    assert decision.status == "keep"
    assert decision.base_ref == base


def test_failed_gate_discards_even_when_score_improves_over_baseline(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    head = _commit_file(tmp_path, "app.py", "value = 2\n", "update")
    prior = (_event(source_ref=base, overall=70.0, status="baseline", workspace_root=tmp_path),)
    report = _score_report(
        source_kind="git_ref",
        source_ref=head,
        overall=91.0,
        verdict="FAIL",
        hard_gate_results=(HardGateResult(name="evidence", passed=False, detail="below gate"),),
    )

    decision = decide_learn_ratchet(
        workspace_root=tmp_path,
        report=report,
        prior_events=prior,
    )

    assert decision.status == "discard"
    assert decision.base_ref == base
    assert decision.note_payload == {
        "baseline_overall": 70.0,
        "ratchet_reason": "verdict_or_hard_gate_failed",
        "verdict": "FAIL",
        "failed_gates": ["evidence"],
    }


def test_caution_verdict_discards_even_when_hard_gates_pass(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    head = _commit_file(tmp_path, "app.py", "value = 2\n", "update")
    prior = (_event(source_ref=base, overall=70.0, status="baseline", workspace_root=tmp_path),)
    report = _score_report(
        source_kind="git_ref",
        source_ref=head,
        overall=91.0,
        verdict="CAUTION",
    )

    decision = decide_learn_ratchet(
        workspace_root=tmp_path,
        report=report,
        prior_events=prior,
    )

    assert decision.status == "discard"
    assert decision.base_ref == base
    assert decision.note_payload == {
        "baseline_overall": 70.0,
        "ratchet_reason": "verdict_or_hard_gate_failed",
        "verdict": "CAUTION",
        "failed_gates": [],
    }


def test_git_input_discards_when_score_regresses(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    head = _commit_file(tmp_path, "app.py", "value = 2\n", "update")
    prior = (_event(source_ref=base, overall=85.0, status="baseline", workspace_root=tmp_path),)
    report = _score_report(source_kind="git_ref", source_ref=head, overall=80.0)

    decision = decide_learn_ratchet(
        workspace_root=tmp_path,
        report=report,
        prior_events=prior,
    )

    assert decision.status == "discard"
    assert decision.base_ref == base


def test_select_baseline_event_ignores_score_lane_events(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    head = _commit_file(tmp_path, "app.py", "value = 2\n", "update")
    prior = (
        _event(
            source_ref=base,
            overall=75.0,
            status="baseline",
            event_type="score",
            workspace_root=tmp_path,
        ),
        _event(source_ref=base, overall=74.0, status="baseline", workspace_root=tmp_path),
    )

    baseline = select_baseline_event(
        workspace_root=tmp_path,
        source_ref=head,
        prior_events=prior,
        allowed_event_types={"learn", "verify"},
    )

    assert baseline == prior[1]


def test_select_baseline_event_ignores_non_pass_counted_events(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    head = _commit_file(tmp_path, "app.py", "value = 2\n", "update")
    failed_event = _event(
        source_ref=base,
        overall=91.0,
        verdict="FAIL",
        status="baseline",
        run_id="run_failed_baseline",
        workspace_root=tmp_path,
    )
    passing_event = _event(
        source_ref=base,
        overall=70.0,
        status="baseline",
        run_id="run_passing_baseline",
        workspace_root=tmp_path,
    )
    report = _score_report(source_kind="git_ref", source_ref=head, overall=80.0)

    baseline = select_baseline_event(
        workspace_root=tmp_path,
        source_ref=head,
        prior_events=(failed_event, passing_event),
    )
    decision = decide_learn_ratchet(
        workspace_root=tmp_path,
        report=report,
        prior_events=(failed_event, passing_event),
    )

    assert baseline == passing_event
    assert decision.status == "keep"
    assert decision.base_ref == base


def test_select_baseline_event_prefers_nearest_ancestor_over_newer_evaluation(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    middle = _commit_file(tmp_path, "app.py", "value = 2\n", "middle")
    head = _commit_file(tmp_path, "app.py", "value = 3\n", "head")
    prior = (
        ResultEvent(
            event_id="018f0f52-91c0-7abc-8123-000000000101",
            run_id="run_base",
            event_type="learn",
            timestamp="2026-04-23T00:00:02Z",
            source_ref=base,
            base_ref=None,
            prompt_version="prompt-v1",
            eval_bundle_version="bundle-v1",
            rubric_version="v0.1",
            overall=90.0,
            verdict="PASS",
            status="baseline",
            weakest_dim="conciseness",
            note_json=None,
        ),
        ResultEvent(
            event_id="018f0f52-91c0-7abc-8123-000000000102",
            run_id="run_middle",
            event_type="learn",
            timestamp="2026-04-23T00:00:01Z",
            source_ref=middle,
            base_ref=None,
            prompt_version="prompt-v1",
            eval_bundle_version="bundle-v1",
            rubric_version="v0.1",
            overall=88.0,
            verdict="PASS",
            status="keep",
            weakest_dim="conciseness",
            note_json=None,
        ),
    )
    for event in prior:
        _write_finalized_marker(tmp_path, event)

    baseline = select_baseline_event(
        workspace_root=tmp_path,
        source_ref=head,
        prior_events=prior,
        allowed_event_types={"learn"},
    )

    assert baseline == prior[1]


def test_degraded_comparison_is_not_directly_discarded(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    head = _commit_file(tmp_path, "app.py", "value = 2\n", "update")
    prior = (_event(source_ref=base, overall=85.0, status="baseline", workspace_root=tmp_path),)
    report = _score_report(
        source_kind="git_ref",
        source_ref=head,
        overall=80.0,
        degraded_flags={"diff_clipped": True},
    )

    decision = decide_learn_ratchet(
        workspace_root=tmp_path,
        report=report,
        prior_events=prior,
    )

    assert decision.status == "keep"
    assert decision.note_payload is not None
    assert decision.note_payload["ratchet_note"] == "degraded_comparison"


def test_failed_gate_overrides_degraded_comparison_keep(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    head = _commit_file(tmp_path, "app.py", "value = 2\n", "update")
    prior = (_event(source_ref=base, overall=85.0, status="baseline", workspace_root=tmp_path),)
    report = _score_report(
        source_kind="git_ref",
        source_ref=head,
        overall=80.0,
        verdict="FAIL",
        degraded_flags={"diff_clipped": True},
        hard_gate_results=(HardGateResult(name="accuracy", passed=False, detail="below gate"),),
    )

    decision = decide_learn_ratchet(
        workspace_root=tmp_path,
        report=report,
        prior_events=prior,
    )

    assert decision.status == "discard"
    assert decision.base_ref == base
    assert decision.note_payload == {
        "baseline_overall": 85.0,
        "ratchet_reason": "verdict_or_hard_gate_failed",
        "verdict": "FAIL",
        "failed_gates": ["accuracy"],
    }


def test_select_baseline_event_ignores_degraded_events(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    head = _commit_file(tmp_path, "app.py", "value = 2\n", "update")
    prior = (
        ResultEvent(
            event_id="018f0f52-91c0-7abc-8123-000000000103",
            run_id="run_degraded",
            event_type="learn",
            timestamp="2026-04-23T00:00:02Z",
            source_ref=base,
            base_ref=None,
            prompt_version="prompt-v1",
            eval_bundle_version="bundle-v1",
            rubric_version="v0.1",
            overall=75.0,
            verdict="PASS",
            status="baseline",
            weakest_dim="conciseness",
            note_json='{"degraded_flags":{"diff_clipped":true}}',
        ),
        ResultEvent(
            event_id="018f0f52-91c0-7abc-8123-000000000104",
            run_id="run_clean",
            event_type="learn",
            timestamp="2026-04-23T00:00:01Z",
            source_ref=base,
            base_ref=None,
            prompt_version="prompt-v1",
            eval_bundle_version="bundle-v1",
            rubric_version="v0.1",
            overall=74.0,
            verdict="PASS",
            status="keep",
            weakest_dim="conciseness",
            note_json=None,
        ),
    )
    for event in prior:
        _write_finalized_marker(tmp_path, event)

    baseline = select_baseline_event(
        workspace_root=tmp_path,
        source_ref=head,
        prior_events=prior,
        allowed_event_types={"learn"},
    )

    assert baseline == prior[1]


def test_select_baseline_event_ignores_unfinalized_events(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    head = _commit_file(tmp_path, "app.py", "value = 2\n", "update")
    unfinalized = _event(
        source_ref=base,
        overall=90.0,
        status="baseline",
        run_id="run_unfinalized",
    )
    finalized = _event(
        source_ref=base,
        overall=70.0,
        status="keep",
        run_id="run_finalized",
        workspace_root=tmp_path,
    )

    baseline = select_baseline_event(
        workspace_root=tmp_path,
        source_ref=head,
        prior_events=(unfinalized, finalized),
        allowed_event_types={"learn"},
    )

    assert baseline == finalized


def test_select_baseline_event_rejects_marker_with_mismatched_run_id(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    base = _commit_file(tmp_path, "app.py", "value = 1\n", "init")
    head = _commit_file(tmp_path, "app.py", "value = 2\n", "update")
    event = _event(
        source_ref=base,
        overall=90.0,
        status="baseline",
        run_id="run_real",
        workspace_root=tmp_path,
    )
    marker_path = tmp_path / ".ahadiff" / "runs" / event.run_id / "finalized.json"
    marker_path.write_text(
        json.dumps({"run_id": "run_other", "event_id": event.event_id}) + "\n",
        encoding="utf-8",
    )

    baseline = select_baseline_event(
        workspace_root=tmp_path,
        source_ref=head,
        prior_events=(event,),
        allowed_event_types={"learn"},
    )

    assert baseline is None


def test_phase25_trigger_requires_two_consecutive_discards() -> None:
    assert should_trigger_phase25(["keep", "discard", "discard"]) is True
    assert should_trigger_phase25(["discard"]) is False
    assert should_trigger_phase25(["discard", "keep"]) is False
