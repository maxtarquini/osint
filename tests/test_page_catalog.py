"""Catalog coverage, source validation, persistence, freshness and UI navigation."""

import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from test_app import FakeInfrastructure, FakeInvestigations, make_app
from textual.widgets import DataTable, Input, Select, TabbedContent, TextArea

from raven.agents.page_catalog import PageCatalogAgent
from raven.app import RavenApp
from raven.config import ConfigurationStore, InMemoryCredentialStore
from raven.exceptions import GraphAgentError, InvestigationChatCancelledError
from raven.graph.vocabulary import NamedEntityVocabularyCatalog
from raven.models import InvestigationDraft, JobKind, JobStatus
from raven.repositories.catalog import CatalogRecords
from raven.repositories.knowledge_base import KnowledgeBaseStore
from raven.services.operations import InvestigationOperations
from raven.services.page_catalog import PageCatalogService
from raven.tui.screens.evidence_inspector import EvidenceInspectorScreen
from raven.tui.widgets.evidence import EvidenceTable

DICTIONARIES = Path(__file__).parents[1] / "config/osint-vocabularies"


class MemoryCatalog:
    def __init__(self):
        self.documents = {}
        self.pages = {}

    def save_catalog(self, catalog):
        self.documents[catalog.investigation_id, catalog.document_id] = replace(catalog, pages=())

    def save_catalog_page(self, catalog, page):
        self.pages[
            catalog.investigation_id, catalog.document_id, catalog.signature, page.number
        ] = page

    def load_catalog(self, investigation_id, document_id, *, with_pages=True):
        catalog = self.documents.get((investigation_id, document_id))
        if catalog is None:
            return None
        pages = (
            tuple(
                value
                for key, value in sorted(self.pages.items())
                if key[:3] == (investigation_id, document_id, catalog.signature)
            )
            if with_pages
            else ()
        )
        return replace(catalog, pages=pages)


class CatalogAi:
    available = True
    settings = SimpleNamespace(model="test-model", provider="ollama", base_url="http://test")

    def __init__(self):
        self.calls = []

    def chat(self, system, user, *, json_mode, **options):
        payload = json.loads(user)
        if "pages" in payload:
            return json.dumps(
                {
                    "summary": "The document describes Acme.",
                    "pages": [page["number"] for page in payload["pages"]],
                }
            )
        self.calls.append(payload)
        source = payload["source"]
        return json.dumps(
            {
                "title": "Corporate structure",
                "summary": "Acme is named in the source.",
                "category": "IDENTITY",
                "topics": ["Acme"],
                "entities": [{"name": "Acme", "code": "CORP_COMPANY"}] if "Acme" in source else [],
                "uses": ["IDENTIFICATION"],
                "quotes": [source[:100]],
                "confidence": 0.9,
            }
        )


def catalog_service(tmp_path, pages=("Acme operates in Rome.", "Acme owns a site.")):
    cases = FakeInvestigations()
    case = cases.create(
        InvestigationDraft(
            name="Catalog case",
            questions=("Where is Acme?",),
            analysis_domain="CORPORATE_OWNERSHIP",
        )
    )
    store = KnowledgeBaseStore(tmp_path / "kb")
    source = tmp_path / "report.md"
    source.write_text("\n".join(pages))
    document = replace(
        store.add(case.investigation_id, source), file_format="PDF", page_count=len(pages)
    )
    store.extract_pages = lambda document, cancelled=None: pages
    case = replace(case, evidence_documents=(document,))
    repository = MemoryCatalog()
    ai = CatalogAi()
    service = PageCatalogService(repository, store, ai, DICTIONARIES, InvestigationOperations())
    return service, case, document, ai


