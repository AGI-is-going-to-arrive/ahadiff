from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from ahadiff.contracts import QuizChoice
from ahadiff.core.errors import InputError
from ahadiff.quiz.distractor_gate import build_distractor_gate_report, write_distractor_gate_report
from ahadiff.quiz.schemas import QuizQuestion

if TYPE_CHECKING:
    from pathlib import Path


def _choice(label: str, text: str, *, correct: bool = False) -> QuizChoice:
    return QuizChoice.model_validate({"label": label, "text": text, "is_correct": correct})


def _question(
    *,
    question_id: str = "quiz_1",
    question: str = "What changed in retry_once?",
    expected_answer: str = "It now retries across attempts.",
    choices: list[QuizChoice] | None = None,
    explanation: str | None = None,
) -> QuizQuestion:
    return QuizQuestion.model_validate(
        {
            "question_id": question_id,
            "question": question,
            "expected_answer": expected_answer,
            "source_claims": ["claim_1"],
            "concepts": ["retry loop"],
            "evidence": [{"file": "src/app.py", "line": 2}],
            "choices": choices
            or [
                {"label": "A", "text": expected_answer, "is_correct": True},
                {"label": "B", "text": "It removes the retry loop.", "is_correct": False},
                {"label": "C", "text": "It only renames a symbol.", "is_correct": False},
                {"label": "D", "text": "It proves exponential backoff.", "is_correct": False},
            ],
            **({"explanation": explanation} if explanation is not None else {}),
        }
    )


def test_distractor_gate_reports_normalized_near_duplicate_choice_text_without_blocking() -> None:
    report = build_distractor_gate_report(
        run_id="run_gate",
        questions=[
            _question(
                choices=[
                    _choice("A", "It now retries across attempts.", correct=True),
                    _choice("B", "It removes the retry loop."),
                    _choice("C", "it removes the retry loop ."),
                    _choice("D", "It proves exponential backoff."),
                ]
            )
        ],
    )

    assert report["mode"] == "advisory"
    assert report["summary"] == {"would_block": 0, "advisory": 1}
    assert report["findings"][0]["rule"] == "D1_duplicate_choice_text"
    assert report["findings"][0]["would_block"] is False
    assert report["findings"][0]["severity"] == "advisory"
    assert report["findings"][0].get("would_block_locked_reason") == ("no_historical_fp_fixture")
    assert report["findings"][0]["evidence"] == {"choice_labels": ["B", "C"]}


def test_distractor_gate_reports_all_none_phrasing() -> None:
    report = build_distractor_gate_report(
        run_id="run_gate",
        questions=[
            _question(
                choices=[
                    _choice("A", "It now retries across attempts.", correct=True),
                    _choice("B", "All of the above"),
                    _choice("C", "It only renames a symbol."),
                    _choice("D", "None of the above"),
                ]
            )
        ],
    )

    finding = report["findings"][0]
    assert finding["rule"] == "D2_all_none_phrasing"
    assert finding["evidence"] == {"choice_labels": ["B", "D"]}
    assert finding["would_block"] is False
    assert finding.get("would_block_locked_reason") == "no_historical_fp_fixture"


def test_distractor_gate_reports_correct_answer_label_leakage() -> None:
    report = build_distractor_gate_report(
        run_id="run_gate",
        questions=[
            _question(
                question="Which option is correct? The correct answer is A.",
            )
        ],
    )

    assert report["findings"][0]["rule"] == "D3_correct_answer_leakage"
    assert report["findings"][0]["evidence"] == {"sources": ["question"]}


def test_distractor_gate_reports_zh_correct_answer_label_leakage() -> None:
    report = build_distractor_gate_report(
        run_id="run_gate",
        questions=[
            _question(question="哪个选项正确？答案是 A。"),
            _question(question="哪个选项正确？答案是Ｂ。"),
        ],
    )

    assert [finding["rule"] for finding in report["findings"]] == [
        "D3_correct_answer_leakage",
        "D3_correct_answer_leakage",
    ]
    assert [finding["evidence"] for finding in report["findings"]] == [
        {"sources": ["question"]},
        {"sources": ["question"]},
    ]


def test_distractor_gate_does_not_flag_staged_unstaged_axis_choices() -> None:
    report = build_distractor_gate_report(
        run_id="run_gate",
        questions=[
            _question(
                question="Which command captures the unstaged changes?",
                expected_answer="ahadiff learn --unstaged",
                choices=[
                    _choice("A", "ahadiff learn --unstaged", correct=True),
                    _choice("B", "ahadiff learn --staged"),
                    _choice("C", "ahadiff learn --last"),
                    _choice("D", "ahadiff learn --since '2 hours ago'"),
                ],
            )
        ],
    )

    assert report["findings"] == []
    assert report["summary"] == {"would_block": 0, "advisory": 0}


def test_distractor_gate_does_not_flag_benign_none_inside_code_text() -> None:
    report = build_distractor_gate_report(
        run_id="run_gate",
        questions=[
            _question(
                expected_answer="Return None when no cache entry exists.",
                choices=[
                    _choice("A", "Return None when no cache entry exists.", correct=True),
                    _choice("B", "Raise KeyError for every miss."),
                    _choice("C", "Write a default object to disk."),
                    _choice("D", "Skip the lookup entirely."),
                ],
            )
        ],
    )

    assert report["findings"] == []


