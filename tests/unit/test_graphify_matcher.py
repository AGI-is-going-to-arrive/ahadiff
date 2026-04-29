"""Tests for graphify fuzzy concept matcher (Phase 5A)."""

from __future__ import annotations

import pytest

from ahadiff.graphify.matcher import match_concepts, similarity


class TestSimilarity:
    def test_exact_match(self) -> None:
        assert similarity("asyncio", "asyncio") == 1.0

    def test_case_insensitive(self) -> None:
        assert similarity("AsyncIO", "asyncio") == 1.0

    def test_nfkc_normalization(self) -> None:
        assert similarity("café", "café") == 1.0

    def test_underscore_split(self) -> None:
        score = similarity("task_runner", "TaskRunner")
        assert score > 0.0

    def test_partial_token_overlap(self) -> None:
        score = similarity("task_runner", "task_manager")
        assert 0.0 < score < 1.0

    def test_no_overlap(self) -> None:
        assert similarity("alpha", "omega") == 0.0

    def test_containment_boost(self) -> None:
        score = similarity("run", "task_runner")
        assert score > 0.0

    def test_empty_strings(self) -> None:
        assert similarity("", "") == 0.0

    def test_one_empty(self) -> None:
        assert similarity("foo", "") == 0.0

    def test_path_like_label(self) -> None:
        score = similarity("capture", "src/ahadiff/git/capture.py")
        assert score > 0.0

    def test_hyphen_split(self) -> None:
        score = similarity("co-change", "co_change")
        assert score > 0.5

    def test_zero_width_chars_stripped(self) -> None:
        assert similarity("foobar", "foo​bar") == 1.0

    def test_control_chars_stripped(self) -> None:
        assert similarity("test", "te\x00st") == 1.0

    def test_zero_width_chars_do_not_break_token_overlap(self) -> None:
        score = similarity("parse graph json", "parse\u200b_graph\x00_json")
        assert score > 0.5

    def test_zero_width_chars_do_not_break_containment(self) -> None:
        assert similarity("task runner", "task\u200brunner") == 1.0


class TestMatchConcepts:
    def test_basic_match(self) -> None:
        results = match_concepts("asyncio", ["asyncio", "threading", "multiprocessing"])
        assert len(results) >= 1
        assert results[0][0] == "asyncio"
        assert results[0][1] == 1.0

    def test_threshold_filters(self) -> None:
        results = match_concepts("alpha", ["omega", "beta", "gamma"], threshold=0.5)
        assert results == []

    def test_max_results_limit(self) -> None:
        candidates = [f"task_{i}" for i in range(20)]
        results = match_concepts("task", candidates, threshold=0.1, max_results=3)
        assert len(results) <= 3

    def test_empty_concept(self) -> None:
        assert match_concepts("", ["foo", "bar"]) == []

    def test_whitespace_only_concept(self) -> None:
        assert match_concepts("   ", ["foo", "bar"], threshold=0.0) == []

    def test_empty_candidates(self) -> None:
        assert match_concepts("foo", []) == []

    def test_sorted_by_score_descending(self) -> None:
        results = match_concepts(
            "task_runner",
            ["task_runner", "task_manager", "event_loop"],
            threshold=0.1,
        )
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.parametrize(
        ("concept", "candidate", "expected_match"),
        [
            ("GraphifyNode", "graphify_node", True),
            ("parse_graph_json", "parse_graph_json_text", True),
            ("FreshnessState", "freshness_state", True),
            ("totally_unrelated", "completely_different", False),
        ],
    )
    def test_real_codebase_names(self, concept: str, candidate: str, expected_match: bool) -> None:
        results = match_concepts(concept, [candidate], threshold=0.4)
        assert (len(results) > 0) == expected_match