def test_catalog_covers_pages_and_resumes_without_reanalyzing_valid_pages(tmp_path):
    service, case, document, ai = catalog_service(
        tmp_path, ("Acme in Rome.", "", "Acme contracts.")
    )
    with pytest.raises(GraphAgentError, match="Some pages"):
        service.index_knowledge_base(case, (document,))
    catalog = service.load(case, document)
    assert [p.number for p in catalog.pages] == [1, 2, 3]
    assert catalog.completed == 3 and catalog.failed_count == 1 and catalog.state == "failed"
    assert catalog.review_count == 0
    assert catalog.pages[1].confidence == 0 and catalog.pages[1].category == ""
    assert catalog.dictionary_hash and catalog.dictionary_versions
    assert len(ai.calls) == 2
    with pytest.raises(GraphAgentError, match="Some pages"):
        service.index_knowledge_base(case, (document,))
    assert len(ai.calls) == 2
    assert ai.calls[0]["dictionary"]["domain_code"] == "CORPORATE_OWNERSHIP"


def test_cancelled_catalog_keeps_completed_pages_and_can_resume(tmp_path):
    service, case, document, ai = catalog_service(tmp_path)
    cancellation = Event()

    def progress(update):
        if "Catalog 1/2" in update.detail:
            cancellation.set()

    with pytest.raises(InvestigationChatCancelledError):
        service.index_knowledge_base(case, (document,), cancellation.is_set, progress)
    catalog = service.load(case, document)
    assert catalog.state == "cancelled" and catalog.completed == 1
    service.index_knowledge_base(case, (document,))
    assert len(ai.calls) == 2
    assert service.load(case, document).state == "ready"


@pytest.mark.parametrize(
    "mutation",
    [
        {"quotes": ["This was invented"]},
        {"quote_ids": ["S999"]},
        {"confidence": True},
        {"confidence": float("nan")},
        {"entities": [{"name": "Acme", "code": "UNKNOWN"}]},
        {"entities": [{"name": "Invented company", "code": "CORP_COMPANY"}]},
        {"category": "FAKE"},
        {"uses": ["FAKE"]},
        {"topics": "not a list"},
    ],
)
def test_agent_rejects_unsupported_or_invalid_classifications(mutation):
    ai = CatalogAi()
    source = "Acme operates in Rome."
    valid = json.loads(ai.chat("", json.dumps({"source": source}), json_mode=True))
    ai.chat = lambda *args, **kwargs: json.dumps({**valid, **mutation})
    vocabulary = NamedEntityVocabularyCatalog(DICTIONARIES).resolve("CORPORATE_OWNERSHIP")
    with pytest.raises(GraphAgentError):
        PageCatalogAgent(ai).analyze(source, vocabulary, "Italian")


def test_invalid_page_analysis_retries_then_keeps_failed_record(tmp_path):
    service, case, document, ai = catalog_service(tmp_path, ("Acme in Rome.",))
    ai.chat = MagicMock(return_value="[]")
    with pytest.raises(GraphAgentError):
        service.index_knowledge_base(case, (document,))
    catalog = service.load(case, document)
    assert ai.chat.call_count == 2
    assert catalog.failed_count == 1 and catalog.pages[0].error
    assert catalog.review_count == 0
    assert catalog.pages[0].state == "failed" and catalog.pages[0].category == ""
    assert catalog.pages[0].error_code == "validation_failed"
    assert "object required" in catalog.pages[0].error
    retry_payload = json.loads(ai.chat.call_args_list[1].args[1])
    assert "object required" in retry_payload["validation_feedback"]
    assert not catalog.categories
    assert not catalog.pages[0].quotes


def test_agent_resolves_quote_ids_to_original_text_and_constrains_output():
    ai = CatalogAi()
    original = ai.chat
    captured = []
    source = "Acme è citata nel documento.\nLa relazione è negata, non confermata."

    def respond(system, user, **options):
        payload = json.loads(user)
        captured.append(options)
        body = json.loads(original(system, user, **options))
        body.pop("quotes")
        body["quote_ids"] = list(payload["source_spans"])
        return json.dumps(body)

    ai.chat = respond
    vocabulary = NamedEntityVocabularyCatalog(DICTIONARIES).resolve("CORPORATE_OWNERSHIP")
    page = PageCatalogAgent(ai).analyze(source, vocabulary, "English")
    assert page.quotes == tuple(source.splitlines())
    schema = captured[0]["json_schema"]["properties"]
    assert schema["quote_ids"]["items"]["enum"] == ["S1", "S2"]
    assert schema["quote_ids"]["maxItems"] == 8
    assert "FAKE" not in schema["uses"]["items"]["enum"]


