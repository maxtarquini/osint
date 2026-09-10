"""Graph details can be resized with real mouse capture and keyboard input."""

import pytest
from test_graph_activity_workspace import _app_with_previous_graph
from textual.widgets import TabbedContent

from raven.tui.widgets.graph import GraphCanvas
from raven.tui.widgets.resizable_split import PaneDivider, ResizableSplit


async def open_graph(app, pilot, case):
    app.open_investigation(case)
    await app.workers.wait_for_complete()
    await pilot.pause()
    app.screen.query_one("#workspace-tabs", TabbedContent).active = "workspace-graph-tab"
    await pilot.pause()
    return app.screen.query_one(ResizableSplit), app.screen.query_one(PaneDivider)


async def drag(pilot, divider, target_x):
    y = divider.region.y + divider.size.height // 2
    await pilot.mouse_down(divider, offset=(1, divider.size.height // 2))
    assert pilot.app.mouse_captured is divider
    await pilot.hover(offset=(target_x, y))
    await pilot.mouse_up(offset=(target_x, y))
    await pilot.pause()
    assert pilot.app.mouse_captured is None


async def test_mouse_drag_resizes_details_preserving_graph_selection_and_zoom(tmp_path):
    app, case, previous = _app_with_previous_graph(tmp_path)
    async with app.run_test(size=(180, 48)) as pilot:
        split, divider = await open_graph(app, pilot, case)
        canvas = app.screen.query_one(GraphCanvas)
        selected = canvas.select_next()
        canvas.zoom_in()
        zoom = canvas.zoom
        await pilot.pause()
        initial = split.details_width
        assert initial >= 50
        start = divider.region.x + 1
        await drag(pilot, divider, start - 15)
        assert split.details_width == initial + 15
        assert canvas.graph is previous.graph and canvas.selected_entity == selected
        assert canvas.zoom == zoom
        assert canvas._console_graph.node_buffers
        # Captured dragging still works when the pointer is far outside the handle.
        await drag(pilot, divider, 1)
        assert app.screen.query_one("#graph-visual-panel").size.width >= 40
        await drag(pilot, divider, 179)
        assert split.details_width >= 36
        assert app.screen.query_one("#graph-details-panel").region.right <= 180
        width = split.details_width
        await pilot.hover(offset=(20, 30))
        assert split.details_width == width


@pytest.mark.parametrize("size", [(80, 24), (160, 44)])
async def test_keyboard_resize_reset_and_compact_limits(tmp_path, size):
    app, case, _ = _app_with_previous_graph(tmp_path)
    async with app.run_test(size=size) as pilot:
        split, divider = await open_graph(app, pilot, case)
        original = split.details_width
        divider.focus()
        await pilot.press("left")
        assert split.details_width > original
        await pilot.press("home")
        assert split.details_width == original
        await pilot.press(*(["right"] * 12))
        assert split.details_width >= 28
        assert app.screen.query_one("#graph-visual-panel").region.width >= 40
        visual = app.screen.query_one("#graph-visual-panel")
        for control in ("open-graph-claims", "fit-graph", "zoom-in-graph", "zoom-out-graph"):
            button = app.screen.query_one(f"#{control}")
            assert visual.region.x <= button.region.x < button.region.right <= visual.region.right
        await pilot.click(divider, offset=(1, 2), times=2)
        assert split.details_width == original
        await pilot.press("tab")
        assert app.focused is not divider


async def test_details_panel_can_be_collapsed_for_graph_first_inspection(tmp_path):
    app, case, _ = _app_with_previous_graph(tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        split, _ = await open_graph(app, pilot, case)
        details = app.screen.query_one("#graph-details-panel")

        await pilot.click("#toggle-graph-details")
        await pilot.pause()
        assert split.has_class("details-collapsed")
        assert not details.display
        assert app.screen.query_one("#graph-visual-panel").region.width == split.region.width

        await pilot.click("#toggle-graph-details")
        await pilot.pause()
        assert not split.has_class("details-collapsed")
        assert details.display


async def test_split_preserves_preference_across_tabs_and_terminal_resize_releases_capture(
    tmp_path,
):
    app, case, _ = _app_with_previous_graph(tmp_path)
    async with app.run_test(size=(180, 48)) as pilot:
        split, divider = await open_graph(app, pilot, case)
        await drag(pilot, divider, divider.region.x - 12)
        wide = split.details_width
        tabs = app.screen.query_one("#workspace-tabs", TabbedContent)
        await pilot.mouse_down(divider, offset=(1, 2))
        tabs.active = "workspace-evidence-tab"
        await pilot.pause()
        assert app.mouse_captured is None
        tabs.active = "workspace-graph-tab"
        await pilot.pause()
        assert split.details_width == wide
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert 28 <= split.details_width <= 36
        assert app.screen.query_one("#graph-details-panel").region.right <= 80
        await pilot.resize_terminal(180, 48)
        await pilot.pause()
        assert split.details_width == wide
        await pilot.mouse_down(divider, offset=(1, 2))
        await pilot.resize_terminal(160, 44)
        await pilot.pause()
        assert app.mouse_captured is None
