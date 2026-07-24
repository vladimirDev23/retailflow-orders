class DomainError(Exception):
    """Base class for business-rule violations."""


class DomainValidationError(DomainError):
    """Raised when a domain value cannot be constructed safely."""


class InvalidOrderTransitionError(DomainError):
    """Raised when the requested state transition is not allowed."""
