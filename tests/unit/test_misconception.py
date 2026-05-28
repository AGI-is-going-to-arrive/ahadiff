from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ahadiff.core.errors import InputError
from ahadiff.quiz.misconception import (
    MisconceptionCard,
    build_misconception_prompt_payload,
    load_misconception_cards,
    load_misconception_prompt,
    parse_misconception_cards,
    write_misconception_cards,
)


def _make_raw_card(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "concept": "null pointer dereference",
        "misconception": "Optional values are always safe to unwrap",
        "correction": "Optional values must be checked before unwrapping",
        "evidence_ref": "src/main.py:42",
        "severity": "high",
        "safety_tags": ["memory_safety"],
        "card_id": "misc_abc123",
        "run_id": "run_001",
    }
    base.update(overrides)
    return base


def _make_valid_json(cards: list[dict[str, object]] | None = None) -> str:
    if cards is None:
        cards = [_make_raw_card()]
    return json.dumps(cards)


class TestParseMisconceptionCards:
    def test_parse_single_card(self) -> None:
        raw = _make_valid_json()
        cards = parse_misconception_cards(raw)
        assert len(cards) == 1
        card = cards[0]
        assert card.concept == "null pointer dereference"
        assert card.misconception == "Optional values are always safe to unwrap"
        assert card.correction == "Optional values must be checked before unwrapping"
        assert card.evidence_ref == "src/main.py:42"
        assert card.severity == "high"
        assert card.safety_tags == ("memory_safety",)
        assert card.run_id == "run_001"

    def test_parse_multiple_cards(self) -> None:
        raw = _make_valid_json(
            [
                _make_raw_card(concept="A", card_id="c1"),
                _make_raw_card(concept="B", card_id="c2"),
            ]
        )
        cards = parse_misconception_cards(raw)
        assert len(cards) == 2
        assert cards[0].concept == "A"
        assert cards[1].concept == "B"

    def test_parse_unwraps_provider_output_cards(self) -> None:
        raw = json.dumps({"output": {"cards": [_make_raw_card(concept="wrapped")]}})

        cards = parse_misconception_cards(raw)

        assert len(cards) == 1
        assert cards[0].concept == "wrapped"

    def test_parse_unwraps_escaped_output_string(self) -> None:
        raw = json.dumps({"output": json.dumps({"cards": [_make_raw_card(concept="escaped")]})})

        cards = parse_misconception_cards(raw)

        assert len(cards) == 1
        assert cards[0].concept == "escaped"

    def test_parse_scans_prose_for_wrapped_cards(self) -> None:
        raw = (
            "Here are the misconception cards:\n"
            + json.dumps({"output": {"cards": [_make_raw_card(concept="prose")]}})
            + "\nUse these for review."
        )

        cards = parse_misconception_cards(raw)

        assert len(cards) == 1
        assert cards[0].concept == "prose"

    def test_parse_invalid_json_returns_empty(self) -> None:
        assert parse_misconception_cards("{not json") == []

    def test_parse_non_array_returns_empty(self) -> None:
        assert parse_misconception_cards('{"key": "value"}') == []

    def test_parse_non_object_element_skipped(self) -> None:
        assert parse_misconception_cards('["not an object"]') == []

    def test_parse_missing_required_key_skipped(self) -> None:
        incomplete = {"concept": "x"}
        assert parse_misconception_cards(json.dumps([incomplete])) == []

    def test_auto_generated_card_id(self) -> None:
        card_dict = _make_raw_card()
        del card_dict["card_id"]
        raw = json.dumps([card_dict])
        cards = parse_misconception_cards(raw)
        assert cards[0].card_id.startswith("misc_")

    def test_non_string_card_id_skipped(self) -> None:
        raw = _make_valid_json([_make_raw_card(card_id=["bad"])])
        assert parse_misconception_cards(raw) == []

    def test_non_string_run_id_skipped(self) -> None:
        raw = _make_valid_json([_make_raw_card(run_id={"bad": True})])
        assert parse_misconception_cards(raw) == []


class TestSeverityValidation:
    @pytest.mark.parametrize("severity", ["low", "medium", "high"])
    def test_valid_severities(self, severity: str) -> None:
        raw = _make_valid_json([_make_raw_card(severity=severity)])
        cards = parse_misconception_cards(raw)
        assert cards[0].severity == severity

    def test_invalid_severity_skipped(self) -> None:
        raw = _make_valid_json([_make_raw_card(severity="critical")])
        assert parse_misconception_cards(raw) == []