def test_catalog_attempts_remaining_documents_after_page_validation_failure(tmp_path):
    service, case, first, ai = catalog_service(tmp_path, ("Acme invalid.",))
    source = tmp_path / "second.md"
    source.write_text("Acme valid.")
    second = service.knowledge_bases.add(case.investigation_id, source)
    service.knowledge_bases.extract_pages = lambda doc, cancelled=None: (
        "Acme invalid." if doc.document_id == first.document_id else "Acme valid.",
    )
    original = ai.chat

    def respond(system, user, **options):
        body = json.loads(original(system, user, **options))
        if json.loads(user).get("source") == "Acme invalid.":
            body["uses"] = ["UNKNOWN_USE"]
        return json.dumps(body)

    ai.chat = respond
    updates = []
    with pytest.raises(GraphAgentError, match="1/2 documents"):
        service.index_knowledge_base(case, (first, second), progress=updates.append)
    assert service.load(case, first).failed_count == 1
    assert service.load(case, second).state == "ready"
    assert updates[-1].completed == updates[-1].total == 2
    assert updates[-1].state.value == "ready"


def test_partial_dates_are_not_completed_and_retry_receives_rejected_values(tmp_path):
    service, case, doc, ai = catalog_service(
        tmp_path, ("Acme. Attivo dal 20 febbraio; prosegue al 5 marzo 2026.",)
    )
    original = ai.chat

    def respond(system, user, **options):
        payload = json.loads(user)
        body = json.loads(original(system, user, **options))
        if "source" in payload:
            if payload["validation_feedback"]:
                assert '"dates": ["20 febbraio 2026"]' in payload["validation_feedback"]
                body["dates"] = ["20 febbraio"]
            else:
                body["dates"] = ["20 febbraio 2026"]
        return json.dumps(body)

    ai.chat = respond
    service.index_knowledge_base(case, (doc,))
    catalog = service.load(case, doc)
    assert catalog.state == "ready"
    assert catalog.pages[0].dates == ("20 febbraio",)
    assert len(ai.calls) == 2


def test_catalog_marks_profile_and_ocr_changes_stale_and_reads_originals(tmp_path):
    service, case, document, ai = catalog_service(tmp_path)
    service.index_knowledge_base(case, (document,))
    chunks = service.search_sources(case, (document,), "Acme")
    assert chunks and chunks[0].text == "Acme operates in Rome."
    assert chunks[0].page_number == 1
    changed = replace(case, analysis_domain="GENERAL_OSINT")
    assert service.load(changed, document).state == "stale"
    assert not service.search_sources(changed, (document,), "Acme")
    service.knowledge_bases.ocr_fingerprint = lambda document: "new-ocr"
    assert service.load(case, document).state == "stale"


def test_source_hash_mismatch_is_not_served(tmp_path):
    service, case, document, ai = catalog_service(tmp_path)
    service.index_knowledge_base(case, (document,))
    service.knowledge_bases.extract_pages = lambda document, cancelled=None: ("changed", "changed")
    assert not service.search_sources(case, (document,), "Acme")


def test_long_page_is_fully_processed_and_non_pdf_is_a_section(tmp_path):
    text = "Acme " * 5000
    service, case, document, ai = catalog_service(tmp_path, (text,))
    document = replace(document, file_format="MD")
    service.index_knowledge_base(case, (document,))
    assert len(ai.calls) == 3
    assert sum(len(call["source"]) for call in ai.calls) >= len(text)
    assert service.load(case, document).unit == "section"


