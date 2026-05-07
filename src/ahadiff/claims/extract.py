from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.git.line_map import (
    LINE_MAP_SCHEMA,
    LINE_MAP_SCHEMA_VERSION,
    FileLineMap,
    HunkLineMap,
)
from ahadiff.git.symbols import (
    SYMBOLS_SCHEMA,
    SYMBOLS_SCHEMA_VERSION,
    SymbolRange,
    SymbolRecord,
)

from .schema import ClaimCandidate, VerifiedClaim

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

_MAX_CLAIM_TEXT_BYTES = 10 * 1024
_JSON_FENCE_RE = re.compile(
    r"```(?P<lang>[^\r\n`]*)\r?\n(?P<body>[\s\S]*?)```",
    re.IGNORECASE,
)
_INVALID_JSON_ESCAPE_RE = re.compile(r'\\(?!["\\/bfnrtu])')


def parse_claim_candidates_text(
    text: str,
    *,
    default_run_id: str | None = None,
) -> tuple[ClaimCandidate, ...]:
    stripped = text.strip()
    if not stripped:
        raise InputError("claim candidate payload is empty")

    parsed_candidates: list[tuple[int, tuple[ClaimCandidate, ...]]] = []
    order = 0
    last_error: InputError | None = None
    for payload_text in _candidate_payload_texts(stripped):
        json_payload = _try_parse_json(payload_text)
        if json_payload is not None:
            try:
                order = _append_candidate_batch(
                    parsed_candidates,
                    order=order,
                    candidates=_coerce_claim_candidates(
                        json_payload,
                        default_run_id=default_run_id,
                    ),
                )
                continue
            except InputError as exc:
                last_error = exc
        try:
            order = _append_candidate_batch(
                parsed_candidates,
                order=order,
                candidates=_parse_jsonl_candidates(
                    payload_text,
                    default_run_id=default_run_id,
                ),
            )
        except InputError as exc:
            last_error = exc
            continue

    for payload_text in _candidate_payload_texts(stripped):
        recovered = _try_recover_truncated_json(payload_text)
        if recovered:
            try:
                order = _append_candidate_batch(
                    parsed_candidates,
                    order=order,
                    candidates=_coerce_claim_candidates(
                        recovered,
                        default_run_id=default_run_id,
                    ),
                )
            except InputError as exc:
                last_error = exc

    if parsed_candidates:
        return max(
            parsed_candidates,
            key=lambda item: (len(item[1]), item[0]),
        )[1]

    if last_error is not None:
        raise last_error
    raise InputError("claim candidate payload is empty")


def _append_candidate_batch(
    batches: list[tuple[int, tuple[ClaimCandidate, ...]]],
    *,
    order: int,
    candidates: tuple[ClaimCandidate, ...],
) -> int:
    if candidates:
        batches.append((order, candidates))
    return order + 1


def load_claim_candidates(
    path: Path,
    *,
    default_run_id: str | None = None,
    enforce_run_id_match: bool = False,
) -> tuple[ClaimCandidate, ...]:
    if not path.exists():
        raise InputError(f"claim candidate file does not exist: {path}")
    candidates = parse_claim_candidates_text(
        path.read_text(encoding="utf-8"),
        default_run_id=default_run_id,
    )
    # When enforce_run_id_match is True, every claim candidate must already
    # belong to ``default_run_id`` — used by the learn pipeline to refuse
    # cross-run contamination from provider-emitted ``run_id`` values.
    if enforce_run_id_match and default_run_id is not None:
        for candidate in candidates:
            if candidate.run_id != default_run_id:
                raise InputError(
                    f"claim candidate run_id mismatch: {candidate.run_id!r} != {default_run_id!r}"
                )
    return candidates


def write_claim_candidates_jsonl(
    path: Path,
    candidates: Sequence[ClaimCandidate],
    *,
    overwrite: bool = False,
) -> Path:
    return _write_jsonl(
        path,
        [candidate.model_dump(mode="json") for candidate in candidates],
        overwrite=overwrite,
    )


