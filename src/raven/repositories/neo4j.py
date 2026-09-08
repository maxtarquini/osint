"""Neo4j connection and idempotent Raven graph schema bootstrap."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from neo4j import GraphDatabase, unit_of_work
from neo4j.exceptions import AuthError

from raven.config import Neo4jSettings
from raven.exceptions import (
    GraphPersistenceError,
    InfrastructureAuthenticationError,
    InvestigationChatCancelledError,
)
from raven.models import InvestigationGraph
from raven.models.retrieval import GraphRetrievalSelection

NEO4J_SCHEMA_VERSION = 3

SCHEMA_QUERIES = (
    "CREATE CONSTRAINT raven_investigation_id IF NOT EXISTS "
    "FOR (node:Investigation) REQUIRE node.id IS UNIQUE",
    "CREATE CONSTRAINT raven_entity_id IF NOT EXISTS FOR (node:Entity) REQUIRE node.id IS UNIQUE",
    "CREATE CONSTRAINT raven_source_id IF NOT EXISTS FOR (node:Source) REQUIRE node.id IS UNIQUE",
    "CREATE CONSTRAINT raven_metadata_key IF NOT EXISTS "
    "FOR (node:RavenMetadata) REQUIRE node.key IS UNIQUE",
    "CREATE INDEX raven_entity_name IF NOT EXISTS FOR (node:Entity) ON (node.name)",
    "CREATE INDEX raven_entity_type IF NOT EXISTS FOR (node:Entity) ON (node.type)",
    "CREATE CONSTRAINT raven_claim_case_id IF NOT EXISTS "
    "FOR (node:Claim) REQUIRE (node.investigation_id, node.id) IS UNIQUE",
    "CREATE INDEX raven_claim_active_run IF NOT EXISTS "
    "FOR (node:Claim) ON (node.investigation_id, node.run_id, node.active)",
    "CREATE INDEX raven_entity_active_run IF NOT EXISTS "
    "FOR (node:Entity) ON (node.investigation_id, node.run_id, node.active)",
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
        self._validate_snapshot(graph)
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
                "support": [
                    json.dumps(asdict(span), ensure_ascii=False) for span in entity.support
                ],
                "resolution_notes": list(entity.resolution_notes),
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
                "support": [
                    json.dumps(asdict(span), ensure_ascii=False) for span in relationship.support
                ],
                "resolution_notes": list(relationship.resolution_notes),
                "rationale": relationship.rationale,
                "confidence": relationship.confidence,
                "status": relationship.status.value,
                "claim_ids": list(relationship.claim_ids),
            }
            for relationship in graph.relationships
        ]
        try:
            with self._driver.session(database=self._database) as session:
                session.execute_write(self._write_snapshot, graph, entities, relationships)
        except Exception as error:
            raise GraphPersistenceError("Unable to synchronize the graph with Neo4j") from error

    @staticmethod
    def _validate_snapshot(graph: InvestigationGraph) -> None:
        """Reject malformed replacements before retiring the previous active graph."""
        entity_ids = {entity.entity_id for entity in graph.entities}
        relationship_ids = {relationship.relationship_id for relationship in graph.relationships}
        if len(entity_ids) != len(graph.entities) or len(relationship_ids) != len(
            graph.relationships
        ):
            raise GraphPersistenceError("Graph snapshot contains duplicate item identifiers")
        if any(
            relationship.source_entity_id not in entity_ids
            or relationship.target_entity_id not in entity_ids
            for relationship in graph.relationships
        ):
            raise GraphPersistenceError("Graph snapshot contains an unknown relationship endpoint")
        claims = {claim.claim_id: claim for claim in graph.claims}
        if len(claims) != len(graph.claims) or len(
            {link.link_id for link in graph.claim_links}
        ) != len(graph.claim_links):
            raise GraphPersistenceError("Graph snapshot contains duplicate claim identifiers")
        if any(
            claim.subject_entity_id not in entity_ids or claim.object_entity_id not in entity_ids
            for claim in graph.claims
        ):
            raise GraphPersistenceError("Graph snapshot contains an unknown claim endpoint")
        if any(
            link.source_claim_id not in claims or link.target_claim_id not in claims
            for link in graph.claim_links
        ):
            raise GraphPersistenceError("Graph snapshot comparison references an unknown claim")
        for relationship in graph.relationships:
            for claim_id in relationship.claim_ids:
                claim = claims.get(claim_id)
                if (
                    claim is None
                    or claim.polarity != "affirmed"
                    or claim.subject_entity_id != relationship.source_entity_id
                    or claim.object_entity_id != relationship.target_entity_id
                    or claim.predicate != relationship.relationship_type
                ):
                    raise GraphPersistenceError(
                        "Graph relationship must reference a matching affirmative claim"
                    )

    @staticmethod
    def _write_snapshot(
        tx: Any,
        graph: InvestigationGraph,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> None:
        tx.run(
            "MERGE (i:Investigation {id: $investigation_id}) "
            "SET i.latest_run_id = $run_id, i.graph_updated_at = datetime(), "
            "i.page_coverage = $page_coverage",
            investigation_id=graph.investigation_id,
            run_id=graph.run_id,
            page_coverage=[
                json.dumps(
                    {
                        "evidence_id": page.evidence_id,
                        "page_number": page.page_number,
                        "text_hash": page.text_hash,
                        "signature": page.signature,
                        "state": page.state,
                        "analyzed_at": page.analyzed_at.isoformat(),
                        "catalog_state": page.catalog_state,
                        "catalog_signature": page.catalog_signature,
                        "catalog_uses": page.catalog_uses,
                        "entity_count": len(page.entities),
                        "claim_count": len(page.claims),
                        "model_name": page.model_name,
                        "error": page.error,
                    },
                    ensure_ascii=False,
                )
                for page in graph.pages
            ],
        ).consume()
        tx.run(
            "MATCH (e:Entity {investigation_id: $investigation_id}) SET e.active = false",
            investigation_id=graph.investigation_id,
        ).consume()
        tx.run(
            "UNWIND $entities AS item "
            "MERGE (e:Entity {id: item.id, investigation_id: $investigation_id}) "
            "SET e.investigation_id = $investigation_id, e.run_id = $run_id, "
            "e.type = item.type, e.subtype = item.subtype, e.name = item.name, "
            "e.aliases = item.aliases, e.identifiers = item.identifiers, "
            "e.evidence_ids = item.evidence_ids, e.support = item.support, "
            "e.rationale = item.rationale, e.resolution_notes = item.resolution_notes, "
            "e.confidence = item.confidence, e.status = item.status, e.active = true "
            "WITH e MATCH (i:Investigation {id: $investigation_id}) "
            "MERGE (i)-[:CONTAINS]->(e)",
            entities=entities,
            investigation_id=graph.investigation_id,
            run_id=graph.run_id,
        ).consume()
        tx.run(
            "MATCH (:Entity {investigation_id: $investigation_id})"
            "-[r:EVIDENCE_RELATION {investigation_id: $investigation_id}]->"
            "(:Entity {investigation_id: $investigation_id}) SET r.active = false",
            investigation_id=graph.investigation_id,
        ).consume()
        tx.run(
            "UNWIND $relationships AS item "
            "MATCH (source:Entity {id: item.source_id, "
            "investigation_id: $investigation_id, active: true}) "
            "MATCH (target:Entity {id: item.target_id, "
            "investigation_id: $investigation_id, active: true}) "
            "MERGE (source)-[r:EVIDENCE_RELATION {id: item.id, "
            "investigation_id: $investigation_id}]->(target) "
            "SET r.investigation_id = $investigation_id, r.run_id = $run_id, "
            "r.type = item.type, r.evidence_ids = item.evidence_ids, r.support = item.support, "
            "r.rationale = item.rationale, r.resolution_notes = item.resolution_notes, "
            "r.confidence = item.confidence, "
            "r.status = item.status, r.active = true, r.claim_ids = item.claim_ids",
            relationships=relationships,
            investigation_id=graph.investigation_id,
            run_id=graph.run_id,
        ).consume()
        tx.run(
            "MATCH (c:Claim {investigation_id: $investigation_id}) SET c.active = false",
            investigation_id=graph.investigation_id,
        ).consume()
        tx.run(
            "MATCH (:Claim {investigation_id: $investigation_id})"
            "-[r:HAS_SUBJECT|HAS_OBJECT|CLAIM_COMPARISON]->() "
            "WHERE r.investigation_id = $investigation_id SET r.active = false",
            investigation_id=graph.investigation_id,
        ).consume()
        claims = [
            {
                **asdict(claim),
                "status": claim.status.value,
                "qualifiers": json.dumps(claim.qualifiers, ensure_ascii=False),
                "support": [json.dumps(asdict(span), ensure_ascii=False) for span in claim.support],
                "resolution_notes": list(claim.resolution_notes),
                "evidence_ids": list(
                    dict.fromkeys(
                        span.evidence_id for span in claim.support if span.verified_original
                    )
                ),
                "page_keys": list(
                    dict.fromkeys(
                        f"{span.evidence_id}:{span.page_number}"
                        for span in claim.support
                        if span.verified_original
                        and type(span.page_number) is int
                        and span.page_number > 0
                    )
                ),
            }
            for claim in graph.claims
        ]
        result = tx.run(
            "UNWIND $claims AS item "
            "MATCH (subject:Entity {id: item.subject_entity_id, "
            "investigation_id: $investigation_id, active: true}) "
            "MATCH (object:Entity {id: item.object_entity_id, "
            "investigation_id: $investigation_id, active: true}) "
            "MERGE (c:Claim {id: item.claim_id, investigation_id: $investigation_id}) "
            "SET c.run_id = $run_id, c.predicate = item.predicate, "
            "c.polarity = item.polarity, c.modality = item.modality, "
            "c.valid_from = item.valid_from, c.valid_until = item.valid_until, "
            "c.asserted_at = item.asserted_at, c.attribution = item.attribution, "
            "c.qualifiers = item.qualifiers, c.support = item.support, "
            "c.confidence = item.confidence, c.status = item.status, "
            "c.resolution_notes = item.resolution_notes, c.active = true, "
            "c.evidence_ids = item.evidence_ids, c.page_keys = item.page_keys "
            "MERGE (c)-[s:HAS_SUBJECT {investigation_id: $investigation_id}]->(subject) "
            "SET s.active = true, s.run_id = $run_id "
            "MERGE (c)-[o:HAS_OBJECT {investigation_id: $investigation_id}]->(object) "
            "SET o.active = true, o.run_id = $run_id "
            "RETURN count(c) AS written",
            claims=claims,
            investigation_id=graph.investigation_id,
            run_id=graph.run_id,
        )
        Neo4jRepository._expect_written(result, len(claims))
        result = tx.run(
            "UNWIND $claim_links AS item "
            "MATCH (source:Claim {id: item.source_claim_id, "
            "investigation_id: $investigation_id, active: true}) "
            "MATCH (target:Claim {id: item.target_claim_id, "
            "investigation_id: $investigation_id, active: true}) "
            "MERGE (source)-[r:CLAIM_COMPARISON {id: item.link_id, "
            "investigation_id: $investigation_id}]->(target) "
            "SET r.kind = item.kind, r.rationale = item.rationale, "
            "r.requires_identity_review = item.requires_identity_review, "
            "r.run_id = $run_id, r.active = true "
            "RETURN count(r) AS written",
            claim_links=[asdict(link) for link in graph.claim_links],
            investigation_id=graph.investigation_id,
            run_id=graph.run_id,
        )
        Neo4jRepository._expect_written(result, len(graph.claim_links))

    @staticmethod
    def _expect_written(result: Any, expected: int) -> None:
        """Missing endpoints must roll back instead of silently dropping UNWIND rows."""
        record = result.single(strict=True)
        result.consume()
        if record is None or record["written"] != expected:
            raise GraphPersistenceError("Graph snapshot write did not persist every claim item")

    def retrieve_context(
        self,
        investigation_id: str,
        expected_run_id: str | None,
        *,
        terms: tuple[str, ...],
        source_pages: tuple[tuple[str, int | None], ...],
        limit: int = 40,
        cancelled: Callable[[], bool] | None = None,
    ) -> GraphRetrievalSelection:
        """Select bounded IDs from the matching active run; MongoDB remains authoritative."""
        if self._driver is None or self._database is None:
            raise GraphPersistenceError("Neo4j is not connected")
        self._check_retrieval_cancelled(cancelled)
        limit = max(1, min(int(limit), 200))
        bounded_terms = tuple(
            dict.fromkeys(
                term.strip().casefold()[:80]
                for term in terms
                if isinstance(term, str) and len(term.strip()) >= 2
            )
        )[:24]
        if any(
            not isinstance(document_id, str)
            or not document_id
            or (page is not None and (type(page) is not int or page < 1))
            for document_id, page in source_pages
        ):
            raise ValueError("Graph retrieval requires valid source page references")
        bounded_pages = tuple(dict.fromkeys(source_pages))[:200]
        try:
            with self._driver.session(
                database=self._database, default_access_mode="READ"
            ) as session:
                return session.execute_read(
                    self._read_context,
                    investigation_id,
                    expected_run_id,
                    bounded_terms,
                    bounded_pages,
                    limit,
                    cancelled,
                )
        except InvestigationChatCancelledError:
            raise
        except Exception as error:
            raise GraphPersistenceError(
                "Unable to retrieve the current Neo4j graph context"
            ) from error

    @staticmethod
    @unit_of_work(timeout=8)
    def _read_context(
        tx: Any,
        investigation_id: str,
        expected_run_id: str | None,
        terms: tuple[str, ...],
        source_pages: tuple[tuple[str, int | None], ...],
        limit: int,
        cancelled: Callable[[], bool] | None,
    ) -> GraphRetrievalSelection:
        # Managed transactions reject neo4j.Query objects. unit_of_work sets the
        # timeout for the entire read transaction, not individually for every query.
        base = {"investigation_id": investigation_id, "run_id": expected_run_id, "limit": limit + 1}
        truncated = False

        def read(query: str, **parameters: Any) -> list[dict[str, Any]]:
            nonlocal truncated
            Neo4jRepository._check_retrieval_cancelled(cancelled)
            rows = tx.run(query, **base, **parameters).data()
            Neo4jRepository._check_retrieval_cancelled(cancelled)
            truncated |= len(rows) > limit
            return rows[:limit]

        head_query = (
            "MATCH (i:Investigation {id: $investigation_id}) "
            "RETURN i.latest_run_id AS run_id LIMIT 1"
        )
        head = read(head_query)
        actual_run = head[0].get("run_id") if head else None
        if expected_run_id is None or actual_run != expected_run_id:
            return GraphRetrievalSelection(
                investigation_id, actual_run, state="stale" if head else "missing"
            )
        entity_rows = read(
            "MATCH (e:Entity {investigation_id: $investigation_id, run_id: $run_id, active: true}) "
            "WHERE any(term IN $terms WHERE toLower(e.name) CONTAINS term "
            "OR any(alias IN coalesce(e.aliases, []) WHERE toLower(alias) CONTAINS term)) "
            "RETURN e.id AS entity_id ORDER BY e.id LIMIT $limit",
            terms=list(terms),
        )
        entity_ids = {row["entity_id"] for row in entity_rows}
        claim_rows = read(
            "MATCH (c:Claim {investigation_id: $investigation_id, run_id: $run_id, active: true}) "
            "WHERE any(key IN $page_keys WHERE key IN coalesce(c.page_keys, [])) "
            "OR any(document_id IN $document_ids "
            "WHERE document_id IN coalesce(c.evidence_ids, [])) "
            "OR EXISTS { MATCH (c)-[s:HAS_SUBJECT|HAS_OBJECT {investigation_id: $investigation_id, "
            "run_id: $run_id, active: true}]->(e:Entity {investigation_id: $investigation_id, "
            "run_id: $run_id, active: true}) WHERE e.id IN $entity_ids } "
            "RETURN c.id AS claim_id ORDER BY c.id LIMIT $limit",
            page_keys=[
                f"{document_id}:{page}" for document_id, page in source_pages if page is not None
            ],
            document_ids=[document_id for document_id, page in source_pages if page is None],
            entity_ids=sorted(entity_ids),
        )
        claim_ids = {row["claim_id"] for row in claim_rows}
        relationship_rows = read(
            "MATCH (source:Entity {investigation_id: $investigation_id, "
            "run_id: $run_id, active: true})"
            "-[r:EVIDENCE_RELATION {investigation_id: $investigation_id, "
            "run_id: $run_id, active: true}]->"
            "(target:Entity {investigation_id: $investigation_id, run_id: $run_id, active: true}) "
            "WHERE source.id IN $entity_ids OR target.id IN $entity_ids "
            "OR any(claim_id IN coalesce(r.claim_ids, []) WHERE claim_id IN $claim_ids) "
            "RETURN r.id AS relationship_id, source.id AS source_id, target.id AS target_id, "
            "r.claim_ids AS claim_ids ORDER BY r.id LIMIT $limit",
            entity_ids=sorted(entity_ids),
            claim_ids=sorted(claim_ids),
        )
        for row in relationship_rows:
            entity_ids.update((row["source_id"], row["target_id"]))
            claim_ids.update(row.get("claim_ids") or [])
        truncated |= len(claim_ids) > 200
        comparisons = read(
            "MATCH (source:Claim {investigation_id: $investigation_id, "
            "run_id: $run_id, active: true})"
            "-[r:CLAIM_COMPARISON {investigation_id: $investigation_id, "
            "run_id: $run_id, active: true}]->"
            "(target:Claim {investigation_id: $investigation_id, run_id: $run_id, active: true}) "
            "WHERE source.id IN $claim_ids OR target.id IN $claim_ids "
            "RETURN r.id AS comparison_id, source.id AS source_id, target.id AS target_id "
            "ORDER BY r.id LIMIT $limit",
            claim_ids=sorted(claim_ids)[:200],
        )
        for row in comparisons:
            claim_ids.update((row["source_id"], row["target_id"]))
        truncated |= len(claim_ids) > 200
        claims_with_endpoints = read(
            "MATCH (c:Claim {investigation_id: $investigation_id, run_id: $run_id, active: true})"
            "-[s:HAS_SUBJECT {investigation_id: $investigation_id, "
            "run_id: $run_id, active: true}]->"
            "(subject:Entity {investigation_id: $investigation_id, "
            "run_id: $run_id, active: true}), "
            "(c)-[o:HAS_OBJECT {investigation_id: $investigation_id, "
            "run_id: $run_id, active: true}]->"
            "(object:Entity {investigation_id: $investigation_id, run_id: $run_id, active: true}) "
            "WHERE c.id IN $claim_ids RETURN c.id AS claim_id, subject.id AS subject_id, "
            "object.id AS object_id ORDER BY c.id LIMIT $limit",
            claim_ids=sorted(claim_ids)[:200],
        )
        claim_ids = {row["claim_id"] for row in claims_with_endpoints}
        for row in claims_with_endpoints:
            entity_ids.update((row["subject_id"], row["object_id"]))
        # A concurrent publication can retire the selected run between read statements.
        final_head = read(head_query)
        final_run = final_head[0].get("run_id") if final_head else None
        if final_run != expected_run_id:
            return GraphRetrievalSelection(investigation_id, final_run, state="stale")

        def bounded(values: Any) -> tuple[str, ...]:
            nonlocal truncated
            values = sorted(set(values))
            truncated |= len(values) > limit
            return tuple(values[:limit])

        entities = bounded(entity_ids)
        claims = bounded(claim_ids)
        relationships = bounded(row["relationship_id"] for row in relationship_rows)
        comparison_ids = bounded(row["comparison_id"] for row in comparisons)
        return GraphRetrievalSelection(
            investigation_id,
            expected_run_id,
            entities,
            claims,
            relationships,
            comparison_ids,
            truncated=truncated,
        )

    @staticmethod
    def _check_retrieval_cancelled(cancelled: Callable[[], bool] | None) -> None:
        if cancelled and cancelled():
            raise InvestigationChatCancelledError("Graph retrieval cancelled")

    def delete_investigation(self, investigation_id: str) -> None:
        """Delete an investigation subgraph without touching other case partitions."""
        if self._driver is None or self._database is None:
            raise GraphPersistenceError("Neo4j is not connected")
        try:
            self._driver.execute_query(
                "MATCH (c:Claim {investigation_id: $investigation_id}) DETACH DELETE c",
                investigation_id=investigation_id,
                database_=self._database,
            )
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
