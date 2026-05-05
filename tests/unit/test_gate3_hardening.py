from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from ahadiff.claims.extract import parse_claim_candidates_text, write_claim_candidates_jsonl
from ahadiff.claims.schema import ClaimCandidate
from ahadiff.claims.verify import verify_claim_candidate
from ahadiff.contracts import ClaimRecord, SourceHunk
from ahadiff.core.config import load_config
from ahadiff.core.errors import ConfigError, InputError
from ahadiff.core.paths import repo_config_path
from ahadiff.eval.deterministic import build_deterministic_scores
from ahadiff.eval.evaluator import ScoreReport, parse_llm_judge_output
from ahadiff.eval.gates import HardGateResult, HardGateSummary, evaluate_hard_gates
from ahadiff.eval.results import (
    append_result,
    finalized_marker_path,
    load_result_events,
    results_tsv_path_for_run,
    review_db_path_for_run,
)
from ahadiff.eval.rubric import load_rubric
from ahadiff.git.line_map import build_line_map
from ahadiff.git.parser import parse_unified_diff
from ahadiff.git.symbols import extract_symbols
from ahadiff.serve import ServeState, create_app

if TYPE_CHECKING:
    from pathlib import Path

    from ahadiff.git.line_map import FileLineMap


def _init_git_repo(root: Path) -> None:
    (root / ".git").mkdir()


def _repo_with_config(tmp_path: Path, content: str) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    config_path = repo_config_path(repo_root)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(content, encoding="utf-8")
    return repo_root


def test_gate3_unknown_config_keys_remain_non_fatal(tmp_path: Path) -> None:
    repo_root = _repo_with_config(
        tmp_path,
        'rogue = true\n\n[future_feature]\nflag = "kept as unknown"\n',
    )

    snapshot = load_config(repo_root, env={"HOME": str(tmp_path / "home")})

    assert snapshot.repo_unknown_keys == ("future_feature.flag", "rogue")


def test_gate3_known_config_key_rejects_wrong_toml_type(tmp_path: Path) -> None:
    repo_root = _repo_with_config(tmp_path, '[capture]\nmax_files = "50"\n')

    with pytest.raises(ConfigError, match=r"capture\.max_files expects int, got str"):
        load_config(repo_root, env={"HOME": str(tmp_path / "home")})


@pytest.mark.parametrize("key", ["max_files", "hard_limit", "max_patch_bytes"])
def test_gate3_capture_limits_reject_non_positive_values(tmp_path: Path, key: str) -> None:
    repo_root = _repo_with_config(tmp_path, f"[capture]\n{key} = 0\n")

    with pytest.raises(ConfigError, match=rf"capture\.{key} must be >= 1"):
        load_config(repo_root, env={"HOME": str(tmp_path / "home")})


def test_gate3_known_config_table_rejects_scalar_value(tmp_path: Path) -> None:
    repo_root = _repo_with_config(tmp_path, 'llm = "not-a-table"\n')

    with pytest.raises(ConfigError, match=r"llm expects table, got str"):
        load_config(repo_root, env={"HOME": str(tmp_path / "home")})


@pytest.mark.parametrize(
    ("provider_body", "expected"),
    [
        (
            'provider_class = "bogus"\n'
            'model_name = "gpt-5.4-mini"\n'
            'base_url = "https://api.example.test"\n',
            r"providers\.demo\.provider_class must be one of",
        ),
        (
            'provider_class = "openai"\n'
            'model_name = "   "\n'
            'base_url = "https://api.example.test"\n',
            r"providers\.demo\.model_name expects non-empty str",
        ),
        (
            'provider_class = "openai"\nmodel_name = "gpt-5.4-mini"\nbase_url = "not-a-url"\n',
            r"providers\.demo\.base_url expects valid URL",
        ),
        (
            'provider_class = "openai"\n'
            'model_name = "gpt-5.4-mini"\n'
            'base_url = "ftp://files.example.test"\n',
            r"providers\.demo\.base_url expects http or https URL",
        ),
    ],
)
def test_gate3_provider_config_schema_is_validated(
    tmp_path: Path,
    provider_body: str,
    expected: str,
) -> None:
    repo_root = _repo_with_config(tmp_path, f"[providers.demo]\n{provider_body}")

    with pytest.raises(ConfigError, match=expected):
        load_config(repo_root, env={"HOME": str(tmp_path / "home")})


