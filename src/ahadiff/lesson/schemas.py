from __future__ import annotations

import json
import re
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_line(value: str) -> str:
    return " ".join(value.strip().split())


def _normalize_lines(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        line = _normalize_line(value)
        if line:
            normalized.append(line)
    if not normalized:
        raise ValueError("section must contain at least one non-empty item")
    return normalized


class _LessonModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @staticmethod
    def _render_heading(title: str, content: str) -> str:
        return f"## {title}\n{content.strip()}"

    @staticmethod
    def _render_bullets(title: str, items: list[str]) -> str:
        return f"## {title}\n" + "\n".join(f"- {item}" for item in items)


class LessonFull(_LessonModel):
    tl_dr: str
    what_changed: list[str]
    why: list[str]
    walkthrough: list[str]
    claims: list[str]
    concepts: list[str]
    misconceptions: list[str] = Field(default_factory=list)
    not_proven: list[str] = Field(default_factory=list)
    quiz: list[str]
    sources: list[str]

    @field_validator("tl_dr")
    @classmethod
    def validate_tl_dr(cls, value: str) -> str:
        normalized = _normalize_line(value)
        if not normalized:
            raise ValueError("tl_dr must not be empty")
        return normalized

    @field_validator("what_changed", "why", "walkthrough", "claims", "concepts", "quiz")
    @classmethod
    def validate_required_lists(cls, values: list[str]) -> list[str]:
        return _normalize_lines(values)

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, values: list[str]) -> list[str]:
        return _normalize_sources(values)

    @field_validator("misconceptions", "not_proven")
    @classmethod
    def validate_optional_lists(cls, values: list[str]) -> list[str]:
        return [_normalize_line(value) for value in values if _normalize_line(value)]

    def render_markdown(self) -> str:
        sections = [
            self._render_heading("TL;DR", self.tl_dr),
            self._render_bullets("What Changed", self.what_changed),
            self._render_bullets("Why", self.why),
            self._render_bullets("Walkthrough", self.walkthrough),
            self._render_bullets("Claims", self.claims),
            self._render_bullets("Concepts", self.concepts),
            self._render_bullets(
                "Misconceptions",
                self.misconceptions or ["None recorded for this run."],
            ),
            self._render_bullets(
                "Not Proven",
                self.not_proven or ["No explicitly unproven claims were recorded."],
            ),
            self._render_bullets("Quiz", self.quiz),
            self._render_bullets("Sources", self.sources),
        ]
        return "\n\n".join(sections) + "\n"

    def render_misconceptions_markdown(self) -> str:
        items = self.misconceptions or ["None recorded for this run."]
        return self._render_bullets("Misconceptions", items) + "\n"

    def render_not_proven_markdown(self) -> str:
        items = self.not_proven or ["No explicitly unproven claims were recorded."]
        return self._render_bullets("Not Proven", items) + "\n"


class LessonHint(_LessonModel):
    tl_dr: str
    key_points: list[str]
    watch_fors: list[str] = Field(default_factory=list)
    claims: list[str]
    sources: list[str]

    @field_validator("tl_dr")
    @classmethod
    def validate_tl_dr(cls, value: str) -> str:
        normalized = _normalize_line(value)
        if not normalized:
            raise ValueError("tl_dr must not be empty")
        return normalized

    @field_validator("key_points", "claims")
    @classmethod
    def validate_required_lists(cls, values: list[str]) -> list[str]:
        return _normalize_lines(values)

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, values: list[str]) -> list[str]:
        return _normalize_sources(values)

    @field_validator("watch_fors")
    @classmethod
    def validate_optional_lists(cls, values: list[str]) -> list[str]:
        return [_normalize_line(value) for value in values if _normalize_line(value)]

    def render_markdown(self) -> str:
        sections = [
            self._render_heading("TL;DR", self.tl_dr),
            self._render_bullets("Key Points", self.key_points),
            self._render_bullets("Claims", self.claims),
        ]
        if self.watch_fors:
            sections.append(self._render_bullets("Watch Fors", self.watch_fors))
        sections.append(self._render_bullets("Sources", self.sources))
        return "\n\n".join(sections) + "\n"


class LessonCompact(_LessonModel):
    headline: str
    summary: list[str]
    concepts: list[str]
    sources: list[str]

    @field_validator("headline")
    @classmethod
    def validate_headline(cls, value: str) -> str:
        normalized = _normalize_line(value)
        if not normalized:
            raise ValueError("headline must not be empty")
        return normalized

    @field_validator("summary", "concepts")
    @classmethod
    def validate_lists(cls, values: list[str]) -> list[str]:
        return _normalize_lines(values)

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, values: list[str]) -> list[str]:
        return _normalize_sources(values)

    def render_markdown(self) -> str:
        sections = [
            self._render_heading("Headline", self.headline),
            self._render_bullets("Summary", self.summary),
            self._render_bullets("Concepts", self.concepts),
            self._render_bullets("Sources", self.sources),
        ]
        return "\n\n".join(sections) + "\n"


