"""Failures at safe boundaries of the Evidence-to-Graph pipeline."""


class GraphAnalysisError(RuntimeError):
    """Base error for graph analysis operations."""


class GraphAnalysisValidationError(GraphAnalysisError):
    """The selected investigation or Evidence cannot be analyzed."""


class GraphAgentError(GraphAnalysisError):
    """An AI agent returned an unavailable or invalid result."""


class GraphPersistenceError(GraphAnalysisError):
    """A graph run or snapshot could not be persisted."""


class GraphAnalysisCancelledError(GraphAnalysisError):
    """The analyst cancelled the active graph run."""


class GraphAgentRequestError(GraphAgentError):
    """A bounded model request failed; repeating it immediately is not useful."""

    def __init__(self, message: str, code: str = "request_failed") -> None:
        super().__init__(message)
        self.code = code


class CatalogValidationError(GraphAgentError):
    """A page-catalog response violates its schema or lacks source support."""

    def __init__(self, reason: str, *, rejected_fields: dict | None = None) -> None:
        super().__init__(f"Catalog validation failed: {reason}")
        self.code = "validation_failed"
        self.rejected_fields = rejected_fields or {}
