"""GET /api/stats, /api/review/heatmap, /api/providers, and /api/serve/status endpoints."""

from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
import stat
import time
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from json import JSONDecodeError
from typing import TYPE_CHECKING, Any, Literal, cast

if not TYPE_CHECKING:
    from pathlib import Path

from anyio import to_thread
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from ahadiff.contracts import ErrorCode
from ahadiff.contracts.event_log import RATCHET_COUNTED_STATUSES, ResultEvent
from ahadiff.contracts.serve_stats import (
    HeatmapEntry,
    ProvidersResponse,
    ProviderSummary,
    ReviewHeatmapResponse,
    ServeStatusResponse,
    SpecAlignmentResponse,
    StatsResponse,
    UsageModelSummary,
    UsageResponse,
)
from ahadiff.core.config import mask_provider_base_url_for_display
from ahadiff.core.errors import InputError, StorageError
from ahadiff.core.json_util import safe_json_loads
from ahadiff.core.paths import validate_run_id
from ahadiff.review.database import connect_review_db, count_concepts

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from .state import ServeState

log = logging.getLogger(__name__)

_MAX_HEATMAP_SPAN_DAYS = 730
_DEFAULT_HEATMAP_DAYS = 365
_MAX_SPEC_ALIGNMENT_JSON_BYTES = 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


# ---------------------------------------------------------------------------
# /api/stats
# ---------------------------------------------------------------------------


def _count_run_artifacts(runs_dir: Path) -> dict[str, int]:
    """Scan runs_dir subdirectories and count lessons, quizzes, and claims."""
    total_runs = 0
    total_lessons = 0
    total_quizzes = 0
    total_claims = 0

    if not runs_dir.is_dir():
        return {
            "total_runs": 0,
            "total_lessons": 0,
            "total_quizzes": 0,
            "total_claims": 0,
        }

    try:
        entries = sorted(runs_dir.iterdir())
    except OSError:
        return {
            "total_runs": 0,
            "total_lessons": 0,
            "total_quizzes": 0,
            "total_claims": 0,
        }

    for entry in entries:
        if not _is_finalized_run_dir(entry):
            continue
        total_runs += 1
        # Check for lesson (any level)
        lesson_dir = entry / "lesson"
        if lesson_dir.is_dir():
            for name in ("lesson.full.md", "lesson.hint.md", "lesson.compact.md"):
                if (lesson_dir / name).is_file():
                    total_lessons += 1
                    break
        # Check for quiz
        quiz_file = entry / "quiz" / "quiz.jsonl"
        if quiz_file.is_file():
            total_quizzes += 1
        # Check for claims
        claims_file = entry / "claims.jsonl"
        if claims_file.is_file():
            total_claims += 1

    return {
        "total_runs": total_runs,
        "total_lessons": total_lessons,
        "total_quizzes": total_quizzes,
        "total_claims": total_claims,
    }


def _is_finalized_run_dir(path: Path) -> bool:
    return not path.is_symlink() and path.is_dir() and (path / "finalized.json").is_file()


def _count_concepts_jsonl(state_dir: Path) -> int:
    """Count lines in concepts.jsonl."""
    import stat as stat_mod

    concepts_path = state_dir / "concepts.jsonl"
    if not concepts_path.is_file():
        return 0
    try:
        leaf_stat = concepts_path.lstat()
        if stat_mod.S_ISLNK(leaf_stat.st_mode):
            return 0
        if bool(getattr(leaf_stat, "st_file_attributes", 0) & 0x400):
            return 0
        count = 0
        with concepts_path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    count += 1
        return count
    except OSError:
        return 0


def _count_concepts(state_dir: Path, db_path: Path) -> int:
    jsonl_count = _count_concepts_jsonl(state_dir)
    if not db_path.is_file():
        return jsonl_count
    try:
        db_count = count_concepts(db_path)
    except Exception as exc:
        log.debug("failed to count concepts from %s", db_path, exc_info=True)
        raise StorageError("failed to count concepts", code=ErrorCode.STORAGE_REVIEW_DB) from exc
    return max(db_count, jsonl_count)


def _is_missing_table_error(exc: sqlite3.OperationalError) -> bool:
    return "no such table:" in str(exc).casefold()


