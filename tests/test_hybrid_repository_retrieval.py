"""Offline retrieval checks for tenant/run isolation and original source-page recall."""

import warnings
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from qdrant_client import QdrantClient
from test_graph_claim_storage import claim_snapshot
from test_neo4j_atomic import SnapshotDriver
from test_neo4j_atomic import repository as snapshot_repository

from raven.config import QdrantSettings
from raven.exceptions import GraphPersistenceError, InvestigationChatCancelledError
from raven.models import EvidenceDocument, EvidenceIngestionState
from raven.repositories.neo4j import Neo4jRepository
from raven.repositories.qdrant import QdrantRepository


def document(document_id="first", case="case-a"):
    return EvidenceDocument(
        document_id,
        case,
        f"{document_id}.pdf",
        f"{case}/{document_id}.pdf",
        "application/pdf",
        "PDF",
        100,
        "hash",
        2,
        False,
        EvidenceIngestionState.READY,
        datetime.now(UTC),
    )


@pytest.fixture
def qdrant():
    client = QdrantClient(location=":memory:")
    repository = QdrantRepository(lambda **kwargs: client)
    with warnings.catch_warnings(action="ignore", category=UserWarning):
        repository.initialize(QdrantSettings(collection="retrieval", vector_size=2))
    yield repository
    repository.close()


def test_qdrant_local_recall_finds_low_similarity_denial_only_on_requested_page(qdrant):
    first, other = document(), document("second")
    foreign = document("first", "case-b")
    qdrant.upsert_document(
        first,
        ("affirmation translated", "denial translated"),
        ((1.0, 0.0), (0.0, 1.0)),
        page_numbers=(1, 2),
        source_texts=("Ada è affiliata.", "Ada non è affiliata."),
        index_signature="hash:it:pages-v2",
    )
    qdrant.upsert_document(other, ("different file",), ((1.0, 0.0),), page_numbers=(2,))
    qdrant.upsert_document(foreign, ("FOREIGN",), ((1.0, 0.0),), page_numbers=(2,))

    nearest = qdrant.search("case-a", (1.0, 0.0), limit=1)
    recalled = qdrant.fetch_pages("case-a", (("first", 2),), limit=12)

    assert nearest[0].text != "denial translated"
    assert len(recalled) == 1
    assert recalled[0].text == "denial translated"
    assert recalled[0].original_text == "Ada non è affiliata."
    assert recalled[0].page_number == 2 and recalled[0].investigation_id == "case-a"
    assert recalled[0].index_signature == "hash:it:pages-v2"
    assert recalled[0].score == 0.0  # Direct source recall never invents vector similarity.


@pytest.mark.parametrize(
    "options",
    [
        {"page_numbers": ()},
        {"page_numbers": (0,)},
        {"page_numbers": (True,)},
        {"source_texts": ()},
        {"source_texts": (123,)},
    ],
)
def test_qdrant_invalid_source_metadata_does_not_remove_previous_document(qdrant, options):
    source = document()
    qdrant.upsert_document(source, ("preserved",), ((1.0, 0.0),), page_numbers=(1,))

    with pytest.raises(ValueError):
        qdrant.upsert_document(source, ("replacement",), ((1.0, 0.0),), **options)

    assert qdrant.search(source.investigation_id, (1.0, 0.0))[0].text == "preserved"


def test_legacy_qdrant_chunks_retain_unknown_page_and_original_text(qdrant):
    source = document()
    qdrant.upsert_document(source, ("legacy normalized text",), ((1.0, 0.0),))

    chunk = qdrant.search(source.investigation_id, (1.0, 0.0))[0]

    assert chunk.page_number is None and chunk.original_text is None
    assert qdrant.fetch_pages(source.investigation_id, ((source.document_id, 1),)) == ()


def test_qdrant_rejects_explicit_foreign_and_wrong_page_payloads_even_if_backend_returns_them():
    repository = QdrantRepository()
    client = MagicMock()
    repository._client, repository._settings = client, QdrantSettings(vector_size=2)
    points = [
        SimpleNamespace(
            score=1.0,
            payload={
                "investigation_id": case,
                "document_id": doc,
                "page_number": page,
                "text": "text",
            },
        )
        for case, doc, page in (
            ("case-b", "first", 1),
            ("case-a", "first", 2),
            ("case-a", "wrong", 1),
            ("case-a", "first", 1),
        )
    ]
    client.query_points.return_value.points = points
    client.scroll.return_value = (points, None)

    search = repository.search("case-a", (1.0, 0.0))
    recalled = repository.fetch_pages("case-a", (("first", 1),))

    assert len(search) == 3 and all(row.investigation_id == "case-a" for row in search)
    assert len(recalled) == 1 and recalled[0].document_id == "first"
    assert recalled[0].page_number == 1
    query_filter = client.scroll.call_args.kwargs["scroll_filter"]
    assert query_filter.must[0].match.value == "case-a"
    exact = query_filter.must[1].should[0].must
    assert [(field.key, field.match.value) for field in exact] == [
        ("document_id", "first"),
        ("page_number", 1),
    ]


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def data(self):
        return self.rows


