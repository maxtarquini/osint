"""Read-only browsing of graph assertions, their comparisons, and page coverage."""

from collections import Counter

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Static, TabbedContent, TabPane, TextArea

from raven.models import EvidenceDocument, Investigation, InvestigationGraph
from raven.models.graph import GraphClaim, PageGraphAnalysis
from raven.tui.screens.document_catalog import DocumentCatalogScreen
from raven.tui.widgets.claim_details import PAGE_STATE_LABELS, ClaimDetails


class GraphClaimsScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Chiudi"),
        Binding("/", "search", "Cerca"),
        Binding("question_mark", "app.context_help", "Help"),
    ]

    def __init__(
        self,
        investigation: Investigation,
        graph: InvestigationGraph | None,
        documents: tuple[EvidenceDocument, ...],
        *,
        claim_id: str | None = None,
    ) -> None:
        super().__init__()
        self.investigation = investigation
        self.graph = graph
        self.documents = {document.document_id: document for document in documents}
        self.details = ClaimDetails(graph, documents)
        self._initial_claim_id = claim_id
        self._claims: list[GraphClaim] = []
        self._pages: list[PageGraphAnalysis] = []
        self._tables_ready = False

    def compose(self) -> ComposeResult:
        with Vertical(id="graph-claims-dialog"):
            yield Static("AFFERMAZIONI E COPERTURA", id="graph-claims-title")
            yield Static(self._summary(), id="graph-claims-summary", markup=False)
            with TabbedContent(initial="claims-browse-tab", id="graph-claims-tabs"):
                with TabPane("Affermazioni", id="claims-browse-tab"):
                    yield Input(
                        placeholder="Cerca entità, negazioni, fonti o citazioni · /",
                        id="graph-claims-search",
                    )
                    with Horizontal(classes="claims-reader-body"):
                        yield DataTable(
                            id="graph-claims-table", cursor_type="row", zebra_stripes=True
                        )
                        yield TextArea("", read_only=True, soft_wrap=True, id="graph-claim-detail")
                with TabPane("Eventi / tempo", id="claims-events-tab"):
                    yield TextArea(self._event_text(), read_only=True, soft_wrap=True)
                with TabPane("Da revisionare", id="claims-review-tab"):
                    yield TextArea(
                        self._review_text(), read_only=True, soft_wrap=True, id="graph-review-text"
                    )
                with TabPane("Copertura", id="claims-coverage-tab"):
                    yield Input(
                        placeholder="Cerca documento, stato, catalogo o errore · /",
                        id="graph-coverage-search",
                    )
                    with Horizontal(classes="claims-reader-body"):
                        yield DataTable(
                            id="graph-coverage-table", cursor_type="row", zebra_stripes=True
                        )
                        yield TextArea(
                            "", read_only=True, soft_wrap=True, id="graph-coverage-detail"
                        )
            with Horizontal(id="graph-claims-actions"):
                yield Button("Catalogo documento", id="claim-open-catalog", disabled=True)
                yield Button("Chiudi", id="close-graph-claims", variant="primary")

    def _event_text(self):
        if not self.graph:
            return "Nessun evento"
        from raven.graph.events import temporal_relation

        claims = {claim.claim_id: claim for claim in self.graph.claims}
        rows = ["Eventi attribuiti alle fonti; record discordanti restano distinti."]
        for event in self.graph.events:
            statements = [claims[key] for key in event.claim_ids if key in claims]
            rows.append(
                f"\n{event.event_type} · {event.valid_from or '?'} → {event.valid_until or '?'}"
                + "\n"
                + " · ".join(
                    f"{claim.polarity} / {claim.epistemic_status} / {claim.claim_kind} / "
                    f"supporto {claim.semantic_support}"
                    for claim in statements
                )
                + "\n"
                + " · ".join(
                    f"{role}: {self.details.entities.get(entity, entity)}"
                    for role, entity in event.roles
                )
                + "\n"
                + " · ".join(f"{key}: {value.value} {value.unit}" for key, value in event.values)
                + f"\nFonte: {event.source.source_id}\nAffermazioni: {', '.join(event.claim_ids)}\n"
                + self.details.source_text(event.support)
            )
        event_claims = {key for event in self.graph.events for key in event.claim_ids}
        # An agreement may be classified as DOCUMENT in a custom dictionary. Its
        # corrections/cessation still belong in this view, regardless of the base type.
        for claim in self.graph.claims:
            if claim.claim_kind in {"corrects", "retracts", "withdraws_certainty", "ceases"}:
                if claim.claim_id not in event_claims:
                    rows.append("\nOPERAZIONE SULLA FONTE\n" + self.details.claim_text(claim))
                event_claims.add(claim.claim_id)
        rows.append("\nCONFRONTI TEMPORALI TRA AFFERMAZIONI CANDIDATE")
        for link in self.graph.claim_links:
            first = claims.get(link.source_claim_id)
            second = claims.get(link.target_claim_id)
            if first and second and {first.claim_id, second.claim_id} & event_claims:
                rows.append(
                    f"\nAffermazioni {first.claim_id} / {second.claim_id}: {link.kind}"
                    f"\nIntervalli espliciti: {temporal_relation(first, second)}"
                    f" · revisione confronto: {link.review_state}"
                    f"\n{link.review_rationale or link.rationale}"
                )
        rows.append(
            "\nIntervallo unknown: estremi insufficienti; possibly_overlaps: date parziali "
            "compatibili. La compatibilità temporale non dimostra identità dell'evento."
        )
        return "\n".join(rows)

    def _review_text(self):
        if not self.graph:
            return "Nessun candidato"
        rows = [
            "Candidati conservati per revisione. Supporto semantico e attendibilità sono distinti."
        ]
        for entity in self.graph.entities:
            if entity.semantic_support != "supported":
                rows.append(
                    f"\n{entity.canonical_name} · "
                    f"{entity.entity_type}/{entity.subtype or ''} · "
                    f"{entity.semantic_support}\n"
                    + "\n".join(entity.resolution_notes)
                    + "\n"
                    + self.details.source_text(entity.support)
                )
        for claim in self.graph.claims:
            if claim.semantic_support != "supported":
                rows.append("\n" + self.details.claim_text(claim))
        return "\n".join(rows)

    def _summary(self) -> str:
        if self.graph is None:
            return "Nessun grafo disponibile. Avvia Analyze Evidence per analizzare le fonti."
        states = Counter(page.state for page in self.graph.pages)
        failed = states["failed"] + states["partial"]
        return (
            f"Affermazioni {len(self.graph.claims)} · Confronti {len(self.graph.claim_links)} · "
            f"Pagine {len(self.graph.pages)} · Errori/parziali {failed}\n"
            "Fonti e confronti non determinano la verità delle affermazioni."
        )

    def on_mount(self) -> None:
        self.on_resize()
        self.query_one("#graph-claims-table", DataTable).add_column("Affermazione", width=38)
        coverage = self.query_one("#graph-coverage-table", DataTable)
        coverage.add_column("Documento", width=20)
        coverage.add_column("Pag.", width=4)
        coverage.add_column("Esito", width=16)
        self._tables_ready = True
        self._filter_claims()
        self._filter_pages()

    def on_resize(self) -> None:
        self.set_class(self.size.width < 120, "narrow-claims-reader")

    def action_close(self) -> None:
        self.dismiss(None)

    def action_search(self) -> None:
        current = self.query_one("#graph-claims-tabs", TabbedContent).active
        selector = (
            "#graph-coverage-search" if current == "claims-coverage-tab" else "#graph-claims-search"
        )
        if current not in {"claims-browse-tab", "claims-coverage-tab"}:
            self.query_one("#graph-claims-tabs", TabbedContent).active = "claims-browse-tab"
        self.query_one(selector, Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-graph-claims":
            self.action_close()
        elif event.button.id == "claim-open-catalog":
            page = self._selected_page()
            document = self.documents.get(page.evidence_id) if page else None
            if document is not None:
                self.app.push_screen(DocumentCatalogScreen(self.investigation, document))

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if self._tables_ready:
            self._update_catalog_action()

    def on_input_changed(self, event: Input.Changed) -> None:
        if not self._tables_ready:
            return
        if event.input.id == "graph-claims-search":
            self._filter_claims()
        elif event.input.id == "graph-coverage-search":
            self._filter_pages()

    def _filter_claims(self) -> None:
        table = self.query_one("#graph-claims-table", DataTable)
        selected = (
            self._claims[table.cursor_row].claim_id
            if table.cursor_row < len(self._claims)
            else None
        ) or self._initial_claim_id
        self._initial_claim_id = None
        query = self.query_one("#graph-claims-search", Input).value.casefold().strip()
        self._claims = [
            claim
            for claim in (self.graph.claims if self.graph else ())
            if query in self.details.claim_text(claim, comparisons=False).casefold()
        ]
        table.clear()
        for claim in self._claims:
            table.add_row(Text(self.details.claim_label(claim)), key=claim.claim_id)
        for index, claim in enumerate(self._claims):
            if claim.claim_id == selected:
                table.move_cursor(row=index)
                break
        self._show_claim()

    def _filter_pages(self) -> None:
        table = self.query_one("#graph-coverage-table", DataTable)
        selected = self._selected_page()
        query = self.query_one("#graph-coverage-search", Input).value.casefold().strip()
        self._pages = [
            page
            for page in (self.graph.pages if self.graph else ())
            if query in self.details.coverage_text(page).casefold()
        ]
        table.clear()
        for index, page in enumerate(self._pages):
            table.add_row(
                Text(self.details.document_name(page.evidence_id)),
                str(page.page_number),
                Text(PAGE_STATE_LABELS.get(page.state, page.state)),
                key=str(index),
            )
        if selected in self._pages:
            table.move_cursor(row=self._pages.index(selected))
        self._show_page()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if not self._tables_ready:
            return
        if event.data_table.id == "graph-claims-table":
            self._show_claim()
        elif event.data_table.id == "graph-coverage-table":
            self._show_page()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        selector = (
            "#graph-claim-detail"
            if event.data_table.id == "graph-claims-table"
            else "#graph-coverage-detail"
        )
        self.query_one(selector, TextArea).focus()

    def _show_claim(self) -> None:
        row = self.query_one("#graph-claims-table", DataTable).cursor_row
        if row < len(self._claims):
            text = self.details.claim_text(self._claims[row])
        elif self.graph is None:
            text = "Nessun grafo disponibile. Genera il grafo dalle evidenze dell'indagine."
        elif not self.graph.claims and self.graph.pages:
            text = (
                "Nessuna affermazione estratta in questo grafo. Consulta Copertura per "
                "distinguere pagine analizzate, vuote, parziali o con errori."
            )
        elif not self.graph.claims:
            text = (
                "Nessuna affermazione strutturata salvata. I grafi precedenti contengono solo "
                "entità e relazioni: rigenera l'analisi per consultare affermazioni e negazioni."
            )
        else:
            text = "Nessuna affermazione corrisponde al filtro."
        self.query_one("#graph-claim-detail", TextArea).load_text(text)

    def _selected_page(self) -> PageGraphAnalysis | None:
        if not self._tables_ready:
            return None
        row = self.query_one("#graph-coverage-table", DataTable).cursor_row
        return self._pages[row] if row < len(self._pages) else None

    def _show_page(self) -> None:
        page = self._selected_page()
        if page is not None:
            text = self.details.coverage_text(page)
        elif self.graph is not None and self.graph.pages:
            text = "Nessuna pagina corrisponde al filtro."
        else:
            text = (
                "Copertura delle pagine non disponibile. I grafi precedenti non la registravano; "
                "l'assenza di questo riepilogo non significa che i documenti siano vuoti."
            )
        self.query_one("#graph-coverage-detail", TextArea).load_text(text)
        self._update_catalog_action()

    def _update_catalog_action(self) -> None:
        page = self._selected_page()
        coverage_active = (
            self.query_one("#graph-claims-tabs", TabbedContent).active == "claims-coverage-tab"
        )
        self.query_one("#claim-open-catalog", Button).disabled = not (
            coverage_active and page is not None and page.evidence_id in self.documents
        )
