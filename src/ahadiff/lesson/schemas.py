from __future__ import annotations

import json
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

    @field_validator("what_changed", "why", "walkthrough", "claims", "concepts", "quiz", "sources")
    @classmethod
    def validate_required_lists(cls, values: list[str]) -> list[str]:
        return _normalize_lines(values)

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

    @field_validator("key_points", "claims", "sources")
    @classmethod
    def validate_required_lists(cls, values: list[str]) -> list[str]:
        return _normalize_lines(values)

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

    @field_validator("summary", "concepts", "sources")
    @classmethod
    def validate_lists(cls, values: list[str]) -> list[str]:
        return _normalize_lines(values)

    def render_markdown(self) -> str:
        sections = [
            self._render_heading("Headline", self.headline),
            self._render_bullets("Summary", self.summary),
            self._render_bullets("Concepts", self.concepts),
            self._render_bullets("Sources", self.sources),
        ]
        return "\n\n".join(sections) + "\n"


def parse_lesson_payload(payload: str, *, schema: type[_LessonModel]) -> _LessonModel:
    candidates = _extract_json_object_candidates(payload)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return schema.model_validate(candidate)
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise ValueError("payload does not contain a JSON object")


def _extract_json_object_candidates(payload: str) -> tuple[dict[str, Any], ...]:
    stripped = payload.strip()
    decoder = json.JSONDecoder()
    candidates = [*_iter_fenced_blocks(stripped), stripped]
    parsed_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        parsed_candidates.extend(_decode_json_objects(candidate, decoder))
    return tuple(parsed_candidates)


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
    return blocks


def _decode_json_objects(text: str, decoder: json.JSONDecoder) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            objects.append(cast("dict[str, Any]", parsed))
    if not objects:
        recovered = _try_recover_truncated_object(text)
        if recovered is not None:
            objects.append(recovered)
    return objects


def _try_recover_truncated_object(text: str) -> dict[str, Any] | None:
    """Recover a JSON object from token-capped truncated output."""
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    last_brace = stripped.rfind("}")
    if last_brace < 0:
        return None
    candidate = stripped[: last_brace + 1]
    open_braces, open_brackets = _count_unquoted_delimiters(candidate)
    candidate += "]" * max(open_brackets, 0) + "}" * max(open_braces, 0)
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(parsed, dict):
        return cast("dict[str, Any]", parsed)
    return None


def _count_unquoted_delimiters(text: str) -> tuple[int, int]:
    """Count unmatched ``{}`` and ``[]`` outside JSON strings."""
    braces = 0
    brackets = 0
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            if in_string:
                escape = True
            continue
        if ch == '"':
            in_string = not in_string
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
    return braces, brackets


__all__ = [
    "LessonCompact",
    "LessonFull",
    "LessonHint",
    "parse_lesson_payload",
]
