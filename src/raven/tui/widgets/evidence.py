"""Reusable evidence-document DataTable for investigation workspaces."""

from __future__ import annotations

from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable

from raven.models import EvidenceDocument, EvidenceIngestionState
from raven.models.catalog import DocumentCatalog
from raven.tui.i18n import tr


def evidence_state_label(state: EvidenceIngestionState) -> str:
    return {
        EvidenceIngestionState.PENDING: "Pending",
        EvidenceIngestionState.PROCESSING: "Processing",
        EvidenceIngestionState.READY: "Ready",
        EvidenceIngestionState.FAILED: "Failed",
    }[state]


class EvidenceTable(DataTable[str]):
    """Aligned, keyboard-first Evidence manifest with independent processing lanes."""

    BINDINGS = [
        Binding("enter", "inspect", "Inspect"),
        Binding("d", "delete", "Delete"),
    ]

    class InspectRequested(Message):
        def __init__(self, document: EvidenceDocument) -> None:
            self.document = document
            super().__init__()

    class DeleteRequested(Message):
        def __init__(self, document: EvidenceDocument) -> None:
            self.document = document
            super().__init__()

    class Highlighted(Message):
        def __init__(self, document: EvidenceDocument) -> None:
            super().__init__()
            self.document = document

    def __init__(self, documents: tuple[EvidenceDocument, ...]) -> None:
        super().__init__(id="evidence-table", cursor_type="row", zebra_stripes=True)
        self._documents = {document.document_id: document for document in documents}

    def on_mount(self) -> None:
        language = self.app.settings.interface_language  # type: ignore[attr-defined]
        self.add_column(tr(language, "file", "File"), key="name", width=20)
        self.add_column("Catalog", key="catalog", width=19)
        self.add_column(tr(language, "format", "Format"), key="format", width=6)
        self.add_column(tr(language, "pages", "Pages"), key="pages", width=5)
        self.add_column(tr(language, "evidence", "Evidence"), key="evidence", width=10)
        self.add_column("RAG", key="rag", width=10)
        self.add_column(tr(language, "graph", "Graph"), key="graph", width=10)
        for document in self._documents.values():
            self.add_document(document)

    def add_document(self, document: EvidenceDocument) -> None:
        self._documents[document.document_id] = document
        cells = self._cells(document)
        self.add_row(cells[0], "Not cataloged", *cells[1:], key=document.document_id)

    def update_catalog(self, document_id: str, catalog: DocumentCatalog | None) -> None:
        if document_id in self._documents:
            self.update_cell(
                document_id, "catalog", catalog.progress_label if catalog else "Not cataloged"
            )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        document = self._documents.get(str(event.row_key.value))
        if document is not None:
            self.post_message(self.Highlighted(document))

    def update_document(self, document: EvidenceDocument) -> None:
        self._documents[document.document_id] = document
        for key, value in zip(
            ("name", "format", "pages", "evidence", "rag", "graph"),
            self._cells(document),
            strict=True,
        ):
            self.update_cell(document.document_id, key, value)

    def remove_document(self, document_id: str) -> None:
        self._documents.pop(document_id, None)
        self.remove_row(document_id)

    def action_inspect(self) -> None:
        document = self._selected_document()
        if document is not None:
            self.post_message(self.InspectRequested(document))

    def action_delete(self) -> None:
        document = self._selected_document()
        if document is not None:
            self.post_message(self.DeleteRequested(document))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        document = self._documents.get(str(event.row_key.value))
        if document is not None:
            self.post_message(self.InspectRequested(document))

    def _selected_document(self) -> EvidenceDocument | None:
        if self.row_count == 0:
            return None
        row_key, _column_key = self.coordinate_to_cell_key(self.cursor_coordinate)
        return self._documents.get(str(row_key.value))

    @staticmethod
    def _cells(document: EvidenceDocument) -> tuple[str, ...]:
        return (
            document.original_name,
            document.file_format,
            document.page_label,
            evidence_state_label(document.ingestion_state),
            evidence_state_label(document.rag_state),
            evidence_state_label(document.graph_state),
        )
