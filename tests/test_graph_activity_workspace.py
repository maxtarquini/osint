"""Graph job activity keeps the investigation usable while work is in flight."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_app import FakeGraphAnalysis, FakeInfrastructure, FakeInvestigations, make_app
from test_graph_jobs import _investigation
from textual.widgets import Button, Select, Static, TabbedContent

from raven.models import (
    EvidencePreparationMode,
    GraphAnalysisJob,
    GraphAnalysisProgress,
    GraphJobStatus,
    GraphRunStatus,
)
from raven.tui.screens.investigation_workspace import InvestigationWorkspaceScreen
from raven.tui.widgets import GraphCanvas
from raven.tui.widgets.graph_activity import GraphBuildActivity


def _app_with_previous_graph(tmp_path: Path):
    case, document = _investigation(1)
    investigations = FakeInvestigations()
    investigations.investigations = [case]
    investigations.documents = [document]
    graph_analysis = FakeGraphAnalysis()
    previous = graph_analysis.analyze(case, (document,), EvidencePreparationMode.COMPRESS)
    app = make_app(
        tmp_path,
        investigations=investigations,
        infrastructure=FakeInfrastructure(),
        graph_analysis=graph_analysis,
    )
    return app, case, previous


def _queued_job(case_id: str) -> GraphAnalysisJob:
    submitted = datetime.now(UTC) - timedelta(seconds=15)
    return GraphAnalysisJob(
        job_id="next-graph-run",
        investigation_id=case_id,
        status=GraphJobStatus.QUEUED,
        preparation_mode=EvidencePreparationMode.COMPRESS,
        submitted_at=submitted,
        updated_at=submitted,
        progress=GraphAnalysisProgress(GraphRunStatus.QUEUED, 0, 6, "Waiting for analysis"),
    )


@pytest.mark.parametrize(
    ("terminal_status", "status_label"),
    (
        (GraphJobStatus.COMPLETED, "Completed"),
        (GraphJobStatus.FAILED, "Analysis failed"),
        (GraphJobStatus.CANCELLED, "Analysis cancelled"),
    ),
)
async def test_graph_activity_tracks_jobs_without_resetting_existing_graph(
    tmp_path: Path, terminal_status: GraphJobStatus, status_label: str
) -> None:
    app, case, previous = _app_with_previous_graph(tmp_path)
    job = _queued_job(case.investigation_id)

    async with app.run_test(size=(160, 48)) as pilot:
        app.open_investigation(case)
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, InvestigationWorkspaceScreen)
        screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-graph-tab"
        await pilot.pause()

        panel = screen.query_one("#graph-build-panel")
        activity = screen.query_one("#graph-build-activity", GraphBuildActivity)
        cancel = screen.query_one("#cancel-graph-analysis", Button)
        canvas = screen.query_one("#graph-canvas", GraphCanvas)
        assert not panel.display
        assert not activity.running
        assert not cancel.display
        assert canvas.graph is previous.graph
        selected = canvas.select_next()
        assert selected is not None
        canvas.zoom_in()
        await pilot.pause()
        zoom = canvas.zoom

        for status, stage, completed, expected_stage in (
            (GraphJobStatus.QUEUED, GraphRunStatus.QUEUED, 0, "Waiting"),
            (GraphJobStatus.RUNNING, GraphRunStatus.EXTRACTING, 2, "Reading pages"),
            (GraphJobStatus.RUNNING, GraphRunStatus.CONSOLIDATING, 6, "Comparing sources"),
        ):
            job = replace(
                job,
                status=status,
                progress=GraphAnalysisProgress(stage, completed, 6, "Safe progress message"),
            )
            screen._apply_graph_analysis_job(job)
            await pilot.pause()
            assert panel.display
            assert activity.running and activity.elapsed_seconds >= 15
            assert cancel.display and not cancel.disabled
            assert screen.query_one("#analyze-evidence", Button).disabled
            assert screen.query_one("#graph-preparation-mode", Select).disabled
            assert f"({completed}/6)" in screen.query_one("#graph-analysis-status").render().plain
            assert expected_stage.casefold() in (
                screen.query_one("#graph-build-stage", Static).render().plain.casefold()
            )
            assert "%" not in activity.render().plain
            assert canvas.graph is previous.graph
            assert canvas.selected_entity == selected
            assert canvas.zoom == zoom

        next_graph = replace(previous.graph, run_id=job.job_id)
        result = replace(previous, graph=next_graph, run=replace(previous.run, run_id=job.job_id))
        terminal = replace(
            job,
            status=terminal_status,
            result=result if terminal_status is GraphJobStatus.COMPLETED else None,
            error="Graph service unavailable" if terminal_status is GraphJobStatus.FAILED else None,
        )
        screen._apply_graph_analysis_job(terminal)
        await pilot.pause()
        assert not panel.display
        assert not activity.running
        assert not cancel.display
        assert not screen.query_one("#analyze-evidence", Button).disabled
        assert not screen.query_one("#graph-preparation-mode", Select).disabled
        assert status_label in screen.query_one("#graph-analysis-status").render().plain
        assert canvas.graph is (
            next_graph if terminal_status is GraphJobStatus.COMPLETED else previous.graph
        )
        if terminal_status is not GraphJobStatus.COMPLETED:
            assert canvas.selected_entity == selected
            assert canvas.zoom == zoom


async def test_graph_activity_compacts_on_resize_and_keeps_cancel_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, case, previous = _app_with_previous_graph(tmp_path)
    cancelled_cases: list[str] = []
    monkeypatch.setattr(app, "cancel_graph_analysis", cancelled_cases.append)
    job = replace(
        _queued_job(case.investigation_id),
        status=GraphJobStatus.RUNNING,
        progress=GraphAnalysisProgress(GraphRunStatus.EXTRACTING, 2, 6, "Reading pages"),
    )

    async with app.run_test(size=(160, 48)) as pilot:
        app.open_investigation(case)
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, InvestigationWorkspaceScreen)
        screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-graph-tab"
        screen._apply_graph_analysis_job(job)
        await pilot.pause()
        panel = screen.query_one("#graph-build-panel")
        copy = screen.query_one("#graph-build-copy")
        activity = screen.query_one("#graph-build-activity")
        assert panel.display and copy.display
        assert not activity.has_class("compact")
        expanded_height = panel.size.height

        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        cancel = screen.query_one("#cancel-graph-analysis", Button)
        canvas = screen.query_one("#graph-canvas", GraphCanvas)
        assert panel.display and not copy.display
        assert activity.has_class("compact")
        assert panel.size.height < expanded_height
        assert activity.region.right <= screen.size.width
        assert cancel.region.bottom <= screen.size.height
        assert cancel.region.right <= screen.size.width
        assert not cancel.region.overlaps(panel.region)
        assert canvas.graph is previous.graph
        assert canvas.size.width >= 40
        assert canvas.size.height >= 1
        assert await pilot.click("#cancel-graph-analysis")
        await pilot.pause()
        assert cancelled_cases == [case.investigation_id]

        await pilot.resize_terminal(160, 48)
        await pilot.pause()
        assert panel.display and copy.display
        assert not activity.has_class("compact")
        assert canvas.graph is previous.graph
