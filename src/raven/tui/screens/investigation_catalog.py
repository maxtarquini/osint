"""Searchable catalog of persisted investigations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Select, Static

from raven.exceptions import InvestigationError
from raven.models import Investigation
from raven.tui.i18n import tr
from raven.tui.screens.investigation_workspace import ConfirmInvestigationDelete
from raven.tui.widgets import InvestigationTable, TopNavigation

if TYPE_CHECKING:
    from raven.app import RavenApp

logger = logging.getLogger(__name__)


class InvestigationCatalogScreen(Screen[None]):
    """Load, filter, sort, and open investigations from MongoDB."""

    BINDINGS = [
        Binding("escape", "app.navigate('home')", "Home"),
        Binding("n", "new_investigation", "New"),
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "focus_search", "Search"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.investigations: tuple[Investigation, ...] = ()
        self._loading = False
        self._deleting = False
        self._pending_delete: Investigation | None = None

    def compose(self) -> ComposeResult:
        language = self._raven_app.settings.interface_language
        yield TopNavigation(active="investigations")
        yield Label("Investigations", id="catalog-title")
        with Horizontal(id="catalog-toolbar"):
            yield Input(placeholder="Search investigations", id="catalog-search")
            yield Select(
                [("Last updated", "updated"), ("Name", "name")],
                value="updated",
                allow_blank=False,
                id="catalog-sort",
            )
            yield Button(tr(language, "refresh", "Refresh"), id="refresh-investigations")
            yield Button(
                tr(language, "new_investigation", "New investigation"),
                id="new-investigation-catalog",
                variant="primary",
            )
        yield Static("● Loading investigations...", id="catalog-load-status", classes="loading")
        yield InvestigationTable()
        with Horizontal(id="catalog-selection-actions"):
            yield Static(
                "Enter open · D delete · arrows navigate",
                id="catalog-table-hint",
            )
            yield Button(
                tr(language, "open_selected", "Open selected"), id="open-selected-investigation"
            )
            yield Button(
                tr(language, "delete_selected", "Delete selected"),
                id="delete-selected-investigation",
                variant="error",
            )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def action_new_investigation(self) -> None:
        self._raven_app.navigate("new-investigation")

    def action_refresh(self) -> None:
        self._refresh()

    def action_focus_search(self) -> None:
        self.query_one("#catalog-search", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-investigation-catalog":
            self.action_new_investigation()
        elif event.button.id == "refresh-investigations":
            self._refresh()
        elif event.button.id == "open-selected-investigation":
            self.query_one(InvestigationTable).action_open_selected()
        elif event.button.id == "delete-selected-investigation":
            self.query_one(InvestigationTable).action_delete_selected()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "catalog-search" and not self._loading:
            await self._render_catalog()

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "catalog-sort" and not self._loading:
            await self._render_catalog()

    def on_investigation_table_open_requested(
        self, event: InvestigationTable.OpenRequested
    ) -> None:
        if self._deleting:
            return
        self._raven_app.open_investigation(event.investigation)

    def on_investigation_table_delete_requested(
        self,
        event: InvestigationTable.DeleteRequested,
    ) -> None:
        if self._deleting or self._pending_delete is not None:
            return
        self._pending_delete = event.investigation
        self.app.push_screen(
            ConfirmInvestigationDelete(event.investigation),
            self._delete_confirmation_closed,
        )

    def _delete_confirmation_closed(self, confirmed: bool | None) -> None:
        investigation, self._pending_delete = self._pending_delete, None
        if not confirmed or investigation is None or self._deleting:
            return
        self._deleting = True
        self._set_catalog_actions_disabled(True)
        status = self.query_one("#catalog-load-status", Static)
        status.set_classes("loading")
        status.update(f"● Deleting {investigation.name} and all associated data...")
        self._delete_investigation(investigation)

    @work(thread=True, exclusive=True, group="investigation-delete", exit_on_error=False)
    def _delete_investigation(self, investigation: Investigation) -> None:
        try:
            self._raven_app.delete_investigation(investigation)
        except InvestigationError as error:
            self.app.call_from_thread(self._delete_failed, str(error))
        except Exception as error:
            logger.error(
                "Unexpected catalog deletion failure. investigation_id=%s error_type=%s",
                investigation.investigation_id,
                type(error).__name__,
            )
            self.app.call_from_thread(
                self._delete_failed,
                "Unable to delete the investigation; check the Raven log",
            )
        else:
            self.app.call_from_thread(self._delete_succeeded, investigation)

    async def _delete_succeeded(self, investigation: Investigation) -> None:
        if not self.is_mounted:
            return
        self.investigations = tuple(
            item
            for item in self.investigations
            if item.investigation_id != investigation.investigation_id
        )
        self._deleting = False
        self._set_catalog_actions_disabled(False)
        await self._render_catalog()
        self.notify(
            f"{investigation.name}, its Evidence, RAG vectors, graph, chat and cache were deleted.",
            title="Investigation deleted",
        )

    def _delete_failed(self, detail: str) -> None:
        if not self.is_mounted:
            return
        self._deleting = False
        self._set_catalog_actions_disabled(False)
        status = self.query_one("#catalog-load-status", Static)
        status.set_classes("error")
        status.update("● Investigation not deleted")
        status.tooltip = detail
        self.notify(detail, title="Investigation not deleted", severity="error")

    def _set_catalog_actions_disabled(self, disabled: bool) -> None:
        self.query_one("#refresh-investigations", Button).disabled = disabled
        self.query_one("#new-investigation-catalog", Button).disabled = disabled
        self.query_one(InvestigationTable).disabled = disabled
        self.query_one("#open-selected-investigation", Button).disabled = disabled
        self.query_one("#delete-selected-investigation", Button).disabled = disabled

    def _refresh(self) -> None:
        if self._loading or self._deleting:
            return
        self._loading = True
        self.query_one("#refresh-investigations", Button).disabled = True
        status = self.query_one("#catalog-load-status", Static)
        status.set_classes("loading")
        status.update("● Loading investigations...")
        self._load_investigations()

    @work(thread=True, exclusive=True, group="investigation-catalog", exit_on_error=False)
    def _load_investigations(self) -> None:
        try:
            investigations = self._raven_app.list_investigations()
        except InvestigationError as error:
            self.app.call_from_thread(self._load_failed, str(error))
        except Exception as error:
            logger.error("Unexpected catalog load failure. error_type=%s", type(error).__name__)
            self.app.call_from_thread(
                self._load_failed,
                "Unable to load investigations; check the Raven log",
            )
        else:
            self.app.call_from_thread(self._load_succeeded, investigations)

    async def _load_succeeded(self, investigations: tuple[Investigation, ...]) -> None:
        if not self.is_mounted:
            return
        self.investigations = investigations
        self._loading = False
        self.query_one("#refresh-investigations", Button).disabled = False
        await self._render_catalog()

    async def _load_failed(self, detail: str) -> None:
        if not self.is_mounted:
            return
        self._loading = False
        self.query_one("#refresh-investigations", Button).disabled = False
        status = self.query_one("#catalog-load-status", Static)
        status.set_classes("error")
        status.update("● Unable to load investigations")
        status.tooltip = detail
        self.query_one(InvestigationTable).clear()

    async def _render_catalog(self) -> None:
        query = self.query_one("#catalog-search", Input).value.strip().casefold()
        visible = [
            investigation
            for investigation in self.investigations
            if not query
            or query in investigation.name.casefold()
            or query in investigation.description.casefold()
        ]
        sort_value = self.query_one("#catalog-sort", Select).value
        if sort_value == "name":
            visible.sort(key=lambda investigation: investigation.name.casefold())
        else:
            visible.sort(key=lambda investigation: investigation.updated_at, reverse=True)

        self.query_one(InvestigationTable).set_investigations(tuple(visible))
        status = self.query_one("#catalog-load-status", Static)
        status.set_classes("ready")
        status.update(f"● {len(visible)} of {len(self.investigations)} investigations")

    @property
    def _raven_app(self) -> RavenApp:
        return cast("RavenApp", self.app)