def test_mongo_round_trip_stores_pages_separately_and_scopes_every_query(tmp_path):
    service, case, document, ai = catalog_service(tmp_path)
    service.index_knowledge_base(case, (document,))
    catalog = service.load(case, document)
    records = CatalogRecords()
    records._database = {"document_catalogs": MagicMock(), "catalog_pages": MagicMock()}
    records.save_catalog(catalog)
    records.save_catalog_page(catalog, catalog.pages[0])
    manifest = records._database["document_catalogs"].replace_one.call_args.args[1]
    assert "pages" not in manifest
    records._database["document_catalogs"].find_one.return_value = manifest
    records._database["catalog_pages"].find.return_value.sort.return_value = [
        asdict(catalog.pages[0])
    ]
    loaded = records.load_catalog(case.investigation_id, document.document_id)
    assert loaded.pages[0] == catalog.pages[0]
    query = records._database["catalog_pages"].find.call_args.args[0]
    assert query == {
        "investigation_id": case.investigation_id,
        "document_id": document.document_id,
        "signature": catalog.signature,
    }


@pytest.mark.parametrize("size", [(80, 24), (120, 32), (160, 50)])
async def test_document_catalog_overview_filter_and_original_navigation(tmp_path, size):
    service, case, document, ai = catalog_service(tmp_path)
    service.index_knowledge_base(case, (document,))
    cases = FakeInvestigations()
    cases.investigations = [case]
    app = make_app(tmp_path, investigations=cases)
    app.load_document_catalog = service.load
    app.evidence_page_previews = service.knowledge_bases.extract_pages
    async with app.run_test(size=size) as pilot:
        app.open_investigation(case)
        await pilot.pause()
        await app.workers.wait_for_complete()
        workspace = app.screen
        workspace.query_one("#workspace-tabs", TabbedContent).active = "workspace-evidence-tab"
        await pilot.pause()
        summary = workspace.query_one("#evidence-catalog-summary")
        assert summary.display and summary.region.bottom <= size[1] - 1
        table = workspace.query_one(EvidenceTable)
        assert table.size.height >= 4
        assert table.get_cell(document.document_id, "catalog") == "2/2 · ready"
        table.focus()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, EvidenceInspectorScreen)
        inspector = app.screen
        assert inspector.query_one("#catalog-page-body").size.height >= 5
        assert inspector.query_one("#catalog-pages-table", DataTable).row_count == 2
        for selector in ("#catalog-document", "#catalog-read-source", "#close-evidence-inspector"):
            button = inspector.query_one(selector)
            assert button.region.bottom <= size[1]
            assert button.region.right <= size[0]
        inspector.query_one("#catalog-page-search", Input).value = "missing topic"
        await pilot.pause()
        assert inspector.query_one("#catalog-pages-table", DataTable).row_count == 0
        inspector.query_one("#catalog-page-search", Input).value = "Acme"
        await pilot.pause()
        inspector.query_one("#catalog-pages-table", DataTable).move_cursor(row=1)
        await pilot.pause()
        await pilot.click("#catalog-read-source")
        await pilot.pause()
        assert inspector.query_one("#evidence-page-select", Select).value == 1
        assert "Acme owns a site." in inspector.query_one("#evidence-text-preview", TextArea).text
        await pilot.press("escape")
        assert app.screen is workspace


def test_catalog_persists_source_read_failure_and_model_unavailability(tmp_path):
    service, case, document, ai = catalog_service(tmp_path)
    ai.available = False
    with pytest.raises(GraphAgentError):
        service.index_knowledge_base(case, (document,))
    assert service.load(case, document).state == "failed"
    ai.available = True
    service.knowledge_bases.document_path(document).write_text("tampered source")
    with pytest.raises(GraphAgentError):
        service.index_knowledge_base(case, (document,))
    catalog = service.load(case, document)
    assert catalog.state == "failed" and catalog.error
    assert not service.search_sources(case, (document,), "Acme")


