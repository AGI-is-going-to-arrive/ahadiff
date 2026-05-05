from __future__ import annotations

import hashlib
import json
import tempfile
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
    try:
        parsed = _extract_json_value(raw)
    except InputError:
        return []
    if isinstance(parsed, dict):
        parsed_map = cast("dict[str, Any]", parsed)
        for key in ("cards", "misconceptions", "misconception_cards", "items", "data"):
            if key in parsed_map and isinstance(parsed_map[key], list):
                parsed = parsed_map[key]
                break
        else:
            _card_keys = {"concept", "misconception", "correction"}
            if _card_keys <= set(parsed_map.keys()):
                parsed = [parsed_map]
    if not isinstance(parsed, list):
        return []
    items = cast("list[Any]", parsed)
    cards: list[MisconceptionCard] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        try:
            cards.append(_validate_card_dict(cast("dict[str, Any]", item), index))
        except InputError:
            continue
    return cards


def _extract_json_value(raw: str) -> Any:
    for candidate in _json_candidates(raw):
        try:
            return safe_json_loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    jsonl = _try_parse_jsonl(raw)
    if jsonl is not None:
        return jsonl
    raise InputError("misconception cards payload contains no valid JSON")


def _json_candidates(raw: str) -> list[str]:
    candidates: list[str] = []
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
                candidates.append(block)
            in_fence = False
            fence_lines = []
            continue
        if in_fence:
            fence_lines.append(line)
    candidates.append(raw.strip())
    return candidates


def _try_parse_jsonl(raw: str) -> list[Any] | None:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return None
    objects: list[Any] = []
    for line in lines:
        try:
            objects.append(json.loads(line))
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
    "load_misconception_prompt",
    "load_misconception_cards",
    "parse_misconception_cards",
    "write_misconception_cards",
]