def test_gate3_toml_parse_error_includes_path_and_line_number(tmp_path: Path) -> None:
    repo_root = _repo_with_config(tmp_path, "[capture]\nmax_files = \n")
    config_path = repo_config_path(repo_root)

    with pytest.raises(ConfigError) as error:
        load_config(repo_root, env={"HOME": str(tmp_path / "home")})

    message = str(error.value)
    assert str(config_path) in message
    assert "line 2" in message


def _patch_text() -> str:
    return """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
-value = 1
+value = 2
 print(value)
"""


def _line_maps() -> tuple[FileLineMap, ...]:
    return build_line_map(parse_unified_diff(_patch_text()))


def _claim_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "claim_id": "claim-1",
        "run_id": "run-1",
        "text": "updates the value",
        "source_hunks": [{"file": "src/app.py", "start": 1, "end": 1, "side": "new"}],
    }
    payload.update(overrides)
    return payload


def test_gate3_llm_judge_output_rejects_malformed_scores() -> None:
    valid_dimensions = {
        dimension.name: {"score": dimension.max_score, "reason": "ok"}
        for dimension in load_rubric().dimensions
    }

    assert parse_llm_judge_output(json.dumps({"dimensions": valid_dimensions}))

    with pytest.raises(InputError, match="invalid LLM judge JSON"):
        parse_llm_judge_output("{not-json")
    with pytest.raises(InputError, match="missing dimensions"):
        parse_llm_judge_output(json.dumps({"dimensions": {}}))
    invalid_type = dict(valid_dimensions)
    invalid_type["accuracy"] = {"score": "20"}
    with pytest.raises(InputError, match="score must be numeric"):
        parse_llm_judge_output(json.dumps({"dimensions": invalid_type}))
    invalid_range = dict(valid_dimensions)
    invalid_range["accuracy"] = {"score": 101}
    with pytest.raises(InputError, match="between 0.00"):
        parse_llm_judge_output(json.dumps({"dimensions": invalid_range}))
    with pytest.raises(InputError, match="Disallowed JSON constant"):
        parse_llm_judge_output('{"dimensions":{"accuracy":NaN}}')


def test_gate3_deterministic_scores_handle_empty_and_unicode_claims() -> None:
    unicode_patch = """\
diff --git "a/src/é.py" "b/src/é.py"
--- "a/src/é.py"
+++ "b/src/é.py"
@@ -1 +1 @@
-old = 1
+new = 2
"""
    rubric = load_rubric()
    empty = build_deterministic_scores(
        rubric=rubric,
        metadata={"learnability": {"score": 0.5}},
        patch_text=unicode_patch,
        claims=(),
        line_maps=build_line_map(parse_unified_diff(unicode_patch)),
        lesson_artifacts={},
        quiz_entries=(),
    )
    assert empty.score_lookup()["accuracy"] == 0.0

    claim = ClaimRecord(
        claim_id="claim-unicode",
        run_id="run-1",
        text="updates the unicode path",
        status="verified",
        confidence="high",
        source_hunks=[SourceHunk(file="src/é.py", start=1, end=1, side="new")],
    )
    scored = build_deterministic_scores(
        rubric=rubric,
        metadata={"learnability": {"score": 0.5}},
        patch_text=unicode_patch,
        claims=(claim,),
        line_maps=build_line_map(parse_unified_diff(unicode_patch)),
        lesson_artifacts={"compact": "short"},
        quiz_entries=(),
    )
    assert scored.score_lookup()["diff_coverage"] > 0.0
    with pytest.raises(ValidationError, match="Field required"):
        ClaimRecord.model_validate({"claim_id": "broken", "run_id": "run-1", "status": "verified"})


