"""Keyboard management and responsive consultation of skill and tool registries."""

import pytest
from test_app import make_app
from test_capabilities import FakeSkillNode
from textual.widgets import DataTable, TabbedContent, TextArea

from raven.services.capabilities import CapabilityRegistry
from raven.tui.screens.capabilities import (
    CapabilitiesScreen,
    CatalogDetailScreen,
    SkillEditor,
)


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


@pytest.mark.parametrize("size", [(80, 24), (140, 45)])
async def test_catalog_navigation_filters_dependencies_and_mcp_contracts(tmp_path, size):
    import json

    from textual.widgets import Button, Input, Select

    from raven.mcp_server import input_schema
    from raven.services.capability_tools import TOOLS

    app = make_app(tmp_path)
    registry = CapabilityRegistry(tmp_path / "skills", FakeSkillNode())
    registry.install_examples()
    registry.catalog()
    registry.set_enabled("tools", "verify_quote", False)
    app.capabilities = registry
    async with app.run_test(size=size) as pilot:
        home = app.screen
        button = home.query_one("#nav-capabilities", Button)
        assert button.region.right <= size[0] and button.region.width >= 10
        await pilot.click("#nav-capabilities")
        await settle(app, pilot)
        screen = app.screen
        assert isinstance(screen, CapabilitiesScreen)
        filters = screen.query_one("#capability-state", Select)
        assert filters.region.right <= size[0]
        assert screen.query_one("#skill-tools").region.right <= size[0]
        filters.value = "available"
        await pilot.pause()
        assert not screen.skill_keys  # All bundled skills depend on verify_quote.
        assert "filtri" in screen.query_one("#skill-details", TextArea).text
        filters.value = "review"
        await pilot.pause()
        assert len(screen.skill_keys) == 6
        filters.value = "all"
        await pilot.pause()
        skill = screen._selected_row()["entry"].definition
        await pilot.click("#skill-tools")
        await pilot.pause()
        assert screen.query_one(TabbedContent).active == "tools-pane"
        assert {t.tool_id for t in screen.tool_keys} == set(skill.tools)
        assert skill.name in screen.query_one("#tool-details", TextArea).text
        await pilot.click("#all-tools")
        await pilot.pause()
        assert len(screen.tool_keys) == len(TOOLS)
        filters.value = "disabled"
        await pilot.pause()
        assert [t.tool_id for t in screen.tool_keys] == ["verify_quote"]
        filters.value = "all"
        screen.query_one("#capability-search", Input).value = "retrieve_evidence"
        await pilot.pause()
        details = screen.query_one("#tool-details", TextArea).text
        assert "Qdrant e Neo4j" in details
        assert "local source snapshot" not in details
        await pilot.press("f3")
        assert isinstance(app.screen, CatalogDetailScreen)
        full = app.screen.query_one("#catalog-detail-text", TextArea)
        assert full.region.height >= size[1] - 8
        assert "INPUT MCP" in full.text
        await pilot.press("escape")
        assert app.screen is screen
        displayed = details.split("INPUT MCP · tools/call\n", 1)[1].split("\n\nINPUT LOCALE", 1)[0]
        assert json.loads(displayed) == input_schema(screen._selected_tool())
        screen.query_one("#capability-search", Input).value = "no-such-tool"
        await pilot.pause()
        assert screen.query_one("#toggle-tool", Button).disabled
        assert "Nessun tool" in screen.query_one("#tool-details", TextArea).text
        await pilot.press("escape")
        assert app.screen is home
        await pilot.press("s")
        await settle(app, pilot)
        assert isinstance(app.screen, CapabilitiesScreen)


