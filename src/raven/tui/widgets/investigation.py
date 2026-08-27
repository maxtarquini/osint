"""Reusable rows for the investigation catalog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Static

from raven.models import Investigation


class InvestigationRow(Horizontal):
    """Catalog row with explicit open and destructive delete actions."""

    class OpenRequested(Message):
        def __init__(self, investigation: Investigation) -> None:
            self.investigation = investigation
            super().__init__()

    class DeleteRequested(Message):
        def __init__(self, investigation: Investigation) -> None:
            self.investigation = investigation
            super().__init__()

    def __init__(self, investigation: Investigation) -> None:
        self.investigation = investigation
        super().__init__(
            id=f"investigation-{investigation.investigation_id}",
            classes="investigation-row",
        )

    def compose(self) -> ComposeResult:
        yield Static(self.investigation.name, classes="catalog-name", markup=False)
        yield Static(self.investigation.status.value.title(), classes="catalog-status")
        yield Static(
            self.investigation.updated_at.astimezone().strftime("%Y-%m-%d %H:%M"),
            classes="catalog-updated",
        )
        yield Static(
            str(len(self.investigation.evidence_documents)),
            classes="catalog-evidence-count",
        )
        with Horizontal(classes="catalog-actions"):
            yield Button("Open", classes="open-investigation")
            yield Button(
                "Delete",
                classes="delete-investigation-catalog",
                variant="error",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.has_class("open-investigation"):
            event.stop()
            self.post_message(self.OpenRequested(self.investigation))
        elif event.button.has_class("delete-investigation-catalog"):
            event.stop()
            self.post_message(self.DeleteRequested(self.investigation))
