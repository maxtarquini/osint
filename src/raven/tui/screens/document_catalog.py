"""Browse, generate and refresh one document's persistent page catalog."""

import logging
from collections.abc import Callable
from threading import Event
from time import monotonic

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Static, TabbedContent, TabPane, TextArea

from raven.exceptions import (
    GraphAgentError,
    InvestigationChatCancelledError,
    InvestigationError,
)
from raven.tui.state import catalog_document_view_state

logger = logging.getLogger(__name__)

CatalogStateCallback = Callable[[str, str, int, int, str], None]


class DocumentCatalogScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Chiudi"), Binding("/", "search", "Cerca pagine")]

    def __init__(
        self,
        investigation,
        document,
        *,
        generate_on_open=False,
        force_on_open=False,
        state_callback: CatalogStateCallback | None = None,
    ):
        super().__init__()
        self.investigation = investigation
        self.document = document
        self._generate_on_open = generate_on_open
        self._force_on_open = force_on_open
        self._state_callback = state_callback
        self.catalog = None
        self.filtered_pages = []
        self._cataloging = False
        self._catalog_force = False
        self._catalog_cancel = Event()
        self._catalog_progress_completed = 0
        self._catalog_progress_total = document.page_count or 0
        self._catalog_stage = "Preparazione del documento"
        self._catalog_stage_started_at = monotonic()

    def compose(self) -> ComposeResult:
        with Vertical(id="saved-catalog-dialog"):
            yield Static(self.document.original_name, id="saved-catalog-title", markup=False)
            yield Static("Caricamento catalogo salvato…", id="saved-catalog-status", markup=False)
            with TabbedContent(initial="saved-catalog-overview"):
                with TabPane("Riepilogo", id="saved-catalog-overview"):
                    yield TextArea("", read_only=True, id="saved-catalog-summary", soft_wrap=True)
                with TabPane("Pagine", id="saved-catalog-pages"):
                    yield Input(
                        placeholder="Cerca titolo, categoria, entità o testo",
                        id="saved-catalog-search",
                    )
                    with Horizontal(id="saved-catalog-body"):
                        yield DataTable(
                            id="saved-catalog-table", cursor_type="row", zebra_stripes=True
                        )
                        yield TextArea("", read_only=True, id="saved-catalog-page", soft_wrap=True)
                with TabPane("Provenienza", id="saved-catalog-provenance-tab"):
                    yield TextArea(
                        "", read_only=True, id="saved-catalog-provenance", soft_wrap=True
                    )
            with Horizontal(id="saved-catalog-actions"):
                yield Button("Genera catalogo", id="generate-saved-catalog", variant="primary")
                yield Button("Annulla", id="cancel-saved-catalog", classes="hidden")
                yield Button("Aggiorna", id="refresh-saved-catalog")
                yield Button("Chiudi", id="close-saved-catalog")

    def on_mount(self):
        # A thread worker can outlive this modal. Keep the owning app instead of
        # resolving ``self.app`` after the screen has been dismissed.
        self._owner_app = self.app
        self.on_resize()
        self.query_one("#saved-catalog-table", DataTable).add_columns("Pagina", "Stato", "Titolo")
        self.set_interval(1.0, self._refresh_running_status)
        self._load()

    def on_resize(self):
        self.set_class(self.size.width < 100, "narrow-catalog-reader")

    def action_close(self):
        if self._cataloging:
            self.notify(
                "La catalogazione continua in background; lo stato resta visibile nella riga.",
                title="Catalogazione pagine",
            )
        self.dismiss(None)

    def action_search(self):
        self.query_one(TabbedContent).active = "saved-catalog-pages"
        self.query_one("#saved-catalog-search", Input).focus()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "close-saved-catalog":
            self.action_close()
        elif event.button.id == "generate-saved-catalog":
            self.call_after_refresh(self._start_cataloging_from_button, event.button)
        elif event.button.id == "cancel-saved-catalog":
            self._catalog_cancel.set()
            event.button.disabled = True
            self.query_one("#saved-catalog-status", Static).update(
                "Annullamento richiesto: attendo la conclusione della chiamata attiva…"
            )
        elif event.button.id == "refresh-saved-catalog":
            self.query_one("#refresh-saved-catalog", Button).disabled = True
            self._load()

    def _start_cataloging_from_button(self, button: Button) -> None:
        state = (
            catalog_document_view_state(self.catalog).state if self.catalog is not None else None
        )
        self._start_cataloging(force=state in {"ready", "stale"})
        button.remove_class("-active")

    def _start_cataloging(self, *, force: bool):
        if self._cataloging:
            return
        self._cataloging = True
        self._catalog_force = force
        self._catalog_cancel.clear()
        generate = self.query_one("#generate-saved-catalog", Button)
        generate.disabled = True
        generate.label = "Generazione in corso…"
        self.query_one("#refresh-saved-catalog", Button).disabled = True
        cancel = self.query_one("#cancel-saved-catalog", Button)
        cancel.disabled = False
        cancel.remove_class("hidden")
        self.query_one("#saved-catalog-status", Static).update(
            "Catalogazione avviata · preparazione del documento…"
        )
        previous = self.catalog
        if previous is None:
            detail = "Nessun catalogo precedente. Le pagine completate saranno salvate subito."
        elif force:
            detail = (
                f"Rigenerazione completa richiesta. Il catalogo precedente era "
                f"{previous.state} ({previous.completed}/{previous.total} pagine)."
            )
        else:
            detail = (
                f"Ripresa del catalogo precedente: {previous.completed}/{previous.total} "
                "pagine già completate saranno riutilizzate."
            )
        self.query_one("#saved-catalog-summary", TextArea).load_text(
            "CATALOGAZIONE IN CORSO\n\n"
            "La barra superiore mostra la fase corrente e da quanto tempo Raven attende "
            "la risposta del nodo AI. Una singola pagina può richiedere alcuni minuti.\n\n" + detail
        )
        completed = previous.completed if previous is not None and not force else 0
        total = previous.total if previous is not None else (self.document.page_count or 0)
        self._catalog_progress_completed = completed
        self._catalog_progress_total = total
        self._catalog_stage = "Preparazione del documento"
        self._catalog_stage_started_at = monotonic()
        self._publish_catalog_state("running", completed, total, "Preparazione della catalogazione")
        self._refresh_running_status()
        self._generate_catalog()

    @work(thread=True, exclusive=True, group="generate-document-catalog", exit_on_error=False)
    def _generate_catalog(self):
        try:
            catalog = self._owner_app.catalog_evidence_document(
                self.investigation,
                self.document,
                self._catalog_cancel.is_set,
                self._catalog_progress,
                force=self._catalog_force,
            )
        except InvestigationChatCancelledError:
            catalog = self._load_after_generation()
            self._owner_app.call_from_thread(
                self._generation_finished,
                catalog,
                "Catalogazione annullata; le pagine completate restano salvate.",
                "warning",
            )
        except (GraphAgentError, InvestigationError) as error:
            catalog = self._load_after_generation()
            self._owner_app.call_from_thread(
                self._generation_finished,
                catalog,
                str(error),
                "error",
            )
        except Exception as error:
            logger.exception(
                "Unexpected catalog generation failure. investigation_id=%s document_id=%s "
                "error_type=%s error=%s",
                self.investigation.investigation_id,
                self.document.document_id,
                type(error).__name__,
                error,
            )
            catalog = self._load_after_generation()
            self._owner_app.call_from_thread(
                self._generation_finished,
                catalog,
                "Impossibile completare la catalogazione; verifica configurazione e log.",
                "error",
            )
        else:
            self._owner_app.call_from_thread(self._generation_finished, catalog, "", "success")

    def _load_after_generation(self):
        try:
            return self._owner_app.load_evidence_catalog(self.investigation, self.document)
        except Exception as error:
            logger.warning(
                "Unable to reload catalog after generation. investigation_id=%s document_id=%s "
                "error_type=%s",
                self.investigation.investigation_id,
                self.document.document_id,
                type(error).__name__,
            )
            return None

    def _catalog_progress(self, progress):
        try:
            self._owner_app.call_from_thread(self._show_catalog_progress, progress)
        except Exception as error:
            # Progress is observational: a transient UI update failure must not
            # abort the persisted catalog generation running in this thread.
            logger.warning(
                "Unable to render catalog progress. investigation_id=%s document_id=%s "
                "error_type=%s error=%s",
                self.investigation.investigation_id,
                self.document.document_id,
                type(error).__name__,
                error,
                exc_info=True,
            )

    def _show_catalog_progress(self, progress):
        if progress.detail != self._catalog_stage:
            self._catalog_stage = progress.detail
            self._catalog_stage_started_at = monotonic()
        self._catalog_progress_completed = progress.completed
        self._catalog_progress_total = progress.total
        self._publish_catalog_state("running", progress.completed, progress.total, progress.detail)
        if not self.is_mounted or not self._cataloging:
            return
        self._refresh_running_status()

    def _refresh_running_status(self) -> None:
        if not self.is_mounted or not self._cataloging:
            return
        elapsed = int(monotonic() - self._catalog_stage_started_at)
        total = self._catalog_progress_total
        progress = (
            f"{self._catalog_progress_completed}/{total} pagine salvate"
            if total
            else f"{self._catalog_progress_completed} pagine salvate"
        )
        stage = self._catalog_stage or "Elaborazione"
        wait = "risposta AI in attesa" if stage.startswith("Analisi ") else "fase attiva"
        label = f"● Generazione attiva · {progress} · {stage} · {wait} da {elapsed}s"
        for status in self.query("#saved-catalog-status").results(Static):
            status.update(label)

    def _generation_finished(self, catalog, detail: str, severity: str):
        self._cataloging = False
        view = catalog_document_view_state(catalog) if catalog is not None else None
        state = (
            view.state if view is not None else ("cancelled" if severity == "warning" else "failed")
        )
        completed = view.completed if view is not None else 0
        total = view.total if view is not None else (self.document.page_count or 0)
        state_detail = view.detail if view is not None else detail
        self._publish_catalog_state(state, completed, total, state_detail)
        if not self.is_mounted:
            notification_severity = severity if severity in {"warning", "error"} else "information"
            self._owner_app.notify(
                detail or "Catalogazione completata in background.",
                title=self.document.original_name,
                severity=notification_severity,
            )
            return
        self._show(catalog, detail if catalog is None else "")
        if detail:
            self.notify(
                detail,
                title="Catalogazione pagine",
                severity=severity,
            )

    @work(thread=True, exclusive=True, group="read-document-catalog", exit_on_error=False)
    def _load(self):
        try:
            catalog = self._owner_app.load_evidence_catalog(self.investigation, self.document)
        except InvestigationError as error:
            self._owner_app.call_from_thread(self._show, None, str(error))
        except Exception as error:
            logger.warning(
                "Unexpected catalog read failure. investigation_id=%s document_id=%s error_type=%s",
                self.investigation.investigation_id,
                self.document.document_id,
                type(error).__name__,
            )
            self._owner_app.call_from_thread(
                self._show, None, "Impossibile leggere il catalogo salvato."
            )
        else:
            self._owner_app.call_from_thread(self._show, catalog, "")

    def _show(self, catalog, error):
        if not self.is_mounted:
            return
        self.catalog = catalog
        view = catalog_document_view_state(catalog) if catalog is not None else None
        self._publish_catalog_state(
            view.state if view is not None else ("unverified" if error else "missing"),
            view.completed if view is not None else 0,
            view.total if view is not None else (self.document.page_count or 0),
            error or (view.detail if view is not None else ""),
        )
        self.query_one("#refresh-saved-catalog", Button).disabled = False
        generate = self.query_one("#generate-saved-catalog", Button)
        generate.disabled = False
        generate.label = (
            {
                "ready": "Rigenera catalogo",
                "stale": "Aggiorna catalogo",
                "summary_pending": "Completa catalogo",
                "incomplete": "Riprendi catalogo",
                "cancelled": "Riprendi catalogo",
                "failed": "Riprova catalogo",
                "review": "Riprendi catalogo",
            }.get(view.state, "Genera catalogo")
            if view is not None
            else "Genera catalogo"
        )
        cancel = self.query_one("#cancel-saved-catalog", Button)
        cancel.disabled = False
        cancel.add_class("hidden")
        if catalog is None:
            status = error or "Nessun catalogo salvato per questo documento."
            summary = status + "\n\nLa reindicizzazione RAG aggiorna la ricerca nei documenti; "
            summary += "la catalogazione delle pagine è un'elaborazione distinta."
            provenance = ""
        else:
            if view.state == "summary_pending":
                status = (
                    f"Pagine analizzate · {catalog.completed}/{catalog.total} · "
                    "nessun errore pagina · sintesi finale da completare"
                )
            elif view.state == "incomplete":
                status = (
                    f"Analisi interrotta · {catalog.completed}/{catalog.total} pagine salvate · "
                    "nessun errore nelle pagine salvate"
                )
            else:
                status = (
                    f"Catalogo salvato · {catalog.completed}/{catalog.total} pagine · "
                    f"{catalog.failed_count} errori · {catalog.review_count} da verificare"
                )
            if (
                catalog.domain != self.investigation.analysis_domain
                or catalog.language != self.investigation.analysis_language.value
            ):
                status += " · Profilo diverso dall'indagine attuale"
            state_label = {
                "summary_pending": "SINTESI DA COMPLETARE",
                "incomplete": "ANALISI INCOMPLETA",
                "ready": "COMPLETO",
                "review": "COMPLETO CON AVVISI",
                "failed": "FALLITO",
                "cancelled": "INTERROTTO",
                "stale": "DA AGGIORNARE",
            }.get(view.state, view.state.upper())
            summary = (
                f"{catalog.domain} · {state_label}\n\n"
                + ("RIEPILOGO AI" if catalog.summary_state == "ready" else "SINTESI DELLE PAGINE")
                + f"\n\n{catalog.summary}\n\nCATEGORIE\n"
                + "\n".join(catalog.categories)
                + "\n\nTEMI\n"
                + ", ".join(catalog.topics)
            )
            if view.state in {"summary_pending", "incomplete"}:
                summary += "\n\nCOSA È SUCCESSO\n" + view.detail
            elif catalog.error:
                summary += "\n\nERRORE REGISTRATO\n" + catalog.error
            provenance = (
                f"Indagine: {catalog.investigation_id}\nDocumento: {catalog.document_id}\n"
                f"Dominio salvato: {catalog.domain}\nLingua salvata: {catalog.language}\n"
                f"Modello: {catalog.model}\nAggiornamento: {catalog.updated_at}\n"
                f"Versioni dizionario: {', '.join(map(str, catalog.dictionary_versions))}\n"
                f"Impronta dizionario: {catalog.dictionary_hash}\n"
                f"Generazione: {catalog.signature}\n\n"
                "Le schede rappresentano analisi delle fonti; verificare attribuzioni, "
                "incertezze e citazioni prima di usarle come conclusioni investigative."
            )
        self.query_one("#saved-catalog-status", Static).update(status)
        self.query_one("#saved-catalog-summary", TextArea).load_text(summary)
        self.query_one("#saved-catalog-provenance", TextArea).load_text(provenance)
        self._filter_pages()
        if self._generate_on_open:
            self._generate_on_open = False
            force = self._force_on_open
            self._force_on_open = False
            self._start_cataloging(force=force)

    def _publish_catalog_state(
        self, state: str, completed: int, total: int, detail: str = ""
    ) -> None:
        if self._state_callback is not None:
            try:
                self._state_callback(
                    self.document.document_id,
                    state,
                    completed,
                    total,
                    detail,
                )
            except Exception as error:
                logger.warning(
                    "Unable to publish catalog state. investigation_id=%s document_id=%s "
                    "state=%s error_type=%s error=%s",
                    self.investigation.investigation_id,
                    self.document.document_id,
                    state,
                    type(error).__name__,
                    error,
                    exc_info=True,
                )

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "saved-catalog-search":
            self._filter_pages()

    def _filter_pages(self):
        if not self.is_mounted:
            return
        query = self.query_one("#saved-catalog-search", Input).value.casefold()
        table = self.query_one("#saved-catalog-table", DataTable)
        selected = (
            self.filtered_pages[table.cursor_row].number
            if table.cursor_row < len(self.filtered_pages)
            else None
        )
        self.filtered_pages = [
            page
            for page in (self.catalog.pages if self.catalog else ())
            if query in self._page_text(page).casefold()
        ]
        table.clear()
        for page in self.filtered_pages:
            from rich.text import Text

            table.add_row(str(page.number), self._state(page.state), Text(page.title[:40]))
        for index, page in enumerate(self.filtered_pages):
            if page.number == selected:
                table.move_cursor(row=index)
        self._show_page()

    def on_data_table_row_highlighted(self, event):
        self._show_page()

    def on_data_table_row_selected(self, event):
        self.query_one("#saved-catalog-page", TextArea).focus()

    def _show_page(self):
        row = self.query_one("#saved-catalog-table", DataTable).cursor_row
        page = self.filtered_pages[row] if row < len(self.filtered_pages) else None
        self.query_one("#saved-catalog-page", TextArea).load_text(
            self._page_text(page) if page else "Nessuna pagina disponibile per questo filtro."
        )

    @staticmethod
    def _state(state):
        return {"ready": "Pronta", "failed": "Errore", "review": "Da verificare"}.get(state, state)

    @classmethod
    def _page_text(cls, page):
        text = (
            f"PAGINA {page.number} · {page.title}\n{cls._state(page.state)} · "
            f"{page.category or 'Non classificata'} · Confidenza {page.confidence:.0%}\n\n"
            f"{page.summary}\n\nTEMI\n"
            + ", ".join(page.topics)
            + "\n\nENTITÀ\n"
            + "\n".join(f"{name} · {code}" for name, code in page.entities)
            + "\n\nCITAZIONI\n"
            + "\n\n".join(page.quotes)
        )
        for label, values in (
            ("Usi", page.uses),
            ("Date", page.dates),
            ("Luoghi", page.places),
            ("Riferimenti", page.references),
        ):
            if values:
                text += f"\n\n{label.upper()}\n" + "\n".join(values)
        if page.error:
            text += f"\n\nERRORE {page.error_code}\n{page.error}"
        return text
