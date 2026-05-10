from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.i18n import prompt_language_instruction
from ahadiff.llm import DEFAULT_OUTPUT_TOKEN_BUDGET, ProviderRequest, make_provider
from ahadiff.safety.ignore import AllowlistPolicy
from ahadiff.safety.redact import redaction_pipeline

from .extract import (
    parse_claim_candidates_text,
    write_claim_candidates_jsonl,
)

if TYPE_CHECKING:
    import httpx

    from ahadiff.contracts import PrivacyMode, ProviderConfig
    from ahadiff.core.config import SecurityConfig

    from .schema import ClaimCandidate


_CLAIM_EXTRACT_EVAL_VERSION = "claim-extract-runtime-v1"
_VALID_PRIVACY_MODES = frozenset({"strict_local", "redacted_remote", "explicit_remote"})
_MAX_RUN_ARTIFACT_TEXT_BYTES = 16 * 1024 * 1024
_DEFAULT_CLAIM_OUTPUT_TOKEN_CAP = 16_000
_REQUIRED_CONTEXT_METADATA_FIELDS = (
    "run_id",
    "source_kind",
    "source_ref",
    "capability_level",
)


class _BudgetKwargs(TypedDict, total=False):
    input_token_budget: int
    output_token_budget: int


_FALLBACK_CLAIM_EXTRACT_PROMPT = """
# Claim Extract Prompt

You are extracting verifiable claims from a redacted diff package.

## Output contract

- Return JSON only. No markdown, no prose.
- Preferred envelope:

```json
{
  "claims": [
    {
      "claim_id": "optional-if-caller-fills",
      "run_id": "optional-if-caller-fills",
      "text": "Short factual claim grounded in the diff",
      "source_hunks": [
        {"file": "src/example.py", "start": 12, "end": 18, "side": "new"}
      ],
      "symbols": ["Example.run"],
      "hunk_ids": ["hunk_deadbeef1234"]
    }
  ]
}
```

## Extraction rules

- Only emit claims that can be grounded in the provided diff/package.
- Each claim must cite at least one `source_hunk`.
- Each `source_hunk` must include `side`:
  - use `"new"` for added/modified post-change lines,
  - use `"old"` for deleted lines or rename-from references,
  - use `"either"` only when old/new cannot be disambiguated from the provided
    evidence and the verifier can infer it from path/hunk context,
  - use `"new"` for rename-to references.
- Use symbols only when the diff or symbol index actually supports them.
- Prefer narrow factual claims over broad interpretations.
- Do not mention files outside the provided patch.
- Avoid risky wording such as `always`, `never`, `secure`, `faster` unless the diff
  directly supports it.
- If the diff only shows deletion or rename, make that explicit in `text`.
"""


def extract_claim_candidates_from_run(
    *,
    run_id: str,
    run_path: Path,
    workspace_root: Path,
    provider_config: ProviderConfig,
    api_key: str | None,
    security_config: SecurityConfig,
    output_path: Path,
    overwrite: bool = False,
    max_concurrent: int = 3,
    qps_limit: int = 3,
    retry_attempts: int = 3,
    request_timeout_seconds: int = 30,
    client: httpx.Client | None = None,
    privacy_mode: PrivacyMode | None = None,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
    claim_output_token_cap: int | None = None,
    output_lang: str = "en",
) -> tuple[Path, tuple[ClaimCandidate, ...]]:
    prompt_text = load_claim_extract_prompt()
    metadata = _load_run_json(run_path / "metadata.json")
    patch_text = _read_required_text(run_path / "patch.diff")
    line_map_text = _read_required_text(run_path / "line_map.json")
    symbols_text = _read_required_text(run_path / "symbols.json")
    payload_text = build_claim_extract_payload(
        prompt_text=prompt_text,
        metadata=metadata,
        patch_text=patch_text,
        line_map_text=line_map_text,
        symbols_text=symbols_text,
        output_lang=output_lang,
    )
    prompt_fingerprint = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:12]
    metadata_privacy_mode = _privacy_mode_from_metadata(metadata)
    resolved_privacy_mode = _resolve_claim_extract_privacy_mode(
        metadata_privacy_mode,
        privacy_mode,
    )
    source_ref = str(_claim_extract_context_metadata(metadata)["source_ref"])
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
    budget_kwargs: _BudgetKwargs = {}
    if input_token_budget is not None:
        budget_kwargs["input_token_budget"] = input_token_budget
    if output_token_budget is not None:
        budget_kwargs["output_token_budget"] = _positive_output_token_value(
            output_token_budget,
            DEFAULT_OUTPUT_TOKEN_BUDGET,
        )
    provider = make_provider(
        provider_config,
        api_key=api_key,
        security_config=security_config,
        workspace_root=workspace_root,
        client=client,
        max_concurrent=max_concurrent,
        qps_limit=qps_limit,
        retry_attempts=retry_attempts,
        request_timeout_seconds=request_timeout_seconds,
        execution_origin="claims_extract",
        **budget_kwargs,
    )
    try:
        response = provider.generate(
            ProviderRequest(
                prompt_name="claim.extract",
                prompt_fingerprint=prompt_fingerprint,
                prompt_version=prompt_fingerprint,
                eval_bundle_version=_CLAIM_EXTRACT_EVAL_VERSION,
                model=provider_config.model_name,
                payload_text=payload_text,
                diff_content=patch_text,
                source_ref=source_ref,
                privacy_mode=resolved_privacy_mode,
                redacted_payload_text=redacted_payload_text,
                findings=findings,
                response_format="json",
                output_lang=output_lang,
                max_output_tokens=_resolve_claim_request_max_output_tokens(
                    provider_max_output_tokens=provider_config.max_output_tokens,
                    output_token_budget=output_token_budget,
                    claim_output_token_cap=claim_output_token_cap,
                ),
                thinking_level=provider_config.thinking_level,
            )
        )
    finally:
        provider.close()
    candidates = parse_claim_candidates_text(
        response.content,
        default_run_id=run_id,
    )
    return write_claim_candidates_jsonl(output_path, candidates, overwrite=overwrite), candidates


