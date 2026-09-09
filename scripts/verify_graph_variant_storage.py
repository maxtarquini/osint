"""Verify MongoDB/Neo4j variant isolation using disposable synthetic case IDs."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pymongo import MongoClient

from raven.config.store import ConfigurationStore
from raven.graph.claims import project_claims
from raven.graph.events import event_records
from raven.models.graph import (
    ClaimLink,
    EvidenceSpan,
    GraphClaim,
    GraphEntity,
    GraphManifest,
    InvestigationGraph,
    LiteralValue,
    SourceAttribution,
)
from raven.repositories.mongodb import MongoRepository
from raven.repositories.neo4j import Neo4jRepository


def main():
    settings = ConfigurationStore().load().with_environment()
    case_id = "raven-variant-verification-" + str(uuid4())
    foreign_id = case_id + "-foreign"
    database_name = "raven_variant_check_" + uuid4().hex
    store = Neo4jRepository()
    checks = []
    with MongoClient(settings.mongodb.uri, serverSelectionTimeoutMS=3000) as client:
        repo = MongoRepository()
        repo._database = client[database_name]
        repo._database.graph_checkpoints.create_index(
            [("investigation_id", 1), ("checkpoint_id", 1)], unique=True
        )
        try:
            store.initialize(settings.neo4j)
            span = EvidenceSpan("doc", "Ada transferred 57 GBP to Elm.", 1, True, "p1u1", 0, 30)
            entities = tuple(
                GraphEntity(
                    key,
                    "ORGANIZATION",
                    key,
                    evidence_ids=("doc",),
                    support=(span,),
                    semantic_support="supported",
                )
                for key in ("Ada", "Elm")
            )
            claim = GraphClaim(
                "claim",
                "Ada",
                "Elm",
                "TRANSFER",
                support=(span,),
                qualifiers=(("amount", "57"), ("currency", "GBP")),
                schema_version=2,
                semantic_support="supported",
                source=SourceAttribution("H1"),
            )
            literal = replace(
                claim,
                claim_id="date",
                predicate="OCCURRED_ON",
                object_entity_id="",
                claim_kind="value",
                literal=LiteralValue("2025-04-02", "date"),
            )
            denial = replace(
                claim, claim_id="denial", polarity="denied", source=SourceAttribution("H3")
            )
            cessation = replace(
                literal,
                claim_id="cessation",
                predicate="CONTRACT_ENDED",
                claim_kind="ceases",
                literal=None,
                valid_from="2025-04-08",
                support=(EvidenceSpan("doc", "Contract ceased on 2025-04-08.", 1, True),),
            )
            claims = (claim, denial, literal, cessation)
            graph = InvestigationGraph(
                case_id,
                "A",
                entities,
                project_claims(claims),
                datetime.now(UTC),
                claims,
                (ClaimLink("conflict", "claim", "denial", "contradicts", "Synthetic fixture"),),
                variant_name="Synthetic A",
                manifest=GraphManifest(
                    documents=(("doc", "hash"),),
                    dictionary_snapshot='{"domain_code":"STORAGE_CHECK","entity_types":[]}',
                ),
                events=event_records(claims, entities),
            )
            second = replace(
                graph,
                run_id="B",
                variant_name="Synthetic B",
                claims=tuple(replace(c, source=SourceAttribution("B-source")) for c in claims),
            )
            foreign = replace(graph, investigation_id=foreign_id)
            for item in (graph, second, foreign):
                repo.save_graph_snapshot(item)
                store.save_graph_snapshot(item)
            assert repo.active_graph_snapshot(case_id) is None
            checks.append("generation_does_not_activate")
            repo.activate_graph_variant(case_id, "A")
            repo.save_graph_snapshot(second)
            store.save_graph_snapshot(second)
            assert repo.active_graph_snapshot(case_id).run_id == "A"
            checks.append("new_variant_preserves_active")
            opened = repo.graph_snapshot(case_id, "B")
            assert opened.claims[0].source.source_id == "B-source"
            assert opened.events == graph.events and opened.manifest == graph.manifest
            assert repo.graph_snapshot(foreign_id, "B") is None
            checks.append("bson_v2_events_and_manifest_roundtrip")
            checks.append("foreign_variant_open_rejected")
            repo.activate_graph_variant(case_id, "B")
            assert repo.active_graph_snapshot(case_id).run_id == "B"
            checks.append("explicit_activation_persists")
            for run_id in ("A", "B"):
                selected = store.retrieve_context(
                    case_id, run_id, terms=("ada",), source_pages=(("doc", 1),)
                )
                assert selected.run_id == run_id
                assert set(selected.claim_ids) == {"claim", "denial", "date", "cessation"}
                assert selected.comparison_ids == ("conflict",)
            checks.append("real_cypher_retrieves_exact_variant_denials_and_literals")
            checks.append("unary_cessation_is_persisted_and_retrievable")
            records = store._driver.execute_query(
                "MATCH (c:RavenVariantClaim {investigation_id:$case}) "
                "RETURN c.run_id AS run, count(c) AS total ORDER BY run",
                case=case_id,
                database_=settings.neo4j.database,
            ).records
            assert [(r["run"], r["total"]) for r in records] == [("A", 4), ("B", 4)]
            checks.append("identical_ids_are_isolated_by_variant")
            repo.clear_graph_data(case_id)
            assert repo.graph_snapshot(case_id, "A") and repo.graph_snapshot(case_id, "B")
            checks.append("profile_change_preserves_immutable_variants")
        finally:
            store.delete_investigation(case_id)
            store.delete_investigation(foreign_id)
            store.close()
            client.drop_database(database_name)
    report = {
        "verified_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "disposable_data_removed": True,
        "models_called": False,
    }
    Path("docs/research/graph-variant-storage-verification-2026-09-08.json").write_text(
        json.dumps(report, indent=2)
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
