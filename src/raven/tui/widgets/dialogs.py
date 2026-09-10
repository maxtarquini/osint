"""Reusable modal dialogs with deterministic keyboard behavior."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmDialog(ModalScreen[bool]):
    """Confirmation primitive that always names the destructive target."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        dialog_id: str,
        title: str,
        title_id: str,
        subject: str,
        subject_id: str,
        warning: str,
        warning_id: str,
        actions_id: str,
        confirm_label: str,
        confirm_id: str,
        cancel_id: str,
        centered_actions: bool = True,
    ) -> None:
        super().__init__()
        self.dialog_id = dialog_id
        self.dialog_title = title
        self.title_id = title_id
        self.subject = subject
        self.subject_id = subject_id
        self.warning = warning
        self.warning_id = warning_id
        self.actions_id = actions_id
        self.confirm_label = confirm_label
        self.confirm_id = confirm_id
        self.cancel_id = cancel_id
        self.centered_actions = centered_actions

    def compose(self) -> ComposeResult:
        with Vertical(id=self.dialog_id):
            yield Static(self.dialog_title, id=self.title_id)
            yield Static(self.subject, id=self.subject_id, markup=False)
            yield Static(self.warning, id=self.warning_id, markup=False)
            if self.centered_actions:
                with Center(id=self.actions_id), Horizontal():
                    yield from self._buttons()
            else:
                with Horizontal(id=self.actions_id):
                    yield from self._buttons()

    def _buttons(self) -> ComposeResult:
        yield Button(self.confirm_label, id=self.confirm_id, variant="error")
        yield Button("Cancel", id=self.cancel_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == self.confirm_id)

    def action_cancel(self) -> None:
        self.dismiss(False)
