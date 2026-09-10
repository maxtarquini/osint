"""Evidence actions and view-state transitions for the workspace."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import replace
from pathlib import Path

from textual import work
from textual.containers import VerticalScroll
from textual.widgets import Button, Static

from raven.exceptions import InvestigationCancelledError, InvestigationError
from raven.models import EvidenceDocument, EvidenceIngestionState
from raven.tui.screens.document_catalog import DocumentCatalogScreen
from raven.tui.screens.file_picker import ConfirmEvidenceDelete, EvidenceFilePicker
from raven.tui.state import CatalogDocumentViewState, catalog_document_view_state
from raven.tui.widgets import EvidenceRow

logger = logging.getLogger(__name__)


class WorkspaceEvidenceActions:
    """Handle Evidence file operations outside the presentation screen."""

    def on_evidence_row_catalog_requested(self, event: EvidenceRow.CatalogRequested) -> None:
        self.app.push_screen(
            DocumentCatalogScreen(
                self.investigation,
                event.document,
                state_callback=self._catalog_state_updated,
            )
        )

    def on_evidence_row_generate_catalog_requested(
        self,
        event: EvidenceRow.GenerateCatalogRequested,
    ) -> None:
        state = self.view_state.evidence.catalog_states.get(event.document.document_id)
        self.app.push_screen(
            DocumentCatalogScreen(
                self.investigation,
                event.document,
                generate_on_open=True,
                force_on_open=state is not None and state.state == "ready",
                state_callback=self._catalog_state_updated,
            )
        )

    def on_evidence_row_catalog_state_refresh_requested(
        self,
        event: EvidenceRow.CatalogStateRefreshRequested,
    ) -> None:
        self.view_state.evidence.catalog_revision += 1
        revision = self.view_state.evidence.catalog_revision
        self._catalog_state_updated(
            event.document.document_id,
            "checking",
            0,
            event.document.page_count or 0,
            "Nuova lettura dello stato salvato",
        )
        self._load_catalog_states(revision, (event.document,))

    def on_evidence_row_reindex_requested(self, event: EvidenceRow.ReindexRequested) -> None:
        self._start_chat_index(document=event.document)

    def on_evidence_row_delete_requested(self, event: EvidenceRow.DeleteRequested) -> None:
        if self._busy or self._rag_indexing:
            return
        self.app.push_screen(
            ConfirmEvidenceDelete(event.document),
            lambda confirmed: self._delete_confirmed(event.document, confirmed),
        )

    def _open_file_picker(self) -> None:
        if not self._busy and not self._rag_indexing:
            self.app.push_screen(
                EvidenceFilePicker(self._last_evidence_source_directory),
                self._file_selected,
            )

    def _file_selected(self, path: Path | None) -> None:
        if path is None or self._busy:
            return
        self._last_evidence_source_directory = path.parent
        self._busy = True
        self._upload_cancel.clear()
        self.query_one("#add-evidence", Button).disabled = True
        self.query_one("#cancel-evidence-upload", Button).remove_class("hidden")
        self._set_operation_status("● Reading document...", "running")
        self._upload_evidence(path)

    @work(thread=True, exclusive=True, group="evidence-upload", exit_on_error=False)
    def _upload_evidence(self, path: Path) -> None:
        try:
            document = self._raven_app.add_evidence(
                self.investigation.investigation_id,
                path,
                self._upload_cancel.is_set,
            )
        except InvestigationCancelledError:
            self.app.call_from_thread(self._upload_cancelled)
        except InvestigationError as error:
            self.app.call_from_thread(self._operation_failed, str(error))
        except Exception as error:
            logger.error("Unexpected evidence upload failure. error_type=%s", type(error).__name__)
            self.app.call_from_thread(self._operation_failed, "Unable to add evidence; check log")
        else:
            self.app.call_from_thread(self._upload_succeeded, document)

    def _upload_succeeded(self, document: EvidenceDocument) -> None:
        if not self.is_mounted:
            return
        self.documents.append(document)
        for empty in self.query("#evidence-empty"):
            empty.remove()
        # Store the state before mounting: mount is asynchronous and the row's
        # children are not queryable until its compose cycle has completed.
        self._catalog_state_updated(
            document.document_id,
            "missing",
            0,
            document.page_count or 0,
            "",
        )
        self.query_one("#evidence-list", VerticalScroll).mount(
            EvidenceRow(
                document,
                catalog_state="missing",
                catalog_total=document.page_count or 0,
            )
        )
        self._finish_operation("● Evidence added", "success")

    def _upload_cancelled(self) -> None:
        if self.is_mounted:
            self._finish_operation("● Upload cancelled", "cancelled")

    def _delete_confirmed(self, document: EvidenceDocument, confirmed: bool | None) -> None:
        if not confirmed or self._busy:
            return
        self._busy = True
        self.query_one("#add-evidence", Button).disabled = True
        row = self.query_one(f"#evidence-{document.document_id}", EvidenceRow)
        row.query_one(".delete-evidence", Button).disabled = True
        self._set_operation_status("● Deleting evidence...", "running")
        self._delete_evidence(document)

    @work(thread=True, exclusive=True, group="evidence-delete", exit_on_error=False)
    def _delete_evidence(self, document: EvidenceDocument) -> None:
        try:
            self._raven_app.delete_evidence(document)
        except InvestigationError as error:
            self.app.call_from_thread(self._delete_failed, document, str(error))
        except Exception as error:
            logger.error(
                "Unexpected evidence deletion failure. error_type=%s", type(error).__name__
            )
            self.app.call_from_thread(
                self._delete_failed,
                document,
                "Unable to delete evidence; check log",
            )
        else:
            self.app.call_from_thread(self._delete_succeeded, document)

    def _delete_succeeded(self, document: EvidenceDocument) -> None:
        if not self.is_mounted:
            return
        self.documents = [
            item for item in self.documents if item.document_id != document.document_id
        ]
        self.view_state.evidence.catalog_states.pop(document.document_id, None)
        self.query_one(f"#evidence-{document.document_id}", EvidenceRow).remove()
        if not self.documents:
            self.query_one("#evidence-list", VerticalScroll).mount(
                Static(
                    "No evidence documents. Use Add evidence to select a file from disk.",
                    id="evidence-empty",
                )
            )
        self._finish_operation("● Evidence deleted", "success")

    def _delete_failed(self, document: EvidenceDocument, detail: str) -> None:
        if not self.is_mounted:
            return
        self.query_one(f"#evidence-{document.document_id}", EvidenceRow).query_one(
            ".delete-evidence", Button
        ).disabled = False
        self._operation_failed(detail)

    def _operation_failed(self, detail: str) -> None:
        if not self.is_mounted:
            return
        self._finish_operation("● Operation failed", "error")
        self.query_one("#evidence-operation-status", Static).tooltip = detail
        self.notify(detail, title="Evidence operation failed", severity="error")

    def _finish_operation(self, label: str, state: str) -> None:
        self._busy = False
        self.query_one("#add-evidence", Button).disabled = False
        self.query_one("#cancel-evidence-upload", Button).add_class("hidden")
        self._set_operation_status(f"{label} · {self._catalog_overview_text()}", state)
        self.query_one("#evidence-count", Static).update(self._count_label())
        self.query_one("#workspace-evidence-metric", Static).update(
            "EVIDENCE\n" + self._count_label()
        )
        self.query_one("#workspace-profile", Static).update(self._analysis_profile_label())
        self.query_one("#graph-evidence-detail", Static).update(
            "Knowledge base\n" + self._count_label()
        )
        self.query_one("#chat-context-summary", Static).update(self._chat_context_label())

    def _set_operation_status(self, label: str, state: str) -> None:
        status = self.query_one("#evidence-operation-status", Static)
        status.set_classes(state)
        status.update(label)
        status.tooltip = None

    def _catalog_overview_text(self) -> str:
        states = [
            self.view_state.evidence.catalog_states.get(
                document.document_id,
                CatalogDocumentViewState(),
            ).state
            for document in self.documents
        ]
        counts = Counter(states)
        labels = {
            "running": ("1 in corso", "{count} in corso"),
            "failed": ("1 con errore", "{count} con errore"),
            "incomplete": ("1 analisi incompleta", "{count} analisi incomplete"),
            "summary_pending": (
                "1 sintesi da completare",
                "{count} sintesi da completare",
            ),
            "cancelled": ("1 interrotto", "{count} interrotti"),
            "review": ("1 con avvisi", "{count} con avvisi"),
            "stale": ("1 da rigenerare", "{count} da rigenerare"),
            "unverified": ("1 stato non leggibile", "{count} stati non leggibili"),
            "missing": ("1 mai generato", "{count} mai generati"),
            "checking": ("1 in verifica", "{count} in verifica"),
            "ready": ("1 pronto", "{count} pronti"),
        }
        parts = []
        for state in labels:
            count = counts[state]
            if count:
                singular, plural = labels[state]
                parts.append(singular if count == 1 else plural.format(count=count))
        return "Cataloghi: " + (" · ".join(parts) if parts else "nessun documento")

    def _refresh_catalog_overview(self) -> None:
        if not self.is_mounted or self._busy or self._rag_indexing:
            return
        states = {
            self.view_state.evidence.catalog_states.get(
                document.document_id,
                CatalogDocumentViewState(),
            ).state
            for document in self.documents
        }
        style = (
            "running"
            if "running" in states
            else "error"
            if "failed" in states
            else "warning"
            if states
            & {"cancelled", "review", "stale", "unverified", "incomplete", "summary_pending"}
            else "success"
            if states == {"ready"}
            else "ready"
        )
        status = self.query_one("#evidence-operation-status", Static)
        status.set_classes(style)
        status.update("● " + self._catalog_overview_text())
        status.tooltip = (
            "Il catalogo delle pagine è distinto dall'indice RAG. Apri Catalogo per la causa "
            "completa oppure usa l'azione indicata sulla riga."
        )

    @work(thread=True, exclusive=True, group="rag-state", exit_on_error=False)
    def _load_rag_states(self, revision: int, documents: tuple[EvidenceDocument, ...]) -> None:
        try:
            states = self._owner_app.evidence_index_states(self.investigation, documents)
        except Exception as error:
            logger.warning(
                "Unable to verify RAG index. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
            states = {
                document.document_id: EvidenceIngestionState.UNVERIFIED for document in documents
            }
        self._owner_app.call_from_thread(self._show_rag_states, revision, states)

    def _show_rag_states(self, revision: int, states: dict[str, EvidenceIngestionState]) -> None:
        # A delayed manifest read must never overwrite a newer indexing operation.
        if not self.is_mounted or revision != self._rag_state_revision:
            return
        self.documents = [
            replace(
                document, ingestion_state=states.get(document.document_id, document.ingestion_state)
            )
            for document in self.documents
        ]
        for row in self.query(EvidenceRow):
            if row.document.document_id in states:
                row.set_ingestion_state(states[row.document.document_id])

    @work(thread=True, exclusive=True, group="catalog-state", exit_on_error=False)
    def _load_catalog_states(
        self,
        revision: int,
        documents: tuple[EvidenceDocument, ...],
    ) -> None:
        states: dict[str, CatalogDocumentViewState] = {}
        for document in documents:
            try:
                catalog = self._owner_app.load_evidence_catalog(
                    self.investigation,
                    document,
                    with_pages=False,
                )
            except Exception as error:
                logger.warning(
                    "Unable to verify page catalog. investigation_id=%s document_id=%s "
                    "error_type=%s error=%s",
                    self.investigation.investigation_id,
                    document.document_id,
                    type(error).__name__,
                    error,
                    exc_info=True,
                )
                states[document.document_id] = CatalogDocumentViewState(
                    "unverified",
                    detail="Impossibile verificare il catalogo salvato",
                )
            else:
                states[document.document_id] = (
                    CatalogDocumentViewState("missing")
                    if catalog is None
                    else catalog_document_view_state(catalog)
                )
        self._owner_app.call_from_thread(self._show_catalog_states, revision, states)

    def _show_catalog_states(
        self,
        revision: int,
        states: dict[str, CatalogDocumentViewState],
    ) -> None:
        if not self.is_mounted or revision != self.view_state.evidence.catalog_revision:
            return
        for document_id, state in states.items():
            self._catalog_state_updated(
                document_id,
                state.state,
                state.completed,
                state.total,
                state.detail,
            )

    def _catalog_state_updated(
        self,
        document_id: str,
        state: str,
        completed: int,
        total: int,
        detail: str,
    ) -> None:
        previous = self.view_state.evidence.catalog_states.get(document_id)
        if state == "running" and (previous is None or previous.state != "running"):
            self.view_state.evidence.catalog_revision += 1
        value = CatalogDocumentViewState(state, completed, total, detail)
        self.view_state.evidence.catalog_states[document_id] = value
        if not self.is_mounted:
            return
        for row in self.query(EvidenceRow):
            if row.document.document_id == document_id:
                row.set_catalog_state(state, completed, total, detail)
                break
        self._refresh_catalog_overview()
