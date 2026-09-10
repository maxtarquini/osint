"""Single-document indexing preserves neighboring vectors and browses stored page catalogs."""

from dataclasses import asdict, replace
from datetime import UTC, datetime
from threading import Event

import pytest
from test_app import FakeChat, FakeInfrastructure, FakeInvestigations, make_app
from test_chat import (
    FakeAiNode,
    FakeKnowledgeBase,
    FakeRepository,
    FakeVectors,
    _document,
    _investigation,
)
from textual.widgets import Button, DataTable, LoadingIndicator, TabbedContent, TextArea

from raven.exceptions import InvestigationChatCancelledError, InvestigationChatError
from raven.models import (
    AnalysisLanguage,
    EvidenceIngestionState,
    InvestigationDraft,
    RagIndexProgress,
)
from raven.models.catalog import CatalogPage, DocumentCatalog
from raven.repositories.mongodb import MongoRepository
from raven.services.chat import InvestigationChatService
from raven.tui.screens.document_catalog import DocumentCatalogScreen
from raven.tui.widgets.evidence import EvidenceRow


def saved_catalog(case_id, document_id):
    pages = (
        CatalogPage(
            1,
            "hash1",
            "Identità della rete",
            "Organizzazione descritta dalla fonte.",
            "IDENTITY",
            topics=("rete",),
            entities=(("Rete RX41", "ORGANIZATION"),),
            quotes=("La rete è fittizia.",),
            confidence=0.9,
            state="ready",
        ),
        CatalogPage(
            2,
            "hash2",
            "Smentita del trasferimento",
            "La fonte nega il trasferimento.",
            "NARRATIVE",
            topics=("smentita",),
            quotes=("Nessun trasferimento di 240 euro.",),
            confidence=0.8,
            state="ready",
        ),
    )
    return DocumentCatalog(
        case_id,
        document_id,
        "generation-current",
        "GENERAL_OSINT",
        "dictionary-hash",
        ("1.0.0",),
        "model",
        "original",
        "page",
        "ready",
        2,
        2,
        0,
        "Riepilogo salvato: confronto delle fonti.",
        ("IDENTITY: 1", "NARRATIVE: 1"),
        ("rete", "smentita"),
        datetime.now(UTC),
        pages=pages,
        summary_state="ready",
    )


def test_force_reindex_touches_only_target_even_if_all_documents_are_indexed():
    case = replace(_investigation(), analysis_language=AnalysisLanguage.ORIGINAL)
    target = _document(case.investigation_id)
    vectors = FakeVectors()
    signature = InvestigationChatService._index_signature(target, "original")
    vectors.manifest = {
        target.document_id: signature,
        "other": "other-signature",
        "third": "third-signature",
    }
    repository = FakeRepository()
    service = InvestigationChatService(repository, vectors, FakeAiNode(), FakeKnowledgeBase())
    assert service.reindex_document(case, target) == 1
    assert [document.document_id for document, chunks in vectors.upserts] == [target.document_id]
    assert vectors.removed == []
    assert vectors.manifest["other"] == "other-signature"
    assert vectors.manifest["third"] == "third-signature"
    assert all(document_id == target.document_id for document_id, state in repository.states)
    with pytest.raises(InvestigationChatError, match="belong"):
        service.reindex_document(case, replace(target, investigation_id="other-case"))
    assert len(vectors.upserts) == 1


def test_cancel_or_model_failure_leaves_all_old_vectors_before_upsert():
    case = replace(_investigation(), analysis_language=AnalysisLanguage.ORIGINAL)
    target = _document(case.investigation_id)
    vectors = FakeVectors()
    vectors.manifest = {target.document_id: "old", "other": "other-signature"}
    stopped = Event()

    class CancellingNode(FakeAiNode):
        def embed(self, texts):
            stopped.set()
            return super().embed(texts)

    service = InvestigationChatService(
        FakeRepository(), vectors, CancellingNode(), FakeKnowledgeBase()
    )
    with pytest.raises(InvestigationChatCancelledError):
        service.reindex_document(case, target, cancelled=stopped.is_set)
    assert vectors.upserts == [] and vectors.removed == []
    assert vectors.manifest == {target.document_id: "old", "other": "other-signature"}


class Cursor(list):
    def sort(self, name, direction):
        return Cursor(sorted(self, key=lambda record: record[name]))


class Collection:
    def __init__(self, records):
        self.records = records

    def find(self, query):
        return Cursor(
            record
            for record in self.records
            if all(record.get(key) == value for key, value in query.items())
        )

    def find_one(self, query):
        return next(iter(self.find(query)), None)


