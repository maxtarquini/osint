"""Snapshot replacement must commit completely or leave the active graph untouched."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from raven.exceptions import GraphPersistenceError
from raven.models import GraphEntity, GraphRelationship, InvestigationGraph
from raven.models.graph import EvidenceSpan
from raven.repositories.neo4j import Neo4jRepository


class TransactionResult:
    def __init__(self, fail: bool, written: int = 0) -> None:
        self.fail = fail
        self.written = written

    def single(self, *, strict: bool) -> dict[str, int]:
        assert strict
        return {"written": self.written}

    def consume(self) -> None:
        if self.fail:
            raise RuntimeError("Simulated deferred Neo4j write failure")


class SnapshotTransaction:
    """Small transactional store; no network, Cypher engine, or real investigation data."""

    def __init__(self, state: dict[str, Any], fail_at: int | None) -> None:
        self.state = state
        self.fail_at = fail_at
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, query: str, **parameters: Any) -> TransactionResult:
        self.calls.append((query, parameters))
        investigation_id = parameters["investigation_id"]
        if query.startswith("MERGE (i:Investigation"):
            self.state["investigations"][investigation_id] = parameters["run_id"]
            self.state["coverage"][investigation_id] = parameters["page_coverage"]
        elif "SET e.active = false" in query:
            for entity in self.state["entities"].values():
                if entity["investigation_id"] == investigation_id:
                    entity["active"] = False
        elif "UNWIND $entities" in query:
            assert "MERGE (e:Entity {id: item.id, investigation_id: $investigation_id})" in query
            for entity in parameters["entities"]:
                old = self.state["entities"].get(entity["id"])
                if old and old["investigation_id"] != investigation_id:
                    raise RuntimeError("Entity unique constraint prevents cross-case ID reuse")
                self.state["entities"][entity["id"]] = {
                    **entity,
                    "investigation_id": investigation_id,
                    "active": True,
                }
        elif "SET c.active = false" in query:
            for claim in self.state["claims"].values():
                if claim["investigation_id"] == investigation_id:
                    claim["active"] = False
        elif "r:HAS_SUBJECT|HAS_OBJECT|CLAIM_COMPARISON" in query:
            for link in self.state["claim_links"].values():
                if link["investigation_id"] == investigation_id:
                    link["active"] = False
        elif "UNWIND $claims" in query:
            assert query.count("investigation_id: $investigation_id, active: true") == 2
            assert "EVIDENCE_RELATION" not in query
            for claim in parameters["claims"]:
                self.state["claims"][(investigation_id, claim["claim_id"])] = {
                    **claim,
                    "investigation_id": investigation_id,
                    "active": True,
                }
        elif "UNWIND $claim_links" in query:
            assert query.count("investigation_id: $investigation_id, active: true") == 2
            for link in parameters["claim_links"]:
                self.state["claim_links"][(investigation_id, link["link_id"])] = {
                    **link,
                    "investigation_id": investigation_id,
                    "active": True,
                }
        elif "SET r.active = false" in query:
            assert "r:EVIDENCE_RELATION {investigation_id: $investigation_id}" in query
            for relation in self.state["relationships"].values():
                if relation["investigation_id"] == investigation_id:
                    relation["active"] = False
        elif "UNWIND $relationships" in query:
            assert query.count("investigation_id: $investigation_id, active: true") == 2
            for relation in parameters["relationships"]:
                self.state["relationships"][relation["id"]] = {
                    **relation,
                    "investigation_id": investigation_id,
                    "active": True,
                }
        else:
            raise AssertionError(f"Unexpected query: {query}")
        written = len(parameters.get("claims", parameters.get("claim_links", [])))
        return TransactionResult(len(self.calls) == self.fail_at, written)


class SnapshotSession:
    def __init__(self, driver: "SnapshotDriver") -> None:
        self.driver = driver

    def __enter__(self) -> "SnapshotSession":
        return self

    def __exit__(self, *args: Any) -> None:
        self.driver.closed_sessions += 1

    def execute_write(self, callback: Any, *args: Any) -> None:
        self.driver.write_count += 1
        transaction = SnapshotTransaction(deepcopy(self.driver.state), self.driver.fail_at)
        self.driver.transactions.append(transaction)
        callback(transaction, *args)
        self.driver.state = transaction.state


class SnapshotDriver:
    def __init__(self, fail_at: int | None = None) -> None:
        self.state = {
            "investigations": {"case-a": "old-run", "case-b": "other-run"},
            "entities": {
                "old-person": {"investigation_id": "case-a", "active": True},
                "other-person": {"investigation_id": "case-b", "active": True},
            },
            "relationships": {
                "old-relation": {"investigation_id": "case-a", "active": True},
                "other-relation": {"investigation_id": "case-b", "active": True},
            },
            "claims": {
                ("case-a", "old-claim"): {"investigation_id": "case-a", "active": True},
                ("case-b", "other-claim"): {"investigation_id": "case-b", "active": True},
            },
            "claim_links": {
                ("case-a", "old-link"): {"investigation_id": "case-a", "active": True},
                ("case-b", "other-link"): {"investigation_id": "case-b", "active": True},
            },
            "coverage": {},
        }
        self.fail_at = fail_at
        self.transactions: list[SnapshotTransaction] = []
        self.write_count = 0
        self.closed_sessions = 0

    def session(self, *, database: str) -> SnapshotSession:
        assert database == "raven-test"
        return SnapshotSession(self)


def repository(driver: SnapshotDriver) -> Neo4jRepository:
    result = Neo4jRepository()
    result._driver = driver
    result._database = "raven-test"
    return result


def snapshot(*, empty: bool = False, person_id: str = "new-person") -> InvestigationGraph:
    citation = EvidenceSpan("document-1", "Rossi lavora per Alfa.", 2, True)
    return InvestigationGraph(
        "case-a",
        "new-run",
        ()
        if empty
        else (
            GraphEntity(
                person_id,
                "PERSON",
                "Rossi",
                evidence_ids=("document-1",),
                support=(citation,),
                resolution_notes=("Distinct identifiers retained.",),
            ),
            GraphEntity("company", "ORGANIZATION", "Alfa"),
        ),
        ()
        if empty
        else (
            GraphRelationship(
                "new-relation",
                person_id,
                "company",
                "WORKS_FOR",
                evidence_ids=("document-1",),
                support=(citation,),
            ),
        ),
        datetime.now(UTC),
    )


@pytest.mark.parametrize("fail_at", range(1, 10))
def test_snapshot_deferred_write_failure_rolls_back_entire_replacement(fail_at: int) -> None:
    driver = SnapshotDriver(fail_at)
    before = deepcopy(driver.state)

    with pytest.raises(GraphPersistenceError, match="synchronize") as error:
        repository(driver).save_graph_snapshot(snapshot())

    assert isinstance(error.value.__cause__, RuntimeError)
    assert driver.state == before
    assert driver.write_count == 1
    assert driver.closed_sessions == 1


def test_snapshot_commit_preserves_other_cases_and_serializes_citation_coordinates() -> None:
    driver = SnapshotDriver()
    before = deepcopy(driver.state)

    repository(driver).save_graph_snapshot(snapshot())

    assert driver.write_count == 1
    assert len(driver.transactions[0].calls) == 9
    assert driver.state["investigations"] == {"case-a": "new-run", "case-b": "other-run"}
    assert driver.state["entities"]["other-person"] == before["entities"]["other-person"]
    assert (
        driver.state["relationships"]["other-relation"] == before["relationships"]["other-relation"]
    )
    assert driver.state["entities"]["old-person"]["active"] is False
    assert driver.state["relationships"]["old-relation"]["active"] is False
    entity = driver.state["entities"]["new-person"]
    relation = driver.state["relationships"]["new-relation"]
    assert entity["active"] is relation["active"] is True
    assert entity["support"] == relation["support"]
    assert json.loads(entity["support"][0]) == {
        "evidence_id": "document-1",
        "page_number": 2,
        "quote": "Rossi lavora per Alfa.",
        "verified_original": True,
        "unit_id": "",
        "start_offset": None,
        "end_offset": None,
    }
    assert entity["resolution_notes"] == ["Distinct identifiers retained."]
    assert driver.state["entities"]["company"]["support"] == []


def test_empty_snapshot_retires_only_selected_case() -> None:
    driver = SnapshotDriver()

    repository(driver).save_graph_snapshot(snapshot(empty=True))

    assert driver.state["investigations"]["case-a"] == "new-run"
    assert driver.state["entities"]["old-person"]["active"] is False
    assert driver.state["relationships"]["old-relation"]["active"] is False
    assert driver.state["entities"]["other-person"]["active"] is True
    assert driver.state["relationships"]["other-relation"]["active"] is True
    assert driver.state["claims"][("case-a", "old-claim")]["active"] is False
    assert driver.state["claims"][("case-b", "other-claim")]["active"] is True
    assert driver.state["claim_links"][("case-a", "old-link")]["active"] is False
    assert driver.state["claim_links"][("case-b", "other-link")]["active"] is True


def test_foreign_entity_id_cannot_reassign_another_cases_node() -> None:
    driver = SnapshotDriver()
    before = deepcopy(driver.state)

    with pytest.raises(GraphPersistenceError, match="synchronize"):
        repository(driver).save_graph_snapshot(snapshot(person_id="other-person"))

    assert driver.state == before


def test_missing_endpoint_is_rejected_before_starting_replacement() -> None:
    driver = SnapshotDriver()
    before = deepcopy(driver.state)
    graph = InvestigationGraph(
        "case-a",
        "new-run",
        (),
        (GraphRelationship("bad", "other-person", "company", "WORKS_FOR"),),
        datetime.now(UTC),
    )

    with pytest.raises(GraphPersistenceError, match="unknown relationship endpoint"):
        repository(driver).save_graph_snapshot(graph)

    assert driver.state == before
    assert driver.write_count == 0


@pytest.mark.parametrize("duplicate", ["entity", "relationship"])
def test_duplicate_ids_cannot_silently_overwrite_snapshot_items(duplicate: str) -> None:
    driver = SnapshotDriver()
    before = deepcopy(driver.state)
    valid = snapshot()
    graph = InvestigationGraph(
        valid.investigation_id,
        valid.run_id,
        valid.entities + (valid.entities[0],) if duplicate == "entity" else valid.entities,
        valid.relationships + valid.relationships
        if duplicate == "relationship"
        else valid.relationships,
        valid.generated_at,
    )

    with pytest.raises(GraphPersistenceError, match="duplicate item identifiers"):
        repository(driver).save_graph_snapshot(graph)

    assert driver.state == before
    assert driver.write_count == 0
