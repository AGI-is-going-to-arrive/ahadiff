from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from pydantic import ValidationError

from ahadiff.core.errors import InputError
from ahadiff.safety.redact import redaction_pipeline

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from .provider import ManagedProvider
    from .schemas import ProviderRequest, ProviderResponse
    from .structured import OutputSchemaSpec
else:
    ManagedProvider = Any
    OutputSchemaSpec = Any
    ProviderRequest = Any
    ProviderResponse = Any

T = TypeVar("T")
_MAX_VALIDATION_RETRIES = 2
_MAX_ERROR_MESSAGE_LENGTH = 200
_SENSITIVE_PATH_COMPONENT_RE = re.compile(
    r"(api[_-]?key|auth|bearer|credential|password|passwd|private|secret|token)",
    re.IGNORECASE,
)
_ABSOLUTE_PATH_RE = re.compile(
    r"(?:/[^\s\"'`]+(?:/[^\s\"'`]+)+|[A-Za-z]:\\[^\s\"'`]+|\\\\[^\s\"'`]+)"
)


@dataclass(frozen=True)
class StructuredCallResult(Generic[T]):
    value: T
    response: ProviderResponse
    attempts: int
    validation_errors: tuple[str, ...] = ()


def build_validation_retry_feedback(
    *,
    schema_id: str,
    schema_version: str,
    errors: Iterable[Mapping[str, object]],
) -> str:
    payload = {
        "schema": f"{schema_id}.v{schema_version}",
        "errors": [_validation_error_payload(error) for error in errors],
    }
    return (
        "The previous response did not match the required output schema. "
        "Return corrected JSON only.\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def generate_with_validation_retry(
    *,
    provider: ManagedProvider,
    request: ProviderRequest,
    schema_spec: OutputSchemaSpec,
    parse: Callable[[str], T],
    fallback_parse: Callable[[str], T] | None = None,
    max_validation_retries: int,
) -> StructuredCallResult[T]:
    if max_validation_retries < 0 or max_validation_retries > _MAX_VALIDATION_RETRIES:
        raise InputError("structured validation retries must be between 0 and 2")

    current_request = request
    validation_errors: list[str] = []
    last_error: Exception | None = None
    for attempt_index in range(max_validation_retries + 1):
        response = provider.generate(current_request)
        try:
            return StructuredCallResult(
                value=parse(response.content),
                response=response,
                attempts=attempt_index + 1,
                validation_errors=tuple(validation_errors),
            )
        except Exception as exc:
            last_error = exc
            if fallback_parse is not None:
                try:
                    return StructuredCallResult(
                        value=fallback_parse(response.content),
                        response=response,
                        attempts=attempt_index + 1,
                        validation_errors=tuple(validation_errors),
                    )
                except Exception as fallback_exc:
                    last_error = fallback_exc
            errors = _errors_from_exception(exc)
            feedback = build_validation_retry_feedback(
                schema_id=schema_spec.schema_id,
                schema_version=schema_spec.schema_version,
                errors=errors,
            )
            validation_errors.append(feedback)
            if attempt_index >= max_validation_retries:
                break
            current_request = _request_with_feedback(current_request, feedback)

    if last_error is not None:
        raise InputError(
            "structured output validation failed after "
            f"{max_validation_retries + 1} attempt(s); provider output omitted"
        ) from None
    raise InputError("structured validation retry failed without a parser error")


def _validation_error_payload(error: Mapping[str, object]) -> dict[str, str]:
    return {
        "path": _format_error_path(error.get("loc")),
        "type": _sanitize_error_text(error.get("type")),
        "message": _sanitize_error_text(error.get("msg")),
    }


def _format_error_path(raw_loc: object) -> str:
    if isinstance(raw_loc, tuple | list):
        parts = [_sanitize_error_path_component(part) for part in cast("Iterable[object]", raw_loc)]
        return ".".join(part for part in parts if part)
    if raw_loc is None:
        return "$"
    return _sanitize_error_path_component(raw_loc)


def _sanitize_error_path_component(value: object) -> str:
    text = _sanitize_error_text(value)
    if _SENSITIVE_PATH_COMPONENT_RE.search(text):
        return "[sensitive path omitted]"
    return text


def _sanitize_error_text(value: object) -> str:
    text = " ".join(("" if value is None else str(value)).split())
    text = text.replace("diff --git", "[diff omitted]")
    text = text.replace('"properties"', "[schema omitted]")
    text = redaction_pipeline(text).redacted_text
    text = _ABSOLUTE_PATH_RE.sub("[path omitted]", text)
    if len(text) > _MAX_ERROR_MESSAGE_LENGTH:
        return text[:_MAX_ERROR_MESSAGE_LENGTH].rstrip() + "..."
    return text


def _errors_from_exception(exc: Exception) -> tuple[Mapping[str, object], ...]:
    if isinstance(exc, ValidationError):
        return tuple(cast("Mapping[str, object]", error) for error in exc.errors())
    if isinstance(exc, InputError) and isinstance(exc.__cause__, ValidationError):
        return tuple(cast("Mapping[str, object]", error) for error in exc.__cause__.errors())
    return (
        {
            "loc": (),
            "type": type(exc).__name__,
            "msg": "parser failed; provider output omitted",
        },
    )


def _request_with_feedback(request: ProviderRequest, feedback: str) -> ProviderRequest:
    payload_text = f"{request.payload_text}\n\n{feedback}"
    redacted_payload_text = request.redacted_payload_text
    if redacted_payload_text is not None:
        redacted_payload_text = f"{redacted_payload_text}\n\n{feedback}"
    return replace(
        request,
        payload_text=payload_text,
        redacted_payload_text=redacted_payload_text,
    )


__all__ = [
    "StructuredCallResult",
    "build_validation_retry_feedback",
    "generate_with_validation_retry",
]
