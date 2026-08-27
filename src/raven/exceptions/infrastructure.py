"""Infrastructure failures safe to surface at the UI boundary."""


class InfrastructureError(RuntimeError):
    """Raised when a configured infrastructure service cannot be initialized."""


class InfrastructureAuthenticationError(InfrastructureError):
    """Raised when a reachable service rejects or requires credentials."""


class InfrastructureConfigurationError(InfrastructureError):
    """Raised when a reachable service needs additional configuration."""
