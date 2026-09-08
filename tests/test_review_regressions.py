"""Fault and provenance regressions from the application-wide review."""

from dataclasses import replace
from datetime import UTC, datetime
from threading import Event, Thread
from types import SimpleNamespace
from uuid import uuid4
from xml.etree import ElementTree

import pytest
from test_chat import (
    FakeAiNode,
    FakeKnowledgeBase,
    FakeRepository,
    FakeVectors,
    _document,
    _investigation,
)
from test_graph_analysis import GraphRepository, GraphStore, ScriptedNode, investigation

from raven.agents import EntityExtractionAgent, RelationshipExtractionAgent
from raven.config import AiNodeSettings, RavenSettings
from raven.exceptions import (
    GraphAgentError,
    GraphAnalysisCancelledError,
    GraphPersistenceError,
    InvestigationCancelledError,
)
from raven.graph.extraction import EvidenceGraphExtractor, consolidate_graph
from raven.graph.grounding import ground_items
from raven.models import (
    BackgroundJob,
    EvidenceSpan,
    GraphEntity,
    GraphItemStatus,
    InvestigationGraph,
    JobKind,
    JobStatus,
    RetrievedEvidenceChunk,
)
from raven.models.graph_filter import GraphFilters
from raven.repositories import KnowledgeBaseStore
from raven.repositories.qdrant import QdrantRepository
from raven.services.chat import InvestigationChatService
from raven.services.graph_analysis import GraphAnalysisService
from raven.services.graph_export import GraphExportService
from raven.services.job_persistence import BackgroundJobWriter
from raven.services.operations import InvestigationOperations
from raven.tui.design import raven_theme


@pytest.mark.parametrize(
    "payload", ["{}", '{"entities":{}}', '{"entities":[null]}', '{"entities":[{}]}']
)
def test_invalid_root_is_not_a_successful_empty_extraction(payload) -> None:
    node = SimpleNamespace(chat=lambda *args, **kwargs: payload)
    with pytest.raises(GraphAgentError):
        EntityExtractionAgent(node).extract(
            "case",
            "doc",
            "Mario Rossi",
            EvidenceGraphExtractor(ScriptedNode()).resolve_vocabulary(),
        )


def test_conflicting_passports_block_even_an_agent_link() -> None:
    class LinkingNode(ScriptedNode):
        def chat(self, *args, **kwargs):
            pytest.fail("Conflicting identifiers must not reach the resolution agent")

    first = GraphEntity("a", "PERSON", "Mario Rossi", external_identifiers=(("passport", "A1"),))
    second = replace(first, entity_id="b", external_identifiers=(("passport", "B2"),))
    resolved, _ = EvidenceGraphExtractor(LinkingNode()).resolve_against(
        "case", (second,), (), (first,)
    )
    assert resolved[0].entity_id == "b"
    merged, _ = consolidate_graph(((first,), resolved), ())
    assert len(merged) == 2


def test_linked_identity_stays_unique_when_identifiers_are_enriched() -> None:
    first = GraphEntity("a", "PERSON", "Mario Rossi", external_identifiers=(("passport", "A1"),))
    enriched = replace(first, external_identifiers=(*first.external_identifiers, ("tax_id", "ABC")))
    entities, _ = consolidate_graph(((first,), (enriched,)), ())
    assert len(entities) == 1
    assert ("tax_id", "ABC") in entities[0].external_identifiers


def test_grounding_checks_original_page_and_rejects_wrong_page_or_fabrication() -> None:
    item = GraphEntity(
        "a",
        "PERSON",
        "Mario",
        support=(
            EvidenceSpan("doc", "Mario did not work for Acme", 2),
            EvidenceSpan("doc", "Mario did not work for Acme", 1),
            EvidenceSpan("doc", "Mario owns Acme", 2),
        ),
    )
    result = ground_items((item,), "doc", ("Cover", "Mario did not work for Acme."))[0]
    assert [span.verified_original for span in result.support] == [True, False, False]


@pytest.mark.parametrize("assertion", ["negated", "uncertain"])
def test_non_asserted_relationships_do_not_become_positive_edges(assertion) -> None:
    import json

    response = {
        "relationships": [
            {
                "source_entity_id": "a",
                "target_entity_id": "b",
                "relationship_type": "WORKS_FOR",
                "assertion": assertion,
                "confidence": 0.99,
            }
        ]
    }
    node = SimpleNamespace(chat=lambda *args, **kwargs: json.dumps(response))
    entities = (GraphEntity("a", "PERSON", "Mario"), GraphEntity("b", "ORGANIZATION", "Acme"))
    assert (
        RelationshipExtractionAgent(node).extract(
            "case", "doc", "Mario did not work for Acme.", entities
        )
        == ()
    )


