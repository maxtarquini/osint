"""Reusable evidence-document rows for investigation workspaces."""

from __future__ import annotations

from dataclasses import replace

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
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

CATALOG_STATE_LABELS = {
    "checking": "Verifica stato…",
    "missing": "Mai generato",
    "running": "In elaborazione",
    "ready": "Completo",
    "review": "Completo con avvisi",
    "cancelled": "Interrotto",
    "incomplete": "Analisi incompleta",
    "summary_pending": "Pagine complete",
    "failed": "Fallito",
    "stale": "Da rigenerare",
    "unverified": "Stato non leggibile",
}


class EvidenceRow(Horizontal):
    """One accessible evidence row with document-scoped actions."""

    can_focus = True
    BINDINGS = [
        Binding("enter", "open_catalog", "Open catalog", show=False),
        Binding("g", "generate_catalog", "Generate catalog", show=False),
        Binding("r", "reindex", "Reindex", show=False),
        Binding("d", "delete", "Delete", show=False),
    ]

    class CatalogRequested(Message):
        def __init__(self, document: EvidenceDocument) -> None:
            self.document = document
            super().__init__()

    class ReindexRequested(Message):
        def __init__(self, document: EvidenceDocument) -> None:
            self.document = document
            super().__init__()

    class GenerateCatalogRequested(Message):
        def __init__(self, document: EvidenceDocument) -> None:
            self.document = document
            super().__init__()

    class CatalogStateRefreshRequested(Message):
        def __init__(self, document: EvidenceDocument) -> None:
            self.document = document
            super().__init__()

    class DeleteRequested(Message):
        def __init__(self, document: EvidenceDocument) -> None:
            self.document = document
            super().__init__()

    def __init__(
        self,
        document: EvidenceDocument,
        *,
        catalog_state: str = "checking",
        catalog_completed: int = 0,
        catalog_total: int = 0,
        catalog_detail: str = "",
    ) -> None:
        self.document = document
        self.catalog_state = catalog_state
        self.catalog_completed = catalog_completed
        self.catalog_total = catalog_total
        self.catalog_detail = catalog_detail
        super().__init__(id=f"evidence-{document.document_id}", classes="evidence-row")

    def compose(self) -> ComposeResult:
        with Vertical(classes="evidence-document-info"):
            yield Static(self.document.original_name, classes="evidence-name", markup=False)
            yield Static(
                self._catalog_explanation(),
                classes=f"catalog-explanation {self.catalog_state}",
                markup=False,
            )
        yield Static(self.document.file_format, classes="evidence-format")
        yield Static(self.document.page_label, classes="evidence-pages")
        status = Static(
            STATE_LABELS[self.document.ingestion_state],
            classes=f"evidence-state {self.document.ingestion_state.value}",
        )
        status.tooltip = STATE_DETAILS.get(self.document.ingestion_state)
        with Horizontal(classes="evidence-statuses"):
            yield status
            catalog_status = Static(
                self._catalog_label(),
                classes=f"catalog-state {self.catalog_state}",
            )
            catalog_status.tooltip = self.catalog_detail or None
            yield catalog_status
        with Horizontal(classes="evidence-document-actions"):
            yield Button(
                "Catalogo",
                classes="open-evidence-catalog",
                tooltip="Apri e consulta il catalogo salvato per questo documento",
            )
            yield Button(
                self._catalog_action_label(),
                classes="generate-evidence-catalog",
                tooltip=self._catalog_action_tooltip(),
                disabled=self.catalog_state in {"checking", "running"},
            )
            yield Button("Reindicizza", classes="reindex-evidence")
            yield Button("Delete", classes="delete-evidence")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.has_class("delete-evidence"):
            event.stop()
            self.post_message(self.DeleteRequested(self.document))
        elif event.button.has_class("open-evidence-catalog"):
            event.stop()
            self.post_message(self.CatalogRequested(self.document))
        elif event.button.has_class("generate-evidence-catalog"):
            event.stop()
            self._request_catalog_action()
        elif event.button.has_class("reindex-evidence"):
            event.stop()
            self.post_message(self.ReindexRequested(self.document))

    def set_ingestion_state(self, state: EvidenceIngestionState) -> None:
        self.document = replace(self.document, ingestion_state=state)
        status = self.query_one(".evidence-state", Static)
        status.set_classes(f"evidence-state {state.value}")
        status.update(STATE_LABELS[state])
        status.tooltip = STATE_DETAILS.get(state)

    def set_catalog_state(
        self,
        state: str,
        completed: int = 0,
        total: int = 0,
        detail: str = "",
    ) -> None:
        self.catalog_state = state
        self.catalog_completed = completed
        self.catalog_total = total
        self.catalog_detail = detail
        for status in self.query(".catalog-state").results(Static):
            status.set_classes(f"catalog-state {state}")
            status.update(self._catalog_label())
            status.tooltip = detail or None
        for explanation in self.query(".catalog-explanation").results(Static):
            explanation.set_classes(f"catalog-explanation {state}")
            explanation.update(self._catalog_explanation())
        for generate in self.query(".generate-evidence-catalog").results(Button):
            generate.label = self._catalog_action_label()
            generate.tooltip = self._catalog_action_tooltip()
            generate.disabled = state in {"checking", "running"}

    def _catalog_label(self) -> str:
        if self.catalog_state == "running" and self.catalog_detail:
            stage = self.catalog_detail.split(" · ", 1)[0]
            if stage.startswith(("Analisi ", "Sintesi ")):
                return stage
        label = CATALOG_STATE_LABELS.get(self.catalog_state, self.catalog_state.title())
        if self.catalog_total > 0 and self.catalog_state in {
            "running",
            "ready",
            "review",
            "cancelled",
            "incomplete",
            "summary_pending",
            "failed",
        }:
            return f"{label} · {self.catalog_completed}/{self.catalog_total}"
        return label

    def _catalog_explanation(self) -> str:
        detail = " ".join(self.catalog_detail.split())
        if self.catalog_state == "checking":
            return "Lettura dello stato del catalogo salvato…"
        if self.catalog_state == "missing":
            return "Catalogo assente: seleziona Genera per analizzare le pagine."
        if self.catalog_state == "running":
            return detail or "Preparazione del documento in corso…"
        if self.catalog_state == "ready":
            return "Catalogo completo e disponibile."
        if self.catalog_state == "review":
            return detail or "Completato, ma alcune pagine richiedono verifica."
        if self.catalog_state == "cancelled":
            saved = (
                f"{self.catalog_completed} pagine salvate"
                if self.catalog_completed
                else "nessuna pagina salvata"
            )
            return f"Generazione interrotta: {saved}. Seleziona Riprendi."
        if self.catalog_state == "incomplete":
            detail = detail or (
                f"{self.catalog_completed}/{self.catalog_total} pagine salvate senza errori; "
                "l'esecuzione si è interrotta prima di completare il documento."
            )
            return detail.rstrip(".") + ". Seleziona Riprendi."
        if self.catalog_state == "summary_pending":
            detail = detail or (
                "Tutte le pagine sono state analizzate senza errori; "
                "la sintesi finale del documento non è stata completata."
            )
            return detail.rstrip(".") + ". Seleziona Completa."
        if self.catalog_state == "failed":
            return (
                f"Causa: {detail}"
                if detail
                else "Generazione fermata da un errore; apri Catalogo per i dettagli."
            )
        if self.catalog_state == "stale":
            return "Profilo, modello o documento cambiato: seleziona Aggiorna."
        if self.catalog_state == "unverified":
            reason = detail or "Raven non riesce a leggere lo stato salvato"
            return reason.rstrip(".") + ". Seleziona Verifica; non avvia l'analisi AI."
        return detail

    def _catalog_action_label(self) -> str:
        if self.catalog_state in {"checking", "running"}:
            return "Attendi"
        if self.catalog_state in {"cancelled", "review"}:
            return "Riprendi"
        if self.catalog_state == "incomplete":
            return "Riprendi"
        if self.catalog_state == "summary_pending":
            return "Completa"
        if self.catalog_state == "failed":
            return "Riprendi" if self.catalog_completed else "Riprova"
        if self.catalog_state == "stale":
            return "Aggiorna"
        if self.catalog_state == "unverified":
            return "Verifica"
        if self.catalog_state == "ready":
            return "Rigenera"
        return "Genera"

    def _catalog_action_tooltip(self) -> str:
        return {
            "running": "La catalogazione è già in corso in background",
            "cancelled": "Riprendi dalle pagine già salvate",
            "incomplete": "Riprendi dalla prima pagina non ancora salvata",
            "summary_pending": "Crea la sintesi finale riutilizzando tutte le pagine salvate",
            "review": "Riprova soltanto le pagine incomplete o non valide",
            "failed": "Riprendi dalle pagine salvate e riprova quella non riuscita",
            "stale": "Rigenera il catalogo con il profilo attuale",
            "unverified": "Riprova soltanto la lettura dello stato; non avvia l'analisi AI",
            "ready": "Rigenera da zero il catalogo completo",
        }.get(self.catalog_state, "Crea il catalogo analizzando le pagine del documento")

    def action_open_catalog(self) -> None:
        self.post_message(self.CatalogRequested(self.document))

    def action_reindex(self) -> None:
        self.post_message(self.ReindexRequested(self.document))

    def action_generate_catalog(self) -> None:
        self._request_catalog_action()

    def _request_catalog_action(self) -> None:
        if self.catalog_state == "unverified":
            self.post_message(self.CatalogStateRefreshRequested(self.document))
        elif self.catalog_state not in {"checking", "running"}:
            self.post_message(self.GenerateCatalogRequested(self.document))

    def action_delete(self) -> None:
        self.post_message(self.DeleteRequested(self.document))
