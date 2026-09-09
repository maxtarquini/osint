"""Generate, browse, compare and explicitly select persistent investigative variants."""

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static, TextArea

from raven.graph.methods import METHODS, graph_method
from raven.graph.variants import comparison_text


class GraphVariantsScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "close", "Chiudi"),
        Binding("ctrl+g", "generate", "Crea variante"),
    ]

    def __init__(self, investigation, service, *, busy=False, model=""):
        super().__init__()
        self.investigation = investigation
        self.service = service
        self.busy = busy
        self.model = model
        self._operating = False
        self._variant_metadata = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="variants-dialog"):
            yield Static("VARIANTI INVESTIGATIVE", id="variants-title")
            with VerticalScroll(id="variants-controls"):
                yield Static("Metodo della nuova variante")
                yield Select(
                    [(m.name, m.method_id) for m in METHODS],
                    value="document_claims",
                    allow_blank=False,
                    id="variant-method",
                )
                yield Static("", id="variant-purpose", markup=False)
                yield Input(
                    placeholder="Nome della nuova variante (facoltativo)", id="variant-name"
                )
                yield Static("Variante A · apertura / selezione attiva")
                yield Select([], id="variant-a", prompt="Nessuna variante")
                yield Static("Variante B · confronto con A")
                yield Select([], id="variant-b", prompt="Seleziona B")
                with Horizontal(classes="variant-actions"):
                    yield Button("Apri A", id="variant-open", disabled=True)
                    yield Button("Imposta attiva", id="variant-activate", disabled=True)
                    yield Button("Confronta", id="variant-compare", disabled=True)
            yield Static("Caricamento…", id="variant-status", markup=False)
            yield TextArea("", read_only=True, soft_wrap=True, id="variant-report")
            with Horizontal(id="variant-footer"):
                yield Button(
                    "Crea variante · Ctrl+G",
                    id="variant-generate",
                    variant="primary",
                    disabled=self.busy,
                )
                yield Button("Chiudi", id="variant-close")

    def on_mount(self):
        self._purpose()
        self._load()

    def _purpose(self):
        method = graph_method(str(self.query_one("#variant-method", Select).value))
        self.query_one("#variant-purpose", Static).update(
            f"{method.purpose}\nVersione {method.version} · modello "
            f"{self.model or 'non disponibile'}. "
            "Estrazione dagli originali; la generazione non cambia la variante attiva."
        )

    def on_select_changed(self, event: Select.Changed):
        if event.select.id == "variant-method":
            self._purpose()
        elif event.select.id in {"variant-a", "variant-b"}:
            if event.select.id == "variant-a":
                metadata = self._variant_metadata.get(str(event.value), {})
                manifest = metadata.get("manifest") or {}
                self.query_one("#variant-report", TextArea).load_text(
                    f"{metadata.get('name', '')}\nMetodo: {manifest.get('method_id', 'legacy')} "
                    f"v{manifest.get('method_version', '?')}\nModello: {manifest.get('model', '?')}"
                    f"\nPrompt: {manifest.get('prompt_version', '?')}"
                    f"\nDizionari: {', '.join(manifest.get('dictionary_versions') or []) or '?'}"
                    f"\nHash dizionario: {manifest.get('dictionary_hash', '?')}"
                    f"\nDocumenti nel manifest: {len(manifest.get('documents', []))}"
                    "\nAprire non cambia la variante usata dalla chat."
                )
            a = self.query_one("#variant-a", Select).value
            b = self.query_one("#variant-b", Select).value
            self.query_one("#variant-open", Button).disabled = a is Select.BLANK
            self.query_one("#variant-activate", Button).disabled = a is Select.BLANK
            self.query_one("#variant-compare", Button).disabled = (
                a is Select.BLANK or b is Select.BLANK or a == b
            )

    @work(thread=True, exclusive=True, group="variant-operation", exit_on_error=False)
    def _load(self):
        try:
            variants = self.service.variants(self.investigation.investigation_id)
            active = self.service.latest(self.investigation.investigation_id)
            method = self.service.method_preference(self.investigation.investigation_id)
            self.app.call_from_thread(self._loaded, variants, active, method)
        except Exception:
            self.app.call_from_thread(self._status, "Impossibile leggere le varianti")

    def _loaded(self, variants, active, method):
        if not self.is_mounted:
            return
        self._variant_metadata = {v["run_id"]: v for v in variants}
        options = [
            (
                v["name"] + (" · ATTIVA" if active and v["run_id"] == active.run_id else ""),
                v["run_id"],
            )
            for v in variants
        ]
        for field in ("#variant-a", "#variant-b"):
            self.query_one(field, Select).set_options(options)
        if options:
            self.query_one("#variant-a", Select).value = active.run_id if active else options[0][1]
        if len(options) > 1:
            self.query_one("#variant-b", Select).value = next(
                v for _, v in options if v != self.query_one("#variant-a", Select).value
            )
        self.query_one("#variant-method", Select).value = method
        self._status(
            f"{len(variants)} varianti · attiva: "
            f"{active.variant_name or active.run_id[:8] if active else 'nessuna'}"
        )

    def _status(self, value):
        if self.is_mounted:
            self.query_one("#variant-status", Static).update(value)

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if self._operating:
            return
        action = event.button.id
        if action == "variant-close":
            self.action_close()
        elif action == "variant-generate":
            self.action_generate()
        else:
            a = self.query_one("#variant-a", Select).value
            b = self.query_one("#variant-b", Select).value
            if a is not Select.BLANK:
                self._operating = True
                self._operation(action, str(a), str(b))

    def action_generate(self):
        if self.busy or self._operating:
            return
        self._operating = True
        self._operation(
            "generate",
            str(self.query_one("#variant-method", Select).value),
            self.query_one("#variant-name", Input).value,
        )

    @work(thread=True, exclusive=True, group="variant-operation", exit_on_error=False)
    def _operation(self, action, first, second):
        case_id = self.investigation.investigation_id
        self.app.call_from_thread(self._status, "Operazione in corso…")
        try:
            if action == "generate":
                self.service.set_method_preference(case_id, first)
                self.app.call_from_thread(self.dismiss, ("generate", first, second))
            elif action == "variant-open":
                graph = self.service.open_variant(case_id, first)
                self.app.call_from_thread(self.dismiss, ("open", graph))
            elif action == "variant-activate":
                graph = self.service.activate_variant(case_id, first)
                self.app.call_from_thread(self.dismiss, ("active", graph))
            elif action == "variant-compare":
                report = self.service.compare_variants(case_id, first, second)
                self.app.call_from_thread(self._report, comparison_text(report))
        except Exception:
            self.app.call_from_thread(
                self._status,
                "Operazione non confermata; riaprire le varianti per verificarne lo stato",
            )
        finally:
            self._operating = False

    def _report(self, text):
        if self.is_mounted:
            self.query_one("#variant-report", TextArea).load_text(text)
            self.query_one("#variant-report", TextArea).focus()
            self._status("Confronto completato · dettagli e fonti nel rapporto")

    def action_close(self):
        self.dismiss(None)
