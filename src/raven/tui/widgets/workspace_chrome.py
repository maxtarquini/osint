"""Workspace navigation and actionable empty states."""

from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static

from raven.config import UiLanguage


class WorkspaceRail(Vertical):
    def compose(self) -> ComposeResult:
        italian = self.app.settings.interface_language is UiLanguage.ITALIAN
        yield Static("IL FASCICOLO" if italian else "CASE WORKSPACE", classes="rail-heading")
        for number, key, english, translation in (
            ("01", "overview", "Case brief", "Il caso"),
            ("02", "evidence", "Evidence", "Evidenze"),
            ("03", "graph", "Connections", "Connessioni"),
            ("04", "timeline", "Timeline", "Cronologia"),
            ("05", "map", "Locations", "Luoghi"),
            ("06", "runs", "Runs & exports", "Analisi ed export"),
            ("07", "chat", "Ask Raven", "Chiedi a Raven"),
        ):
            yield Button(
                f"{number}  {translation if italian else english}",
                id=f"rail-{key}",
                classes="rail-link",
            )
        with Vertical(id="rail-note"):
            yield Static("◆  RAVEN", classes="rail-signature")
            yield Static(
                "Dalle fonti alle connessioni.\nOgni conclusione torna all’evidenza."
                if italian
                else "From sources to connections.\nEvery finding leads back to evidence.",
                classes="rail-description",
            )

    def select(self, pane: str) -> None:
        key = pane.removeprefix("workspace-").removesuffix("-tab")
        for button in self.query(Button):
            button.set_class(button.id == f"rail-{key}", "selected")


class WorkspaceEmptyState(Vertical):
    """A bounded explanation and a working next action instead of an empty frame."""

    class Proceed(Message):
        def __init__(self, target: str) -> None:
            super().__init__()
            self.target = target

    def __init__(self, kind: str, has_documents: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.kind = kind
        self.has_documents = has_documents
        self.add_class("workspace-empty-state")

    def compose(self) -> ComposeResult:
        italian = self.app.settings.interface_language is UiLanguage.ITALIAN
        content = {
            "map": (
                "        N        \n    ·   │   ·    \n"
                " W ──── ◇ ──── E \n    ·   │   ·    \n        S        ",
                "Give your investigation a sense of place",
                "Dai un luogo alla tua investigazione",
                "Connect people and events to places. "
                "Locations from your evidence will appear here.",
                "Collega persone ed eventi ai luoghi. "
                "Qui compariranno le posizioni presenti nelle evidenze.",
            ),
            "timeline": (
                "○ ─────── ◇ ─────── ○\n          │          \n          ·          ",
                "See how the story unfolds",
                "Ricostruisci la sequenza degli eventi",
                "Bring dates and events together in a chronology linked to your sources.",
                "Riunisci date ed eventi in una cronologia collegata alle fonti.",
            ),
            "evidence": (
                "┌─────────┐   \n│ ─────── │ ┐ \n│ ─────   │ │ \n└─────────┘ │ \n  └─────────┘ ",
                "Every investigation starts with a source",
                "Ogni investigazione parte da una fonte",
                "Add your first document. Raven keeps the original "
                "and helps you explore what it contains.",
                "Aggiungi il primo documento. Raven conserva l’originale "
                "e ti aiuta a esplorarne il contenuto.",
            ),
            "graph": (
                "    ○ ───── ◇    \n    │       │    \n    ◇ ───── ○    ",
                "Discover the connections",
                "Scopri le connessioni",
                "Explore the people, organizations and relationships supported by your documents.",
                "Esplora persone, organizzazioni e relazioni documentate nelle tue fonti.",
            ),
        }
        art, title, it_title, description, it_description = content[self.kind]
        with Vertical(classes="empty-state-card"):
            yield Static(art, classes="empty-state-art")
            yield Static(it_title if italian else title, classes="empty-state-title")
            yield Static(
                it_description if italian else description, classes="empty-state-description"
            )
            with Horizontal(classes="empty-state-steps"):
                for english, translated in (
                    ("01  ADD SOURCES", "01  AGGIUNGI FONTI"),
                    ("02  ANALYZE", "02  ANALIZZA"),
                    ("03  EXPLORE", "03  ESPLORA"),
                ):
                    yield Static(translated if italian else english)
            with Center(classes="empty-state-action-row"):
                yield Button(self._action_label(), variant="primary", classes="empty-state-action")

    def _action_label(self) -> str:
        italian = self.app.settings.interface_language is UiLanguage.ITALIAN
        if self.has_documents:
            if self.kind == "graph":
                return "Analizza evidenze" if italian else "Analyze Evidence"
            return "Esplora il grafo" if italian else "Explore the graph"
        return "Aggiungi la prima evidenza" if italian else "Add your first evidence"

    def set_document_state(self, has_documents: bool) -> None:
        self.has_documents = has_documents
        self.query_one(Button).label = self._action_label()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        target = "analyze" if self.kind == "graph" else "graph"
        self.post_message(self.Proceed(target if self.has_documents else "add"))