def test_gate3_hard_gates_handle_missing_boundary_and_safety_findings() -> None:
    rubric = load_rubric()

    missing = evaluate_hard_gates(
        rubric=rubric,
        dimension_scores={},
        claims=(),
        secret_leak_detected=False,
        injection_unresolved=False,
    )
    assert missing.failed_names() == ("accuracy", "evidence")

    boundary = evaluate_hard_gates(
        rubric=rubric,
        dimension_scores={"accuracy": 14.0, "evidence": 13.0},
        claims=(),
        secret_leak_detected=False,
        injection_unresolved=False,
    )
    assert "accuracy" in boundary.failed_names()
    assert boundary.as_payload()["accuracy"]["detail"] == (
        "accuracy score 14.00 <= 14.00; requires > 14.00"
    )

    non_critical = evaluate_hard_gates(
        rubric=rubric,
        dimension_scores={"accuracy": 15.0, "evidence": 13.0},
        claims=(),
        secret_leak_detected=False,
        injection_unresolved=False,
        safety_findings=({"severity": "High"},),
    )
    critical = evaluate_hard_gates(
        rubric=rubric,
        dimension_scores={"accuracy": 15.0, "evidence": 13.0},
        claims=(),
        secret_leak_detected=False,
        injection_unresolved=False,
        safety_findings=({"severity": "Critical"},),
    )
    assert "critical_safety_findings" not in non_critical.failed_names()
    assert "critical_safety_findings" in critical.failed_names()


def _score_report(run_id: str) -> ScoreReport:
    return ScoreReport(
        run_id=run_id,
        source_ref="abc123",
        source_kind="git_ref",
        capability_level=2,
        degraded_flags={},
        overall=88.0,
        verdict="PASS",
        weakest_dim="evidence",
        eval_bundle_version="eval123",
        rubric_version="rubric-v1",
        dimensions=(),
        hard_gates=HardGateSummary(
            results=(HardGateResult("accuracy", True, "ok", score=20.0, threshold=14.0),)
        ),
        notes=(),
    )


def test_gate3_result_events_support_concurrent_writes(tmp_path: Path) -> None:
    run_path = tmp_path / ".ahadiff" / "runs" / "run-concurrent"
    run_path.mkdir(parents=True)

    def write_event(index: int) -> bool:
        outcome = append_result(
            run_path=run_path,
            report=_score_report("run-concurrent"),
            status="non_ratcheted",
            base_ref=None,
            event_type=f"verify-{index}",
            event_id=f"018f0f52-91c0-7abc-8123-{index:012d}",
            write_finalized=False,
            prompt_version_override="prompt123",
        )
        return outcome.sqlite_inserted

    with ThreadPoolExecutor(max_workers=4) as executor:
        inserted = list(executor.map(write_event, range(8)))

    assert inserted == [True] * 8
    assert len(load_result_events(review_db_path_for_run(run_path))) == 8


def test_gate3_result_event_duplicate_and_write_failure_do_not_publish_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_path = tmp_path / ".ahadiff" / "runs" / "run-duplicate"
    run_path.mkdir(parents=True)
    report = _score_report("run-duplicate")
    event_id = "018f0f52-91c0-7abc-8123-000000000001"

    first = append_result(
        run_path=run_path,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="verify",
        event_id=event_id,
        prompt_version_override="prompt123",
    )
    second = append_result(
        run_path=run_path,
        report=report,
        status="non_ratcheted",
        base_ref=None,
        event_type="verify",
        event_id=event_id,
        prompt_version_override="prompt123",
    )
    assert first.sqlite_inserted is True
    assert second.sqlite_inserted is False

    broken_path = tmp_path / "broken" / ".ahadiff" / "runs" / "run-broken"
    broken_path.mkdir(parents=True)

    def fail_sync(*_args: object, **_kwargs: object) -> bool:
        raise OSError("disk full")

    monkeypatch.setattr("ahadiff.eval.results.sync_result_event", fail_sync)
    with pytest.raises(OSError, match="disk full"):
        append_result(
            run_path=broken_path,
            report=_score_report("run-broken"),
            status="non_ratcheted",
            base_ref=None,
            event_type="verify",
            event_id="018f0f52-91c0-7abc-8123-000000000002",
            prompt_version_override="prompt123",
        )
    assert not results_tsv_path_for_run(broken_path).exists()
    assert not finalized_marker_path(broken_path).exists()


