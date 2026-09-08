"""Graph activity stays decorative, responsive and quiet when it is not visible."""

from datetime import UTC, datetime, timedelta

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import Screen

from raven.tui.widgets import graph_activity
from raven.tui.widgets.graph_activity import GraphBuildActivity


class ActivityApp(App):
    def compose(self) -> ComposeResult:
        with Vertical(id="holder"):
            yield GraphBuildActivity(id="activity")

    def on_mount(self) -> None:
        self.query_one(GraphBuildActivity).styles.height = "auto"
        self.query_one(GraphBuildActivity).styles.color = "#67e8f9"


def test_elapsed_clock_is_idempotent_for_same_job_and_freezes_after_stop(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr(graph_activity, "monotonic", lambda: clock["now"])
    widget = GraphBuildActivity()
    started = datetime.now(UTC) - timedelta(seconds=90)

    widget.start(started)
    assert widget.running and widget.elapsed_seconds == 90
    clock["now"] += 5
    widget.start(started)
    widget.start()
    assert widget.elapsed_seconds == 95
    widget.stop()
    clock["now"] += 30
    widget.stop()
    assert not widget.running and widget.elapsed_seconds == 95
    widget.start()
    assert widget.elapsed_seconds == 0


def test_naive_and_future_start_times_are_safe():
    widget = GraphBuildActivity()
    widget.start(datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=65))
    assert widget.elapsed_seconds == 65
    assert "01:05" in widget.render().plain
    widget.start(datetime.now(UTC) + timedelta(hours=1))
    assert widget.elapsed_seconds == 0


@pytest.mark.parametrize("size,compact", [((80, 24), False), ((40, 24), False), ((80, 24), True)])
async def test_constellation_is_five_lines_or_one_compact_line_without_false_progress(
    size, compact
):
    app = ActivityApp()
    async with app.run_test(size=size) as pilot:
        widget = app.query_one(GraphBuildActivity)
        if compact:
            widget.add_class("compact")
        widget.start(datetime.now(UTC) - timedelta(seconds=12))
        await pilot.pause()

        content = widget.render().plain
        assert len(content.splitlines()) == (1 if compact or size[0] < 55 else 5)
        assert max(map(len, content.splitlines())) <= size[0]
        assert "Building graph" in content and "00:" in content
        assert "%" not in content and "page" not in content.lower()
        assert not widget.can_focus
        assert "not investigation results" in widget.tooltip


async def test_timers_run_only_while_active_and_visible_then_stop_on_unmount():
    app = ActivityApp()
    app.animation_level = "full"
    async with app.run_test(size=(80, 24)) as pilot:
        widget = app.query_one(GraphBuildActivity)
        await pilot.pause(0.2)
        assert widget._frame == 0
        widget.start()
        await pilot.pause(0.3)
        assert widget._frame > 0

        app.query_one("#holder").display = False
        await pilot.pause()
        hidden_frame = widget._frame
        await pilot.pause(0.3)
        assert widget._frame == hidden_frame and widget.running

        app.query_one("#holder").display = True
        await pilot.pause(0.3)
        assert widget._frame != hidden_frame
        widget.stop()
        stopped_frame = widget._frame
        await pilot.pause(0.3)
        assert widget._frame == stopped_frame

        widget.start()
        await widget.remove()
        assert not widget.running
        assert widget._animation_timer is None and widget._elapsed_timer is None


async def test_animation_pauses_on_another_screen_and_resumes_on_return():
    app = ActivityApp()
    app.animation_level = "full"
    async with app.run_test(size=(80, 24)) as pilot:
        widget = app.query_one(GraphBuildActivity)
        widget.start()
        await pilot.pause(0.2)
        await app.push_screen(Screen())
        await pilot.pause()
        paused_frame = widget._frame
        await pilot.pause(0.3)
        assert widget._frame == paused_frame
        app.pop_screen()
        await pilot.pause(0.3)
        assert widget._frame != paused_frame


async def test_animation_none_is_static_but_elapsed_time_remains_available(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr(graph_activity, "monotonic", lambda: clock["now"])
    app = ActivityApp()
    app.animation_level = "none"
    async with app.run_test(size=(80, 24)) as pilot:
        widget = app.query_one(GraphBuildActivity)
        widget.start()
        await pilot.pause(0.3)
        initial = widget.render().plain
        clock["now"] += 8
        widget._refresh_activity_elapsed()
        await pilot.pause()
        assert widget._frame == 0
        assert widget.render().plain.splitlines()[0] == initial.splitlines()[0]
        assert "Elapsed 00:08" in widget.render().plain
