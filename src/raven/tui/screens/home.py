"""Home and contextual-help screens."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Label, Static

from raven.models import ServiceName
from raven.tui.widgets import ServiceStatusIndicator, TopNavigation
from raven.tui.widgets.logo import RavenLogo

if TYPE_CHECKING:
    from raven.app import RavenApp


class HelpScreen(ModalScreen[None]):
    """Small keyboard reference that keeps help out of the main workflow."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("enter", "dismiss", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Center(), Vertical(id="help-dialog"):
            yield Label("Keyboard help", id="help-title")
            yield Static(
                "[b]Enter[/b]  activate\n[b]C[/b]      configuration\n"
                "[b]R[/b]      refresh services\n[b]?[/b]      open this help\n"
                "[b]Q[/b]      quit Raven\n\n"
                "[b]Chat[/b]   /NEW · /SAVE · /STATS · /INFO"
            )
            yield Button("Close", id="close-help", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-help":
            self.dismiss()


class HomeScreen(Screen[None]):
    """Initial landing screen for the Raven application."""

    BINDINGS = [
        Binding("q", "app.quit", "Quit"),
        Binding("question_mark", "show_help", "Help"),
        Binding("c", "app.navigate('configuration')", "Configuration"),
        Binding("r", "app.refresh_infrastructure", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield TopNavigation(active="home")
        with Vertical(id="home-shell"):
            yield RavenLogo(id="brand-logo")
            yield Label("OSINT GRAPH INTELLIGENCE", id="tagline")
            with Horizontal(id="infrastructure-status"):
                yield ServiceStatusIndicator(ServiceName.MONGODB)
                yield ServiceStatusIndicator(ServiceName.QDRANT)
                yield ServiceStatusIndicator(ServiceName.NEO4J)
                yield ServiceStatusIndicator(ServiceName.AI)
            with Center(id="primary-action-row"):
                yield Button(
                    "Start a new investigation",
                    id="new-investigation",
                    variant="primary",
                )
        yield Footer()

    def on_mount(self) -> None:
        raven_app = cast("RavenApp", self.app)
        raven_app.apply_cached_statuses(self)
        if raven_app.auto_connect:
            raven_app.refresh_infrastructure()

    def on_screen_resume(self) -> None:
        cast("RavenApp", self.app).apply_cached_statuses(self)

    def action_show_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-investigation":
            self._raven_app.navigate("new-investigation")

    @property
    def _raven_app(self) -> RavenApp:
        return cast("RavenApp", self.app)