def test_gate3_result_event_insert_attempts_must_be_positive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_path = tmp_path / ".ahadiff" / "runs" / "run-invalid-attempts"
    run_path.mkdir(parents=True)
    monkeypatch.setattr("ahadiff.eval.results._RESULT_EVENT_INSERT_ATTEMPTS", 0)

    with pytest.raises(AssertionError, match="_RESULT_EVENT_INSERT_ATTEMPTS must be >= 1"):
        append_result(
            run_path=run_path,
            report=_score_report("run-invalid-attempts"),
            status="non_ratcheted",
            base_ref=None,
            event_type="verify",
            event_id="018f0f52-91c0-7abc-8123-000000000003",
            prompt_version_override="prompt123",
        )


def test_gate3_claim_extraction_passes_bad_llm_claims_to_verifier() -> None:
    line_maps = _line_maps()
    result = parse_claim_candidates_text(
        json.dumps(
            {
                "claims": [
                    _claim_payload(source_hunks=[{"file": "src/missing.py", "start": 1, "end": 1}])
                ]
            }
        ),
        default_run_id="run-1",
    )
    assert len(result) == 1
    missing_file = verify_claim_candidate(result[0], line_maps=line_maps, symbols=())
    assert missing_file.record.status == "rejected"
    assert missing_file.record.reason_code == "file_not_in_patch"

    result = parse_claim_candidates_text(
        json.dumps(
            {
                "claims": [
                    _claim_payload(source_hunks=[{"file": "src/app.py", "start": 99, "end": 99}])
                ]
            }
        ),
        default_run_id="run-1",
    )
    assert len(result) == 1
    outside_hunk = verify_claim_candidate(result[0], line_maps=line_maps, symbols=())
    assert outside_hunk.record.status == "rejected"
    assert outside_hunk.record.reason_code == "line_outside_hunk"

    dedup_result = parse_claim_candidates_text(
        json.dumps({"claims": [_claim_payload(), _claim_payload(text="second")]}),
        default_run_id="run-1",
    )
    assert len(dedup_result) == 2
    assert dedup_result[0].claim_id != dedup_result[1].claim_id
    with pytest.raises(InputError, match="claim text must not be empty"):
        parse_claim_candidates_text(
            json.dumps({"claims": [_claim_payload(text="   ")]}),
            default_run_id="run-1",
        )
    with pytest.raises(InputError, match="claim content exceeds"):
        parse_claim_candidates_text(
            json.dumps({"claims": [_claim_payload(text="x" * (10 * 1024 + 1))]}),
            default_run_id="run-1",
        )


def test_gate3_claim_extraction_passes_mode_only_file_to_verifier() -> None:
    mode_only_patch = """\
diff --git a/script.sh b/script.sh
old mode 100644
new mode 100755
"""
    line_maps = build_line_map(parse_unified_diff(mode_only_patch))
    result = parse_claim_candidates_text(
        json.dumps(
            {
                "claims": [
                    {
                        "claim_id": "claim-mode",
                        "run_id": "run-1",
                        "text": "makes script executable",
                        "source_hunks": [
                            {"file": "script.sh", "start": 1, "end": 1, "side": "new"}
                        ],
                    }
                ]
            }
        ),
        default_run_id="run-1",
    )
    assert len(result) == 1
    verified = verify_claim_candidate(result[0], line_maps=line_maps, symbols=())
    assert verified.record.status == "rejected"
    assert verified.record.reason_code == "line_outside_hunk"