def test_reader_isolates_case_document_generation_and_normalizes_legacy_failures():
    catalog = saved_catalog("case", "doc")
    payload = asdict(catalog)
    payload.pop("pages")
    payload["future_metadata"] = "ignored"
    records = [
        dict(asdict(page), investigation_id="case", document_id="doc", signature=catalog.signature)
        for page in catalog.pages
    ]
    records[1].update(
        state="review",
        category="EVIDENCE_ONLY",
        title="Page needs review",
        error="Invalid type",
        summary="",
        quotes=[],
    )
    # Earlier catalog generations predate optional timeline/reference fields.
    for field in ("dates", "places", "references"):
        records[1].pop(field)
    records.append({**records[0], "signature": "old", "title": "Old version"})
    records.append({**records[0], "investigation_id": "foreign", "title": "Foreign case"})
    repository = MongoRepository()
    repository._database = {
        "document_catalogs": Collection([payload]),
        "catalog_pages": Collection(records),
    }
    loaded = repository.load_catalog("case", "doc")
    assert loaded.summary == catalog.summary
    assert len(loaded.pages) == 2
    assert loaded.failed_count == 1 and loaded.review_count == 0
    assert loaded.pages[1].category == "" and loaded.pages[1].state == "failed"
    assert repository.load_catalog("foreign", "doc") is None
    assert repository.load_catalog("case", "other") is None


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.parametrize("size", [(80, 24), (150, 42)])
async def test_row_catalog_navigation_and_single_document_reindex(tmp_path, size):
    investigations = FakeInvestigations()
    case = investigations.create(InvestigationDraft(name="Case", questions=("Who?",)))
    first = replace(
        investigations.add_evidence(case.investigation_id, tmp_path / "first.pdf"),
        ingestion_state=EvidenceIngestionState.FAILED,
    )
    second = replace(
        first,
        document_id="second",
        original_name="second.pdf",
        ingestion_state=EvidenceIngestionState.READY,
    )
    third = replace(
        first,
        document_id="third",
        original_name="third.pdf",
        ingestion_state=EvidenceIngestionState.PENDING,
    )
    case = replace(case, evidence_documents=(first, second, third))

    class SingleChat(FakeChat):
        def reindex_document(self, investigation, document, cancelled=None, progress=None):
            return self.index_knowledge_base(investigation, (document,), cancelled, progress)

    chat = SingleChat()
    app = make_app(
        tmp_path,
        infrastructure=FakeInfrastructure(),
        investigations=investigations,
        investigation_chat=chat,
    )
    app.settings = replace(app.settings, ai=replace(app.settings.ai, embedding_model="test"))
    calls = []

    def load_catalog(investigation, document):
        calls.append((investigation.investigation_id, document.document_id))
        return saved_catalog(investigation.investigation_id, document.document_id)

    app.load_evidence_catalog = load_catalog
    async with app.run_test(size=size) as pilot:
        app.open_investigation(case)
        await settle(app, pilot)
        screen = app.screen
        row = screen.query_one(f"#evidence-{first.document_id}", EvidenceRow)
        row.query_one(".open-evidence-catalog", Button).focus()
        await pilot.pause()
        button = row.query_one(".open-evidence-catalog")
        assert 0 <= button.region.x < button.region.right <= size[0]
        assert button.region.height == 3
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, DocumentCatalogScreen)
        assert calls == [(case.investigation_id, first.document_id)]
        assert "confronto" in app.screen.query_one("#saved-catalog-summary", TextArea).text
        app.screen.query_one(TabbedContent).active = "saved-catalog-pages"
        await pilot.pause()
        table = app.screen.query_one("#saved-catalog-table", DataTable)
        table.focus()
        await pilot.press("down", "enter")
        assert "240 euro" in app.screen.query_one("#saved-catalog-page", TextArea).text
        assert app.screen.query_one("#saved-catalog-page").region.height >= 3
        await pilot.press("/")
        await pilot.press(*"identità")
        await pilot.pause()
        assert table.row_count == 1
        assert "Identità" in app.screen.query_one("#saved-catalog-page", TextArea).text
        await pilot.press("escape")
        assert app.screen is screen
        row.query_one(".reindex-evidence", Button).focus()
        await pilot.press("enter")
        await settle(app, pilot)
        assert chat.indexed_documents == [first.document_id]
        assert [document.ingestion_state for document in screen.documents] == [
            EvidenceIngestionState.READY,
            EvidenceIngestionState.READY,
            EvidenceIngestionState.PENDING,
        ]
        assert not row.query_one(".reindex-evidence", Button).disabled


@pytest.mark.parametrize("failure", ["cancel", "model"])
def test_failed_or_cancelled_reindex_updates_only_target_state(failure):
    from raven.exceptions import InvestigationCancelledError
    from raven.exceptions.graph import GraphAgentRequestError

    case = _investigation()
    target = _document(case.investigation_id)
    vectors = FakeVectors()
    vectors.manifest = {target.document_id: "old", "other": "other-signature"}
    repository = FakeRepository()

    class Source(FakeKnowledgeBase):
        def extract_text(self, document, cancelled=None):
            if failure == "cancel":
                raise InvestigationCancelledError("Cancelled during extraction")
            return super().extract_text(document, cancelled)

    class Model(FakeAiNode):
        def chat(self, system, user, **kwargs):
            assert kwargs["max_output_tokens"] == 512
            assert kwargs["timeout_seconds"] == 60
            assert kwargs["thinking"] == "low"
            raise GraphAgentRequestError("Timed out after 60 seconds", "timeout")

    service = InvestigationChatService(repository, vectors, Model(), Source())
    error_type = InvestigationChatCancelledError if failure == "cancel" else InvestigationChatError
    with pytest.raises(error_type):
        service.reindex_document(case, target)
    expected = (
        EvidenceIngestionState.PENDING if failure == "cancel" else EvidenceIngestionState.FAILED
    )
    assert repository.states[-1] == (target.document_id, expected)
    assert all(identity == target.document_id for identity, state in repository.states)
    assert vectors.upserts == vectors.removed == []
    assert vectors.manifest == {target.document_id: "old", "other": "other-signature"}


