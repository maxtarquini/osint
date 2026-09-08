"""Evidence metadata and extracted-text inspector."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from raven.config import UiLanguage
from raven.models import AnalysisLanguage, EvidenceDocument
from raven.models.catalog import DocumentCatalog
from raven.tui.widgets.catalog import CatalogSummary


class EvidenceInspectorScreen(ModalScreen[None]):
    """Inspect immutable metadata, independent lane states, and extracted text."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(
        self,
        document: EvidenceDocument,
        pages: tuple[str, ...],
        language: AnalysisLanguage,
        investigation=None,
    ) -> None:
        super().__init__()
        self.document = document
        self.pages = pages
        self.language = language
        self.investigation = investigation
        self.catalog: DocumentCatalog | None = None
        self.selected_page = 1

    def _tr(self, english: str, italian: str) -> str:
        return italian if self.app.settings.interface_language is UiLanguage.ITALIAN else english

    @property
    def unit(self) -> str:
        return (
            self._tr("Page", "Pagina")
            if self.document.file_format == "PDF"
            else self._tr("Section", "Sezione")
        )

    def compose(self) -> ComposeResult:
        document = self.document
        with Vertical(id="evidence-inspector-dialog"):
            yield Static(
                self._tr("DOCUMENT CATALOG", "CATALOGO DOCUMENTO"), id="evidence-inspector-title"
            )
            yield Static(document.original_name, id="evidence-inspector-name", markup=False)
            with TabbedContent(id="evidence-inspector-tabs"):
                with TabPane(self._tr("Catalog", "Catalogo"), id="document-catalog-tab"):
                    yield CatalogSummary(id="document-catalog-summary")
                    yield Input(
                        placeholder=self._tr(
                            "Filter pages by topic, category or entity",
                            "Filtra per tema, categoria o entità",
                        ),
                        id="catalog-page-search",
                    )
                    with Horizontal(id="catalog-page-body"):
                        yield DataTable(
                            id="catalog-pages-table", cursor_type="row", zebra_stripes=True
                        )
                        with VerticalScroll(id="catalog-page-details-scroll"):
                            yield Static(
                                self._tr(
                                    "Select a page to inspect its classification.",
                                    "Seleziona una pagina per consultarne la classificazione.",
                                ),
                                id="catalog-page-details",
                                markup=False,
                            )
                with TabPane(
                    self._tr("Original text", "Testo originale"), id="document-source-tab"
                ):
                    with Horizontal(id="evidence-page-toolbar"):
                        yield Static(
                            self._tr("SOURCE AND CITATIONS", "FONTE E CITAZIONI"),
                            classes="panel-title",
                        )
                        yield Select(
                            [
                                (f"{self.unit} {index}", index - 1)
                                for index in range(1, len(self.pages) + 1)
                            ],
                            value=0 if self.pages else Select.BLANK,
                            allow_blank=not self.pages,
                            id="evidence-page-select",
                        )
                    yield TextArea(self._page_text(0), id="evidence-text-preview", read_only=True)
                with (
                    TabPane(self._tr("Overview", "Riepilogo"), id="document-overview-tab"),
                    VerticalScroll(),
                ):
                    yield Static("", id="catalog-document-overview", markup=False)
                with (
                    TabPane(self._tr("Metadata", "Metadati"), id="document-metadata-tab"),
                    VerticalScroll(),
                ):
                    yield Static(
                        f"FORMAT  {document.file_format} · {document.size_bytes:,} bytes\n\n"
                        f"EVIDENCE  {document.ingestion_state.value}\n"
                        f"RAG  {document.rag_state.value}\n"
                        f"GRAPH  {document.graph_state.value}\n\n"
                        f"SHA-256\n{document.sha256}\n\nSTORAGE KEY\n{document.storage_key}",
                        markup=False,
                    )
                    yield Static("", id="catalog-provenance", markup=False)
            yield Static(
                self._tr(
                    "AI classifications are proposals; verify them against the source.",
                    "Le classificazioni AI sono proposte: verificale sulla fonte.",
                ),
                id="evidence-inspector-hint",
            )
            with Horizontal(id="evidence-inspector-actions"):
                yield Button(self._tr("Read source", "Leggi fonte"), id="catalog-read-source")
                yield Button(
                    self._tr("Catalog pages", "Cataloga pagine"),
                    id="catalog-document",
                    variant="primary",
                )
                yield Button(self._tr("Cancel", "Annulla"), id="cancel-catalog", disabled=True)
                if document.file_format == "PDF":
                    yield Button("Run local OCR", id="run-evidence-ocr")
                yield Button("Close", id="close-evidence-inspector", variant="primary")

    def on_mount(self) -> None:
        self.set_class(self.size.height <= 30, "compact-catalog")
        self.query_one("#catalog-pages-table", DataTable).add_columns(
            self.unit,
            self._tr("Title", "Titolo"),
            self._tr("Category", "Categoria"),
            self._tr("Review", "Revisione"),
        )
        self._show_catalog(None)
        self.call_after_refresh(self.refresh_catalog)

    def on_resize(self) -> None:
        self.set_class(self.size.height <= 30, "compact-catalog")

    def refresh_catalog(self) -> None:
        if self.investigation is not None and self.is_mounted:
            self._load_catalog()

    @work(thread=True, exclusive=True, group="document-catalog-load", exit_on_error=False)
    def _load_catalog(self) -> None:
        try:
            catalog = self.app.load_document_catalog(self.investigation, self.document)
        except Exception:
            self.app.call_from_thread(self._catalog_unavailable)
        else:
            self.app.call_from_thread(self._show_catalog, catalog)

    def _catalog_unavailable(self) -> None:
        if self.is_mounted:
            self.query_one("#evidence-inspector-hint", Static).update(
                self._tr(
                    "Catalog unavailable; check storage and dictionary configuration.",
                    "Catalogo non disponibile: verifica archivio e dizionario.",
                )
            )

    def _show_catalog(self, catalog: DocumentCatalog | None) -> None:
        if not self.is_mounted:
            return
        self.catalog = catalog
        self.query_one(CatalogSummary).show_catalog(
            self.document.original_name,
            catalog,
            self.investigation.analysis_domain if self.investigation else "",
        )
        queue = self.app.catalog_jobs
        job = queue.snapshot(self.document.investigation_id) if queue else None
        active = job is not None and job.status.value in {"queued", "running"}
        self.query_one("#catalog-document", Button).disabled = active or queue is None
        self.query_one("#cancel-catalog", Button).disabled = not active
        if self.document.file_format == "PDF":
            self.query_one("#run-evidence-ocr", Button).disabled = active
        if active:
            self.query_one("#evidence-inspector-hint", Static).update(job.message)
        else:
            self.query_one("#evidence-inspector-hint", Static).update(
                self._tr(
                    "AI classifications are proposals; verify them against the source.",
                    "Le classificazioni AI sono proposte: verificale sulla fonte.",
                )
            )
        if catalog:
            summary_label = (
                self._tr("AI DOCUMENT OVERVIEW · draft", "RIEPILOGO AI · bozza")
                if catalog.summary_state == "ready"
                else self._tr(
                    "PAGE HIGHLIGHTS · summary unavailable",
                    "ANTEPRIMA PAGINE · sintesi non disponibile",
                )
            )
            self.query_one("#catalog-document-overview", Static).update(
                summary_label
                + "\n\n"
                + catalog.summary
                + f"\n\n{catalog.completed}/{catalog.total} processed"
                + f" · {catalog.failed_count} failed · {catalog.review_count} need review"
            )
            self.query_one("#catalog-provenance", Static).update(
                f"\nCATALOG MODEL\n{catalog.model}\n\nDICTIONARY\n"
                + ", ".join(catalog.dictionary_versions)
                + f"\n{catalog.dictionary_hash}"
            )
        self._filter_pages()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "catalog-page-search":
            self._filter_pages()

    def _filter_pages(self) -> None:
        table = self.query_one("#catalog-pages-table", DataTable)
        search = self.query_one("#catalog-page-search", Input).value.casefold().strip()
        table.clear()
        pages = self.catalog.pages if self.catalog else ()
        for page in pages:
            text = " ".join(
                (
                    page.title,
                    page.summary,
                    page.category,
                    *page.topics,
                    *(name for name, _ in page.entities),
                )
            ).casefold()
            if search and search not in text:
                continue
            table.add_row(
                str(page.number),
                page.title,
                page.category or self._tr("Not classified", "Non classificata"),
                page.state,
                key=str(page.number),
            )
        numbers = [int(key.value) for key in table.rows]
        if numbers:
            selected = numbers.index(self.selected_page) if self.selected_page in numbers else 0
            table.move_cursor(row=selected)
            self._show_page(numbers[selected])
        else:
            self.query_one("#catalog-page-details", Static).update(
                self._tr(
                    "No catalog pages match. Start cataloging or change the filter.",
                    "Nessuna pagina trovata. Avvia la catalogazione o modifica il filtro.",
                )
            )
        self.query_one("#catalog-read-source", Button).disabled = not numbers

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "catalog-pages-table" and event.row_key.value:
            self._show_page(int(event.row_key.value))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "catalog-pages-table":
            self._read_source()

    def _show_page(self, number: int) -> None:
        self.selected_page = number
        page = (
            next((p for p in self.catalog.pages if p.number == number), None)
            if self.catalog
            else None
        )
        if page is None:
            return
        entities = ", ".join(f"{name} ({code})" for name, code in page.entities) or "—"
        category = page.category or self._tr("Not classified", "Non classificata")
        confidence_label = self._tr("extraction confidence", "confidenza estrazione")
        confidence = (
            "" if page.state == "failed" else f" · {confidence_label} {page.confidence:.0%}"
        )
        reason = page.error
        if page.state == "review" and not reason:
            reason = self._tr(
                "Extraction confidence is below 60%; verify the classification against the source.",
                "Confidenza dell’estrazione sotto il 60%: verifica la classificazione sulla fonte.",
            )
        self.query_one("#catalog-page-details", Static).update(
            f"{self.unit} {number} · {page.title}\n{category} · {page.state}{confidence}"
            f"\n\n{page.summary}\n{reason}\n\n"
            f"{self._tr('Topics', 'Temi')}: {', '.join(page.topics) or '—'}\n\n"
            f"{self._tr('Entities', 'Entità')}: {entities}\n\n"
            f"{self._tr('Dates', 'Date')}: {', '.join(page.dates) or '—'}\n"
            f"{self._tr('Places', 'Luoghi')}: {', '.join(page.places) or '—'}\n"
            f"{self._tr('References', 'Rimandi')}: {', '.join(page.references) or '—'}\n\n"
            f"{self._tr('Uses', 'Utilizzi')}: {', '.join(page.uses) or '—'}\n\n"
            f"{self._tr('Source excerpts', 'Estratti dalla fonte')}:\n" + "\n\n".join(page.quotes)
        )

    def _read_source(self) -> None:
        if not self.pages or self.selected_page > len(self.pages):
            return
        self.query_one("#evidence-inspector-tabs", TabbedContent).active = "document-source-tab"
        self.query_one("#evidence-page-select", Select).value = self.selected_page - 1
        self.query_one("#evidence-text-preview", TextArea).load_text(
            self._page_text(self.selected_page - 1)
        )

    def _page_text(self, index: int) -> str:
        if not self.pages:
            return "No extractable text is available. OCR may be required."
        text = self.pages[index] or "No embedded text on this page. OCR may be required."
        return (
            f"[Evidence: {self.document.original_name} · {self.unit.lower()} {index + 1}]\n\n{text}"
        )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "evidence-page-select" or event.value is Select.BLANK:
            return
        self.query_one("#evidence-text-preview", TextArea).load_text(
            self._page_text(int(event.value))
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-evidence-inspector":
            self.dismiss()
        elif event.button.id == "catalog-read-source":
            self._read_source()
        elif event.button.id == "catalog-document" and self.investigation is not None:
            try:
                self.app.enqueue_page_catalog(self.investigation, (self.document,))
            except Exception:
                self._catalog_unavailable()
            self.refresh_catalog()
        elif event.button.id == "cancel-catalog" and self.app.catalog_jobs:
            self.app.catalog_jobs.cancel(self.document.investigation_id)
        elif event.button.id == "run-evidence-ocr":
            event.button.disabled = True
            self.query_one("#evidence-inspector-hint", Static).update(
                "Running local OCR with Tesseract · the cached result stays in this investigation"
            )
            self._run_ocr()

    @work(thread=True, exclusive=True, group="evidence-ocr", exit_on_error=False)
    def _run_ocr(self) -> None:
        try:
            pages = self.app.ocr_evidence_pages(  # type: ignore[attr-defined]
                self.document, self.language
            )
        except Exception:
            self.app.call_from_thread(self._ocr_failed)
        else:
            self.app.call_from_thread(self._ocr_completed, pages)

    def _ocr_completed(self, pages: tuple[str, ...]) -> None:
        if not self.is_mounted:
            return
        self.pages = pages
        selector = self.query_one("#evidence-page-select", Select)
        selector.set_options(
            [(f"Page {index}", index - 1) for index in range(1, len(self.pages) + 1)]
        )
        selector.value = 0
        self.query_one("#evidence-text-preview", TextArea).load_text(self._page_text(0))
        self.query_one("#evidence-inspector-hint", Static).update(
            f"OCR cached locally · {len(pages)} page{'s' if len(pages) != 1 else ''}"
        )
        self.query_one("#run-evidence-ocr", Button).disabled = False
        self.refresh_catalog()

    def _ocr_failed(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#evidence-inspector-hint", Static).update(
            "OCR failed · verify that pdftoppm and Tesseract language data are installed"
        )
        self.query_one("#run-evidence-ocr", Button).disabled = False