def test_projection_retry_uses_latest_checkpoint_and_acknowledges_only_on_success(tmp_path):
    class Repository(GraphRepository):
        pending = True

        def pending_graph_investigations(self):
            return ("case",) if self.pending else ()

        def mark_graph_projected(self, investigation_id, run_id):
            assert run_id == "latest"

        def acknowledge_graph_projections(self, investigation_id):
            self.pending = False

    class Store(GraphStore):
        offline = True

        def save_graph_snapshot(self, graph):
            if self.offline:
                raise GraphPersistenceError("offline")
            super().save_graph_snapshot(graph)

    repository, store = Repository(), Store()
    repository.graph = InvestigationGraph("case", "latest", (), (), datetime.now(UTC))
    service = GraphAnalysisService(repository, store, ScriptedNode(), KnowledgeBaseStore(tmp_path))
    with pytest.raises(GraphPersistenceError):
        service.reconcile_projections()
    assert repository.pending
    store.offline = False
    assert service.reconcile_projections() == 1
    assert store.graph.run_id == "latest" and not repository.pending


def test_each_chunk_on_same_page_retains_a_distinct_citation() -> None:
    chunks = tuple(
        RetrievedEvidenceChunk("doc", "a.pdf", i, f"Passage {i}", 0.9, 2, 2) for i in range(2)
    )
    labels = InvestigationChatService._source_labels(chunks)
    citations = InvestigationChatService._citations(chunks)
    assert len(labels) == len(citations) == 2
    assert labels[0].startswith("[E1]") and labels[1].startswith("[E2]")
    assert citations[0].text != citations[1].text
    assert citations[0].page_number == citations[1].page_number == 2


def test_model_or_ocr_change_reindexes_even_with_same_dimensions() -> None:
    ai = FakeAiNode()
    ai.settings = AiNodeSettings(model="chat", embedding_model="embed-a")
    kb = FakeKnowledgeBase()
    kb.ocr_fingerprint = lambda doc: "ocr-v1"
    vectors = FakeVectors()
    service = InvestigationChatService(FakeRepository(), vectors, ai, kb)
    case = _investigation()
    document = _document(case.investigation_id)
    service.index_knowledge_base(case, (document,))
    service.index_knowledge_base(case, (document,))
    assert len(vectors.upserts) == 1
    ai.settings = replace(ai.settings, embedding_model="embed-b")
    service.index_knowledge_base(case, (document,))
    kb.ocr_fingerprint = lambda doc: "ocr-v2"
    service.index_knowledge_base(case, (document,))
    assert len(vectors.upserts) == 3


def test_cancel_during_last_model_call_prevents_graph_publication(tmp_path) -> None:
    cancelled = Event()

    class CancellingNode(ScriptedNode):
        def chat(self, system, user, **kwargs):
            response = super().chat(system, user, **kwargs)
            if "relationship extraction" in system:
                cancelled.set()
            return response

    case_id = str(uuid4())
    source = tmp_path / "doc.md"
    source.write_text("Mario Rossi works for Alfa S.p.A.")
    kb = KnowledgeBaseStore(tmp_path / "kb")
    document = kb.add(case_id, source)
    repository, store = GraphRepository(), GraphStore()
    service = GraphAnalysisService(repository, store, CancellingNode(), kb)
    with pytest.raises(GraphAnalysisCancelledError):
        service.analyze(investigation(case_id), (document,), cancelled=cancelled.is_set)
    assert repository.graph is None and store.graph is None
    assert repository.runs[-1].status.value == "cancelled"


