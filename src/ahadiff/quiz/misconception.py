from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, cast

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads

MisconceptionSeverity = Literal["low", "medium", "high"]

_VALID_SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high"})

_MAX_DIFF_SUMMARY_BYTES = 8 * 1024
_PROMPT_FILENAME = "misconception_card.md"
_CARD_CONTAINER_KEYS = ("cards", "misconceptions", "misconception_cards", "items", "data")
_CARD_KEYS = {"concept", "misconception", "correction"}
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>[\s\S]*?</think>", re.IGNORECASE)


@dataclass(frozen=True)
class MisconceptionCard:
    card_id: str
    concept: str
    misconception: str
    correction: str
    evidence_ref: str
    severity: MisconceptionSeverity
    safety_tags: tuple[str, ...]
    run_id: str


def parse_misconception_cards(raw: str) -> list[MisconceptionCard]:
    for parsed in _extract_json_candidates(raw):
        items = _coerce_card_items(parsed)
        if items is None:
            continue
        cards = _validate_card_items(items)
        if cards:
            return cards
    return []


def has_explicit_empty_misconception_cards(raw: str) -> bool:
    for parsed in _extract_json_candidates(raw):
        if _contains_explicit_empty_card_container(parsed):
            return True
        items = _coerce_card_items(parsed)
        if items:
            return False
    return False


def _contains_explicit_empty_card_container(value: Any) -> bool:
    if isinstance(value, list):
        return any(
            _contains_explicit_empty_card_container(item) for item in cast("list[Any]", value)
        )
    if not isinstance(value, dict):
        return False
    value_map = cast("dict[str, Any]", value)
    for key in _CARD_CONTAINER_KEYS:
        raw_items = value_map.get(key)
        if raw_items == []:
            return True
        if isinstance(raw_items, list):
            return False
    return any(
        _contains_explicit_empty_card_container(nested)
        for nested in _nested_card_sources(value_map)
    )


def _validate_card_items(items: list[Any]) -> list[MisconceptionCard]:
    cards: list[MisconceptionCard] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        try:
            cards.append(_validate_card_dict(cast("dict[str, Any]", item), index))
        except InputError:
            continue
    return cards


def _extract_json_candidates(raw: str) -> tuple[Any, ...]:
    stripped = _strip_thinking_blocks(raw.strip()).strip()
    if not stripped:
        return ()
    decoder = _make_json_decoder()
    candidates = [*_iter_fenced_blocks(stripped), stripped]
    first_json = _first_json_start(stripped)
    if first_json >= 0:
        candidates.append(stripped[first_json:])

    parsed_candidates: list[Any] = []
    for candidate in candidates:
        for parsed in _decode_json_values(candidate, decoder):
            _append_json_candidate(parsed_candidates, parsed, decoder)

    jsonl = _try_parse_jsonl(raw)
    if jsonl is not None:
        parsed_candidates.append(jsonl)

    indexed_candidates = list(enumerate(parsed_candidates))
    indexed_candidates.sort(key=lambda item: (_candidate_quality(item[1]), item[0]), reverse=True)
    return tuple(candidate for _, candidate in indexed_candidates)


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
    if not isinstance(parsed, dict):
        return
    parsed_map = cast("dict[str, Any]", parsed)
    output = parsed_map.get("output")
    if isinstance(output, dict | list):
        candidates.append(output)
    elif isinstance(output, str):
        candidates.extend(_decode_json_values(output, decoder))
    for nested_text in _provider_text_fragments(parsed_map):
        candidates.extend(_decode_json_values(nested_text, decoder))


def _candidate_quality(candidate: Any) -> int:
    items = _coerce_card_items(candidate)
    if items is not None:
        if any(_looks_like_card(item) for item in items):
            return 1000 + len(items)
        return 700 + len(items)
    if isinstance(candidate, dict):
        candidate_map = cast("dict[str, Any]", candidate)
        if "output" in candidate_map:
            return 100
        return len(candidate_map)
    return 0


