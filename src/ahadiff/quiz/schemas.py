from __future__ import annotations

import json
import re
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from ahadiff.contracts.quiz_choice import AnswerMode, QuizChoice, validate_quiz_choices

QuizKind = Literal["guided", "recall", "transfer"]


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _normalize_string_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        line = _normalize_text(value)
        if line:
            normalized.append(line)
    return list(dict.fromkeys(normalized))


class QuizEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    line: StrictInt

    @field_validator("file")
    @classmethod
    def validate_file(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("evidence file must not be empty")
        return normalized

    @field_validator("line")
    @classmethod
    def validate_line(cls, value: int) -> int:
        if value < 1:
            raise ValueError("evidence line must be positive")
        return value


class QuizQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str | None = None
    review_card_id: str | None = None
    question: str
    expected_answer: str
    quiz_kind: QuizKind = "recall"
    answer_mode: AnswerMode = "open"
    choices: list[QuizChoice] | None = None
    source_claims: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    evidence: list[QuizEvidence]
    explanation: str | None = None

    @model_validator(mode="before")
    @classmethod
    def infer_answer_mode(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data_map = cast("dict[str, Any]", data)
        if (
            "answer_mode" not in data_map
            and "choices" in data_map
            and data_map.get("choices") is not None
        ):
            return {**data_map, "answer_mode": "multiple_choice"}
        return data_map

    @field_validator("question", "expected_answer")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            raise ValueError("quiz question text must not be empty")
        return normalized

    @field_validator("question_id", "review_card_id")
    @classmethod
    def normalize_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("source_claims", "concepts")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return _normalize_string_list(values)

    @field_validator("explanation")
    @classmethod
    def normalize_explanation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_text(value)
        return normalized or None

    @model_validator(mode="after")
    def validate_links_and_choices(self) -> QuizQuestion:
        if not self.source_claims:
            raise ValueError("quiz question must link to at least one source claim")
        if not self.evidence:
            raise ValueError("quiz question must include at least one evidence anchor")
        if self.choices is None:
            if self.answer_mode == "multiple_choice":
                raise ValueError("multiple_choice quiz questions must include choices")
            return self
        if self.answer_mode != "multiple_choice":
            raise ValueError("quiz choices are only allowed for multiple_choice questions")
        self.choices = list(
            validate_quiz_choices(self.choices, expected_answer=self.expected_answer)
        )
        return self


class QuizSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[QuizQuestion] = Field(..., min_length=1, max_length=30)

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, values: list[QuizQuestion]) -> list[QuizQuestion]:
        if not values:
            raise ValueError("quiz set must contain at least one question")
        return values


class MisconceptionCardOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept: str
    misconception: str
    correction: str
    evidence_ref: str
    severity: str
    safety_tags: list[str]


class MisconceptionCardSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards: list[MisconceptionCardOutput] = Field(..., max_length=30)


def parse_quiz_payload(payload: str, *, require_choices: bool = False) -> QuizSet:
    last_error: Exception | None = None
    for candidate in _extract_json_candidates(payload):
        try:
            if isinstance(candidate, list):
                if not candidate or not isinstance(candidate[0], dict):
                    continue
                if "question" not in candidate[0]:
                    continue
                return _validate_required_choices(
                    QuizSet.model_validate({"questions": candidate}),
                    require_choices=require_choices,
                )
            if isinstance(candidate, dict):
                candidate_map = cast("dict[str, Any]", candidate)
                if "questions" in candidate_map:
                    return _validate_required_choices(
                        QuizSet.model_validate(candidate_map),
                        require_choices=require_choices,
                    )
                required_keys = {"question", "expected_answer", "source_claims", "evidence"}
                if required_keys <= set(candidate_map.keys()):
                    return _validate_required_choices(
                        QuizSet.model_validate({"questions": [candidate_map]}),
                        require_choices=require_choices,
                    )
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise ValueError("payload does not contain a valid quiz JSON object")


def _validate_required_choices(quiz_set: QuizSet, *, require_choices: bool) -> QuizSet:
    if not require_choices:
        return quiz_set
    for question in quiz_set.questions:
        if question.answer_mode != "multiple_choice" or not question.choices:
            raise ValueError("quiz payload must include choices for every question")
    return quiz_set


def _extract_json_candidates(payload: str) -> tuple[Any, ...]:
    stripped = _strip_thinking_blocks(payload.strip()).strip()
    decoder = json.JSONDecoder()
    candidates = [*_iter_fenced_blocks(stripped), stripped]
    first_json = _first_json_start(stripped)
    if first_json >= 0:
        candidates.append(stripped[first_json:])
    parsed_candidates: list[Any] = []
    for candidate in candidates:
        for parsed in _decode_json_values(candidate, decoder):
            _append_json_candidate(parsed_candidates, parsed, decoder)
    indexed_candidates = list(enumerate(parsed_candidates))
    indexed_candidates.sort(key=lambda item: (_candidate_quality(item[1]), item[0]), reverse=True)
    parsed_candidates = [candidate for _, candidate in indexed_candidates]
    return tuple(parsed_candidates)


_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>[\s\S]*?</think>", re.IGNORECASE)


def _strip_thinking_blocks(text: str) -> str:
    return _THINK_BLOCK_RE.sub("", text)


def _first_json_start(text: str) -> int:
    starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
    return min(starts) if starts else -1


def _append_json_candidate(
    candidates: list[Any],
    parsed: Any,
    decoder: json.JSONDecoder,
) -> None:
    candidates.append(parsed)
    if isinstance(parsed, dict):
        parsed_map = cast("dict[str, Any]", parsed)
        output = parsed_map.get("output")
        if isinstance(output, dict | list):
            candidates.append(output)
        elif isinstance(output, str):
            candidates.extend(_decode_json_values(output, decoder))
        for nested_text in _provider_text_fragments(parsed_map):
            candidates.extend(_decode_json_values(nested_text, decoder))


def _candidate_quality(candidate: Any) -> int:
    if isinstance(candidate, dict):
        candidate_map = cast("dict[str, Any]", candidate)
        if isinstance(candidate_map.get("questions"), list):
            questions = cast("list[Any]", candidate_map["questions"])
            return 1000 + len(questions)
        if "question" in candidate_map:
            return 900
        if "output" in candidate_map:
            return 100
        return len(candidate_map)
    if isinstance(candidate, list):
        candidate_items = cast("list[Any]", candidate)
        return 800 + len(candidate_items)
    return 0


def _provider_text_fragments(parsed: dict[str, Any]) -> list[str]:
    fragments: list[str] = []
    output_text = parsed.get("output_text")
    if isinstance(output_text, str):
        fragments.append(output_text)

    output = parsed.get("output")
    if isinstance(output, list):
        for raw_output_item in cast("list[Any]", output):
            if not isinstance(raw_output_item, dict):
                continue
            output_item = cast("dict[str, Any]", raw_output_item)
            content = output_item.get("content")
            if isinstance(content, list):
                fragments.extend(_text_fields_from_items(cast("list[Any]", content)))

    choices = parsed.get("choices")
    if isinstance(choices, list):
        for raw_choice in cast("list[Any]", choices):
            if not isinstance(raw_choice, dict):
                continue
            choice = cast("dict[str, Any]", raw_choice)
            message = choice.get("message")
            if isinstance(message, dict):
                message_map = cast("dict[str, Any]", message)
                content = message_map.get("content")
                if isinstance(content, str):
                    fragments.append(content)

    candidates = parsed.get("candidates")
    if isinstance(candidates, list):
        for raw_candidate in cast("list[Any]", candidates):
            if not isinstance(raw_candidate, dict):
                continue
            candidate = cast("dict[str, Any]", raw_candidate)
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            content_map = cast("dict[str, Any]", content)
            parts = content_map.get("parts")
            if isinstance(parts, list):
                fragments.extend(_text_fields_from_items(cast("list[Any]", parts)))

    content = parsed.get("content")
    if isinstance(content, list):
        fragments.extend(_text_fields_from_items(cast("list[Any]", content)))

    return fragments


def _text_fields_from_items(items: list[Any]) -> list[str]:
    fragments: list[str] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        item = cast("dict[str, Any]", raw_item)
        text = item.get("text")
        if isinstance(text, str):
            fragments.append(text)
    return fragments


def _iter_fenced_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    in_fence = False
    fence_lines: list[str] = []
    for line in text.splitlines():
        marker = line.strip()
        if not in_fence and marker.startswith("```"):
            in_fence = True
            fence_lines = []
            continue
        if in_fence and marker == "```":
            block = "\n".join(fence_lines).strip()
            if block:
                blocks.append(block)
            in_fence = False
            fence_lines = []
            continue
        if in_fence:
            fence_lines.append(line)
    if in_fence and fence_lines:
        block = "\n".join(fence_lines).strip()
        if block:
            blocks.append(block)
    return blocks


def _decode_json_values(text: str, decoder: json.JSONDecoder) -> list[Any]:
    values: list[Any] = []
    pos = 0
    length = len(text)
    while pos < length:
        character = text[pos]
        if character not in {"{", "["}:
            pos += 1
            continue
        try:
            parsed, end_offset = decoder.raw_decode(text[pos:])
        except json.JSONDecodeError:
            pos += 1
            continue
        if isinstance(parsed, dict) and not parsed:
            pos += end_offset
            continue
        values.append(parsed)
        pos += end_offset
    if not values:
        try:
            parsed = json.loads(text.strip())
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if parsed is not None:
            values.append(parsed)
    if not values:
        recovered = _try_recover_truncated_json(text)
        if recovered is not None:
            values.append(recovered)
    return values


def _try_recover_truncated_json(text: str) -> Any | None:
    stripped = text.strip()
    first_json = _first_json_start(stripped)
    if first_json < 0:
        return None
    fragment = stripped[first_json:]

    last_complete = max(_last_unquoted_index(fragment, "}"), _last_unquoted_index(fragment, "]"))
    strategy_inputs = [fragment]
    if last_complete >= 0:
        strategy_inputs.insert(0, fragment[: last_complete + 1])
    for candidate in strategy_inputs:
        parsed = _try_parse_recovered_json(_close_open_string(candidate))
        if _has_quiz_payload_shape(parsed):
            return parsed

    for candidate in _progressively_trimmed_candidates(fragment):
        parsed = _try_parse_recovered_json(candidate)
        if _has_quiz_payload_shape(parsed):
            return parsed

    for candidate in _partial_json_candidates(fragment):
        parsed = _try_parse_recovered_json(candidate)
        if _has_quiz_payload_shape(parsed):
            return parsed
    return None


def _try_parse_recovered_json(text: str) -> Any | None:
    candidate = text.strip()
    trimmed = _trim_trailing_broken_string(candidate)
    if trimmed is not None:
        candidate = trimmed
    candidate = _close_open_string(candidate)
    candidate = _close_unquoted_delimiters(candidate)
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None


def _has_quiz_payload_shape(value: Any) -> bool:
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return any(isinstance(item, dict) and "question" in item for item in items)
    if isinstance(value, dict):
        value_map = cast("dict[str, Any]", value)
        if "question" in value_map:
            return True
        questions = value_map.get("questions")
        if isinstance(questions, list):
            question_items = cast("list[Any]", questions)
            return any(isinstance(item, dict) and "question" in item for item in question_items)
        output = value_map.get("output")
        return _has_quiz_payload_shape(output)
    return False


def _progressively_trimmed_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for end in range(len(text), 0, -1):
        prefix = text[:end].rstrip()
        if not prefix:
            continue
        trimmed = _trim_trailing_broken_string(prefix)
        for candidate in (trimmed, prefix):
            if candidate and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
        if len(candidates) >= _RECOVERY_MAX_TRIM_CANDIDATES:
            break
    return candidates


_RECOVERY_MAX_TRIM_CANDIDATES = 256


def _partial_json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    stack: list[str] = []
    in_string = False
    escape = False
    for index, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
            continue
        if ch in "}]":
            if stack and ((stack[-1] == "{" and ch == "}") or (stack[-1] == "[" and ch == "]")):
                stack.pop()
            continue
        if ch == "," and stack in (["["], ["{", "["]):
            candidates.append(text[:index])
    return list(reversed(candidates))


def _trim_trailing_broken_string(text: str) -> str | None:
    stripped = text.rstrip()
    if not stripped:
        return None
    if stripped.endswith(","):
        return stripped[:-1].rstrip()
    if stripped.endswith(":"):
        return _trim_to_previous_pair_boundary(stripped[:-1])
    quote_index = _last_unescaped_quote_index(stripped)
    if quote_index != len(stripped) - 1:
        if _has_open_string(stripped):
            before_string = stripped[:quote_index].rstrip()
            if before_string.endswith(":"):
                return _trim_to_previous_pair_boundary(before_string[:-1])
            if (
                before_string.endswith(",")
                or before_string.endswith("{")
                or before_string.endswith("[")
            ):
                return _trim_to_previous_pair_boundary(before_string)
        return None
    opening_quote = _matching_open_quote_index(stripped, quote_index)
    if opening_quote is None:
        return None
    before_string = stripped[:opening_quote].rstrip()
    if before_string.endswith(",") or before_string.endswith("{") or before_string.endswith("["):
        return _trim_to_previous_pair_boundary(before_string)
    return None


def _trim_to_previous_pair_boundary(text: str) -> str | None:
    stripped = text.rstrip()
    if not stripped:
        return None
    if stripped.endswith(","):
        return stripped[:-1].rstrip()
    comma_index = _last_unquoted_index(stripped, ",")
    if comma_index >= 0:
        return stripped[:comma_index].rstrip()
    return stripped


def _count_unquoted_delimiters(text: str) -> tuple[int, int]:
    braces, brackets, in_string, last_quote = _scan_unquoted_delimiters(text)
    if in_string and last_quote is not None:
        recounted = text[:last_quote] + text[last_quote + 1 :]
        braces, brackets, _, _ = _scan_unquoted_delimiters(recounted)
    return braces, brackets


def _scan_unquoted_delimiters(text: str) -> tuple[int, int, bool, int | None]:
    braces = 0
    brackets = 0
    in_string = False
    escape = False
    last_quote: int | None = None
    for index, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            last_quote = index
            continue
        if in_string:
            continue
        if ch == "{":
            braces += 1
        elif ch == "}":
            braces -= 1
        elif ch == "[":
            brackets += 1
        elif ch == "]":
            brackets -= 1
    return braces, brackets, in_string, last_quote


def _close_open_string(text: str) -> str:
    if not _has_open_string(text):
        return text
    return text.rstrip() + '"'


def _has_open_string(text: str) -> bool:
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
    return in_string


def _close_unquoted_delimiters(text: str) -> str:
    open_braces, open_brackets = _count_unquoted_delimiters(text)
    if open_braces <= 0 and open_brackets <= 0:
        return text.rstrip()
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
        elif stack and ((ch == "}" and stack[-1] == "{") or (ch == "]" and stack[-1] == "[")):
            stack.pop()
    suffix = "".join("}" if item == "{" else "]" for item in reversed(stack))
    return text.rstrip() + suffix


def _last_unquoted_index(text: str, target: str) -> int:
    in_string = False
    escape = False
    last_index = -1
    for index, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string and ch == target:
            last_index = index
    return last_index


def _last_unescaped_quote_index(text: str) -> int:
    escape = False
    for index in range(len(text) - 1, -1, -1):
        ch = text[index]
        if ch == "\\":
            escape = not escape
            continue
        if ch == '"' and not escape:
            return index
        escape = False
    return -1


def _matching_open_quote_index(text: str, closing_quote_index: int) -> int | None:
    in_string = False
    escape = False
    opening_quote: int | None = None
    for index, ch in enumerate(text[: closing_quote_index + 1]):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            if in_string:
                if index == closing_quote_index:
                    return opening_quote
                in_string = False
                opening_quote = None
            else:
                in_string = True
                opening_quote = index
    return None


__all__ = [
    "MisconceptionCardOutput",
    "MisconceptionCardSet",
    "QuizEvidence",
    "QuizQuestion",
    "QuizSet",
    "parse_quiz_payload",
]
