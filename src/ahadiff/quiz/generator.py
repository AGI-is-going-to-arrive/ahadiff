from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ahadiff.claims.extract import (
    load_line_map_records,
    load_symbol_records,
    read_artifact_text_no_follow,
)
from ahadiff.contracts import (
    ClaimRecord,
    PrivacyMode,
    ProviderConfig,
    ReviewCard,
    compute_runtime_eval_bundle_version,
)
from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.source_evidence import (
    evidence_prompt_section,
    load_evidence_anchors,
    review_prompt_section,
    source_prompt_section,
    validate_source_anchor_references,
)
from ahadiff.i18n import prompt_language_instruction
from ahadiff.lesson.generator import load_redacted_run_bundle
from ahadiff.lesson.scaffolding import compute_scaffolding_level
from ahadiff.llm import (
    DEFAULT_INPUT_TOKEN_BUDGET,
    DEFAULT_OUTPUT_TOKEN_BUDGET,
    ProviderRequest,
    generate_with_validation_retry,
    make_provider,
)
from ahadiff.llm.cost import effective_output_cap, resolve_model_limits
from ahadiff.llm.strict_json import (
    require_complete_json_for_fallback,
    strict_json_envelope,
)
from ahadiff.llm.structured import schema_spec_for, structured_request_kwargs
from ahadiff.safety.ignore import AllowlistPolicy
from ahadiff.safety.redact import redaction_pipeline

from .distractor_gate import build_distractor_gate_report, write_distractor_gate_report
from .misconception import (
    MisconceptionCard,
    build_misconception_prompt_payload,
    has_explicit_empty_misconception_cards,
    load_misconception_prompt,
    parse_misconception_cards,
    write_misconception_cards,
)
from .schemas import QuizQuestion, parse_quiz_payload

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    import httpx

    from ahadiff.contracts.source_anchor import SourceAnchor
    from ahadiff.core.config import SecurityConfig
    from ahadiff.git.line_map import FileLineMap, HunkLineMap
    from ahadiff.git.symbols import SymbolRecord
    from ahadiff.llm.schemas import EnforcementMode


@dataclass(frozen=True)
class QuizArtifactPaths:
    quiz_dir: Path
    quiz_path: Path
    cards_path: Path | None = None
    misconception_path: Path | None = None
    distractor_gate_path: Path | None = None


@dataclass(frozen=True)
class _ResolvedAnchor:
    file_id: str
    display_path: str
    hunk_id: str
    hunk_hash: str
    symbol: str | None
    change_kind: str | None
    source_anchors: tuple[Any, ...] = ()


