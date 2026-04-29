"""GET /api/stats, /api/review/heatmap, /api/providers, and /api/serve/status endpoints."""

from __future__ import annotations

import logging
import math
import sqlite3
import time
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

if not TYPE_CHECKING:
    from pathlib import Path

from anyio import to_thread
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_stats import (
    HeatmapEntry,
    ProvidersResponse,
    ProviderSummary,
    ReviewHeatmapResponse,
    ServeStatusResponse,
    StatsResponse,
)
from ahadiff.review.database import connect_review_db, count_concepts

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from .state import ServeState

log = logging.getLogger(__name__)

_MAX_HEATMAP_SPAN_DAYS = 730
_DEFAULT_HEATMAP_DAYS = 365


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
        raise HTTPException(status_code=500, detail="failed to count concepts") from exc
    return max(db_count, jsonl_count)


def _is_missing_table_error(exc: sqlite3.OperationalError) -> bool:
    return "no such table:" in str(exc).casefold()


def _raise_stats_backend_error(detail: str, exc: Exception) -> None:
    log.debug("%s", detail, exc_info=True)
    raise HTTPException(status_code=500, detail=detail) from exc


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


def _build_providers(state: ServeState) -> dict[str, Any]:
    from ahadiff.core.config import load_config

    providers: list[ProviderSummary] = []
    try:
        cfg = load_config(state.state_dir.parent)
        values = cast("dict[str, Any]", getattr(cfg, "values", {}))
        providers_config = values.get("providers")
        if isinstance(providers_config, Mapping):
            for _, provider in sorted(
                cast("dict[str, Any]", providers_config).items(),
                key=lambda item: str(item[0]),
            ):
                if not isinstance(provider, Mapping):
                    continue
                provider_mapping = cast("Mapping[str, object]", provider)
                provider_class = str(provider_mapping.get("provider_class") or "")
                model_name = str(provider_mapping.get("model_name") or "")
                base_url = str(provider_mapping.get("base_url") or "")
                raw_context = provider_mapping.get("probed_max_context")
                probed_max_context = (
                    int(raw_context) if isinstance(raw_context, int) and raw_context > 0 else None
                )
                probed = probed_max_context is not None or bool(
                    provider_mapping.get("probe_timestamp")
                )
                if provider_class and model_name and base_url:
                    providers.append(
                        ProviderSummary(
                            provider_class=provider_class,
                            model_name=model_name,
                            base_url=base_url,
                            probed=probed,
                            probed_max_context=probed_max_context,
                        )
                    )
        if providers:
            return ProvidersResponse(providers=providers).model_dump(mode="json")
        llm = values.get("llm", getattr(cfg, "llm", None))
        if isinstance(llm, Mapping):
            llm_mapping = cast("Mapping[str, object]", llm)
            gen_model = str(llm_mapping.get("generate_model") or "")
            judge_model = str(llm_mapping.get("judge_model") or "")
            base_url = str(llm_mapping.get("base_url") or "")
        elif llm is not None:
            gen_model = getattr(llm, "generate_model", None) or ""
            judge_model = getattr(llm, "judge_model", None) or ""
            base_url = getattr(llm, "base_url", None) or ""
        else:
            gen_model = ""
            judge_model = ""
            base_url = ""

        if gen_model:
            providers.append(
                ProviderSummary(
                    provider_class="generate",
                    model_name=gen_model,
                    base_url=base_url,
                    probed=False,
                    probed_max_context=None,
                )
            )
        if judge_model and judge_model != gen_model:
            providers.append(
                ProviderSummary(
                    provider_class="judge",
                    model_name=judge_model,
                    base_url=base_url,
                    probed=False,
                    probed_max_context=None,
                )
            )
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


def _build_usage(state: ServeState) -> dict[str, Any]:
    from ahadiff.core.paths import usage_db_path, workspace_identity_lookup_keys
    from ahadiff.llm.usage import connect_usage_db

    db_path = usage_db_path()
    if not db_path.is_file():
        return {"models": [], "total_calls": 0}

    current_identity, legacy_identity = workspace_identity_lookup_keys(state.state_dir.parent)
    try:
        with connect_usage_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT model_id,
                       COUNT(*) AS call_count,
                       SUM(input_tokens) AS total_input,
                       SUM(output_tokens) AS total_output,
                       SUM(cost_usd) AS total_cost
                FROM llm_usage
                WHERE workspace_identity IN (?, ?)
                GROUP BY model_id
                ORDER BY call_count DESC
                """,
                (current_identity, legacy_identity),
            ).fetchall()
    except Exception as error:
        raise RuntimeError("usage database is unavailable") from error

    total_calls = 0
    models: list[dict[str, Any]] = []
    for row in rows:
        count = int(row[1])
        total_calls += count
        cost = float(row[4]) if row[4] is not None else None
        if cost is not None and not math.isfinite(cost):
            cost = None
        models.append(
            {
                "model_id": str(row[0]),
                "call_count": count,
                "total_input_tokens": int(row[2]) if row[2] is not None else 0,
                "total_output_tokens": int(row[3]) if row[3] is not None else 0,
                "total_cost_usd": cost,
            }
        )
    return {"models": models, "total_calls": total_calls}


async def get_usage(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    state: ServeState = serve_state(request)
    try:
        payload = await to_thread.run_sync(_build_usage, state)
    except Exception as error:
        log.warning("usage API failed", exc_info=True)
        raise HTTPException(status_code=500, detail="usage database is unavailable") from error
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# /api/spec/alignment
# ---------------------------------------------------------------------------


def _build_spec_alignment(state: ServeState) -> dict[str, Any]:
    db_path = state.review_db_path
    if not db_path.is_file():
        return {"alignment_score": None, "total_evaluated": 0, "recent_trend": None}

    try:
        with connect_review_db(db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*), AVG(overall)
                FROM result_events
                WHERE status IN ('baseline', 'keep', 'keep_final')
                """
            ).fetchone()
    except sqlite3.OperationalError:
        return {"alignment_score": None, "total_evaluated": 0, "recent_trend": None}

    if not row or row[0] == 0:
        return {"alignment_score": None, "total_evaluated": 0, "recent_trend": None}

    total = int(row[0])
    avg = float(row[1]) if row[1] is not None else None
    if avg is not None and not math.isfinite(avg):
        avg = None

    trend: str | None = None
    if total >= 4:
        try:
            with connect_review_db(db_path) as conn:
                half = total // 2
                earlier = conn.execute(
                    """
                    SELECT AVG(overall) FROM (
                        SELECT overall FROM result_events
                        WHERE status IN ('baseline', 'keep', 'keep_final')
                        ORDER BY timestamp ASC
                        LIMIT ?
                    )
                    """,
                    (half,),
                ).fetchone()
                later = conn.execute(
                    """
                    SELECT AVG(overall) FROM (
                        SELECT overall FROM result_events
                        WHERE status IN ('baseline', 'keep', 'keep_final')
                        ORDER BY timestamp DESC
                        LIMIT ?
                    )
                    """,
                    (half,),
                ).fetchone()
                if earlier and later and earlier[0] is not None and later[0] is not None:
                    diff = float(later[0]) - float(earlier[0])
                    if diff > 1.0:
                        trend = "improving"
                    elif diff < -1.0:
                        trend = "declining"
                    else:
                        trend = "stable"
        except sqlite3.OperationalError:
            pass

    return {"alignment_score": avg, "total_evaluated": total, "recent_trend": trend}


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
]
