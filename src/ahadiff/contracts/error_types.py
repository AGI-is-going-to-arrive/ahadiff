class AhaDiffError(Exception):
    """Base contract error."""


class InputError(AhaDiffError):
    """Invalid user or diff input."""


class SafetyError(AhaDiffError):
    """Secret, privacy, or trust boundary violation."""


class ProviderError(AhaDiffError):
    """Provider probe or generation failure."""


class VerificationError(AhaDiffError):
    """Claim or evaluator verification failure."""


class StorageError(AhaDiffError):
    """SQLite, file system, or lock failure."""


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
