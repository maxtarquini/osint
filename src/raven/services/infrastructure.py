"""Infrastructure orchestration outside the terminal presentation layer."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from typing import Any, Protocol

from raven.ai import SharedAiNode
from raven.config import AiNodeSettings, RavenSettings
from raven.exceptions import (
    InfrastructureAuthenticationError,
    InfrastructureConfigurationError,
)
from raven.models import ConnectionState, ServiceName, ServiceStatus
from raven.repositories import MongoRepository, Neo4jRepository, QdrantRepository

logger = logging.getLogger(__name__)


class InfrastructureAdapter(Protocol):
    def initialize(self, settings: Any) -> None: ...

    def close(self) -> None: ...


class InfrastructureService:
    """Initialize all configured data services and translate failures to safe states."""

    def __init__(
        self,
        settings: RavenSettings,
        adapters: Mapping[ServiceName, InfrastructureAdapter] | None = None,
    ) -> None:
        self._settings = settings.with_environment()
        self._adapters: dict[ServiceName, InfrastructureAdapter] = dict(
            adapters
            or {
                ServiceName.MONGODB: MongoRepository(),
                ServiceName.QDRANT: QdrantRepository(),
                ServiceName.NEO4J: Neo4jRepository(),
                ServiceName.AI: SharedAiNode(),
            }
        )
        self._locks = {service: threading.Lock() for service in ServiceName}

    def configure(self, settings: RavenSettings) -> None:
        self._settings = settings.with_environment()

    def initialize(self, service: ServiceName) -> ServiceStatus:
        adapter = self._adapters[service]
        try:
            with self._locks[service]:
                settings = {
                    ServiceName.MONGODB: self._settings.mongodb,
                    ServiceName.QDRANT: self._settings.qdrant,
                    ServiceName.NEO4J: self._settings.neo4j,
                    ServiceName.AI: self._settings.ai,
                }[service]
                adapter.initialize(settings)
        except InfrastructureAuthenticationError as error:
            logger.warning(
                "Infrastructure authentication failed. service=%s error_type=%s",
                service.value,
                type(error).__name__,
            )
            return ServiceStatus.authentication_required(service)
        except InfrastructureConfigurationError as error:
            logger.warning(
                "Infrastructure configuration incomplete. service=%s error_type=%s",
                service.value,
                type(error).__name__,
            )
            return ServiceStatus.configuration_required(service)
        except Exception as error:
            logger.warning(
                "Infrastructure initialization failed. service=%s error_type=%s",
                service.value,
                type(error).__name__,
            )
            return ServiceStatus.unavailable(service)
        logger.info("Infrastructure initialized. service=%s", service.value)
        return ServiceStatus.connected(service)

    def test_ai_node(self, settings: AiNodeSettings) -> ServiceStatus:
        """Probe draft AI settings without activating or persisting them."""
        try:
            with self._locks[ServiceName.AI]:
                embedding_dimension = self.ai_node.probe(settings)
            expected_dimension = self._settings.qdrant.vector_size
            if embedding_dimension is not None and embedding_dimension != expected_dimension:
                detail = (
                    f"Embedding model returns {embedding_dimension} dimensions; "
                    f"Qdrant expects {expected_dimension}"
                )
                logger.warning(
                    "AI node embedding dimension mismatch. actual=%d expected=%d",
                    embedding_dimension,
                    expected_dimension,
                )
                return ServiceStatus(
                    ServiceName.AI,
                    ConnectionState.CONFIGURATION_REQUIRED,
                    detail,
                )
        except InfrastructureAuthenticationError as error:
            logger.warning("AI node test needs authentication. error_type=%s", type(error).__name__)
            return ServiceStatus.authentication_required(ServiceName.AI)
        except InfrastructureConfigurationError as error:
            logger.warning("AI node test needs configuration. error_type=%s", type(error).__name__)
            return ServiceStatus.configuration_required(ServiceName.AI)
        except Exception as error:
            logger.warning("AI node test failed. error_type=%s", type(error).__name__)
            return ServiceStatus.unavailable(ServiceName.AI)
        detail = (
            f"Inference and embedding ready · {embedding_dimension} dimensions"
            if embedding_dimension is not None
            else "Inference ready · embedding model not configured"
        )
        logger.info("AI node test succeeded. embedding_dimension=%s", embedding_dimension)
        return ServiceStatus(ServiceName.AI, ConnectionState.CONNECTED, detail)

    @property
    def ai_node(self) -> SharedAiNode:
        """Expose the single initialized node to future application agents."""
        adapter = self._adapters[ServiceName.AI]
        if not isinstance(adapter, SharedAiNode):
            raise TypeError("The configured AI adapter is not a SharedAiNode")
        return adapter

    @property
    def mongo_repository(self) -> MongoRepository:
        """Expose the initialized Mongo repository to investigation use cases."""
        adapter = self._adapters[ServiceName.MONGODB]
        if not isinstance(adapter, MongoRepository):
            raise TypeError("The configured MongoDB adapter is not a MongoRepository")
        return adapter

    @property
    def neo4j_repository(self) -> Neo4jRepository:
        """Expose the initialized graph adapter to Evidence-analysis use cases."""
        adapter = self._adapters[ServiceName.NEO4J]
        if not isinstance(adapter, Neo4jRepository):
            raise TypeError("The configured Neo4j adapter is not a Neo4jRepository")
        return adapter

    @property
    def qdrant_repository(self) -> QdrantRepository:
        """Expose the initialized vector adapter to investigation RAG use cases."""
        adapter = self._adapters[ServiceName.QDRANT]
        if not isinstance(adapter, QdrantRepository):
            raise TypeError("The configured Qdrant adapter is not a QdrantRepository")
        return adapter

    def close(self) -> None:
        for service, adapter in self._adapters.items():
            try:
                with self._locks[service]:
                    adapter.close()
            except Exception as error:
                logger.warning(
                    "Infrastructure close failed. service=%s error_type=%s",
                    service.value,
                    type(error).__name__,
                )