def test_profile_change_during_agent_call_cannot_publish_under_old_dictionary(tmp_path):
    service, case, document, ai = catalog_service(tmp_path)
    original = ai.chat

    def change_profile(*args, **kwargs):
        result = original(*args, **kwargs)
        service.knowledge_bases.ocr_fingerprint = lambda document: "changed-during-run"
        return result

    ai.chat = change_profile
    with pytest.raises(InvestigationChatCancelledError):
        service.index_knowledge_base(case, (document,))
    raw = service.repository.load_catalog(case.investigation_id, document.document_id)
    assert raw.state == "cancelled" and not raw.pages


def test_domain_specific_catalog_categories_are_supplied_to_the_agent():
    vocabulary = NamedEntityVocabularyCatalog(DICTIONARIES).resolve("CORPORATE_OWNERSHIP")
    assert "OWNERSHIP_STRUCTURE" in vocabulary.page_categories
    ai = CatalogAi()
    original = ai.chat

    def classify(*args, **kwargs):
        body = json.loads(original(*args, **kwargs))
        return json.dumps(
            {**body, "category": "OWNERSHIP_STRUCTURE", "uses": ["OWNERSHIP_TRACING"]}
        )

    ai.chat = classify
    page = PageCatalogAgent(ai).analyze("Acme owns the company.", vocabulary, "English")
    assert page.category == "OWNERSHIP_STRUCTURE"
    assert "OWNERSHIP_TRACING" in ai.calls[0]["allowed_uses"]


def test_document_summary_rejects_invented_page_references(tmp_path):
    service, case, document, ai = catalog_service(tmp_path)
    original = ai.chat

    def bad_summary(system, user, **kwargs):
        if "pages" in json.loads(user):
            return json.dumps({"summary": "Acme is mentioned.", "pages": [999]})
        return original(system, user, **kwargs)

    ai.chat = bad_summary
    service.index_knowledge_base(case, (document,))
    catalog = service.load(case, document)
    assert catalog.completed == 2 and catalog.summary_state == "review"
    assert "999" not in catalog.summary


async def test_upload_automatically_enqueues_application_owned_catalog_job(tmp_path):
    started = Event()
    captured = []

    def run(investigation, documents, cancelled=None, progress=None):
        captured.extend(documents)
        started.set()
        return len(documents)

    runner = SimpleNamespace(index_knowledge_base=run, load=lambda *args, **kwargs: None)
    cases = FakeInvestigations()
    case = cases.create(InvestigationDraft(name="Auto catalog", questions=("Who?",)))
    app = RavenApp(
        configuration_store=ConfigurationStore(tmp_path / "config.json", InMemoryCredentialStore()),
        infrastructure=FakeInfrastructure(),
        investigations=cases,
        page_catalog=runner,
        auto_connect=False,
    )
    async with app.run_test() as pilot:
        document = await asyncio.to_thread(
            app.add_evidence, case.investigation_id, tmp_path / "report.pdf"
        )
        assert await asyncio.to_thread(started.wait, 2)
        await pilot.pause()
        job = app.catalog_jobs.snapshot(case.investigation_id)
        assert job.kind is JobKind.CATALOG and job.status is JobStatus.COMPLETED
        assert captured == [document]


@pytest.mark.parametrize("code", ["timeout", "output_limit", "authentication"])
def test_request_failure_is_saved_without_retry_or_false_category(tmp_path, code):
    from raven.exceptions import GraphAgentRequestError

    service, case, document, ai = catalog_service(tmp_path)
    ai.chat = MagicMock(side_effect=GraphAgentRequestError("Bounded request failed", code))
    with pytest.raises(GraphAgentRequestError):
        service.index_knowledge_base(case, (document,))
    assert ai.chat.call_count == 1
    catalog = service.load(case, document)
    assert catalog.state == "failed" and catalog.completed == 1
    assert catalog.failed_count == 1 and catalog.review_count == 0
    assert catalog.pages[0].category == "" and catalog.pages[0].error_code == code
    assert not catalog.categories and not catalog.summary and not catalog.topics
    assert not service.search_sources(case, (document,), "Acme")


