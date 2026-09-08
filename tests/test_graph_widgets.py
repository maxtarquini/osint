"""Rendering regressions for the interactive investigation graph canvas."""

from datetime import UTC, datetime

from textual.app import App, ComposeResult

from raven.models import GraphEntity, InvestigationGraph
from raven.tui.widgets import GraphCanvas


class GraphWidgetApp(App[None]):
    def compose(self) -> ComposeResult:
        yield GraphCanvas(id="graph")


async def test_entity_only_graph_keeps_nodes_readable_in_small_viewport() -> None:
    entities = tuple(
        GraphEntity(
            entity_id=f"ip-{index}",
            entity_type="IP_ADDRESS",
            canonical_name=f"4.4.1.{index}",
        )
        for index in range(1, 15)
    )
    graph = InvestigationGraph(
        investigation_id="investigation",
        run_id="run",
        entities=entities,
        relationships=(),
        generated_at=datetime.now(UTC),
    )
    app = GraphWidgetApp()

    async with app.run_test(size=(80, 24)) as pilot:
        canvas = app.query_one(GraphCanvas)
        canvas.set_graph(graph)
        await pilot.pause()

        assert canvas._effective_zoom() >= 0.75
        assert all(buffer.width > 1 for buffer in canvas._console_graph.node_buffers.values())
        visible = "\n".join(canvas.render_line(row).text for row in range(canvas.size.height))
        assert "4.4.1." in visible
        assert "IP_ADDRESS" in visible
        assert (
            canvas.virtual_size.width > canvas.size.width
            or canvas.virtual_size.height > canvas.size.height
        )
