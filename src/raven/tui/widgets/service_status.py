"""Accessible connection-state indicator for infrastructure services."""

from __future__ import annotations

from textual.widgets import Static

from raven.models import ConnectionState, ServiceName, ServiceStatus

SERVICE_LABELS = {
    ServiceName.MONGODB: "MongoDB",
    ServiceName.QDRANT: "Qdrant",
    ServiceName.NEO4J: "Neo4j",
    ServiceName.AI: "AI Node",
}

STATE_LABELS = {
    ConnectionState.CHECKING: "Checking",
    ConnectionState.CONNECTED: "Connected",
    ConnectionState.AUTHENTICATION_REQUIRED: "Auth required",
    ConnectionState.CONFIGURATION_REQUIRED: "Configure node",
    ConnectionState.UNAVAILABLE: "Unavailable",
}


class ServiceStatusIndicator(Static):
    """LED-like marker paired with text so color is never the only signal."""

    def __init__(self, service: ServiceName) -> None:
        self.service = service
        self.status = ServiceStatus.checking(service)
        super().__init__(id=f"status-{service.value}", classes="service-status checking")

    def on_mount(self) -> None:
        self._render_status()

    def set_status(self, status: ServiceStatus) -> None:
        if status.service != self.service:
            return
        self.status = status
        self._render_status()

    def _render_status(self) -> None:
        self.remove_class(
            "checking",
            "connected",
            "authentication-required",
            "configuration-required",
            "unavailable",
        )
        self.add_class(self.status.state.value)
        label = SERVICE_LABELS[self.service]
        state = STATE_LABELS[self.status.state]
        self.update(f"● {label}: {state}")
        self.tooltip = self.status.detail
