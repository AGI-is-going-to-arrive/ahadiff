from __future__ import annotations

import math
from dataclasses import asdict
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from starlette.testclient import TestClient

from ahadiff.core.budget import (
    CaptureRecommendation,
    compute_cjk_factor,
    compute_cjk_ratio,
    compute_output_reserve,
    compute_recommended_capture,
)
from ahadiff.core.config import load_config
from ahadiff.llm.cost import ResolvedModelLimits
from ahadiff.serve import ServeState, create_app, routes_learn

if TYPE_CHECKING:
    from pathlib import Path


def _limits(context: int, output: int) -> ResolvedModelLimits:
    return ResolvedModelLimits(
        max_context_tokens=context,
        max_input_tokens=max(context - output, 0),
        max_output_tokens=output,
        source="live",
        input_source="total_derived",
        output_source="live",
    )


@pytest.mark.parametrize(
    ("context", "output", "expected_hard_limit", "expected_max_files", "expected_fits"),
    [
        (4_096, 4_096, 100, 1, False),
        (4_096, 24_000, 100, 1, False),
        (32_768, 4_096, 682, 14, True),
        (32_768, 24_000, 114, 3, True),
        (128_000, 24_000, 2_666, 54, True),
        (200_000, 24_000, 4_166, 84, True),
        (1_000_000, 24_000, 20_833, 417, True),
    ],
)
def test_compute_recommended_capture_verification_cases(
    context: int,
    output: int,
    expected_hard_limit: int,
    expected_max_files: int,
    expected_fits: bool,
) -> None:
    recommendation = compute_recommended_capture(
        limits=_limits(context, output),
        output_reserve=output,
    )

    assert recommendation.hard_limit == expected_hard_limit
    assert recommendation.max_files == expected_max_files
    assert recommendation.fits_minimums is expected_fits


def test_compute_recommended_capture_marks_output_reserve_larger_than_context_as_too_small() -> (
    None
):
    recommendation = compute_recommended_capture(
        limits=_limits(16_000, 24_000),
        output_reserve=24_000,
    )

    assert recommendation.fits_minimums is False
    assert recommendation.diff_token_budget == 0
    assert recommendation.hard_limit == 100
    assert "recommended diff budget is below the minimum learning floor" in recommendation.warnings


def test_compute_cjk_factor_reduces_char_budget_for_cjk_text() -> None:
    assert compute_cjk_factor("plain ascii diff text") == 1.0
    cjk_factor = compute_cjk_factor("中文变更说明" * 20)
    assert 0.5 <= cjk_factor < 1.0


def test_compute_cjk_ratio_and_factor_for_empty_string() -> None:
    assert compute_cjk_ratio("") == 0.0
    assert compute_cjk_factor("") == 1.0


def test_compute_cjk_ratio_and_factor_for_pure_ascii() -> None:
    text = "diff --git a/app.py b/app.py\n+print('plain ascii')\n"

    assert compute_cjk_ratio(text) == 0.0
    assert compute_cjk_factor(text) == 1.0


def test_compute_cjk_ratio_and_factor_for_pure_chinese_cjk() -> None:
    text = "中文预算调整"

    assert compute_cjk_ratio(text) == 1.0
    assert compute_cjk_factor(text) == 0.5


def test_compute_cjk_factor_scales_proportionally_for_half_cjk_half_ascii() -> None:
    text = "中文ab" * 10

    assert compute_cjk_ratio(text) == 0.5
    assert compute_cjk_factor(text) == 0.75


def test_compute_cjk_ratio_counts_punctuation_but_ignores_whitespace() -> None:
    text = "中 文，。\n\t!"

    assert compute_cjk_ratio(text) == 4 / 5
    assert compute_cjk_factor(text) == 0.6


def test_compute_cjk_ratio_detects_hiragana_and_katakana() -> None:
    text = "ひらがなカタカナ"

    assert compute_cjk_ratio(text) == 1.0
    assert compute_cjk_factor(text) == 0.5


