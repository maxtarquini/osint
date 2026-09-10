"""Contextual keyboard help shared by all Raven workflows."""

from __future__ import annotations

from collections.abc import Iterable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from raven.tui.copy import copy


class ContextHelpScreen(ModalScreen[None]):
    """Show global navigation and the bindings exposed by the current screen."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("enter", "dismiss", "Close", show=False),
    ]

    def __init__(self, screen_name: str, bindings: Iterable[Binding]) -> None:
        super().__init__()
        self.screen_name = screen_name
        self.context_bindings = tuple(bindings)

    def compose(self) -> ComposeResult:
        rows = ["Tab / Shift+Tab  move focus", "Enter            activate"]
        seen: set[tuple[str, str]] = set()
        for binding in self.context_bindings:
            key = binding.key.replace("question_mark", "?")
            item = (key, binding.description)
            if not binding.description or item in seen:
                continue
            seen.add(item)
            rows.append(f"{key:<16} {binding.description}")
        with Center(), Vertical(id="help-dialog"):
            yield Label(copy.text("help.title"), id="help-title")
            yield Static(self.screen_name, id="help-context")
            yield Static("\n".join(rows), id="help-bindings", markup=False)
            yield Button(copy.text("help.close"), id="close-help", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-help":
            self.dismiss()