def _coerce_card_items(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return cast("list[Any]", value)
    if not isinstance(value, dict):
        return None
    value_map = cast("dict[str, Any]", value)
    for key in _CARD_CONTAINER_KEYS:
        raw_items = value_map.get(key)
        if isinstance(raw_items, list):
            return cast("list[Any]", raw_items)
    if set(value_map.keys()) >= _CARD_KEYS:
        return [value_map]
    for nested in _nested_card_sources(value_map):
        items = _coerce_card_items(nested)
        if items is not None:
            return items
    return None


def _nested_card_sources(value: dict[str, Any]) -> list[Any]:
    sources: list[Any] = []
    for key in ("output", "data", "result", "response"):
        nested = value.get(key)
        if isinstance(nested, dict | list):
            sources.append(nested)
        elif isinstance(nested, str):
            sources.extend(_extract_json_candidates(nested))
    for nested_text in _provider_text_fragments(value):
        sources.extend(_extract_json_candidates(nested_text))
    return sources


def _looks_like_card(value: Any) -> bool:
    return isinstance(value, dict) and set(cast("dict[str, Any]", value).keys()) >= _CARD_KEYS


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


def _iter_fenced_blocks(raw: str) -> list[str]:
    blocks: list[str] = []
    in_fence = False
    fence_lines: list[str] = []
    for line in raw.splitlines():
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
        except (json.JSONDecodeError, ValueError):
            pos += 1
            continue
        if isinstance(parsed, dict) and not parsed:
            pos += end_offset
            continue
        values.append(parsed)
        pos += end_offset
    if not values:
        with suppress(json.JSONDecodeError, ValueError):
            values.append(safe_json_loads(text.strip()))
    return values


def _make_json_decoder() -> json.JSONDecoder:
    return json.JSONDecoder(parse_constant=_reject_json_constant, parse_float=_parse_finite_float)


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"Disallowed JSON constant: {value!r}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"Non-finite JSON number: {value!r}")
    return parsed


def _try_parse_jsonl(raw: str) -> list[Any] | None:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return None
    objects: list[Any] = []
    for line in lines:
        try:
            objects.append(safe_json_loads(line))
        except (json.JSONDecodeError, ValueError):
            return None
    return objects


def write_misconception_cards(cards: list[MisconceptionCard], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        try:
            for card in cards:
                handle.write(json.dumps(_card_to_dict(card), ensure_ascii=False) + "\n")
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    temp_path.replace(output_path)
    return output_path


def load_misconception_cards(path: Path) -> list[MisconceptionCard]:
    if not path.exists():
        raise InputError(f"misconception cards file does not exist: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"misconception cards file is unreadable: {path}") from exc
    cards: list[MisconceptionCard] = []
    for line_num, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = safe_json_loads(stripped)
        except (json.JSONDecodeError, ValueError) as exc:
            raise InputError(f"invalid JSONL at line {line_num}: {exc}") from exc
        if not isinstance(item, dict):
            raise InputError(f"misconception card at line {line_num} must be a JSON object")
        cards.append(_validate_card_dict(cast("dict[str, Any]", item), line_num))
    return cards


def build_misconception_prompt_payload(
    concept_terms: list[str],
    diff_text: str,
    run_id: str,
) -> dict[str, object]:
    diff_summary = diff_text[:_MAX_DIFF_SUMMARY_BYTES] if diff_text else ""
    return {
        "concept_terms": concept_terms,
        "diff_summary": diff_summary,
        "run_id": run_id,
    }


def load_misconception_prompt() -> str:
    prompt_path = Path(__file__).resolve().parents[3] / "prompts" / _PROMPT_FILENAME
    if prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8")
    try:
        package_prompt = files("ahadiff").joinpath("prompts", _PROMPT_FILENAME)
        if package_prompt.is_file():
            return package_prompt.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass
    raise InputError(f"misconception prompt resource is missing: {_PROMPT_FILENAME}")


def _validate_card_dict(item: dict[str, Any], index: int) -> MisconceptionCard:
    required = ("concept", "misconception", "correction", "evidence_ref", "severity")
    for key in required:
        if key not in item:
            raise InputError(f"misconception card at index {index} missing required key: {key}")

    concept = _require_nonempty_str(item, "concept", index)
    misconception = _require_nonempty_str(item, "misconception", index)
    correction = _require_nonempty_str(item, "correction", index)
    evidence_ref = _require_nonempty_str(item, "evidence_ref", index)

    severity = item["severity"]
    if severity not in _VALID_SEVERITIES:
        msg = f"misconception card at index {index}: severity must be low/medium/high"
        raise InputError(f"{msg}, got {severity!r}")

    raw_tags = item.get("safety_tags", [])
    if not isinstance(raw_tags, list):
        raise InputError(f"misconception card at index {index}: safety_tags must be a list")
    tag_list = cast("list[Any]", raw_tags)
    for i, tag in enumerate(tag_list):
        if not isinstance(tag, str):
            raise InputError(
                f"misconception card at index {index}: safety_tags[{i}] must be a string"
            )
    safety_tags = tuple(cast("list[str]", tag_list))

    card_id = _optional_string_or_default(
        item.get("card_id"),
        index=index,
        key="card_id",
        default=_make_card_id(concept, misconception),
    )
    run_id = _optional_string_or_default(item.get("run_id"), index=index, key="run_id", default="")

    return MisconceptionCard(
        card_id=str(card_id),
        concept=concept,
        misconception=misconception,
        correction=correction,
        evidence_ref=evidence_ref,
        severity=severity,
        safety_tags=safety_tags,
        run_id=run_id,
    )


def _require_nonempty_str(item: dict[str, Any], key: str, index: int) -> str:
    value = item[key]
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"misconception card at index {index}: {key} must be a non-empty string")
    return value.strip()


def _make_card_id(concept: str, misconception: str) -> str:
    payload = f"{concept}::{misconception}".encode()
    return f"misc_{hashlib.sha256(payload).hexdigest()[:12]}"


def _optional_string_or_default(value: object, *, index: int, key: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise InputError(f"misconception card at index {index}: {key} must be a string")
    stripped = value.strip()
    return stripped or default


def _card_to_dict(card: MisconceptionCard) -> dict[str, Any]:
    return {
        "card_id": card.card_id,
        "concept": card.concept,
        "misconception": card.misconception,
        "correction": card.correction,
        "evidence_ref": card.evidence_ref,
        "severity": card.severity,
        "safety_tags": list(card.safety_tags),
        "run_id": card.run_id,
    }


__all__ = [
    "MisconceptionCard",
    "MisconceptionSeverity",
    "build_misconception_prompt_payload",
    "has_explicit_empty_misconception_cards",
    "load_misconception_prompt",
    "load_misconception_cards",
    "parse_misconception_cards",
    "write_misconception_cards",
]
