"""Keyboard-accessible graph review and original-source provenance."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Select, Static

from raven.models import EvidenceDocument, GraphEntity, GraphItemStatus, GraphRelationship


class GraphInspectorScreen(ModalScreen[tuple[str, str] | None]):
    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(
        self,
        item: GraphEntity | GraphRelationship,
        detail: str,
        documents: tuple[EvidenceDocument, ...],
    ) -> None:
        super().__init__()
        self.item = item
        self.detail = detail
        self.documents = tuple(d for d in documents if d.document_id in item.evidence_ids)

    def compose(self) -> ComposeResult:
        with Vertical(id="graph-inspector-dialog"):
            yield Static("GRAPH INSPECTOR", classes="panel-title")
            with VerticalScroll(id="graph-inspector-content"):
                yield Static(self.detail, markup=False)
                names = {d.document_id: d.original_name for d in self.documents}
                for span in self.item.support:
                    location = names.get(span.evidence_id, span.evidence_id)
                    if span.page_number:
                        location += f" · page {span.page_number}"
                    verification = (
                        "Quotation found in original"
                        if span.verified_original
                        else "Quotation requires source review"
                    )
                    yield Static(
                        f"\n{location}\n{verification}\n“{span.quote}”",
                        markup=False,
                    )
                if not self.item.support:
                    yield Static("\nNo original quotation supplied · review the source.")
                if isinstance(self.item, GraphEntity) and self.item.resolution_notes:
                    yield Static(
                        "\nRESOLUTION DECISIONS\n" + "\n".join(self.item.resolution_notes),
                        markup=False,
                    )
            if self.documents:
                with Horizontal(id="graph-inspector-sources"):
                    yield Select(
                        [(d.original_name, d.document_id) for d in self.documents],
                        value=self.documents[0].document_id,
                        allow_blank=False,
                        id="graph-source-select",
                    )
                    yield Button("Open source", id="graph-open-source")
            with Horizontal(id="graph-inspector-actions"):
                yield Button("Verify", id="inspect-verify", variant="success")
                yield Button("Reject", id="inspect-reject", variant="error")
                yield Button("Proposed", id="inspect-proposed")
                yield Button("Close", id="inspect-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        statuses = {
            "inspect-verify": GraphItemStatus.VERIFIED,
            "inspect-reject": GraphItemStatus.REJECTED,
            "inspect-proposed": GraphItemStatus.PROPOSED,
        }
        if event.button.id in statuses:
            self.dismiss(("review", statuses[event.button.id].value))
        elif event.button.id == "graph-open-source":
            self.dismiss(("source", str(self.query_one("#graph-source-select", Select).value)))
        else:
            self.dismiss(None)
