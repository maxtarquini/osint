"""Question-directed retrieval preserves complete counterclaims and source boundaries."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_chat import (
    FakeAiNode,
    FakeKnowledgeBase,
    FakeRepository,
    FakeVectors,
    _document,
    _investigation,
)

from raven.exceptions import InvestigationChatCancelledError, InvestigationChatError
from raven.models import (
    ChatMessage,
    ChatRole,
    GraphEntity,
    InvestigationGraph,
    RetrievedEvidenceChunk,
)
from raven.models.graph import ClaimLink, EvidenceSpan, GraphClaim
from raven.models.retrieval import GraphRetrievalSelection
from raven.services.chat import InvestigationChatService
from raven.services.context_budget import MESSAGE_ENVELOPE_CHARS, budget_context
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


@pytest.mark.parametrize("vector_page", [1, None])
def test_oversized_comparison_component_cannot_leak_through_positive_vector_or_entity(vector_page):
    case, docs, graph, chunk = scenario()
    claims = tuple(replace(graph.claims[index % 2], claim_id=str(index)) for index in range(81))
    links = tuple(
        ClaimLink(str(index), str(index), str(index + 1), "contradicts", "Compare")
        for index in range(80)
    )
    graph = replace(
        graph,
        claims=claims,
        claim_links=links,
        entities=(replace(graph.entities[0], support=graph.claims[0].support), graph.entities[1]),
        relationships=(replace(graph.relationships[0], claim_ids=()),),
    )
    result = HybridInvestigationRetriever(
        Vectors((replace(chunk, page_number=vector_page),))
    ).retrieve(case, docs, graph, "Acme", (0.5,))
    assert result.graph.claims == () and result.graph.claim_links == ()
    assert result.chunks == ()
    assert all(not entity.support for entity in result.graph.entities)
    assert result.graph.relationships == ()
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
    with pytest.raises(InvestigationChatError, match="Riduci la domanda o aumenta il contesto"):
        InvestigationChatService._conversation_messages(
            (), "Acme?", (chunk,), graph, context_size=512
        )


def test_graph_budget_omission_blocks_positive_text_in_every_source_route():
    case, docs, graph, chunk = scenario()
    positive = "POSITIVE ASSERTION: Acme controls Beta."
    negative = "NEGATIVE ASSERTION: Acme does not control Beta."
    yes = replace(
        graph.claims[0],
        support=(replace(graph.claims[0].support[0], quote=positive + " Detail." * 240),),
    )
    no = replace(
        graph.claims[1],
        support=(replace(graph.claims[1].support[0], quote=negative + " Denial." * 240),),
    )
    brief_support = (replace(yes.support[0], quote=positive),)
    graph = replace(
        graph,
        claims=(yes, no),
        entities=(replace(graph.entities[0], support=brief_support), graph.entities[1]),
        relationships=(replace(graph.relationships[0], support=brief_support, claim_ids=()),),
    )
    affirmative = replace(chunk, text=yes.support[0].quote, original_text=yes.support[0].quote)
    denial = replace(
        chunk,
        document_id=docs[1].document_id,
        document_name=docs[1].original_name,
        page_number=2,
        text=no.support[0].quote,
        original_text=no.support[0].quote,
    )
    independent = replace(
        chunk, page_number=3, text="Independent page remains available.", original_text=None
    )
    budget = budget_context(3000, "", "Acme?", "", ())
    # The positive vector excerpt fits alone: its exclusion must follow the omitted
    # comparison group, rather than merely failing the evidence length limit.
    assert len(InvestigationChatService._evidence_context((affirmative,))) < budget.evidence_budget
    messages = InvestigationChatService._conversation_messages(
        (), "Acme?", (affirmative, denial, independent), graph, context_size=3000
    )
    content = messages[-1]["content"]
    parsed = json.loads(content.split("CURRENT INVESTIGATION GRAPH\n", 1)[1])
    assert parsed["claims"] == [] and parsed["claim_links"] == []
    assert parsed["omitted"]["claims"] == 2
    assert parsed["relationships"] == []
    assert parsed["entities"] and all(not entity["source_support"] for entity in parsed["entities"])
    assert positive not in content and negative not in content
    assert "Independent page remains available." in content


def test_complete_chat_input_including_system_question_status_and_history_fits_budget():
    case, docs, graph, chunk = scenario()
    system = InvestigationChatService._system_prompt(case)
    question = "Who controls Beta? " * 16
    status = "Retrieval was limited; consult both source documents."
    history = tuple(
        ChatMessage(
            str(index),
            case.investigation_id,
            ChatRole.USER if index % 2 == 0 else ChatRole.ASSISTANT,
            f"Earlier message {index}. " + "Context. " * 40,
            datetime.now(UTC),
        )
        for index in range(20)
    )
    messages = InvestigationChatService._conversation_messages(
        history,
        question,
        (chunk,),
        graph,
        context_size=4096,
        retrieval_status=status,
        system_text=system,
    )
    input_chars = (
        len(system)
        + MESSAGE_ENVELOPE_CHARS
        + sum(len(message["content"]) + MESSAGE_ENVELOPE_CHARS for message in messages)
    )
    assert input_chars <= (4096 * 3 // 4) * 3
    assert 0 < len(messages) - 1 < len(history)
    assert [message["content"] for message in messages[:-1]] == [
        message.content for message in history[-(len(messages) - 1) :]
    ]
    assert messages[-1]["content"].startswith("QUESTION\n" + question + "\n\n")
    assert messages[-1]["content"].endswith("RETRIEVAL STATUS\n" + status)


def test_complete_chat_input_rejects_oversized_question_instead_of_truncating_it():
    case, docs, graph, chunk = scenario()
    with pytest.raises(InvestigationChatError, match="Riduci la domanda o aumenta il contesto"):
        InvestigationChatService._conversation_messages(
            (),
            "Who controls Beta? " * 500,
            (chunk,),
            graph,
            context_size=3000,
            system_text=InvestigationChatService._system_prompt(case),
        )


@pytest.mark.parametrize("context_size,question", [(512, "Acme?"), (3000, "Acme? " * 1000)])
def test_stream_rejects_impossible_input_before_indexing_model_calls_or_saving(
    context_size, question
):
    case, docs, graph, chunk = scenario()
    repository = FakeRepository()
    ai = FakeAiNode()
    ai.settings = SimpleNamespace(context_size=context_size)
    ai.embed = Mock()
    ai.stream_chat = Mock()
    service = InvestigationChatService(repository, FakeVectors(), ai, FakeKnowledgeBase())
    service.index_knowledge_base = Mock()

    with pytest.raises(InvestigationChatError, match="Riduci la domanda o aumenta il contesto"):
        tuple(service.stream_answer(case, docs, graph, question))

    service.index_knowledge_base.assert_not_called()
    ai.embed.assert_not_called()
    ai.stream_chat.assert_not_called()
    assert repository.messages == []


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


def test_legacy_entity_and_relationship_support_receive_resolvable_graph_citations():
    case, docs, graph, chunk = scenario()
    identity_source = EvidenceSpan(docs[0].document_id, "Acme is an organization.", 1, True)
    edge_source = EvidenceSpan(docs[1].document_id, "Acme controls Beta.", 2, True)
    graph = replace(
        graph,
        claims=(),
        claim_links=(),
        entities=(replace(graph.entities[0], support=(identity_source,)), graph.entities[1]),
        relationships=(replace(graph.relationships[0], support=(edge_source,), claim_ids=()),),
    )
    context = InvestigationChatService._graph_context(graph)
    parsed = json.loads(context)
    assert parsed["legacy_without_claims"] and parsed["claims"] == []
    entity_source = parsed["entities"][0]["source_support"][0]
    relationship_source = parsed["relationships"][0]["source_support"][0]
    assert entity_source["citation"] == "G1" and relationship_source["citation"] == "G2"
    assert entity_source["quote"] == identity_source.quote
    assert relationship_source["quote"] == edge_source.quote
    labels = InvestigationChatService._source_labels(
        (), context, {doc.document_id: doc.original_name for doc in docs}
    )
    assert labels == ("[G1] report.pdf · page 1", "[G2] denial.pdf · page 2")


@pytest.mark.parametrize(
    ("kind", "review_state"),
    [
        ("candidate_unrelated", "supported"),
        ("unrelated", "unreviewed"),
        ("candidate_contradicts", "unsupported"),
        ("candidate_contradicts", "contradicted"),
        ("candidate_scope_review", "uncertain"),
        ("candidate_semantic_review", "unreviewed"),
        ("candidate_uncertain", "supported"),
    ],
)
def test_review_only_pairs_do_not_swallow_a_real_counterclaim_group(kind, review_state):
    from raven.services.retrieval import omitted_comparison_pages

    _, _, graph, _ = scenario()
    unrelated = tuple(
        replace(
            graph.claims[0],
            claim_id=f"noise-{number}",
            subject_entity_id="other",
            object_entity_id="other",
            attribution="Unrelated discussion " * 100,
            support=(EvidenceSpan("other-document", "Unrelated discussion.", number + 1, True),),
        )
        for number in range(100)
    )
    review_pairs = tuple(
        ClaimLink(
            f"review-{number}",
            "yes",
            claim.claim_id,
            kind,
            "Candidate retrieved for review",
            review_state=review_state,
            review_rationale="The pair does not establish a usable comparison.",
        )
        for number, claim in enumerate(unrelated)
    )
    graph = replace(
        graph,
        claims=(*graph.claims, *unrelated),
        claim_links=(*graph.claim_links, *review_pairs),
        entities=(*graph.entities, GraphEntity("other", "ORGANIZATION", "Other")),
    )
    selected, _ = HybridInvestigationRetriever._select_graph(graph, ("acme",), (), None, None)
    assert {c.claim_id for c in selected.claims} == {"yes", "no"}
    context = json.loads(InvestigationChatService._graph_context(selected, max_chars=5000))
    assert {c["id"] for c in context["claims"]} == {"yes", "no"}
    assert [link["id"] for link in context["claim_links"]] == ["opposition"]
    # Neither retrieval nor serialization may mutate the persisted review record.
    assert len(graph.claims) == 102 and len(graph.claim_links) == 101
    assert omitted_comparison_pages(graph, {"yes", "no"}) == set()
    direct = json.loads(InvestigationChatService._graph_context(graph, max_chars=5000))
    assert {"yes", "no"} <= {c["id"] for c in direct["claims"]}
    assert direct["review_only_comparisons_omitted"] == 100
