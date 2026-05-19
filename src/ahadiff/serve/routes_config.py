"""GET /api/config and GET /api/doctor endpoints."""

from __future__ import annotations

import logging
import math
import sqlite3
from typing import TYPE_CHECKING, Any, Literal, cast

from anyio import to_thread
from starlette.responses import JSONResponse

from ahadiff.contracts.serve_app import ConfigResponse, ConfigUpdateResponse
from ahadiff.contracts.serve_doctor import DoctorCheck, DoctorResponse
from ahadiff.core.sqlite_util import safe_sqlite_connect

if TYPE_CHECKING:
    from starlette.requests import Request

    from .state import ServeState

log = logging.getLogger(__name__)

_QUIZ_DEFAULTS: dict[str, Any] = {
    "quiz_question_count": 3,
    "quiz_question_count_mode": "fixed",
    "quiz_auto_range_min": 3,
    "quiz_auto_range_max": 8,
}


def _empty_config_snapshot() -> dict[str, Any]:
    return {
        "lang": None,
        "privacy_mode": None,
        "generate_provider": None,
        "generate_model": None,
        "judge_provider": None,
        "judge_model": None,
        "serve_port": None,
        "key_status": {},
        "capture": {
            "max_files": 30,
            "hard_limit": 3000,
            "max_patch_bytes": 5_000_000,
            "file_ranking": "learning_value",
            "symbol_extractor": "auto",
        },
        "llm": {
            "input_token_budget": 200_000,
            "output_token_budget": 50_000,
            "request_timeout_seconds": 30,
            "max_concurrent": 3,
            "retry_attempts": 3,
            "output_lang": "auto",
        },
        "learn": {
            "learnability_threshold": 0.3,
            "desired_retention": 0.9,
        },
        "quiz": dict(_QUIZ_DEFAULTS),
    }


def _object_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in cast("dict[object, object]", value).items()}


def _provider_key_status(providers: object) -> dict[str, str]:
    import os

    statuses: dict[str, str] = {}
    for provider_name, raw_provider in _object_mapping(providers).items():
        provider_values = _object_mapping(raw_provider)
        api_key_env = provider_values.get("api_key_env")
        if isinstance(api_key_env, str) and api_key_env:
            statuses[provider_name] = "configured" if os.environ.get(api_key_env) else "missing"
    return statuses


def _add_legacy_llm_key_status(key_status: dict[str, str], api_key_env: object) -> None:
    if not isinstance(api_key_env, str) or not api_key_env:
        return
    import os

    key_status.setdefault("llm", "configured" if os.environ.get(api_key_env) else "missing")