def test_compute_cjk_ratio_detects_hangul() -> None:
    text = "한글테스트"

    assert compute_cjk_ratio(text) == 1.0
    assert compute_cjk_factor(text) == 0.5


def test_compute_cjk_ratio_detects_requested_cjk_blocks() -> None:
    text = (
        "\u1100"  # Hangul Jamo
        "\u3002"  # CJK Symbols and Punctuation
        "\u3042"  # Hiragana
        "\u30a2"  # Katakana
        "\u3400"  # CJK Extension A
        "\u4e00"  # CJK Unified Ideographs
        "\uac00"  # Hangul Syllables
        "\uf900"  # CJK Compatibility Ideographs
        "\uff76"  # Halfwidth and Fullwidth Forms
        "\U00020000"  # CJK Extension B
        "\U0002a700"  # CJK Extension C
        "\U0002b740"  # CJK Extension D
    )

    assert compute_cjk_ratio(text) == 1.0
    assert compute_cjk_factor(text) == 0.5


def test_compute_cjk_ratio_samples_code_diff_comments() -> None:
    text = "diff --git a/app.py b/app.py\n@@\n+    # 修复预算\n+    value = 1  # 中文注释\n"
    non_space_count = len([char for char in text if not char.isspace()])
    expected_ratio = 8 / non_space_count

    assert compute_cjk_ratio(text) == expected_ratio
    assert abs(compute_cjk_factor(text) - (1.0 - expected_ratio * 0.5)) < 1e-12


def test_compute_cjk_factor_uses_fixed_prefix_sample_for_large_diff_text() -> None:
    sampled_prefix = "中a" * 10_000
    large_diff = sampled_prefix + ("x" * (10 * 1024 * 1024))

    assert len(large_diff) > 10 * 1024 * 1024
    assert compute_cjk_ratio(large_diff) == compute_cjk_ratio(sampled_prefix)
    assert compute_cjk_factor(large_diff) == compute_cjk_factor(sampled_prefix)


def test_cjk_factor_floor_is_never_below_half() -> None:
    recommendation = compute_recommended_capture(
        limits=_limits(128_000, 24_000),
        output_reserve=24_000,
        cjk_factor=0.1,
    )

    assert compute_cjk_factor("中文" * 100) == 0.5
    assert recommendation.cjk_factor == 0.5


@pytest.mark.parametrize("factor", [0.0, math.nan, math.inf, -math.inf])
def test_cjk_factor_input_is_clamped_to_finite_floor(factor: float) -> None:
    recommendation = compute_recommended_capture(
        limits=_limits(128_000, 24_000),
        output_reserve=24_000,
        cjk_factor=factor,
    )

    assert recommendation.cjk_factor == 0.5
    assert recommendation.payload_byte_budget == 101_818


def test_cjk_factor_payload_byte_budget_decreases_when_factor_is_lower() -> None:
    ascii_recommendation = compute_recommended_capture(
        limits=_limits(128_000, 24_000),
        output_reserve=24_000,
        cjk_factor=1.0,
    )
    cjk_recommendation = compute_recommended_capture(
        limits=_limits(128_000, 24_000),
        output_reserve=24_000,
        cjk_factor=0.5,
    )

    assert cjk_recommendation.payload_byte_budget < ascii_recommendation.payload_byte_budget


def test_cjk_factor_lower_payload_byte_budget_expectation_holds() -> None:
    ascii_recommendation = compute_recommended_capture(
        limits=_limits(128_000, 24_000),
        output_reserve=24_000,
        cjk_factor=1.0,
    )
    cjk_recommendation = compute_recommended_capture(
        limits=_limits(128_000, 24_000),
        output_reserve=24_000,
        cjk_factor=0.5,
    )

    assert cjk_recommendation.payload_byte_budget < ascii_recommendation.payload_byte_budget


def test_compute_output_reserve_warns_when_thinking_budget_consumes_reserve() -> None:
    reserve, warnings = compute_output_reserve(
        config_output_budget=10_000,
        per_step_caps={"lesson_full_output_cap": 24_000},
        provider_max_output=16_000,
        thinking_budget=24_000,
    )

    assert reserve == 24_000
    assert warnings