_PROMPT_FILENAME = "quiz_generate.md"
log = logging.getLogger(__name__)
_PROMPT_NAME = "quiz.generate"
_MISCONCEPTION_PROMPT_NAME = "quiz.misconception_card"
_MISCONCEPTION_ARTIFACT_NAME = "misconception_cards.jsonl"
_DISTRACTOR_GATE_ARTIFACT_NAME = "distractor_gate.json"
_VALID_PRIVACY_MODES = frozenset({"strict_local", "redacted_remote", "explicit_remote"})
_MAX_RUN_ARTIFACT_TEXT_BYTES = 16 * 1024 * 1024
_QUIZ_OUTPUT_TOKEN_CAP = 18_000
_MISCONCEPTION_OUTPUT_TOKEN_CAP = 6_000
_MAX_MISCONCEPTION_CARDS = 30


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
    quiz_output_token_cap: int | None = None,
    misconception_output_token_cap: int | None = None,
    question_count: int = 3,
    on_sub_progress: Callable[[str], None] | None = None,
    structured_output_mode: EnforcementMode = "json_object",
    structured_validation_retries: int = 1,
    active_practice: bool | None = None,
) -> tuple[QuizArtifactPaths, tuple[QuizQuestion, ...]]:
    bundle = load_redacted_run_bundle(
        run_id=run_id,
        run_path=run_path,
        workspace_root=workspace_root,
    )
    lesson_text = _read_required_text(run_path / "lesson" / "lesson.full.md")
    effective_active_practice = _active_practice_mode(bundle.metadata, active_practice)
    if on_sub_progress is not None:
        on_sub_progress("Generating quiz questions (1/2)")
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
        output_token_cap=quiz_output_token_cap,
        question_count=question_count,
        active_practice=effective_active_practice,
        structured_output_mode=structured_output_mode,
        structured_validation_retries=structured_validation_retries,
    )
    question_set = parse_quiz_payload(payload, require_choices=True)
    _validate_active_practice_questions(
        question_set.questions,
        active_practice=effective_active_practice,
        question_count=question_count,
    )
    questions = _materialize_question_ids(run_id, question_set.questions)
    available_anchors = load_evidence_anchors(run_path)
    _validate_question_sources(
        questions,
        claims=_load_claim_records(run_path / "claims.jsonl"),
        available_anchors=available_anchors,
        document=bundle.metadata.get("source_kind") == "document",
    )
    if on_sub_progress is not None:
        on_sub_progress("Generating misconception cards (2/2)")
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
        output_token_cap=misconception_output_token_cap,
        structured_output_mode=structured_output_mode,
        structured_validation_retries=structured_validation_retries,
    )
    quiz_dir = run_path / "quiz"
    quiz_path = quiz_dir / "quiz.jsonl"
    misconception_path = quiz_dir / _MISCONCEPTION_ARTIFACT_NAME
    distractor_gate_path = quiz_dir / _DISTRACTOR_GATE_ARTIFACT_NAME
    write_quiz_questions_jsonl(quiz_path, questions, overwrite=overwrite)
    write_misconception_cards(list(misconception_cards), misconception_path)
    try:
        write_distractor_gate_report(
            distractor_gate_path,
            build_distractor_gate_report(run_id=run_id, questions=questions),
        )
    except (OSError, ValueError, InputError, StorageError) as exc:
        log.warning("distractor gate report write failed: %s", type(exc).__name__)
    return (
        QuizArtifactPaths(
            quiz_dir=quiz_dir,
            quiz_path=quiz_path,
            misconception_path=misconception_path,
            distractor_gate_path=distractor_gate_path,
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
    available_anchors = load_evidence_anchors(run_path, metadata)
    source_ref = str(metadata["source_ref"])
    claims = _load_claim_records(run_path / "claims.jsonl")
    claim_lookup = {claim.claim_id: claim for claim in claims}
    line_maps = load_line_map_records(run_path / "line_map.json")
    symbols = load_symbol_records(run_path / "symbols.json")
    cards: list[ReviewCard] = []
    questions_with_card_ids: list[QuizQuestion] = []
    for question in questions:
        claim = _resolve_primary_claim(question, claim_lookup)
        if claim.source_anchors and not validate_source_anchor_references(
            claim.source_anchors, available_anchors
        ):
            raise InputError("review card claim anchor does not match the persisted source")
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
                source_anchors=list(anchor.source_anchors),
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
    question_count: int = 3,
    output_lang: str = "en",
    source_anchors: Any = (),
    review_context: Any = None,
    active_practice: bool | None = None,
) -> str:
    effective_active_practice = _active_practice_mode(metadata, active_practice)
    metadata_payload = {
        "run_id": metadata["run_id"],
        "source_kind": metadata["source_kind"],
        "source_ref": metadata["source_ref"],
        "capability_level": metadata["capability_level"],
        "degraded_flags": metadata.get("degraded_flags", {}),
        "learnability": metadata.get("learnability", {}),
        "active_practice": effective_active_practice,
    }
    return "\n\n".join(
        (
            _source_quiz_prompt(
                prompt_text.replace("{question_count}", str(question_count)),
                claims_text=claims_text,
                source_anchors=source_anchors,
                document=metadata.get("source_kind") == "document",
                active_practice=effective_active_practice,
            ).strip(),
            "## Requested practice mode\nactive_practice=" + str(effective_active_practice).lower(),
            "## Output language\n" + prompt_language_instruction(output_lang),
            "## Run metadata\n```json\n"
            + json.dumps(metadata_payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n```",
            "## lesson.full.md\n```markdown\n" + lesson_text.rstrip() + "\n```",
            "## claims.jsonl\n```json\n" + claims_text.rstrip() + "\n```",
            source_prompt_section(patch_text, metadata),
            evidence_prompt_section(source_anchors),
            review_prompt_section(review_context),
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
    output_token_cap: int | None = None,
    question_count: int = 3,
    structured_output_mode: EnforcementMode = "json_object",
    structured_validation_retries: int = 1,
    active_practice: bool = False,
) -> str:
    if type(question_count) is not int:
        raise InputError("quiz question_count must be an integer")
    if question_count < 1 or question_count > 30:
        raise InputError("quiz question_count must be between 1 and 30")
    accepted_claims = _parse_claim_records(bundle.claims_text)
    prompt_text = load_quiz_prompt()
    resolved_prompt_text = prompt_text.replace("{question_count}", str(question_count))
    payload_text = build_quiz_payload(
        prompt_text=prompt_text,
        metadata=bundle.metadata,
        lesson_text=lesson_text,
        claims_text=bundle.claims_text,
        source_anchors=getattr(bundle, "source_anchors", ()),
        review_context=getattr(bundle, "review_context", None),
        patch_text=bundle.patch_text,
        line_map_text=bundle.line_map_text,
        symbols_text=bundle.symbols_text,
        question_count=question_count,
        active_practice=active_practice,
        output_lang=output_lang,
    )
    prompt_fingerprint = hashlib.sha256(resolved_prompt_text.encode("utf-8")).hexdigest()[:12]
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
        output_token_budget=_positive_output_token_value(
            output_token_budget,
            DEFAULT_OUTPUT_TOKEN_BUDGET,
        ),
    )
    schema_spec = schema_spec_for("quiz_generate.v1")
    request = ProviderRequest(
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
        max_output_tokens=_resolve_request_output_tokens(
            provider_config=provider_config,
            output_token_budget=output_token_budget,
            output_token_cap=output_token_cap,
            default_output_token_cap=_QUIZ_OUTPUT_TOKEN_CAP,
        ),
        thinking_level=provider_config.thinking_level,
        **structured_request_kwargs(
            schema_name="quiz_generate.v1",
            provider_class=provider_config.provider_class,
            mode=structured_output_mode,
        ),
    )

    def _validate(payload: str) -> str:
        parsed = strict_json_envelope(payload, root_key="questions", allow_empty=False)
        _validate_schema_payload(schema_spec, parsed)
        parsed_questions = parse_quiz_payload(payload, require_choices=True)
        _validate_active_practice_questions(
            parsed_questions.questions,
            active_practice=active_practice,
            question_count=question_count,
        )
        return payload

    def _fallback(payload: str) -> str:
        require_complete_json_for_fallback(payload)
        parsed_questions = parse_quiz_payload(payload, require_choices=True)
        _validate_active_practice_questions(
            parsed_questions.questions,
            active_practice=active_practice,
            question_count=question_count,
        )
        return payload

    def _validate_sources(payload: str) -> None:
        _validate_question_sources(
            parse_quiz_payload(payload, require_choices=True).questions,
            claims=accepted_claims,
            available_anchors=getattr(bundle, "source_anchors", ()),
            document=bundle.metadata.get("source_kind") == "document",
        )

    try:
        result = generate_with_validation_retry(
            provider=provider,
            request=request,
            schema_spec=schema_spec,
            parse=_validate,
            fallback_parse=_fallback,
            post_parse_validate=_validate_sources,
            max_validation_retries=structured_validation_retries,
        )
    finally:
        provider.close()
    return result.value


def _validate_question_sources(
    questions: Sequence[QuizQuestion],
    *,
    claims: Sequence[ClaimRecord],
    available_anchors: Sequence[SourceAnchor],
    document: bool,
) -> None:
    accepted = {claim.claim_id: claim for claim in claims if claim.status != "rejected"}
    for question in questions:
        if not question.source_claims or any(cid not in accepted for cid in question.source_claims):
            raise InputError("quiz must refer to accepted source claims")
        if document and (not question.source_anchors or question.evidence):
            raise InputError("document quiz must use document source anchors without diff evidence")
        if question.source_anchors:
            if not validate_source_anchor_references(question.source_anchors, available_anchors):
                raise InputError("quiz source anchor does not match the persisted source")
            associated = tuple(
                anchor for cid in question.source_claims for anchor in accepted[cid].source_anchors
            )
            if not validate_source_anchor_references(question.source_anchors, associated):
                raise InputError("quiz source anchor is not associated with its source claims")


def _source_quiz_prompt(
    prompt_text: str,
    *,
    claims_text: str,
    source_anchors: Sequence[SourceAnchor],
    document: bool,
    active_practice: bool,
) -> str:
    if not document:
        return prompt_text
    available = {anchor.anchor_id: anchor for anchor in source_anchors}
    selected = next(
        (
            (claim, anchor)
            for claim in _parse_claim_records(claims_text)
            if claim.status != "rejected"
            for anchor in claim.source_anchors
            if available.get(anchor.anchor_id) == anchor
        ),
        None,
    )
    if selected is None:
        raise InputError("document quiz requires accepted claims with persisted source anchors")
    claim, anchor = selected
    example: dict[str, object] = {
        "question": "Replace this example with a concrete question grounded in this document.",
        "expected_answer": anchor.quote,
        "quiz_kind": "transfer" if active_practice else "recall",
        "answer_mode": "open" if active_practice else "multiple_choice",
        "source_claims": [claim.claim_id],
        "concepts": [],
        "evidence": [],
        "source_anchors": [anchor.model_dump(mode="json")],
    }
    if active_practice:
        example["exercise_kind"] = "prediction"
    else:
        example["choices"] = [
            {"label": "A", "text": anchor.quote, "is_correct": True},
            {
                "label": "B",
                "text": "The document proves an unstated runtime result.",
                "is_correct": False,
            },
            {"label": "C", "text": "The document states the opposite rule.", "is_correct": False},
            {
                "label": "D",
                "text": "The document makes no statement about this concept.",
                "is_correct": False,
            },
        ]
    section = (
        "## Document source example\n"
        "This is a document, not a diff. Every question must set evidence to []. "
        "Put complete SourceAnchor objects ONLY in source_anchors; never in evidence. "
        "Do not use legacy file/line evidence for a document. Copy every anchor field "
        "exactly from Validated source anchors, including locator, content_hash and quote. "
        "Each selected anchor must also belong to a selected accepted source_claim. "
        "This field-placement example uses a real supplied anchor and claim; "
        "replace its example question/choices with the requested tasks.\n```json\n"
        + json.dumps({"questions": [example]}, ensure_ascii=False, indent=2)
        + "\n```\n\n"
    )
    before, marker, remainder = prompt_text.partition("## Diff source example\n")
    if not marker:
        return prompt_text + "\n\n" + section
    _, rules, after = remainder.partition("## Generation rules\n")
    if not rules:
        raise InputError("quiz prompt source-example section is incomplete")
    return before + section + rules + after


def _active_practice_mode(metadata: Mapping[str, object], override: bool | None) -> bool:
    value = metadata.get("active_practice", False) if override is None else override
    if type(value) is not bool:
        raise InputError("active_practice must be a boolean")
    return value


def _validate_active_practice_questions(
    questions: Sequence[QuizQuestion],
    *,
    active_practice: bool,
    question_count: int,
) -> None:
    if not active_practice:
        return
    if len(questions) != question_count:
        raise ValueError(f"active practice requires exactly {question_count} questions")
    if any(
        question.quiz_kind != "transfer"
        or question.answer_mode != "open"
        or question.choices is not None
        or question.exercise_kind is None
        for question in questions
    ):
        raise ValueError(
            "active practice requires transfer/open questions with exercise_kind and no choices"
        )
    expected = {"prediction", "completion", "error_reason"}
    if question_count == 1:
        expected = {"prediction"}
    elif question_count == 2:
        expected = {"prediction", "completion"}
    if not expected.issubset({question.exercise_kind for question in questions}):
        raise ValueError("active practice must cover exercise_kind: " + ", ".join(sorted(expected)))


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
    output_token_cap: int | None = None,
    structured_output_mode: EnforcementMode = "json_object",
    structured_validation_retries: int = 1,
) -> tuple[MisconceptionCard, ...]:
    prompt_text = load_misconception_prompt()
    document_source = bundle.metadata.get("source_kind") == "document"
    if document_source:
        prompt_text = (
            prompt_text.replace("code reviewer", "source reviewer")
            .replace("code diff", "source document")
            .replace("code change", "source passage")
            .replace("specific code evidence (file:line format)", "provided document anchor id")
        )
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
    if document_source:
        payload_text += "\n\n" + evidence_prompt_section(bundle.source_anchors)
        payload_text += (
            "\n\nEvidence refs must be exact supplied anchor_id values. "
            "Corrections are semantic guidance, not verified execution outcomes."
        )
    payload_text += "\n\n" + review_prompt_section(getattr(bundle, "review_context", None))
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
        output_token_budget=_positive_output_token_value(
            output_token_budget,
            DEFAULT_OUTPUT_TOKEN_BUDGET,
        ),
    )
    schema_spec = schema_spec_for("quiz_misconception_card.v1")
    request = ProviderRequest(
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
        max_output_tokens=_resolve_request_output_tokens(
            provider_config=provider_config,
            output_token_budget=output_token_budget,
            output_token_cap=output_token_cap,
            default_output_token_cap=_MISCONCEPTION_OUTPUT_TOKEN_CAP,
        ),
        thinking_level=provider_config.thinking_level,
        **structured_request_kwargs(
            schema_name="quiz_misconception_card.v1",
            provider_class=provider_config.provider_class,
            mode=structured_output_mode,
        ),
    )

    def _validate(payload: str) -> str:
        parsed = strict_json_envelope(payload, root_key="cards", allow_empty=True)
        _validate_schema_payload(schema_spec, parsed)
        cards = parse_misconception_cards(payload)
        _validate_misconception_card_count(cards)
        _validate_document_misconception_refs(cards)
        if parsed["cards"] and not cards:
            raise ValueError("misconception payload must contain at least one card")
        return payload

    def _fallback(payload: str) -> str:
        require_complete_json_for_fallback(payload)
        cards = parse_misconception_cards(payload)
        _validate_misconception_card_count(cards)
        _validate_document_misconception_refs(cards)
        if not cards and not has_explicit_empty_misconception_cards(payload):
            raise ValueError("misconception payload must contain at least one card")
        return payload

    def _validate_document_misconception_refs(cards: Sequence[MisconceptionCard]) -> None:
        if not document_source:
            return
        available = {anchor.anchor_id for anchor in bundle.source_anchors}
        if any(
            card.evidence_ref not in available or card.run_id not in {"", run_id} for card in cards
        ):
            raise ValueError("misconception evidence must refer to a supplied document anchor")

    try:
        result = generate_with_validation_retry(
            provider=provider,
            request=request,
            schema_spec=schema_spec,
            parse=_validate,
            fallback_parse=_fallback,
            max_validation_retries=structured_validation_retries,
        )
    finally:
        provider.close()
    cards = parse_misconception_cards(result.value)
    _validate_misconception_card_count(cards)
    return tuple(replace(card, run_id=card.run_id or run_id) for card in cards)


def _validate_misconception_card_count(cards: Sequence[MisconceptionCard]) -> None:
    if len(cards) > _MAX_MISCONCEPTION_CARDS:
        raise ValueError(
            f"misconception payload must contain at most {_MAX_MISCONCEPTION_CARDS} cards"
        )


def _validate_schema_payload(schema_spec: Any, parsed: dict[str, Any]) -> None:
    if schema_spec.pydantic_model is None:
        raise ValueError(f"{schema_spec.schema_id} schema is missing a validation model")
    schema_spec.pydantic_model.model_validate(parsed)


def _resolve_request_output_tokens(
    *,
    provider_config: ProviderConfig,
    output_token_budget: int | None,
    output_token_cap: int | None,
    default_output_token_cap: int,
) -> int:
    limits = resolve_model_limits(
        str(provider_config.provider_class),
        provider_config.model_name,
        provider_config,
    )
    model_max_candidates = [limits.max_output_tokens]
    if provider_config.max_output_tokens and provider_config.max_output_tokens > 0:
        model_max_candidates.append(provider_config.max_output_tokens)
    return effective_output_cap(
        requested_step_cap=output_token_cap,
        llm_output_budget=output_token_budget,
        resolved_model_max_output=min(model_max_candidates),
        default_step_cap=default_output_token_cap,
    )


def _positive_output_token_value(value: int | None, default: int) -> int:
    return value if value is not None and value > 0 else default


def _materialize_question_ids(
    run_id: str,
    questions: Sequence[QuizQuestion],
) -> tuple[QuizQuestion, ...]:
    materialized: list[QuizQuestion] = []
    for index, question in enumerate(questions, start=1):
        generated_id = _make_prefixed_digest(
            "quiz_exercise" if question.exercise_kind is not None else "quiz",
            run_id,
            index,
            question.question,
        )
        question_id = (
            generated_id
            if question.exercise_kind is not None
            else question.question_id or generated_id
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
            if len(terms) >= 30:
                return terms
    return terms


def _load_claim_records(path: Path) -> tuple[ClaimRecord, ...]:
    if not path.exists():
        raise InputError(f"verified claims artifact does not exist: {path}")
    claims = _parse_claim_records(_read_required_text(path))
    if not claims:
        raise InputError(f"claims artifact is empty: {path}")
    return claims


def _parse_claim_records(text: str) -> tuple[ClaimRecord, ...]:
    claims: list[ClaimRecord] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = safe_json_loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            raise InputError(f"invalid claims.jsonl line {index}") from exc
        claims.append(ClaimRecord.model_validate(payload))
    return tuple(claims)


def _resolve_primary_claim(
    question: QuizQuestion,
    claim_lookup: dict[str, ClaimRecord],
) -> ClaimRecord:
    for claim_id in question.source_claims:
        claim = claim_lookup.get(claim_id)
        if claim is not None and claim.status != "rejected":
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
        "card_exercise" if question.exercise_kind is not None else "card",
        claim.run_id,
        question.question_id or question.question,
        concept,
    )


def _resolve_claim_anchor(
    claim: ClaimRecord,
    line_maps: Sequence[FileLineMap],
    symbols: Sequence[SymbolRecord],
) -> _ResolvedAnchor:
    if claim.source_anchors and claim.source_anchors[0].source_kind == "document":
        anchor = claim.source_anchors[0]
        namespace = "document-anchor"
        return _ResolvedAnchor(
            file_id=f"{namespace}:{hashlib.sha256(anchor.file.encode('utf-8')).hexdigest()[:32]}",
            display_path=anchor.file,
            hunk_id=f"{namespace}:{anchor.anchor_id}",
            hunk_hash=anchor.content_hash,
            symbol=None,
            change_kind=None,
            source_anchors=tuple(claim.source_anchors),
        )
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
                    source_anchors=tuple(claim.source_anchors),
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
    return read_artifact_text_no_follow(path, max_bytes=_MAX_RUN_ARTIFACT_TEXT_BYTES)


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