def parse_lesson_payload(payload: str, *, schema: type[_LessonModel]) -> _LessonModel:
    candidates = extract_json_object_candidates(payload)
    last_error: Exception | None = None
    last_valid: _LessonModel | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            last_valid = schema.model_validate(candidate)
        except Exception as exc:
            last_error = exc
            continue
    if last_valid is not None:
        return last_valid
    if last_error is not None:
        raise last_error
    raise ValueError("payload does not contain a JSON object")


def extract_json_object_candidates(payload: str) -> tuple[dict[str, Any], ...]:
    stripped = _strip_thinking_blocks(payload.strip()).strip()
    decoder = json.JSONDecoder()
    candidates = [*_iter_fenced_blocks(stripped), stripped]
    first_brace = stripped.find("{")
    if first_brace >= 0:
        candidates.append(stripped[first_brace:])
    parsed_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        for parsed in _decode_json_objects(candidate, decoder):
            _append_json_object_candidate(parsed_candidates, parsed, decoder)
    return tuple(parsed_candidates)


_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>[\s\S]*?</think>", re.IGNORECASE)
_TRUNCATED_SOURCE_RE = re.compile(
    r"(?:(?::(?:old|new|either):\d+-)|(?::\d+-)|(?:\blines?\s+\d+-))\s*`?$",
    re.IGNORECASE,
)


def _normalize_sources(values: list[str]) -> list[str]:
    normalized = _normalize_lines(values)
    for source in normalized:
        if _TRUNCATED_SOURCE_RE.search(source):
            raise ValueError("source marker appears truncated")
    return normalized


def _strip_thinking_blocks(text: str) -> str:
    return _THINK_BLOCK_RE.sub("", text)


def _append_json_object_candidate(
    candidates: list[dict[str, Any]],
    parsed: dict[str, Any],
    decoder: json.JSONDecoder,
) -> None:
    candidates.append(parsed)
    output = parsed.get("output")
    if isinstance(output, dict):
        candidates.append(cast("dict[str, Any]", output))
    elif isinstance(output, str):
        for nested in _decode_json_objects(output, decoder):
            candidates.append(nested)
    for nested_text in _provider_text_fragments(parsed):
        for nested in _decode_json_objects(nested_text, decoder):
            candidates.append(nested)


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


def _decode_json_objects(text: str, decoder: json.JSONDecoder) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    pos = 0
    length = len(text)
    while pos < length:
        character = text[pos]
        if character != "{":
            pos += 1
            continue
        try:
            parsed, end_offset = decoder.raw_decode(text[pos:])
        except json.JSONDecodeError:
            pos += 1
            continue
        if isinstance(parsed, dict) and parsed:
            objects.append(cast("dict[str, Any]", parsed))
        pos += end_offset
    if not objects:
        try:
            parsed = json.loads(text.strip())
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict) and parsed:
            objects.append(cast("dict[str, Any]", parsed))
    if not objects:
        recovered = _try_recover_truncated_object(text)
        if recovered is not None:
            objects.append(recovered)
    return objects


def _try_recover_truncated_object(text: str) -> dict[str, Any] | None:
    """Recover a JSON object from token-capped truncated output."""
    stripped = text.strip()
    first_brace = stripped.find("{")
    if first_brace < 0:
        return None
    fragment = stripped[first_brace:]

    last_complete = _last_unquoted_index(fragment, "}")
    strategy_a_inputs = [fragment]
    if last_complete >= 0:
        strategy_a_inputs.insert(0, fragment[: last_complete + 1])
    for candidate in strategy_a_inputs:
        parsed = _try_parse_recovered_object(_close_open_string(candidate))
        if parsed is not None:
            return parsed

    for candidate in _progressively_trimmed_candidates(fragment):
        parsed = _try_parse_recovered_object(candidate)
        if parsed is not None:
            return parsed

    for candidate in _partial_object_candidates(fragment):
        parsed = _try_parse_recovered_object(candidate)
        if parsed is not None:
            return parsed
    return None


def _try_parse_recovered_object(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    trimmed = _trim_trailing_broken_string(candidate)
    if trimmed is not None:
        candidate = trimmed
    candidate = _close_open_string(candidate)
    candidate = _close_unquoted_delimiters(candidate)
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(parsed, dict) and parsed:
        return cast("dict[str, Any]", parsed)
    return None


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


def _partial_object_candidates(text: str) -> list[str]:
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
        if ch == "," and stack == ["{"]:
            candidates.append(text[:index])
    return list(reversed(candidates))


def _trim_trailing_broken_string(text: str) -> str | None:
    """Trim a dangling key, dangling value separator, or trailing comma."""
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
    if before_string.endswith(",") or before_string.endswith("{"):
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
    """Count unmatched ``{}`` and ``[]`` outside JSON strings."""
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
        if ch == "\\":
            if in_string:
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
    "LessonCompact",
    "LessonFull",
    "LessonHint",
    "parse_lesson_payload",
]