def _safe_config_snapshot(state: ServeState) -> dict[str, Any]:
    from .config_runtime import load_serve_config_snapshot

    try:
        cfg = load_serve_config_snapshot(state)
    except Exception:
        return _empty_config_snapshot()

    values = getattr(cfg, "values", None)
    if isinstance(values, dict):
        snapshot_values = _object_mapping(cast("object", values))
        llm_values = _object_mapping(snapshot_values.get("llm"))
        serve_values = _object_mapping(snapshot_values.get("serve"))
        capture_values = _object_mapping(snapshot_values.get("capture"))
        quiz_values = _object_mapping(snapshot_values.get("quiz"))
        result: dict[str, Any] = {
            "lang": snapshot_values.get("lang"),
            "privacy_mode": snapshot_values.get("privacy_mode"),
            "generate_provider": llm_values.get("generate_provider", ""),
            "generate_model": llm_values.get("generate_model"),
            "judge_provider": llm_values.get("judge_provider", ""),
            "judge_model": llm_values.get("judge_model"),
            "serve_port": serve_values.get("port"),
            "capture": {
                "max_files": capture_values.get("max_files", 30),
                "hard_limit": capture_values.get("hard_limit", 3000),
                "max_patch_bytes": capture_values.get("max_patch_bytes", 5_000_000),
                "file_ranking": capture_values.get("file_ranking", "learning_value"),
                "symbol_extractor": capture_values.get("symbol_extractor", "auto"),
            },
            "llm": {
                "input_token_budget": llm_values.get("input_token_budget", 200_000),
                "output_token_budget": llm_values.get("output_token_budget", 50_000),
                "request_timeout_seconds": llm_values.get("request_timeout_seconds", 30),
                "max_concurrent": llm_values.get("max_concurrent", 3),
                "retry_attempts": llm_values.get("retry_attempts", 3),
                "output_lang": llm_values.get("output_lang", "auto"),
            },
            "quiz": {
                "quiz_question_count": quiz_values.get("quiz_question_count", 3),
                "quiz_question_count_mode": quiz_values.get("quiz_question_count_mode", "fixed"),
                "quiz_auto_range_min": quiz_values.get("quiz_auto_range_min", 3),
                "quiz_auto_range_max": quiz_values.get("quiz_auto_range_max", 8),
            },
        }
        learn_values = _object_mapping(snapshot_values.get("learn"))
        result["learn"] = {
            "learnability_threshold": learn_values.get("learnability_threshold", 0.3),
            "desired_retention": learn_values.get("desired_retention", 0.9),
        }
        api_key_env = llm_values.get("api_key_env")
        providers = snapshot_values.get("providers")
    else:
        result = {}
        result["lang"] = getattr(cfg, "lang", None)
        result["privacy_mode"] = getattr(cfg, "privacy_mode", None)

        llm = getattr(cfg, "llm", None)
        result["generate_provider"] = getattr(llm, "generate_provider", "") if llm else ""
        result["generate_model"] = getattr(llm, "generate_model", None) if llm else None
        result["judge_provider"] = getattr(llm, "judge_provider", "") if llm else ""
        result["judge_model"] = getattr(llm, "judge_model", None) if llm else None

        serve = getattr(cfg, "serve", None)
        result["serve_port"] = getattr(serve, "port", None) if serve else None
        result["capture"] = {
            "max_files": 30,
            "hard_limit": 3000,
            "max_patch_bytes": 5_000_000,
            "file_ranking": "learning_value",
            "symbol_extractor": "auto",
        }
        result["llm"] = {
            "input_token_budget": 200_000,
            "output_token_budget": 50_000,
            "request_timeout_seconds": 30,
            "max_concurrent": 3,
            "retry_attempts": 3,
            "output_lang": "auto",
        }
        result["learn"] = {"learnability_threshold": 0.3, "desired_retention": 0.9}
        result["quiz"] = dict(_QUIZ_DEFAULTS)
        api_key_env = getattr(llm, "api_key_env", None) if llm else None
        providers = getattr(cfg, "providers", None)

    key_status = _provider_key_status(providers)
    _add_legacy_llm_key_status(key_status, api_key_env)
    result["key_status"] = key_status

    return result


def _doctor_check(
    name: str,
    status: str,
    message: str,
    *,
    category: str,
    details: dict[str, Any] | None = None,
) -> DoctorCheck:
    return DoctorCheck(
        name=name,
        category=category,
        status=cast("Any", status),
        message=message,
        details=details or {},
    )


def _summary_status(checks: list[DoctorCheck]) -> str:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "pass"


