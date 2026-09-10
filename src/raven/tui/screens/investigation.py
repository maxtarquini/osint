"""Investigation creation workflow and evidence knowledge-base input."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Select, Static, TextArea

from raven.exceptions import InvestigationError
from raven.models import (
    DEFAULT_ANALYSIS_DOMAIN,
    AnalysisLanguage,
    Investigation,
    InvestigationDomain,
    InvestigationDraft,
)
from raven.tui.widgets import TopNavigation

if TYPE_CHECKING:
    from raven.app import RavenApp

logger = logging.getLogger(__name__)


class InvestigationCreateScreen(Screen[None]):
    """Create or edit the brief before opening an investigation workspace."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "create", "Create"),
        Binding("question_mark", "app.context_help", "Help"),
    ]

    def __init__(
        self,
        domains: tuple[InvestigationDomain, ...] = (),
        *,
        investigation: Investigation | None = None,
    ) -> None:
        super().__init__()
        self._creating = False
        self.investigation = investigation
        self.domains = domains or (
            InvestigationDomain(
                DEFAULT_ANALYSIS_DOMAIN,
                "General OSINT",
                "General-purpose OSINT named-entity vocabulary",
            ),
        )
        self._domains_by_code = {domain.code: domain for domain in self.domains}

    def compose(self) -> ComposeResult:
        yield TopNavigation(active="investigations")
        editing = self.investigation is not None
        yield Label(
            "Edit investigation" if editing else "Create investigation",
            id="investigation-title",
        )
        yield Static(
            (
                "Update the case profile. Changing language or dictionary invalidates the "
                "derived graph and RAG index."
                if editing
                else "Define the investigation; evidence is managed after opening its workspace."
            ),
            id="investigation-hint",
        )
        with VerticalScroll(id="investigation-form"):
            yield Label("Name")
            yield Input(
                value=self.investigation.name if self.investigation else "",
                id="investigation-name",
                placeholder="e.g. Operation Raven",
            )
            yield Label("Description / context (optional)")
            yield TextArea(
                self.investigation.description if self.investigation else "",
                id="investigation-description",
                classes="short-editor",
            )
            yield Label("Reference / document normalization language")
            yield Select(
                [
                    ("Original language of each evidence", AnalysisLanguage.ORIGINAL.value),
                    ("Italian", AnalysisLanguage.ITALIAN.value),
                    ("English", AnalysisLanguage.ENGLISH.value),
                    ("French", AnalysisLanguage.FRENCH.value),
                    ("Spanish", AnalysisLanguage.SPANISH.value),
                    ("German", AnalysisLanguage.GERMAN.value),
                    ("Arabic", AnalysisLanguage.ARABIC.value),
                ],
                value=(
                    self.investigation.analysis_language.value
                    if self.investigation
                    else AnalysisLanguage.ORIGINAL.value
                ),
                allow_blank=False,
                id="investigation-analysis-language",
            )
            yield Label("Analysis domain")
            yield Select(
                [(f"{domain.name}  [{domain.code}]", domain.code) for domain in self.domains],
                value=self._selected_domain(),
                allow_blank=False,
                id="investigation-analysis-domain",
            )
            initial_domain = self._domains_by_code[self._selected_domain()]
            yield Static(
                initial_domain.description,
                id="investigation-domain-description",
                markup=False,
            )
            yield Label("Investigation questions · one per line")
            yield TextArea(
                "\n".join(self.investigation.questions) if self.investigation else "",
                id="investigation-questions",
                classes="questions-editor",
            )
        with Center(id="investigation-actions"), Horizontal():
            yield Static("● Ready", id="investigation-create-status", classes="ready")
            yield Button(
                "Save changes" if editing else "Create",
                id="create-investigation",
                variant="primary",
            )
            yield Button("Cancel", id="cancel-investigation")
        yield Footer()

    def on_mount(self) -> None:
        self._set_responsive_layout(self.size.height)

    def on_resize(self, event: Resize) -> None:
        self._set_responsive_layout(event.size.height)

    def _set_responsive_layout(self, height: int) -> None:
        self.set_class(height <= 26, "compact-investigation-form")

    def action_create(self) -> None:
        self._start_creation()

    def action_cancel(self) -> None:
        self._cancel()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-investigation":
            self._start_creation()
        elif event.button.id == "cancel-investigation":
            self._cancel()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "investigation-analysis-domain" or not isinstance(event.value, str):
            return
        domain = self._domains_by_code[event.value]
        self.query_one("#investigation-domain-description", Static).update(domain.description)

    def _start_creation(self) -> None:
        if self._creating:
            return
        try:
            draft = self._draft().validated()
        except InvestigationError as error:
            self.notify(str(error), title="Invalid investigation", severity="error")
            return
        self._creating = True
        self._set_form_disabled(True)
        status = self.query_one("#investigation-create-status", Static)
        status.set_classes("running")
        status.update(
            "● Saving investigation..."
            if self.investigation is not None
            else "● Creating investigation..."
        )
        self._create_investigation(draft)

    @work(thread=True, exclusive=True, group="investigation-create", exit_on_error=False)
    def _create_investigation(self, draft: InvestigationDraft) -> None:
        try:
            if self.investigation is None:
                investigation = self._raven_app.create_investigation(draft)
            else:
                investigation = self._raven_app.update_investigation(
                    self.investigation,
                    draft,
                )
        except InvestigationError as error:
            self.app.call_from_thread(self._creation_failed, str(error))
        except Exception as error:
            logger.error(
                "Unexpected investigation creation failure. error_type=%s",
                type(error).__name__,
            )
            self.app.call_from_thread(
                self._creation_failed,
                "Unable to create the investigation; check the Raven log",
            )
        else:
            self.app.call_from_thread(self._creation_succeeded, investigation)

    def _creation_succeeded(self, investigation: Investigation) -> None:
        if self.is_mounted:
            if self.investigation is None:
                self._raven_app.investigation_created(investigation)
            else:
                self._raven_app.investigation_updated(investigation)

    def _creation_failed(self, detail: str) -> None:
        if not self.is_mounted:
            return
        self._creating = False
        self._set_form_disabled(False)
        status = self.query_one("#investigation-create-status", Static)
        status.set_classes("error")
        status.update("● Creation failed")
        status.tooltip = detail
        self.notify(detail, title="Investigation not saved", severity="error")

    def _cancel(self) -> None:
        if self._creating:
            self.notify("Investigation creation is still running.", title="Please wait")
            return
        if self.investigation is not None:
            self.app.pop_screen()
        else:
            self._raven_app.navigate("home")

    def _selected_domain(self) -> str:
        if (
            self.investigation is not None
            and self.investigation.analysis_domain in self._domains_by_code
        ):
            return self.investigation.analysis_domain
        if DEFAULT_ANALYSIS_DOMAIN in self._domains_by_code:
            return DEFAULT_ANALYSIS_DOMAIN
        return self.domains[0].code

    def _set_form_disabled(self, disabled: bool) -> None:
        self.query_one("#create-investigation", Button).disabled = disabled
        self.query_one("#cancel-investigation", Button).disabled = disabled
        self.query_one("#investigation-name", Input).disabled = disabled
        self.query_one("#investigation-analysis-language", Select).disabled = disabled
        self.query_one("#investigation-analysis-domain", Select).disabled = disabled
        for editor_id in (
            "investigation-description",
            "investigation-questions",
        ):
            self.query_one(f"#{editor_id}", TextArea).disabled = disabled

    def _draft(self) -> InvestigationDraft:
        questions = tuple(
            line for line in self.query_one("#investigation-questions", TextArea).text.splitlines()
        )
        return InvestigationDraft(
            name=self.query_one("#investigation-name", Input).value,
            description=self.query_one("#investigation-description", TextArea).text,
            questions=questions,
            analysis_language=AnalysisLanguage(
                self.query_one("#investigation-analysis-language", Select).value
            ),
            analysis_domain=cast(
                str,
                self.query_one("#investigation-analysis-domain", Select).value,
            ),
        )

    @property
    def _raven_app(self) -> RavenApp:
        return cast("RavenApp", self.app)
