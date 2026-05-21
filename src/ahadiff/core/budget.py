from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ahadiff.llm.cost import ResolvedModelLimits

PROVIDER_CONTEXT_RATIO = 0.90
RISK_WARN_RATIO = 0.50
SAFETY_RESERVE_RATIO = 0.12
MIN_SAFETY_RESERVE = 2_000
MAX_SAFETY_RESERVE = 50_000
DEFAULT_SYSTEM_PROMPT_TOKENS = 1_220
MIN_DIFF_TOKEN_FLOOR = 2_400
DIFF_TOKEN_MARGIN = 0.10
DEFAULT_DIFF_CHARS_PER_TOKEN = 3.5
DEFAULT_DIFF_TOKENS_PER_LINE = 24
AUTO_LINES_PER_FILE = 50
MIN_MAX_FILES = 1
MAX_MAX_FILES = 500
MIN_HARD_LIMIT = 100
MAX_HARD_LIMIT = 100_000
MIN_PATCH_BYTES = 100_000
MAX_PATCH_BYTES_RUNTIME = 50 * 1024 * 1024
RAW_PATCH_INTAKE_MULTIPLIER = 8

_CJK_RANGES = (
    (0x1100, 0x11FF),
    (0x3000, 0x303F),
    (0x3040, 0x309F),
    (0x30A0, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xAC00, 0xD7AF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
    (0x2CEB0, 0x2EBEF),
    (0x30000, 0x3134F),
)


@dataclass(frozen=True)
class CaptureRecommendation:
    mode: Literal["auto", "manual"]
    max_files: int
    hard_limit: int
    max_patch_bytes: int
    runtime_max_patch_bytes: int
    payload_byte_budget: int
    context_window: int | None
    max_input_tokens: int
    max_output_tokens: int
    diff_token_budget: int
    safety_reserve: int
    output_reserve: int
    system_prompt_tokens: int
    fits_minimums: bool
    model_name: str
    source: str
    cjk_ratio: float
    cjk_factor: float
    warnings: list[str]


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def _is_cjk_char(char: str) -> bool:
    codepoint = ord(char)
    return any(start <= codepoint <= end for start, end in _CJK_RANGES)


def compute_cjk_ratio(text: str) -> float:
    sample = text[:20_000]
    if not sample:
        return 0.0
    counted = [char for char in sample if not char.isspace()]
    if not counted:
        return 0.0
    cjk_count = sum(1 for char in counted if _is_cjk_char(char))
    return cjk_count / len(counted)


def compute_cjk_factor(text: str) -> float:
    """Sample CJK ratio from text and return a conservative token density factor."""
    cjk_ratio = compute_cjk_ratio(text)
    return max(0.5, 1.0 - cjk_ratio * 0.5)


def _ratio_from_factor(cjk_factor: float) -> float:
    if cjk_factor >= 1.0:
        return 0.0
    return max(0.0, min(1.0, (1.0 - cjk_factor) / 0.5))


def compute_recommended_capture(
    *,
    limits: ResolvedModelLimits,
    output_reserve: int,
    system_prompt_tokens: int = DEFAULT_SYSTEM_PROMPT_TOKENS,
    diff_chars_per_token: float = DEFAULT_DIFF_CHARS_PER_TOKEN,
    diff_tokens_per_line: int = DEFAULT_DIFF_TOKENS_PER_LINE,
    cjk_factor: float = 1.0,
    model_name: str = "",
) -> CaptureRecommendation:
    basis = limits.max_context_tokens or limits.max_input_tokens
    safety_reserve = _clamp(
        math.ceil(basis * SAFETY_RESERVE_RATIO),
        MIN_SAFETY_RESERVE,
        MAX_SAFETY_RESERVE,
    )

    effective_input_tokens = limits.max_input_tokens
    if limits.max_context_tokens is not None:
        effective_input_tokens = min(
            effective_input_tokens,
            max(limits.max_context_tokens - output_reserve, 0),
        )
    provider_input_budget = math.floor(effective_input_tokens * PROVIDER_CONTEXT_RATIO)
    risk_limit = math.floor(basis * RISK_WARN_RATIO)
    diff_budget = max(
        0,
        min(provider_input_budget - system_prompt_tokens - safety_reserve, risk_limit),
    )

    hard_limit = _clamp(
        math.floor(diff_budget / diff_tokens_per_line),
        MIN_HARD_LIMIT,
        MAX_HARD_LIMIT,
    )
    if diff_budget < MIN_DIFF_TOKEN_FLOOR:
        max_files = 1
    else:
        max_files = _clamp(
            math.ceil(hard_limit / AUTO_LINES_PER_FILE),
            MIN_MAX_FILES,
            MAX_MAX_FILES,
        )

    safe_cjk_factor = 0.5 if not math.isfinite(cjk_factor) else min(1.0, max(cjk_factor, 0.5))
    payload_byte_budget = math.floor(
        diff_budget * diff_chars_per_token * safe_cjk_factor / (1.0 + DIFF_TOKEN_MARGIN)
    )
    max_patch_bytes = _clamp(
        max(MIN_PATCH_BYTES, payload_byte_budget * RAW_PATCH_INTAKE_MULTIPLIER),
        MIN_PATCH_BYTES,
        MAX_PATCH_BYTES_RUNTIME,
    )

    warnings = list(limits.warnings)
    if diff_budget < MIN_DIFF_TOKEN_FLOOR:
        warnings.append("recommended diff budget is below the minimum learning floor")

    return CaptureRecommendation(
        mode="auto",
        max_files=max_files,
        hard_limit=hard_limit,
        max_patch_bytes=max_patch_bytes,
        runtime_max_patch_bytes=MAX_PATCH_BYTES_RUNTIME,
        payload_byte_budget=payload_byte_budget,
        context_window=limits.max_context_tokens,
        max_input_tokens=limits.max_input_tokens,
        max_output_tokens=limits.max_output_tokens,
        diff_token_budget=diff_budget,
        safety_reserve=safety_reserve,
        output_reserve=output_reserve,
        system_prompt_tokens=system_prompt_tokens,
        fits_minimums=diff_budget >= MIN_DIFF_TOKEN_FLOOR,
        model_name=model_name,
        source=limits.source,
        cjk_ratio=_ratio_from_factor(safe_cjk_factor),
        cjk_factor=safe_cjk_factor,
        warnings=warnings,
    )


def compute_output_reserve(
    *,
    config_output_budget: int | None,
    per_step_caps: dict[str, int],
    provider_max_output: int | None,
    thinking_budget: int | None,
) -> tuple[int, list[str]]:
    candidates = [
        value
        for value in (
            config_output_budget,
            max(per_step_caps.values()) if per_step_caps else None,
            provider_max_output,
        )
        if value is not None and value > 0
    ]
    output_reserve = max(candidates) if candidates else DEFAULT_SYSTEM_PROMPT_TOKENS
    warnings: list[str] = []
    if thinking_budget is not None and thinking_budget >= output_reserve:
        warnings.append(
            f"thinking_budget {thinking_budget} is greater than or equal to output reserve "
            f"{output_reserve}"
        )
    return output_reserve, warnings


def manual_capture_recommendation(
    *,
    max_files: int,
    hard_limit: int,
    max_patch_bytes: int,
    limits: ResolvedModelLimits,
    output_reserve: int,
    model_name: str = "",
    system_prompt_tokens: int = DEFAULT_SYSTEM_PROMPT_TOKENS,
    diff_tokens_per_line: int = DEFAULT_DIFF_TOKENS_PER_LINE,
) -> CaptureRecommendation:
    recommendation = compute_recommended_capture(
        limits=limits,
        output_reserve=output_reserve,
        system_prompt_tokens=system_prompt_tokens,
        diff_tokens_per_line=diff_tokens_per_line,
        model_name=model_name,
    )
    return replace(
        recommendation,
        mode="manual",
        max_files=max_files,
        hard_limit=hard_limit,
        max_patch_bytes=min(max_patch_bytes, MAX_PATCH_BYTES_RUNTIME),
        payload_byte_budget=math.floor(
            min(max_patch_bytes, MAX_PATCH_BYTES_RUNTIME) / RAW_PATCH_INTAKE_MULTIPLIER
        ),
        diff_token_budget=max(0, hard_limit * diff_tokens_per_line),
        fits_minimums=hard_limit * diff_tokens_per_line >= MIN_DIFF_TOKEN_FLOOR,
    )


__all__ = [
    "AUTO_LINES_PER_FILE",
    "DEFAULT_DIFF_CHARS_PER_TOKEN",
    "DEFAULT_DIFF_TOKENS_PER_LINE",
    "DEFAULT_SYSTEM_PROMPT_TOKENS",
    "DIFF_TOKEN_MARGIN",
    "MAX_HARD_LIMIT",
    "MAX_MAX_FILES",
    "MAX_PATCH_BYTES_RUNTIME",
    "MAX_SAFETY_RESERVE",
    "MIN_DIFF_TOKEN_FLOOR",
    "MIN_HARD_LIMIT",
    "MIN_MAX_FILES",
    "MIN_PATCH_BYTES",
    "MIN_SAFETY_RESERVE",
    "PROVIDER_CONTEXT_RATIO",
    "RAW_PATCH_INTAKE_MULTIPLIER",
    "RISK_WARN_RATIO",
    "SAFETY_RESERVE_RATIO",
    "CaptureRecommendation",
    "compute_cjk_factor",
    "compute_cjk_ratio",
    "compute_output_reserve",
    "compute_recommended_capture",
    "manual_capture_recommendation",
]
