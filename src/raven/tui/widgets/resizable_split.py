"""Mouse and keyboard resizing for a main pane and its details sidebar."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Click, MouseDown, MouseMove, MouseUp
from textual.message import Message
from textual.widgets import Static


class PaneDivider(Static):
    """Focusable drag handle between the two children of a ResizableSplit."""

    can_focus = True
    BINDINGS = [
        Binding("left", "widen", "Allarga dettagli"),
        Binding("right", "narrow", "Riduci dettagli"),
        Binding("home", "reset", "Ripristina spazi"),
    ]

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._drag_start: tuple[int, int] | None = None
        self.tooltip = (
            "Trascina per ridimensionare i pannelli. "
            "Con Tab seleziona il separatore, poi usa ←/→. Home o doppio clic ripristina."
        )

    @property
    def split(self) -> ResizableSplit:
        assert isinstance(self.parent, ResizableSplit)
        return self.parent

    def render(self) -> Text:
        height = max(1, self.size.height)
        rows = [" │ "] * height
        rows[height // 2] = " ↔ "
        return Text("\n".join(rows))

    def on_mouse_down(self, event: MouseDown) -> None:
        if event.button == 1:
            event.stop()
            event.prevent_default()
            self.focus()
            self._drag_start = (event.screen_x, self.split.details_width)
            self.capture_mouse()
            self.add_class("dragging")

    def on_mouse_move(self, event: MouseMove) -> None:
        if self._drag_start is not None:
            event.stop()
            origin, width = self._drag_start
            self.split.set_details_width(width + origin - event.screen_x)

    def on_mouse_up(self, event: MouseUp) -> None:
        if event.button == 1 and self._drag_start is not None:
            event.stop()
            origin, width = self._drag_start
            self.split.set_details_width(width + origin - event.screen_x)
            self.stop_drag()

    def stop_drag(self) -> None:
        self._drag_start = None
        self.remove_class("dragging")
        if self.app.mouse_captured is self:
            self.release_mouse()

    def on_hide(self) -> None:
        self.stop_drag()

    def on_unmount(self) -> None:
        self.stop_drag()

    def on_click(self, event: Click) -> None:
        event.stop()
        if event.chain == 2:
            self.action_reset()

    def action_widen(self) -> None:
        self.split.set_details_width(self.split.details_width + 4)

    def action_narrow(self) -> None:
        self.split.set_details_width(self.split.details_width - 4)

    def action_reset(self) -> None:
        self.split.reset_split()


class ResizableSplit(Horizontal):
    """Main pane, PaneDivider, details pane; remember proportions within the workspace.

    Clamping on terminal resize preserves the preferred ratio, so returning to a larger
    terminal restores the chosen layout instead of keeping the compact sidebar width.
    """

    class Resized(Message):
        def __init__(self, main_width: int) -> None:
            self.main_width = main_width
            super().__init__()

    DEFAULT_RATIO = 0.30

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._details_ratio = self.DEFAULT_RATIO

    @property
    def details_width(self) -> int:
        return self.children[-1].region.width

    @property
    def _pane_space(self) -> int:
        return max(0, self.content_size.width - 3)

    def _clamp_width(self, width: int) -> int:
        available = self._pane_space
        # Leave the graph at least 40 columns and never let either pane disappear.
        maximum = max(1, min(int(available * 0.60), available - 40))
        minimum = min(28 if available < 110 else 36, maximum)
        return max(minimum, min(maximum, width))

    def set_details_width(self, width: int) -> None:
        if self._pane_space:
            self._details_ratio = self._clamp_width(width) / self._pane_space
            self._apply_width()

    def reset_split(self) -> None:
        self._details_ratio = self.DEFAULT_RATIO
        self._apply_width()

    def _apply_width(self) -> None:
        if len(self.children) == 3 and self._pane_space:
            width = self._clamp_width(round(self._pane_space * self._details_ratio))
            self.children[-1].styles.width = width
            self.post_message(self.Resized(self._pane_space - width))

    def on_resize(self) -> None:
        for divider in self.query(PaneDivider):
            divider.stop_drag()
        self._apply_width()

    def on_show(self) -> None:
        self.call_after_refresh(self._apply_width)

    def on_hide(self) -> None:
        for divider in self.query(PaneDivider):
            divider.stop_drag()


class CatalogSplit(ResizableSplit):
    """A catalog list on the left, with most of the space reserved for its card."""

    DEFAULT_RATIO = 0.65

    def _clamp_width(self, width: int) -> int:
        maximum = max(1, self._pane_space - 24)
        minimum = min(32, maximum)
        return max(minimum, min(maximum, width))