class ReadTransaction:
    def __init__(self, head="run", final_head="run", *, many=0, on_read=None):
        self.head, self.final_head = head, final_head
        self.many, self.on_read = many, on_read
        self.calls = []
        self.head_reads = 0

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        assert isinstance(query, str)
        assert not any(word in query for word in ("MERGE ", "CREATE ", "DELETE ", "SET "))
        if self.on_read:
            self.on_read()
        if "latest_run_id" in query:
            self.head_reads += 1
            value = self.head if self.head_reads == 1 else self.final_head
            return Rows([{"run_id": value}] if value is not None else [])
        assert "investigation_id: $investigation_id" in query
        assert "run_id: $run_id, active: true" in query
        assert "LIMIT $limit" in query
        if "RETURN e.id AS entity_id" in query:
            return Rows(
                [{"entity_id": f"entity-{index:03d}"} for index in range(self.many)]
                if self.many
                else [{"entity_id": "ada"}]
            )
        if "RETURN c.id AS claim_id ORDER BY" in query:
            return Rows([{"claim_id": "affirmation"}])
        if "RETURN r.id AS relationship_id" in query:
            return Rows(
                [
                    {
                        "relationship_id": "member",
                        "source_id": "ada",
                        "target_id": "org",
                        "claim_ids": ["affirmation"],
                    }
                ]
            )
        if "RETURN r.id AS comparison_id" in query:
            return Rows(
                [
                    {
                        "comparison_id": "disagreement",
                        "source_id": "affirmation",
                        "target_id": "denial",
                    }
                ]
            )
        if "subject.id AS subject_id" in query:
            return Rows(
                [
                    {"claim_id": claim, "subject_id": "ada", "object_id": "org"}
                    for claim in ("affirmation", "denial")
                ]
            )
        raise AssertionError(query)


class ReadSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.driver.closed = True

    def execute_read(self, callback, *args):
        assert callback.timeout == 8
        self.driver.read_count += 1
        return callback(self.driver.transaction, *args)


class ReadDriver:
    def __init__(self, transaction):
        self.transaction = transaction
        self.closed, self.read_count = False, 0

    def session(self, *, database, default_access_mode):
        assert database == "raven-test" and default_access_mode == "READ"
        return ReadSession(self)


def reader(transaction):
    repository = Neo4jRepository()
    repository._driver, repository._database = ReadDriver(transaction), "raven-test"
    return repository


def test_neo4j_read_is_run_scoped_parameterized_and_includes_denial_counterpart():
    transaction = ReadTransaction()
    repository = reader(transaction)
    injection = "ada' DELETE all //"

    result = repository.retrieve_context(
        "case-a", "run", terms=(injection,), source_pages=(("document", 3), ("legacy", None))
    )

    assert result.state == "ready" and not result.truncated
    assert result.entity_ids == ("ada", "org")
    assert result.claim_ids == ("affirmation", "denial")
    assert result.relationship_ids == ("member",)
    assert result.comparison_ids == ("disagreement",)
    assert repository._driver.read_count == 1 and repository._driver.closed
    assert all(
        parameters["investigation_id"] == "case-a" and parameters["run_id"] == "run"
        for _, parameters in transaction.calls
    )
    assert all(injection not in query for query, _ in transaction.calls)
    assert transaction.calls[1][1]["terms"] == [injection.casefold()]
    assert transaction.calls[2][1]["page_keys"] == ["document:3"]
    assert transaction.calls[2][1]["document_ids"] == ["legacy"]


@pytest.mark.parametrize("actual", [None, "another-run"])
def test_neo4j_stale_or_missing_run_cannot_return_any_ids(actual):
    transaction = ReadTransaction(head=actual)
    result = reader(transaction).retrieve_context("case-a", "run", terms=("Ada",), source_pages=())
    assert result.state == ("missing" if actual is None else "stale")
    assert not any(
        (result.entity_ids, result.claim_ids, result.relationship_ids, result.comparison_ids)
    )
    assert len(transaction.calls) == 1


def test_neo4j_concurrent_publication_discards_selection_from_previous_active_run():
    result = reader(ReadTransaction(final_head="new-run")).retrieve_context(
        "case-a", "run", terms=("Ada",), source_pages=()
    )
    assert result.state == "stale" and result.run_id == "new-run"
    assert result.entity_ids == result.claim_ids == result.comparison_ids == ()


def test_neo4j_read_hard_caps_ids_and_reports_truncation():
    transaction = ReadTransaction(many=205)
    result = reader(transaction).retrieve_context(
        "case-a", "run", terms=("Ada",), source_pages=(), limit=10000
    )
    assert len(result.entity_ids) == 200 and result.truncated
    assert all(parameters["limit"] == 201 for _, parameters in transaction.calls)


def test_neo4j_cancel_is_propagated_after_read_without_returning_partial_context():
    state = {"cancelled": False}

    def cancel():
        state["cancelled"] = True

    transaction = ReadTransaction(on_read=cancel)
    with pytest.raises(InvestigationChatCancelledError):
        reader(transaction).retrieve_context(
            "case-a", "run", terms=(), source_pages=(), cancelled=lambda: state["cancelled"]
        )
    assert len(transaction.calls) == 1


def test_neo4j_failed_read_has_typed_failure_not_successful_empty_selection():
    transaction = ReadTransaction(on_read=lambda: (_ for _ in ()).throw(RuntimeError("timeout")))
    with pytest.raises(GraphPersistenceError, match="retrieve"):
        reader(transaction).retrieve_context("case-a", "run", terms=(), source_pages=())


def test_saved_claim_seed_keys_include_only_verified_original_pages():
    graph = claim_snapshot()
    claim = graph.claims[0]
    claim = replace(
        claim,
        support=(
            *claim.support,
            replace(claim.support[0], evidence_id="unverified", verified_original=False),
        ),
    )
    graph = replace(graph, claims=(claim, *graph.claims[1:]))
    driver = SnapshotDriver()

    snapshot_repository(driver).save_graph_snapshot(graph)

    payload = driver.state["claims"][(graph.investigation_id, claim.claim_id)]
    assert payload["evidence_ids"] == ["doc-positive"]
    assert payload["page_keys"] == ["doc-positive:2"]