def write_verified_claims_jsonl(
    path: Path,
    claims: Sequence[VerifiedClaim],
    *,
    overwrite: bool = False,
) -> Path:
    return _write_jsonl(
        path,
        [claim.record.model_dump(mode="json") for claim in claims],
        overwrite=overwrite,
    )


def load_line_map_records(path: Path) -> tuple[FileLineMap, ...]:
    payload = _load_json(path)
    if payload.get("schema") != LINE_MAP_SCHEMA:
        raise InputError(f"unexpected line_map schema in {path}")
    if payload.get("schema_version") != LINE_MAP_SCHEMA_VERSION:
        raise InputError(f"unexpected line_map schema_version in {path}")
    files: list[FileLineMap] = []
    for item in payload.get("files", []):
        files.append(
            FileLineMap(
                file_id=str(item["file_id"]),
                display_path=str(item["display_path"]),
                path_identity_key=str(item["path_identity_key"]),
                old_path=item.get("old_path"),
                new_path=item.get("new_path"),
                change_kind=item["change_kind"],
                hunks=tuple(
                    HunkLineMap(
                        file_id=str(hunk["file_id"]),
                        display_path=str(hunk["display_path"]),
                        hunk_id=str(hunk["hunk_id"]),
                        hunk_hash=str(hunk["hunk_hash"]),
                        change_kind=hunk["change_kind"],
                        old_start=int(hunk["old_start"]),
                        old_end=int(hunk["old_end"]),
                        new_start=int(hunk["new_start"]),
                        new_end=int(hunk["new_end"]),
                        section_header=hunk.get("section_header"),
                        added_lines=tuple(int(value) for value in hunk["added_lines"]),
                        deleted_lines=tuple(int(value) for value in hunk["deleted_lines"]),
                        context_old_lines=tuple(int(value) for value in hunk["context_old_lines"]),
                        context_new_lines=tuple(int(value) for value in hunk["context_new_lines"]),
                    )
                    for hunk in item.get("hunks", [])
                ),
            )
        )
    return tuple(files)


def load_symbol_records(path: Path) -> tuple[SymbolRecord, ...]:
    payload = _load_json(path)
    if payload.get("schema") != SYMBOLS_SCHEMA:
        raise InputError(f"unexpected symbols schema in {path}")
    if payload.get("schema_version") != SYMBOLS_SCHEMA_VERSION:
        raise InputError(f"unexpected symbols schema_version in {path}")
    records: list[SymbolRecord] = []
    for item in payload.get("symbols", []):
        range_payload = item["range"]
        selection_payload = item["selection_range"]
        records.append(
            SymbolRecord(
                path=str(item["path"]),
                qualified_name=str(item["qualified_name"]),
                kind=str(item["kind"]),
                range=SymbolRange(
                    start=int(range_payload["start"]),
                    end=int(range_payload["end"]),
                ),
                selection_range=SymbolRange(
                    start=int(selection_payload["start"]),
                    end=int(selection_payload["end"]),
                ),
                parent=item.get("parent"),
                touched_lines=tuple(int(value) for value in item["touched_lines"]),
                hunk_ids=tuple(str(value) for value in item["hunk_ids"]),
                hunk_hash=str(item["hunk_hash"]),
                change_kind=item.get("change_kind"),
                extractor=item["extractor"],
                confidence=item["confidence"],
                error=item.get("error"),
            )
        )
    return tuple(records)


def _candidate_payload_texts(text: str) -> tuple[str, ...]:
    fence_payloads: list[str] = []
    for match in _JSON_FENCE_RE.finditer(text):
        language = (match.group("lang") or "").strip().casefold()
        if language and language != "json":
            continue
        fence_payloads.append(match.group("body").strip())
    embedded_payloads = _embedded_json_payload_texts(text)
    return tuple(dict.fromkeys((*fence_payloads, *embedded_payloads, text)))


def _embedded_json_payload_texts(text: str) -> tuple[str, ...]:
    decoder = json.JSONDecoder()
    payloads: list[str] = []
    for index, character in enumerate(text):
        if character not in "{[":
            continue
        try:
            _parsed, end_offset = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        payloads.append(text[index : index + end_offset].strip())
    return tuple(payloads)


