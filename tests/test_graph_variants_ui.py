"""Real Textual pilots for method selection, persisted A/B and explicit activation."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from test_app import make_app
from test_graph_analysis import investigation
from textual.widgets import Button, Select, TextArea

from raven.graph.variants import compare_variants
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


async def test_generation_returns_selected_method_and_name_without_activation(tmp_path):
    app = make_app(tmp_path)
    service = Variants()
    result = []
    async with app.run_test(size=(80, 24)) as pilot:
        screen = GraphVariantsScreen(investigation("case"), service)
        app.push_screen(screen, result.append)
        await pilot.pause()
        await app.workers.wait_for_complete()
        screen.query_one("#variant-method", Select).value = "cross_source_review"
        screen.query_one("#variant-generate", Button).focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert result[0] == ("generate", "cross_source_review", "")
        assert service.method == "cross_source_review" and not service.selections
