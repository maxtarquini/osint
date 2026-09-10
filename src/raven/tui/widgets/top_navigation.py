"""Reusable top-level navigation for Raven screens."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.events import Resize
from textual.message import Message
from textual.widgets import Button, Static

from raven.tui.copy import copy


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
        yield Static("RAVEN", id="navigation-brand")
        for target, label in (
            ("home", copy.text("nav.home")),
            ("investigations", copy.text("nav.investigations")),
            ("configuration", copy.text("nav.configuration")),
            ("capabilities", copy.text("nav.capabilities")),
        ):
            button = Button(label, id=f"nav-{target}", classes="navigation-item")
            if target == self.active:
                button.add_class("active")
            yield button
        yield Static("GRAPH INTELLIGENCE", id="navigation-context")

    def on_resize(self, event: Resize) -> None:
        compact = event.size.width < 100
        self.set_class(compact, "compact")
        self.query_one("#nav-investigations", Button).label = (
            copy.text("nav.investigations.short") if compact else copy.text("nav.investigations")
        )
        self.query_one("#nav-configuration", Button).label = (
            copy.text("nav.configuration.short") if compact else copy.text("nav.configuration")
        )
        self.query_one("#nav-capabilities", Button).label = (
            copy.text("nav.capabilities.short") if compact else copy.text("nav.capabilities")
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        target = event.button.id.removeprefix("nav-") if event.button.id else ""
        event.stop()
        self.post_message(self.Navigate(target))
