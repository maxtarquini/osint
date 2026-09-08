"""Exercise rendered graph geometry, not only the separate plain-text summary."""

from datetime import UTC, datetime

import pytest
from netext._core import Point
from textual.app import App, ComposeResult
from textual.geometry import Offset
from textual.widgets import Static, TabbedContent, TabPane

from raven.models import GraphEntity, GraphRelationship, InvestigationGraph
from raven.tui.widgets.graph import GraphCanvas


def graph_fixture(count=20, prefix="Entity", connected=False):
    entities = tuple(GraphEntity(str(i), "ORGANIZATION", f"{prefix} {i:02}") for i in range(count))
    edges = tuple(
        GraphRelationship(f"edge-{i}", str(i), str(i + 1), "REFERENCES")
        for i in range(count - 1)
        if connected and i % 3 != 2
    )
    return InvestigationGraph("case", "run", entities, edges, datetime.now(UTC))


class GraphApp(App):
    CSS = """
    TabbedContent, ContentSwitcher, TabPane { height: 1fr; padding: 0; }
    GraphCanvas { height: 1fr; width: 1fr; background: #102326; scrollbar-size: 1 1; }
    """

    def compose(self) -> ComposeResult:
        with TabbedContent(initial="other"):
            with TabPane("Other", id="other"):
                yield Static("Another section")
            with TabPane("Graph", id="graph"):
                yield GraphCanvas(id="canvas")


def rendered_text(canvas):
    return "\n".join("".join(s.text for s in row) for row in canvas._strip_segments)


async def show_graph(app, pilot, graph):
    canvas = app.query_one(GraphCanvas)
    canvas.set_graph(graph)
    app.query_one(TabbedContent).active = "graph"
    await pilot.pause()
    return canvas


async def test_graph_loaded_while_tab_is_hidden_replaces_empty_renderer():
    app = GraphApp()
    async with app.run_test(size=(130, 35)) as pilot:
        canvas = await show_graph(app, pilot, graph_fixture(prefix="First"))
        assert set(canvas._console_graph.node_buffers) == {str(i) for i in range(20)}
        assert "First 00" in rendered_text(canvas)
        assert "GRAPH EMPTY" not in rendered_text(canvas)
        app.query_one(TabbedContent).active = "other"
        await pilot.pause()
        canvas.set_graph(graph_fixture(9, prefix="Replacement"))
        app.query_one(TabbedContent).active = "graph"
        await pilot.pause()
        assert len(canvas._console_graph.node_buffers) == 9
        assert "Replacement 00" in rendered_text(canvas)
        assert "First" not in rendered_text(canvas)


@pytest.mark.parametrize("connected", [False, True])
async def test_fit_packs_components_with_readable_nonoverlapping_nodes(connected):
    graph = graph_fixture(24, connected=connected)
    app = GraphApp()
    async with app.run_test(size=(180, 42)) as pilot:
        canvas = await show_graph(app, pilot, graph)
        canvas.fit()
        await pilot.pause()
        buffers = list(canvas._console_graph.node_buffers.values())
        assert len({buffer.left_x for buffer in buffers}) > 1
        assert all(buffer.width > 5 and buffer.height > 1 for buffer in buffers)
        assert canvas._effective_zoom() >= 1
        assert "Entity 00" in rendered_text(canvas)
        assert "Entity 23" in rendered_text(canvas)
        assert len(canvas._console_graph.edge_buffers) == len(graph.relationships)
        if not connected:
            before = {
                key: (b.left_x, b.top_y) for key, b in canvas._console_graph.node_buffers.items()
            }
            canvas.select_entity("0")
            await pilot.pause()
            assert before == {
                key: (b.left_x, b.top_y) for key, b in canvas._console_graph.node_buffers.items()
            }
        for index, first in enumerate(buffers):
            for second in buffers[index + 1 :]:
                assert (
                    first.right_x < second.left_x
                    or second.right_x < first.left_x
                    or first.bottom_y < second.top_y
                    or second.bottom_y < first.top_y
                )
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert canvas._effective_zoom() >= 1
        assert "Entity 23" in rendered_text(canvas)
        assert canvas.max_scroll_y > 0 or canvas.max_scroll_x > 0
        await pilot.resize_terminal(180, 42)
        await pilot.pause()
        assert len({b.left_x for b in canvas._console_graph.node_buffers.values()}) > 1


async def test_zoom_buttons_use_requested_scale_and_fit_restores_readable_names():
    app = GraphApp()
    async with app.run_test(size=(100, 24)) as pilot:
        canvas = await show_graph(app, pilot, graph_fixture(40))
        canvas._set_zoom(0.4)
        canvas.zoom_in()
        canvas.zoom_in()
        assert canvas.zoom == pytest.approx(0.625)
        assert canvas.zoom_label == "62%"
        await pilot.pause()
        assert canvas._console_graph.zoom_x == pytest.approx(0.625)
        assert canvas._console_graph.zoom_y == pytest.approx(0.625)
        canvas.fit()
        await pilot.pause()
        assert canvas.zoom_label == "FIT"
        assert all(b.width > 5 for b in canvas._console_graph.node_buffers.values())


@pytest.mark.parametrize("horizontal", [False, True])
async def test_click_after_scrolling_selects_the_node_under_the_pointer(horizontal):
    app = GraphApp()
    async with app.run_test(size=(100, 24)) as pilot:
        canvas = await show_graph(app, pilot, graph_fixture(50, connected=horizontal))
        if horizontal:
            canvas._set_zoom(2)
            await pilot.pause()
        canvas.scroll_to(
            x=canvas.max_scroll_x if horizontal else 0,
            y=0 if horizontal else canvas.max_scroll_y,
            animate=False,
            immediate=True,
        )
        await pilot.pause()
        assert (canvas.scroll_offset.x if horizontal else canvas.scroll_offset.y) > 0
        target = None
        for (x, y), reference in canvas._reverse_click_map.items():
            position = canvas.view_to_widget_coordinates(Point(x, y))
            if (
                reference.type == "node"
                and 1 <= position.x < canvas.content_size.width - 1
                and 1 <= position.y < canvas.content_size.height - 1
            ):
                target = (reference.ref, position)
                break
        assert target is not None
        entity_id, position = target
        assert canvas.widget_to_view_coordinates(position) == Point(
            canvas._console_graph.full_viewport.x + position.x + canvas.scroll_offset.x,
            canvas._console_graph.full_viewport.y + position.y + canvas.scroll_offset.y,
        )
        assert canvas.view_to_widget_coordinates(
            canvas.widget_to_view_coordinates(Offset(3, 4))
        ) == Offset(3, 4)
        await pilot.click("#canvas", offset=position)
        await pilot.pause()
        assert canvas.selected_entity.entity_id == entity_id


async def test_canvas_spacers_use_the_canvas_background():
    app = GraphApp()
    async with app.run_test(size=(120, 32)) as pilot:
        canvas = await show_graph(app, pilot, graph_fixture(2, connected=True))
        line = canvas.render_line(canvas.size.height - 1)
        assert line.cell_length == canvas.size.width
        assert all(
            segment.style is not None and segment.style.bgcolor is not None for segment in line
        )
