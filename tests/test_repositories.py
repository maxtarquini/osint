"""Deterministic schema-bootstrap tests using simulated database drivers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from neo4j.exceptions import AuthError

from raven.config import MongoSettings, Neo4jSettings, QdrantSettings
from raven.exceptions import InfrastructureAuthenticationError
from raven.models import (
    DEFAULT_ANALYSIS_DOMAIN,
    AnalysisLanguage,
    ChatMessage,
    ChatRole,
    EvidenceDocument,
    EvidenceIngestionState,
    EvidencePreparationMode,
    GraphAnalysisRun,
    GraphEntity,
    GraphRelationship,
    GraphRunStatus,
    Investigation,
    InvestigationGraph,
    InvestigationStatus,
    TokenUsage,
)
from raven.repositories.mongodb import BASE_COLLECTIONS, MongoRepository
from raven.repositories.neo4j import SCHEMA_QUERIES, Neo4jRepository
from raven.repositories.qdrant import QdrantRepository


def test_mongodb_bootstrap_creates_collections_indexes_and_schema_marker() -> None:
    client = MagicMock()
    database = MagicMock()
    collections = {name: MagicMock() for name in BASE_COLLECTIONS}
    client.__getitem__.return_value = database
    database.list_collection_names.return_value = []
    database.__getitem__.side_effect = collections.__getitem__
    factory = MagicMock(return_value=client)
    repository = MongoRepository(factory)

    repository.initialize(MongoSettings())

    client.admin.command.assert_called_once_with("ping")
    assert database.create_collection.call_count == len(BASE_COLLECTIONS)
    collections["investigations"].create_index.assert_called()
    assert collections["evidence_documents"].create_index.call_count == 5
    assert collections["chat_messages"].create_index.call_count == 2
    collections["entities"].create_index.assert_called()
    collections["relationships"].create_index.assert_called()
    collections["app_metadata"].update_one.assert_called_once()
    repository.close()
    client.close.assert_called_once()


def test_mongodb_persists_chat_token_usage() -> None:
    client = MagicMock()
    database = MagicMock()
    collections = {name: MagicMock() for name in BASE_COLLECTIONS}
    client.__getitem__.return_value = database
    database.list_collection_names.return_value = list(BASE_COLLECTIONS)
    database.__getitem__.side_effect = collections.__getitem__
    repository = MongoRepository(MagicMock(return_value=client))
    repository.initialize(MongoSettings())
    message = ChatMessage(
        message_id="message-id",
        investigation_id="investigation-id",
        role=ChatRole.ASSISTANT,
        content="Grounded answer",
        created_at=datetime.now(UTC),
        usage=TokenUsage(120, 30, 150),
    )

    repository.save_chat_message(message)

    document = collections["chat_messages"].insert_one.call_args.args[0]
    assert document["usage"] == {
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
    }


def test_mongodb_persists_investigation_and_evidence_manifest() -> None:
    client = MagicMock()
    database = MagicMock()
    collections = {name: MagicMock() for name in BASE_COLLECTIONS}
    client.__getitem__.return_value = database
    database.list_collection_names.return_value = list(BASE_COLLECTIONS)
    database.__getitem__.side_effect = collections.__getitem__
    repository = MongoRepository(MagicMock(return_value=client))
    repository.initialize(MongoSettings())
    now = datetime.now(UTC)
    evidence = EvidenceDocument(
        document_id="document-id",
        investigation_id="investigation-id",
        original_name="report.pdf",
        storage_key="investigation-id/document-id.pdf",
        media_type="application/pdf",
        file_format="PDF",
        size_bytes=100,
        sha256="0" * 64,
        page_count=4,
        page_count_estimated=False,
        ingestion_state=EvidenceIngestionState.PENDING,
        created_at=now,
    )
    investigation = Investigation(
        investigation_id="investigation-id",
        name="Case",
        description="Context",
        questions=("Who?",),
        status=InvestigationStatus.DRAFT,
        evidence_documents=(),
        created_at=now,
        updated_at=now,
        analysis_domain="MARITIME_INTELLIGENCE",
    )

    repository.create_investigation(investigation)
    repository.add_evidence(evidence)

    stored_investigation = collections["investigations"].insert_one.call_args.args[0]
    stored_evidence = collections["evidence_documents"].insert_one.call_args.args[0]
    assert stored_investigation["questions"] == ["Who?"]
    assert stored_investigation["analysis_language"] == "original"
    assert stored_investigation["analysis_domain"] == "MARITIME_INTELLIGENCE"
    assert stored_investigation["evidence_count"] == 0
    assert stored_evidence["storage_key"] == "investigation-id/document-id.pdf"
    assert stored_evidence["page_count"] == 4
    assert stored_evidence["ingestion_state"] == "pending"

    collections["investigations"].find.return_value.sort.return_value = [stored_investigation]
    collections["evidence_documents"].find.return_value = [stored_evidence]
    loaded = repository.list_investigations()
    assert loaded[0].name == "Case"
    assert loaded[0].analysis_domain == "MARITIME_INTELLIGENCE"
    assert loaded[0].evidence_documents == (evidence,)

    legacy_document = dict(stored_investigation)
    legacy_document.pop("analysis_domain")
    legacy = repository._investigation_from_document(legacy_document, ())
    assert legacy.analysis_domain == DEFAULT_ANALYSIS_DOMAIN

    repository.delete_evidence(evidence)
    collections["evidence_documents"].delete_one.assert_called_with(
        {"investigation_id": "investigation-id", "document_id": "document-id"}
    )


def test_mongodb_updates_profile_and_cascade_deletes_case_records() -> None:
    client = MagicMock()
    database = MagicMock()
    collections = {name: MagicMock() for name in BASE_COLLECTIONS}
    client.__getitem__.return_value = database
    database.list_collection_names.return_value = list(BASE_COLLECTIONS)
    database.__getitem__.side_effect = collections.__getitem__
    collections["investigations"].update_one.return_value.matched_count = 1
    collections["investigations"].delete_one.return_value.deleted_count = 1
    repository = MongoRepository(MagicMock(return_value=client))
    repository.initialize(MongoSettings())
    now = datetime.now(UTC)
    investigation = Investigation(
        "investigation-id",
        "Updated case",
        "Context",
        ("Who?",),
        InvestigationStatus.DRAFT,
        (),
        now,
        now,
        AnalysisLanguage.ITALIAN,
        "MARITIME_INTELLIGENCE",
    )

    repository.update_investigation(investigation)
    repository.reset_evidence_ingestion_states(investigation.investigation_id)
    repository.clear_graph_data(investigation.investigation_id)
    repository.delete_investigation(investigation.investigation_id)

    profile = collections["investigations"].update_one.call_args_list[0].args[1]["$set"]
    assert profile["analysis_language"] == "italian"
    assert profile["analysis_domain"] == "MARITIME_INTELLIGENCE"
    collections["evidence_documents"].update_many.assert_called_once()
    collections["chat_messages"].delete_many.assert_called_once_with(
        {"investigation_id": "investigation-id"}
    )
    collections["investigations"].delete_one.assert_called_once_with(
        {"investigation_id": "investigation-id"}
    )


def test_qdrant_bootstrap_creates_cosine_collection_when_missing() -> None:
    client = MagicMock()
    client.collection_exists.return_value = False
    factory = MagicMock(return_value=client)
    repository = QdrantRepository(factory)
    settings = QdrantSettings(collection="case_vectors", vector_size=384)

    repository.initialize(settings)

    client.get_collections.assert_called_once()
    create = client.create_collection.call_args.kwargs
    assert create["collection_name"] == "case_vectors"
    assert create["vectors_config"].size == 384
    assert client.create_payload_index.call_count == 3
    repository.close()
    client.close.assert_called_once()


def test_qdrant_bootstrap_validates_existing_vector_size() -> None:
    client = MagicMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=1024)))
    )
    repository = QdrantRepository(MagicMock(return_value=client))

    repository.initialize(QdrantSettings())

    client.create_collection.assert_not_called()


def test_qdrant_bootstrap_recreates_empty_collection_for_new_vector_size() -> None:
    client = MagicMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=1536))),
        points_count=0,
    )
    repository = QdrantRepository(MagicMock(return_value=client))

    repository.initialize(QdrantSettings(collection="case_vectors", vector_size=1024))

    client.delete_collection.assert_called_once_with(collection_name="case_vectors")
    create = client.create_collection.call_args.kwargs
    assert create["collection_name"] == "case_vectors"
    assert create["vectors_config"].size == 1024
    assert client.create_payload_index.call_count == 3


def test_qdrant_bootstrap_preserves_non_empty_collection_on_size_mismatch() -> None:
    client = MagicMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=1536))),
        points_count=4,
    )
    repository = QdrantRepository(MagicMock(return_value=client))

    with pytest.raises(ValueError, match="contains 4 points"):
        repository.initialize(QdrantSettings(collection="case_vectors", vector_size=1024))

    client.delete_collection.assert_not_called()
    client.create_collection.assert_not_called()
    client.close.assert_called_once()


def test_qdrant_rag_search_is_always_partitioned_by_investigation() -> None:
    client = MagicMock()
    client.collection_exists.return_value = False
    client.scroll.return_value = ([], None)
    client.query_points.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.91,
                payload={
                    "document_id": "document-id",
                    "document_name": "report.pdf",
                    "chunk_index": 2,
                    "text": "Relevant Evidence",
                    "page_count": 4,
                },
            )
        ]
    )
    repository = QdrantRepository(MagicMock(return_value=client))
    repository.initialize(QdrantSettings(collection="case_vectors", vector_size=3))

    chunks = repository.search("investigation-a", (0.1, 0.2, 0.3))

    query = client.query_points.call_args.kwargs
    assert query["collection_name"] == "case_vectors"
    assert query["query_filter"].must[0].match.value == "investigation-a"
    assert chunks[0].document_name == "report.pdf"
    assert chunks[0].chunk_index == 2


def test_qdrant_reports_confirmed_document_chunk_count_and_vector_size() -> None:
    client = MagicMock()
    client.collection_exists.return_value = False
    client.count.return_value = SimpleNamespace(count=7)
    repository = QdrantRepository(MagicMock(return_value=client))
    repository.initialize(QdrantSettings(collection="case_vectors", vector_size=1024))

    count = repository.document_chunk_count("investigation-a", "document-a")

    assert repository.vector_size == 1024
    assert count == 7
    request = client.count.call_args.kwargs
    assert request["collection_name"] == "case_vectors"
    assert request["exact"] is True
    assert [condition.match.value for condition in request["count_filter"].must] == [
        "investigation-a",
        "document-a",
    ]


def test_qdrant_deletes_complete_investigation_partition() -> None:
    client = MagicMock()
    client.collection_exists.return_value = False
    repository = QdrantRepository(MagicMock(return_value=client))
    repository.initialize(QdrantSettings(collection="case_vectors", vector_size=3))

    repository.remove_investigation("investigation-a")

    delete = client.delete.call_args.kwargs
    assert delete["collection_name"] == "case_vectors"
    assert delete["points_selector"].filter.must[0].match.value == "investigation-a"


def test_neo4j_bootstrap_verifies_connection_and_applies_schema() -> None:
    driver = MagicMock()
    factory = MagicMock(return_value=driver)
    repository = Neo4jRepository(factory)
    settings = Neo4jSettings(password="secret")

    repository.initialize(settings)

    factory.assert_called_once_with(
        settings.uri,
        auth=(settings.username, "secret"),
        connection_timeout=2.5,
    )
    driver.verify_connectivity.assert_called_once()
    assert driver.execute_query.call_count == len(SCHEMA_QUERIES) + 1
    for query in SCHEMA_QUERIES:
        driver.execute_query.assert_any_call(query, database_=settings.database)
    repository.close()
    driver.close.assert_called_once()


def test_mongodb_persists_graph_run_and_reloads_latest_snapshot() -> None:
    client = MagicMock()
    database = MagicMock()
    collections = {name: MagicMock() for name in BASE_COLLECTIONS}
    client.__getitem__.return_value = database
    database.list_collection_names.return_value = list(BASE_COLLECTIONS)
    database.__getitem__.side_effect = collections.__getitem__
    repository = MongoRepository(MagicMock(return_value=client))
    repository.initialize(MongoSettings())
    now = datetime.now(UTC)
    run = GraphAnalysisRun(
        "run-id",
        "investigation-id",
        GraphRunStatus.COMPLETED,
        EvidencePreparationMode.COMPRESS,
        AnalysisLanguage.ITALIAN.value,
        1,
        1,
        0,
        2,
        1,
        "model-a",
        now,
        now,
        now,
    )
    graph = InvestigationGraph(
        "investigation-id",
        "run-id",
        (
            GraphEntity("person", "PERSON", "Mario Rossi", evidence_ids=("evidence",)),
            GraphEntity("company", "ORGANIZATION", "Alfa", evidence_ids=("evidence",)),
        ),
        (
            GraphRelationship(
                "works-for",
                "person",
                "company",
                "WORKS_FOR",
                evidence_ids=("evidence",),
            ),
        ),
        now,
    )

    repository.save_graph_run(run)
    repository.save_graph_snapshot(graph)
    checkpoint = collections["graph_checkpoints"].replace_one.call_args.args[1]
    collections["graph_checkpoints"].find_one.return_value = checkpoint

    loaded = repository.latest_graph_snapshot("investigation-id")

    assert collections["graph_analysis_runs"].replace_one.call_args.kwargs["upsert"] is True
    assert loaded == graph


def test_neo4j_synchronizes_proposed_graph_with_evidence_provenance() -> None:
    driver = MagicMock()
    repository = Neo4jRepository(MagicMock(return_value=driver))
    repository.initialize(Neo4jSettings(password="secret"))
    now = datetime.now(UTC)
    graph = InvestigationGraph(
        "investigation-id",
        "run-id",
        (
            GraphEntity("person", "PERSON", "Mario Rossi", evidence_ids=("evidence",)),
            GraphEntity("company", "ORGANIZATION", "Alfa", evidence_ids=("evidence",)),
        ),
        (
            GraphRelationship(
                "works-for",
                "person",
                "company",
                "WORKS_FOR",
                evidence_ids=("evidence",),
            ),
        ),
        now,
    )
    session = driver.session.return_value.__enter__.return_value
    transaction = MagicMock()
    session.execute_write.side_effect = lambda fn, *args: fn(transaction, *args)

    repository.save_graph_snapshot(graph)

    session.execute_write.assert_called_once()
    assert transaction.run.call_count == 5
    entity_call = transaction.run.call_args_list[2]
    assert entity_call.kwargs["entities"][0]["evidence_ids"] == ["evidence"]
    relationship_call = transaction.run.call_args_list[4]
    assert relationship_call.kwargs["relationships"][0]["type"] == "WORKS_FOR"


def test_neo4j_deletes_only_selected_investigation_subgraph() -> None:
    driver = MagicMock()
    repository = Neo4jRepository(MagicMock(return_value=driver))
    repository.initialize(Neo4jSettings(password="secret"))
    calls_before = driver.execute_query.call_count

    repository.delete_investigation("investigation-id")

    calls = driver.execute_query.call_args_list[calls_before:]
    assert len(calls) == 2
    assert all(call.kwargs["investigation_id"] == "investigation-id" for call in calls)
    assert all("DETACH DELETE" in call.args[0] for call in calls)


def test_neo4j_bootstrap_translates_authentication_failure() -> None:
    driver = MagicMock()
    driver.verify_connectivity.side_effect = AuthError("authentication required")
    repository = Neo4jRepository(MagicMock(return_value=driver))

    with pytest.raises(InfrastructureAuthenticationError):
        repository.initialize(Neo4jSettings())

    driver.close.assert_called_once()