def _raise_stats_backend_error(detail: str, exc: Exception) -> None:
    log.debug("%s", detail, exc_info=True)
    raise StorageError(detail, code=ErrorCode.STORAGE_REVIEW_DB) from exc


def _query_review_stats(db_path: Path) -> dict[str, Any]:
    """Query review_logs count, avg overall score, weakest dims from review.sqlite."""
    result: dict[str, Any] = {
        "total_reviews": 0,
        "avg_overall_score": None,
        "weakest_dimensions": [],
        "last_run_at": None,
    }
    if not db_path.is_file():
        return result

    try:
        with connect_review_db(db_path) as conn:
            # Count review logs
            try:
                row = conn.execute("SELECT COUNT(*) FROM review_logs").fetchone()
                result["total_reviews"] = int(row[0]) if row else 0
            except sqlite3.OperationalError as exc:
                if _is_missing_table_error(exc):
                    pass
                else:
                    _raise_stats_backend_error("failed to query review stats", exc)

            # Avg overall score and weakest dimensions from finalized events
            try:
                row = conn.execute(
                    """
                    SELECT AVG(overall) FROM result_events
                    WHERE status IN ('baseline', 'keep', 'keep_final')
                    """
                ).fetchone()
                if row and row[0] is not None:
                    val = float(row[0])
                    result["avg_overall_score"] = val if math.isfinite(val) else None
            except sqlite3.OperationalError as exc:
                if _is_missing_table_error(exc):
                    pass
                else:
                    _raise_stats_backend_error("failed to query review stats", exc)

            # Weakest dimensions (top-3 most frequent, finalized only)
            try:
                rows = conn.execute(
                    """
                    SELECT weakest_dim, COUNT(*) AS cnt
                    FROM result_events
                    WHERE weakest_dim IS NOT NULL AND weakest_dim != ''
                      AND status IN ('baseline', 'keep', 'keep_final')
                    GROUP BY weakest_dim
                    ORDER BY cnt DESC
                    LIMIT 10
                    """
                ).fetchall()
                if rows:
                    result["weakest_dimensions"] = [str(r[0]) for r in rows[:3]]
            except sqlite3.OperationalError as exc:
                if _is_missing_table_error(exc):
                    pass
                else:
                    _raise_stats_backend_error("failed to query review stats", exc)

            # Last run timestamp
            try:
                row = conn.execute("SELECT MAX(timestamp) FROM result_events").fetchone()
                if row and row[0] is not None:
                    result["last_run_at"] = str(row[0])
            except sqlite3.OperationalError as exc:
                if _is_missing_table_error(exc):
                    pass
                else:
                    _raise_stats_backend_error("failed to query review stats", exc)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_stats_backend_error("failed to query review stats", exc)

    return result


def _build_stats(state: ServeState) -> dict[str, Any]:
    artifacts = _count_run_artifacts(state.runs_dir)
    concepts = _count_concepts(state.state_dir, state.review_db_path)
    review = _query_review_stats(state.review_db_path)

    resp = StatsResponse(
        total_runs=artifacts["total_runs"],
        total_lessons=artifacts["total_lessons"],
        total_quizzes=artifacts["total_quizzes"],
        total_concepts=concepts,
        total_claims=artifacts["total_claims"],
        total_reviews=review["total_reviews"],
        avg_overall_score=review["avg_overall_score"],
        weakest_dimensions=review["weakest_dimensions"],
        last_run_at=review["last_run_at"],
    )
    return resp.model_dump(mode="json")


async def get_stats(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)
    payload = await to_thread.run_sync(_build_stats, state)
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# /api/review/heatmap
# ---------------------------------------------------------------------------


