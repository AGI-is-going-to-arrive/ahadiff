from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from ahadiff.llm import usage as usage_module
from ahadiff.llm.usage import (
    UsageByModel,
    UsageRecord,
    UsageSummary,
    query_usage_by_model,
    query_usage_summary,
    record_usage_event,
)


def _make_record(
    *,
    workspace_identity: str = "/repo/a",
    model_id: str = "gpt-5.4-mini",
    provider_class: str = "openai_chat",
    cost_usd: float | None = 0.01,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_hit: bool = False,
) -> UsageRecord:
    return UsageRecord(
        workspace_identity=workspace_identity,
        provider_class=provider_class,
        api_family="openai",
        api_family_version="v1",
        model_id=model_id,
        prompt_name="lesson_generate",
        prompt_fingerprint="abc123",
        prompt_version="v1",
        eval_bundle_version="v1",
        output_lang="en",
        privacy_mode="redacted_remote",
        source_ref="abc1234",
        cache_key="key1",
        cache_hit=cache_hit,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        pricing_version="v1",
        cost_confidence="exact",
        execution_origin="cli",
    )


def test_query_usage_summary_empty_db(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    result = query_usage_summary(db_path=db)
    assert result == UsageSummary(0.0, 0, 0, 0, 0, 0)


def test_query_usage_summary_nonexistent_db(tmp_path: Path) -> None:
    db = tmp_path / "does_not_exist.sqlite"
    result = query_usage_summary(db_path=db)
    assert result == UsageSummary(0.0, 0, 0, 0, 0, 0)


def test_query_usage_summary_with_data(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    record_usage_event(_make_record(cost_usd=0.05, input_tokens=200, output_tokens=100), db_path=db)
    record_usage_event(
        _make_record(cost_usd=0.03, input_tokens=150, output_tokens=75, cache_hit=True), db_path=db
    )
    result = query_usage_summary(db_path=db)
    assert result.total_calls == 2
    assert result.total_input_tokens == 350
    assert result.total_output_tokens == 175
    assert abs(result.total_cost_usd - 0.08) < 1e-9
    assert result.cache_hits == 1
    assert result.cache_misses == 1


def test_query_usage_summary_filters_by_workspace(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    record_usage_event(_make_record(workspace_identity="/repo/a", cost_usd=0.10), db_path=db)
    record_usage_event(_make_record(workspace_identity="/repo/b", cost_usd=0.20), db_path=db)
    result_a = query_usage_summary(db_path=db, workspace_identity="/repo/a")
    assert result_a.total_calls == 1
    assert abs(result_a.total_cost_usd - 0.10) < 1e-9

    result_all = query_usage_summary(db_path=db)
    assert result_all.total_calls == 2
    assert abs(result_all.total_cost_usd - 0.30) < 1e-9


def test_query_usage_by_model_empty(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    result = query_usage_by_model(db_path=db)
    assert result == ()


def test_query_usage_by_model_nonexistent(tmp_path: Path) -> None:
    result = query_usage_by_model(db_path=tmp_path / "nope.sqlite")
    assert result == ()


def test_query_usage_by_model_groups_correctly(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    record_usage_event(_make_record(model_id="gpt-5.4-mini", cost_usd=0.01), db_path=db)
    record_usage_event(_make_record(model_id="gpt-5.4-mini", cost_usd=0.02), db_path=db)
    record_usage_event(
        _make_record(model_id="claude-sonnet-4-6", provider_class="anthropic", cost_usd=0.05),
        db_path=db,
    )
    result = query_usage_by_model(db_path=db)
    assert len(result) == 2
    assert all(isinstance(r, UsageByModel) for r in result)
    top = result[0]
    assert top.model_id == "claude-sonnet-4-6"
    assert top.call_count == 1
    assert abs(top.cost_usd - 0.05) < 1e-9
    second = result[1]
    assert second.model_id == "gpt-5.4-mini"
    assert second.call_count == 2


def test_query_usage_by_model_filters_workspace(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    record_usage_event(
        _make_record(workspace_identity="/repo/x", model_id="m1", cost_usd=0.01), db_path=db
    )
    record_usage_event(
        _make_record(workspace_identity="/repo/y", model_id="m2", cost_usd=0.02), db_path=db
    )
    result = query_usage_by_model(db_path=db, workspace_identity="/repo/x")
    assert len(result) == 1
    assert result[0].model_id == "m1"


def test_query_usage_summary_null_cost(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    record_usage_event(_make_record(cost_usd=None), db_path=db)
    result = query_usage_summary(db_path=db)
    assert result.total_calls == 1
    assert result.total_cost_usd == 0.0


def test_usage_schema_cache_does_not_skip_recreated_empty_database(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite"
    record_usage_event(_make_record(model_id="before", cost_usd=0.01), db_path=db)
    for sqlite_path in (db, db.with_name(f"{db.name}-wal"), db.with_name(f"{db.name}-shm")):
        sqlite_path.unlink(missing_ok=True)
    db.touch()

    record_usage_event(_make_record(model_id="after", cost_usd=0.02), db_path=db)

    result = query_usage_summary(db_path=db)
    assert result.total_calls == 1
    assert abs(result.total_cost_usd - 0.02) < 1e-9


def test_usage_schema_cache_signature_stays_stable_across_delete_journal_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "usage.sqlite"
    schema_cache = usage_module._SCHEMA_INITIALIZED  # pyright: ignore[reportPrivateUsage]
    schema_cache.clear()

    def _force_delete(_db: object) -> str:
        return "DELETE"

    monkeypatch.setattr(usage_module, "_resolve_sqlite_journal_mode", _force_delete)

    record_usage_event(_make_record(model_id="first", cost_usd=0.01), db_path=db)
    first_signature = schema_cache[str(db)]
    record_usage_event(_make_record(model_id="second", cost_usd=0.02), db_path=db)
    second_signature = schema_cache[str(db)]

    assert first_signature == second_signature
    result = query_usage_summary(db_path=db)
    assert result.total_calls == 2
    assert abs(result.total_cost_usd - 0.03) < 1e-9


def test_query_usage_time_filters_normalize_timezone_offsets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "usage.sqlite"
    timestamps = iter(("2026-04-27T23:30:00Z", "2026-04-28T00:30:00Z"))

    def fake_utc_now() -> str:
        return next(timestamps)

    monkeypatch.setattr(usage_module, "_utc_now", fake_utc_now)
    record_usage_event(_make_record(model_id="before", cost_usd=0.01), db_path=db)
    record_usage_event(_make_record(model_id="after", cost_usd=0.02), db_path=db)

    since_result = query_usage_summary(db_path=db, since="2026-04-28T10:00:00+10:00")
    assert since_result.total_calls == 1
    assert abs(since_result.total_cost_usd - 0.02) < 1e-9

    until_result = query_usage_by_model(db_path=db, until="2026-04-28T10:00:00+10:00")
    assert len(until_result) == 1
    assert until_result[0].model_id == "before"
