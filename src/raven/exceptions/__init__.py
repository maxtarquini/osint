"""Application-specific exceptions."""

from raven.exceptions.chat import InvestigationChatCancelledError, InvestigationChatError
from raven.exceptions.configuration import ConfigurationError
from raven.exceptions.graph import (
    CatalogValidationError,
    GraphAgentError,
    GraphAgentRequestError,
    GraphAnalysisCancelledError,
    GraphAnalysisError,
    GraphAnalysisValidationError,
    GraphPersistenceError,
)
from raven.exceptions.infrastructure import (
    InfrastructureAuthenticationError,
    InfrastructureConfigurationError,
    InfrastructureError,
)
from raven.exceptions.investigation import (
    InvestigationCancelledError,
    InvestigationError,
    InvestigationPersistenceError,
    InvestigationValidationError,
)

__all__ = [
    "CatalogValidationError",
    "ConfigurationError",
    "GraphAgentError",
    "GraphAgentRequestError",
    "GraphAnalysisCancelledError",
    "GraphAnalysisError",
    "GraphAnalysisValidationError",
    "GraphPersistenceError",
    "InfrastructureAuthenticationError",
    "InfrastructureConfigurationError",
    "InfrastructureError",
    "InvestigationError",
    "InvestigationCancelledError",
    "InvestigationPersistenceError",
    "InvestigationValidationError",
    "InvestigationChatCancelledError",
    "InvestigationChatError",
]