def _build_heatmap(
    state: ServeState,
    from_date: str | None,
    to_date: str | None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    # Defaults
    if to_date:
        try:
            end = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            end = now
    else:
        end = now

    if from_date:
        try:
            start = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            start = end - timedelta(days=_DEFAULT_HEATMAP_DAYS)
    else:
        start = end - timedelta(days=_DEFAULT_HEATMAP_DAYS)

    span = (end - start).days
    if span < 0:
        start, end = end, start
        span = (end - start).days
    if span > _MAX_HEATMAP_SPAN_DAYS:
        start = end - timedelta(days=_MAX_HEATMAP_SPAN_DAYS)

    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    entries: list[HeatmapEntry] = []
    db_path = state.review_db_path
    if not db_path.is_file():
        return ReviewHeatmapResponse(entries=entries).model_dump(mode="json")

    try:
        with connect_review_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    date(reviewed_at_utc) AS d,
                    COUNT(*) AS cnt,
                    AVG(rating) AS avg_r
                FROM review_logs
                WHERE date(reviewed_at_utc) >= ? AND date(reviewed_at_utc) <= ?
                GROUP BY d
                ORDER BY d ASC
                """,
                (start_str, end_str),
            ).fetchall()
            for row in rows:
                avg_r = float(row[2]) if row[2] is not None else None
                if avg_r is not None and not math.isfinite(avg_r):
                    avg_r = None
                entries.append(
                    HeatmapEntry(
                        date=str(row[0]),
                        review_count=int(row[1]),
                        avg_rating=avg_r,
                    )
                )
    except sqlite3.OperationalError as exc:
        if not _is_missing_table_error(exc):
            _raise_stats_backend_error("failed to query review heatmap", exc)
    except Exception as exc:
        _raise_stats_backend_error("failed to query review heatmap", exc)

    return ReviewHeatmapResponse(entries=entries).model_dump(mode="json")


async def get_review_heatmap(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)
    from_date = request.query_params.get("from")
    to_date = request.query_params.get("to")
    payload = await to_thread.run_sync(
        lambda: _build_heatmap(state, from_date, to_date),
    )
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# /api/providers
# ---------------------------------------------------------------------------


def _optional_positive_int(mapping: Mapping[str, object], key: str) -> int | None:
    raw = mapping.get(key)
    return int(raw) if isinstance(raw, int) and raw > 0 else None


def _optional_thinking_level(mapping: Mapping[str, object]) -> str | None:
    raw = mapping.get("thinking_level")
    if isinstance(raw, str) and raw in {"none", "low", "medium", "high"}:
        return raw
    return None


def _provider_api_family(provider_class: str) -> tuple[str | None, str | None, str]:
    if provider_class == "openai_responses":
        return ("openai", "responses-v1", "openai_responses")
    if provider_class in {"openai", "newapi", "lmstudio"}:
        return ("openai", "chat-v1", provider_class)
    if provider_class == "azure":
        return ("openai", "azure-openai", "azure")
    if provider_class == "gemini":
        return ("gemini", "v1beta", "gemini")
    if provider_class == "anthropic":
        return ("anthropic", "2023-06-01", "anthropic")
    if provider_class == "ollama":
        return ("ollama", "v1", "ollama")
    return (None, None, provider_class or "legacy")


_ENV_VAR_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _parse_available_models(mapping: Mapping[str, Any]) -> list[str]:
    raw = mapping.get("available_models")
    if isinstance(raw, list | tuple):
        items = cast("list[object] | tuple[object, ...]", raw)
        return [str(item) for item in items if isinstance(item, str) and item.strip()]
    return []


def _provider_key_status(
    api_key_env: str | None,
) -> Literal["configured", "missing", "unknown"]:
    import os

    if not api_key_env:
        return "unknown"
    if os.environ.get(api_key_env):
        return "configured"
    if _ENV_VAR_NAME_RE.fullmatch(api_key_env):
        return "missing"
    return "configured"


def _provider_summary_from_mapping(
    alias: str,
    provider_mapping: Mapping[str, object],
    *,
    role: str | None = None,
) -> ProviderSummary | None:
    provider_class = str(provider_mapping.get("provider_class") or "")
    model_name = str(provider_mapping.get("model_name") or "")
    base_url = mask_provider_base_url_for_display(str(provider_mapping.get("base_url") or ""))
    if not provider_class or not model_name or not base_url:
        return None
    raw_api_key_env = provider_mapping.get("api_key_env")
    api_key_env: str | None = None
    if isinstance(raw_api_key_env, str) and raw_api_key_env:
        if _ENV_VAR_NAME_RE.fullmatch(raw_api_key_env):
            api_key_env = raw_api_key_env
        elif len(raw_api_key_env) > 8:
            api_key_env = raw_api_key_env[:4] + "****" + raw_api_key_env[-4:]
        else:
            api_key_env = "****"
    api_family, api_family_version, provider_kind = _provider_api_family(provider_class)
    probed_max_context = _optional_positive_int(provider_mapping, "probed_max_context")
    probed_max_input_tokens = _optional_positive_int(provider_mapping, "probed_max_input_tokens")
    probed_max_output_tokens = _optional_positive_int(provider_mapping, "probed_max_output_tokens")
    probed_tpm = _optional_positive_int(provider_mapping, "probed_tpm")
    probed_rpm = _optional_positive_int(provider_mapping, "probed_rpm")
    raw_probed_limits_source = provider_mapping.get("probed_limits_source")
    probed_limits_source = (
        str(raw_probed_limits_source)
        if isinstance(raw_probed_limits_source, str)
        and raw_probed_limits_source in {"live", "registry", "default", "fallback"}
        else None
    )
    raw_model_limits_name = provider_mapping.get("model_limits_name")
    model_limits_name = (
        str(raw_model_limits_name)
        if isinstance(raw_model_limits_name, str) and raw_model_limits_name
        else None
    )
    raw_probe_timestamp = provider_mapping.get("probe_timestamp")
    probe_timestamp = (
        str(raw_probe_timestamp)
        if isinstance(raw_probe_timestamp, str) and raw_probe_timestamp
        else None
    )
    probed = any(
        value is not None
        for value in (
            probed_max_context,
            probed_max_input_tokens,
            probed_max_output_tokens,
            probed_limits_source,
            probed_tpm,
            probed_rpm,
            probe_timestamp,
        )
    )
    return ProviderSummary(
        alias=alias,
        role=role,
        provider_class=provider_class,
        provider_kind=provider_kind,
        model_name=model_name,
        base_url=mask_provider_base_url_for_display(base_url),
        api_key_env=api_key_env,
        key_status=_provider_key_status(api_key_env),
        api_family=api_family,
        api_family_version=api_family_version,
        probed=probed,
        probed_max_context=probed_max_context,
        probed_max_input_tokens=probed_max_input_tokens,
        probed_max_output_tokens=probed_max_output_tokens,
        probed_limits_source=probed_limits_source,
        model_limits_name=model_limits_name,
        max_output_tokens=_optional_positive_int(provider_mapping, "max_output_tokens"),
        thinking_level=_optional_thinking_level(provider_mapping),
        probed_tpm=probed_tpm,
        probed_rpm=probed_rpm,
        probe_timestamp=probe_timestamp,
        available_models=_parse_available_models(provider_mapping),
    )


# Public alias so other route modules (e.g. routes_providers.py) can build
# ProviderSummary payloads without duplicating the canonical mapping logic.
provider_summary_from_mapping = _provider_summary_from_mapping


def _legacy_provider_summary(  # pyright: ignore[reportUnusedFunction]
    alias: str,
    model_name: str,
    base_url: str,
    api_key_env: str | None,
) -> ProviderSummary:
    api_family, api_family_version, provider_kind = _provider_api_family("")
    return ProviderSummary(
        alias=alias,
        role=alias,
        provider_class=alias,
        provider_kind=provider_kind,
        model_name=model_name,
        base_url=base_url,
        api_key_env=api_key_env,
        key_status=_provider_key_status(api_key_env),
        api_family=api_family,
        api_family_version=api_family_version,
        probed=False,
        probed_max_context=None,
        probed_max_input_tokens=None,
        probed_max_output_tokens=None,
        probed_limits_source=None,
        model_limits_name=None,
    )


def _build_providers(state: ServeState) -> dict[str, Any]:
    from ahadiff.core.config import load_config

    providers: list[ProviderSummary] = []
    try:
        cfg = load_config(state.state_dir.parent)
        values = cast("dict[str, Any]", getattr(cfg, "values", {}))
        providers_config = values.get("providers")
        if isinstance(providers_config, Mapping):
            for alias, provider in sorted(
                cast("dict[str, Any]", providers_config).items(),
                key=lambda item: str(item[0]),
            ):
                if not isinstance(provider, Mapping):
                    continue
                provider_mapping = cast("Mapping[str, object]", provider)
                raw_role = provider_mapping.get("role")
                summary = _provider_summary_from_mapping(
                    str(alias),
                    provider_mapping,
                    role=str(raw_role) if isinstance(raw_role, str) and raw_role else None,
                )
                if summary is not None:
                    providers.append(summary)
        return ProvidersResponse(providers=providers).model_dump(mode="json")
    except Exception:
        log.debug("failed to load provider config", exc_info=True)

    return ProvidersResponse(providers=providers).model_dump(mode="json")


async def get_providers(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)
    payload = await to_thread.run_sync(_build_providers, state)
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# /api/serve/status  (NO auth required)
# ---------------------------------------------------------------------------


def _build_serve_status(state: ServeState) -> dict[str, Any]:
    import ahadiff

    runs_count = 0
    if state.runs_dir.is_dir():
        with suppress(OSError):
            runs_count = sum(1 for e in state.runs_dir.iterdir() if _is_finalized_run_dir(e))

    started_at = state.started_at or time.monotonic()
    uptime = time.monotonic() - started_at

    resp = ServeStatusResponse(
        version=ahadiff.__version__,
        uptime_seconds=round(uptime, 2),
        review_db_exists=state.review_db_path.is_file(),
        runs_count=runs_count,
    )
    return resp.model_dump(mode="json")


async def get_serve_status(request: Request) -> JSONResponse:
    from .auth import serve_state

    state: ServeState = serve_state(request)
    payload = await to_thread.run_sync(_build_serve_status, state)
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# /api/stats/learning
# ---------------------------------------------------------------------------


def _build_learning_effectiveness(state: ServeState) -> dict[str, Any]:
    from ahadiff.contracts.serve_stats import (
        HelpfulnessAggregateDTO,
        LearningEffectivenessResponse,
        TransferConceptDTO,
    )
    from ahadiff.lesson.helpfulness import aggregate_helpfulness
    from ahadiff.lesson.transfer import validate_learning_transfer

    helpfulness_data = aggregate_helpfulness(state.review_db_path)
    transfer_data = validate_learning_transfer(state.review_db_path)

    helpfulness_dtos = [
        HelpfulnessAggregateDTO(
            target_kind=h.target_kind,
            target_id=h.target_id,
            signal_count=h.signal_count,
            positive_count=h.positive_count,
            negative_count=h.negative_count,
            helpfulness_score=h.helpfulness_score,
        )
        for h in helpfulness_data
    ]

    transfer_dtos = [
        TransferConceptDTO(
            concept=m.concept,
            total_reviews=m.total_reviews,
            avg_rating=m.avg_rating,
            improving=m.improving,
        )
        for m in transfer_data.metrics
    ]

    resp = LearningEffectivenessResponse(
        total_concepts_reviewed=transfer_data.total_concepts_reviewed,
        concepts_improving=transfer_data.concepts_improving,
        concepts_stable=transfer_data.concepts_stable,
        concepts_declining=transfer_data.concepts_declining,
        transfer_rate=transfer_data.transfer_rate,
        helpfulness=helpfulness_dtos,
        transfer_metrics=transfer_dtos,
    )
    return resp.model_dump(mode="json")


async def get_learning_effectiveness(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)
    payload = await to_thread.run_sync(_build_learning_effectiveness, state)
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# /api/usage
# ---------------------------------------------------------------------------


def _build_usage(
    state: ServeState,
    *,
    since: str | None,
    until: str | None,
) -> dict[str, Any]:
    from ahadiff.core.paths import usage_db_path, workspace_identity_lookup_keys
    from ahadiff.llm.usage import query_usage_by_model, query_usage_summary

    db_path = usage_db_path()
    if not db_path.is_file():
        return UsageResponse(
            models=[],
            total_calls=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cost_usd=0.0,
            cache_hits=0,
            cache_misses=0,
        ).model_dump(mode="json")

    current_identity, legacy_identity = workspace_identity_lookup_keys(state.state_dir.parent)
    try:
        identities = tuple(dict.fromkeys((current_identity, legacy_identity)))
        total_calls = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost_usd = 0.0
        cache_hits = 0
        cache_misses = 0
        by_model: dict[tuple[str, str], UsageModelSummary] = {}
        for identity in identities:
            summary = query_usage_summary(
                db_path=db_path,
                workspace_identity=identity,
                since=since,
                until=until,
            )
            total_calls += summary.total_calls
            total_input_tokens += summary.total_input_tokens
            total_output_tokens += summary.total_output_tokens
            total_cost_usd += summary.total_cost_usd
            cache_hits += summary.cache_hits
            cache_misses += summary.cache_misses
            for item in query_usage_by_model(
                db_path=db_path,
                workspace_identity=identity,
                since=since,
                until=until,
            ):
                key = (item.provider_class, item.model_id)
                existing = by_model.get(key)
                if existing is None:
                    by_model[key] = UsageModelSummary(
                        provider_class=item.provider_class,
                        model_id=item.model_id,
                        call_count=item.call_count,
                        total_input_tokens=item.input_tokens,
                        total_output_tokens=item.output_tokens,
                        total_cost_usd=item.cost_usd,
                    )
                else:
                    by_model[key] = UsageModelSummary(
                        provider_class=existing.provider_class,
                        model_id=existing.model_id,
                        call_count=existing.call_count + item.call_count,
                        total_input_tokens=existing.total_input_tokens + item.input_tokens,
                        total_output_tokens=existing.total_output_tokens + item.output_tokens,
                        total_cost_usd=existing.total_cost_usd + item.cost_usd,
                    )
    except Exception as error:
        raise RuntimeError("usage database is unavailable") from error

    if not math.isfinite(total_cost_usd):
        total_cost_usd = 0.0
    models = sorted(by_model.values(), key=lambda item: item.call_count, reverse=True)
    return UsageResponse(
        models=models,
        total_calls=total_calls,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_cost_usd=total_cost_usd,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
    ).model_dump(mode="json")


async def get_usage(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)
    since = request.query_params.get("from")
    until = request.query_params.get("to")
    try:
        payload = await to_thread.run_sync(lambda: _build_usage(state, since=since, until=until))
    except Exception as error:
        from ahadiff.core.errors import InputError

        if isinstance(error.__cause__, InputError):
            raise HTTPException(status_code=400, detail=str(error.__cause__)) from error
        log.warning("usage API failed", exc_info=True)
        raise StorageError(
            "usage database is unavailable",
            code=ErrorCode.STORAGE_USAGE_DB,
        ) from error
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# /api/spec/alignment
# ---------------------------------------------------------------------------


def _build_spec_alignment(state: ServeState) -> dict[str, Any]:
    db_path = state.review_db_path
    if not db_path.is_file():
        return _empty_spec_alignment()

    events = _load_spec_alignment_events(db_path)
    if not events:
        return _empty_spec_alignment()

    scores: list[float] = []
    aggregate = {
        "implemented": 0,
        "partial": 0,
        "missing": 0,
        "unknown": 0,
        "total_requirements": 0,
        "degraded_count": 0,
        "semantic_reviewed": 0,
        "semantic_degraded_count": 0,
        "semantic_disagreement_count": 0,
    }
    for event in events:
        item = _load_run_spec_alignment_summary(state.runs_dir, event)
        if item is None:
            continue
        if item["degraded"]:
            aggregate["degraded_count"] += 1
        raw_score = item["score"]
        if isinstance(raw_score, float):
            scores.append(raw_score)
            aggregate["implemented"] += item["implemented"]
            aggregate["partial"] += item["partial"]
            aggregate["missing"] += item["missing"]
            aggregate["unknown"] += item["unknown"]
            aggregate["total_requirements"] += item["total_requirements"]
            aggregate["semantic_reviewed"] += item["semantic_reviewed"]
            aggregate["semantic_degraded_count"] += item["semantic_degraded_count"]
            aggregate["semantic_disagreement_count"] += item["semantic_disagreement_count"]

    if not scores:
        payload = _empty_spec_alignment()
        payload["degraded_count"] = aggregate["degraded_count"]
        return payload

    avg = round(sum(scores) / len(scores), 2)
    trend: str | None = None
    if len(scores) >= 4:
        half = len(scores) // 2
        earlier_avg = sum(scores[:half]) / half
        later_avg = sum(scores[-half:]) / half
        diff = later_avg - earlier_avg
        if diff > 1.0:
            trend = "improving"
        elif diff < -1.0:
            trend = "declining"
        else:
            trend = "stable"

    return SpecAlignmentResponse(
        alignment_score=avg,
        total_evaluated=len(scores),
        recent_trend=trend,
        total_requirements=aggregate["total_requirements"],
        implemented=aggregate["implemented"],
        partial=aggregate["partial"],
        missing=aggregate["missing"],
        unknown=aggregate["unknown"],
        degraded_count=aggregate["degraded_count"],
        semantic_reviewed=aggregate["semantic_reviewed"],
        semantic_degraded_count=aggregate["semantic_degraded_count"],
        semantic_disagreement_count=aggregate["semantic_disagreement_count"],
    ).model_dump(mode="json")


def _empty_spec_alignment() -> dict[str, Any]:
    return SpecAlignmentResponse(
        alignment_score=None,
        total_evaluated=0,
        recent_trend=None,
    ).model_dump(mode="json")


def _load_spec_alignment_events(db_path: Path) -> list[ResultEvent]:
    statuses = tuple(sorted(RATCHET_COUNTED_STATUSES))
    placeholders = ", ".join("?" for _ in statuses)
    try:
        with connect_review_db(db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT event_id, run_id, event_type, timestamp, source_ref, base_ref,
                       prompt_version, eval_bundle_version, rubric_version, overall,
                       verdict, status, weakest_dim, note_json
                FROM result_events
                WHERE status IN ({placeholders})
                ORDER BY timestamp ASC, event_id ASC
                """,
                statuses,
            ).fetchall()
    except sqlite3.OperationalError:
        return []

    events: list[ResultEvent] = []
    for row in rows:
        try:
            events.append(ResultEvent.model_validate(dict(row)))
        except ValidationError:
            continue
    return events


