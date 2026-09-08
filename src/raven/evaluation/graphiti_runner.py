"""Optional Graphiti retrieval experiment over manually supplied synthetic claims.

Run this file in an isolated environment with graphiti-core[kuzu]==0.30.1 and
httpx==0.28.1. It does not extract claims, call an LLM, or connect to Raven databases.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import statistics
import tempfile
import time
from datetime import UTC, datetime
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Any
from unittest.mock import patch

from raven.evaluation.embeddings import DIMENSIONS, SEED, deterministic_embedding


async def evaluate_graphiti(fixture: dict[str, Any], *, top_k: int = 6) -> dict[str, Any]:
    """Exercise the real Graphiti RRF search with a temporary Kuzu database.

    Document visibility is an application constraint: all documents are inserted,
    including excluded controls, and the search receives both the case namespace
    and an allowlist of claims from currently active documents.
    """
    if fixture.get("synthetic") is not True:
        raise ValueError("This runner accepts explicitly synthetic fixtures only")
    if not 1 <= top_k <= 80:
        raise ValueError("top_k must be between 1 and 80")
    os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"
    os.environ["EMBEDDING_DIM"] = str(DIMENSIONS)

    # Optional imports stay outside normal application startup and test discovery.
    import kuzu
    from graphiti_core import Graphiti
    from graphiti_core.cross_encoder.client import CrossEncoderClient
    from graphiti_core.driver.kuzu_driver import KuzuDriver
    from graphiti_core.edges import EntityEdge
    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.nodes import EntityNode
    from graphiti_core.search.search_config_recipes import EDGE_HYBRID_SEARCH_RRF
    from graphiti_core.search.search_filters import SearchFilters

    class ForbiddenLLM(LLMClient):
        async def _generate_response(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError("An LLM call is forbidden in this retrieval-only experiment")

    class ForbiddenReranker(CrossEncoderClient):
        async def rank(self, *args: Any, **kwargs: Any) -> list[tuple[str, float]]:
            raise AssertionError("A model reranker is forbidden in this RRF experiment")

    class FixtureEmbedder(EmbedderClient):
        async def create(self, input_data: Any) -> list[float]:
            text = input_data if isinstance(input_data, str) else " ".join(input_data)
            return list(deterministic_embedding(text))

    documents = {document["id"]: document for document in fixture["documents"]}
    entities = {entity["id"]: entity for entity in fixture["entities"]}
    active_ids = [
        claim["id"]
        for claim in fixture["claims"]
        if documents[claim["doc"]]["active"]
        and documents[claim["doc"]]["case"] == fixture["case_id"]
    ]
    if not active_ids:
        raise ValueError("The fixture has no active in-case claims")
    timestamp = datetime(2026, 9, 8, tzinfo=UTC)
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="raven-graphiti-retrieval-") as temporary:
        # Kuzu's default allocation scales with host RAM. Bound this test backend
        # while preserving the real driver, persistence, and retrieval operations.
        bounded_database = partial(
            kuzu.Database, buffer_pool_size=64 * 1024 * 1024, max_num_threads=2
        )
        with patch.object(kuzu, "Database", bounded_database):
            driver = KuzuDriver(str(Path(temporary) / "graph"))
        graphiti = Graphiti(
            graph_driver=driver,
            llm_client=ForbiddenLLM(None),
            embedder=FixtureEmbedder(),
            cross_encoder=ForbiddenReranker(),
            max_coroutines=1,
        )
        try:
            # INSTALL downloads only Kuzu's official FTS extension when absent.
            await driver.execute_query("INSTALL FTS")
            await driver.execute_query("LOAD EXTENSION FTS")
            cases = sorted({document["case"] for document in documents.values()})
            for case_id in cases:
                for entity in entities.values():
                    await EntityNode(
                        uuid=f"{case_id}:{entity['id']}",
                        name=entity["name"],
                        group_id=case_id,
                        labels=["Entity", entity["type"]],
                        created_at=timestamp,
                        summary=" ".join(entity.get("aliases", [])),
                        name_embedding=list(deterministic_embedding(entity["name"])),
                        attributes={
                            "raven_entity_id": entity["id"],
                            "aliases": entity.get("aliases", []),
                            "identifiers": entity.get("identifiers", {}),
                        },
                    ).save(driver)
            for claim in fixture["claims"]:
                case_id = documents[claim["doc"]]["case"]
                await EntityEdge(
                    uuid=claim["id"],
                    source_node_uuid=f"{case_id}:{claim['subject']}",
                    target_node_uuid=f"{case_id}:{claim['object']}",
                    name=claim["predicate"],
                    fact=claim["quote"],
                    fact_embedding=list(deterministic_embedding(claim["quote"])),
                    group_id=case_id,
                    created_at=timestamp,
                    valid_at=_date(claim.get("valid_from")),
                    invalid_at=_date(claim.get("valid_until")),
                    reference_time=_date(claim.get("asserted_at")),
                    attributes=dict(claim),
                ).save(driver)

            # Graphiti 0.30.1's KuzuDriver.build_indices_and_constraints is a no-op.
            # Its graph operations implement the actual backend FTS index creation.
            await driver.graph_ops.build_indices_and_constraints(driver)
            seed_ms = (time.perf_counter() - started) * 1000
            config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
            config.limit = top_k
            for query in fixture["queries"]:
                measurements = []
                edges = []
                for _ in range(3):
                    query_started = time.perf_counter()
                    found = await asyncio.wait_for(
                        graphiti.search_(
                            query["question"],
                            config=config,
                            group_ids=[fixture["case_id"]],
                            search_filter=SearchFilters(edge_uuids=active_ids),
                        ),
                        timeout=15,
                    )
                    measurements.append((time.perf_counter() - query_started) * 1000)
                    edges = found.edges
                claims = [edge.attributes for edge in edges]
                results.append(
                    {
                        "id": query["id"],
                        "claim_ids": [edge.uuid for edge in edges],
                        "entity_ids": sorted(
                            {claim[key] for claim in claims for key in ("subject", "object")}
                        ),
                        "document_pages": [
                            {"document_id": claim["doc"], "page_number": claim["page"]}
                            for claim in claims
                        ],
                        "retrieved_claims": claims,
                        "latency_ms": statistics.median(measurements),
                        "latency_samples_ms": measurements,
                        "errors": [],
                    }
                )
        finally:
            await graphiti.close()
            # The Kuzu driver close is a no-op, so release its local resources here.
            driver.client.executor.shutdown(wait=True)
            driver.db.close()
    return {
        "status": "executed",
        "engine": "graphiti-core",
        "version": version("graphiti-core"),
        "backend": f"kuzu {version('kuzu')}",
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {
                name: version(name) for name in ("httpx", "neo4j", "numpy", "openai", "pydantic")
            },
        },
        "embedding": {"kind": "deterministic lexical hash", "dimensions": DIMENSIONS, "seed": SEED},
        "top_k": top_k,
        "seed_ms": seed_ms,
        "synthetic": True,
        "llm_calls": 0,
        "scope_filter": "case group_ids plus active-document claim UUID allowlist",
        "recipe": "EDGE_HYBRID_SEARCH_RRF: BM25 + cosine + reciprocal rank fusion",
        "limitations": [
            "Deprecated Kuzu backend; results are not a Neo4j performance benchmark.",
            "Claims, polarity, identities and quotations are manually supplied, not extracted.",
            "No episode ingestion, automatic invalidation, or LLM summaries were tested.",
            "Document visibility is application-owned; group_ids alone do not exclude deletions.",
            "Three sequential retrieval samples per query; latency is not a production SLA.",
        ],
        "queries": results,
    }


def _date(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).replace(tzinfo=UTC) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=6)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    result = asyncio.run(evaluate_graphiti(fixture, top_k=args.top_k))
    result["fixture_sha256"] = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
