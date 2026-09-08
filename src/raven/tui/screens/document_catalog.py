"""Browse stored page catalogs without starting model requests or changing evidence."""

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Static, TabbedContent, TabPane, TextArea

from raven.exceptions import InvestigationError


class DocumentCatalogScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Chiudi"), Binding("/", "search", "Cerca pagine")]

    def __init__(self, investigation, document):
        super().__init__()
        self.investigation = investigation
        self.document = document
        self.catalog = None
        self.filtered_pages = []

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
                yield Button("Aggiorna", id="refresh-saved-catalog")
                yield Button("Chiudi", id="close-saved-catalog", variant="primary")

    def on_mount(self):
        self.on_resize()
        self.query_one("#saved-catalog-table", DataTable).add_columns("Pagina", "Stato", "Titolo")
        self._load()

    def on_resize(self):
        self.set_class(self.size.width < 100, "narrow-catalog-reader")

    def action_close(self):
        self.dismiss(None)

    def action_search(self):
        self.query_one(TabbedContent).active = "saved-catalog-pages"
        self.query_one("#saved-catalog-search", Input).focus()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "close-saved-catalog":
            self.action_close()
        elif event.button.id == "refresh-saved-catalog":
            self.query_one("#refresh-saved-catalog", Button).disabled = True
            self._load()

    @work(thread=True, exclusive=True, group="read-document-catalog", exit_on_error=False)
    def _load(self):
        try:
            catalog = self.app.load_evidence_catalog(self.investigation, self.document)
        except InvestigationError as error:
            self.app.call_from_thread(self._show, None, str(error))
        except Exception:
            self.app.call_from_thread(self._show, None, "Impossibile leggere il catalogo salvato.")
        else:
            self.app.call_from_thread(self._show, catalog, "")

    def _show(self, catalog, error):
        if not self.is_mounted:
            return
        self.catalog = catalog
        self.query_one("#refresh-saved-catalog", Button).disabled = False
        if catalog is None:
            status = error or "Nessun catalogo salvato per questo documento."
            summary = status + "\n\nLa reindicizzazione RAG aggiorna la ricerca nei documenti; "
            summary += "la catalogazione delle pagine è un'elaborazione distinta."
            provenance = ""
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
            summary = (
                f"{catalog.domain} · {catalog.state}\n\n"
                + ("RIEPILOGO AI" if catalog.summary_state == "ready" else "SINTESI DELLE PAGINE")
                + f"\n\n{catalog.summary}\n\nCATEGORIE\n"
                + "\n".join(catalog.categories)
                + "\n\nTEMI\n"
                + ", ".join(catalog.topics)
            )
            if catalog.error:
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
