from __future__ import annotations

from typing import Any

from .error_codes import ErrorCode


class AhaDiffError(Exception):
    """Base contract error."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    details: dict[str, Any]

    def __init__(
        self,
        message: str = "",
        *args: object,
        code: ErrorCode | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, *args)
        self.code = code if code is not None else self.__class__.code
        self.details = dict(details) if details is not None else {}


class InputError(AhaDiffError):
    """Invalid user or diff input."""

    code = ErrorCode.INPUT_BAD_FIELD


class SafetyError(AhaDiffError):
    """Secret, privacy, or trust boundary violation."""

    code = ErrorCode.LOOPBACK_DENIED


class ProviderError(AhaDiffError):
    """Provider probe or generation failure."""

    code = ErrorCode.PROVIDER_HTTP


class VerificationError(AhaDiffError):
    """Claim or evaluator verification failure."""


class StorageError(AhaDiffError):
    """SQLite, file system, or lock failure."""

    code = ErrorCode.STORAGE_FS


class MigrationError(StorageError):
    """Schema migration failure."""


class DegradedRunWarning(UserWarning):
    """Run completed with degraded guarantees."""


__all__ = [
    "AhaDiffError",
    "InputError",
    "SafetyError",
    "ProviderError",
    "VerificationError",
    "StorageError",
    "MigrationError",
    "DegradedRunWarning",
]