@pytest.mark.parametrize("size", [(80, 24), (140, 45)])
async def test_catalog_split_drag_keyboard_and_resize_preserve_selection(tmp_path, size):
    from test_graph_split import drag

    from raven.tui.widgets.resizable_split import CatalogSplit, PaneDivider

    app = make_app(tmp_path)
    app.capabilities = CapabilityRegistry(tmp_path / "skills", FakeSkillNode())
    app.capabilities.install_examples()
    async with app.run_test(size=size) as pilot:
        app.navigate("capabilities")
        await settle(app, pilot)
        screen = app.screen
        tabs = screen.query_one(TabbedContent)
        for kind, detail_id in (("skills", "skill-details"), ("tools", "tool-details")):
            tabs.active = f"{kind}-pane"
            await pilot.pause()
            split = screen.query_one(f"#{kind}-split", CatalogSplit)
            divider = screen.query_one(f"#{kind}-divider", PaneDivider)
            table = screen.query_one(f"#{kind}-table", DataTable)
            details = screen.query_one(f"#{detail_id}", TextArea)
            table.focus()
            await pilot.press("down", "down")
            selected, text = table.cursor_row, details.text
            assert table.region.y == details.region.y
            assert table.region.right == divider.region.x
            assert divider.region.right == details.region.x
            assert table.region.height == details.region.height >= 6
            assert details.region.right <= size[0]
            initial = split.details_width
            await drag(pilot, divider, divider.region.x + 7)
            assert split.details_width == initial - 6
            assert table.cursor_row == selected and details.text == text
            await pilot.press("left")
            assert split.details_width == initial - 2
            await pilot.press("home")
            assert split.details_width == initial
            await drag(pilot, divider, divider.region.x + 9)
            chosen = split.details_width
            # Switching tabs must release captured mouse input and preserve each ratio.
            await pilot.mouse_down(divider, offset=(1, 2))
            tabs.active = "tools-pane" if kind == "skills" else "skills-pane"
            await pilot.pause()
            assert app.mouse_captured is None
            tabs.active = f"{kind}-pane"
            await pilot.pause()
            assert split.details_width == chosen
            await pilot.resize_terminal(100, 30)
            await pilot.pause()
            assert table.region.width >= 24 and details.region.width >= 32
            assert details.region.right <= 100
            await pilot.resize_terminal(*size)
            await pilot.pause()
            assert split.details_width == chosen
            assert table.cursor_row == selected and details.text == text
            # Both extremes keep the list and card usable, without hiding the actions.
            await drag(pilot, divider, 1)
            assert table.region.width >= 24
            await drag(pilot, divider, size[0] - 1)
            assert details.region.width >= 32
            await pilot.click(divider, offset=(1, 2), times=2)
            assert split.details_width == initial
            await pilot.press("tab")
            assert details.has_focus


@pytest.mark.parametrize("size", [(80, 24), (140, 45)])
async def test_catalog_main_menu_routes_and_nested_home(tmp_path, size):
    from raven.tui.screens.configuration import ConfigurationScreen
    from raven.tui.screens.investigation_catalog import InvestigationCatalogScreen

    app = make_app(tmp_path)
    app.capabilities = CapabilityRegistry(tmp_path / "skills", FakeSkillNode())
    async with app.run_test(size=size) as pilot:
        home = app.screen
        home_depth = len(app.screen_stack)
        await pilot.click("#nav-configuration")
        await pilot.pause()
        await pilot.click("#nav-capabilities")
        await settle(app, pilot)
        catalog = app.screen
        depth = len(app.screen_stack)
        for target in ("home", "investigations", "configuration", "capabilities"):
            button = catalog.query_one(f"#nav-{target}")
            assert 0 <= button.region.x < button.region.right <= size[0]
            assert button.region.y == 0 and not button.disabled
        assert catalog.query_one("#nav-capabilities").has_class("active")
        await pilot.click("#nav-capabilities")
        assert app.screen is catalog and len(app.screen_stack) == depth
        catalog.query_one("#nav-investigations").focus()
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, InvestigationCatalogScreen)
        await pilot.click("#nav-capabilities")
        await settle(app, pilot)
        await pilot.click("#nav-configuration")
        await pilot.pause()
        assert isinstance(app.screen, ConfigurationScreen)
        await pilot.click("#nav-capabilities")
        await settle(app, pilot)
        await pilot.click("#nav-home")
        await pilot.pause()
        assert app.screen is home and len(app.screen_stack) == home_depth


async def test_catalog_menu_stays_enabled_during_work_and_home_cancels(tmp_path):
    from threading import Event

    from raven.exceptions.capabilities import CapabilityCancelled

    app = make_app(tmp_path)
    node = FakeSkillNode()
    started, cancelled = Event(), Event()
    app.capabilities = CapabilityRegistry(tmp_path / "skills", node)
    app.capabilities.install_examples()
    async with app.run_test(size=(80, 24)) as pilot:
        home = app.screen
        await pilot.click("#nav-capabilities")
        await settle(app, pilot)
        screen = app.screen

        def wait_for_leaving():
            started.set()
            if not screen.cancelling.wait(5):
                raise AssertionError("Leaving the catalog did not cancel the operation")
            cancelled.set()
            raise CapabilityCancelled("Cancelled")

        node.callback = wait_for_leaving
        await pilot.click("#catalog-skills")
        await pilot.pause()
        assert started.is_set() and screen.busy
        for target in ("home", "investigations", "configuration", "capabilities"):
            assert not screen.query_one(f"#nav-{target}").disabled
        await pilot.click("#nav-home")
        await settle(app, pilot)
        assert app.screen is home and cancelled.is_set()
