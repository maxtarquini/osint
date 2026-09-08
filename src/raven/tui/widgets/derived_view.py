"""Presentation shell for spatial and chronological investigation views."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from raven.config import UiLanguage
from raven.tui.widgets.workspace_chrome import WorkspaceEmptyState


class DerivedEvidenceView(Vertical):
    def __init__(self, kind: str, has_documents: bool, **kwargs) -> None:
        super().__init__(**kwargs)
        self.kind = kind
        self.has_documents = has_documents
        self.add_class("derived-workspace")

    def compose(self) -> ComposeResult:
        italian = self.app.settings.interface_language is UiLanguage.ITALIAN
        spatial = self.kind == "map"
        title = (
            ("Luoghi" if spatial else "Cronologia")
            if italian
            else ("Locations" if spatial else "Timeline")
        )
        with Horizontal(classes="derived-heading"):
            with Vertical(classes="derived-heading-copy"):
                yield Static(
                    "ESPLORA LE EVIDENZE" if italian else "EXPLORE YOUR EVIDENCE",
                    classes="section-kicker",
                )
                yield Static(title, classes="view-title")
                yield Static(
                    "Il contesto geografico del caso"
                    if italian and spatial
                    else "La sequenza temporale del caso"
                    if italian
                    else "The geographic context of your case"
                    if spatial
                    else "The sequence behind your investigation",
                    classes="view-subtitle",
                )
            yield Static("0", id=f"{self.kind}-count", classes="derived-count")
        yield WorkspaceEmptyState(
            self.kind,
            self.has_documents,
            id=f"{self.kind}-empty",
        )
        with VerticalScroll(id=f"{self.kind}-results", classes="derived-results hidden"):
            yield Static("", id=f"graph-{self.kind}-view", markup=False)
        with Horizontal(classes="derived-footnote"):
            yield Static("◆  " + ("Collegato alle fonti" if italian else "Linked to sources"))
            yield Static(
                "Le posizioni richiedono coordinate nelle evidenze."
                if italian and spatial
                else "Gli eventi conservano date e riferimenti originali."
                if italian
                else "Locations require coordinates in your evidence."
                if spatial
                else "Events retain their original dates and source references."
            )

    def show_results(self, content: str, count: int) -> None:
        italian = self.app.settings.interface_language is UiLanguage.ITALIAN
        noun = (
            ("LUOGHI" if self.kind == "map" else "EVENTI")
            if italian
            else ("LOCATIONS" if self.kind == "map" else "EVENTS")
        )
        self.query_one(f"#{self.kind}-count", Static).update(f"{count}\n{noun}")
        self.query_one(f"#{self.kind}-empty").set_class(count > 0, "hidden")
        self.query_one(f"#{self.kind}-results").set_class(count == 0, "hidden")
        self.query_one(f"#graph-{self.kind}-view", Static).update(content)
