"""Tests for MCP ask_lesson tool and the lesson fragment search helper."""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, Any

import pytest

from ahadiff.contracts import ErrorCode
from ahadiff.core.errors import InputError
from ahadiff.mcp._lesson_search import (  # pyright: ignore[reportPrivateUsage]
    DEFAULT_TOP_K,
    MAX_QUESTION_LENGTH,
    MAX_TOP_K,
    bounded_top_k,
    evidence_for_fragments,
    score_fragments,
    search_lesson,
    split_lesson_fragments,
    tokenize_query,
    validate_question,
)
from ahadiff.mcp.server import (
    _ask_lesson,  # pyright: ignore[reportPrivateUsage]
    _tool_handlers,  # pyright: ignore[reportPrivateUsage]
    create_mcp_server,
)

if TYPE_CHECKING:
    from pathlib import Path


_SAMPLE_LESSON = """## TL;DR
This change adds a new feature.

## What Changed
- Added function foo to module bar.
- Updated tests for baz.

### Edge cases
- Handles empty inputs.

## Why
- Improves throughput by 2x.
"""


def _write_run(
    state_dir: Path,
    run_id: str,
    *,
    lesson_full: str | None = None,
    lesson_hint: str | None = None,
    lesson_compact: str | None = None,
    claims: list[dict[str, Any]] | None = None,
    finalized: bool = True,
) -> None:
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if finalized:
        (run_dir / "finalized.json").write_text("{}\n", encoding="utf-8")
    if lesson_full is not None or lesson_hint is not None or lesson_compact is not None:
        lesson_dir = run_dir / "lesson"
        lesson_dir.mkdir(parents=True, exist_ok=True)
        if lesson_full is not None:
            (lesson_dir / "lesson.full.md").write_text(lesson_full, encoding="utf-8")
        if lesson_hint is not None:
            (lesson_dir / "lesson.hint.md").write_text(lesson_hint, encoding="utf-8")
        if lesson_compact is not None:
            (lesson_dir / "lesson.compact.md").write_text(lesson_compact, encoding="utf-8")
    if claims is not None:
        with (run_dir / "claims.jsonl").open("w", encoding="utf-8") as fh:
            for claim in claims:
                fh.write(json.dumps(claim, ensure_ascii=False, sort_keys=True) + "\n")


def _claim(
    claim_id: str,
    text: str,
    *,
    status: str = "verified",
    confidence: str = "high",
    source_hunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "run_id": "run_ABC",
        "text": text,
        "status": status,
        "confidence": confidence,
        "source_hunks": source_hunks
        or [
            {
                "file": "src/foo.py",
                "start": 10,
                "end": 20,
                "side": "new",
                "hunk_id": f"hunk_{claim_id}",
            }
        ],
        "symbols": [],
        "negative_evidence": [],
        "reason_code": None,
        "extractor": "regex",
    }


# ---------------------------------------------------------------------------
# split_lesson_fragments
# ---------------------------------------------------------------------------


class TestLessonFragmentSplitter:
    def test_split_by_h2_headings(self) -> None:
        text = "## A\nbody-a\n## B\nbody-b\n"
        fragments = split_lesson_fragments(text)
        assert [f["heading"] for f in fragments] == ["A", "B"]
        assert [f["body"] for f in fragments] == ["body-a", "body-b"]
        assert [f["section_id"] for f in fragments] == [0, 1]

    def test_split_by_h3_headings(self) -> None:
        text = "## Section\nintro\n### Sub A\nsub-a body\n### Sub B\nsub-b body\n"
        fragments = split_lesson_fragments(text)
        headings = [f["heading"] for f in fragments]
        assert "Section" in headings
        assert "Sub A" in headings
        assert "Sub B" in headings

    def test_fragment_truncation_at_max_chars(self) -> None:
        body = "x" * 2000
        text = f"## Long\n{body}\n"
        fragments = split_lesson_fragments(text, max_chars=100)
        assert len(fragments) == 1
        assert len(fragments[0]["body"]) == 100  # type: ignore[arg-type]

    def test_empty_lesson_returns_empty(self) -> None:
        assert split_lesson_fragments("") == []

    def test_preamble_before_first_heading_is_kept(self) -> None:
        text = "preamble line\n## Heading\nbody\n"
        fragments = split_lesson_fragments(text)
        assert fragments[0]["heading"] == ""
        assert "preamble line" in str(fragments[0]["body"])

    def test_invalid_max_chars_raises(self) -> None:
        with pytest.raises(ValueError, match="max_chars"):
            split_lesson_fragments("## A\n", max_chars=0)


