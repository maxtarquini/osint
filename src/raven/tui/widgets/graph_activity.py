"""Decorative, cancellable animation for real graph work without invented progress."""

from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic

from rich.style import Style
from rich.text import Text
from textual.color import Color
from textual.events import Resize
from textual.timer import Timer
from textual.widgets import Static

_CONSTELLATION = (
    "       ◇──────────◇       ",
    "      ╱ ╲        ╱ ╲      ",
    "  ◇──◇───◇──────◇───◇──◇  ",
    "      ╲ ╱        ╲ ╱      ",
    "       ◇──────────◇       ",
)
_POINTS = tuple(
    (row, column)
    for row, line in enumerate(_CONSTELLATION)
    for column, character in enumerate(line)
    if character != " "
)


class GraphBuildActivity(Static):
    """An abstract constellation; its nodes never represent investigation results.

    Repeated ``start`` calls for the same job preserve elapsed time and animation.
    A naive ``started_at`` is interpreted as UTC, matching stored graph timestamps.
    The host owns layout and visibility; this widget never captures keyboard focus.
    """

    can_focus = False
    can_focus_children = False

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__("", id=id, classes=classes)
        self._activity_running = False
        self._shown = False
        self._started_at: datetime | None = None
        self._elapsed_base = 0.0
        self._clock_anchor = 0.0
        self._frame = 0
        self._animation_timer: Timer | None = None
        self._elapsed_timer: Timer | None = None
        self.tooltip = "Activity indicator. The animated nodes are not investigation results."

    @property
    def running(self) -> bool:
        return self._activity_running

    @property
    def elapsed_seconds(self) -> int:
        elapsed = self._elapsed_base
        if self._activity_running:
            elapsed += monotonic() - self._clock_anchor
        return max(0, int(elapsed))

    def start(self, started_at: datetime | None = None) -> None:
        if started_at is not None:
            started_at = (
                started_at.replace(tzinfo=UTC)
                if started_at.tzinfo is None
                else started_at.astimezone(UTC)
            )
        if self._activity_running and (started_at is None or started_at == self._started_at):
            self._sync_activity_timers()
            return
        self._started_at = started_at
        self._elapsed_base = (
            max(0.0, (datetime.now(UTC) - started_at).total_seconds()) if started_at else 0.0
        )
        self._clock_anchor = monotonic()
        self._activity_running = True
        self._frame = 0
        self._sync_activity_timers()
        self.refresh()

    def stop(self) -> None:
        if self._activity_running:
            self._elapsed_base += monotonic() - self._clock_anchor
        self._activity_running = False
        self._sync_activity_timers()
        self.refresh()

    def on_mount(self) -> None:
        self._animation_timer = self.set_interval(1 / 8, self._advance_activity_frame, pause=True)
        self._elapsed_timer = self.set_interval(1, self._refresh_activity_elapsed, pause=True)
        self.app.screen_change_signal.subscribe(self, self._screen_changed)
        self._sync_activity_timers()

    def on_show(self) -> None:
        self._shown = True
        self._sync_activity_timers()
        self.refresh()

    def on_hide(self) -> None:
        self._shown = False
        self._sync_activity_timers()

    def on_unmount(self) -> None:
        self.stop()
        for timer in (self._animation_timer, self._elapsed_timer):
            if timer is not None:
                timer.stop()
        self._animation_timer = self._elapsed_timer = None

    def on_resize(self, _event: Resize) -> None:
        self.refresh(layout=True)

    def _screen_changed(self, _screen: object) -> None:
        self._sync_activity_timers()

    def _is_visible_activity(self) -> bool:
        return (
            self._activity_running
            and self.is_mounted
            and self._shown
            and self.visible
            and self.is_on_screen
            and self.screen.is_active
            and all(ancestor.display for ancestor in self.ancestors)
        )

    def _sync_activity_timers(self) -> None:
        if self._animation_timer is None or self._elapsed_timer is None:
            return
        active = self._is_visible_activity()
        if active:
            self._elapsed_timer.resume()
        else:
            self._elapsed_timer.pause()
        if active and self.app.animation_level != "none":
            self._animation_timer.resume()
        else:
            self._animation_timer.pause()

    def _advance_activity_frame(self) -> None:
        self._sync_activity_timers()
        if not self._is_visible_activity() or self.app.animation_level == "none":
            return
        self._frame = (self._frame + 1) % len(_POINTS)
        self.refresh()

    def _refresh_activity_elapsed(self) -> None:
        self._sync_activity_timers()
        if self._is_visible_activity():
            self.refresh()

    def render(self) -> Text:
        accent = (
            self.styles.color.rich_color if self.is_mounted else Color.parse("#67e8f9").rich_color
        )
        variables = self.app.theme_variables if self.is_mounted else {}
        success = Color.parse(variables.get("success", "#6ee7b7")).rich_color
        muted = Style(color=accent, dim=True)
        bright = Style(color=accent, bold=True)
        pulse = Style(color=success, bold=True)
        seconds = self.elapsed_seconds
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        elapsed = f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"
        width = self.size.width or 54
        motion = self._activity_running and self.is_mounted and self.app.animation_level != "none"
        frame = self._frame if motion else 0
        label = "Building graph" if self._activity_running else "Graph activity"
        text = Text(no_wrap=True, overflow="crop")
        if width < 55 or self.has_class("compact"):
            if width >= 35:
                for index, node in enumerate(("◇", "─", "◇", "─", "◇")):
                    active = index == frame % 5
                    text.append("◆" if active and node == "◇" else node, pulse if active else muted)
                text.append(f"  {label}", bright)
            else:
                text.append("◆ ", pulse)
                if width >= 19:
                    text.append("Graph", bright)
            text.append(f" · {elapsed}", muted)
            text.truncate(width, overflow="crop")
            return text

        head = _POINTS[frame]
        trail = {_POINTS[(frame - index) % len(_POINTS)] for index in range(1, 5)}
        for row, line in enumerate(_CONSTELLATION):
            if row:
                text.append("\n")
            for column, character in enumerate(line):
                position = (row, column)
                style = pulse if position == head else bright if position in trail else muted
                text.append("◆" if position == head and character == "◇" else character, style)
            if row == 1:
                text.append(f"  {label}", bright)
            elif row == 3:
                text.append(f"  Elapsed {elapsed}", muted)
        return text
