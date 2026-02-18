class BlackboardError(Exception):
    """Base blackboard error."""


class RevisionConflictError(BlackboardError):
    """Raised when optimistic concurrency check fails."""


class SchemaValidationError(BlackboardError):
    """Raised when data does not match the registered schema."""


class BackendNotConfiguredError(BlackboardError):
    """Raised when a requested backend is unavailable or not configured."""


class DocumentNotFoundError(BlackboardError):
    """Raised when a session blackboard document does not exist."""
