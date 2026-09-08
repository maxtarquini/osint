"""Cancellation stops resolution and publication before either graph store changes."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_graph_analysis import GraphRepository, GraphStore, investigation

from raven.ai import SharedAiNode
from raven.config import AiThinkingLevel
from raven.exceptions import (
    GraphAnalysisCancelledError,
    InvestigationCancelledError,
    InvestigationChatCancelledError,
)
from raven.graph.extraction import EvidenceGraphExtractor
from raven.models import EvidenceIngestionState, GraphEntity, GraphRunStatus, InvestigationGraph
from raven.repositories import KnowledgeBaseStore
from raven.services import GraphAnalysisService


@pytest.mark.parametrize("stage", ["extraction", "last_document_resolution", "consolidation"])
def test_cancel_at_final_stage_preserves_both_existing_snapshots(tmp_path, stage):
    case = investigation(str(uuid4()))
    source = tmp_path / "source.md"
    source.write_text("Contact alpha@example.org")
    knowledge_base = KnowledgeBaseStore(tmp_path / "kb")
    document = knowledge_base.add(case.investigation_id, source)
    repository, graph_store = GraphRepository(), GraphStore()
    repository.states[document.document_id] = EvidenceIngestionState.READY
    old_graph = InvestigationGraph(case.investigation_id, "old-run", (), (), datetime.now(UTC))
    repository.graph = graph_store.graph = old_graph
    service = GraphAnalysisService(repository, graph_store, SharedAiNode(), knowledge_base)
    state = {"cancelled": False}
    original_resolve = service._extractor.resolve_against

    def resolve(*args, **kwargs):
        assert callable(kwargs["cancelled"])
        result = original_resolve(*args, **kwargs)
        if stage == "last_document_resolution":
            state["cancelled"] = True
        return result

    def progress(update):
        if stage == "consolidation" and update.stage is GraphRunStatus.CONSOLIDATING:
            state["cancelled"] = True

    service._extractor.resolve_against = resolve
    if stage == "extraction":

        def stopped_extract(*args, **kwargs):
            raise InvestigationCancelledError("Source read cancelled")

        knowledge_base.extract_pages = stopped_extract

    with pytest.raises(GraphAnalysisCancelledError):
        service.analyze(case, (document,), cancelled=lambda: state["cancelled"], progress=progress)

    assert repository.graph is old_graph
    assert graph_store.graph is old_graph
    assert repository.runs[-1].status is GraphRunStatus.CANCELLED
    assert repository.states[document.document_id] is EvidenceIngestionState.READY


def test_identity_model_receives_cancellation_and_bounded_request_options():
    state = {"cancelled": False, "calls": 0}

    def cancelled():
        return state["cancelled"]

    def chat(system, user, **options):
        state["calls"] += 1
        assert options["cancelled"] is cancelled
        assert options["timeout_seconds"] == 60
        assert options["max_output_tokens"] == 2048
        assert options["thinking"] is AiThinkingLevel.LOW
        state["cancelled"] = True
        raise InvestigationChatCancelledError("cancelled")

    extractor = EvidenceGraphExtractor(SimpleNamespace(available=True, chat=chat))
    first = GraphEntity(
        "one", "PERSON", "Mario Rossi", external_identifiers=(("email", "mario@example.org"),)
    )
    second = GraphEntity(
        "two", "PERSON", "Mario Rossi", external_identifiers=first.external_identifiers
    )

    with pytest.raises(InvestigationChatCancelledError):
        extractor.resolve_against("case", (second,), (), (first,), cancelled=cancelled)

    assert state["calls"] == 1


def test_resolution_rechecks_cancellation_between_mentions():
    extractor = EvidenceGraphExtractor(SimpleNamespace(available=False))
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks == 2

    with pytest.raises(GraphAnalysisCancelledError):
        extractor.resolve_against(
            "case",
            (GraphEntity("one", "PERSON", "Mario"), GraphEntity("two", "PERSON", "Ada")),
            (),
            (),
            cancelled=cancelled,
        )

    assert checks == 2


def test_publication_finishes_both_stores_if_cancel_arrives_after_first_write(tmp_path):
    case = investigation(str(uuid4()))
    source = tmp_path / "source.md"
    source.write_text("Contact alpha@example.org")
    knowledge_base = KnowledgeBaseStore(tmp_path / "kb")
    document = knowledge_base.add(case.investigation_id, source)
    state = {"cancelled": False}

    class CancellingRepository(GraphRepository):
        def save_graph_snapshot(self, graph):
            super().save_graph_snapshot(graph)
            state["cancelled"] = True

    repository, graph_store = CancellingRepository(), GraphStore()
    service = GraphAnalysisService(repository, graph_store, SharedAiNode(), knowledge_base)

    result = service.analyze(case, (document,), cancelled=lambda: state["cancelled"])

    assert state["cancelled"]
    assert repository.graph == graph_store.graph == result.graph
    assert result.run.status is GraphRunStatus.COMPLETED_WITH_WARNINGS
    assert result.graph.pages[0].state == "observables_only"
