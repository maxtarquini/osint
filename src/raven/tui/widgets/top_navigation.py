"""Reusable top-level navigation for Raven screens."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Static

from raven.config import UiLanguage
from raven.tui.i18n import tr


class TopNavigation(Horizontal):
    """Compact keyboard-friendly menu shared by top-level screens."""

    class Navigate(Message):
        """Request navigation to a named application area."""

        def __init__(self, target: str) -> None:
            self.target = target
            super().__init__()

    def __init__(self, *, active: str) -> None:
        super().__init__(id="top-navigation")
        self.active = active

    def compose(self) -> ComposeResult:
        settings = getattr(self.app, "settings", None)
        language = getattr(settings, "interface_language", UiLanguage.ENGLISH)
        yield Static("RAVEN", id="navigation-brand")
        for target, label in (
            ("home", tr(language, "home", "Home")),
            ("investigations", tr(language, "investigations", "Investigations")),
            ("jobs", tr(language, "jobs", "Jobs")),
            ("configuration", tr(language, "configuration", "Configuration")),
        ):
            button = Button(label, id=f"nav-{target}", classes="navigation-item")
            if target == self.active:
                button.add_class("active")
            yield button
        yield Static("GRAPH INTELLIGENCE", id="navigation-context")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        target = event.button.id.removeprefix("nav-") if event.button.id else ""
        event.stop()
        self.post_message(self.Navigate(target))
