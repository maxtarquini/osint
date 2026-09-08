"""Reusable DataTable for the investigation catalog."""

from __future__ import annotations

from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable

from raven.models import Investigation
from raven.tui.i18n import tr


class InvestigationTable(DataTable[str]):
    """Aligned, keyboard-first case catalog with stable row identities."""

    BINDINGS = [
        Binding("enter", "open_selected", "Open"),
        Binding("d", "delete_selected", "Delete"),
    ]

    class OpenRequested(Message):
        def __init__(self, investigation: Investigation) -> None:
            self.investigation = investigation
            super().__init__()

    class DeleteRequested(Message):
        def __init__(self, investigation: Investigation) -> None:
            self.investigation = investigation
            super().__init__()

    def __init__(self) -> None:
        super().__init__(
            id="catalog-table",
            cursor_type="row",
            zebra_stripes=True,
        )
        self.investigations: dict[str, Investigation] = {}

    def on_mount(self) -> None:
        language = self.app.settings.interface_language  # type: ignore[attr-defined]
        self.add_columns(
            tr(language, "name", "Name"),
            tr(language, "status", "Status"),
            tr(language, "updated", "Updated"),
            tr(language, "evidence", "Evidence"),
            tr(language, "language", "Language"),
            tr(language, "domain", "Domain"),
        )

    def set_investigations(self, investigations: tuple[Investigation, ...]) -> None:
        previous = self.cursor_row
        self.clear()
        self.investigations = {
            investigation.investigation_id: investigation for investigation in investigations
        }
        for investigation in investigations:
            self.add_row(
                investigation.name,
                investigation.status.value.title(),
                investigation.updated_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                str(len(investigation.evidence_documents)),
                investigation.analysis_language.value.title(),
                investigation.analysis_domain,
                key=investigation.investigation_id,
            )
        if investigations:
            self.move_cursor(row=min(previous, len(investigations) - 1))

    def selected_investigation(self) -> Investigation | None:
        if self.row_count == 0:
            return None
        key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
        return self.investigations.get(str(key))

    def action_open_selected(self) -> None:
        investigation = self.selected_investigation()
        if investigation:
            self.post_message(self.OpenRequested(investigation))

    def action_delete_selected(self) -> None:
        investigation = self.selected_investigation()
        if investigation:
            self.post_message(self.DeleteRequested(investigation))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        investigation = self.investigations.get(str(event.row_key.value))
        if investigation:
            self.post_message(self.OpenRequested(investigation))