class TestSafetyTags:
    def test_empty_safety_tags(self) -> None:
        raw = _make_valid_json([_make_raw_card(safety_tags=[])])
        cards = parse_misconception_cards(raw)
        assert cards[0].safety_tags == ()

    def test_multiple_safety_tags(self) -> None:
        raw = _make_valid_json([_make_raw_card(safety_tags=["security", "injection", "overflow"])])
        cards = parse_misconception_cards(raw)
        assert cards[0].safety_tags == ("security", "injection", "overflow")

    def test_non_list_safety_tags_skipped(self) -> None:
        raw = _make_valid_json([_make_raw_card(safety_tags="not_a_list")])
        assert parse_misconception_cards(raw) == []

    def test_non_string_safety_tag_element_skipped(self) -> None:
        raw = _make_valid_json([_make_raw_card(safety_tags=["security", 42])])
        assert parse_misconception_cards(raw) == []

    def test_default_empty_safety_tags(self) -> None:
        card_dict = _make_raw_card()
        del card_dict["safety_tags"]
        raw = json.dumps([card_dict])
        cards = parse_misconception_cards(raw)
        assert cards[0].safety_tags == ()


class TestNonEmptyStringValidation:
    @pytest.mark.parametrize("field", ["concept", "misconception", "correction", "evidence_ref"])
    def test_empty_string_skipped(self, field: str) -> None:
        raw = _make_valid_json([_make_raw_card(**{field: ""})])
        assert parse_misconception_cards(raw) == []

    @pytest.mark.parametrize("field", ["concept", "misconception", "correction", "evidence_ref"])
    def test_whitespace_only_skipped(self, field: str) -> None:
        raw = _make_valid_json([_make_raw_card(**{field: "   "})])
        assert parse_misconception_cards(raw) == []

    @pytest.mark.parametrize("field", ["concept", "misconception", "correction", "evidence_ref"])
    def test_non_string_skipped(self, field: str) -> None:
        raw = _make_valid_json([_make_raw_card(**{field: 42})])
        assert parse_misconception_cards(raw) == []


class TestWriteAndLoadRoundTrip:
    def test_roundtrip(self, tmp_path: Path) -> None:
        cards = [
            MisconceptionCard(
                card_id="misc_001",
                concept="SQL injection",
                misconception="String concatenation in queries is safe",
                correction="Always use parameterized queries",
                evidence_ref="db/query.py:15",
                severity="high",
                safety_tags=("security", "injection"),
                run_id="run_abc",
            ),
            MisconceptionCard(
                card_id="misc_002",
                concept="error handling",
                misconception="Catching all exceptions is best practice",
                correction="Catch specific exception types",
                evidence_ref="app/main.py:88",
                severity="medium",
                safety_tags=(),
                run_id="run_abc",
            ),
        ]
        output_path = tmp_path / "misconceptions.jsonl"
        write_misconception_cards(cards, output_path)
        loaded = load_misconception_cards(output_path)
        assert len(loaded) == 2
        assert loaded[0].card_id == "misc_001"
        assert loaded[0].concept == "SQL injection"
        assert loaded[0].safety_tags == ("security", "injection")
        assert loaded[1].card_id == "misc_002"
        assert loaded[1].safety_tags == ()

    def test_load_nonexistent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(InputError, match="does not exist"):
            load_misconception_cards(tmp_path / "missing.jsonl")

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        cards = [
            MisconceptionCard(
                card_id="misc_x",
                concept="c",
                misconception="m",
                correction="r",
                evidence_ref="f:1",
                severity="low",
                safety_tags=(),
                run_id="run_1",
            ),
        ]
        output_path = tmp_path / "sub" / "dir" / "cards.jsonl"
        write_misconception_cards(cards, output_path)
        assert output_path.exists()


class TestBuildMisconceptionPromptPayload:
    def test_basic_payload(self) -> None:
        result = build_misconception_prompt_payload(
            concept_terms=["async", "await"],
            diff_text="+ async def fetch():",
            run_id="run_xyz",
        )
        assert result["concept_terms"] == ["async", "await"]
        assert result["diff_summary"] == "+ async def fetch():"
        assert result["run_id"] == "run_xyz"

    def test_diff_truncation(self) -> None:
        long_diff = "x" * 20_000
        result = build_misconception_prompt_payload(
            concept_terms=["big"],
            diff_text=long_diff,
            run_id="run_t",
        )
        assert len(str(result["diff_summary"])) == 8 * 1024

    def test_empty_diff(self) -> None:
        result = build_misconception_prompt_payload(
            concept_terms=["x"],
            diff_text="",
            run_id="run_e",
        )
        assert result["diff_summary"] == ""

    def test_empty_concepts(self) -> None:
        result = build_misconception_prompt_payload(
            concept_terms=[],
            diff_text="some diff",
            run_id="run_c",
        )
        assert result["concept_terms"] == []


def test_load_misconception_prompt_reads_prompt_resource() -> None:
    prompt_text = load_misconception_prompt()

    assert "Respond with a JSON object with a `cards` array" in prompt_text
    assert "run_id" in prompt_text


class TestMisconceptionCardFrozen:
    def test_frozen_dataclass(self) -> None:
        card = MisconceptionCard(
            card_id="misc_f",
            concept="c",
            misconception="m",
            correction="r",
            evidence_ref="f:1",
            severity="low",
            safety_tags=(),
            run_id="run_1",
        )
        with pytest.raises(AttributeError):
            card.concept = "changed"  # type: ignore[misc]