def test_evidence_root_is_pinned_across_reconfiguration_and_restart(tmp_path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("Original source")
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    kb = KnowledgeBaseStore(old_root)
    document = kb.add(str(uuid4()), source)
    kb.configure_root(new_root)
    restarted = KnowledgeBaseStore(new_root)
    assert restarted.extract_text(document) == "Original source"
    assert kb.extract_text(document) == "Original source"


def test_partial_vector_manifest_is_not_ready() -> None:
    chunks = [{"chunk_index": i, "chunk_count": 3, "index_signature": "v3"} for i in range(3)]
    assert QdrantRepository._complete_manifest(chunks)
    assert not QdrantRepository._complete_manifest(chunks[:2])
    chunks[2]["index_signature"] = "old-model"
    assert not QdrantRepository._complete_manifest(chunks)


def test_job_persistence_does_not_block_submit_and_reports_failure() -> None:
    started, release = Event(), Event()

    class Recorder:
        def save_background_job(self, job):
            started.set()
            assert release.wait(2)
            raise RuntimeError("offline")

    writer = BackgroundJobWriter(Recorder())
    now = datetime.now(UTC)
    job = BackgroundJob(
        "job", "case", JobKind.GRAPH, JobStatus.RUNNING, "extract", 0, 1, "Working", now, now
    )
    try:
        writer.submit(job)
        assert started.wait(1)
        assert not release.is_set()
        writer.submit(replace(job, completed=1))
        release.set()
        assert not writer.flush()
    finally:
        release.set()
        writer.close()


def test_mutation_invalidates_active_work_before_acquiring_its_lock() -> None:
    operations = InvestigationOperations()
    entered = Event()
    finished = Event()

    def mutate():
        entered.set()
        with operations.mutation("case"):
            finished.set()

    with operations.operation("case") as cancelled:
        thread = Thread(target=mutate)
        thread.start()
        assert entered.wait(1)
        assert operations._case("case").invalidated.wait(1)
        assert cancelled() and not finished.is_set()
    thread.join(1)
    assert finished.is_set()
    with operations.operation("case") as cancelled:
        assert not cancelled()


def test_upload_can_cancel_while_waiting_for_active_analysis_lock() -> None:
    operations = InvestigationOperations()
    cancel_upload, finished = Event(), Event()
    errors = []

    def upload():
        try:
            with operations.mutation("case", cancel_upload.is_set):
                errors.append("Unexpected write after cancellation")
        except InvestigationCancelledError:
            finished.set()

    with operations.operation("case") as analysis_cancelled:
        thread = Thread(target=upload)
        thread.start()
        try:
            assert operations._case("case").invalidated.wait(1)
            cancel_upload.set()
            # Cancellation returns before the active analysis releases its lock.
            assert finished.wait(1)
            assert analysis_cancelled()
        finally:
            cancel_upload.set()
    thread.join(1)
    assert not thread.is_alive()
    assert not errors
    with operations.operation("case") as cancelled:
        assert not cancelled()
    with operations.mutation("case"):
        pass


def test_stale_review_preserves_previous_decision_and_audit(tmp_path) -> None:
    now = datetime.now(UTC)
    entities = (GraphEntity("a", "PERSON", "A"), GraphEntity("b", "PERSON", "B"))
    original = InvestigationGraph("case", "run", entities, (), now)
    repository = GraphRepository()
    repository.graph = original
    service = GraphAnalysisService(
        repository, GraphStore(), ScriptedNode(), KnowledgeBaseStore(tmp_path)
    )
    service.review_item(original, "a", GraphItemStatus.VERIFIED)
    result = service.review_item(original, "b", GraphItemStatus.REJECTED)
    assert result.entities[0].status is GraphItemStatus.VERIFIED
    assert result.entities[1].status is GraphItemStatus.REJECTED
    assert len(result.review_history) == 2


def test_graphml_declares_every_data_key_and_has_valid_endpoints(tmp_path) -> None:
    graph = InvestigationGraph(
        "case", "run", (GraphEntity("a", "PERSON", "A & B"),), (), datetime.now(UTC)
    )
    path = tmp_path / "graph.graphml"
    GraphExportService._write_graphml(path, graph)
    root = ElementTree.parse(path).getroot()
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    declared = {key.attrib["id"] for key in root.findall("g:key", ns)}
    assert all(data.attrib["key"] in declared for data in root.findall(".//g:data", ns))


@pytest.mark.parametrize("palette", ["sapphire", "jade", "amber"])
@pytest.mark.parametrize("appearance", ["dark", "light"])
def test_theme_configuration_round_trips(palette, appearance) -> None:
    settings = RavenSettings(interface_density="compact").validated()
    legacy = settings.to_public_dict()
    legacy["interface"]["palette"] = palette
    legacy["interface"]["appearance"] = appearance
    restored = RavenSettings.from_dict(legacy)
    assert restored.interface_density == "compact"
    assert "palette" not in restored.to_public_dict()["interface"]
    assert "appearance" not in restored.to_public_dict()["interface"]
    assert raven_theme().name == "raven"


def test_graph_filters_combine_status_source_kind_and_confidence() -> None:
    item = GraphEntity(
        "a", "PERSON", "A", evidence_ids=("doc",), confidence=0.95, status=GraphItemStatus.VERIFIED
    )
    filters = GraphFilters("verified", "entity", "doc", 90)
    assert filters.matches(item)
    assert not filters.matches(replace(item, status=GraphItemStatus.REJECTED))
    assert not filters.matches(replace(item, confidence=0.89))
    assert not filters.matches(replace(item, evidence_ids=("other",)))