def _resolve_claim_request_max_output_tokens(
    *,
    provider_max_output_tokens: int | None,
    output_token_budget: int | None,
    claim_output_token_cap: int | None,
) -> int:
    output_budget = _positive_output_token_value(output_token_budget, DEFAULT_OUTPUT_TOKEN_BUDGET)
    cap = _positive_output_token_value(
        claim_output_token_cap,
        _DEFAULT_CLAIM_OUTPUT_TOKEN_CAP,
    )
    limits = [output_budget, cap]
    if provider_max_output_tokens and provider_max_output_tokens > 0:
        limits.append(provider_max_output_tokens)
    return min(limits)


def _positive_output_token_value(value: int | None, default: int) -> int:
    return value if value is not None and value > 0 else default


def build_claim_extract_payload(
    *,
    prompt_text: str,
    metadata: dict[str, Any],
    patch_text: str,
    line_map_text: str,
    symbols_text: str,
    output_lang: str = "en",
) -> str:
    context_metadata = _claim_extract_context_metadata(metadata)
    return "\n\n".join(
        (
            prompt_text.strip(),
            "## Output language\n" + prompt_language_instruction(output_lang),
            "## Run metadata\n```json\n"
            + json.dumps(context_metadata, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n```",
            "## patch.diff\n```diff\n" + patch_text.rstrip() + "\n```",
            "## line_map.json\n```json\n" + line_map_text.rstrip() + "\n```",
            "## symbols.json\n```json\n" + symbols_text.rstrip() + "\n```",
        )
    )


def load_claim_extract_prompt() -> str:
    prompt_path = Path(__file__).resolve().parents[3] / "prompts" / "claim_extract.md"
    if prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8")
    try:
        package_prompt = files("ahadiff").joinpath("prompts", "claim_extract.md")
        if package_prompt.is_file():
            return package_prompt.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass
    return _FALLBACK_CLAIM_EXTRACT_PROMPT


def _claim_extract_context_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in _REQUIRED_CONTEXT_METADATA_FIELDS if metadata.get(key) is None]
    if missing:
        raise InputError("run metadata missing required field(s): " + ", ".join(missing))
    degraded_flags = metadata.get("degraded_flags", {})
    if not isinstance(degraded_flags, dict):
        raise InputError("run metadata field degraded_flags must be an object")
    return {
        "run_id": metadata["run_id"],
        "source_kind": metadata["source_kind"],
        "source_ref": metadata["source_ref"],
        "capability_level": metadata["capability_level"],
        "degraded_flags": degraded_flags,
    }


def _privacy_mode_from_metadata(metadata: dict[str, Any]) -> PrivacyMode:
    raw_value = metadata.get("privacy_mode", "strict_local")
    if raw_value not in _VALID_PRIVACY_MODES:
        raise InputError(f"unsupported run metadata privacy_mode: {raw_value!r}")
    return cast("PrivacyMode", raw_value)


def _resolve_claim_extract_privacy_mode(
    metadata_privacy_mode: PrivacyMode,
    requested_privacy_mode: PrivacyMode | None,
) -> PrivacyMode:
    if requested_privacy_mode is None:
        return metadata_privacy_mode
    if metadata_privacy_mode == "redacted_remote" and requested_privacy_mode == "explicit_remote":
        return "redacted_remote"
    return requested_privacy_mode


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
    "build_claim_extract_payload",
    "extract_claim_candidates_from_run",
    "load_claim_extract_prompt",
]
