"""Claims keep negation, source attribution, and comparisons through UI and chat."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from test_app import FakeGraphAnalysis, FakeInvestigations, make_app
from textual.widgets import Button, DataTable, Input, TabbedContent, TextArea

from raven.models import GraphEntity, GraphRelationship, InvestigationDraft, InvestigationGraph
from raven.models.graph import ClaimLink, EvidenceSpan, GraphClaim, PageGraphAnalysis
from raven.services.chat import InvestigationChatService
from raven.tui.screens.document_catalog import DocumentCatalogScreen
from raven.tui.screens.graph_claims import GraphClaimsScreen
from raven.tui.screens.investigation_workspace import InvestigationWorkspaceScreen
from raven.tui.widgets.claim_details import ClaimDetails, page_error_text


def case_and_claim_graph(tmp_path):
    investigations = FakeInvestigations()
    case = investigations.create(InvestigationDraft(name="Caso RX41", questions=("Who?",)))
    first = investigations.add_evidence(case.investigation_id, tmp_path / "rapporto.pdf")
    second = replace(first, document_id="denial-doc", original_name="smentita.pdf")
    case = replace(case, evidence_documents=(first, second))
    investigations.investigations[0] = case
    source_span = EvidenceSpan(first.document_id, "Ada risulterebbe affiliata a Levante.", 1, True)
    denial_span = EvidenceSpan(second.document_id, "[RX41] Ada non è affiliata a Levante.", 2, True)
    first_claim = GraphClaim(
        "yes",
        "ada",
        "levante",
        "MEMBER_OF",
        modality="alleged",
        valid_from="2026-01-01",
        valid_until="2026-02-01",
        asserted_at="2026-03-01",
        attribution="Bollettino A",
        qualifiers=(("ambito", "locale"),),
        support=(source_span,),
    )
    denial = GraphClaim(
        "no",
        "ada",
        "levante",
        "MEMBER_OF",
        polarity="denied",
        modality="asserted",
        valid_from="2026-01-01",
        valid_until="2026-02-01",
        asserted_at="2026-04-01",
        attribution="Portavoce B",
        support=(denial_span,),
    )
    link = ClaimLink(
        "conflict",
        "yes",
        "no",
        "candidate_contradicts",
        "Stesso periodo, identità da confrontare.",
        True,
    )
    graph = InvestigationGraph(
        case.investigation_id,
        "run",
        (GraphEntity("ada", "PERSON", "Ada"), GraphEntity("levante", "ORGANIZATION", "Levante")),
        (
            GraphRelationship(
                "member", "ada", "levante", "MEMBER_OF", support=(source_span,), claim_ids=("yes",)
            ),
        ),
        datetime.now(UTC),
        claims=(first_claim, denial),
        claim_links=(link,),
        pages=(
            PageGraphAnalysis(
                first.document_id,
                1,
                "hash1",
                "sig1",
                "reused",
                datetime.now(UTC),
                catalog_state="current",
                catalog_uses=("entity_extraction",),
                claims=(first_claim,),
            ),
            PageGraphAnalysis(
                second.document_id,
                2,
                "hash2",
                "sig2",
                "partial",
                datetime.now(UTC),
                catalog_state="stale",
                claims=(denial,),
                error="Una citazione non trovata nella pagina.",
            ),
        ),
    )
    return investigations, case, graph


def test_relationship_details_include_linked_denial_without_deciding_truth(tmp_path):
    _, case, graph = case_and_claim_graph(tmp_path)
    screen = InvestigationWorkspaceScreen(case)
    screen.graph = graph
    detail = screen._relationship_detail(graph.relationships)
    assert "AFFERMATA" in detail and "NEGATA" in detail
    assert "rapporto.pdf" in detail and "smentita.pdf" in detail
    assert "Pagina 2" in detail
    assert "Possibile contraddizione" in detail
    assert "Identità da verificare" in detail
    assert "Una contraddizione non decide quale fonte sia vera" in detail
    assert "Da: 2026-01-01" in detail
    assert "Data dell'affermazione nella fonte: 2026-04-01" in detail


def test_claim_view_handles_missing_related_claim_and_missing_document(tmp_path):
    _, case, graph = case_and_claim_graph(tmp_path)
    graph = replace(
        graph,
        claim_links=(
            ClaimLink("dangling", "yes", "removed", "contradicts", "Fonte non più disponibile"),
        ),
    )
    details = ClaimDetails(graph, ())
    text = details.claim_text(graph.claims[0])
    assert "Documento non disponibile" in text
    assert "Affermazione collegata non disponibile: removed" in text


def test_page_errors_are_readable_without_losing_multiple_failure_reasons():
    text = page_error_text("invalid_claim_polarity; unverified_source_citation; timeout")
    assert "affermi o neghi" in text
    assert "pagina originale" in text
    assert "tempo disponibile" in text
    assert "invalid_claim" not in text
    assert page_error_text("") == "Nessuno"


def test_non_pdf_claim_source_and_coverage_use_logical_text_position(tmp_path):
    _, case, graph = case_and_claim_graph(tmp_path)
    document = replace(case.evidence_documents[0], file_format="TXT", original_name="rapporto.txt")
    details = ClaimDetails(graph, (document,))
    assert "Unità di testo 1" in details.claim_text(graph.claims[0])
    assert "Unità di testo 1" in details.coverage_text(graph.pages[0])
    assert "Pagina 1" not in details.source_text(graph.claims[0].support)
    assert "posizione non verificata" in details.source_text(
        (replace(graph.claims[0].support[0], page_number=None),)
    )


def test_chat_serializes_denial_comparison_time_and_attribution(tmp_path):
    _, case, graph = case_and_claim_graph(tmp_path)
    graph = replace(
        graph,
        claim_links=(
            replace(
                graph.claim_links[0],
                review_state="supported",
                review_rationale="The two attributed assertions concern the same period.",
            ),
        ),
    )
    context = json.loads(InvestigationChatService._graph_context(graph))
    claims = {claim["id"]: claim for claim in context["claims"]}
    assert claims["no"]["polarity"] == "denied"
    assert claims["yes"]["modality"] == "alleged"
    assert claims["no"]["valid_from"] == "2026-01-01"
    assert claims["no"]["asserted_at"] == "2026-04-01"
    assert claims["no"]["attribution"] == "Portavoce B"
    assert claims["yes"]["qualifiers"] == {"ambito": "locale"}
    assert context["claim_links"][0]["requires_identity_review"] is True
    assert context["claim_links"][0]["review_state"] == "supported"
    assert context["claim_links"][0]["review_rationale"] == graph.claim_links[0].review_rationale
    assert context["relationships"][0]["claim_ids"] == ["yes"]
    assert context["coverage"] == {"reused": 1, "partial": 1}
    assert context["truncated"] is False
    prompt = InvestigationChatService._system_prompt(case)
    assert 'polarity="denied"' in prompt
    assert "never turn it into a positive graph fact" in prompt
    assert "Cite both sides of a conflict" in prompt


def test_chat_budget_never_separates_a_denial_from_its_compared_assertion(tmp_path):
    _, _, graph = case_and_claim_graph(tmp_path)
    extra = tuple(
        replace(graph.claims[0], claim_id=f"extra-{number}", attribution="A" * 800)
        for number in range(100)
    )
    graph = replace(graph, claims=(*graph.claims, *extra))
    serialized = InvestigationChatService._graph_context(graph, max_chars=4_000)
    context = json.loads(serialized)
    assert len(serialized) <= 4_000
    included = {claim["id"] for claim in context["claims"]}
    assert {"yes", "no"} <= included
    assert context["truncated"] is True
    assert context["omitted"]["claims"] > 0
    assert all(
        {link["source_claim_id"], link["target_claim_id"]} <= included
        for link in context["claim_links"]
    )

    oversized = replace(graph.claims[1], attribution="oversized " * 1_000)
    graph = replace(graph, claims=(graph.claims[0], oversized))
    serialized = InvestigationChatService._graph_context(graph, max_chars=3_000)
    context = json.loads(serialized)
    assert len(serialized) <= 3_000
    assert context["claims"] == [] and context["claim_links"] == []
    assert context["relationships"] == []


@pytest.mark.parametrize("size", [(80, 24), (150, 42)])
async def test_claims_coverage_and_catalog_navigation_are_read_only(tmp_path, size):
    investigations, case, graph = case_and_claim_graph(tmp_path)
    analysis = FakeGraphAnalysis()
    analysis.graph = graph
    app = make_app(tmp_path, investigations=investigations, graph_analysis=analysis)
    catalog_reads = []

    def load_catalog(investigation, document):
        catalog_reads.append(document.document_id)
        return None

    app.load_evidence_catalog = load_catalog
    async with app.run_test(size=size) as pilot:
        await pilot.click("#nav-investigations")
        await app.workers.wait_for_complete()
        await pilot.click(".open-investigation")
        await app.workers.wait_for_complete()
        app.screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-graph-tab"
        await pilot.pause()
        button = app.screen.query_one("#open-graph-claims", Button)
        button.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, GraphClaimsScreen)
        screen = app.screen
        detail = screen.query_one("#graph-claim-detail", TextArea)
        assert "AFFERMATA" in detail.text and "NEGATA" in detail.text
        assert "smentita.pdf" in detail.text and "Pagina 2" in detail.text
        assert detail.size.height >= 3
        assert screen.query_one("#graph-claims-table", DataTable).max_scroll_x == 0

        await pilot.press("/")
        assert screen.query_one("#graph-claims-search", Input).has_focus
        screen.query_one("#graph-claims-search", Input).value = "smentita.pdf"
        await pilot.pause()
        assert screen.query_one("#graph-claims-table", DataTable).row_count == 1
        assert detail.text.startswith("NEGATA")
        screen.query_one("#graph-claims-table", DataTable).focus()
        await pilot.press("enter")
        assert detail.has_focus

        screen.query_one("#graph-claims-tabs", TabbedContent).active = "claims-coverage-tab"
        await pilot.pause()
        table = screen.query_one("#graph-coverage-table", DataTable)
        table.focus()
        await pilot.press("down", "enter")
        await pilot.pause()
        coverage = screen.query_one("#graph-coverage-detail", TextArea)
        assert coverage.has_focus
        assert "Analisi: Parziale" in coverage.text
        assert "Catalogo: Non aggiornato" in coverage.text
        assert "Una citazione non trovata" in coverage.text
        assert "Di cui negate: 1" in coverage.text
        assert coverage.size.height >= 3
        assert table.max_scroll_x == 0

        await pilot.click("#claim-open-catalog")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, DocumentCatalogScreen)
        assert catalog_reads == ["denial-doc"]
        await pilot.press("escape")
        assert app.screen is screen
        await pilot.press("escape")
        assert isinstance(app.screen, InvestigationWorkspaceScreen)
        assert analysis.mode is None


@pytest.mark.parametrize("missing_graph", [True, False])
async def test_missing_or_legacy_graph_explains_unavailable_claims(tmp_path, missing_graph):
    investigations, case, graph = case_and_claim_graph(tmp_path)
    graph = None if missing_graph else replace(graph, claims=(), claim_links=(), pages=())
    app = make_app(tmp_path, investigations=investigations)
    async with app.run_test(size=(80, 24)) as pilot:
        await app.push_screen(GraphClaimsScreen(case, graph, case.evidence_documents))
        await pilot.pause()
        detail = app.screen.query_one("#graph-claim-detail", TextArea).text
        assert ("Nessun grafo disponibile" if missing_graph else "grafi precedenti") in detail
        assert (
            "Copertura delle pagine non disponibile"
            in app.screen.query_one("#graph-coverage-detail", TextArea).text
        )
        assert app.screen.query_one("#claim-open-catalog", Button).disabled
        await pilot.press("escape")
