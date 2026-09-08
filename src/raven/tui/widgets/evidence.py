"""Reusable evidence-document rows for investigation workspaces."""

from __future__ import annotations

from dataclasses import replace

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Static

from raven.models import EvidenceDocument, EvidenceIngestionState

STATE_LABELS = {
    EvidenceIngestionState.PENDING: "Pending",
    EvidenceIngestionState.PROCESSING: "Indexing…",
    EvidenceIngestionState.READY: "Indexed",
    EvidenceIngestionState.FAILED: "Index failed",
    EvidenceIngestionState.OUTDATED: "Da aggiornare",
    EvidenceIngestionState.UNVERIFIED: "Non verificato",
}


STATE_DETAILS = {
    EvidenceIngestionState.OUTDATED: (
        "L'indice è presente in Qdrant, ma usa una versione del formato, del documento "
        "o della lingua diversa da quella attuale. Reindicizza aggiorna solo questo documento."
    ),
    EvidenceIngestionState.UNVERIFIED: (
        "Impossibile verificare Qdrant. Questo stato non indica un fallimento dell'indicizzazione."
    ),
}


class EvidenceRow(Horizontal):
    """One accessible evidence row with document-scoped actions."""

    class CatalogRequested(Message):
        def __init__(self, document: EvidenceDocument) -> None:
            self.document = document
            super().__init__()

    class ReindexRequested(Message):
        def __init__(self, document: EvidenceDocument) -> None:
            self.document = document
            super().__init__()

    class DeleteRequested(Message):
        def __init__(self, document: EvidenceDocument) -> None:
            self.document = document
            super().__init__()

    def __init__(self, document: EvidenceDocument) -> None:
        self.document = document
        super().__init__(id=f"evidence-{document.document_id}", classes="evidence-row")

    def compose(self) -> ComposeResult:
        yield Static(self.document.original_name, classes="evidence-name", markup=False)
        yield Static(self.document.file_format, classes="evidence-format")
        yield Static(self.document.page_label, classes="evidence-pages")
        status = Static(
            STATE_LABELS[self.document.ingestion_state],
            classes=f"evidence-state {self.document.ingestion_state.value}",
        )
        status.tooltip = STATE_DETAILS.get(self.document.ingestion_state)
        yield status
        with Horizontal(classes="evidence-document-actions"):
            yield Button("Apri catalogo", classes="open-evidence-catalog")
            yield Button("Reindicizza", classes="reindex-evidence")
            yield Button("Delete", classes="delete-evidence")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.has_class("delete-evidence"):
            event.stop()
            self.post_message(self.DeleteRequested(self.document))
        elif event.button.has_class("open-evidence-catalog"):
            event.stop()
            self.post_message(self.CatalogRequested(self.document))
        elif event.button.has_class("reindex-evidence"):
            event.stop()
            self.post_message(self.ReindexRequested(self.document))

    def set_ingestion_state(self, state: EvidenceIngestionState) -> None:
        self.document = replace(self.document, ingestion_state=state)
        status = self.query_one(".evidence-state", Static)
        status.set_classes(f"evidence-state {state.value}")
        status.update(STATE_LABELS[state])
        status.tooltip = STATE_DETAILS.get(state)