def test_real_out_of_domain_classification_is_preserved(tmp_path):
    service, case, document, ai = catalog_service(tmp_path, ("A library grows plants.",))
    original = ai.chat

    def library(*args, **kwargs):
        body = json.loads(original(*args, **kwargs))
        if "category" in body:
            body.update(
                category="EVIDENCE_ONLY",
                summary="A library grows plants.",
                title="Library",
                topics=["plants"],
                confidence=0.95,
            )
        return json.dumps(body)

    ai.chat = library
    service.index_knowledge_base(case, (document,))
    catalog = service.load(case, document)
    assert catalog.pages[0].category == "EVIDENCE_ONLY"
    assert catalog.failed_count == catalog.review_count == 0
    assert catalog.state == "ready"


def test_legacy_failure_is_normalized_without_erasing_valid_evidence_only(tmp_path):
    service, case, document, ai = catalog_service(tmp_path)
    service.index_knowledge_base(case, (document,))
    catalog = service.load(case, document)
    legacy = asdict(
        replace(
            catalog.pages[0],
            summary="",
            category="EVIDENCE_ONLY",
            quotes=(),
            entities=(),
            topics=(),
            state="review",
            error="Analysis unavailable or source validation failed.",
        )
    )
    legacy.pop("error_code")
    valid = asdict(replace(catalog.pages[1], category="EVIDENCE_ONLY"))
    valid.pop("error_code")
    manifest = asdict(replace(catalog, summary_state="page_highlights"))
    manifest.pop("pages")
    manifest.pop("failed_count")
    records = CatalogRecords()
    records._database = {"document_catalogs": MagicMock(), "catalog_pages": MagicMock()}
    records._database["document_catalogs"].find_one.return_value = manifest
    records._database["catalog_pages"].find.return_value.sort.return_value = [legacy, valid]
    loaded = records.load_catalog(case.investigation_id, document.document_id)
    assert loaded.failed_count == 1 and loaded.review_count == 0
    assert loaded.pages[0].category == "" and loaded.pages[0].state == "failed"
    assert loaded.pages[1].category == "EVIDENCE_ONLY"
    assert loaded.categories == ("EVIDENCE_ONLY: 1",)
    assert loaded.summary.startswith("2.")


def test_catalog_prompt_distinguishes_extraction_confidence_and_source_truth():
    ai = CatalogAi()
    original = ai.chat
    calls = []

    def capture(system, user, **options):
        calls.append((system, options))
        body = json.loads(original(system, user, **options))
        body["references"] = ["pagina 1", "2 / 8"]
        return json.dumps(body)

    ai.chat = capture
    v = NamedEntityVocabularyCatalog(DICTIONARIES).resolve("CORPORATE_OWNERSHIP")
    page = PageCatalogAgent(ai).analyze("Acme. See pagina 1. Footer 2 / 8", v, "Italian")
    assert page.references == ("pagina 1",)
    system, options = calls[0]
    assert "NOT whether the described events are true" in system
    assert "Fictional/test material" in system
    assert options["max_output_tokens"] == 4096 and options["timeout_seconds"] == 180