def _try_parse_json(text: str) -> Any | None:
    for candidate in (text, _escape_invalid_json_string_backslashes(text)):
        try:
            return safe_json_loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _escape_invalid_json_string_backslashes(text: str) -> str:
    return _INVALID_JSON_ESCAPE_RE.sub(r"\\\\", text)


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


def _try_recover_truncated_json(text: str) -> list[dict[str, Any]] | None:
    """Recover complete claim objects from token-capped truncated JSON."""
    stripped = text.strip()
    if not stripped.startswith("{") and not stripped.startswith("["):
        return _try_recover_leading_truncated_claim_array(stripped)
    last_complete = stripped.rfind("}")
    if last_complete < 0:
        return None
    for candidate in _truncated_json_candidates(stripped, last_complete=last_complete):
        parsed = _try_parse_json(candidate)
        items = _claim_dicts_from_recovered_payload(parsed)
        if items:
            return items
    return None


def _try_recover_leading_truncated_claim_array(text: str) -> list[dict[str, Any]] | None:
    """Recover arrays where generation started in the middle of the first claim."""
    for match in re.finditer(r'\{\s*"(?:claim_id|run_id|text|source_hunks)"\s*:', text):
        candidate = "[" + text[match.start() :]
        recovered = _try_recover_truncated_json(candidate)
        if recovered:
            return recovered
    return None


def _truncated_json_candidates(text: str, *, last_complete: int) -> tuple[str, ...]:
    candidates: list[str] = []
    if text.startswith("["):
        last_array_end = text.rfind("]")
        if last_array_end >= 0:
            candidates.append(text[: last_array_end + 1])
    candidate = text[: last_complete + 1]
    open_braces, open_brackets = _count_unquoted_delimiters(candidate)
    candidate += "]" * max(open_brackets, 0) + "}" * max(open_braces, 0)
    candidates.append(candidate)
    return tuple(dict.fromkeys(candidates))


def _claim_dicts_from_recovered_payload(parsed: Any) -> list[dict[str, Any]] | None:
    items = _claim_dicts_from_payload(parsed)
    if items:
        return items
    return None


def _claim_dicts_from_payload(parsed: Any) -> list[dict[str, Any]] | None:
    if isinstance(parsed, dict):
        envelope = cast("dict[str, Any]", parsed)
        claims_value = envelope.get("claims")
        if isinstance(claims_value, list) and claims_value:
            cv = cast("list[Any]", claims_value)
            claim_items: list[dict[str, Any]] = []
            for item in cv:
                if not isinstance(item, dict):
                    continue
                item_map = cast("dict[str, Any]", item)
                if _looks_like_claim_candidate(item_map):
                    claim_items.append(item_map)
            return claim_items or None
        output_value = envelope.get("output")
        if isinstance(output_value, dict | list):
            nested = _claim_dicts_from_payload(output_value)
            if nested:
                return nested
        if isinstance(output_value, str):
            nested_payload = _try_parse_json(output_value)
            nested = _claim_dicts_from_payload(nested_payload)
            if nested:
                return nested
        return None
    if isinstance(parsed, list) and parsed:
        items = cast("list[Any]", parsed)
        claim_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_map = cast("dict[str, Any]", item)
            if _looks_like_claim_candidate(item_map):
                claim_items.append(item_map)
        return claim_items or None
    return None


