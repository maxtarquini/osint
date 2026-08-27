"""Configuration failures safe to surface at the UI boundary."""


class ConfigurationError(ValueError):
    """Raised when Raven configuration is missing, malformed, or unsafe."""