# ---------------------------------------------------------------------------
# tokenize_query
# ---------------------------------------------------------------------------


class TestTokenizer:
    def test_basic_tokenize(self) -> None:
        tokens = tokenize_query("Hello World")
        assert tokens == {"hello", "world"}

    def test_stopwords_removed(self) -> None:
        tokens = tokenize_query("the quick brown fox")
        assert "the" not in tokens
        assert {"quick", "brown", "fox"}.issubset(tokens)

    def test_non_ascii_query(self) -> None:
        tokens = tokenize_query("中文测试 query")
        assert "query" in tokens
        assert any("中文" in t or "中文测试" in t for t in tokens)

    def test_regex_like_query_treated_as_literal(self) -> None:
        # Should not crash or trigger pattern compilation; punctuation is treated as separators.
        tokens = tokenize_query(".*+(?=evil)[a-z]{1,1000}")
        # No special-character tokens slip through; only alphanumeric runs remain.
        for tok in tokens:
            assert not any(ch in tok for ch in ".*+()=[]{}")

    def test_long_punctuation_string_is_safe(self) -> None:
        # A long punctuation-only string should produce no tokens and complete quickly.
        weird = "?!." * 10_000
        assert tokenize_query(weird) == set()

    def test_empty_string_returns_empty_set(self) -> None:
        assert tokenize_query("") == set()


# ---------------------------------------------------------------------------
# score_fragments
# ---------------------------------------------------------------------------


class TestScoring:
    def test_exact_heading_match_scores_highest(self) -> None:
        fragments = split_lesson_fragments(_SAMPLE_LESSON)
        query_tokens = tokenize_query("What Changed")
        scored = score_fragments(query_tokens, fragments)
        assert str(scored[0]["heading"]) == "What Changed"
        assert float(scored[0]["score"]) > 0.0

    def test_multi_fragment_ranking(self) -> None:
        fragments = split_lesson_fragments(_SAMPLE_LESSON)
        query_tokens = tokenize_query("throughput improves")
        scored = score_fragments(query_tokens, fragments)
        # "Why" fragment mentions both 'improves' and 'throughput'.
        assert str(scored[0]["heading"]) == "Why"

    def test_empty_query_returns_zero_scores(self) -> None:
        fragments = split_lesson_fragments(_SAMPLE_LESSON)
        scored = score_fragments(set(), fragments)
        assert all(float(item["score"]) == 0.0 for item in scored)

    def test_ties_broken_by_section_id_ascending(self) -> None:
        fragments = [
            {"section_id": 1, "heading": "A", "body": "foo"},
            {"section_id": 0, "heading": "B", "body": "foo"},
        ]
        scored = score_fragments({"foo"}, fragments)
        assert int(scored[0]["section_id"]) == 0


# ---------------------------------------------------------------------------
# search_lesson and helpers
# ---------------------------------------------------------------------------


class TestSearchLessonAndHelpers:
    def test_search_lesson_returns_top_k(self) -> None:
        results = search_lesson(_SAMPLE_LESSON, "What Changed", top_k=2)
        assert len(results) == 2

    def test_search_lesson_zero_top_k_returns_empty(self) -> None:
        assert search_lesson(_SAMPLE_LESSON, "foo", top_k=0) == []

    def test_search_lesson_negative_top_k_raises(self) -> None:
        with pytest.raises(ValueError, match="top_k"):
            search_lesson(_SAMPLE_LESSON, "foo", top_k=-1)

    def test_validate_question_strips_and_returns(self) -> None:
        assert validate_question("  hi  ") == "hi"

    def test_validate_question_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="required"):
            validate_question("   ")

    def test_validate_question_rejects_oversized(self) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            validate_question("x" * (MAX_QUESTION_LENGTH + 1))

    def test_bounded_top_k_clamps_high(self) -> None:
        assert bounded_top_k(999) == MAX_TOP_K

    def test_bounded_top_k_clamps_low(self) -> None:
        assert bounded_top_k(-5) == 1

    def test_bounded_top_k_falls_back_to_default_on_garbage(self) -> None:
        assert bounded_top_k("hello") == DEFAULT_TOP_K
        assert bounded_top_k(None) == DEFAULT_TOP_K
        assert bounded_top_k(True) == DEFAULT_TOP_K