def _run_doctor_checks(state: ServeState) -> dict[str, Any]:
    checks: list[DoctorCheck] = []

    repo_root = state.state_dir.parent
    ahadiff_dir = repo_root / ".ahadiff"
    checks.append(
        _doctor_check(
            "repo_root",
            "pass" if ahadiff_dir.is_dir() else "fail",
            ".ahadiff/ exists" if ahadiff_dir.is_dir() else ".ahadiff/ not found",
            category="paths",
            details={"path": ".ahadiff"},
        )
    )
    checks.append(
        _doctor_check(
            "state_dir_path",
            "pass" if state.state_dir.is_dir() else "fail",
            "state directory is accessible"
            if state.state_dir.is_dir()
            else "state directory is missing",
            category="paths",
            details={"name": state.state_dir.name},
        )
    )

    sqlite_ver = sqlite3.sqlite_version
    checks.append(
        _doctor_check(
            "sqlite_version",
            "pass",
            f"SQLite {sqlite_ver}",
            category="runtime",
        )
    )
    checks.append(
        _doctor_check(
            "sqlite_runtime_gate",
            "pass",
            f"SQLite runtime accepted: {sqlite_ver}",
            category="runtime",
        )
    )

    cfg: Any | None = None
    try:
        from ahadiff.core.config import load_config

        cfg = load_config(repo_root)
        checks.append(
            _doctor_check(
                "config_valid",
                "pass",
                "Config loaded successfully",
                category="config",
            )
        )
    except Exception as exc:
        checks.append(
            _doctor_check(
                "config_valid",
                "fail",
                f"Config error: {type(exc).__name__}",
                category="config",
            )
        )

    unknown_keys: list[str] = []
    sensitive_keys: list[str] = []
    precedence_conflicts: list[str] = []
    if cfg is not None:
        for attr in ("repo_unknown_keys", "global_unknown_keys"):
            unknown_keys.extend(str(item) for item in getattr(cfg, attr, ()) or ())
        sensitive_keys.extend(str(item) for item in getattr(cfg, "repo_sensitive_keys", ()) or ())
        precedence_conflicts.extend(
            str(item) for item in getattr(cfg, "precedence_conflicts", ()) or ()
        )
    checks.append(
        _doctor_check(
            "config_unknown_keys",
            "warn" if unknown_keys else "pass",
            "Unknown config keys found" if unknown_keys else "No unknown config keys",
            category="config",
            details={"count": len(unknown_keys), "keys": unknown_keys[:20]},
        )
    )
    checks.append(
        _doctor_check(
            "config_sensitive_keys",
            "fail" if sensitive_keys else "pass",
            "Sensitive config keys found" if sensitive_keys else "No sensitive config keys",
            category="config",
            details={"count": len(sensitive_keys), "keys": sensitive_keys[:20]},
        )
    )
    checks.append(
        _doctor_check(
            "config_precedence_conflicts",
            "warn" if precedence_conflicts else "pass",
            "Config precedence conflicts found"
            if precedence_conflicts
            else "No config precedence conflicts",
            category="config",
            details={"count": len(precedence_conflicts)},
        )
    )

    review_db = state.state_dir / "review.sqlite"
    checks.append(
        _doctor_check(
            "review_db",
            "pass" if review_db.is_file() else "warn",
            "review.sqlite present" if review_db.is_file() else "review.sqlite not found",
            category="storage",
        )
    )
    if review_db.is_file():
        try:
            with safe_sqlite_connect(review_db) as conn:
                row = conn.execute("PRAGMA quick_check").fetchone()
            quick_check_ok = row is not None and row[0] == "ok"
            checks.append(
                _doctor_check(
                    "review_db_quick_check",
                    "pass" if quick_check_ok else "fail",
                    "review.sqlite quick_check ok"
                    if quick_check_ok
                    else "review.sqlite quick_check failed",
                    category="storage",
                )
            )
        except (sqlite3.DatabaseError, OSError):
            checks.append(
                _doctor_check(
                    "review_db_quick_check",
                    "fail",
                    "review.sqlite quick_check failed",
                    category="storage",
                )
            )
    else:
        checks.append(
            _doctor_check(
                "review_db_quick_check",
                "warn",
                "review.sqlite not found",
                category="storage",
            )
        )

    try:
        from ahadiff.core.paths import usage_db_path

        usage_db = usage_db_path()
        checks.append(
            _doctor_check(
                "usage_db",
                "pass" if usage_db.is_file() else "warn",
                "usage.sqlite present" if usage_db.is_file() else "usage.sqlite not found",
                category="storage",
                details={"filename": usage_db.name},
            )
        )
    except Exception:
        checks.append(
            _doctor_check(
                "usage_db",
                "warn",
                "usage.sqlite path unavailable",
                category="storage",
            )
        )

    audit_path = state.state_dir / "audit.jsonl"
    checks.append(
        _doctor_check(
            "audit_file",
            "pass" if audit_path.is_file() else "warn",
            "audit.jsonl present" if audit_path.is_file() else "audit.jsonl not found",
            category="storage",
        )
    )

    return DoctorResponse(
        summary_status=cast("Any", _summary_status(checks)),
        checks=checks,
    ).model_dump(mode="json")


