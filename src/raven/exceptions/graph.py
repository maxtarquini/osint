"""Failures at safe boundaries of the Evidence-to-Graph pipeline."""


class GraphAnalysisError(RuntimeError):
    """Base error for graph analysis operations."""


class GraphAnalysisValidationError(GraphAnalysisError):
    """The selected investigation or Evidence cannot be analyzed."""


class GraphAgentError(GraphAnalysisError):
    """An AI agent returned an unavailable or invalid result."""


class GraphAgentRequestError(GraphAgentError):
    """A bounded model request failed; repeating it immediately is not useful."""

    def __init__(self, message: str, code: str = "request_failed") -> None:
        super().__init__(message)
        self.code = code


class CatalogBatchError(GraphAgentError):
    """All documents were attempted, but some pages still need correction."""

    def __init__(self, failed: int, total: int) -> None:
        super().__init__(
            f"Some pages could not be classified in {failed}/{total} documents. "
            "Other documents were processed. Open page errors and retry."
        )


class CatalogValidationError(GraphAgentError):
    """A catalog response violates the schema or lacks source support."""

    def __init__(self, reason: str, *, rejected_fields: dict | None = None) -> None:
        super().__init__(f"Catalog validation failed: {reason}")
        self.code = "validation_failed"
        self.rejected_fields = rejected_fields or {}


class GraphPersistenceError(GraphAnalysisError):
    """A graph run or snapshot could not be persisted."""


class GraphAnalysisCancelledError(GraphAnalysisError):
    """The analyst cancelled the active graph run."""
