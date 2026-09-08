"""RAG availability is verified independently of graph extraction outcomes."""

from dataclasses import replace

import pytest
from test_app import FakeChat
from test_chat import (
    FakeAiNode,
    FakeKnowledgeBase,
    FakeRepository,
    FakeVectors,
    _document,
    _investigation,
)
from test_graph_activity_workspace import _app_with_previous_graph
from textual.widgets import Static, TabbedContent

from raven.exceptions import InvestigationChatError
from raven.models import EvidenceIngestionState as State
from raven.models import RagIndexProgress
from raven.services.chat import InvestigationChatService
from raven.tui.widgets.evidence import EvidenceRow


def test_manifest_overrides_historical_graph_failure_without_writes():
    case = _investigation()
    current = replace(_document(case.investigation_id), ingestion_state=State.FAILED)
    old = replace(current, document_id="old")
    missing = replace(current, document_id="missing", ingestion_state=State.READY)
    vectors = FakeVectors()
    vectors.manifest = {
        current.document_id: InvestigationChatService._index_signature(
            current, case.analysis_language.value
        ),
        old.document_id: old.sha256,
        "foreign-document": "ignored",
    }
    repository = FakeRepository()
    service = InvestigationChatService(repository, vectors, FakeAiNode(), FakeKnowledgeBase())
    assert service.index_states(case, (current, old, missing)) == {
        current.document_id: State.READY,
        old.document_id: State.OUTDATED,
        missing.document_id: State.PENDING,
    }
    assert not repository.states and not vectors.upserts and not vectors.removed
    with pytest.raises(InvestigationChatError, match="belong"):
        service.index_states(case, (replace(current, investigation_id="foreign"),))


@pytest.mark.parametrize("size", [(80, 24), (160, 48)])
async def test_graph_failure_never_changes_verified_index_and_late_reads_are_ignored(
    tmp_path, size
):
    app, case, graph_result = _app_with_previous_graph(tmp_path)
    document = case.evidence_documents[0]
    case = replace(case, evidence_documents=(replace(document, ingestion_state=State.FAILED),))

    class IndexedChat(FakeChat):
        def index_states(self, investigation, documents):
            return {doc.document_id: State.READY for doc in documents}

    app.investigation_chat = IndexedChat()
    async with app.run_test(size=size) as pilot:
        app.open_investigation(case)
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-evidence-tab"
        await pilot.pause()
        row = screen.query_one(EvidenceRow)
        status = row.query_one(".evidence-state", Static)
        assert status.render().plain == "Indexed"
        screen._graph_succeeded(
            replace(graph_result, evidence_states=((document.document_id, State.FAILED),))
        )
        assert screen.documents[0].ingestion_state is State.READY
        assert status.render().plain == "Indexed"
        revision = screen._rag_state_revision
        screen._show_rag_index_progress(
            RagIndexProgress(document.document_id, document.original_name, State.PROCESSING, 0, 1)
        )
        screen._show_rag_states(revision, {document.document_id: State.READY})
        assert status.render().plain == "Indexing…"
        screen._show_rag_states(screen._rag_state_revision, {document.document_id: State.OUTDATED})
        await pilot.pause()
        assert status.render().plain == "Da aggiornare"
        assert status.region.width >= len("Da aggiornare")


async def test_unreachable_qdrant_is_unverified_not_index_failed(tmp_path):
    app, case, _ = _app_with_previous_graph(tmp_path)

    class OfflineChat(FakeChat):
        def index_states(self, investigation, documents):
            raise ConnectionError("unavailable")

    app.investigation_chat = OfflineChat()
    async with app.run_test(size=(80, 24)) as pilot:
        app.open_investigation(case)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.screen.documents[0].ingestion_state is State.UNVERIFIED
        assert (
            app.screen.query_one(EvidenceRow).query_one(".evidence-state", Static).render().plain
            == "Non verificato"
        )