async def test_missing_catalog_and_read_error_are_visible(tmp_path):
    app = make_app(tmp_path, infrastructure=FakeInfrastructure())
    case = _investigation()
    document = _document(case.investigation_id)
    app.load_evidence_catalog = lambda *_: None
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(DocumentCatalogScreen(case, document))
        await settle(app, pilot)
        assert "Nessun catalogo" in app.screen.query_one("#saved-catalog-status").render().plain
        assert "distinta" in app.screen.query_one("#saved-catalog-summary", TextArea).text
        app.load_evidence_catalog = lambda *_: (_ for _ in ()).throw(RuntimeError("private detail"))
        await pilot.click("#refresh-saved-catalog")
        await settle(app, pilot)
        status = app.screen.query_one("#saved-catalog-status").render().plain
        assert "Impossibile" in status
        assert "private detail" not in status


async def test_missing_catalog_can_be_generated_from_reader(tmp_path):
    case = _investigation()
    document = _document(case.investigation_id)

    class CatalogRunner:
        def __init__(self):
            self.catalog = None
            self.calls = []

        def load(self, investigation, selected, *, with_pages=True):
            return self.catalog

        def catalog_document(
            self, investigation, selected, cancelled=None, progress=None, *, force=False
        ):
            self.calls.append((selected.document_id, force))
            self.catalog = saved_catalog(investigation.investigation_id, selected.document_id)
            progress(
                RagIndexProgress(
                    selected.document_id,
                    selected.original_name,
                    EvidenceIngestionState.PROCESSING,
                    2,
                    2,
                    "Catalogo completato",
                )
            )
            return self.catalog

    runner = CatalogRunner()
    app = make_app(tmp_path, infrastructure=FakeInfrastructure(), page_catalog=runner)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(DocumentCatalogScreen(case, document))
        await settle(app, pilot)
        assert "Nessun catalogo" in app.screen.query_one("#saved-catalog-status").render().plain
        await pilot.click("#generate-saved-catalog")
        await settle(app, pilot)
        assert runner.calls == [(document.document_id, False)]
        assert "2/2 pagine" in app.screen.query_one("#saved-catalog-status").render().plain
        assert app.screen.query_one("#generate-saved-catalog", Button).label.plain == (
            "Rigenera catalogo"
        )


@pytest.mark.parametrize("outcome", ["ready", "failed", "cancelled"])
async def test_indexing_animation_tracks_worker_lifecycle(tmp_path, outcome):
    release = Event()
    case = _investigation()
    document = _document(case.investigation_id)
    case = replace(case, evidence_documents=(document,))

    class WaitingChat(FakeChat):
        def index_knowledge_base(self, investigation, documents, cancelled=None, progress=None):
            progress(
                RagIndexProgress(
                    document.document_id,
                    document.original_name,
                    EvidenceIngestionState.PROCESSING,
                    0,
                    1,
                )
            )
            assert release.wait(10)
            if cancelled():
                raise InvestigationChatCancelledError("Cancelled")
            if outcome == "failed":
                raise InvestigationChatError("Model unavailable")
            return 1

        def reindex_document(self, investigation, document, cancelled=None, progress=None):
            return self.index_knowledge_base(investigation, (document,), cancelled, progress)

    app = make_app(tmp_path, investigation_chat=WaitingChat())
    app.settings = replace(app.settings, ai=replace(app.settings.ai, embedding_model="test"))
    async with app.run_test(size=(80, 24)) as pilot:
        app.open_investigation(case)
        await settle(app, pilot)
        screen = app.screen
        activity = screen.query_one("#rag-activity", LoadingIndicator)
        assert activity.has_class("hidden")
        try:
            screen._start_chat_index(document=None if outcome == "ready" else document)
            await pilot.pause()
            assert not activity.has_class("hidden")
            assert activity.region.width == 11
            assert activity.region.height == 2
            status = screen.query_one("#evidence-operation-status")
            assert document.original_name in status.render().plain
            assert status.region.right <= 80
            if outcome == "cancelled":
                screen._cancel_rag_index()
                assert not activity.has_class("hidden")
        finally:
            release.set()
        await settle(app, pilot)
        assert activity.has_class("hidden")
        assert outcome in screen.query_one("#evidence-operation-status").render().plain
