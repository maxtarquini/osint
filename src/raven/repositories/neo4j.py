"""Neo4j connection and idempotent Raven graph schema bootstrap."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError

from raven.config import Neo4jSettings
from raven.exceptions import GraphPersistenceError, InfrastructureAuthenticationError
from raven.models import InvestigationGraph

NEO4J_SCHEMA_VERSION = 1

SCHEMA_QUERIES = (
    "CREATE CONSTRAINT raven_investigation_id IF NOT EXISTS "
    "FOR (node:Investigation) REQUIRE node.id IS UNIQUE",
    "CREATE CONSTRAINT raven_entity_id IF NOT EXISTS FOR (node:Entity) REQUIRE node.id IS UNIQUE",
    "CREATE CONSTRAINT raven_source_id IF NOT EXISTS FOR (node:Source) REQUIRE node.id IS UNIQUE",
    "CREATE CONSTRAINT raven_metadata_key IF NOT EXISTS "
    "FOR (node:RavenMetadata) REQUIRE node.key IS UNIQUE",
    "CREATE INDEX raven_entity_name IF NOT EXISTS FOR (node:Entity) ON (node.name)",
    "CREATE INDEX raven_entity_type IF NOT EXISTS FOR (node:Entity) ON (node.type)",
)


class Neo4jRepository:
    """Own the Neo4j driver and prepare constraints required by Raven."""

    def __init__(self, driver_factory: Callable[..., Any] = GraphDatabase.driver) -> None:
        self._driver_factory = driver_factory
        self._driver: Any | None = None
        self._database: str | None = None

    def initialize(self, settings: Neo4jSettings) -> None:
        auth = (settings.username, settings.password) if settings.password is not None else None
        candidate = self._driver_factory(
            settings.uri,
            auth=auth,
            connection_timeout=2.5,
        )
        try:
            candidate.verify_connectivity()
            for query in SCHEMA_QUERIES:
                candidate.execute_query(query, database_=settings.database)
            candidate.execute_query(
                "MERGE (metadata:RavenMetadata {key: $key}) "
                "SET metadata.version = $version, metadata.updated_at = datetime()",
                key="schema",
                version=NEO4J_SCHEMA_VERSION,
                database_=settings.database,
            )
        except AuthError as error:
            candidate.close()
            raise InfrastructureAuthenticationError("Neo4j authentication failed") from error
        except Exception:
            candidate.close()
            raise
        previous, self._driver = self._driver, candidate
        self._database = settings.database
        if previous is not None:
            previous.close()

    def save_graph_snapshot(self, graph: InvestigationGraph) -> None:
        """Upsert the latest proposed graph while keeping Evidence provenance on every item."""
        if self._driver is None or self._database is None:
            raise GraphPersistenceError("Neo4j is not connected")
        entities = [
            {
                "id": entity.entity_id,
                "type": entity.entity_type,
                "subtype": entity.subtype,
                "name": entity.canonical_name,
                "aliases": list(entity.aliases),
                "identifiers": [
                    f"{scheme}={value}" for scheme, value in entity.external_identifiers
                ],
                "evidence_ids": list(entity.evidence_ids),
                "rationale": entity.rationale,
                "confidence": entity.confidence,
                "status": entity.status.value,
            }
            for entity in graph.entities
        ]
        relationships = [
            {
                "id": relationship.relationship_id,
                "source_id": relationship.source_entity_id,
                "target_id": relationship.target_entity_id,
                "type": relationship.relationship_type,
                "evidence_ids": list(relationship.evidence_ids),
                "rationale": relationship.rationale,
                "confidence": relationship.confidence,
                "status": relationship.status.value,
            }
            for relationship in graph.relationships
        ]
        try:
            self._driver.execute_query(
                "MERGE (i:Investigation {id: $investigation_id}) "
                "SET i.latest_run_id = $run_id, i.graph_updated_at = datetime()",
                investigation_id=graph.investigation_id,
                run_id=graph.run_id,
                database_=self._database,
            )
            self._driver.execute_query(
                "MATCH (e:Entity {investigation_id: $investigation_id}) SET e.active = false",
                investigation_id=graph.investigation_id,
                database_=self._database,
            )
            self._driver.execute_query(
                "UNWIND $entities AS item "
                "MERGE (e:Entity {id: item.id}) "
                "SET e.investigation_id = $investigation_id, e.run_id = $run_id, "
                "e.type = item.type, e.subtype = item.subtype, e.name = item.name, "
                "e.aliases = item.aliases, e.identifiers = item.identifiers, "
                "e.evidence_ids = item.evidence_ids, e.rationale = item.rationale, "
                "e.confidence = item.confidence, e.status = item.status, e.active = true "
                "WITH e MATCH (i:Investigation {id: $investigation_id}) "
                "MERGE (i)-[:CONTAINS]->(e)",
                entities=entities,
                investigation_id=graph.investigation_id,
                run_id=graph.run_id,
                database_=self._database,
            )
            self._driver.execute_query(
                "MATCH (:Entity {investigation_id: $investigation_id})"
                "-[r:EVIDENCE_RELATION]->(:Entity) SET r.active = false",
                investigation_id=graph.investigation_id,
                database_=self._database,
            )
            self._driver.execute_query(
                "UNWIND $relationships AS item "
                "MATCH (source:Entity {id: item.source_id}) "
                "MATCH (target:Entity {id: item.target_id}) "
                "MERGE (source)-[r:EVIDENCE_RELATION {id: item.id}]->(target) "
                "SET r.investigation_id = $investigation_id, r.run_id = $run_id, "
                "r.type = item.type, r.evidence_ids = item.evidence_ids, "
                "r.rationale = item.rationale, r.confidence = item.confidence, "
                "r.status = item.status, r.active = true",
                relationships=relationships,
                investigation_id=graph.investigation_id,
                run_id=graph.run_id,
                database_=self._database,
            )
        except Exception as error:
            raise GraphPersistenceError("Unable to synchronize the graph with Neo4j") from error

    def delete_investigation(self, investigation_id: str) -> None:
        """Delete an investigation subgraph without touching other case partitions."""
        if self._driver is None or self._database is None:
            raise GraphPersistenceError("Neo4j is not connected")
        try:
            self._driver.execute_query(
                "MATCH (e:Entity {investigation_id: $investigation_id}) DETACH DELETE e",
                investigation_id=investigation_id,
                database_=self._database,
            )
            self._driver.execute_query(
                "MATCH (i:Investigation {id: $investigation_id}) DETACH DELETE i",
                investigation_id=investigation_id,
                database_=self._database,
            )
        except Exception as error:
            raise GraphPersistenceError("Unable to delete the Neo4j investigation graph") from error

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            self._database = None
