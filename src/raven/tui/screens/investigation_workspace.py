"""Opened investigation workspace with independent evidence management."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    LoadingIndicator,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from raven.exceptions import (
    GraphAnalysisError,
    InvestigationCancelledError,
    InvestigationChatCancelledError,
    InvestigationChatError,
    InvestigationError,
)
from raven.models import (
    ChatEventKind,
    ChatMessage,
    ChatRole,
    EvidenceDocument,
    EvidenceIngestionState,
    EvidencePreparationMode,
    GraphAnalysisJob,
    GraphAnalysisResult,
    GraphEntity,
    GraphJobStatus,
    GraphRelationship,
    GraphRunStatus,
    Investigation,
    InvestigationGraph,
    RagIndexProgress,
    TokenUsage,
)
from raven.models.graph import EvidenceSpan
from raven.tui.actions import ChatCommand, ChatCommandError, parse_chat_command
from raven.tui.screens.document_catalog import DocumentCatalogScreen
from raven.tui.screens.file_picker import (
    ConfirmEvidenceDelete,
    EvidenceFilePicker,
    MarkdownExportPicker,
)
from raven.tui.screens.graph_claims import GraphClaimsScreen
from raven.tui.widgets import (
    ChatMessageView,
    EvidenceRow,
    GraphCanvas,
    LocalCommandView,
    StreamingAssistantView,
    TopNavigation,
)
from raven.tui.widgets.claim_details import ClaimDetails
from raven.tui.widgets.graph_activity import GraphBuildActivity
from raven.tui.widgets.resizable_split import PaneDivider, ResizableSplit

if TYPE_CHECKING:
    from raven.app import RavenApp

logger = logging.getLogger(__name__)


class ConfirmClearChat(ModalScreen[bool]):
    """Require explicit confirmation before deleting one investigation's chat history."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, investigation: Investigation) -> None:
        super().__init__()
        self.investigation = investigation

    def compose(self) -> ComposeResult:
        with Vertical(id="clear-chat-dialog"):
            yield Static("CLEAR CHAT HISTORY", id="clear-chat-title")
            yield Static(
                self.investigation.name,
                id="clear-chat-investigation",
                markup=False,
            )
            yield Static(
                "Delete every saved chat turn for this investigation? Evidence and graph data "
                "will not be changed.",
                id="clear-chat-warning",
            )
            with Center(id="clear-chat-actions"), Horizontal():
                yield Button("Delete history", id="confirm-clear-chat", variant="error")
                yield Button("Cancel", id="cancel-clear-chat")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-clear-chat")

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConfirmInvestigationDelete(ModalScreen[bool]):
    """Require explicit confirmation before deleting an entire investigation."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, investigation: Investigation) -> None:
        super().__init__()
        self.investigation = investigation

    def compose(self) -> ComposeResult:
        with Vertical(id="delete-investigation-dialog"):
            yield Static("DELETE INVESTIGATION", id="delete-investigation-title")
            yield Static(
                self.investigation.name,
                id="delete-investigation-name",
                markup=False,
            )
            yield Static(
                "This permanently removes the case, copied Evidence files, chat history, "
                "RAG vectors, graph data, and any local case cache. Original source files "
                "are not changed.",
                id="delete-investigation-warning",
                markup=False,
            )
            with Center(id="delete-investigation-actions"), Horizontal():
                yield Button(
                    "Delete investigation",
                    id="confirm-delete-investigation",
                    variant="error",
                )
                yield Button("Cancel", id="cancel-delete-investigation")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-delete-investigation")

    def action_cancel(self) -> None:
        self.dismiss(False)


class InvestigationWorkspaceScreen(Screen[None]):
    """Operate on one opened investigation and its knowledge base."""

    BINDINGS = [
        Binding("escape", "app.navigate('home')", "Home"),
        Binding("a", "add_evidence", "Add evidence"),
        Binding("o", "show_overview", "Overview", show=False),
        Binding("e", "show_evidence", "Evidence", show=False),
        Binding("g", "show_graph", "Graph", show=False),
        Binding("c", "show_chat", "Chat", show=False),
        Binding("ctrl+enter", "send_chat", "Send chat"),
        Binding("ctrl+i", "index_rag", "Index RAG"),
        Binding("slash", "focus_graph_search", "Find entity", show=False),
        Binding("ctrl+g", "analyze_graph", "Analyze graph"),
    ]

    def __init__(self, investigation: Investigation) -> None:
        super().__init__()
        self.investigation = investigation
        self.documents = list(investigation.evidence_documents)
        self._busy = False
        self._upload_cancel = Event()
        self._graph_busy = False
        self._applied_graph_job_id: str | None = None
        self.graph: InvestigationGraph | None = None
        self._last_evidence_source_directory = Path.home()
        self._chat_busy = False
        self._chat_cancel = Event()
        self._active_response: StreamingAssistantView | None = None
        self._chat_sources: tuple[str, ...] = ()
        self._rag_indexing = False
        self._rag_target = None
        self._rag_state_revision = 0
        self._chat_input_tokens = 0
        self._chat_output_tokens = 0
        self._chat_total_tokens = 0
        self._chat_saved_messages = 0
        self._last_assistant_markdown: str | None = None
        self._last_assistant_sources: tuple[str, ...] = ()
        self._last_export_directory = Path.home()
        self._deleting = False

    def compose(self) -> ComposeResult:
        yield TopNavigation(active="investigations")
        with Horizontal(id="workspace-summary"):
            with Vertical(id="workspace-heading"):
                yield Static("INVESTIGATION WORKSPACE", classes="section-kicker")
                yield Label(self.investigation.name, id="workspace-title")
                yield Static(
                    f"ID {self.investigation.investigation_id[:8]}  ·  "
                    f"updated {self.investigation.updated_at.astimezone():%Y-%m-%d %H:%M}",
                    id="workspace-identifier",
                )
            with Horizontal(id="workspace-metrics"):
                yield Static(
                    "REFERENCE\n" + self.investigation.analysis_language.value.title(),
                    classes="workspace-metric",
                    id="workspace-language-metric",
                )
                yield Static(
                    "EVIDENCE\n" + self._count_label(),
                    classes="workspace-metric",
                    id="workspace-evidence-metric",
                )
                yield Static(
                    "GRAPH\nPending",
                    classes="workspace-metric",
                    id="workspace-graph-metric",
                )
        with TabbedContent(initial="workspace-evidence-tab", id="workspace-tabs"):
            with (
                TabPane("Overview / Settings", id="workspace-overview-tab"),
                VerticalScroll(id="workspace-overview"),
            ):
                with Horizontal(id="overview-case-actions"):
                    yield Static(
                        "Profile changes reprocess Evidence and invalidate the derived graph.",
                        id="overview-case-actions-hint",
                    )
                    yield Button("Edit configuration", id="edit-investigation")
                    yield Button(
                        "Delete investigation",
                        id="delete-investigation",
                        variant="error",
                    )
                with Horizontal(id="overview-grid"):
                    with Vertical(classes="overview-card", id="overview-brief-card"):
                        yield Static("CASE BRIEF", classes="panel-title")
                        yield Static(
                            self.investigation.description or "No context provided",
                            id="workspace-description",
                            markup=False,
                        )
                    with Vertical(classes="overview-card", id="overview-profile-card"):
                        yield Static("ANALYSIS PROFILE", classes="panel-title")
                        yield Static(
                            self._analysis_profile_label(),
                            id="workspace-profile",
                        )
                with Vertical(classes="overview-card", id="overview-questions-card"):
                    yield Static("INVESTIGATION QUESTIONS", classes="panel-title")
                    yield Static(
                        "\n".join(
                            f"{index:02}.  {question}"
                            for index, question in enumerate(self.investigation.questions, 1)
                        ),
                        id="workspace-questions",
                        markup=False,
                    )
            with TabPane("Evidence", id="workspace-evidence-tab"):
                with Horizontal(id="evidence-section-header"):
                    with Vertical(classes="section-heading"):
                        yield Static("EVIDENCE KNOWLEDGE BASE", classes="panel-title")
                        evidence_directory = self._raven_app.evidence_directory(
                            self.investigation.investigation_id
                        )
                        storage_path = Static(
                            "Stored in  " + self._display_path(evidence_directory),
                            id="evidence-storage-path",
                            classes="section-description",
                            markup=False,
                        )
                        storage_path.tooltip = str(evidence_directory)
                        yield storage_path
                    yield Static(self._count_label(), id="evidence-count")
                    yield Button("Index RAG", id="index-evidence-rag")
                    yield Button("Cancel RAG", id="cancel-rag-index", classes="hidden")
                    yield Button("Add file", id="add-evidence", variant="primary")
                    yield Button("Cancel", id="cancel-evidence-upload", classes="hidden")
                with Horizontal(id="evidence-operation-line"):
                    yield LoadingIndicator(id="rag-activity", classes="hidden")
                    yield Static("● Ready", id="evidence-operation-status", classes="ready")
                with Horizontal(id="evidence-header"):
                    yield Static("File", classes="evidence-name")
                    yield Static("Format", classes="evidence-format")
                    yield Static("Pages", classes="evidence-pages")
                    yield Static("RAG index", classes="evidence-state")
                    yield Static("Action", classes="evidence-action")
                with VerticalScroll(id="evidence-list"):
                    if not self.documents:
                        yield Static(
                            "No evidence documents. Use Add evidence to select a file from disk.",
                            id="evidence-empty",
                        )
                    for document in self.documents:
                        yield EvidenceRow(document)
            with TabPane("Graph", id="workspace-graph-tab"):
                with Horizontal(id="graph-toolbar"):
                    with Vertical(id="graph-mode-control"):
                        yield Static("EVIDENCE PREPARATION", classes="field-label")
                        yield Select(
                            [
                                ("Compress Evidence", EvidencePreparationMode.COMPRESS.value),
                                ("Full text", EvidencePreparationMode.FULL_TEXT.value),
                                (
                                    "Translate + overlapping chunks",
                                    EvidencePreparationMode.TRANSLATE_AND_CHUNK.value,
                                ),
                            ],
                            value=EvidencePreparationMode.COMPRESS.value,
                            allow_blank=False,
                            id="graph-preparation-mode",
                        )
                    with Horizontal(id="graph-actions"):
                        yield Button("Nuova variante", id="analyze-evidence", variant="primary")
                        yield Button("Varianti / confronta", id="graph-variants")
                        yield Button("Cancel", id="cancel-graph-analysis", classes="hidden")
                yield Static(
                    "● Ready · language: "
                    + self.investigation.analysis_language.prompt_label
                    + " · domain: "
                    + self.investigation.analysis_domain,
                    id="graph-analysis-status",
                    classes="ready",
                )
                with Horizontal(id="graph-build-panel", classes="hidden"):
                    yield GraphBuildActivity(id="graph-build-activity")
                    with Vertical(id="graph-build-copy"):
                        yield Static("FROM SOURCES TO CONNECTIONS", id="graph-build-title")
                        yield Static("Waiting for analysis", id="graph-build-stage", markup=False)
                        yield Static(
                            "Every connection leads back to its sources.", id="graph-build-hint"
                        )
                with ResizableSplit(id="graph-body"):
                    with Vertical(id="graph-visual-panel"):
                        with Vertical(id="graph-panel-header"):
                            with Horizontal(id="graph-panel-title-row"):
                                yield Static("PROPOSED GRAPH", classes="panel-title")
                                yield Static("0 entities · 0 relationships", id="graph-statistics")
                            with Horizontal(id="graph-view-controls"):
                                yield Static(
                                    "Arrows pan · J/K select · +/- zoom",
                                    id="graph-navigation-hint",
                                )
                                yield Button(
                                    "Affermazioni / copertura",
                                    id="open-graph-claims",
                                    tooltip="Apri affermazioni, fonti e copertura delle pagine",
                                )
                                yield Static("FIT", id="graph-zoom-label")
                                yield Button(
                                    "Fit",
                                    id="fit-graph",
                                    classes="graph-view-button",
                                    tooltip=(
                                        "Arrange groups at readable size. "
                                        "Use arrows to pan large graphs."
                                    ),
                                )
                                yield Button("−", id="zoom-out-graph", classes="graph-view-button")
                                yield Button("+", id="zoom-in-graph", classes="graph-view-button")
                        yield GraphCanvas(id="graph-canvas")
                    yield PaneDivider(id="graph-pane-divider")
                    with VerticalScroll(id="graph-details-panel"):
                        yield Static("ANALYSIS CONTEXT", classes="panel-title")
                        yield Input(
                            placeholder="Find entity · Enter",
                            id="graph-entity-search",
                        )
                        yield Static(
                            "SELECTED ITEM\nClick a node or edge, or focus the graph and use J/K.",
                            id="graph-selection-detail",
                            classes="graph-detail-block",
                            markup=False,
                        )
                        yield Static(
                            "Normalization language\n"
                            + self.investigation.analysis_language.prompt_label,
                            id="graph-language-detail",
                            classes="graph-detail-block",
                        )
                        yield Static(
                            "Analysis domain\n" + self.investigation.analysis_domain,
                            id="graph-domain-detail",
                            classes="graph-detail-block",
                        )
                        yield Static(
                            "Knowledge base\n" + self._count_label(),
                            id="graph-evidence-detail",
                            classes="graph-detail-block",
                        )
                        yield Static(
                            "Entity types\nNo graph generated",
                            id="graph-breakdown",
                            classes="graph-detail-block",
                        )
                        yield Static(
                            "PROVENANCE\nAI output is Evidence-grounded and PROPOSED. "
                            "A quote found in the original source does not verify the claim. "
                            "Older graphs may contain document references only.",
                            id="graph-provenance-hint",
                        )
            with TabPane("Chat", id="workspace-chat-tab"):
                with Horizontal(id="chat-toolbar"):
                    with Vertical(classes="section-heading", id="chat-heading"):
                        yield Static("INVESTIGATION COPILOT", classes="panel-title")
                        yield Static(
                            "RAG over this investigation's Evidence plus the latest graph",
                            classes="section-description",
                        )
                    yield Static("TOKENS\n0 total", id="chat-token-usage")
                    yield Button("Index RAG", id="index-chat-kb")
                    yield Button("Clear chat", id="clear-chat")
                yield Static(
                    "● Loading conversation...",
                    id="chat-operation-status",
                    classes="running",
                )
                with Horizontal(id="chat-body"):
                    with VerticalScroll(id="chat-conversation"):
                        yield Static(
                            "Ask about documents, entities, relationships, contradictions, or "
                            "request a Mermaid diagram. Commands: /NEW · /SAVE · /STATS · "
                            "/INFO.",
                            id="chat-empty",
                        )
                    with VerticalScroll(id="chat-context-panel"):
                        yield Static("ACTIVE CONTEXT", classes="panel-title")
                        yield Static(
                            self._chat_context_label(),
                            id="chat-context-summary",
                            markup=False,
                        )
                        yield Static(
                            "GROUNDING POLICY\nEvidence citations use [E1], [E2]... Graph items "
                            "remain hypotheses while marked PROPOSED.",
                            classes="chat-context-note",
                            markup=False,
                        )
                with Vertical(id="chat-composer"):
                    yield TextArea(
                        id="chat-input",
                        classes="chat-input",
                        language=None,
                    )
                    with Horizontal(id="chat-composer-actions"):
                        yield Static(
                            "/NEW · /SAVE · /STATS · /INFO  ·  Ctrl+Enter send",
                            id="chat-composer-hint",
                        )
                        yield Button("Cancel", id="cancel-chat", classes="hidden")
                        yield Button("Send", id="send-chat", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self._set_responsive_layout(self.size.width, self.size.height)
        self._load_latest_graph()
        self._load_chat_history()
        self._load_rag_states(self._rag_state_revision, tuple(self.documents))
        self._sync_graph_analysis_job()
        self.set_interval(0.15, self._sync_graph_analysis_job)

    def on_resizable_split_resized(self, event: ResizableSplit.Resized) -> None:
        compact = event.main_width < 85
        self.query_one("#graph-visual-panel").set_class(compact, "compact-graph-pane")
        self.query_one("#open-graph-claims", Button).label = (
            "Affermazioni" if compact else "Affermazioni / copertura"
        )

    def on_resize(self, event: Resize) -> None:
        self._set_responsive_layout(event.size.width, event.size.height)

    def _set_responsive_layout(self, width: int, height: int) -> None:
        self.set_class(height <= 26, "compact-workspace")
        self.set_class(width < 100, "narrow-workspace")
        compact_activity = width < 100 or height < 40
        self.set_class(compact_activity, "compact-graph-activity")
        for activity in self.query(GraphBuildActivity):
            activity.set_class(compact_activity, "compact")
        if self.graph is not None:
            for statistics in self.query("#graph-statistics"):
                statistics.update(self._graph_statistics_label(self.graph, width))

    def action_add_evidence(self) -> None:
        self._open_file_picker()

    def action_show_overview(self) -> None:
        self._show_tab("workspace-overview-tab")

    def action_show_evidence(self) -> None:
        self._show_tab("workspace-evidence-tab")

    def action_show_graph(self) -> None:
        self._show_tab("workspace-graph-tab")

    def action_show_chat(self) -> None:
        self._show_tab("workspace-chat-tab")

    async def action_send_chat(self) -> None:
        if self.query_one("#workspace-tabs", TabbedContent).active == "workspace-chat-tab":
            await self._start_chat()

    def action_analyze_graph(self) -> None:
        self._show_tab("workspace-graph-tab")
        self._start_graph_analysis()

    def action_index_rag(self) -> None:
        self._show_tab("workspace-evidence-tab")
        self._start_chat_index()

    def action_focus_graph_search(self) -> None:
        self._show_tab("workspace-graph-tab")
        self.query_one("#graph-entity-search", Input).focus()

    def _show_tab(self, tab_id: str) -> None:
        self.query_one("#workspace-tabs", TabbedContent).active = tab_id

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-evidence":
            self._open_file_picker()
        elif event.button.id == "index-evidence-rag":
            self._start_chat_index()
        elif event.button.id == "cancel-rag-index":
            self._cancel_rag_index()
        elif event.button.id == "cancel-evidence-upload":
            self._upload_cancel.set()
            self._set_operation_status("● Cancelling upload...", "running")
        elif event.button.id == "graph-variants":
            self._open_variants()
        elif event.button.id == "analyze-evidence":
            self._start_graph_analysis()
        elif event.button.id == "cancel-graph-analysis":
            self._raven_app.cancel_graph_analysis(self.investigation.investigation_id)
            self._sync_graph_analysis_job()
        elif event.button.id == "open-graph-claims":
            self.app.push_screen(
                GraphClaimsScreen(self.investigation, self.graph, tuple(self.documents))
            )
        elif event.button.id == "fit-graph":
            self.query_one("#graph-canvas", GraphCanvas).fit()
        elif event.button.id == "zoom-out-graph":
            self.query_one("#graph-canvas", GraphCanvas).zoom_out()
        elif event.button.id == "zoom-in-graph":
            self.query_one("#graph-canvas", GraphCanvas).zoom_in()
        elif event.button.id == "send-chat":
            await self._start_chat()
        elif event.button.id == "cancel-chat":
            if self._rag_indexing:
                self._cancel_rag_index()
            else:
                self._chat_cancel.set()
                self._set_chat_status("● Cancelling after the active provider event...", "running")
        elif event.button.id == "index-chat-kb":
            self._start_chat_index()
        elif event.button.id == "clear-chat" and not self._chat_busy:
            self.app.push_screen(
                ConfirmClearChat(self.investigation),
                self._clear_chat_confirmed,
            )
        elif event.button.id == "edit-investigation" and not self._deleting:
            self._raven_app.edit_investigation(self.investigation)
        elif event.button.id == "delete-investigation" and not self._deleting:
            self.app.push_screen(
                ConfirmInvestigationDelete(self.investigation),
                self._delete_investigation_confirmed,
            )

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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "graph-entity-search":
            return
        selected = self.query_one("#graph-canvas", GraphCanvas).select_matching(event.value)
        if selected is None:
            self.notify(
                f'No graph entity matches "{event.value.strip()}".',
                title="Entity not found",
                severity="warning",
            )

    def on_graph_canvas_view_changed(self, event: GraphCanvas.ViewChanged) -> None:
        self.query_one("#graph-zoom-label", Static).update(event.label)

    def on_graph_canvas_selection_changed(self, event: GraphCanvas.SelectionChanged) -> None:
        selection = event.selection
        if isinstance(selection, GraphEntity):
            self.query_one("#graph-selection-detail", Static).update(self._entity_detail(selection))
        elif isinstance(selection, tuple) and selection:
            self.query_one("#graph-selection-detail", Static).update(
                self._relationship_detail(selection)
            )
        else:
            self.query_one("#graph-selection-detail", Static).update(
                "SELECTED ITEM\nClick a node or edge, or focus the graph and use J/K."
            )
        self.query_one("#graph-details-panel", VerticalScroll).scroll_home(animate=False)

    def on_evidence_row_catalog_requested(self, event: EvidenceRow.CatalogRequested) -> None:
        self.app.push_screen(DocumentCatalogScreen(self.investigation, event.document))

    def on_evidence_row_reindex_requested(self, event: EvidenceRow.ReindexRequested) -> None:
        self._start_chat_index(document=event.document)

    def on_evidence_row_delete_requested(self, event: EvidenceRow.DeleteRequested) -> None:
        if self._busy or self._rag_indexing:
            return
        self.app.push_screen(
            ConfirmEvidenceDelete(event.document),
            lambda confirmed: self._delete_confirmed(event.document, confirmed),
        )

    def _open_file_picker(self) -> None:
        if not self._busy and not self._rag_indexing:
            self.app.push_screen(
                EvidenceFilePicker(self._last_evidence_source_directory),
                self._file_selected,
            )

    def _file_selected(self, path: Path | None) -> None:
        if path is None or self._busy:
            return
        self._last_evidence_source_directory = path.parent
        self._busy = True
        self._upload_cancel.clear()
        self.query_one("#add-evidence", Button).disabled = True
        self.query_one("#cancel-evidence-upload", Button).remove_class("hidden")
        self._set_operation_status("● Reading document...", "running")
        self._upload_evidence(path)

    @work(thread=True, exclusive=True, group="evidence-upload", exit_on_error=False)
    def _upload_evidence(self, path: Path) -> None:
        try:
            document = self._raven_app.add_evidence(
                self.investigation.investigation_id,
                path,
                self._upload_cancel.is_set,
            )
        except InvestigationCancelledError:
            self.app.call_from_thread(self._upload_cancelled)
        except InvestigationError as error:
            self.app.call_from_thread(self._operation_failed, str(error))
        except Exception as error:
            logger.error("Unexpected evidence upload failure. error_type=%s", type(error).__name__)
            self.app.call_from_thread(self._operation_failed, "Unable to add evidence; check log")
        else:
            self.app.call_from_thread(self._upload_succeeded, document)

    def _upload_succeeded(self, document: EvidenceDocument) -> None:
        if not self.is_mounted:
            return
        self.documents.append(document)
        for empty in self.query("#evidence-empty"):
            empty.remove()
        self.query_one("#evidence-list", VerticalScroll).mount(EvidenceRow(document))
        self._finish_operation("● Evidence added", "success")

    def _upload_cancelled(self) -> None:
        if self.is_mounted:
            self._finish_operation("● Upload cancelled", "cancelled")

    def _delete_confirmed(self, document: EvidenceDocument, confirmed: bool | None) -> None:
        if not confirmed or self._busy:
            return
        self._busy = True
        self.query_one("#add-evidence", Button).disabled = True
        row = self.query_one(f"#evidence-{document.document_id}", EvidenceRow)
        row.query_one(".delete-evidence", Button).disabled = True
        self._set_operation_status("● Deleting evidence...", "running")
        self._delete_evidence(document)

    @work(thread=True, exclusive=True, group="evidence-delete", exit_on_error=False)
    def _delete_evidence(self, document: EvidenceDocument) -> None:
        try:
            self._raven_app.delete_evidence(document)
        except InvestigationError as error:
            self.app.call_from_thread(self._delete_failed, document, str(error))
        except Exception as error:
            logger.error(
                "Unexpected evidence deletion failure. error_type=%s", type(error).__name__
            )
            self.app.call_from_thread(
                self._delete_failed,
                document,
                "Unable to delete evidence; check log",
            )
        else:
            self.app.call_from_thread(self._delete_succeeded, document)

    def _delete_succeeded(self, document: EvidenceDocument) -> None:
        if not self.is_mounted:
            return
        self.documents = [
            item for item in self.documents if item.document_id != document.document_id
        ]
        self.query_one(f"#evidence-{document.document_id}", EvidenceRow).remove()
        if not self.documents:
            self.query_one("#evidence-list", VerticalScroll).mount(
                Static(
                    "No evidence documents. Use Add evidence to select a file from disk.",
                    id="evidence-empty",
                )
            )
        self._finish_operation("● Evidence deleted", "success")

    def _delete_failed(self, document: EvidenceDocument, detail: str) -> None:
        if not self.is_mounted:
            return
        self.query_one(f"#evidence-{document.document_id}", EvidenceRow).query_one(
            ".delete-evidence", Button
        ).disabled = False
        self._operation_failed(detail)

    def _operation_failed(self, detail: str) -> None:
        if not self.is_mounted:
            return
        self._finish_operation("● Operation failed", "error")
        self.query_one("#evidence-operation-status", Static).tooltip = detail
        self.notify(detail, title="Evidence operation failed", severity="error")

    def _finish_operation(self, label: str, state: str) -> None:
        self._busy = False
        self.query_one("#add-evidence", Button).disabled = False
        self.query_one("#cancel-evidence-upload", Button).add_class("hidden")
        self._set_operation_status(label, state)
        self.query_one("#evidence-count", Static).update(self._count_label())
        self.query_one("#workspace-evidence-metric", Static).update(
            "EVIDENCE\n" + self._count_label()
        )
        self.query_one("#workspace-profile", Static).update(self._analysis_profile_label())
        self.query_one("#graph-evidence-detail", Static).update(
            "Knowledge base\n" + self._count_label()
        )
        self.query_one("#chat-context-summary", Static).update(self._chat_context_label())

    def _set_operation_status(self, label: str, state: str) -> None:
        status = self.query_one("#evidence-operation-status", Static)
        status.set_classes(state)
        status.update(label)
        status.tooltip = None

    def _count_label(self) -> str:
        count = len(self.documents)
        return f"{count} document{'s' if count != 1 else ''}"

    def _analysis_profile_label(self) -> str:
        return (
            "Normalization language\n"
            + self.investigation.analysis_language.prompt_label
            + "\n\nAnalysis domain\n"
            + self.investigation.analysis_domain
            + "\n\nKnowledge base\n"
            + self._count_label()
        )

    @staticmethod
    def _display_path(path: Path) -> str:
        try:
            return str(Path("~") / path.relative_to(Path.home()))
        except ValueError:
            return str(path)

    def _chat_context_label(self) -> str:
        graph_label = (
            f"{len(self.graph.entities)} entities · {len(self.graph.relationships)} relationships"
            if self.graph is not None
            else "No graph snapshot"
        )
        ai_settings = self._raven_app.settings.with_environment().ai
        embedding_model = ai_settings.embedding_model or "Not configured"
        return (
            f"Evidence KB\n{self._count_label()}\n\n"
            f"Graph\n{graph_label}\n\n"
            "Normalization language\n"
            f"{self.investigation.analysis_language.prompt_label}\n\n"
            "Embedding node\n"
            f"{ai_settings.embedding_provider.value} · {embedding_model}\n\n"
            f"Inference context\n{ai_settings.context_size:,} tokens"
        )

    @work(thread=True, exclusive=True, group="rag-state", exit_on_error=False)
    def _load_rag_states(self, revision: int, documents: tuple[EvidenceDocument, ...]) -> None:
        try:
            states = self._raven_app.evidence_index_states(self.investigation, documents)
        except Exception as error:
            logger.warning(
                "Unable to verify RAG index. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
            states = {
                document.document_id: EvidenceIngestionState.UNVERIFIED for document in documents
            }
        self.app.call_from_thread(self._show_rag_states, revision, states)

    def _show_rag_states(self, revision: int, states: dict[str, EvidenceIngestionState]) -> None:
        # A delayed manifest read must never overwrite a newer indexing operation.
        if not self.is_mounted or revision != self._rag_state_revision:
            return
        self.documents = [
            replace(
                document, ingestion_state=states.get(document.document_id, document.ingestion_state)
            )
            for document in self.documents
        ]
        for row in self.query(EvidenceRow):
            if row.document.document_id in states:
                row.set_ingestion_state(states[row.document.document_id])

    @work(thread=True, exclusive=True, group="chat-history", exit_on_error=False)
    def _load_chat_history(self) -> None:
        try:
            messages = self._raven_app.load_investigation_chat(self.investigation.investigation_id)
        except Exception as error:
            logger.warning(
                "Unable to load chat history. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
            self.app.call_from_thread(
                self._set_chat_status, "● Chat history unavailable", "warning"
            )
        else:
            self.app.call_from_thread(self._show_chat_history, messages)

    def _show_chat_history(self, messages: tuple[ChatMessage, ...]) -> None:
        if not self.is_mounted:
            return
        conversation = self.query_one("#chat-conversation", VerticalScroll)
        if messages:
            self.query_one("#chat-empty", Static).remove()
            conversation.mount(*(ChatMessageView(message) for message in messages))
            conversation.scroll_end(animate=False)
        last_assistant = next(
            (message for message in reversed(messages) if message.role is ChatRole.ASSISTANT),
            None,
        )
        self._last_assistant_markdown = (
            last_assistant.content if last_assistant is not None else None
        )
        self._last_assistant_sources = last_assistant.sources if last_assistant is not None else ()
        self._chat_saved_messages = len(messages)
        self._replace_chat_usage(messages)
        self._set_chat_status(
            f"● Ready · {len(messages)} saved turn{'s' if len(messages) != 1 else ''}",
            "ready",
        )

    def _start_chat_index(
        self, *, silent: bool = False, document: EvidenceDocument | None = None
    ) -> None:
        if self._chat_busy or self._busy:
            return
        if not self._raven_app.settings.with_environment().ai.embedding_model:
            self._set_rag_status("● Configure an AI embedding model to index the KB", "warning")
            if not silent:
                self.notify(
                    "Set the embedding model in Configuration > AI Node.",
                    title="RAG configuration required",
                    severity="warning",
                )
            return
        if not self.documents:
            self._set_rag_status("● Add Evidence before indexing", "warning")
            if not silent:
                self.notify(
                    "Add at least one Evidence document before indexing the chat KB.",
                    title="No Evidence",
                    severity="warning",
                )
            return
        self._chat_busy = True
        self._rag_indexing = True
        self._rag_state_revision += 1
        self._rag_target = document.document_id if document else None
        self._chat_cancel.clear()
        self._set_chat_controls_disabled(True)
        self._set_rag_controls_disabled(True)
        self._set_rag_status("● Preparing investigation RAG index...", "running")
        self._index_chat_kb(silent, document)

    def _cancel_rag_index(self) -> None:
        if not self._rag_indexing:
            return
        self._chat_cancel.set()
        self._set_rag_status("● Cancelling after the active indexing step...", "running")

    @work(thread=True, exclusive=True, group="chat-operation", exit_on_error=False)
    def _index_chat_kb(self, silent: bool, document: EvidenceDocument | None = None) -> None:
        try:
            if document is None:
                count = self._raven_app.index_investigation_knowledge_base(
                    self.investigation,
                    tuple(self.documents),
                    self._chat_cancel.is_set,
                    self._chat_index_progress,
                )
            else:
                count = self._raven_app.reindex_evidence_document(
                    self.investigation,
                    document,
                    self._chat_cancel.is_set,
                    self._chat_index_progress,
                )
        except InvestigationChatCancelledError:
            self.app.call_from_thread(self._chat_cancelled)
        except (InvestigationChatError, InvestigationError) as error:
            self.app.call_from_thread(self._chat_failed, str(error), silent)
        except Exception as error:
            logger.error(
                "Unexpected chat indexing failure. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
            self.app.call_from_thread(
                self._chat_failed, "Unable to index the investigation KB", silent
            )
        else:
            self.app.call_from_thread(self._chat_indexed, count)

    def _chat_index_progress(self, progress: RagIndexProgress) -> None:
        self.app.call_from_thread(self._show_rag_index_progress, progress)

    def _show_rag_index_progress(self, progress: RagIndexProgress) -> None:
        self._rag_state_revision += 1
        if not self.is_mounted:
            return
        self.documents = [
            replace(document, ingestion_state=progress.state)
            if document.document_id == progress.document_id
            else document
            for document in self.documents
        ]
        row = self.query_one(f"#evidence-{progress.document_id}", EvidenceRow)
        row.set_ingestion_state(progress.state)
        action = {
            EvidenceIngestionState.PROCESSING: "Indexing",
            EvidenceIngestionState.READY: "Indexed",
            EvidenceIngestionState.FAILED: "Failed",
            EvidenceIngestionState.PENDING: "Pending",
        }[progress.state]
        state = "error" if progress.state is EvidenceIngestionState.FAILED else "running"
        self._set_rag_status(
            f"● {action} {progress.document_name} ({progress.completed}/{progress.total})",
            state,
        )

    def _chat_indexed(self, count: int) -> None:
        if not self.is_mounted:
            return
        self.documents = [
            replace(document, ingestion_state=EvidenceIngestionState.READY)
            if self._rag_target is None or document.document_id == self._rag_target
            else document
            for document in self.documents
        ]
        for row in self.query(EvidenceRow):
            if self._rag_target is None or row.document.document_id == self._rag_target:
                row.set_ingestion_state(EvidenceIngestionState.READY)
        self._finish_chat_operation(f"● KB indexed · {count} document(s)", "success")
        self._finish_rag_operation(
            f"● RAG index ready · {count} document(s)",
            "success",
        )

    async def _start_chat(self) -> None:
        if self._chat_busy:
            return
        question = self.query_one("#chat-input", TextArea).text.strip()
        if not question:
            self._set_chat_status("● Write a question before sending", "warning")
            self.query_one("#chat-input", TextArea).focus()
            return
        try:
            command = parse_chat_command(question)
        except ChatCommandError as error:
            self._set_chat_status(f"● {error}", "warning")
            self.query_one("#chat-input", TextArea).focus()
            return
        if command is not None:
            self.query_one("#chat-input", TextArea).clear()
            await self._execute_chat_command(command)
            return
        conversation = self.query_one("#chat-conversation", VerticalScroll)
        for empty in self.query("#chat-empty"):
            empty.remove()
        user_message = ChatMessage(
            message_id=str(uuid4()),
            investigation_id=self.investigation.investigation_id,
            role=ChatRole.USER,
            content=question,
            created_at=datetime.now(UTC),
        )
        response = StreamingAssistantView()
        await conversation.mount(ChatMessageView(user_message), response)
        conversation.scroll_end(animate=False)
        self._active_response = response
        self._rag_state_revision += 1
        self._chat_sources = ()
        self._chat_busy = True
        self._chat_cancel.clear()
        self._set_chat_controls_disabled(True)
        self.query_one("#chat-input", TextArea).clear()
        self._set_chat_status("● Preparing grounded context...", "running")
        self._stream_chat(question)

    @work(thread=True, exclusive=True, group="chat-operation", exit_on_error=False)
    def _stream_chat(self, question: str) -> None:
        try:
            for event in self._raven_app.stream_investigation_chat(
                self.investigation,
                tuple(self.documents),
                self.graph,
                question,
                self._chat_cancel.is_set,
                self._chat_index_progress,
            ):
                if event.kind is ChatEventKind.STATUS:
                    self.app.call_from_thread(self._set_chat_status, f"● {event.text}", "running")
                elif event.kind is ChatEventKind.SOURCES:
                    self._chat_sources = event.sources
                elif event.kind is ChatEventKind.TOKEN:
                    self.app.call_from_thread(self._append_chat_fragment, event.text)
                elif event.kind is ChatEventKind.COMPLETE:
                    self.app.call_from_thread(
                        self._chat_completed,
                        event.sources or self._chat_sources,
                        event.usage,
                    )
        except InvestigationChatCancelledError:
            self.app.call_from_thread(self._chat_cancelled)
        except (InvestigationChatError, InvestigationError) as error:
            self.app.call_from_thread(self._chat_failed, str(error), False)
        except Exception as error:
            logger.error(
                "Unexpected streamed chat failure. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
            self.app.call_from_thread(
                self._chat_failed, "Unable to complete the investigation chat", False
            )

    async def _append_chat_fragment(self, fragment: str) -> None:
        if self._active_response is None or not self._active_response.is_mounted:
            return
        await self._active_response.append_fragment(fragment)
        self.query_one("#chat-conversation", VerticalScroll).scroll_end(animate=False)

    async def _chat_completed(
        self,
        sources: tuple[str, ...],
        usage: TokenUsage | None,
    ) -> None:
        if self._active_response is not None and self._active_response.is_mounted:
            self._last_assistant_markdown = self._active_response.markdown_source
            self._last_assistant_sources = sources
            await self._active_response.complete(sources, usage, show_usage=True)
        self._active_response = None
        self._chat_saved_messages += 2
        if usage is not None:
            self._add_chat_usage(usage)
            label = f"● Grounded answer complete · {usage.total_tokens:,} tokens"
        else:
            label = "● Grounded answer complete · token usage unavailable"
        self._finish_chat_operation(label, "success")
        self.call_after_refresh(self._scroll_chat_to_end)

    def _scroll_chat_to_end(self) -> None:
        self.query_one("#chat-conversation", VerticalScroll).scroll_end(animate=False)

    async def _chat_cancelled(self) -> None:
        if not self.is_mounted:
            return
        rag_indexing = self._rag_indexing
        if self._active_response is not None and self._active_response.is_mounted:
            await self._active_response.complete(self._chat_sources)
        self._active_response = None
        self._finish_chat_operation("● Chat operation cancelled", "cancelled")
        if rag_indexing:
            self._finish_rag_operation("● RAG indexing cancelled", "cancelled")

    async def _chat_failed(self, detail: str, silent: bool) -> None:
        if not self.is_mounted:
            return
        rag_indexing = self._rag_indexing
        if self._active_response is not None and self._active_response.is_mounted:
            await self._active_response.complete(self._chat_sources)
            self._active_response.add_class("error")
        self._active_response = None
        self._finish_chat_operation("● Chat operation failed", "error")
        if rag_indexing:
            self._finish_rag_operation("● RAG indexing failed", "error")
        status = self.query_one("#chat-operation-status", Static)
        status.tooltip = detail
        if rag_indexing:
            self.query_one("#evidence-operation-status", Static).tooltip = detail
        if not silent:
            self.notify(detail, title="Investigation chat failed", severity="error")

    def _finish_chat_operation(self, label: str, state: str) -> None:
        self._chat_busy = False
        self._set_chat_controls_disabled(False)
        self._set_chat_status(label, state)

    def _finish_rag_operation(self, label: str, state: str) -> None:
        self._rag_indexing = False
        self._rag_target = None
        self._set_rag_controls_disabled(False)
        self._set_operation_status(label, state)

    def _set_rag_controls_disabled(self, disabled: bool) -> None:
        self.query_one("#rag-activity", LoadingIndicator).set_class(not disabled, "hidden")
        self.query_one("#index-evidence-rag", Button).disabled = disabled
        self.query_one("#add-evidence", Button).disabled = disabled
        self.query_one("#cancel-rag-index", Button).set_class(not disabled, "hidden")
        for row in self.query(EvidenceRow):
            row.query_one(".delete-evidence", Button).disabled = disabled
            row.query_one(".reindex-evidence", Button).disabled = disabled

    def _set_rag_status(self, label: str, state: str) -> None:
        self._set_operation_status(label, state)
        self._set_chat_status(label, state)

    def _set_chat_controls_disabled(self, disabled: bool) -> None:
        self.query_one("#send-chat", Button).disabled = disabled
        self.query_one("#index-chat-kb", Button).disabled = disabled
        self.query_one("#clear-chat", Button).disabled = disabled
        self.query_one("#chat-input", TextArea).disabled = disabled
        self.query_one("#cancel-chat", Button).set_class(not disabled, "hidden")

    def _set_chat_status(self, label: str, state: str) -> None:
        if not self.is_mounted:
            return
        status = self.query_one("#chat-operation-status", Static)
        status.set_classes(state)
        status.update(label)
        status.tooltip = None

    def _clear_chat_confirmed(self, confirmed: bool | None) -> None:
        if confirmed:
            self._clear_chat_history()

    @work(thread=True, exclusive=True, group="chat-operation", exit_on_error=False)
    def _clear_chat_history(self) -> None:
        self._chat_busy = True
        self.app.call_from_thread(self._set_chat_controls_disabled, True)
        try:
            self._raven_app.clear_investigation_chat(self.investigation.investigation_id)
        except Exception as error:
            self.app.call_from_thread(self._chat_failed, str(error), False)
        else:
            self.app.call_from_thread(self._chat_history_cleared)

    async def _chat_history_cleared(self) -> None:
        conversation = self.query_one("#chat-conversation", VerticalScroll)
        await conversation.remove_children()
        await conversation.mount(
            Static(
                "Ask about documents, entities, relationships, contradictions, or request a "
                "Mermaid diagram. Commands: /NEW · /SAVE · /STATS · /INFO.",
                id="chat-empty",
            )
        )
        self._chat_saved_messages = 0
        self._last_assistant_markdown = None
        self._last_assistant_sources = ()
        self._replace_chat_usage(())
        self._finish_chat_operation("● Chat history cleared", "success")

    async def _execute_chat_command(self, command: ChatCommand) -> None:
        if command is ChatCommand.NEW:
            self.app.push_screen(
                ConfirmClearChat(self.investigation),
                self._clear_chat_confirmed,
            )
            return
        if command is ChatCommand.SAVE:
            self._open_chat_export()
            return
        if command is ChatCommand.STATS:
            await self._mount_local_command(self._chat_statistics_markdown(), "Statistics ready")
            return
        await self._mount_local_command(self._chat_info_markdown(), "Context information ready")

    async def _mount_local_command(self, markdown: str, status: str) -> None:
        conversation = self.query_one("#chat-conversation", VerticalScroll)
        for empty in self.query("#chat-empty"):
            empty.remove()
        await conversation.mount(LocalCommandView(markdown))
        conversation.scroll_end(animate=False)
        self._set_chat_status(f"● {status} · local command · 0 tokens", "success")

    def _open_chat_export(self) -> None:
        if not self._last_assistant_markdown:
            self._set_chat_status("● No model response is available to save", "warning")
            return
        self.app.push_screen(
            MarkdownExportPicker(
                self._last_export_directory,
                self._raven_app.suggested_chat_export_filename(self.investigation),
            ),
            self._chat_export_selected,
        )

    def _chat_export_selected(self, destination: Path | None) -> None:
        if destination is None or not self._last_assistant_markdown or self._chat_busy:
            return
        self._chat_busy = True
        self._set_chat_controls_disabled(True)
        self._set_chat_status("● Saving latest response as Markdown...", "running")
        self._save_chat_export(
            destination,
            self._last_assistant_markdown,
            self._last_assistant_sources,
        )

    @work(thread=True, exclusive=True, group="chat-export", exit_on_error=False)
    def _save_chat_export(
        self,
        destination: Path,
        response: str,
        sources: tuple[str, ...],
    ) -> None:
        try:
            saved = self._raven_app.export_investigation_chat_response(
                self.investigation,
                response,
                sources,
                destination,
            )
        except InvestigationChatError as error:
            self.app.call_from_thread(self._chat_export_failed, str(error))
        except Exception as error:
            logger.error(
                "Unexpected chat export failure. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
            self.app.call_from_thread(
                self._chat_export_failed,
                "Unable to save the Markdown response",
            )
        else:
            self.app.call_from_thread(self._chat_export_succeeded, saved)

    def _chat_export_succeeded(self, destination: Path) -> None:
        self._last_export_directory = destination.parent
        self._finish_chat_operation(f"● Response saved · {destination.name}", "success")
        self.notify(str(destination), title="Markdown response saved")

    def _chat_export_failed(self, detail: str) -> None:
        self._finish_chat_operation("● Markdown export failed", "error")
        self.notify(detail, title="Response not saved", severity="error")

    def _chat_statistics_markdown(self) -> str:
        indexed = sum(
            document.ingestion_state is EvidenceIngestionState.READY for document in self.documents
        )
        entities = len(self.graph.entities) if self.graph is not None else 0
        relationships = len(self.graph.relationships) if self.graph is not None else 0
        return (
            "## Chat statistics\n\n"
            f"- Saved messages: **{self._chat_saved_messages:,}**\n"
            f"- Input tokens: **{self._chat_input_tokens:,}**\n"
            f"- Output tokens: **{self._chat_output_tokens:,}**\n"
            f"- Total tokens: **{self._chat_total_tokens:,}**\n"
            f"- Evidence documents: **{len(self.documents):,}**\n"
            f"- RAG-ready documents: **{indexed:,}/{len(self.documents):,}**\n"
            f"- Graph: **{entities:,} entities · {relationships:,} relationships**"
        )

    def _chat_info_markdown(self) -> str:
        settings = self._raven_app.settings.with_environment().ai
        graph_label = (
            f"{len(self.graph.entities):,} entities · "
            f"{len(self.graph.relationships):,} relationships"
            if self.graph is not None
            else "No graph snapshot"
        )
        documents = (
            "\n".join(
                f"- `{self._safe_code(document.original_name)}` · {document.file_format} · "
                f"{document.page_label} pages · {document.ingestion_state.value}"
                for document in self.documents
            )
            if self.documents
            else "- No Evidence documents"
        )
        last_sources = (
            "\n".join(f"- `{self._safe_code(source)}`" for source in self._last_assistant_sources)
            if self._last_assistant_sources
            else "- No sources reported for the latest model response"
        )
        return (
            "## Active investigation context\n\n"
            f"- Investigation: **{self.investigation.name}**\n"
            f"- Reference language: **{self.investigation.analysis_language.prompt_label}**\n"
            f"- Analysis domain: **{self.investigation.analysis_domain}**\n"
            f"- Graph: **{graph_label}**\n"
            f"- Inference: **{settings.provider.value} · {settings.model or 'not configured'}**\n"
            f"- Context budget: **{settings.context_size:,} tokens**\n"
            f"- Embedding: **{settings.embedding_provider.value} · "
            f"{settings.embedding_model or 'not configured'}**\n\n"
            "### Evidence sources\n\n"
            f"{documents}\n\n"
            "### Latest answer citations\n\n"
            f"{last_sources}"
        )

    @staticmethod
    def _safe_code(value: str) -> str:
        return " ".join(value.replace("`", "'").split())

    def _replace_chat_usage(self, messages: tuple[ChatMessage, ...]) -> None:
        usage = tuple(message.usage for message in messages if message.usage is not None)
        self._chat_input_tokens = sum(item.input_tokens for item in usage)
        self._chat_output_tokens = sum(item.output_tokens for item in usage)
        self._chat_total_tokens = sum(item.total_tokens for item in usage)
        self._refresh_chat_usage()

    def _add_chat_usage(self, usage: TokenUsage) -> None:
        self._chat_input_tokens += usage.input_tokens
        self._chat_output_tokens += usage.output_tokens
        self._chat_total_tokens += usage.total_tokens
        self._refresh_chat_usage()

    def _refresh_chat_usage(self) -> None:
        if not self.is_mounted:
            return
        summary = self.query_one("#chat-token-usage", Static)
        summary.update(f"TOKENS\n{self._chat_total_tokens:,} total")
        summary.tooltip = (
            f"Input: {self._chat_input_tokens:,} · "
            f"Output: {self._chat_output_tokens:,} · "
            f"Total: {self._chat_total_tokens:,}"
        )

    @work(thread=True, exclusive=True, group="graph-load", exit_on_error=False)
    def _load_latest_graph(self) -> None:
        try:
            graph = self._raven_app.latest_graph(self.investigation.investigation_id)
        except Exception as error:
            logger.warning(
                "Unable to load latest graph. investigation_id=%s error_type=%s",
                self.investigation.investigation_id,
                type(error).__name__,
            )
        else:
            if graph is not None:
                self.app.call_from_thread(self._show_graph, graph)

    def _open_variants(self):
        from raven.tui.screens.graph_variants import GraphVariantsScreen

        service = self._raven_app.graph_analysis
        if service is None:
            self.notify("Servizio grafo non disponibile", severity="error")
            return
        self.app.push_screen(
            GraphVariantsScreen(
                self.investigation,
                service,
                busy=self._graph_busy,
                model=self._raven_app.settings.with_environment().ai.model,
            ),
            self._variant_selected,
        )

    def _variant_selected(self, result):
        if result is None:
            return
        if result[0] == "generate":
            self._start_graph_analysis(method_id=result[1], variant_name=result[2])
        else:
            self._show_graph(result[1])
            self.notify(
                "Variante attiva selezionata"
                if result[0] == "active"
                else "Variante aperta per consultazione; chat usa quella attiva"
            )

    def _start_graph_analysis(self, *, method_id=None, variant_name="") -> None:
        if self._graph_busy:
            return
        if not self.documents:
            self.notify(
                "Add at least one Evidence document before graph analysis.",
                title="No Evidence",
                severity="warning",
            )
            return
        if method_id is None:
            self._open_variants()
            return
        mode = EvidencePreparationMode(self.query_one("#graph-preparation-mode", Select).value)
        try:
            job = self._raven_app.enqueue_graph_analysis(
                self.investigation,
                tuple(self.documents),
                mode,
                method_id=method_id,
                variant_name=variant_name,
            )
        except (GraphAnalysisError, InvestigationError) as error:
            self._graph_failed(str(error))
        else:
            self._apply_graph_analysis_job(job)

    def _sync_graph_analysis_job(self) -> None:
        if not self.is_mounted:
            return
        job = self._raven_app.graph_analysis_job(self.investigation.investigation_id)
        if job is not None:
            self._apply_graph_analysis_job(job)

    def _apply_graph_analysis_job(self, job: GraphAnalysisJob) -> None:
        if not self.is_mounted:
            return
        active = job.status in {GraphJobStatus.QUEUED, GraphJobStatus.RUNNING}
        self._graph_busy = active
        mode = self.query_one("#graph-preparation-mode", Select)
        mode.value = job.preparation_mode.value
        mode.disabled = active
        self.query_one("#analyze-evidence", Button).disabled = active
        cancel = self.query_one("#cancel-graph-analysis", Button)
        cancel.set_class(not active, "hidden")
        panel = self.query_one("#graph-build-panel")
        activity = self.query_one("#graph-build-activity", GraphBuildActivity)
        panel.set_class(not active, "hidden")
        if active:
            activity.start(job.submitted_at)
            stage = {
                GraphRunStatus.QUEUED: "Waiting for the analysis slot",
                GraphRunStatus.EXTRACTING: "Reading pages · extracting entities and claims",
                GraphRunStatus.CONSOLIDATING: "Connecting entities · comparing sources",
            }.get(job.progress.stage, "Preparing the investigation graph")
            self.query_one("#graph-build-stage", Static).update(stage)
            queue_label = "Queued" if job.status is GraphJobStatus.QUEUED else "Running"
            progress = job.progress
            self._set_graph_status(
                f"● {queue_label} · {progress.message} ({progress.completed}/{progress.total})",
                "running",
            )
            return
        activity.stop()
        if self._applied_graph_job_id == job.job_id:
            return
        self._applied_graph_job_id = job.job_id
        if job.status is GraphJobStatus.COMPLETED and job.result is not None:
            self._graph_succeeded(job.result)
        elif job.status is GraphJobStatus.CANCELLED:
            self._graph_cancelled()
        elif job.status is GraphJobStatus.FAILED:
            self._graph_failed(job.error or "Graph analysis failed")

    def _graph_succeeded(self, result: GraphAnalysisResult) -> None:
        if not self.is_mounted:
            return
        self._show_graph(result.graph)
        state = "warning" if result.run.evidence_failed or result.run.last_error else "success"
        label = (
            f"● {result.run.status.value.replace('_', ' ').title()} · "
            f"model: {result.run.model_name}"
        )
        self._finish_graph_operation(label, state)

    def _graph_cancelled(self) -> None:
        if self.is_mounted:
            self._finish_graph_operation("● Analysis cancelled", "cancelled")

    def _graph_failed(self, detail: str) -> None:
        if not self.is_mounted:
            return
        self._finish_graph_operation("● Analysis failed", "error")
        status = self.query_one("#graph-analysis-status", Static)
        status.tooltip = detail
        self.notify(detail, title="Graph analysis failed", severity="error")

    def _show_graph(self, graph: InvestigationGraph) -> None:
        if not self.is_mounted:
            return
        self.graph = graph
        displayed = (
            replace(
                graph,
                entities=tuple(e for e in graph.entities if e.semantic_support == "supported"),
            )
            if graph.manifest
            else graph
        )
        self.query_one("#graph-canvas", GraphCanvas).set_graph(displayed)
        self.query_one("#graph-statistics", Static).update(
            self._graph_statistics_label(graph, self.size.width)
        )
        self.query_one("#workspace-graph-metric", Static).update(
            f"GRAPH\n{len(graph.entities)}N · {len(graph.relationships)}E"
        )
        type_counts: dict[str, int] = {}
        for entity in graph.entities:
            type_counts[entity.entity_type] = type_counts.get(entity.entity_type, 0) + 1
        breakdown = "\n".join(
            f"{entity_type.title()}  {count}"
            for entity_type, count in sorted(
                type_counts.items(), key=lambda item: (-item[1], item[0])
            )
        )
        generated_at = graph.generated_at.astimezone().strftime("%Y-%m-%d %H:%M")
        self.query_one("#graph-breakdown", Static).update(
            "Entity types\n" + (breakdown or "No entities") + f"\n\nGenerated\n{generated_at}"
        )
        self.query_one("#chat-context-summary", Static).update(self._chat_context_label())

    @staticmethod
    def _graph_statistics_label(graph: InvestigationGraph, width: int) -> str:
        counts = f"{len(graph.entities)} entities · {len(graph.relationships)} relationships"
        return counts if width < 100 else counts + f" · run {graph.run_id[:8]}"

    def _entity_detail(self, entity: GraphEntity) -> str:
        classification = entity.entity_type
        if entity.subtype:
            classification += " / " + entity.subtype
        aliases = ", ".join(entity.aliases[:4]) or "—"
        identifiers = (
            ", ".join(f"{key}: {value}" for key, value in entity.external_identifiers[:4]) or "—"
        )
        rationale = entity.rationale.strip() or "No rationale supplied"
        return (
            "SELECTED ENTITY\n"
            + entity.canonical_name
            + "\n\nTYPE\n"
            + classification
            + "\n\nSTATUS / CONFIDENCE\n"
            + f"{entity.status.value.upper()} · {entity.confidence:.0%}"
            + "\n\nALIASES\n"
            + aliases
            + "\n\nIDENTIFIERS\n"
            + identifiers
            + "\n\nEVIDENCE\n"
            + f"{len(entity.evidence_ids)} supporting document(s)"
            + "\n\nFONTI / CITAZIONI\n"
            + self._support_detail(entity.support)
            + (
                "\n\nNOTE DI IDENTITÀ\n" + "\n".join(entity.resolution_notes)
                if entity.resolution_notes
                else ""
            )
            + "\n\nRATIONALE\n"
            + rationale
        )

    def _relationship_detail(
        self,
        relationships: tuple[GraphRelationship, ...],
    ) -> str:
        by_id = (
            {entity.entity_id: entity.canonical_name for entity in self.graph.entities}
            if self.graph is not None
            else {}
        )
        first = relationships[0]
        source = by_id.get(first.source_entity_id, first.source_entity_id)
        target = by_id.get(first.target_entity_id, first.target_entity_id)
        types = ", ".join(dict.fromkeys(item.relationship_type for item in relationships))
        evidence_ids = {evidence_id for item in relationships for evidence_id in item.evidence_ids}
        confidence = max(item.confidence for item in relationships)
        rationale = next(
            (item.rationale.strip() for item in relationships if item.rationale.strip()),
            "No rationale supplied",
        )
        support = "\n\n".join(
            (
                f"{item.relationship_type} · {item.status.value.upper()}\n"
                if len(relationships) > 1
                else ""
            )
            + self._support_detail(item.support)
            + (
                "\nNOTE SULLA RELAZIONE\n" + "\n".join(item.resolution_notes)
                if item.resolution_notes
                else ""
            )
            for item in relationships
        )
        return (
            "SELECTED RELATIONSHIP\n"
            + source
            + "\n  → "
            + target
            + "\n\nTYPE\n"
            + types
            + "\n\nSTATUS / CONFIDENCE\n"
            + f"{first.status.value.upper()} · {confidence:.0%}"
            + "\n\nEVIDENCE\n"
            + f"{len(evidence_ids)} supporting document(s)"
            + "\n\nFONTI / CITAZIONI\n"
            + support
            + "\n\nAFFERMAZIONI E CONFRONTI\n"
            + self._relationship_claim_details(relationships)
            + "\n\nRATIONALE\n"
            + rationale
        )

    def _relationship_claim_details(self, relationships: tuple[GraphRelationship, ...]) -> str:
        claim_ids = tuple(
            dict.fromkeys(claim_id for item in relationships for claim_id in item.claim_ids)
        )
        if not claim_ids or self.graph is None:
            return (
                "Nessuna affermazione strutturata collegata; "
                "i grafi precedenti non la registravano."
            )
        details = ClaimDetails(self.graph, tuple(self.documents))
        return "\n\n".join(
            details.claim_text(details.claims[claim_id])
            if claim_id in details.claims
            else f"Affermazione collegata non disponibile: {claim_id}"
            for claim_id in claim_ids
        )

    def _support_detail(self, support: tuple[EvidenceSpan, ...]) -> str:
        if not support:
            return (
                "Nessuna citazione puntuale salvata. I grafi precedenti possono avere solo "
                "riferimenti al documento: rigenera l'analisi per verificare pagine e citazioni."
            )
        documents = {item.document_id: item for item in self.documents}
        excerpts = []
        for span in dict.fromkeys(support):
            document = documents.get(span.evidence_id)
            source = (
                document.original_name
                if document
                else f"Documento non presente nell'indagine · {span.evidence_id}"
            )
            position = (
                f"Pagina {span.page_number}"
                if type(span.page_number) is int and span.page_number > 0
                else "Pagina non disponibile · posizione non verificata"
            )
            if document and document.file_format.upper() != "PDF" and span.page_number == 1:
                position = "Unità di testo 1 · formato senza paginazione stabile"
            verification = (
                "Citazione verificata nel testo originale"
                if span.verified_original
                else "Citazione non verificata nel testo originale"
            )
            excerpts.append(f"{source}\n{position}\n{verification}\n“{span.quote}”")
        return "\n\n".join(excerpts) + (
            "\n\nLa verifica della citazione conferma la presenza nel testo, "
            "non la verità dell'affermazione."
        )

    def _finish_graph_operation(self, label: str, state: str) -> None:
        self._graph_busy = False
        self.query_one("#graph-build-activity", GraphBuildActivity).stop()
        self.query_one("#graph-build-panel").add_class("hidden")
        self.query_one("#analyze-evidence", Button).disabled = False
        self.query_one("#graph-preparation-mode", Select).disabled = False
        self.query_one("#cancel-graph-analysis", Button).add_class("hidden")
        self._set_graph_status(label, state)

    def _set_graph_status(self, label: str, state: str) -> None:
        if not self.is_mounted:
            return
        status = self.query_one("#graph-analysis-status", Static)
        status.set_classes(state)
        status.update(label)
        status.tooltip = None

    @property
    def _raven_app(self) -> RavenApp:
        return cast("RavenApp", self.app)