# ---------------------------------------------------------------------------
# evidence_for_fragments
# ---------------------------------------------------------------------------


class TestEvidenceJoin:
    def test_evidence_joins_by_token_overlap(self) -> None:
        fragments = [{"section_id": 0, "heading": "Truncation banner", "body": ""}]
        claims = [_claim("c-1", "Adds large file truncation banner styles to Diff CSS.")]
        evidence = evidence_for_fragments(fragments, claims, min_matched_tokens=1)
        assert len(evidence) == 1
        assert evidence[0]["claim_id"] == "c-1"

    def test_evidence_skips_no_overlap(self) -> None:
        fragments = [{"section_id": 0, "heading": "Truncation banner", "body": ""}]
        claims = [_claim("c-1", "completely unrelated text about networking")]
        assert evidence_for_fragments(fragments, claims, min_matched_tokens=1) == []

    def test_evidence_per_fragment_limit(self) -> None:
        fragments = [{"section_id": 0, "heading": "foo bar", "body": ""}]
        claims = [_claim(f"c-{i}", "foo bar baz") for i in range(50)]
        evidence = evidence_for_fragments(fragments, claims, per_fragment_limit=5, total_limit=100)
        assert len(evidence) == 5

    def test_evidence_total_limit(self) -> None:
        fragments = [{"section_id": i, "heading": f"foo bar {i}", "body": ""} for i in range(5)]
        claims = [_claim(f"c-{i}", "foo bar match") for i in range(30)]
        evidence = evidence_for_fragments(fragments, claims, per_fragment_limit=20, total_limit=20)
        assert len(evidence) == 20


# ---------------------------------------------------------------------------
# ask_lesson tool registration and call_tool integration
# ---------------------------------------------------------------------------


