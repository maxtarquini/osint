"""Neo4j projections partitioned by investigation AND immutable variant ID."""

import json
from dataclasses import asdict

from raven.models.retrieval import GraphRetrievalSelection

VARIANT_SCHEMA = (
    "CREATE CONSTRAINT raven_variant_key IF NOT EXISTS FOR (v:RavenVariant) "
    "REQUIRE (v.investigation_id, v.run_id) IS UNIQUE",
    "CREATE CONSTRAINT raven_variant_entity_key IF NOT EXISTS FOR (e:RavenVariantEntity) "
    "REQUIRE (e.investigation_id, e.run_id, e.id) IS UNIQUE",
    "CREATE CONSTRAINT raven_variant_claim_key IF NOT EXISTS FOR (c:RavenVariantClaim) "
    "REQUIRE (c.investigation_id, c.run_id, c.id) IS UNIQUE",
)


def write_variant(tx, graph):
    params = {"investigation_id": graph.investigation_id, "run_id": graph.run_id}
    tx.run(
        "MERGE (v:RavenVariant {investigation_id:$investigation_id, run_id:$run_id}) "
        "ON CREATE SET v.name=$name, v.manifest=$manifest, "
        "v.created_at=datetime(), v.events=$events",
        **params,
        name=graph.variant_name,
        manifest=json.dumps(asdict(graph.manifest)),
        events=[json.dumps(asdict(event), default=str) for event in graph.events],
    ).consume()
    tx.run(
        "UNWIND $items AS item "
        "MERGE (e:RavenVariantEntity "
        "{investigation_id:$investigation_id, run_id:$run_id, id:item.id}) "
        ""
        "ON CREATE SET e.name=item.name, e.aliases=item.aliases, e.payload=item.payload",
        **params,
        items=[
            {
                "id": e.entity_id,
                "name": e.canonical_name,
                "aliases": list(e.aliases),
                "payload": json.dumps(asdict(e), default=str),
            }
            for e in graph.entities
        ],
    ).consume()
    tx.run(
        "UNWIND $items AS item "
        "MERGE (c:RavenVariantClaim "
        "{investigation_id:$investigation_id, run_id:$run_id, id:item.id}) "
        ""
        "ON CREATE SET c.payload=item.payload, c.subject_id=item.subject_id, "
        "c.object_id=item.object_id, c.page_keys=item.page_keys, c.evidence_ids=item.evidence_ids",
        **params,
        items=[
            {
                "id": c.claim_id,
                "payload": json.dumps(asdict(c), default=str),
                "subject_id": c.subject_entity_id,
                "object_id": c.object_entity_id,
                "page_keys": [
                    f"{s.evidence_id}:{s.page_number}" for s in c.support if s.verified_original
                ],
                "evidence_ids": list({s.evidence_id for s in c.support if s.verified_original}),
            }
            for c in graph.claims
        ],
    ).consume()
    tx.run(
        "MATCH (c:RavenVariantClaim {investigation_id:$investigation_id, run_id:$run_id}) "
        "MATCH (e:RavenVariantEntity {investigation_id:$investigation_id, run_id:$run_id}) "
        "WHERE e.id=c.subject_id MERGE (c)-[:HAS_SUBJECT]->(e)",
        **params,
    ).consume()
    tx.run(
        "MATCH (c:RavenVariantClaim {investigation_id:$investigation_id, run_id:$run_id}) "
        "MATCH (e:RavenVariantEntity {investigation_id:$investigation_id, run_id:$run_id}) "
        "WHERE e.id=c.object_id MERGE (c)-[:HAS_OBJECT]->(e)",
        **params,
    ).consume()
    tx.run(
        "UNWIND $items AS item "
        "MATCH (a:RavenVariantEntity "
        "{investigation_id:$investigation_id, run_id:$run_id, id:item.source_entity_id}) "
        "MATCH (b:RavenVariantEntity "
        "{investigation_id:$investigation_id, run_id:$run_id, id:item.target_entity_id}) "
        "MERGE (a)-[r:VARIANT_RELATION {id:item.relationship_id}]->(b) "
        "ON CREATE SET r.payload=item.payload",
        **params,
        items=[
            {
                "source_entity_id": r.source_entity_id,
                "target_entity_id": r.target_entity_id,
                "relationship_id": r.relationship_id,
                "payload": json.dumps(asdict(r), default=str),
            }
            for r in graph.relationships
        ],
    ).consume()
    tx.run(
        "UNWIND $items AS item "
        "MATCH (a:RavenVariantClaim "
        "{investigation_id:$investigation_id, run_id:$run_id, id:item.source_claim_id}) "
        "MATCH (b:RavenVariantClaim "
        "{investigation_id:$investigation_id, run_id:$run_id, id:item.target_claim_id}) "
        "MERGE (a)-[r:VARIANT_COMPARISON {id:item.link_id}]->(b) "
        "ON CREATE SET r.kind=item.kind, r.payload=item.payload",
        **params,
        items=[{**asdict(link), "payload": json.dumps(asdict(link))} for link in graph.claim_links],
    ).consume()


def read_variant(tx, investigation_id, run_id, terms, source_pages, limit):
    params = {"investigation_id": investigation_id, "run_id": run_id, "limit": limit + 1}
    head = tx.run(
        "MATCH (v:RavenVariant {investigation_id:$investigation_id, run_id:$run_id}) "
        "RETURN v.run_id AS run_id",
        investigation_id=investigation_id,
        run_id=run_id,
    ).data()
    if not head:
        return None
    entities = tx.run(
        "MATCH (e:RavenVariantEntity {investigation_id:$investigation_id, run_id:$run_id}) "
        "WHERE any(term IN $terms WHERE toLower(e.name) CONTAINS term OR "
        "any(alias IN e.aliases WHERE toLower(alias) CONTAINS term)) "
        "RETURN e.id AS id ORDER BY e.id LIMIT $limit",
        **params,
        terms=list(terms),
    ).data()
    ids = [e["id"] for e in entities[:limit]]
    claims = tx.run(
        "MATCH (c:RavenVariantClaim {investigation_id:$investigation_id, run_id:$run_id}) "
        "WHERE c.subject_id IN $entities OR c.object_id IN $entities OR "
        "any(key IN $pages WHERE key IN c.page_keys) OR "
        "any(doc IN $documents WHERE doc IN c.evidence_ids) "
        "RETURN c.id AS id ORDER BY c.id LIMIT $limit",
        **params,
        entities=ids,
        pages=[f"{d}:{p}" for d, p in source_pages if p is not None],
        documents=[d for d, p in source_pages if p is None],
    ).data()
    comparisons = tx.run(
        "MATCH (a:RavenVariantClaim {investigation_id:$investigation_id, run_id:$run_id})"
        "-[r:VARIANT_COMPARISON]->(b:RavenVariantClaim "
        "{investigation_id:$investigation_id, run_id:$run_id}) "
        "WHERE a.id IN $claims OR b.id IN $claims "
        "RETURN r.id AS id, a.id AS source, b.id AS target ORDER BY r.id LIMIT $limit",
        **params,
        claims=[c["id"] for c in claims[:limit]],
    ).data()
    claim_ids = {c["id"] for c in claims[:limit]}
    for link in comparisons[:limit]:
        claim_ids.update((link["source"], link["target"]))
    return GraphRetrievalSelection(
        investigation_id,
        run_id,
        tuple(ids),
        tuple(sorted(claim_ids)),
        (),
        tuple(c["id"] for c in comparisons[:limit]),
        truncated=any(len(rows) > limit for rows in (entities, claims, comparisons)),
    )