async def get_config(request: Request) -> JSONResponse:
    from .auth import serve_state

    state: ServeState = serve_state(request)
    snapshot = await to_thread.run_sync(_safe_config_snapshot, state)
    return JSONResponse(ConfigResponse.model_validate(snapshot).model_dump(mode="json"))


async def get_doctor(request: Request) -> JSONResponse:
    from .auth import serve_state

    state: ServeState = serve_state(request)
    payload = await to_thread.run_sync(_run_doctor_checks, state)
    return JSONResponse(payload)


_ALLOWED_CONFIG_LANG = frozenset({"en", "zh-CN"})
_ALLOWED_PRIVACY_MODES = frozenset({"strict_local", "redacted_remote", "explicit_remote"})
_ALLOWED_FILE_RANKINGS = frozenset({"learning_value", "changed_lines", "path"})
_CAPTURE_INT_FIELDS: dict[str, tuple[int, int]] = {
    "max_files": (1, 500),
    "hard_limit": (100, 100_000),
    "max_patch_bytes": (10_000, 100_000_000),
}
_LLM_INT_FIELDS: dict[str, tuple[int, int]] = {
    "input_token_budget": (1_000, 10_000_000),
    "output_token_budget": (1_000, 10_000_000),
    "request_timeout_seconds": (5, 600),
    "max_concurrent": (1, 20),
    "retry_attempts": (0, 10),
    "structured_validation_retries": (0, 2),
}
_ALLOWED_SYMBOL_EXTRACTORS = frozenset({"auto", "builtin", "tree_sitter"})
_ALLOWED_OUTPUT_LANGS = frozenset({"auto", "en", "zh-CN"})
_ALLOWED_STRUCTURED_OUTPUT_MODES = frozenset(
    {
        "prompt_contract",
        "json_object",
        "native_json_schema",
        "strict_tool",
    }
)
_ALLOWED_QUIZ_COUNT_MODES = frozenset({"fixed", "auto"})
_QUIZ_INT_FIELDS = {
    "quiz_question_count",
    "quiz_auto_range_min",
    "quiz_auto_range_max",
}


def _validate_llm_update(llm: object) -> dict[str, Any] | str:
    if not isinstance(llm, dict):
        return "llm must be a JSON object"
    llm_dict = cast("dict[str, Any]", llm)
    allowed = set(_LLM_INT_FIELDS) | {"output_lang", "structured_output_mode"}
    unknown_llm: set[str] = set(llm_dict.keys()) - allowed
    if unknown_llm:
        return f"unknown llm keys: {sorted(unknown_llm)}"
    validated: dict[str, Any] = {}
    for field_name, (lo, hi) in _LLM_INT_FIELDS.items():
        if field_name in llm_dict:
            val: object = llm_dict[field_name]
            if not isinstance(val, int) or isinstance(val, bool):
                return f"llm.{field_name} must be an integer"
            if val < lo or val > hi:
                return f"llm.{field_name} must be between {lo} and {hi}"
            validated[field_name] = val
    if "output_lang" in llm_dict:
        ol: object = llm_dict["output_lang"]
        if not isinstance(ol, str) or ol not in _ALLOWED_OUTPUT_LANGS:
            return f"llm.output_lang must be one of {sorted(_ALLOWED_OUTPUT_LANGS)}"
        validated["output_lang"] = ol
    if "structured_output_mode" in llm_dict:
        mode: object = llm_dict["structured_output_mode"]
        if not isinstance(mode, str) or mode not in _ALLOWED_STRUCTURED_OUTPUT_MODES:
            return (
                "llm.structured_output_mode must be one of "
                f"{sorted(_ALLOWED_STRUCTURED_OUTPUT_MODES)}"
            )
        validated["structured_output_mode"] = mode
    return validated


