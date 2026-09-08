"""Connection state text must fit its card and retain semantic colors."""

from dataclasses import replace

import pytest
from test_app import FakeInfrastructure, make_app
from textual.color import Color
from textual.geometry import Region

from raven.config import RavenSettings, UiLanguage
from raven.models import ConnectionState, ServiceName, ServiceStatus
from raven.tui.design import raven_theme
from raven.tui.widgets.service_status import (
    ITALIAN_STATE_LABELS,
    STATE_LABELS,
    STATE_SYMBOLS,
    ServiceStatusIndicator,
)


@pytest.mark.parametrize("size", [(80, 24), (160, 45)])
@pytest.mark.parametrize("language", [UiLanguage.ITALIAN, UiLanguage.ENGLISH])
@pytest.mark.parametrize("appearance", ["dark", "light"])
async def test_all_service_states_have_visible_labels_and_distinct_colors(
    tmp_path,
    size,
    language,
    appearance,
):
    app = make_app(tmp_path, infrastructure=FakeInfrastructure())
    legacy = app.settings.to_public_dict()
    legacy["interface"]["appearance"] = appearance
    app.settings = replace(RavenSettings.from_dict(legacy), interface_language=language)
    app.apply_design()
    theme = raven_theme()
    colors = {
        ConnectionState.CONNECTED: theme.success,
        ConnectionState.UNAVAILABLE: theme.error,
        ConnectionState.CHECKING: theme.warning,
        ConnectionState.AUTHENTICATION_REQUIRED: theme.warning,
        ConnectionState.CONFIGURATION_REQUIRED: theme.warning,
    }
    labels = ITALIAN_STATE_LABELS if language is UiLanguage.ITALIAN else STATE_LABELS
    async with app.run_test(size=size) as pilot:
        indicator = app.screen.query_one("#status-mongodb", ServiceStatusIndicator)
        for state in ConnectionState:
            indicator.set_status(ServiceStatus(ServiceName.MONGODB, state, "Safe detail"))
            await pilot.pause()
            lines = indicator.render_lines(
                Region(1, 1, indicator.region.width - 2, indicator.region.height - 2)
            )
            rendered = " ".join(" ".join(line.text for line in lines).split())
            assert labels[state] in rendered
            assert STATE_SYMBOLS[state] in rendered
            expected = Color.parse(colors[state])
            # Textual's theme conversion may round RGB channels by one unit.
            assert (
                max(
                    abs(getattr(indicator.styles.color, channel) - getattr(expected, channel))
                    for channel in ("r", "g", "b")
                )
                <= 1
            )
            assert indicator.region.bottom <= size[1] - 1
        assert Color.parse(theme.success) != Color.parse(theme.accent)
        assert not app.use_command_palette
        assert set(app.available_themes) == {"raven"}
        home = app.screen
        await pilot.press("ctrl+p")
        app.action_change_theme()
        app.action_toggle_dark()
        await pilot.pause()
        assert app.screen is home and app.theme == "raven"
        app.navigate("configuration")
        await pilot.pause()
        assert not app.screen.query("#interface-palette")
        assert not app.screen.query("#interface-appearance")
