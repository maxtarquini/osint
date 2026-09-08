"""Question-directed retrieval preserves complete counterclaims and source boundaries."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from test_chat import (
    FakeAiNode,
    FakeKnowledgeBase,
    FakeRepository,
    FakeVectors,
    _document,
    _investigation,
)

from raven.exceptions import InvestigationChatCancelledError
from raven.models import GraphEntity, InvestigationGraph, RetrievedEvidenceChunk
from raven.models.graph import ClaimLink, EvidenceSpan, GraphClaim
from raven.models.retrieval import GraphRetrievalSelection
from raven.services.chat import InvestigationChatService
from raven.services.retrieval import HybridInvestigationRetriever, evidence_index_signature


def scenario():
    case = _investigation()
    first = replace(
        _document(case.investigation_id),
        file_format="PDF",
        original_name="report.pdf",
        page_count=3,
        page_count_estimated=False,
    )
    second = replace(first, document_id="denial", original_name="denial.pdf")
    yes = GraphClaim(
        "yes",
        "acme",
        "beta",
        "CONTROLS",
        support=(EvidenceSpan(first.document_id, "Acme controls Beta.", 1, True),),
    )
    no = replace(
        yes,
        claim_id="no",
        polarity="denied",
        support=(EvidenceSpan(second.document_id, "Acme does not control Beta.", 2, True),),
    )
    from raven.graph.claims import project_claims

    graph = InvestigationGraph(
        case.investigation_id,
        "current",
        (
            GraphEntity(
                "acme", "ORGANIZATION", "Acme", evidence_ids=(first.document_id, second.document_id)
            ),
            GraphEntity(
                "beta", "ORGANIZATION", "Beta", evidence_ids=(first.document_id, second.document_id)
            ),
        ),
        project_claims((yes, no)),
        datetime.now(UTC),
        claims=(yes, no),
        claim_links=(ClaimLink("opposition", "yes", "no", "contradicts", "Compare both sources"),),
    )
    chunk = RetrievedEvidenceChunk(
        first.document_id,
        first.original_name,
        0,
        "Acme controls Beta.",
        0.95,
        page_number=1,
        original_text="Acme controls Beta.",
        index_signature=evidence_index_signature(first, case.analysis_language.value),
        investigation_id=case.investigation_id,
    )
    return case, (first, second), graph, chunk


class Vectors:
    def __init__(self, chunks=(), linked=()):
        self.chunks, self.linked = chunks, linked
        self.requested = ()

    def search(self, *args, **kwargs):
        return self.chunks

    def fetch_pages(self, case_id, pages, *, limit):
        self.requested = (case_id, pages, limit)
        return self.linked


class GraphStore:
    def __init__(self, selection):
        self.selection = selection
        self.requested = ()

    def retrieve_context(self, *args, **kwargs):
        self.requested = (args, kwargs)
        return self.selection


def test_vector_page_to_neo4j_to_counterclaim_to_original_page():
    case, docs, graph, chunk = scenario()
    linked = replace(
        chunk,
        document_id=docs[1].document_id,
        document_name=docs[1].original_name,
        page_number=2,
        text=graph.claims[1].support[0].quote,
        original_text=graph.claims[1].support[0].quote,
    )
    vectors = Vectors((chunk,), (linked,))
    store = GraphStore(
        GraphRetrievalSelection(case.investigation_id, graph.run_id, claim_ids=("yes",))
    )
    result = HybridInvestigationRetriever(vectors, store).retrieve(
        case, docs, graph, "Acme?", (0.5,)
    )
    assert result.trace.strategy == "qdrant+neo4j"
    assert {claim.claim_id for claim in result.graph.claims} == {"yes", "no"}
    assert result.graph.claim_links == graph.claim_links
    assert len(result.graph.relationships) == 1
    assert store.requested[1]["source_pages"] == ((docs[0].document_id, 1),)
    assert (docs[1].document_id, 2) in vectors.requested[1]
    assert len(result.chunks) == 2 and result.trace.linked_sources == 1


@pytest.mark.parametrize("bad", ["case", "run", "unavailable"])
def test_neo4j_failure_or_wrong_generation_falls_back_to_current_snapshot(bad):
    case, docs, graph, chunk = scenario()
    selection = GraphRetrievalSelection(case.investigation_id, graph.run_id, claim_ids=("forged",))
    if bad == "case":
        selection = replace(selection, investigation_id="foreign")
    elif bad == "run":
        selection = replace(selection, run_id="old")
    store = GraphStore(selection)
    if bad == "unavailable":

        def failed(*args, **kwargs):
            raise RuntimeError("SECRET ENDPOINT")

        store.retrieve_context = failed
    result = HybridInvestigationRetriever(Vectors(), store).retrieve(
        case, docs, graph, "Acme?", None
    )
    assert result.trace.strategy == "qdrant+snapshot"
    assert {claim.claim_id for claim in result.graph.claims} == {"yes", "no"}
    assert result.trace.warnings and "SECRET" not in repr(result)


def test_vector_payloads_from_other_cases_deleted_documents_and_old_index_are_rejected():
    case, docs, graph, chunk = scenario()
    vectors = Vectors(
        (
            replace(chunk, investigation_id="foreign"),
            replace(chunk, document_id="deleted"),
            replace(chunk, index_signature="old-signature"),
            replace(chunk, page_number=99),
        )
    )
    result = HybridInvestigationRetriever(vectors).retrieve(case, docs, None, "Acme", (0.5,))
    assert result.chunks == ()
    # A foreign Mongo snapshot cannot supply claims even if entity IDs happen to match.
    result = HybridInvestigationRetriever(vectors).retrieve(
        case, docs, replace(graph, investigation_id="foreign"), "Acme", (0.5,)
    )
    assert result.graph is None and "foreign_graph_rejected" in result.trace.warnings


def test_removed_document_claims_do_not_survive_in_retrieved_graph():
    case, docs, graph, chunk = scenario()
    result = HybridInvestigationRetriever(Vectors()).retrieve(case, docs[:1], graph, "Acme", None)
    assert [claim.claim_id for claim in result.graph.claims] == ["yes"]
    assert result.graph.claim_links == ()
    assert all(docs[1].document_id not in entity.evidence_ids for entity in result.graph.entities)


def test_question_finds_entity_after_first_hundred_without_loading_unrelated_graph():
    case, docs, graph, chunk = scenario()
    distractors = tuple(
        GraphEntity(f"noise-{index}", "PERSON", f"Unrelated{index}") for index in range(140)
    )
    graph = replace(graph, entities=(*distractors, *graph.entities))
    result = HybridInvestigationRetriever(Vectors()).retrieve(
        case, docs, graph, "Who controls Beta?", None
    )
    assert {entity.entity_id for entity in result.graph.entities} == {"acme", "beta"}


def test_oversized_comparison_component_is_omitted_whole():
    case, docs, graph, chunk = scenario()
    claims = tuple(replace(graph.claims[index % 2], claim_id=str(index)) for index in range(81))
    links = tuple(
        ClaimLink(str(index), str(index), str(index + 1), "contradicts", "Compare")
        for index in range(80)
    )
    graph = replace(graph, claims=claims, claim_links=links, relationships=())
    result = HybridInvestigationRetriever(Vectors()).retrieve(case, docs, graph, "Acme", None)
    assert result.graph.claims == () and result.graph.claim_links == ()
    assert result.trace.truncated


def test_cancellation_between_vector_and_graph_queries():
    case, docs, graph, chunk = scenario()
    stopped = False
    vectors = Vectors()

    def search(*args, **kwargs):
        nonlocal stopped
        stopped = True
        return (chunk,)

    vectors.search = search
    store = GraphStore(GraphRetrievalSelection(case.investigation_id, graph.run_id))
    with pytest.raises(InvestigationChatCancelledError):
        HybridInvestigationRetriever(vectors, store).retrieve(
            case, docs, graph, "Acme", (0.5,), cancelled=lambda: stopped
        )
    assert store.requested == ()


def test_actual_chat_budget_never_slices_claim_json_or_leaves_half_conflict():
    case, docs, graph, chunk = scenario()
    messages = InvestigationChatService._conversation_messages(
        (), "Acme?", (chunk,), graph, context_size=3000
    )
    payload = messages[-1]["content"].split("CURRENT INVESTIGATION GRAPH\n", 1)[1]
    parsed = json.loads(payload)
    assert {claim["id"] for claim in parsed["claims"]} in (set(), {"yes", "no"})
    small = InvestigationChatService._conversation_messages(
        (), "Acme?", (chunk,), graph, context_size=512
    )
    assert json.loads(small[-1]["content"].split("CURRENT INVESTIGATION GRAPH\n", 1)[1])["omitted"]


def test_indexing_retains_physical_pages_and_original_text_when_translated():
    case, docs, graph, chunk = scenario()
    kb = FakeKnowledgeBase()
    kb.extract_pages = lambda *args: ("Prima pagina.", "", "Terza pagina.")
    ai = FakeAiNode()

    def chat(system, user, **options):
        return "it" if "Language Detection" in system else "English translation."

    ai.chat = chat
    saved = {}
    vectors = FakeVectors()

    def upsert(doc, chunks, vectors, **metadata):
        saved.update(metadata, chunks=chunks)

    vectors.upsert_document = upsert
    InvestigationChatService(FakeRepository(), vectors, ai, kb).index_knowledge_base(case, docs[:1])
    assert saved["page_numbers"] == (1, 3)
    assert saved["source_texts"] == ("Prima pagina.", "Terza pagina.")
    assert saved["chunks"] == ("English translation.", "English translation.")


def test_chat_citations_name_graph_sources_and_keep_original_quotation():
    case, docs, graph, chunk = scenario()
    context = InvestigationChatService._graph_context(graph)
    labels = InvestigationChatService._source_labels(
        (chunk,), context, {doc.document_id: doc.original_name for doc in docs}
    )
    assert any("[G" in label and "denial.pdf" in label and "page 2" in label for label in labels)
    translated = replace(chunk, original_text="Testo originale.", text="Translated text.")
    text = InvestigationChatService._evidence_context((translated,))
    assert "ORIGINAL SOURCE\nTesto originale." in text
    assert "may be translated" in text