def _validate_capture_update(capture: object) -> dict[str, Any] | str:
    if not isinstance(capture, dict):
        return "capture must be a JSON object"
    capture_dict = cast("dict[str, Any]", capture)
    allowed = {"max_files", "hard_limit", "max_patch_bytes", "file_ranking", "symbol_extractor"}
    unknown_cap: set[str] = set(capture_dict.keys()) - allowed
    if unknown_cap:
        return f"unknown capture keys: {sorted(unknown_cap)}"
    validated: dict[str, Any] = {}
    for field_name, (lo, hi) in _CAPTURE_INT_FIELDS.items():
        if field_name in capture_dict:
            val: object = capture_dict[field_name]
            if not isinstance(val, int) or isinstance(val, bool):
                return f"capture.{field_name} must be an integer"
            if val < lo or val > hi:
                return f"capture.{field_name} must be between {lo} and {hi}"
            validated[field_name] = val
    if "file_ranking" in capture_dict:
        ranking: object = capture_dict["file_ranking"]
        if not isinstance(ranking, str) or ranking not in _ALLOWED_FILE_RANKINGS:
            return f"capture.file_ranking must be one of {sorted(_ALLOWED_FILE_RANKINGS)}"
        validated["file_ranking"] = ranking
    if "symbol_extractor" in capture_dict:
        se: object = capture_dict["symbol_extractor"]
        if not isinstance(se, str) or se not in _ALLOWED_SYMBOL_EXTRACTORS:
            return f"capture.symbol_extractor must be one of {sorted(_ALLOWED_SYMBOL_EXTRACTORS)}"
        validated["symbol_extractor"] = se
    return validated


def _validate_learn_update(learn: object) -> dict[str, Any] | str:
    if not isinstance(learn, dict):
        return "learn must be a JSON object"
    learn_dict = cast("dict[str, Any]", learn)
    allowed = {"learnability_threshold", "desired_retention"}
    unknown_learn: set[str] = set(learn_dict.keys()) - allowed
    if unknown_learn:
        return f"unknown learn keys: {sorted(unknown_learn)}"
    validated: dict[str, Any] = {}
    if "learnability_threshold" in learn_dict:
        val: object = learn_dict["learnability_threshold"]
        if not isinstance(val, int | float) or isinstance(val, bool):
            return "learn.learnability_threshold must be a number"
        parsed = float(val)
        if not math.isfinite(parsed):
            return "learn.learnability_threshold must be a finite number"
        if parsed < 0.0 or parsed > 1.0:
            return "learn.learnability_threshold must be between 0.0 and 1.0"
        validated["learnability_threshold"] = parsed
    if "desired_retention" in learn_dict:
        val = learn_dict["desired_retention"]
        if not isinstance(val, int | float) or isinstance(val, bool):
            return "learn.desired_retention must be a number"
        parsed = float(val)
        if not math.isfinite(parsed):
            return "learn.desired_retention must be a finite number"
        if parsed < 0.7 or parsed > 0.99:
            return "learn.desired_retention must be between 0.7 and 0.99"
        validated["desired_retention"] = parsed
    return validated


def _validate_quiz_int_field(field: str, value: object) -> int | str:
    if not isinstance(value, int) or isinstance(value, bool):
        return f"quiz.{field} must be an integer"
    if value < 1 or value > 10:
        return f"quiz.{field} must be between 1 and 10"
    return value


def _validate_effective_quiz_config(values: dict[str, object]) -> str | None:
    mode = values.get("quiz_question_count_mode", _QUIZ_DEFAULTS["quiz_question_count_mode"])
    if not isinstance(mode, str) or mode not in _ALLOWED_QUIZ_COUNT_MODES:
        allowed_modes = sorted(_ALLOWED_QUIZ_COUNT_MODES)
        return f"quiz.quiz_question_count_mode must be one of {allowed_modes}"
    for field in _QUIZ_INT_FIELDS:
        parsed = _validate_quiz_int_field(field, values.get(field))
        if isinstance(parsed, str):
            return parsed
        values[field] = parsed
    range_min = values["quiz_auto_range_min"]
    range_max = values["quiz_auto_range_max"]
    if isinstance(range_min, int) and isinstance(range_max, int) and range_min > range_max:
        return "quiz.quiz_auto_range_min must be <= quiz.quiz_auto_range_max"
    return None