def test_capture_mode_config_migrates_custom_legacy_capture_to_manual(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".ahadiff").mkdir()
    env = {"HOME": str(tmp_path / "home")}

    default_snapshot = load_config(repo, env=env)
    assert default_snapshot.values["capture"]["mode"] == "auto"

    (repo / ".ahadiff" / "config.toml").write_text(
        "[capture]\nmax_files = 12\n",
        encoding="utf-8",
    )
    migrated_snapshot = load_config(repo, env=env)

    assert migrated_snapshot.values["capture"]["mode"] == "manual"
    assert migrated_snapshot.resolved["capture.mode"].source == "migration:capture-customized"


def _client(state_dir: Path) -> TestClient:
    app = create_app(ServeState(state_dir=state_dir, token="test-token", locale="en"))
    return TestClient(app, base_url="http://localhost:8765")


def _post_estimate(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/learn/estimate",
        json={},
        headers={
            "X-AhaDiff-Token": "test-token",
            "origin": "http://localhost:8765",
        },
    )
    assert response.status_code == 200
    return cast("dict[str, Any]", response.json())


def test_auto_mode_estimate_uses_effective_capture_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_capture_patch(**kwargs: object) -> SimpleNamespace:
        captured_kwargs.update(kwargs)
        return SimpleNamespace(
            persisted_patch_text="diff --git a/a.py b/a.py\n+print('hello')\n",
            metadata={"selected_files": ["a.py"], "omitted_files": []},
        )

    def fake_estimate_text_tokens(_text: str, _strategy: object) -> int:
        return 10

    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", fake_estimate_text_tokens)

    payload = _post_estimate(_client(tmp_path / ".ahadiff"))

    effective = cast("dict[str, Any]", payload["effective_capture_limits"])
    assert effective["mode"] == "auto"
    assert captured_kwargs["max_files"] == effective["max_files"]
    assert captured_kwargs["hard_limit"] == effective["hard_limit"]
    assert captured_kwargs["max_patch_bytes"] == effective["max_patch_bytes"]
    assert payload["diff_clipped"] is False
    assert payload["omitted_files_count"] == 0


def test_manual_mode_estimate_preserves_configured_capture_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    state_dir = repo / ".ahadiff"
    state_dir.mkdir()
    (state_dir / "config.toml").write_text(
        '[capture]\nmode = "manual"\nmax_files = 7\nhard_limit = 222\nmax_patch_bytes = 123456\n',
        encoding="utf-8",
    )
    captured_kwargs: dict[str, object] = {}

    def fake_capture_patch(**kwargs: object) -> SimpleNamespace:
        captured_kwargs.update(kwargs)
        return SimpleNamespace(
            persisted_patch_text="diff --git a/a.py b/a.py\n+print('hello')\n",
            metadata={
                "selected_files": ["a.py"],
                "omitted_files": ["b.py"],
                "degraded_flags": {"diff_clipped": True},
            },
        )

    def fake_estimate_text_tokens(_text: str, _strategy: object) -> int:
        return 10

    monkeypatch.setattr(routes_learn, "capture_patch", fake_capture_patch)
    monkeypatch.setattr(routes_learn, "estimate_text_tokens", fake_estimate_text_tokens)

    payload = _post_estimate(_client(state_dir))

    assert captured_kwargs["max_files"] == 7
    assert captured_kwargs["hard_limit"] == 222
    assert captured_kwargs["max_patch_bytes"] == 123_456
    assert payload["effective_capture_limits"]["mode"] == "manual"
    assert payload["diff_clipped"] is True
    assert payload["omitted_files_count"] == 1


def test_capture_recommendation_dataclass_serializes_for_api_response() -> None:
    recommendation = compute_recommended_capture(
        limits=_limits(128_000, 24_000),
        output_reserve=24_000,
    )

    payload = asdict(CaptureRecommendation(**asdict(recommendation)))
    assert payload["runtime_max_patch_bytes"] == 50 * 1024 * 1024
