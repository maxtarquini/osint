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
