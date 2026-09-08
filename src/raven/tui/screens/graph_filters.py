"""Compact graph filter editor."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Select

from raven.models import EvidenceDocument
from raven.models.graph_filter import GraphFilters


class GraphFiltersScreen(ModalScreen[GraphFilters | None]):
    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, filters: GraphFilters, documents: tuple[EvidenceDocument, ...]) -> None:
        super().__init__()
        self.filters = filters
        self.documents = documents

    def compose(self) -> ComposeResult:
        with Vertical(id="graph-filter-dialog"):
            yield Label("Status")
            yield Select(
                [(s.title(), s) for s in ("all", "proposed", "verified", "rejected")],
                value=self.filters.status,
                allow_blank=False,
                id="filter-status",
            )
            yield Label("Item type")
            yield Select(
                [(s.title(), s) for s in ("all", "entity", "relationship")],
                value=self.filters.kind,
                allow_blank=False,
                id="filter-kind",
            )
            yield Label("Source document")
            yield Select(
                [
                    ("All sources", "all"),
                    *((d.original_name, d.document_id) for d in self.documents),
                ],
                value=self.filters.source,
                allow_blank=False,
                id="filter-source",
            )
            yield Label("Minimum confidence · model estimate")
            yield Select(
                [(f"{n}%", n) for n in (0, 50, 75, 90)],
                value=self.filters.confidence,
                allow_blank=False,
                id="filter-confidence",
            )
            with Horizontal(id="graph-filter-actions"):
                yield Button("Reset", id="reset-graph-filters")
                yield Button("Apply", id="apply-graph-filters", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "reset-graph-filters":
            self.dismiss(GraphFilters())
        else:
            self.dismiss(
                GraphFilters(
                    str(self.query_one("#filter-status", Select).value),
                    str(self.query_one("#filter-kind", Select).value),
                    str(self.query_one("#filter-source", Select).value),
                    int(self.query_one("#filter-confidence", Select).value),
                )
            )
