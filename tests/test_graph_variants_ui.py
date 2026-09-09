"""Real Textual pilots for method selection, persisted A/B and explicit activation."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from test_app import FakeGraphAnalysis, FakeInvestigations, make_app
from test_graph_analysis import investigation
from textual.widgets import Button, Input, Select, TabbedContent, TextArea

from raven.graph.variants import compare_variants
from raven.models import InvestigationDraft
from raven.models.graph import GraphManifest, InvestigationGraph
from raven.tui.screens.graph_variants import GraphVariantsScreen


class Variants:
    def __init__(self):
        self.first = InvestigationGraph(
            "case",
            "one",
            (),
            (),
            datetime.now(UTC),
            variant_name="Documentale",
            manifest=GraphManifest(),
        )
        self.second = replace(self.first, run_id="two", variant_name="Temporale")
        self.active = self.first
        self.method = "event_temporal"
        self.selections = []

    def variants(self, case_id):
        return tuple(
            {"run_id": g.run_id, "name": g.variant_name} for g in (self.first, self.second)
        )

    def latest(self, case_id):
        return self.active

    def method_preference(self, case_id):
        return self.method

    def set_method_preference(self, case_id, method_id):
        self.method = method_id

    def open_variant(self, case_id, run_id):
        return self.first if run_id == "one" else self.second

    def compare_variants(self, case_id, first, second):
        return compare_variants(
            self.open_variant(case_id, first), self.open_variant(case_id, second)
        )

    def activate_variant(self, case_id, run_id):
        self.selections.append(run_id)
        self.active = self.open_variant(case_id, run_id)
        return self.active


@pytest.mark.parametrize("size", [(80, 24), (140, 45)])
async def test_variant_modal_keyboard_compare_open_activate_and_escape(tmp_path, size):
    app = make_app(tmp_path)
    service = Variants()
    result = []
    async with app.run_test(size=size) as pilot:
        screen = GraphVariantsScreen(investigation("case"), service, model="test-model")
        app.push_screen(screen, result.append)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert screen.query_one("#variant-method", Select).value == "event_temporal"
        assert screen.query_one("#variant-a", Select).value == "one"
        button = screen.query_one("#variant-compare", Button)
        button.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "Proposizioni allineate" in screen.query_one("#variant-report", TextArea).text
        assert service.active is service.first and not service.selections
        assert screen.query_one("#variant-close", Button).region.bottom <= size[1]
        screen.query_one("#variant-a", Select).value = "two"
        await pilot.pause()
        screen.query_one("#variant-activate", Button).focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert service.active is service.second and result[0][0] == "active"
        app.push_screen(GraphVariantsScreen(investigation("case"), service))
        await app.workers.wait_for_complete()
        await pilot.press("escape")
        assert not isinstance(app.screen, GraphVariantsScreen)


@pytest.mark.parametrize("size", [(80, 24), (140, 45), (200, 60)])
async def test_generation_returns_selected_method_and_name_without_activation(tmp_path, size):
    app = make_app(tmp_path)
    service = Variants()
    result = []
    async with app.run_test(size=size) as pilot:
        screen = GraphVariantsScreen(investigation("case"), service)
        app.push_screen(screen, result.append)
        await pilot.pause()
        await app.workers.wait_for_complete()
        screen.query_one("#variant-method", Select).value = "cross_source_review"
        screen.query_one("#variant-name", Input).value = "Verifica incrociata"
        await pilot.pause()
        button = screen.query_one("#variant-generate", Button)
        footer = screen.query_one("#variant-footer")
        assert button.parent is footer
        assert button.region.bottom <= screen.query_one("#variants-dialog").content_region.bottom
        assert button.region.right <= footer.content_region.right
        # No focus/scroll helper: the primary action must be visible immediately.
        await pilot.click("#variant-generate")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert result[0] == ("generate", "cross_source_review", "Verifica incrociata")
        assert service.method == "cross_source_review" and not service.selections


async def test_generation_shortcut_respects_busy_state(tmp_path):
    app = make_app(tmp_path)
    service = Variants()
    result = []
    async with app.run_test(size=(80, 24)) as pilot:
        screen = GraphVariantsScreen(investigation("case"), service, busy=True)
        app.push_screen(screen, result.append)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert screen.query_one("#variant-generate", Button).disabled
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert app.screen is screen and not result
        await pilot.press("escape")
        screen = GraphVariantsScreen(investigation("case"), service)
        app.push_screen(screen, result.append)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("ctrl+g")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert result[-1] == ("generate", "event_temporal", "")


async def test_visible_create_button_starts_workspace_generation(tmp_path):
    class GeneratingService(FakeGraphAnalysis):
        def __init__(self):
            super().__init__()
            self.preference = "document_claims"
            self.requests = []

        def variants(self, case_id):
            return ()

        def method_preference(self, case_id):
            return self.preference

        def set_method_preference(self, case_id, method):
            self.preference = method

        def analyze(self, *args, **kwargs):
            self.requests.append(kwargs)
            return super().analyze(*args, **kwargs)

    cases = FakeInvestigations()
    case = cases.create(InvestigationDraft(name="Creation flow", questions=("Who?",)))
    document = cases.add_evidence(case.investigation_id, tmp_path / "source.pdf")
    case = replace(case, evidence_documents=(document,))
    cases.investigations[0] = case
    service = GeneratingService()
    app = make_app(tmp_path, investigations=cases, graph_analysis=service)
    async with app.run_test(size=(80, 24)) as pilot:
        app.open_investigation(case)
        await pilot.pause()
        await app.workers.wait_for_complete()
        workspace = app.screen
        workspace.query_one("#workspace-tabs", TabbedContent).active = "workspace-graph-tab"
        await pilot.pause()
        await pilot.click("#analyze-evidence")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, GraphVariantsScreen)
        app.screen.query_one("#variant-method", Select).value = "event_temporal"
        app.screen.query_one("#variant-name", Input).value = "Timeline di prova"
        await pilot.pause()
        await pilot.click("#variant-generate")
        await app.workers.wait_for_complete()
        for _ in range(30):
            await pilot.pause(0.05)
            if workspace.graph:
                break
        assert app.screen is workspace
        assert len(service.requests) == 1
        assert service.requests[0]["method_id"] == "event_temporal"
        assert service.requests[0]["variant_name"] == "Timeline di prova"
        assert workspace.graph is not None