def _current_quiz_config_for_update(state: ServeState) -> dict[str, object]:
    from ahadiff.core.config import read_config_data

    config_path = state.state_dir / "config.toml"
    if not config_path.exists():
        return {}
    raw_config = read_config_data(config_path)
    return _object_mapping(raw_config.get("quiz"))


def _validate_quiz_update(
    quiz: object,
    *,
    current_quiz: object | None = None,
) -> dict[str, Any] | str:
    if not isinstance(quiz, dict):
        return "quiz must be a JSON object"
    quiz_dict = cast("dict[str, Any]", quiz)
    allowed = _QUIZ_INT_FIELDS | {"quiz_question_count_mode"}
    unknown_quiz: set[str] = set(quiz_dict.keys()) - allowed
    if unknown_quiz:
        return f"unknown quiz keys: {sorted(unknown_quiz)}"
    validated: dict[str, Any] = {}
    if "quiz_question_count_mode" in quiz_dict:
        mode: object = quiz_dict["quiz_question_count_mode"]
        if not isinstance(mode, str) or mode not in _ALLOWED_QUIZ_COUNT_MODES:
            allowed_modes = sorted(_ALLOWED_QUIZ_COUNT_MODES)
            return f"quiz.quiz_question_count_mode must be one of {allowed_modes}"
        validated["quiz_question_count_mode"] = mode
    for field in _QUIZ_INT_FIELDS:
        if field not in quiz_dict:
            continue
        parsed = _validate_quiz_int_field(field, quiz_dict[field])
        if isinstance(parsed, str):
            return parsed
        validated[field] = parsed

    current_values = _object_mapping(current_quiz)
    effective_values: dict[str, object] = dict(_QUIZ_DEFAULTS)
    effective_values.update({key: current_values[key] for key in allowed if key in current_values})
    effective_values.update(validated)
    effective_error = _validate_effective_quiz_config(effective_values)
    if effective_error is not None:
        return effective_error
    return validated