def _load_run_spec_alignment_summary(runs_dir: Path, event: ResultEvent) -> dict[str, Any] | None:
    run_path = _finalized_stats_event_run_path(runs_dir, event)
    if run_path is None:
        return None
    artifact_path = _artifact_path_for_stats_read(run_path, "spec_alignment.json")
    if artifact_path is not None:
        artifact = _load_stats_json_object(artifact_path)
        if artifact is None:
            return _empty_run_spec_alignment_summary(degraded=True)
        schema_version = artifact.get("schema_version")
        if (
            artifact.get("artifact") != "spec_alignment"
            or artifact.get("schema") != "ahadiff.spec_alignment"
            or isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version < 1
        ):
            return _empty_run_spec_alignment_summary(degraded=True)
        score = _finite_spec_score(artifact.get("score"))
        if score is None:
            return _empty_run_spec_alignment_summary(degraded=True)
        semantic_summary = _semantic_summary_from_artifact(artifact)
        raw_summary = artifact.get("summary")
        summary: Mapping[str, object] = (
            cast("Mapping[str, object]", raw_summary)
            if isinstance(raw_summary, dict)
            else cast("Mapping[str, object]", {})
        )
        requirements = artifact.get("requirements")
        total_requirements = (
            len(cast("list[object]", requirements)) if isinstance(requirements, list) else 0
        )
        summary_item = _empty_run_spec_alignment_summary(degraded=False)
        summary_item["score"] = score
        summary_item["implemented"] = _summary_count(summary, "implemented")
        summary_item["partial"] = _summary_count(summary, "partial")
        summary_item["missing"] = _summary_count(summary, "missing")
        summary_item["unknown"] = _summary_count(summary, "unknown")
        summary_item["total_requirements"] = max(
            total_requirements,
            summary_item["implemented"]
            + summary_item["partial"]
            + summary_item["missing"]
            + summary_item["unknown"],
        )
        summary_item.update(semantic_summary)
        return summary_item

    score_path = _artifact_path_for_stats_read(run_path, "score.json")
    if score_path is None:
        return None
    payload = _load_stats_json_object(score_path)
    if payload is None:
        return None

    dimensions_raw = payload.get("dimensions")
    if not isinstance(dimensions_raw, dict):
        return None
    dimensions = cast("Mapping[str, object]", dimensions_raw)
    spec_alignment_raw = dimensions.get("spec_alignment")
    if not isinstance(spec_alignment_raw, dict):
        return None
    spec_alignment = cast("Mapping[str, object]", spec_alignment_raw)
    raw_max_score = spec_alignment.get("max_score")
    if not isinstance(raw_max_score, int | float) or float(raw_max_score) <= 0:
        return None
    raw_score = spec_alignment.get("score")
    score = _finite_spec_score(raw_score)
    if score is None:
        return None
    summary_item = _empty_run_spec_alignment_summary(degraded=False)
    summary_item["score"] = score
    return summary_item