def test_gate3_claim_verifier_handles_deleted_binary_and_content_mismatch() -> None:
    deleted_patch = """\
diff --git a/src/old.py b/src/old.py
deleted file mode 100644
--- a/src/old.py
+++ /dev/null
@@ -1 +0,0 @@
-old = 1
"""
    deleted_maps = build_line_map(parse_unified_diff(deleted_patch))
    deleted_claim = ClaimCandidate(
        claim_id="claim-deleted",
        run_id="run-1",
        text="removes old.py",
        source_hunks=[SourceHunk(file="src/old.py", start=1, end=1, side="old")],
    )
    deleted = verify_claim_candidate(deleted_claim, line_maps=deleted_maps, symbols=())
    assert deleted.record.status == "weak"

    binary_patch = """\
diff --git a/image.png b/image.png
new file mode 100644
index 0000000..1111111
Binary files /dev/null and b/image.png differ
"""
    binary_claim = ClaimCandidate(
        claim_id="claim-binary",
        run_id="run-1",
        text="adds an image",
        source_hunks=[SourceHunk(file="image.png", start=1, end=1, side="new")],
    )
    binary = verify_claim_candidate(
        binary_claim,
        line_maps=build_line_map(parse_unified_diff(binary_patch)),
        symbols=(),
    )
    assert binary.record.status == "rejected"

    changed_files = parse_unified_diff(_patch_text())
    mismatch_claim = ClaimCandidate(
        claim_id="claim-mismatch",
        run_id="run-1",
        text="adds retry handling",
        source_hunks=[SourceHunk(file="src/app.py", start=1, end=1, side="new")],
    )
    mismatch = verify_claim_candidate(
        mismatch_claim,
        line_maps=build_line_map(changed_files),
        symbols=extract_symbols(changed_files, after_text_by_path={"src/app.py": "value = 2\n"}),
        after_text_by_path={"src/app.py": "value = 2\n"},
    )
    assert mismatch.record.status == "contradicted"


def test_gate3_claim_jsonl_write_keeps_existing_file_on_partial_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "claims.raw.jsonl"
    output_path.write_text('{"original":true}\n', encoding="utf-8")
    temp_path = tmp_path / ".claims.raw.jsonl.partial.tmp"

    class FailingTemp:
        name = str(temp_path)

        def __enter__(self) -> FailingTemp:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def write(self, _text: str) -> None:
            temp_path.write_text("partial", encoding="utf-8")
            raise OSError("disk full")

    def failing_named_temp_file(*_args: object, **_kwargs: object) -> FailingTemp:
        return FailingTemp()

    monkeypatch.setattr(
        "ahadiff.claims.extract.tempfile.NamedTemporaryFile",
        failing_named_temp_file,
    )
    with pytest.raises(OSError, match="disk full"):
        write_claim_candidates_jsonl(
            output_path,
            [
                ClaimCandidate(
                    claim_id="claim-1",
                    run_id="run-1",
                    text="updates value",
                    source_hunks=[SourceHunk(file="src/app.py", start=1, end=1)],
                )
            ],
            overwrite=True,
        )
    assert output_path.read_text(encoding="utf-8") == '{"original":true}\n'
    assert not temp_path.exists()


def test_gate3_routes_return_structured_errors_and_validate_query_params(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".ahadiff"
    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )

    bad_run = client.get("/api/run/run_not_hex")
    missing_run = client.get("/api/run/run-1")
    bad_page_size = client.get("/api/runs?page_size=0")
    bad_cursor = client.get("/api/runs?cursor=not-a-valid-cursor")

    assert bad_run.status_code == 400
    assert bad_run.json()["status"] == 400
    assert missing_run.status_code == 404
    assert missing_run.json()["status"] == 404
    assert bad_page_size.status_code == 400
    assert bad_page_size.json()["status"] == 400
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["status"] == 400


def test_gate3_claim_parse_rejects_nan_infinity() -> None:
    nan_json = json.dumps(
        [
            {
                "claim_id": "c1",
                "run_id": "r1",
                "text": "some claim",
                "source_hunks": [{"file": "a.py", "start": 1, "end": 2, "side": "new"}],
            }
        ]
    ).replace('"start": 1', '"start": NaN')

    with pytest.raises(InputError, match="invalid claim candidate JSONL line 1"):
        parse_claim_candidates_text(nan_json, default_run_id="r1")

    inf_json = (
        '{"claim_id":"c1","run_id":"r1","text":"x",'
        '"source_hunks":[{"file":"a.py","start":Infinity,"end":2,"side":"new"}]}'
    )
    with pytest.raises(InputError, match="invalid claim candidate JSONL line 1"):
        parse_claim_candidates_text(inf_json, default_run_id="r1")

    overflow_json = (
        '{"claim_id":"c1","run_id":"r1","text":"x",'
        '"source_hunks":[{"file":"a.py","start":1e309,"end":2,"side":"new"}]}'
    )
    with pytest.raises(InputError, match="invalid claim candidate JSONL line 1"):
        parse_claim_candidates_text(overflow_json, default_run_id="r1")