async def put_config(request: Request) -> JSONResponse:
    from .auth import require_write_token, serve_state

    require_write_token(request)
    payload: Any = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse({"error": "expected JSON object", "status": 400}, status_code=400)

    body = cast("dict[str, Any]", payload)
    allowed_keys: set[str] = {
        "lang",
        "capture",
        "privacy_mode",
        "generate_provider",
        "generate_model",
        "judge_provider",
        "judge_model",
        "serve_port",
        "llm",
        "learn",
        "quiz",
    }
    unknown: set[str] = set(body.keys()) - allowed_keys
    if unknown:
        return JSONResponse(
            {"error": f"unknown config keys: {sorted(unknown)}", "status": 400},
            status_code=400,
        )

    state = serve_state(request)
    persist_updates: dict[str, Any] = {}
    lang_update: Literal["en", "zh-CN"] | None = None

    if "lang" in body:
        lang: str = str(body["lang"])
        if lang not in _ALLOWED_CONFIG_LANG:
            return JSONResponse(
                {"error": f"lang must be one of {sorted(_ALLOWED_CONFIG_LANG)}", "status": 400},
                status_code=400,
            )
        lang_update = cast("Literal['en', 'zh-CN']", lang)
        persist_updates["lang"] = lang

    if "privacy_mode" in body:
        pm: object = body["privacy_mode"]
        if not isinstance(pm, str) or pm not in _ALLOWED_PRIVACY_MODES:
            return JSONResponse(
                {
                    "error": f"privacy_mode must be one of {sorted(_ALLOWED_PRIVACY_MODES)}",
                    "status": 400,
                },
                status_code=400,
            )
        persist_updates["privacy_mode"] = pm

    config_path = state.state_dir / "config.toml"
    configured_aliases: set[str] = set()
    if config_path.exists():
        try:
            from ahadiff.core.config import read_config_data

            raw = read_config_data(config_path)
            raw_providers = raw.get("providers")
            if isinstance(raw_providers, dict):
                providers = cast("dict[str, object]", raw_providers)
                configured_aliases = set(providers)
        except Exception:
            pass

    for role in ("generate", "judge"):
        prov_key = f"{role}_provider"
        if prov_key in body:
            pv: object = body[prov_key]
            if not isinstance(pv, str):
                return JSONResponse(
                    {"error": f"{prov_key} must be a string", "status": 400},
                    status_code=400,
                )
            pv_stripped = pv.strip()
            if pv_stripped and pv_stripped not in configured_aliases:
                return JSONResponse(
                    {
                        "error": (f"{prov_key} '{pv_stripped}' not found in configured providers"),
                        "status": 400,
                    },
                    status_code=400,
                )
            persist_updates.setdefault("llm", {})[prov_key] = pv_stripped

    if "generate_model" in body:
        gm: object = body["generate_model"]
        if not isinstance(gm, str) or not gm.strip():
            return JSONResponse(
                {"error": "generate_model must be a non-empty string", "status": 400},
                status_code=400,
            )
        persist_updates.setdefault("llm", {})["generate_model"] = gm.strip()

    if "judge_model" in body:
        jm: object = body["judge_model"]
        if not isinstance(jm, str) or not jm.strip():
            return JSONResponse(
                {"error": "judge_model must be a non-empty string", "status": 400},
                status_code=400,
            )
        persist_updates.setdefault("llm", {})["judge_model"] = jm.strip()

    if "serve_port" in body:
        sp: object = body["serve_port"]
        if not isinstance(sp, int) or isinstance(sp, bool):
            return JSONResponse(
                {"error": "serve_port must be an integer", "status": 400},
                status_code=400,
            )
        if sp < 1024 or sp > 65535:
            return JSONResponse(
                {"error": "serve_port must be between 1024 and 65535", "status": 400},
                status_code=400,
            )
        persist_updates.setdefault("serve", {})["port"] = sp

    if "llm" in body:
        llm_result = _validate_llm_update(body["llm"])
        if isinstance(llm_result, str):
            return JSONResponse({"error": llm_result, "status": 400}, status_code=400)
        if llm_result:
            persist_updates.setdefault("llm", {}).update(llm_result)

    if "capture" in body:
        result = _validate_capture_update(body["capture"])
        if isinstance(result, str):
            return JSONResponse({"error": result, "status": 400}, status_code=400)
        if result:
            persist_updates["capture"] = result

    if "learn" in body:
        learn_result = _validate_learn_update(body["learn"])
        if isinstance(learn_result, str):
            return JSONResponse({"error": learn_result, "status": 400}, status_code=400)
        if learn_result:
            persist_updates["learn"] = learn_result

    if "quiz" in body:
        try:
            current_quiz = await to_thread.run_sync(_current_quiz_config_for_update, state)
        except Exception as exc:
            return JSONResponse(
                {"error": f"cannot read current quiz config: {exc}", "status": 400},
                status_code=400,
            )
        quiz_result = _validate_quiz_update(body["quiz"], current_quiz=current_quiz)
        if isinstance(quiz_result, str):
            return JSONResponse({"error": quiz_result, "status": 400}, status_code=400)
        if quiz_result:
            persist_updates["quiz"] = quiz_result

    if persist_updates:
        from ahadiff.core.config import read_config_data, write_config_data

        def _persist_config(s: ServeState) -> None:
            config_path = s.state_dir.parent / ".ahadiff" / "config.toml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            data = read_config_data(config_path) if config_path.exists() else {}
            for key, value in persist_updates.items():
                if isinstance(value, dict):
                    section = data.setdefault(key, {})
                    section.update(value)
                else:
                    data[key] = value
            write_config_data(config_path, data)

        assert state.write_lock is not None
        async with state.write_lock:
            await to_thread.run_sync(_persist_config, state)
            if lang_update is not None:
                request.app.state.ahadiff = state.with_locale(lang_update)

    return JSONResponse(ConfigUpdateResponse(updated=True, scope="session").model_dump(mode="json"))
