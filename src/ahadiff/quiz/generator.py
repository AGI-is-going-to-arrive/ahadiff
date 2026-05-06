from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.claims.extract import load_line_map_records, load_symbol_records
from ahadiff.contracts import (
    ClaimRecord,
    PrivacyMode,
    ProviderConfig,
    ReviewCard,
    compute_runtime_eval_bundle_version,
)
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.i18n import prompt_language_instruction
from ahadiff.lesson.generator import load_redacted_run_bundle
from ahadiff.lesson.scaffolding import compute_scaffolding_level
from ahadiff.llm import (
    DEFAULT_INPUT_TOKEN_BUDGET,
    DEFAULT_OUTPUT_TOKEN_BUDGET,
    ProviderRequest,
    make_provider,
)
from ahadiff.safety.ignore import AllowlistPolicy
from ahadiff.safety.redact import redaction_pipeline

from .misconception import (
    MisconceptionCard,
    build_misconception_prompt_payload,
    load_misconception_prompt,
    parse_misconception_cards,
    write_misconception_cards,
)
from .schemas import QuizQuestion, parse_quiz_payload

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx

    from ahadiff.core.config import SecurityConfig
    from ahadiff.git.line_map import FileLineMap, HunkLineMap
    from ahadiff.git.symbols import SymbolRecord


@dataclass(frozen=True)
class QuizArtifactPaths:
    quiz_dir: Path
    quiz_path: Path
    cards_path: Path | None = None
    misconception_path: Path | None = None


@dataclass(frozen=True)
class _ResolvedAnchor:
    file_id: str
    display_path: str
    hunk_id: str
    hunk_hash: str
    symbol: str | None
    change_kind: str | None


_PROMPT_FILENAME = "quiz_generate.md"
_PROMPT_NAME = "quiz.generate"
_MISCONCEPTION_PROMPT_NAME = "quiz.misconception_card"
_MISCONCEPTION_ARTIFACT_NAME = "misconception_cards.jsonl"
_VALID_PRIVACY_MODES = frozenset({"strict_local", "redacted_remote", "explicit_remote"})
_MAX_RUN_ARTIFACT_TEXT_BYTES = 16 * 1024 * 1024


def generate_quiz_from_run(
    *,
    run_id: str,
    run_path: Path,
    workspace_root: Path,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    output_lang: str = "en",
    overwrite: bool = False,
    client: httpx.Client | None = None,
    request_timeout_seconds: int = 30,
    max_concurrent: int = 3,
    qps_limit: int = 3,
    retry_attempts: int = 3,
    privacy_mode: PrivacyMode | None = None,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
) -> tuple[QuizArtifactPaths, tuple[QuizQuestion, ...]]:
    bundle = load_redacted_run_bundle(
        run_id=run_id,
        run_path=run_path,
        workspace_root=workspace_root,
    )
    lesson_text = _read_required_text(run_path / "lesson" / "lesson.full.md")
    payload = _generate_quiz_payload(
        bundle=bundle,
        lesson_text=lesson_text,
        provider_config=provider_config,
        api_key=api_key,
        security_config=security_config,
        output_lang=output_lang,
        client=client,
        request_timeout_seconds=request_timeout_seconds,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        privacy_mode=privacy_mode,
        input_token_budget=input_token_budget,
        output_token_budget=output_token_budget,
    )
    question_set = parse_quiz_payload(payload, require_choices=True)
    questions = _materialize_question_ids(run_id, question_set.questions)
    misconception_cards = _generate_misconception_cards(
        run_id=run_id,
        bundle=bundle,
        questions=questions,
        provider_config=provider_config,
        api_key=api_key,
        security_config=security_config,
        output_lang=output_lang,
        client=client,
        request_timeout_seconds=request_timeout_seconds,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        privacy_mode=privacy_mode,
        input_token_budget=input_token_budget,
        output_token_budget=output_token_budget,
    )
    quiz_dir = run_path / "quiz"
    quiz_path = quiz_dir / "quiz.jsonl"
    misconception_path = quiz_dir / _MISCONCEPTION_ARTIFACT_NAME
    write_quiz_questions_jsonl(quiz_path, questions, overwrite=overwrite)
    write_misconception_cards(list(misconception_cards), misconception_path)
    return (
        QuizArtifactPaths(
            quiz_dir=quiz_dir,
            quiz_path=quiz_path,
            misconception_path=misconception_path,
        ),
        questions,
    )