def _empty_run_spec_alignment_summary(*, degraded: bool) -> dict[str, Any]:
    return {
        "score": None,
        "implemented": 0,
        "partial": 0,
        "missing": 0,
        "unknown": 0,
        "total_requirements": 0,
        "degraded": degraded,
        "semantic_reviewed": 0,
        "semantic_degraded_count": 0,
        "semantic_disagreement_count": 0,
    }


def _semantic_summary_from_artifact(artifact: Mapping[str, object]) -> dict[str, int]:
    raw_review = artifact.get("semantic_review")
    if not isinstance(raw_review, dict):
        return {
            "semantic_reviewed": 0,
            "semantic_degraded_count": 0,
            "semantic_disagreement_count": 0,
        }
    review = cast("Mapping[str, object]", raw_review)
    raw_requirements = review.get("requirements")
    requirements = (
        cast("list[object]", raw_requirements) if isinstance(raw_requirements, list) else []
    )
    disagreements = 0
    for raw_item in requirements:
        if not isinstance(raw_item, dict):
            continue
        item = cast("Mapping[str, object]", raw_item)
        if item.get("disagreement_with_deterministic") is True:
            disagreements += 1
    return {
        "semantic_reviewed": 1,
        "semantic_degraded_count": 1 if review.get("degraded") is True else 0,
        "semantic_disagreement_count": disagreements,
    }


