"""A reusable per-document catalog overview, visible before opening individual pages."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from raven.config import UiLanguage
from raven.models.catalog import DocumentCatalog


class CatalogSummary(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("", classes="catalog-summary-title", markup=False)
        yield Static("", classes="catalog-summary-status", markup=False)
        yield Static("", classes="catalog-summary-content", markup=False)

    def show_catalog(self, name: str, catalog: DocumentCatalog | None, domain: str = "") -> None:
        italian = self.app.settings.interface_language is UiLanguage.ITALIAN
        self.query_one(".catalog-summary-title", Static).update(
            ("CATALOGO · " if italian else "PAGE CATALOG · ") + name
        )
        if catalog is None:
            status = ("Da catalogare" if italian else "Not cataloged") + f" · {domain}"
            content = (
                "Apri il documento per avviare l’agente di classificazione delle pagine."
                if italian
                else "Open the document to start the page classification agent."
            )
        else:
            labels = {
                "running": "In corso",
                "ready": "Catalogato",
                "review": "Da revisionare",
                "cancelled": "Annullato",
                "failed": "Errore",
                "stale": "Da aggiornare",
                "interrupted": "Interrotto",
            }
            state = labels.get(catalog.state, catalog.state) if italian else catalog.state.title()
            unit = (
                ("pagine" if catalog.unit == "page" else "sezioni")
                if italian
                else catalog.unit + "s"
            )
            review = "da verificare" if italian else "need review"
            failed = "fallite" if italian else "failed"
            processed = "elaborate" if italian else "processed"
            status = (
                f"{state} · {catalog.completed}/{catalog.total} {unit} {processed}"
                f" · {catalog.failed_count} {failed}"
                f" · {catalog.review_count} {review} · {catalog.domain}"
            )
            themes = "Temi" if italian else "Topics"
            content = (
                (
                    " · ".join(catalog.categories)
                    or ("Nessuna pagina classificata" if italian else "No classified pages")
                )
                + "\n"
                + themes
                + ": "
                + (", ".join(catalog.topics) or "—")
            )
            if catalog.summary:
                summary_label = (
                    ("Riepilogo AI: " if italian else "AI overview: ")
                    if catalog.summary_state == "ready"
                    else ("Anteprima pagine: " if italian else "Page highlights: ")
                )
                content = summary_label + catalog.summary.replace("\n", " ")[:240] + "\n" + content
            if catalog.error:
                content += "\n" + catalog.error
            if catalog.state == "stale":
                content += "\n" + (
                    "Fonte, OCR, modello, dizionario o regole cambiati: aggiorna il catalogo."
                    if italian
                    else "Source, OCR, model, dictionary or rules changed: update this catalog."
                )
        self.query_one(".catalog-summary-status", Static).update(status)
        self.query_one(".catalog-summary-content", Static).update(content)
        self.query_one(".catalog-summary-content", Static).tooltip = (
            catalog.summary if catalog else None
        )