def load_quiz_questions(path: Path) -> tuple[QuizQuestion, ...]:
    if not path.exists():
        raise InputError(f"quiz artifact does not exist: {path}")
    questions: list[QuizQuestion] = []
    for index, line in enumerate(_read_required_text(path).splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = safe_json_loads(stripped)
        except (json.JSONDecodeError, ValueError) as exc:
            raise InputError(f"invalid quiz JSONL line {index}") from exc
        questions.append(QuizQuestion.model_validate(payload))
    if not questions:
        raise InputError(f"quiz artifact is empty: {path}")
    return tuple(questions)


def write_quiz_questions_jsonl(
    path: Path,
    questions: Sequence[QuizQuestion],
    *,
    overwrite: bool = False,
) -> Path:
    serialized = [question.model_dump(mode="json") for question in questions]
    return _write_jsonl(path, serialized, overwrite=overwrite)


def generate_cards_for_run(
    *,
    run_path: Path,
    questions: Sequence[QuizQuestion],
    verdict: str,
    overwrite: bool = False,
) -> Path | None:
    if verdict == "FAIL":
        return None
    metadata = _load_run_json(run_path / "metadata.json")
    source_ref = str(metadata["source_ref"])
    claims = _load_claim_records(run_path / "claims.jsonl")
    claim_lookup = {claim.claim_id: claim for claim in claims}
    line_maps = load_line_map_records(run_path / "line_map.json")
    symbols = load_symbol_records(run_path / "symbols.json")
    cards: list[ReviewCard] = []
    questions_with_card_ids: list[QuizQuestion] = []
    for question in questions:
        claim = _resolve_primary_claim(question, claim_lookup)
        anchor = _resolve_claim_anchor(claim, line_maps, symbols)
        fsrs_state = json.dumps(
            {"state_name": "Learning", "stability_days": 0.0},
            sort_keys=True,
        )
        concept = _resolve_review_card_concept(question, claim)
        card_id = _make_review_card_id(claim=claim, question=question, concept=concept)
        questions_with_card_ids.append(question.model_copy(update={"review_card_id": card_id}))
        cards.append(
            ReviewCard(
                card_id=card_id,
                concept=concept,
                run_id=claim.run_id,
                source_ref=source_ref,
                fsrs_state=fsrs_state,
                scaffolding_level=compute_scaffolding_level(fsrs_state=fsrs_state),
                file_id=anchor.file_id,
                display_path=anchor.display_path,
                hunk_id=anchor.hunk_id,
                hunk_hash=anchor.hunk_hash,
                symbol=anchor.symbol,
                change_kind=cast("Any", anchor.change_kind),
                question=question.question,
                answer=question.expected_answer,
                answer_mode=question.answer_mode,
                choices=question.choices,
            )
        )
    cards_path = run_path / "quiz" / "cards.jsonl"
    write_review_cards_jsonl(cards_path, cards, overwrite=overwrite)
    write_quiz_questions_jsonl(
        run_path / "quiz" / "quiz.jsonl",
        questions_with_card_ids,
        overwrite=True,
    )
    return cards_path


def write_review_cards_jsonl(
    path: Path,
    cards: Sequence[ReviewCard],
    *,
    overwrite: bool = False,
) -> Path:
    serialized = [card.model_dump(mode="json") for card in cards]
    return _write_jsonl(path, serialized, overwrite=overwrite)


def load_quiz_prompt() -> str:
    prompt_path = Path(__file__).resolve().parents[3] / "prompts" / _PROMPT_FILENAME
    if prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8")
    try:
        package_prompt = files("ahadiff").joinpath("prompts", _PROMPT_FILENAME)
        if package_prompt.is_file():
            return package_prompt.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass
    raise InputError(f"quiz prompt resource is missing: {_PROMPT_FILENAME}")


def build_quiz_payload(
    *,
    prompt_text: str,
    metadata: dict[str, Any],
    lesson_text: str,
    claims_text: str,
    patch_text: str,
    line_map_text: str,
    symbols_text: str,
    output_lang: str = "en",
) -> str:
    metadata_payload = {
        "run_id": metadata["run_id"],
        "source_kind": metadata["source_kind"],
        "source_ref": metadata["source_ref"],
        "capability_level": metadata["capability_level"],
        "degraded_flags": metadata.get("degraded_flags", {}),
        "learnability": metadata.get("learnability", {}),
    }
    return "\n\n".join(
        (
            prompt_text.strip(),
            "## Output language\n" + prompt_language_instruction(output_lang),
            "## Run metadata\n```json\n"
            + json.dumps(metadata_payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n```",
            "## lesson.full.md\n```markdown\n" + lesson_text.rstrip() + "\n```",
            "## claims.jsonl\n```json\n" + claims_text.rstrip() + "\n```",
            "## patch.diff\n```diff\n" + patch_text.rstrip() + "\n```",
            "## line_map.json\n```json\n" + line_map_text.rstrip() + "\n```",
            "## symbols.json\n```json\n" + symbols_text.rstrip() + "\n```",
        )
    )


def _generate_quiz_payload(
    *,
    bundle: Any,
    lesson_text: str,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    output_lang: str,
    client: httpx.Client | None,
    request_timeout_seconds: int,
    max_concurrent: int,
    qps_limit: int,
    retry_attempts: int,
    privacy_mode: PrivacyMode | None,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
) -> str:
    prompt_text = load_quiz_prompt()
    payload_text = build_quiz_payload(
        prompt_text=prompt_text,
        metadata=bundle.metadata,
        lesson_text=lesson_text,
        claims_text=bundle.claims_text,
        patch_text=bundle.patch_text,
        line_map_text=bundle.line_map_text,
        symbols_text=bundle.symbols_text,
        output_lang=output_lang,
    )
    prompt_fingerprint = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:12]
    resolved_privacy_mode = privacy_mode or bundle.privacy_mode
    if resolved_privacy_mode not in _VALID_PRIVACY_MODES:
        raise InputError(f"unsupported privacy_mode: {resolved_privacy_mode!r}")
    redacted_payload_text = None
    findings = ()
    if resolved_privacy_mode == "redacted_remote":
        redaction = redaction_pipeline(
            payload_text,
            policy=AllowlistPolicy(
                allow_exact=security_config.allow_exact,
                allow_paths=security_config.allow_paths,
                suppress_rules=security_config.suppress_rules,
            ),
        )
        redacted_payload_text = redaction.redacted_text
        findings = redaction.findings
    provider = make_provider(
        provider_config,
        api_key=api_key,
        security_config=security_config,
        workspace_root=bundle.workspace_root,
        client=client,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        request_timeout_seconds=request_timeout_seconds,
        execution_origin="quiz_generate",
        input_token_budget=(
            input_token_budget if input_token_budget is not None else DEFAULT_INPUT_TOKEN_BUDGET
        ),
        output_token_budget=(
            output_token_budget if output_token_budget is not None else DEFAULT_OUTPUT_TOKEN_BUDGET
        ),
    )
    try:
        response = provider.generate(
            ProviderRequest(
                prompt_name=_PROMPT_NAME,
                prompt_fingerprint=prompt_fingerprint,
                prompt_version=prompt_fingerprint,
                eval_bundle_version=compute_runtime_eval_bundle_version(),
                model=provider_config.model_name,
                payload_text=payload_text,
                diff_content=bundle.patch_text,
                source_ref=str(bundle.metadata["source_ref"]),
                output_lang=output_lang,
                privacy_mode=resolved_privacy_mode,
                redacted_payload_text=redacted_payload_text,
                findings=findings,
                response_format="json",
                max_output_tokens=provider_config.max_output_tokens or 4000,
                thinking_level=provider_config.thinking_level,
            )
        )
    finally:
        provider.close()
    return response.content


def _generate_misconception_cards(
    *,
    run_id: str,
    bundle: Any,
    questions: Sequence[QuizQuestion],
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    output_lang: str,
    client: httpx.Client | None,
    request_timeout_seconds: int,
    max_concurrent: int,
    qps_limit: int,
    retry_attempts: int,
    privacy_mode: PrivacyMode | None,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
) -> tuple[MisconceptionCard, ...]:
    prompt_text = load_misconception_prompt()
    concept_terms = _dedupe_concept_terms(questions)
    prompt_payload = build_misconception_prompt_payload(
        concept_terms=concept_terms,
        diff_text=bundle.patch_text,
        run_id=run_id,
    )
    payload_text = prompt_text.format(
        concept_terms=json.dumps(prompt_payload["concept_terms"], ensure_ascii=False, indent=2),
        run_id=str(prompt_payload["run_id"]),
        diff_summary=str(prompt_payload["diff_summary"]),
        OUTPUT_LANGUAGE=prompt_language_instruction(output_lang),
    )
    prompt_fingerprint = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:12]
    resolved_privacy_mode = privacy_mode or bundle.privacy_mode
    if resolved_privacy_mode not in _VALID_PRIVACY_MODES:
        raise InputError(f"unsupported privacy_mode: {resolved_privacy_mode!r}")
    redacted_payload_text = None
    findings = ()
    if resolved_privacy_mode == "redacted_remote":
        redaction = redaction_pipeline(
            payload_text,
            policy=AllowlistPolicy(
                allow_exact=security_config.allow_exact,
                allow_paths=security_config.allow_paths,
                suppress_rules=security_config.suppress_rules,
            ),
        )
        redacted_payload_text = redaction.redacted_text
        findings = redaction.findings
    provider = make_provider(
        provider_config,
        api_key=api_key,
        security_config=security_config,
        workspace_root=bundle.workspace_root,
        client=client,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        request_timeout_seconds=request_timeout_seconds,
        execution_origin="quiz_generate",
        input_token_budget=(
            input_token_budget if input_token_budget is not None else DEFAULT_INPUT_TOKEN_BUDGET
        ),
        output_token_budget=(
            output_token_budget if output_token_budget is not None else DEFAULT_OUTPUT_TOKEN_BUDGET
        ),
    )
    try:
        response = provider.generate(
            ProviderRequest(
                prompt_name=_MISCONCEPTION_PROMPT_NAME,
                prompt_fingerprint=prompt_fingerprint,
                prompt_version=prompt_fingerprint,
                eval_bundle_version=compute_runtime_eval_bundle_version(),
                model=provider_config.model_name,
                payload_text=payload_text,
                diff_content=bundle.patch_text,
                source_ref=str(bundle.metadata["source_ref"]),
                output_lang=output_lang,
                privacy_mode=resolved_privacy_mode,
                redacted_payload_text=redacted_payload_text,
                findings=findings,
                response_format="json",
                max_output_tokens=provider_config.max_output_tokens or 2000,
                thinking_level=provider_config.thinking_level,
            )
        )
    finally:
        provider.close()
    cards = parse_misconception_cards(response.content)
    return tuple(replace(card, run_id=card.run_id or run_id) for card in cards)


def _materialize_question_ids(
    run_id: str,
    questions: Sequence[QuizQuestion],
) -> tuple[QuizQuestion, ...]:
    materialized: list[QuizQuestion] = []
    for index, question in enumerate(questions, start=1):
        question_id = question.question_id or _make_prefixed_digest(
            "quiz",
            run_id,
            index,
            question.question,
        )
        materialized.append(question.model_copy(update={"question_id": question_id}))
    return tuple(materialized)


def _dedupe_concept_terms(questions: Sequence[QuizQuestion]) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for question in questions:
        for concept in question.concepts:
            normalized = concept.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(normalized)
    return terms


def _load_claim_records(path: Path) -> tuple[ClaimRecord, ...]:
    if not path.exists():
        raise InputError(f"verified claims artifact does not exist: {path}")
    claims: list[ClaimRecord] = []
    for index, line in enumerate(_read_required_text(path).splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = safe_json_loads(stripped)
        except (json.JSONDecodeError, ValueError) as exc:
            raise InputError(f"invalid claims.jsonl line {index}") from exc
        claims.append(ClaimRecord.model_validate(payload))
    if not claims:
        raise InputError(f"claims artifact is empty: {path}")
    return tuple(claims)


def _resolve_primary_claim(
    question: QuizQuestion,
    claim_lookup: dict[str, ClaimRecord],
) -> ClaimRecord:
    for claim_id in question.source_claims:
        claim = claim_lookup.get(claim_id)
        if claim is not None:
            return claim
    raise InputError(
        "quiz question refers to unknown source claim(s): " + ", ".join(question.source_claims)
    )


def _resolve_review_card_concept(question: QuizQuestion, claim: ClaimRecord) -> str:
    if question.concepts:
        return question.concepts[0]
    if claim.symbols:
        return claim.symbols[0]
    return question.question


def _make_review_card_id(
    *,
    claim: ClaimRecord,
    question: QuizQuestion,
    concept: str,
) -> str:
    return _make_prefixed_digest(
        "card",
        claim.run_id,
        question.question_id or question.question,
        concept,
    )


def _resolve_claim_anchor(
    claim: ClaimRecord,
    line_maps: Sequence[FileLineMap],
    symbols: Sequence[SymbolRecord],
) -> _ResolvedAnchor:
    for source_hunk in claim.source_hunks:
        for file_map in line_maps:
            if not _path_matches(file_map, source_hunk.file):
                continue
            for hunk in file_map.hunks:
                if not _hunk_matches(hunk, source_hunk.start, source_hunk.end, source_hunk.side):
                    continue
                return _ResolvedAnchor(
                    file_id=file_map.file_id,
                    display_path=file_map.display_path,
                    hunk_id=hunk.hunk_id,
                    hunk_hash=hunk.hunk_hash,
                    symbol=_resolve_symbol_name(
                        claim=claim,
                        matched_hunk_id=hunk.hunk_id,
                        display_path=file_map.display_path,
                        symbols=symbols,
                    ),
                    change_kind=hunk.change_kind
                    if hunk.change_kind in {"deleted", "renamed"}
                    else None,
                )
    raise InputError(f"could not resolve review-card anchor for claim {claim.claim_id}")


def _path_matches(file_map: FileLineMap, target_path: str) -> bool:
    return target_path in {file_map.display_path, file_map.old_path, file_map.new_path}


def _hunk_matches(hunk: HunkLineMap, start: int, end: int, side: str) -> bool:
    if side == "old":
        candidate_lines = (*hunk.deleted_lines, *hunk.context_old_lines)
    elif side == "new":
        candidate_lines = (*hunk.added_lines, *hunk.context_new_lines)
    else:
        candidate_lines = (
            *hunk.deleted_lines,
            *hunk.context_old_lines,
            *hunk.added_lines,
            *hunk.context_new_lines,
        )
    return any(start <= line <= end for line in candidate_lines)


def _resolve_symbol_name(
    *,
    claim: ClaimRecord,
    matched_hunk_id: str,
    display_path: str,
    symbols: Sequence[SymbolRecord],
) -> str | None:
    if claim.symbols:
        return claim.symbols[0]
    for symbol in symbols:
        if symbol.path == display_path and matched_hunk_id in symbol.hunk_ids:
            return symbol.qualified_name
    return None


def _make_prefixed_digest(prefix: str, *parts: object) -> str:
    payload = "::".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:12]}"


def _write_jsonl(
    path: Path,
    items: Sequence[dict[str, Any]],
    *,
    overwrite: bool,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise InputError(f"output path already exists: {path}")
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        try:
            for item in items:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    temp_path.replace(path)
    return path


def _load_run_json(path: Path) -> dict[str, Any]:
    try:
        payload = safe_json_loads(_read_required_text(path))
    except (json.JSONDecodeError, ValueError) as exc:
        raise InputError(f"invalid JSON in run artifact: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InputError(f"run artifact must be a JSON object: {path}")
    return cast("dict[str, Any]", payload)


def _read_required_text(path: Path) -> str:
    if not path.exists():
        raise InputError(f"required run artifact is missing: {path}")
    try:
        with path.open("rb") as handle:
            data = handle.read(_MAX_RUN_ARTIFACT_TEXT_BYTES + 1)
    except OSError as exc:
        raise InputError(f"required run artifact is unreadable: {path}") from exc
    if len(data) > _MAX_RUN_ARTIFACT_TEXT_BYTES:
        raise InputError(f"required run artifact exceeds size limit: {path}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"required run artifact is not valid UTF-8: {path}") from exc


__all__ = [
    "QuizArtifactPaths",
    "build_quiz_payload",
    "generate_cards_for_run",
    "generate_quiz_from_run",
    "load_quiz_prompt",
    "load_quiz_questions",
    "write_quiz_questions_jsonl",
    "write_review_cards_jsonl",
]
