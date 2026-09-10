"""Home and contextual-help screens."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, Footer, Label, Static

from raven.exceptions import InvestigationError
from raven.models import Investigation, ServiceName
from raven.tui.copy import copy
from raven.tui.screens.help import ContextHelpScreen
from raven.tui.widgets import ServiceStatusIndicator, TopNavigation
from raven.tui.widgets.logo import RavenLogo

if TYPE_CHECKING:
    from raven.app import RavenApp


class HelpScreen(ContextHelpScreen):
    """Backward-compatible home help name used by existing integrations."""

    def __init__(self) -> None:
        super().__init__("Home", HomeScreen.BINDINGS)


class RecentInvestigationButton(Button):
    """Compact, keyboard-focusable entry for resuming a recent investigation."""

    def __init__(self, investigation: Investigation) -> None:
        self.investigation = investigation
        evidence = len(investigation.evidence_documents)
        label = (
            f"{investigation.name}  ·  {investigation.updated_at.astimezone():%Y-%m-%d %H:%M}"
            f"  ·  {evidence} evidence"
        )
        super().__init__(label, classes="recent-investigation")


class HomeScreen(Screen[None]):
    """Initial landing screen for the Raven application."""

    BINDINGS = [
        Binding("q", "app.quit", "Quit"),
        Binding("question_mark", "show_help", "Help"),
        Binding("c", "app.navigate('configuration')", "Configuration", show=False),
        Binding("r", "app.refresh_infrastructure", "Refresh", show=False),
        Binding("s", "app.navigate('capabilities')", "Skills & Tools", show=False),
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
            with Center(id="primary-action-row"), Horizontal(id="home-primary-actions"):
                yield Button(
                    copy.text("home.new"),
                    id="new-investigation",
                    variant="primary",
                )
                yield Button(copy.text("home.open"), id="open-investigations")
            with Vertical(id="recent-investigations-panel"):
                yield Static(copy.text("home.recent"), classes="panel-title")
                with VerticalScroll(id="recent-investigations"):
                    yield Static(copy.text("home.no_recent"), id="recent-investigations-empty")
        yield Footer()

    def on_mount(self) -> None:
        raven_app = cast("RavenApp", self.app)
        raven_app.apply_cached_statuses(self)
        self._set_responsive_layout(self.size.width, self.size.height)
        if raven_app.auto_connect:
            raven_app.refresh_infrastructure()

    def on_resize(self, event: Resize) -> None:
        self._set_responsive_layout(event.size.width, event.size.height)

    def _set_responsive_layout(self, width: int, height: int) -> None:
        self.set_class(width < 100 or height <= 28, "compact-home")

    @work(thread=True, exclusive=True, group="home-recent", exit_on_error=False)
    def _load_recent_investigations(self) -> None:
        try:
            investigations = sorted(
                self._raven_app.list_investigations(),
                key=lambda item: item.updated_at,
                reverse=True,
            )[:3]
        except InvestigationError:
            investigations = []
        self.app.call_from_thread(self._show_recent_investigations, investigations)

    async def _show_recent_investigations(self, investigations: list[Investigation]) -> None:
        if not self.is_mounted:
            return
        container = self.query_one("#recent-investigations", VerticalScroll)
        await container.remove_children()
        if investigations:
            await container.mount(*(RecentInvestigationButton(item) for item in investigations))
        else:
            await container.mount(
                Static(copy.text("home.no_recent"), id="recent-investigations-empty")
            )

    def on_screen_resume(self) -> None:
        cast("RavenApp", self.app).apply_cached_statuses(self)
        self._load_recent_investigations()

    def action_show_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-investigation":
            self._raven_app.navigate("new-investigation")
        elif event.button.id == "open-investigations":
            self._raven_app.navigate("investigations")
        elif isinstance(event.button, RecentInvestigationButton):
            self._raven_app.open_investigation(event.button.investigation)

    @property
    def _raven_app(self) -> RavenApp:
        return cast("RavenApp", self.app)
