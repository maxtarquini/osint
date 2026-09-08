"""Regression tests for the table-first graph browser."""

from datetime import UTC, datetime

from textual.app import App, ComposeResult

from raven.models import GraphEntity, GraphRelationship, InvestigationGraph
from raven.tui.widgets import GraphItemsTable


class GraphTableApp(App[None]):
    def compose(self) -> ComposeResult:
        yield GraphItemsTable(id="items")


async def test_graph_table_lists_relations_and_all_entities() -> None:
    person = GraphEntity("person", "PERSON", "Mario Rossi")
    company = GraphEntity("company", "ORGANIZATION", "Acme")
    relationship = GraphRelationship("works", "person", "company", "WORKS_FOR")
    graph = InvestigationGraph(
        "case",
        "run",
        (person, company),
        (relationship,),
        datetime.now(UTC),
    )
    app = GraphTableApp()

    async with app.run_test(size=(100, 24)) as pilot:
        table = app.query_one(GraphItemsTable)
        table.set_graph(graph)
        await pilot.pause()

        assert table.row_count == 3
        assert table.select_matching("works_for") == relationship
        assert table.selected_item() == relationship
        assert table.select_matching("Acme") is not None
        assert table.select_item("person") == person
