"""Real Textual layout, review and event-driven job regressions."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from test_app import FakeInvestigations, make_app
from textual.widgets import Checkbox, TabbedContent

from raven.models import (
    EvidencePreparationMode,
    GraphAnalysisJob,
    GraphAnalysisProgress,
    GraphEntity,
    GraphJobStatus,
    GraphRunStatus,
    InvestigationDraft,
    InvestigationGraph,
)
from raven.tui.screens.file_picker import EvidenceFilePicker
from raven.tui.screens.graph_filters import GraphFiltersScreen
from raven.tui.screens.graph_inspector import GraphInspectorScreen
from raven.tui.screens.home import HomeScreen


@pytest.mark.parametrize("size", [(80, 24), (120, 32), (160, 45)])
async def test_graph_inspection_search_filters_and_home_at_supported_sizes(tmp_path, size):
    cases = FakeInvestigations()
    case = cases.create(InvestigationDraft(name="Layout case", questions=("Who?",)))
    app = make_app(tmp_path, investigations=cases)
    async with app.run_test(size=size) as pilot:
        app.open_investigation(case)
        await pilot.pause()
        await app.workers.wait_for_complete()
        workspace = app.screen
        workspace.query_one("#workspace-tabs", TabbedContent).active = "workspace-graph-tab"
        workspace._show_graph(
            InvestigationGraph(
                case.investigation_id,
                "run",
                (GraphEntity("a", "PERSON", "Name"),),
                (),
                datetime.now(UTC),
            )
        )
        await pilot.pause()
        search = workspace.query_one("#graph-entity-search")
        assert search.region.height == 3 and search.visible
        table = workspace.query_one("#graph-items-table")
        assert table.region.bottom <= size[1] - 1
        table.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, GraphInspectorScreen)
        for selector in ("#inspect-verify", "#inspect-reject", "#inspect-close"):
            button = app.screen.query_one(selector)
            assert button.region.bottom <= size[1]
            assert button.region.right <= size[0]
        await pilot.press("escape")
        await pilot.click("#graph-filters")
        await pilot.pause()
        assert isinstance(app.screen, GraphFiltersScreen)
        assert app.screen.query_one("#apply-graph-filters").region.bottom <= size[1]
        await pilot.press("escape")
        app.navigate("jobs")
        await pilot.pause()
        app.navigate("home")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


async def test_completed_job_does_not_reset_next_run_controls(tmp_path):
    cases = FakeInvestigations()
    case = cases.create(InvestigationDraft(name="Next run", questions=("Who?",)))
    app = make_app(tmp_path, investigations=cases)
    async with app.run_test(size=(80, 24)) as pilot:
        app.open_investigation(case)
        await pilot.pause()
        workspace = app.screen
        now = datetime.now(UTC)
        job = GraphAnalysisJob(
            "job",
            case.investigation_id,
            GraphJobStatus.COMPLETED,
            EvidencePreparationMode.COMPRESS,
            now,
            now,
            GraphAnalysisProgress(GraphRunStatus.COMPLETED, 1, 1, "Done"),
        )
        workspace._apply_graph_analysis_job(job)
        workspace.query_one("#graph-compress-evidence", Checkbox).value = False
        workspace.query_one("#graph-chunk-evidence", Checkbox).value = True
        workspace._apply_graph_analysis_job(job)
        assert not workspace.query_one("#graph-compress-evidence", Checkbox).value
        assert workspace.query_one("#graph-chunk-evidence", Checkbox).value
        workspace.query_one("#workspace-tabs", TabbedContent).active = "workspace-chat-tab"
        app.settings = replace(app.settings, interface_density="compact")
        app.apply_design()
        await pilot.pause()
        assert app.theme == "raven"
        assert workspace.query_one("#chat-input").region.bottom <= 23


@pytest.mark.parametrize("size", [(80, 24), (120, 32), (160, 50)])
async def test_locations_navigation_and_empty_state_action(tmp_path, size):
    cases = FakeInvestigations()
    case = cases.create(InvestigationDraft(name="New case", questions=("Where?",)))
    app = make_app(tmp_path, investigations=cases)
    async with app.run_test(size=size) as pilot:
        app.open_investigation(case)
        await pilot.pause()
        await app.workers.wait_for_complete()
        workspace = app.screen
        tabs = workspace.query_one("#workspace-tabs", TabbedContent)
        rail = workspace.query_one("#workspace-rail")
        if size[0] >= 140:
            assert rail.display
            await pilot.click("#rail-map")
        else:
            assert not rail.display
            tabs.active = "workspace-map-tab"
        await pilot.pause()
        assert tabs.active == "workspace-map-tab"
        assert workspace.query_one("#rail-map").has_class("selected")
        action = workspace.query_one("#map-empty .empty-state-action")
        assert action.region.height == 3
        assert 0 <= action.region.y < action.region.bottom <= size[1] - 1
        assert 0 <= action.region.x < action.region.right <= size[0]
        await pilot.click("#map-empty .empty-state-action")
        await pilot.pause()
        assert isinstance(app.screen, EvidenceFilePicker)


async def test_derived_views_replace_empty_states_when_graph_has_results(tmp_path):
    cases = FakeInvestigations()
    case = cases.create(InvestigationDraft(name="Located event", questions=("Where?",)))
    app = make_app(tmp_path, investigations=cases)
    async with app.run_test(size=(160, 50)) as pilot:
        app.open_investigation(case)
        await pilot.pause()
        await app.workers.wait_for_complete()
        workspace = app.screen
        await pilot.click("#rail-map")
        workspace._show_graph(
            InvestigationGraph(
                case.investigation_id,
                "run",
                (
                    GraphEntity(
                        "rome",
                        "LOCATION",
                        "Roma",
                        external_identifiers=(
                            ("latitude", "41.9"),
                            ("longitude", "12.5"),
                            ("date", "2026-09-07"),
                        ),
                    ),
                ),
                (),
                datetime.now(UTC),
            )
        )
        await pilot.pause()
        assert not workspace.query_one("#map-empty").display
        assert workspace.query_one("#map-results").display
        assert "Roma" in str(workspace.query_one("#graph-map-view").render())
        await pilot.click("#rail-timeline")
        await pilot.pause()
        assert not workspace.query_one("#timeline-empty").display
        assert workspace.query_one("#timeline-results").display
        assert "2026-09-07" in str(workspace.query_one("#graph-timeline-view").render())


@pytest.mark.parametrize("size", [(80, 24), (120, 32), (160, 45)])
@pytest.mark.parametrize("description", ["", "Detailed investigation context. " * 55])
async def test_overview_keeps_full_profile_and_context_accessible(tmp_path, size, description):
    cases = FakeInvestigations()
    case = cases.create(
        InvestigationDraft(
            name="Complete overview",
            questions=("Which entities are linked?",),
            description=description,
            analysis_domain="TERRORISM_EXTREMISM",
        )
    )
    app = make_app(tmp_path, investigations=cases)
    async with app.run_test(size=size) as pilot:
        app.open_investigation(case)
        await pilot.pause()
        workspace = app.screen
        workspace.query_one("#workspace-tabs", TabbedContent).active = "workspace-overview-tab"
        await pilot.pause()
        grid = workspace.query_one("#overview-grid")
        for text_id, card_id in (
            ("workspace-profile", "overview-profile-card"),
            ("workspace-description", "overview-brief-card"),
        ):
            text = workspace.query_one(f"#{text_id}")
            card = workspace.query_one(f"#{card_id}")
            assert text.region.bottom <= card.content_region.bottom
            assert card.region.bottom <= grid.content_region.bottom
            assert card.region.right <= size[0]
        profile = workspace.query_one("#workspace-profile")
        assert "TERRORISM_EXTREMISM" in str(profile.render())
        assert "Knowledge base\n0 documents" in str(profile.render())
        overview = workspace.query_one("#workspace-overview")
        overview.scroll_end(animate=False)
        await pilot.pause()
        questions = workspace.query_one("#workspace-questions")
        assert overview.content_region.y <= questions.region.y
        assert questions.region.bottom <= overview.content_region.bottom