@pytest.mark.parametrize("size", [(80, 24), (160, 45)])
async def test_catalog_inspector_distinguishes_failures_and_low_confidence(tmp_path, size):
    from textual.widgets import Static

    from raven.models.catalog import catalog_overview

    service, case, document, ai = catalog_service(tmp_path)
    service.index_knowledge_base(case, (document,))
    catalog = service.load(case, document)
    failed = replace(
        catalog.pages[0],
        category="",
        summary="",
        quotes=(),
        entities=(),
        topics=(),
        state="failed",
        error="The AI request timed out after 180 seconds",
    )
    low = replace(catalog.pages[1], state="review", confidence=0.3)
    catalog = catalog_overview(replace(catalog, state="cancelled"), (failed, low))
    app = make_app(tmp_path)
    app.load_document_catalog = lambda *args: catalog
    async with app.run_test(size=size) as pilot:
        app.push_screen(
            EvidenceInspectorScreen(document, ("Acme", "Acme"), case.analysis_language, case)
        )
        await pilot.pause()
        await app.workers.wait_for_complete()
        inspector = app.screen
        status = str(inspector.query_one(".catalog-summary-status", Static).render())
        assert "1 failed" in status and "1 need review" in status
        table = inspector.query_one("#catalog-pages-table", DataTable)
        assert table.get_row("1")[2] == "Not classified"
        inspector._show_page(1)
        text = str(inspector.query_one("#catalog-page-details", Static).render())
        assert "timed out after 180 seconds" in text
        assert "EVIDENCE_ONLY" not in text and "confidence" not in text
        inspector._show_page(2)
        text = str(inspector.query_one("#catalog-page-details", Static).render())
        assert "30%" in text and "below 60%" in text


@pytest.mark.parametrize(
    ("returned_code", "valid"),
    [
        ("TER_TERRORIST_ORGANIZATION", True),
        ("ORGANIZATION|TER_TERRORIST_ORGANIZATION", True),
        ("PERSON|TER_TERRORIST_ORGANIZATION", False),
        ("ORGANIZATION|INVENTED", False),
    ],
)
def test_catalog_canonicalizes_only_registered_type_subtype_pairs(returned_code, valid):
    from raven.exceptions import CatalogValidationError

    ai = CatalogAi()
    original = ai.chat
    captured = []

    def response(system, user, **options):
        captured.append(json.loads(user))
        body = json.loads(original(system, user, **options))
        body["entities"] = [{"name": "Fronte Vela RX41", "code": returned_code}]
        return json.dumps(body)

    ai.chat = response
    vocabulary = NamedEntityVocabularyCatalog(DICTIONARIES).resolve("TERRORISM_EXTREMISM")
    agent = PageCatalogAgent(ai)
    if valid:
        page = agent.analyze("Fronte Vela RX41 is named in the source.", vocabulary, "English")
        assert page.entities == (("Fronte Vela RX41", "TER_TERRORIST_ORGANIZATION"),)
    else:
        with pytest.raises(CatalogValidationError, match="unknown entity code"):
            agent.analyze("Fronte Vela RX41 is named in the source.", vocabulary, "English")
    entries = captured[0]["dictionary"]["entity_types"]
    assert {item["code"] for item in entries} == {item.code for item in vocabulary.entity_types}
    for entry, definition in zip(entries, vocabulary.entity_types, strict=True):
        assert entry["include_when"] == list(definition.include_when)
        assert entry["exclude_when"] == list(definition.exclude_when)


def test_repaired_pages_regenerate_a_previously_partial_document_summary(tmp_path):
    service, case, doc, ai = catalog_service(tmp_path, ("Acme first.", "Acme second."))
    original = ai.chat
    fail_second = True
    summary_pages = []

    def respond(system, user, **options):
        payload = json.loads(user)
        body = json.loads(original(system, user, **options))
        if "pages" in payload:
            summary_pages.append([p["number"] for p in payload["pages"]])
        elif fail_second and payload["source"] == "Acme second.":
            body["uses"] = ["INVALID"]
        return json.dumps(body)

    ai.chat = respond
    with pytest.raises(GraphAgentError):
        service.index_knowledge_base(case, (doc,))
    partial = service.load(case, doc)
    assert partial.summary_state == "ready" and partial.failed_count == 1
    assert summary_pages == [[1]]
    fail_second = False
    service.index_knowledge_base(case, (doc,))
    assert summary_pages == [[1], [1, 2]]
    assert service.load(case, doc).failed_count == 0
