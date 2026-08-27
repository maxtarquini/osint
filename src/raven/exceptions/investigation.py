"""Investigation creation failures safe for use-case boundaries."""


class InvestigationError(RuntimeError):
    """Base failure for investigation operations."""


class InvestigationValidationError(InvestigationError):
    """Raised when investigation or evidence input is invalid."""


class InvestigationPersistenceError(InvestigationError):
    """Raised when investigation metadata cannot be persisted."""


class InvestigationCancelledError(InvestigationError):
    """Raised when the user cancels knowledge-base creation."""
