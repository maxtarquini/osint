"""Infrastructure status values shared by services and the TUI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ServiceName(StrEnum):
    """Infrastructure services initialized by Raven."""

    MONGODB = "mongodb"
    QDRANT = "qdrant"
    NEO4J = "neo4j"
    AI = "ai"


class ConnectionState(StrEnum):
    """User-facing state of an infrastructure connection."""

    CHECKING = "checking"
    CONNECTED = "connected"
    AUTHENTICATION_REQUIRED = "authentication-required"
    CONFIGURATION_REQUIRED = "configuration-required"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    """Safe connection result that never contains secrets or raw driver errors."""

    service: ServiceName
    state: ConnectionState
    detail: str

    @classmethod
    def checking(cls, service: ServiceName) -> ServiceStatus:
        return cls(service, ConnectionState.CHECKING, "Checking connection")

    @classmethod
    def connected(cls, service: ServiceName) -> ServiceStatus:
        return cls(service, ConnectionState.CONNECTED, "Connected and ready")

    @classmethod
    def unavailable(cls, service: ServiceName) -> ServiceStatus:
        return cls(
            service,
            ConnectionState.UNAVAILABLE,
            "Unavailable; check endpoint, credentials, and service",
        )

    @classmethod
    def authentication_required(cls, service: ServiceName) -> ServiceStatus:
        return cls(
            service,
            ConnectionState.AUTHENTICATION_REQUIRED,
            "Service is running; configure valid credentials",
        )

    @classmethod
    def configuration_required(cls, service: ServiceName) -> ServiceStatus:
        return cls(
            service,
            ConnectionState.CONFIGURATION_REQUIRED,
            "Select an available model to configure the AI node",
        )
