"""Overview and investigation-lifecycle actions for the workspace."""

from __future__ import annotations

import logging

from textual import work
from textual.widgets import Button

from raven.exceptions import InvestigationError

logger = logging.getLogger(__name__)


class WorkspaceOverviewActions:
    """Handle destructive case actions outside the presentation screen."""

    def _delete_investigation_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed or self._deleting:
            return
        self._deleting = True
        self.query_one("#edit-investigation", Button).disabled = True
        self.query_one("#delete-investigation", Button).disabled = True
        self.notify(
            "Deleting case data and isolated Evidence storage...",
            title="Deleting investigation",
        )
        self._delete_investigation()

    @work(thread=True, exclusive=True, group="investigation-delete", exit_on_error=False)
    def _delete_investigation(self) -> None:
        try:
            self._raven_app.delete_investigation(self.investigation)
        except InvestigationError as error:
            self.app.call_from_thread(self._investigation_delete_failed, str(error))
        except Exception as error:
            logger.error(
                "Unexpected investigation deletion failure. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
            self.app.call_from_thread(
                self._investigation_delete_failed,
                "Unable to delete the investigation; check the Raven log",
            )
        else:
            self.app.call_from_thread(
                self._raven_app.investigation_deleted,
                self.investigation,
            )

    def _investigation_delete_failed(self, detail: str) -> None:
        if not self.is_mounted:
            return
        self._deleting = False
        self.query_one("#edit-investigation", Button).disabled = False
        self.query_one("#delete-investigation", Button).disabled = False
        self.notify(detail, title="Investigation not deleted", severity="error")
