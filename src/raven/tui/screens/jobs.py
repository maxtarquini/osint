"""Global persistent background-job workspace."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Static

from raven.models import BackgroundJob, JobKind, JobStatus
from raven.tui.i18n import tr
from raven.tui.widgets import TopNavigation

if TYPE_CHECKING:
    from raven.app import RavenApp

logger = logging.getLogger(__name__)


class JobsScreen(Screen[None]):
    """Monitor long-running work independently from investigation screens."""

    BINDINGS = [
        Binding("escape", "app.navigate('home')", "Home"),
        Binding("r", "refresh_jobs", "Refresh"),
        Binding("c", "cancel_job", "Cancel selected"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.jobs: dict[str, BackgroundJob] = {}

    @property
    def _raven_app(self) -> RavenApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        language = self._raven_app.settings.interface_language
        yield TopNavigation(active="jobs")
        with Vertical(id="jobs-workspace"):
            with Horizontal(id="jobs-heading"):
                with Vertical(classes="section-heading"):
                    yield Static("BACKGROUND JOBS", classes="section-kicker")
                    yield Static(
                        "Page catalogs, RAG and graph agents · progress and retained history",
                        classes="section-description",
                    )
                yield Button(
                    tr(language, "cancel_selected", "Cancel selected"),
                    id="cancel-selected-job",
                )
                yield Button(
                    tr(language, "refresh", "Refresh"),
                    id="refresh-jobs",
                    variant="primary",
                )
            yield Static("● Loading job history...", id="jobs-status", classes="running")
            yield DataTable(id="jobs-table", cursor_type="row", zebra_stripes=True)
            yield Static(
                "R refresh · C cancel selected · completed and failed jobs remain in history",
                id="jobs-hint",
            )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#jobs-table", DataTable)
        language = self._raven_app.settings.interface_language
        table.add_columns(
            tr(language, "type", "Type"),
            tr(language, "investigation", "Investigation"),
            tr(language, "status", "Status"),
            tr(language, "progress", "Progress"),
            tr(language, "stage", "Stage"),
            tr(language, "updated", "Updated"),
            tr(language, "message", "Message"),
        )
        self.action_refresh_jobs()

    def action_refresh_jobs(self) -> None:
        self._load_jobs()

    @work(thread=True, exclusive=True, group="jobs-refresh", exit_on_error=False)
    def _load_jobs(self) -> None:
        try:
            jobs = self._raven_app.list_background_jobs()
        except Exception as error:
            logger.warning("Unable to refresh Jobs. error_type=%s", type(error).__name__)
            self.app.call_from_thread(self._show_error)
        else:
            self.app.call_from_thread(self._render_jobs, jobs)

    def _render_jobs(self, jobs: tuple[BackgroundJob, ...]) -> None:
        if not self.is_mounted:
            return
        self.jobs = {job.job_id: job for job in jobs}
        table = self.query_one("#jobs-table", DataTable)
        previous = (
            table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            if table.row_count
            else None
        )
        table.clear()
        for job in jobs:
            progress = (
                f"{job.completed}/{job.total} · {job.progress_percent}%" if job.total else "—"
            )
            message = job.error or job.message
            table.add_row(
                job.kind.value.upper(),
                job.investigation_name or job.investigation_id[:12],
                job.status.value.replace("_", " ").title(),
                progress,
                job.stage.replace("_", " ").title(),
                job.updated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                message,
                key=job.job_id,
            )
        if jobs:
            selected = next((i for i, job in enumerate(jobs) if job.job_id == previous), 0)
            table.move_cursor(row=selected)
        active = sum(job.status in {JobStatus.QUEUED, JobStatus.RUNNING} for job in jobs)
        status = self.query_one("#jobs-status", Static)
        status.set_classes("running" if active else "ready")
        status.update(f"● {active} active · {len(jobs)} retained jobs")

    def _show_error(self) -> None:
        if self.is_mounted:
            status = self.query_one("#jobs-status", Static)
            status.set_classes("error")
            status.update("● Job history unavailable · MongoDB may be disconnected")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-jobs":
            self.action_refresh_jobs()
        elif event.button.id == "cancel-selected-job":
            self.action_cancel_job()

    def action_cancel_job(self) -> None:
        table = self.query_one("#jobs-table", DataTable)
        if table.row_count == 0:
            return
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        job = self.jobs.get(str(key))
        if job is None or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            self.notify("Select an active job.", title="Nothing to cancel", severity="warning")
            return
        if job.kind is JobKind.RAG:
            current = self._raven_app.rag_index_job(job.investigation_id)
            if current is None or current.job_id != job.job_id:
                self.action_refresh_jobs()
                return
            self._raven_app.cancel_rag_index(job.investigation_id)
        elif job.kind is JobKind.CATALOG:
            queue = self._raven_app.catalog_jobs
            current = queue.snapshot(job.investigation_id) if queue else None
            if current is not None and current.job_id == job.job_id:
                queue.cancel(job.investigation_id)
        elif job.kind is JobKind.GRAPH:
            current = self._raven_app.graph_analysis_job(job.investigation_id)
            if current is None or current.job_id != job.job_id:
                self.action_refresh_jobs()
                return
            self._raven_app.cancel_graph_analysis(job.investigation_id)
        self.action_refresh_jobs()