def _finite_spec_score(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    score = float(value)
    return score if math.isfinite(score) and 0.0 <= score <= 10.0 else None


def _summary_count(summary: Mapping[str, object], key: str) -> int:
    value = summary.get(key)
    return value if isinstance(value, int) and value >= 0 else 0


def _finalized_stats_event_run_path(runs_dir: Path, event: ResultEvent) -> Path | None:
    try:
        validate_run_id(event.run_id)
    except InputError:
        return None
    if event.run_id.endswith(".tmp"):
        return None
    run_path = runs_dir / event.run_id
    if run_path.is_symlink() or not run_path.is_dir():
        return None
    marker = _load_stats_json_object(run_path / "finalized.json")
    if marker is None:
        return None
    if marker.get("run_id") != event.run_id or marker.get("event_id") != event.event_id:
        return None
    return run_path


def _artifact_path_for_stats_read(run_path: Path, relative_path: str) -> Path | None:
    artifact_path = run_path / relative_path
    if not artifact_path.is_file() or artifact_path.is_symlink():
        return None
    try:
        artifact_path.resolve(strict=True).relative_to(run_path.resolve(strict=True))
    except (OSError, ValueError):
        return None
    return artifact_path


def _load_stats_json_object(path: Path) -> dict[str, Any] | None:
    text = _read_stats_regular_text(path)
    if text is None:
        return None
    try:
        payload = safe_json_loads(text)
    except (JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return cast("dict[str, Any]", payload)


def _read_stats_regular_text(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        path_stat = os.lstat(path)
    except OSError:
        return None
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or _has_windows_reparse_point(path_stat)
        or getattr(path_stat, "st_nlink", 1) > 1
        or path_stat.st_size > _MAX_SPEC_ALIGNMENT_JSON_BYTES
    ):
        return None
    fd = -1
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened_stat = os.fstat(fd)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _has_windows_reparse_point(opened_stat)
            or getattr(opened_stat, "st_nlink", 1) > 1
            or opened_stat.st_size > _MAX_SPEC_ALIGNMENT_JSON_BYTES
        ):
            return None
        if (opened_stat.st_dev, opened_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            return None
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        if fd != -1:
            os.close(fd)


def _has_windows_reparse_point(path_stat: object) -> bool:
    if os.name != "nt":
        return False
    return bool(getattr(path_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


async def get_spec_alignment(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)
    payload = await to_thread.run_sync(_build_spec_alignment, state)
    return JSONResponse(payload)


__all__ = [
    "get_learning_effectiveness",
    "get_providers",
    "get_review_heatmap",
    "get_serve_status",
    "get_spec_alignment",
    "get_stats",
    "get_usage",
    "provider_summary_from_mapping",
]
