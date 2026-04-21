from ahadiff.contracts import (
    AhaDiffError,
    DegradedRunWarning,
    InputError,
    MigrationError,
    ProviderError,
    SafetyError,
    StorageError,
    VerificationError,
)


class ConfigError(InputError):
    """Raised when a config layer contains invalid data."""


__all__ = [
    "AhaDiffError",
    "ConfigError",
    "DegradedRunWarning",
    "InputError",
    "MigrationError",
    "ProviderError",
    "SafetyError",
    "StorageError",
    "VerificationError",
]