def _looks_like_claim_candidate(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    value_map = cast("dict[str, object]", value)
    return any(key in value_map for key in ("text", "source_hunks", "claim_id"))


def _parse_jsonl_candidates(
    text: str,
    *,
    default_run_id: str | None,
) -> tuple[ClaimCandidate, ...]:
    items: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = safe_json_loads(stripped)
        except (json.JSONDecodeError, ValueError) as exc:
            raise InputError(f"invalid claim candidate JSONL line {index}") from exc
        if not isinstance(payload, dict):
            raise InputError(f"claim candidate line {index} must be a JSON object")
        items.append(cast("dict[str, Any]", payload))
    if not items:
        raise InputError("claim candidate payload did not contain any JSON objects")
    return _coerce_claim_candidates(items, default_run_id=default_run_id)


def _coerce_claim_candidates(
    payload: Any,
    *,
    default_run_id: str | None,
) -> tuple[ClaimCandidate, ...]:
    items: list[dict[str, Any]]
    if isinstance(payload, dict):
        envelope = cast("dict[str, Any]", payload)
        wrapped_items = _claim_dicts_from_payload(envelope)
        items = wrapped_items if wrapped_items is not None else [envelope]
    elif isinstance(payload, list):
        items = []
        for index, item in enumerate(cast("list[Any]", payload), start=1):
            if not isinstance(item, dict):
                raise InputError(f"claim candidate #{index} must be a JSON object")
            items.append(cast("dict[str, Any]", item))
    else:
        raise InputError("claim candidate payload must be a JSON object, array, or JSONL")

    candidates: list[ClaimCandidate] = []
    seen_claim_ids: set[str] = set()
    for index, item in enumerate(items, start=1):
        normalized: dict[str, Any] = dict(item)
        if not normalized.get("claim_id"):
            normalized["claim_id"] = _default_claim_id(default_run_id, index)
        if not normalized.get("run_id"):
            if default_run_id is None:
                raise InputError(f"claim candidate #{index} is missing run_id")
            normalized["run_id"] = default_run_id
        try:
            candidate = ClaimCandidate.model_validate(normalized)
        except ValidationError as exc:
            raise InputError(f"invalid claim candidate #{index}: {exc}") from exc
        if candidate.claim_id in seen_claim_ids:
            dedup_suffix = 2
            while f"{candidate.claim_id}_{dedup_suffix}" in seen_claim_ids:
                dedup_suffix += 1
            candidate = candidate.model_copy(
                update={"claim_id": f"{candidate.claim_id}_{dedup_suffix}"}
            )
        _validate_claim_candidate_shape(candidate)
        seen_claim_ids.add(candidate.claim_id)
        candidates.append(candidate)
    return tuple(candidates)


def _validate_claim_candidate_shape(candidate: ClaimCandidate) -> None:
    if len(candidate.text.encode("utf-8")) > _MAX_CLAIM_TEXT_BYTES:
        raise InputError(
            f"claim content exceeds {_MAX_CLAIM_TEXT_BYTES} bytes: {candidate.claim_id}"
        )


def _default_claim_id(run_id: str | None, index: int) -> str:
    prefix = "claim" if run_id is None else run_id
    return f"{prefix}-claim-{index:03d}"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise InputError(f"artifact file does not exist: {path}")
    try:
        payload = safe_json_loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise InputError(f"invalid JSON in artifact file: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InputError(f"artifact payload must be a JSON object: {path}")
    return cast("dict[str, Any]", payload)


def _write_jsonl(
    path: Path,
    rows: Iterable[dict[str, Any]],
    *,
    overwrite: bool,
) -> Path:
    if path.exists() and not overwrite:
        raise InputError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload_text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    tmp_file: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_file = Path(handle.name)
            handle.write(payload_text)
        tmp_file.replace(path)
    finally:
        if tmp_file is not None:
            tmp_file.unlink(missing_ok=True)
    return path


def load_text_map(path: Path, *, expected_artifact: str) -> dict[str, str]:
    payload = _load_json(path)
    if payload.get("artifact") != expected_artifact:
        raise InputError(f"unexpected text map artifact in {path}")
    if payload.get("schema") != "ahadiff.text_map":
        raise InputError(f"unexpected text map schema in {path}")
    if payload.get("schema_version") != 1:
        raise InputError(f"unexpected text map schema_version in {path}")
    raw_texts = payload.get("texts")
    if not isinstance(raw_texts, dict):
        raise InputError(f"text map payload must contain an object field 'texts': {path}")
    texts: dict[str, str] = {}
    for key, value in cast("dict[Any, Any]", raw_texts).items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise InputError(f"text map entries must be string-to-string in {path}")
        texts[key] = value
    return texts


__all__ = [
    "load_claim_candidates",
    "load_line_map_records",
    "load_symbol_records",
    "load_text_map",
    "parse_claim_candidates_text",
    "write_claim_candidates_jsonl",
    "write_verified_claims_jsonl",
]
