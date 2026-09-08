"""Claims and raw page extractions survive storage without becoming confirmed relations."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from bson import BSON
from bson.codec_options import CodecOptions
from test_neo4j_atomic import (
    SnapshotDriver,
    SnapshotSession,
    SnapshotTransaction,
    TransactionResult,
)
from test_neo4j_atomic import (
    repository as neo_repository,
)

from raven.exceptions import GraphPersistenceError
from raven.models.graph import (
    ClaimLink,
    EvidencePreparationMode,
    EvidenceSpan,
    GraphAnalysisRun,
    GraphClaim,
    GraphEntity,
    GraphItemStatus,
    GraphRelationship,
    GraphRunStatus,
    InvestigationGraph,
    PageGraphAnalysis,
)
from raven.repositories.mongodb import MongoRepository


def claim_snapshot():
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    asserted = EvidenceSpan("doc-positive", "Ada è affiliata a Levante.", 2, True)
    denied = EvidenceSpan("doc-negative", "Ada non è affiliata a Levante.", 4, True)
    person = GraphEntity(
        "ada",
        "PERSON",
        "Ada",
        external_identifiers=(("passport", "AA1"), ("passport", "AA2")),
        evidence_ids=("doc-positive", "doc-negative"),
        support=(asserted, denied),
    )
    organization = GraphEntity("levante", "ORGANIZATION", "Levante")
    positive = GraphClaim(
        "assertion",
        "ada",
        "levante",
        "MEMBER_OF",
        modality="alleged",
        valid_from="2026-01-01",
        valid_until="2026-08-01",
        asserted_at="2026-09-01",
        attribution="Source A",
        qualifiers=(("location", "Roma"), ("location", "Milano")),
        support=(asserted,),
        confidence=0.85,
        resolution_notes=("Source assertion, subject to review",),
    )
    negative = replace(
        positive,
        claim_id="denial",
        polarity="negated",
        modality="asserted",
        attribution="Source B",
        support=(denied,),
        status=GraphItemStatus.REJECTED,
    )
    comparison = ClaimLink(
        "comparison",
        positive.claim_id,
        negative.claim_id,
        "contradiction",
        "Same period, opposing source statements",
        True,
    )
    relation = GraphRelationship(
        "membership",
        "ada",
        "levante",
        "MEMBER_OF",
        support=(asserted,),
        claim_ids=(positive.claim_id,),
    )
    # Cached page extraction deliberately has local IDs predating identity resolution.
    raw_entity = replace(person, entity_id="page-local-ada")
    raw_claim = replace(
        positive, claim_id="page-local-claim", subject_entity_id=raw_entity.entity_id
    )
    page = PageGraphAnalysis(
        "doc-positive",
        2,
        "text-hash",
        "extraction-signature",
        "ready",
        now,
        catalog_state="ready",
        catalog_signature="catalog-version",
        catalog_uses=("relationships", "contradictions"),
        entities=(raw_entity, organization),
        claims=(raw_claim,),
        model_name="scripted-model",
    )
    failed_page = replace(
        page,
        evidence_id="doc-negative",
        page_number=4,
        state="failed",
        entities=(),
        claims=(),
        error="Request timed out",
        catalog_state="missing",
    )
    return InvestigationGraph(
        "case-a",
        "new-run",
        (person, organization),
        (relation,),
        now,
        (positive, negative),
        (comparison,),
        (page, failed_page),
    )


def test_mongo_bson_roundtrip_preserves_claims_links_and_raw_page_cache():
    checkpoints = MagicMock()
    repository = MongoRepository()
    repository._database = {"graph_checkpoints": checkpoints, "investigations": MagicMock()}
    graph = claim_snapshot()

    repository.save_graph_snapshot(graph)
    query, payload = checkpoints.replace_one.call_args.args
    assert query == {"investigation_id": graph.investigation_id, "checkpoint_id": graph.run_id}
    persisted = BSON.encode(payload).decode(codec_options=CodecOptions(tz_aware=True))
    checkpoints.find_one.return_value = persisted
    loaded = repository.latest_graph_snapshot(graph.investigation_id)

    assert loaded == graph
    assert isinstance(loaded.pages[0].analyzed_at, datetime)
    assert loaded.claims[1].status is GraphItemStatus.REJECTED
    assert loaded.pages[0].entities[0].entity_id == "page-local-ada"
    assert loaded.pages[0].claims[0].subject_entity_id == "page-local-ada"
    assert loaded.entities[0].external_identifiers == (("passport", "AA1"), ("passport", "AA2"))
    assert loaded.pages[1].state == "failed"
    assert loaded.pages[1].error == "Request timed out"


@pytest.mark.parametrize("status", [GraphRunStatus.FAILED, GraphRunStatus.CANCELLED])
def test_attempt_page_outcomes_persist_safe_diagnostics_without_publishing_graph(status):
    graph = claim_snapshot()
    page = replace(graph.pages[0], state="failed", error="invalid_claim_endpoint")
    run = GraphAnalysisRun(
        "failed-attempt",
        graph.investigation_id,
        status,
        EvidencePreparationMode.FULL_TEXT,
        "original",
        1,
        0,
        1,
        0,
        0,
        "scripted-model",
        graph.generated_at,
        graph.generated_at,
        last_error="1 page requires retry",
        page_outcomes=(page,),
    )
    runs, checkpoints = MagicMock(), MagicMock()
    repository = MongoRepository()
    repository._database = {"graph_analysis_runs": runs, "graph_checkpoints": checkpoints}

    repository.save_graph_run(run)

    payload = runs.replace_one.call_args.args[1]
    stored_page = payload["page_outcomes"][0]
    assert payload["status"] == status.value
    assert stored_page["evidence_id"] == page.evidence_id
    assert stored_page["page_number"] == page.page_number
    assert stored_page["error"] == "invalid_claim_endpoint"
    assert stored_page["signature"] == page.signature
    assert stored_page["analyzed_at"] == page.analyzed_at
    assert stored_page["entities"] == stored_page["claims"] == []
    assert "Ada" not in json.dumps(payload, default=str)
    checkpoints.replace_one.assert_not_called()


@pytest.mark.parametrize("optional", ["absent", None])
def test_mongo_legacy_graph_needs_no_claim_or_page_fields(optional):
    graph = claim_snapshot()
    payload = {
        "investigation_id": graph.investigation_id,
        "checkpoint_id": "legacy-run",
        "generated_at": graph.generated_at,
        "entities": [
            {
                "entity_id": "old",
                "type": "PERSON",
                "canonical_name": "Ada",
                "external_identifiers": {"passport": "AA1"},
            }
        ],
        "relationships": [],
    }
    if optional is None:
        payload.update(claims=None, claim_links=None, pages=None)
    checkpoints = MagicMock()
    checkpoints.find_one.return_value = payload
    repository = MongoRepository()
    repository._database = {"graph_checkpoints": checkpoints}

    loaded = repository.latest_graph_snapshot(graph.investigation_id)

    assert loaded.claims == loaded.claim_links == loaded.pages == ()
    assert loaded.entities[0].external_identifiers == (("passport", "AA1"),)


@pytest.mark.parametrize("fail_at", [6, 7, 8, 9])
def test_failure_during_claim_publication_rolls_back_every_snapshot_component(fail_at):
    driver = SnapshotDriver(fail_at)
    previous = deepcopy(driver.state)

    with pytest.raises(GraphPersistenceError):
        neo_repository(driver).save_graph_snapshot(claim_snapshot())

    assert driver.state == previous
    assert driver.write_count == 1


def test_neo4j_claims_keep_negations_separate_and_preserve_other_cases():
    driver = SnapshotDriver()
    previous = deepcopy(driver.state)
    graph = claim_snapshot()

    neo_repository(driver).save_graph_snapshot(graph)

    claim = driver.state["claims"][("case-a", "denial")]
    assert claim["polarity"] == "negated"
    assert claim["attribution"] == "Source B"
    assert json.loads(claim["support"][0])["page_number"] == 4
    assert claim["status"] == "rejected"
    assert driver.state["relationships"]["membership"]["claim_ids"] == ["assertion"]
    active_relations = [
        row
        for row in driver.state["relationships"].values()
        if row["investigation_id"] == "case-a" and row["active"]
    ]
    assert len(active_relations) == 1
    link = driver.state["claim_links"][("case-a", "comparison")]
    assert link["kind"] == "contradiction" and link["requires_identity_review"]
    assert (
        driver.state["claims"][("case-b", "other-claim")]
        == previous["claims"][("case-b", "other-claim")]
    )
    assert (
        driver.state["claim_links"][("case-b", "other-link")]
        == previous["claim_links"][("case-b", "other-link")]
    )
    coverage = json.loads(driver.state["coverage"]["case-a"][0])
    assert coverage["page_number"] == 2 and coverage["claim_count"] == 1
    assert "entities" not in coverage and "claims" not in coverage


@pytest.mark.parametrize(
    "invalid",
    [
        "unknown-endpoint",
        "unknown-claim",
        "negated-edge",
        "wrong-predicate",
        "wrong-subject",
        "duplicate-claim",
        "duplicate-link",
        "unknown-link",
    ],
)
def test_malformed_claim_graph_cannot_retire_the_existing_snapshot(invalid):
    graph = claim_snapshot()
    if invalid == "unknown-endpoint":
        graph = replace(graph, claims=(replace(graph.claims[0], object_entity_id="foreign"),))
    elif invalid == "unknown-claim":
        graph = replace(
            graph, relationships=(replace(graph.relationships[0], claim_ids=("missing",)),)
        )
    elif invalid == "negated-edge":
        graph = replace(
            graph, relationships=(replace(graph.relationships[0], claim_ids=("denial",)),)
        )
    elif invalid == "wrong-predicate":
        graph = replace(
            graph, relationships=(replace(graph.relationships[0], relationship_type="OWNS"),)
        )
    elif invalid == "wrong-subject":
        graph = replace(
            graph, relationships=(replace(graph.relationships[0], source_entity_id="levante"),)
        )
    elif invalid == "duplicate-claim":
        graph = replace(graph, claims=(*graph.claims, graph.claims[0]))
    elif invalid == "duplicate-link":
        graph = replace(graph, claim_links=(*graph.claim_links, graph.claim_links[0]))
    elif invalid == "unknown-link":
        graph = replace(
            graph, claim_links=(replace(graph.claim_links[0], target_claim_id="foreign"),)
        )
    driver = SnapshotDriver()
    previous = deepcopy(driver.state)

    with pytest.raises(GraphPersistenceError):
        neo_repository(driver).save_graph_snapshot(graph)

    assert driver.write_count == 0
    assert driver.state == previous


@pytest.mark.parametrize("target", ["claims", "claim_links"])
def test_missing_cypher_matches_fail_instead_of_reporting_partial_success(target):
    class MissingMatchTransaction(SnapshotTransaction):
        def run(self, query, **parameters):
            result = super().run(query, **parameters)
            if f"UNWIND ${target} " in query:
                return TransactionResult(False, 0)
            return result

    class MissingMatchSession(SnapshotSession):
        def execute_write(self, callback, *args):
            self.driver.write_count += 1
            tx = MissingMatchTransaction(deepcopy(self.driver.state), None)
            callback(tx, *args)
            self.driver.state = tx.state

    class Driver(SnapshotDriver):
        def session(self, *, database):
            return MissingMatchSession(self)

    driver = Driver()
    previous = deepcopy(driver.state)

    with pytest.raises(GraphPersistenceError):
        neo_repository(driver).save_graph_snapshot(claim_snapshot())

    assert driver.state == previous
