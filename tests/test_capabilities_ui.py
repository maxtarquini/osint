"""Keyboard management and responsive consultation of skill and tool registries."""

import pytest
from test_app import make_app
from test_capabilities import FakeSkillNode
from textual.widgets import DataTable, TabbedContent, TextArea

from raven.services.capabilities import CapabilityRegistry
from raven.tui.screens.capabilities import CapabilitiesScreen, SkillEditor


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.parametrize("size", [(80, 24), (140, 45)])
async def test_capability_create_consult_catalog_edit_toggle_and_navigation(tmp_path, size):
    app = make_app(tmp_path)
    app.capabilities = CapabilityRegistry(tmp_path / "skills", FakeSkillNode())
    async with app.run_test(size=size) as pilot:
        app.navigate("configuration")
        await pilot.pause()
        app.screen.query_one("#configuration-tabs", TabbedContent).active = "capabilities-tab"
        await pilot.pause()
        app.screen.query_one("#manage-capabilities").focus()
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, CapabilitiesScreen)
        screen = app.screen
        assert screen.query_one("#skills-table", DataTable).row_count == 0
        await pilot.click("#seed-skills")
        await settle(app, pilot)
        assert screen.query_one("#skills-table", DataTable).row_count == 6
        for selector in ("#catalog-skills", "#edit-skill", "#toggle-skill", "#seed-skills"):
            widget = screen.query_one(selector)
            assert widget.region.bottom <= size[1]
            assert widget.region.right <= size[0]
            assert widget.region.height == 3
        assert screen.query_one("#skill-details").region.height >= 3
        screen.query_one("#skills-table").focus()
        await pilot.press("enter")
        assert screen.query_one("#skill-details").has_focus
        await pilot.click("#catalog-skills")
        await settle(app, pilot)
        assert all(row["state"] == "ready" for row in screen.rows)
        assert "Analisi con citazioni" in screen.query_one("#skill-details", TextArea).text
        await pilot.click("#edit-skill")
        await settle(app, pilot)
        assert isinstance(app.screen, SkillEditor)
        source = app.screen.query_one("#skill-source-editor", TextArea)
        source.load_text(source.text + "\nNuova regola di prova.")
        await pilot.press("ctrl+s")
        await settle(app, pilot)
        assert app.screen is screen
        assert screen._selected_row()["state"] == "stale"
        await pilot.click("#toggle-skill")
        await settle(app, pilot)
        assert not screen._selected_row()["enabled"]
        screen.query_one(TabbedContent).active = "tools-pane"
        await pilot.pause()
        await pilot.click("#toggle-tool")
        await settle(app, pilot)
        assert screen._selected_tool().tool_id in screen.metadata["disabled_tools"]
        assert "INPUT" in screen.query_one("#tool-details", TextArea).text
        assert screen.query_one("#toggle-tool").region.bottom <= size[1]
        await pilot.press("/")
        assert screen.query_one("#capability-search").has_focus
        await pilot.press("escape")
        assert app.screen is not screen


async def test_editor_validation_stays_open_and_creates_valid_file(tmp_path):
    app = make_app(tmp_path)
    app.capabilities = CapabilityRegistry(tmp_path / "skills", FakeSkillNode())
    async with app.run_test(size=(80, 24)) as pilot:
        app.navigate("capabilities")
        await settle(app, pilot)
        await pilot.click("#new-skill")
        editor = app.screen
        original = editor.query_one("#skill-source-editor", TextArea).text
        editor.query_one("#skill-source-editor", TextArea).load_text("invalid file")
        await pilot.press("ctrl+s")
        await settle(app, pilot)
        assert app.screen is editor
        assert not (tmp_path / "skills" / "new-skill.SKILL").exists()
        editor.query_one("#skill-source-editor", TextArea).load_text(original)
        await pilot.press("ctrl+s")
        await settle(app, pilot)
        assert isinstance(app.screen, CapabilitiesScreen)
        assert app.screen.query_one("#skills-table", DataTable).row_count == 1


async def test_cancel_catalog_keeps_ui_responsive_and_allows_retry(tmp_path):
    from threading import Event

    from raven.exceptions.capabilities import CapabilityCancelled

    app = make_app(tmp_path)
    node = FakeSkillNode()
    started = Event()
    service = CapabilityRegistry(tmp_path / "skills", node)
    service.install_examples()
    app.capabilities = service
    async with app.run_test(size=(80, 24)) as pilot:
        app.navigate("capabilities")
        await settle(app, pilot)
        screen = app.screen

        def block_until_cancelled():
            started.set()
            if not screen.cancelling.wait(5):
                raise AssertionError("The cancel control did not stop the request")
            raise CapabilityCancelled("Cancelled")

        node.callback = block_until_cancelled
        await pilot.click("#catalog-skills")
        await pilot.pause()
        assert started.is_set()
        assert screen.query_one("#catalog-skills").disabled
        assert not screen.query_one("#cancel-skill-catalog").disabled
        await pilot.click("#cancel-skill-catalog")
        await settle(app, pilot)
        assert not screen.busy
        assert all(row["state"] == "not_cataloged" for row in screen.rows)
        node.callback = None
        await pilot.click("#catalog-skills")
        await settle(app, pilot)
        assert all(row["state"] == "ready" for row in screen.rows)
        await pilot.click("#export-skills")
        await settle(app, pilot)
        assert (service.store.root / "raven-discovery-catalog.json").is_file()
