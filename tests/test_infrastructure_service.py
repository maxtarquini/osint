"""Tests for safe infrastructure orchestration states."""

from __future__ import annotations

from typing import Any

from raven.ai import SharedAiNode
from raven.config import AiNodeSettings, RavenSettings
from raven.exceptions import (
    InfrastructureAuthenticationError,
    InfrastructureConfigurationError,
)
from raven.models import ConnectionState, ServiceName
from raven.services import InfrastructureService


class Adapter:
    def __init__(
        self,
        *,
        fails: bool = False,
        authentication_fails: bool = False,
        configuration_fails: bool = False,
    ) -> None:
        self.fails = fails
        self.authentication_fails = authentication_fails
        self.configuration_fails = configuration_fails
        self.settings: Any = None
        self.closed = False

    def initialize(self, settings: Any) -> None:
        self.settings = settings
        if self.authentication_fails:
            raise InfrastructureAuthenticationError("credentials rejected")
        if self.configuration_fails:
            raise InfrastructureConfigurationError("model missing")
        if self.fails:
            raise RuntimeError("driver detail that must not reach the UI")

    def close(self) -> None:
        self.closed = True


class ProbeAiNode(SharedAiNode):
    def __init__(self, failure: Exception | None = None) -> None:
        super().__init__()
        self.failure = failure
        self.probed: AiNodeSettings | None = None

    def probe(self, settings: AiNodeSettings) -> None:
        self.probed = settings
        if self.failure is not None:
            raise self.failure


def test_service_returns_connected_after_successful_bootstrap() -> None:
    adapters = {service: Adapter() for service in ServiceName}
    service = InfrastructureService(RavenSettings(), adapters)

    statuses = [service.initialize(name) for name in ServiceName]

    assert all(status.state is ConnectionState.CONNECTED for status in statuses)
    assert all(status.detail == "Connected and ready" for status in statuses)
    service.close()
    assert all(adapter.closed for adapter in adapters.values())


def test_service_hides_raw_driver_failure_from_user_status() -> None:
    adapters = {service: Adapter() for service in ServiceName}
    adapters[ServiceName.MONGODB] = Adapter(fails=True)
    service = InfrastructureService(RavenSettings(), adapters)

    status = service.initialize(ServiceName.MONGODB)

    assert status.state is ConnectionState.UNAVAILABLE
    assert "driver detail" not in status.detail


def test_service_reports_reachable_service_that_requires_authentication() -> None:
    adapters = {service: Adapter() for service in ServiceName}
    adapters[ServiceName.NEO4J] = Adapter(authentication_fails=True)
    service = InfrastructureService(RavenSettings(), adapters)

    status = service.initialize(ServiceName.NEO4J)

    assert status.state is ConnectionState.AUTHENTICATION_REQUIRED
    assert status.detail == "Service is running; configure valid credentials"


def test_service_reports_ai_node_that_needs_a_model() -> None:
    adapters = {service: Adapter() for service in ServiceName}
    adapters[ServiceName.AI] = Adapter(configuration_fails=True)
    service = InfrastructureService(RavenSettings(), adapters)

    status = service.initialize(ServiceName.AI)

    assert status.state is ConnectionState.CONFIGURATION_REQUIRED
    assert status.detail == "Select an available model to configure the AI node"


def test_ai_node_probe_uses_draft_settings_without_reconfiguring_service() -> None:
    adapters = {service: Adapter() for service in ServiceName}
    node = ProbeAiNode()
    adapters[ServiceName.AI] = node
    service = InfrastructureService(RavenSettings(), adapters)
    draft = AiNodeSettings(model="qwen3")

    status = service.test_ai_node(draft)

    assert status.state is ConnectionState.CONNECTED
    assert node.probed == draft