class TestAskLessonTool:
    def test_tool_registered_as_seventh(self, tmp_path: Path) -> None:
        server = create_mcp_server(tmp_path)
        # We need to drive the registered list_tools to actually fetch the list.
        # The list_tools handler is registered onto the server but is hidden; we
        # can introspect via the handlers dict directly.
        handlers = _tool_handlers(tmp_path, tmp_path / "review.sqlite")
        assert "ask_lesson" in handlers
        assert len(handlers) == 7
        assert server is not None

    def test_existing_six_tools_unchanged(self, tmp_path: Path) -> None:
        handlers = _tool_handlers(tmp_path, tmp_path / "review.sqlite")
        expected = {
            "list_runs",
            "get_run_summary",
            "list_due_cards",
            "search",
            "get_concepts",
            "get_stats",
            "ask_lesson",
        }
        assert set(handlers.keys()) == expected

    def test_missing_run_returns_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(InputError) as excinfo:
            _ask_lesson(tmp_path, {"run_id": "run_missing", "question": "anything"})
        assert excinfo.value.code == ErrorCode.RUN_NOT_FOUND

    def test_oversized_question_returns_validation_error(self, tmp_path: Path) -> None:
        _write_run(tmp_path, "run_OK", lesson_full=_SAMPLE_LESSON)
        with pytest.raises(InputError) as excinfo:
            _ask_lesson(
                tmp_path,
                {"run_id": "run_OK", "question": "x" * (MAX_QUESTION_LENGTH + 1)},
            )
        assert excinfo.value.code == ErrorCode.INPUT_VALIDATION

    def test_empty_question_returns_validation_error(self, tmp_path: Path) -> None:
        _write_run(tmp_path, "run_OK", lesson_full=_SAMPLE_LESSON)
        with pytest.raises(InputError) as excinfo:
            _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "   "})
        assert excinfo.value.code == ErrorCode.INPUT_VALIDATION

    def test_invalid_run_id_returns_validation_error(self, tmp_path: Path) -> None:
        with pytest.raises(InputError) as excinfo:
            _ask_lesson(tmp_path, {"run_id": "../escape", "question": "what?"})
        assert excinfo.value.code == ErrorCode.INPUT_VALIDATION

    def test_missing_run_id_returns_validation_error(self, tmp_path: Path) -> None:
        with pytest.raises(InputError) as excinfo:
            _ask_lesson(tmp_path, {"question": "what?"})
        assert excinfo.value.code == ErrorCode.INPUT_VALIDATION

    def test_empty_result_returns_empty_fragments(self, tmp_path: Path) -> None:
        _write_run(tmp_path, "run_OK", lesson_full="just preamble\n")
        result = _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "xyz1234567"})
        assert isinstance(result["fragments"], list)
        assert result["evidence"] == []
        assert result["run_meta"]["lesson_file"] == "lesson.full.md"

    def test_missing_lesson_dir_returns_null_lesson_file(self, tmp_path: Path) -> None:
        _write_run(tmp_path, "run_OK")
        result = _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "anything"})
        assert result["fragments"] == []
        assert result["evidence"] == []
        assert result["run_meta"] == {"run_id": "run_OK", "lesson_file": None}

    def test_lesson_full_preferred_over_hint_and_compact(self, tmp_path: Path) -> None:
        _write_run(
            tmp_path,
            "run_OK",
            lesson_full=_SAMPLE_LESSON,
            lesson_hint="## Hint\nbody\n",
            lesson_compact="## Compact\nbody\n",
        )
        result = _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "throughput"})
        assert result["run_meta"]["lesson_file"] == "lesson.full.md"

    def test_falls_back_to_hint_when_full_absent(self, tmp_path: Path) -> None:
        _write_run(tmp_path, "run_OK", lesson_hint="## Hint\nbody\n")
        result = _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "body"})
        assert result["run_meta"]["lesson_file"] == "lesson.hint.md"

    def test_falls_back_to_compact_when_full_and_hint_absent(self, tmp_path: Path) -> None:
        _write_run(tmp_path, "run_OK", lesson_compact="## Compact\nbody\n")
        result = _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "body"})
        assert result["run_meta"]["lesson_file"] == "lesson.compact.md"

    def test_top_k_respects_limit(self, tmp_path: Path) -> None:
        lesson = "\n".join(f"## Section {i}\nbody {i}" for i in range(15))
        _write_run(tmp_path, "run_OK", lesson_full=lesson)
        result = _ask_lesson(
            tmp_path,
            {"run_id": "run_OK", "question": "section body", "top_k": 5},
        )
        assert len(result["fragments"]) == 5

    def test_top_k_clamped_at_max(self, tmp_path: Path) -> None:
        lesson = "\n".join(f"## Section {i}\nbody {i}" for i in range(20))
        _write_run(tmp_path, "run_OK", lesson_full=lesson)
        result = _ask_lesson(
            tmp_path,
            {"run_id": "run_OK", "question": "section body", "top_k": 999},
        )
        assert len(result["fragments"]) <= MAX_TOP_K

    def test_all_five_claim_statuses_in_evidence(self, tmp_path: Path) -> None:
        claims = [
            _claim("c-1", "foo bar verified evidence", status="verified"),
            _claim("c-2", "foo bar weak evidence", status="weak"),
            _claim("c-3", "foo bar not proven evidence", status="not_proven"),
            _claim("c-4", "foo bar contradicted evidence", status="contradicted"),
            _claim(
                "c-5",
                "foo bar rejected evidence",
                status="rejected",
                confidence="low",
            ),
        ]
        _write_run(
            tmp_path,
            "run_OK",
            lesson_full="## Foo Bar\nbody about foo bar.\n",
            claims=claims,
        )
        result = _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "foo bar"})
        evidence = result["evidence"]
        statuses = {entry["status"] for entry in evidence}
        assert statuses == {"verified", "weak", "not_proven", "contradicted", "rejected"}

    def test_invalid_claims_lines_are_skipped(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run_OK"
        run_dir.mkdir(parents=True)
        (run_dir / "finalized.json").write_text("{}\n", encoding="utf-8")
        lesson_dir = run_dir / "lesson"
        lesson_dir.mkdir(parents=True)
        (lesson_dir / "lesson.full.md").write_text("## Foo\nfoo bar baz\n", encoding="utf-8")
        valid_claim = _claim("c-1", "foo bar baz claim")
        (run_dir / "claims.jsonl").write_text(
            "not-json-line\n"
            + json.dumps(valid_claim, ensure_ascii=False, sort_keys=True)
            + "\n"
            + "{partial\n",
            encoding="utf-8",
        )
        result = _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "foo"})
        evidence = result["evidence"]
        assert len(evidence) == 1
        assert evidence[0]["claim_id"] == "c-1"

    def test_oversized_lesson_is_skipped(self, tmp_path: Path) -> None:
        # Write a >2MB lesson and expect lesson_file None (logged but no crash).
        run_dir = tmp_path / "runs" / "run_OK"
        run_dir.mkdir(parents=True)
        (run_dir / "finalized.json").write_text("{}\n", encoding="utf-8")
        lesson_dir = run_dir / "lesson"
        lesson_dir.mkdir(parents=True)
        (lesson_dir / "lesson.full.md").write_text(
            "## A\n" + ("x" * (2 * 1024 * 1024 + 1)), encoding="utf-8"
        )
        result = _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "anything"})
        assert result["fragments"] == []
        assert result["run_meta"]["lesson_file"] is None

    def test_regex_like_question_is_safe(self, tmp_path: Path) -> None:
        _write_run(tmp_path, "run_OK", lesson_full=_SAMPLE_LESSON)
        # If user-supplied query were compiled as a regex, this would either crash
        # or take exponential time; here it should just return quickly.
        result = _ask_lesson(
            tmp_path,
            {"run_id": "run_OK", "question": "(.+)+evil[^x]*"},
        )
        assert isinstance(result["fragments"], list)

    def test_unfinalized_run_returns_not_found(self, tmp_path: Path) -> None:
        # Run directory exists with lesson + claims, but finalized.json is missing.
        _write_run(
            tmp_path,
            "run_OK",
            lesson_full=_SAMPLE_LESSON,
            finalized=False,
        )
        assert not (tmp_path / "runs" / "run_OK" / "finalized.json").exists()
        with pytest.raises(InputError) as excinfo:
            _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "anything"})
        assert excinfo.value.code == ErrorCode.RUN_NOT_FOUND

    def test_finalized_symlink_is_rejected(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "run_OK"
        run_dir.mkdir(parents=True)
        decoy = tmp_path / "elsewhere.json"
        decoy.write_text("{}\n", encoding="utf-8")
        try:
            (run_dir / "finalized.json").symlink_to(decoy)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        with pytest.raises(InputError) as excinfo:
            _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "anything"})
        assert excinfo.value.code == ErrorCode.RUN_NOT_FOUND

    @pytest.mark.skipif(
        sys.platform == "win32" or not hasattr(os, "mkfifo"),
        reason="POSIX FIFOs are not available on this platform",
    )
    def test_lesson_fifo_is_skipped(self, tmp_path: Path) -> None:
        # Build a finalized run, then replace lesson.full.md with a FIFO. A naive
        # read_bytes() call against a FIFO would block waiting for a writer; the
        # regular-file guard must skip the entry instead.
        _write_run(tmp_path, "run_OK")
        lesson_dir = tmp_path / "runs" / "run_OK" / "lesson"
        lesson_dir.mkdir(parents=True, exist_ok=True)
        fifo_path = lesson_dir / "lesson.full.md"
        os.mkfifo(fifo_path)
        result = _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "anything"})
        assert result["fragments"] == []
        assert result["run_meta"]["lesson_file"] is None

    @pytest.mark.skipif(
        sys.platform == "win32" or not hasattr(os, "mkfifo"),
        reason="POSIX FIFOs are not available on this platform",
    )
    def test_claims_fifo_is_skipped(self, tmp_path: Path) -> None:
        # The lesson is a real file but claims.jsonl is a FIFO; evidence should
        # be empty without the read blocking.
        _write_run(tmp_path, "run_OK", lesson_full=_SAMPLE_LESSON)
        fifo_path = tmp_path / "runs" / "run_OK" / "claims.jsonl"
        os.mkfifo(fifo_path)
        result = _ask_lesson(tmp_path, {"run_id": "run_OK", "question": "throughput"})
        assert result["evidence"] == []
        assert result["run_meta"]["lesson_file"] == "lesson.full.md"