def test_distractor_gate_does_not_flag_zh_all_none_phrase_inside_code_string() -> None:
    report = build_distractor_gate_report(
        run_id="run_gate",
        questions=[
            _question(
                expected_answer='代码返回字符串 "未命中缓存"。',
                choices=[
                    _choice("A", '代码返回字符串 "未命中缓存"。', correct=True),
                    _choice("B", '代码返回字符串 "以上皆非"。'),
                    _choice("C", "抛出 KeyError。"),
                    _choice("D", "跳过缓存读取。"),
                ],
            )
        ],
    )

    assert report["findings"] == []


def test_distractor_gate_reports_multilingual_all_none_phrasing() -> None:
    report = build_distractor_gate_report(
        run_id="run_gate",
        questions=[
            _question(
                expected_answer="新增重试循环。",
                choices=[
                    _choice("A", "新增重试循环。", correct=True),
                    _choice("B", "以上皆非"),
                    _choice("C", "只重命名变量。"),
                    _choice("D", "删除异常处理。"),
                ],
            )
        ],
    )

    assert report["findings"][0]["rule"] == "D2_all_none_phrasing"
    assert report["findings"][0]["evidence"] == {"choice_labels": ["B"]}


def test_distractor_gate_report_redacts_provider_error_like_identifiers() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    report = build_distractor_gate_report(
        run_id="run_gate",
        questions=[
            _question(
                question_id=f'/Users/alice/project/{secret}/{{"raw":"json"}}',
                choices=[
                    _choice("A", "It now retries across attempts.", correct=True),
                    _choice("B", "All of the above"),
                    _choice("C", "It only renames a symbol."),
                    _choice("D", "It proves exponential backoff."),
                ],
            )
        ],
    )
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)

    assert secret not in encoded
    assert "/Users/alice" not in encoded
    assert '{"raw":"json"}' not in encoded
    assert report["findings"][0]["question_id"] == "question_1"


def test_distractor_gate_never_marks_findings_would_block_without_historical_fp_fixture() -> None:
    report = build_distractor_gate_report(
        run_id="run_gate",
        questions=[
            _question(
                question_id="quiz_duplicate",
                choices=[
                    _choice("A", "It now retries across attempts.", correct=True),
                    _choice("B", "It removes the retry loop."),
                    _choice("C", "it removes the retry loop ."),
                    _choice("D", "It proves exponential backoff."),
                ],
            ),
            _question(
                question_id="quiz_all_none",
                choices=[
                    _choice("A", "It now retries across attempts.", correct=True),
                    _choice("B", "None of the above"),
                    _choice("C", "It only renames a symbol."),
                    _choice("D", "It proves exponential backoff."),
                ],
            ),
            _question(question_id="quiz_leak", question="Which option is correct? Answer is A."),
            _question(
                question_id="quiz_true_false",
                expected_answer="True",
                choices=[
                    _choice("A", "True", correct=True),
                    _choice("B", "False"),
                    _choice("C", "Yes"),
                    _choice("D", "No"),
                ],
            ),
        ],
    )

    assert {finding["rule"] for finding in report["findings"]} == {
        "D1_duplicate_choice_text",
        "D2_all_none_phrasing",
        "D3_correct_answer_leakage",
        "D4_true_false_options",
    }
    assert all(finding["would_block"] is False for finding in report["findings"])
    assert all(finding["severity"] == "advisory" for finding in report["findings"])
    locked_findings = [
        finding for finding in report["findings"] if finding["rule"].startswith(("D1_", "D2_"))
    ]
    assert locked_findings
    assert all(
        finding.get("would_block_locked_reason") == "no_historical_fp_fixture"
        for finding in locked_findings
    )


def test_write_distractor_gate_report_rejects_symlink_parent(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not available on this platform")

    run_dir = tmp_path / ".ahadiff" / "runs" / "run_gate"
    outside = tmp_path / "outside"
    run_dir.mkdir(parents=True)
    outside.mkdir()
    try:
        (run_dir / "quiz").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation failed: {exc}")
    report = build_distractor_gate_report(run_id="run_gate", questions=[_question()])

    with pytest.raises(InputError, match="symlink"):
        write_distractor_gate_report(run_dir / "quiz" / "distractor_gate.json", report)

    assert not (outside / "distractor_gate.json").exists()
    assert list(outside.iterdir()) == []


def test_write_distractor_gate_report_cleans_temp_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / ".ahadiff" / "runs" / "run_gate" / "quiz" / "distractor_gate.json"
    report = build_distractor_gate_report(run_id="run_gate", questions=[_question()])

    def fail_replace(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("ahadiff.quiz.distractor_gate.replace_with_retry", fail_replace)

    with pytest.raises(OSError, match="disk full"):
        write_distractor_gate_report(path, report)

    assert list(path.parent.glob(".distractor_gate.json.*.tmp")) == []
