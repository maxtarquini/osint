"""Saved graph citations remain attributable and accessible in the existing workspace."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from test_app import FakeGraphAnalysis, FakeInvestigations, make_app
from textual.containers import VerticalScroll
from textual.widgets import Static, TabbedContent

from raven.models import GraphEntity, GraphRelationship, InvestigationDraft, InvestigationGraph
from raven.models.graph import EvidenceSpan
from raven.repositories.mongodb import MongoRepository
from raven.tui.screens.investigation_workspace import InvestigationWorkspaceScreen
from raven.tui.widgets import GraphCanvas


def sample_graph(case_id="case", evidence_id="document-id"):
    span = EvidenceSpan(
        evidence_id=evidence_id,
        quote="[RX41] Ada compare nel registro di Rete Levante.",
        page_number=2,
        verified_original=True,
    )
    person = GraphEntity(
        "ada",
        "PERSON",
        "Ada",
        evidence_ids=(evidence_id,),
        support=(span,),
        resolution_notes=("Omonimo distinto: data di nascita incompatibile.",),
    )
    organization = GraphEntity("levante", "ORGANIZATION", "Rete Levante")
    relation = GraphRelationship(
        "member",
        person.entity_id,
        organization.entity_id,
        "MEMBER_OF",
        evidence_ids=(evidence_id,),
        support=(span,),
        resolution_notes=("La fonte descrive un'affiliazione da verificare.",),
    )
    return InvestigationGraph(
        case_id, "run-provenance", (person, organization), (relation,), datetime.now(UTC)
    )


def test_graph_snapshot_roundtrip_preserves_citations_and_identity_notes():
    checkpoints = MagicMock()
    repository = MongoRepository()
    repository._database = {"graph_checkpoints": checkpoints, "investigations": MagicMock()}
    graph = sample_graph()

    repository.save_graph_snapshot(graph)

    query, payload = checkpoints.replace_one.call_args.args
    assert query == {"investigation_id": "case", "checkpoint_id": "run-provenance"}
    assert payload["entities"][0]["support"] == [
        {
            "evidence_id": "document-id",
            "quote": "[RX41] Ada compare nel registro di Rete Levante.",
            "page_number": 2,
            "verified_original": True,
            "unit_id": "",
            "start_offset": None,
            "end_offset": None,
        }
    ]
    assert payload["relationships"][0]["resolution_notes"] == [
        "La fonte descrive un'affiliazione da verificare."
    ]
    checkpoints.find_one.return_value = payload
    assert repository.latest_graph_snapshot("case") == graph
    assert checkpoints.find_one.call_args.args == ({"investigation_id": "case"},)


@pytest.mark.parametrize("optional_value", ["absent", None])
def test_legacy_records_without_citations_remain_readable_and_unverified(optional_value):
    entity = {"entity_id": "ada", "type": "PERSON", "canonical_name": "Ada"}
    relationship = {
        "relationship_id": "member",
        "source_entity_id": "ada",
        "target_entity_id": "levante",
        "type": "MEMBER_OF",
    }
    if optional_value is None:
        for record in (entity, relationship):
            record.update(support=None, resolution_notes=None)

    for item in (
        MongoRepository._graph_entity_from_document(entity),
        MongoRepository._graph_relationship_from_document(relationship),
    ):
        assert item.support == ()
        assert item.resolution_notes == ()
        assert item.status.value == "proposed"


def test_old_citation_without_location_does_not_gain_verification():
    entity = MongoRepository._graph_entity_from_document(
        {
            "entity_id": "ada",
            "type": "PERSON",
            "canonical_name": "Ada",
            "support": [{"evidence_id": "old-document", "quote": "Ada compare nel registro."}],
        }
    )
    assert entity.support == (EvidenceSpan("old-document", "Ada compare nel registro."),)
    investigations = FakeInvestigations()
    case = investigations.create(InvestigationDraft(name="Case", questions=("Who?",)))
    detail = InvestigationWorkspaceScreen(case)._entity_detail(entity)
    assert "posizione non verificata" in detail
    assert "Citazione non verificata nel testo originale" in detail
    assert "Documento non presente nell'indagine · old-document" in detail


def test_multiple_edge_details_keep_each_claim_attached_to_its_citation():
    investigations = FakeInvestigations()
    case = investigations.create(InvestigationDraft(name="Case", questions=("Who?",)))
    screen = InvestigationWorkspaceScreen(case)
    graph = sample_graph(case.investigation_id)
    screen.graph = graph
    first = graph.relationships[0]
    second = replace(
        first,
        relationship_id="denial",
        relationship_type="DENIES_MEMBERSHIP",
        support=(EvidenceSpan("second-doc", "La fonte nega l'affiliazione.", 4, True),),
        resolution_notes=(),
    )
    detail = screen._relationship_detail((first, second))
    first_start = detail.index("MEMBER_OF · PROPOSED")
    second_start = detail.index("DENIES_MEMBERSHIP · PROPOSED")
    assert "Ada compare nel registro" in detail[first_start:second_start]
    assert "La fonte nega l'affiliazione." in detail[second_start:]
    assert "Pagina 4" in detail[second_start:]


@pytest.mark.parametrize("size", [(80, 24), (150, 42)])
async def test_graph_selection_shows_source_page_quote_and_legacy_notice(tmp_path, size):
    investigations = FakeInvestigations()
    case = investigations.create(InvestigationDraft(name="Case", questions=("Who?",)))
    document = investigations.add_evidence(case.investigation_id, tmp_path / "fonte-rx41.pdf")
    case = replace(case, evidence_documents=(document,))
    investigations.investigations[0] = case
    analysis = FakeGraphAnalysis()
    analysis.graph = sample_graph(case.investigation_id)
    app = make_app(tmp_path, investigations=investigations, graph_analysis=analysis)

    async with app.run_test(size=size) as pilot:
        await pilot.click("#nav-investigations")
        await app.workers.wait_for_complete()
        await pilot.click(".open-investigation")
        await app.workers.wait_for_complete()
        app.screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-graph-tab"
        await pilot.pause()
        canvas = app.screen.query_one("#graph-canvas", GraphCanvas)
        canvas.focus()
        await pilot.press("j")
        await pilot.pause()

        detail = app.screen.query_one("#graph-selection-detail", Static)
        text = detail.render().plain
        assert "fonte-rx41.pdf" in text
        assert "Pagina 2" in text
        assert "[RX41] Ada compare nel registro" in text
        assert "NOTE DI IDENTITÀ" in text
        assert "Omonimo distinto" in text
        assert "PROPOSED" in text
        assert "Citazione verificata nel testo originale" in text
        assert "non la verità dell'affermazione" in text

        panel = app.screen.query_one("#graph-details-panel", VerticalScroll)
        panel.focus()
        await pilot.press("end")
        await pilot.pause()
        assert panel.scroll_y > 0
        assert panel.max_scroll_x == 0

        canvas.post_message(GraphCanvas.SelectionChanged(analysis.graph.relationships))
        await pilot.pause()
        assert panel.scroll_y == 0
        assert "La fonte descrive un'affiliazione" in detail.render().plain
        assert "Pagina 2" in detail.render().plain

        canvas.select_entity("levante")
        await pilot.pause()
        assert "Nessuna citazione puntuale salvata" in detail.render().plain
        assert "grafi precedenti" in detail.render().plain
