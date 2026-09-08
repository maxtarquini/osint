"""Opened investigation workspace with independent evidence management."""

from __future__ import annotations

import logging
import webbrowser
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
    Checkbox,
    DataTable,
    Footer,
    Input,
    Label,
    LoadingIndicator,
    ProgressBar,
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
    AnalysisLanguage,
    ChatEventKind,
    ChatMessage,
    ChatRole,
    EvidenceCitation,
    EvidenceDocument,
    EvidenceIngestionState,
    EvidencePreparationMode,
    GraphAnalysisJob,
    GraphAnalysisResult,
    GraphAnalysisRun,
    GraphEntity,
    GraphItemStatus,
    GraphJobStatus,
    GraphRelationship,
    Investigation,
    InvestigationGraph,
    JobStatus,
    RagIndexProgress,
    TokenUsage,
)
from raven.models.graph_filter import GraphFilters
from raven.services.graph_views import graph_map, graph_timeline, render_world_map
from raven.tui.actions import ChatCommand, ChatCommandError, parse_chat_command
from raven.tui.i18n import tr
from raven.tui.screens.evidence_inspector import EvidenceInspectorScreen
from raven.tui.screens.file_picker import (
    ConfirmEvidenceDelete,
    EvidenceFilePicker,
    MarkdownExportPicker,
)
from raven.tui.screens.graph_filters import GraphFiltersScreen
from raven.tui.screens.graph_inspector import GraphInspectorScreen
from raven.tui.widgets import (
    ChatInput,
    ChatMessageView,
    EvidenceTable,
    GraphCanvas,
    GraphItemsTable,
    LocalCommandView,
    StreamingAssistantView,
    TopNavigation,
)
from raven.tui.widgets.catalog import CatalogSummary
from raven.tui.widgets.derived_view import DerivedEvidenceView
from raven.tui.widgets.workspace_chrome import WorkspaceEmptyState, WorkspaceRail

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
        self._selected_graph_item_id: str | None = None
        self._graph_view_mode = "table"
        self._graph_runs: dict[str, GraphAnalysisRun] = {}
        self._last_evidence_source_directory = Path.home()
        self._chat_busy = False
        self._chat_cancel = Event()
        self._active_response: StreamingAssistantView | None = None
        self._chat_sources: tuple[str, ...] = ()
        self._rag_indexing = False
        self._rag_progress_completed = 0
        self._rag_progress_total = 0
        self._rag_verified_chunks: dict[str, int] = {}
        self._applied_rag_job_id: str | None = None
        self._chat_input_tokens = 0
        self._chat_output_tokens = 0
        self._chat_total_tokens = 0
        self._chat_last_usage: TokenUsage | None = None
        self._chat_saved_messages = 0
        self._last_assistant_markdown: str | None = None
        self._last_assistant_sources: tuple[str, ...] = ()
        self._last_export_directory = Path.home()
        self._deleting = False

    def compose(self) -> ComposeResult:
        language = self._raven_app.settings.interface_language
        yield TopNavigation(active="investigations")
        with Horizontal(id="workspace-summary"):
            with Vertical(id="workspace-heading"):
                yield Static(
                    tr(language, "workspace", "INVESTIGATION WORKSPACE"), classes="section-kicker"
                )
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
        with Horizontal(id="workspace-body"):
            yield WorkspaceRail(id="workspace-rail")
            with TabbedContent(initial="workspace-evidence-tab", id="workspace-tabs"):
                with (
                    TabPane(
                        tr(language, "overview", "Overview / Settings"), id="workspace-overview-tab"
                    ),
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
                with TabPane(tr(language, "evidence", "Evidence"), id="workspace-evidence-tab"):
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
                        yield Button(
                            tr(language, "index_rag", "Index RAG"), id="index-evidence-rag"
                        )
                        yield Button("Cancel RAG", id="cancel-rag-index", classes="hidden")
                        yield Button(
                            tr(language, "add_file", "Add file"),
                            id="add-evidence",
                            variant="primary",
                        )
                        yield Button("Cancel", id="cancel-evidence-upload", classes="hidden")
                    yield Static("● Ready", id="evidence-operation-status", classes="ready")
                    with Horizontal(id="rag-index-progress-strip", classes="hidden"):
                        yield LoadingIndicator(id="rag-index-spinner")
                        yield ProgressBar(
                            total=1,
                            show_eta=False,
                            id="rag-index-progress",
                        )
                        yield Static("0 / 0 documents", id="rag-index-progress-detail")
                    yield WorkspaceEmptyState("evidence", id="evidence-empty")
                    yield EvidenceTable(tuple(self.documents))
                    yield CatalogSummary(id="evidence-catalog-summary", classes="hidden")
                    yield Static(
                        "Select a document for its catalog · Enter open pages · D delete",
                        id="evidence-table-hint",
                    )
                with TabPane(tr(language, "graph", "Graph"), id="workspace-graph-tab"):
                    with Horizontal(id="graph-toolbar"):
                        with Vertical(id="graph-mode-control"):
                            yield Static("EVIDENCE PREPARATION", classes="field-label")
                            with Horizontal(id="graph-preparation-options"):
                                yield Checkbox(
                                    "Compress text",
                                    value=True,
                                    id="graph-compress-evidence",
                                )
                                yield Checkbox(
                                    "Chunk overlap",
                                    value=False,
                                    id="graph-chunk-evidence",
                                )
                            yield Static(
                                self._graph_translation_policy_label(),
                                id="graph-preparation-hint",
                            )
                        with Horizontal(id="graph-actions"):
                            yield Button(
                                tr(language, "analyze_evidence", "Analyze Evidence"),
                                id="analyze-evidence",
                                variant="primary",
                            )
                            yield Button("Cancel", id="cancel-graph-analysis", classes="hidden")
                    yield Static(
                        "● Ready · language: "
                        + self.investigation.analysis_language.prompt_label
                        + " · domain: "
                        + self.investigation.analysis_domain,
                        id="graph-analysis-status",
                        classes="ready",
                    )
                    with Horizontal(id="graph-body"):
                        with Vertical(id="graph-visual-panel"):
                            with Vertical(id="graph-panel-header"):
                                with Horizontal(id="graph-panel-title-row"):
                                    yield Static("PROPOSED GRAPH", classes="panel-title")
                                    yield Static(
                                        "0 entities · 0 relationships", id="graph-statistics"
                                    )
                                with Horizontal(id="graph-view-controls"):
                                    yield Static(
                                        "Rows select graph items · Enter inspect",
                                        id="graph-navigation-hint",
                                    )
                                    yield Button(
                                        tr(language, "table", "Table"),
                                        id="show-graph-table",
                                        variant="primary",
                                        classes="graph-mode-button",
                                    )
                                    yield Button(
                                        tr(language, "terminal_map", "Terminal map"),
                                        id="show-terminal-graph",
                                        classes="graph-mode-button",
                                    )
                                    yield Button(
                                        tr(language, "open_interactive", "Open interactive"),
                                        id="open-interactive-graph",
                                        classes="graph-open-button",
                                    )
                                    with Horizontal(id="graph-terminal-controls", classes="hidden"):
                                        yield Static("FIT", id="graph-zoom-label")
                                        yield Button(
                                            "Fit", id="fit-graph", classes="graph-view-button"
                                        )
                                        yield Button(
                                            "−", id="zoom-out-graph", classes="graph-view-button"
                                        )
                                        yield Button(
                                            "+", id="zoom-in-graph", classes="graph-view-button"
                                        )
                            with Horizontal(id="graph-search-bar"):
                                yield Input(
                                    placeholder="Find entity or relationship · Enter",
                                    id="graph-entity-search",
                                )
                                yield Button("Filters", id="graph-filters")
                            yield WorkspaceEmptyState(
                                "graph", bool(self.documents), id="graph-empty"
                            )
                            yield GraphItemsTable(language, id="graph-items-table")
                            yield GraphCanvas(id="graph-canvas", classes="hidden")
                        with VerticalScroll(id="graph-details-panel"):
                            yield Static("ANALYSIS CONTEXT", classes="panel-title")
                            with Vertical(id="graph-review-actions"):
                                yield Button("Verify", id="verify-graph-item", variant="success")
                                yield Button("Reject", id="reject-graph-item", variant="error")
                                yield Button("Reset proposed", id="propose-graph-item")
                            yield Static(
                                "SELECTED ITEM\nClick a node or edge, "
                                "or focus the graph and use J/K.",
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
                                "It is not a verified fact.",
                                id="graph-provenance-hint",
                            )
                with TabPane(tr(language, "runs_export", "Runs / Export"), id="workspace-runs-tab"):
                    with Horizontal(id="runs-toolbar"):
                        with Vertical(classes="section-heading"):
                            yield Static("GRAPH RUN HISTORY", classes="panel-title")
                            yield Static(
                                "Every pipeline execution and reproducibility profile",
                                classes="section-description",
                            )
                        yield Button("Load selected", id="load-graph-run")
                        yield Button("Export current", id="export-current-graph", variant="primary")
                    yield Static(
                        "● Loading run history...", id="graph-runs-status", classes="running"
                    )
                    yield DataTable(id="graph-runs-table", cursor_type="row", zebra_stripes=True)
                with TabPane(tr(language, "timeline", "Timeline"), id="workspace-timeline-tab"):
                    yield DerivedEvidenceView(
                        "timeline", bool(self.documents), id="timeline-workspace"
                    )
                with TabPane(tr(language, "map", "Map"), id="workspace-map-tab"):
                    yield DerivedEvidenceView("map", bool(self.documents), id="map-workspace")
                with TabPane(tr(language, "chat", "Chat"), id="workspace-chat-tab"):
                    with Horizontal(id="chat-toolbar"):
                        with Vertical(classes="section-heading", id="chat-heading"):
                            yield Static("INVESTIGATION COPILOT", classes="panel-title")
                            yield Static(
                                "RAG over this investigation's Evidence plus the latest graph",
                                classes="section-description",
                            )
                        yield Static(
                            self._chat_usage_summary(),
                            id="chat-token-usage",
                        )
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
                                "GROUNDING POLICY\nEvidence citations use [E1], [E2]... "
                                "Graph items "
                                "remain hypotheses while marked PROPOSED.",
                                classes="chat-context-note",
                                markup=False,
                            )
                    with Vertical(id="chat-composer"):
                        with Horizontal(id="chat-input-row"):
                            yield ChatInput(
                                id="chat-input",
                                classes="chat-input",
                                language=None,
                            )
                            yield Button("Cancel", id="cancel-chat", classes="hidden")
                            yield Button("Send", id="send-chat", variant="primary")
                        yield Static(
                            "/NEW · /SAVE · /STATS · /INFO  ·  Enter send · Shift+Enter new line",
                            id="chat-composer-hint",
                        )
        yield Footer()

    def on_mount(self) -> None:
        self._set_responsive_layout(self.size.width, self.size.height)
        self._load_latest_graph()
        self._load_chat_history()
        run_table = self.query_one("#graph-runs-table", DataTable)
        run_table.add_columns(
            "Updated", "Status", "Evidence", "Entities", "Relations", "Mode", "Model", "Run ID"
        )
        self._load_graph_runs()
        self.call_after_refresh(self.refresh_job_state)
        self.call_after_refresh(self._refresh_empty_states)
        self.call_after_refresh(self.refresh_catalogs)

    def refresh_catalogs(self) -> None:
        if self.is_mounted and self.documents:
            self._load_catalog_summaries()

    @work(thread=True, exclusive=True, group="catalog-summaries", exit_on_error=False)
    def _load_catalog_summaries(self) -> None:
        try:
            catalogs = {
                doc.document_id: self._raven_app.load_document_catalog(
                    self.investigation,
                    doc,
                    with_pages=False,
                )
                for doc in tuple(self.documents)
            }
        except Exception:
            return
        self.app.call_from_thread(self._show_catalog_summaries, catalogs)

    def _show_catalog_summaries(self, catalogs) -> None:
        if not self.is_mounted:
            return
        self._catalog_summaries = catalogs
        table = self.query_one(EvidenceTable)
        for document_id, catalog in catalogs.items():
            table.update_catalog(document_id, catalog)
        document = table._selected_document()
        if document:
            self._show_selected_catalog(document)

    def on_evidence_table_highlighted(self, event: EvidenceTable.Highlighted) -> None:
        self._show_selected_catalog(event.document)

    def _show_selected_catalog(self, document: EvidenceDocument) -> None:
        panel = self.query_one("#evidence-catalog-summary", CatalogSummary)
        panel.remove_class("hidden")
        panel.show_catalog(
            document.original_name,
            getattr(self, "_catalog_summaries", {}).get(document.document_id),
            self.investigation.analysis_domain,
        )

    def _refresh_empty_states(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#evidence-empty").set_class(bool(self.documents), "hidden")
        self.query_one("#evidence-catalog-summary").set_class(not self.documents, "hidden")
        self.query_one(EvidenceTable).set_class(not self.documents, "hidden")
        for empty in self.query(WorkspaceEmptyState):
            empty.set_document_state(bool(self.documents))
        self.set_class(self.graph is None or not self.graph.entities, "without-graph")
        for kind in ("map", "timeline"):
            if self.graph is None:
                self.query_one(f"#{kind}-workspace", DerivedEvidenceView).show_results("", 0)
        self.query_one(WorkspaceRail).select(
            self.query_one("#workspace-tabs", TabbedContent).active
        )

    def on_workspace_empty_state_proceed(self, event: WorkspaceEmptyState.Proceed) -> None:
        if event.target == "add":
            self._open_file_picker()
        elif event.target == "analyze":
            self.action_analyze_graph()
        else:
            self.action_show_graph()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.tabbed_content.id == "workspace-tabs":
            self.query_one(WorkspaceRail).select(event.pane.id or "")

    def refresh_job_state(self) -> None:
        """Apply application-owned job events without polling or database I/O."""
        self._sync_graph_analysis_job()
        self._sync_rag_index_job()

    def on_resize(self, event: Resize) -> None:
        self._set_responsive_layout(event.size.width, event.size.height)

    def _set_responsive_layout(self, width: int, height: int) -> None:
        self.set_class(
            height <= 34 or self._raven_app.settings.interface_density == "compact",
            "compact-workspace",
        )
        self.set_class(width < 100, "narrow-workspace")
        self.set_class(width >= 140 and height >= 30, "rail-workspace")
        if self.graph is not None:
            self.query_one("#graph-statistics", Static).update(
                self._graph_statistics_label(self.graph, width)
            )

    def _graph_translation_policy_label(self) -> str:
        language = self.investigation.analysis_language
        if language is AnalysisLanguage.ORIGINAL:
            return "Translation off · preserve original language"
        return f"Translate automatically → {language.prompt_label}"

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

    async def on_chat_input_submit(self, _event: ChatInput.Submit) -> None:
        """Use the same validated path for keyboard and button submissions."""
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
        if event.button.id and event.button.id.startswith("rail-"):
            key = event.button.id.removeprefix("rail-")
            self._show_tab(f"workspace-{key}-tab")
            return
        if event.button.id == "graph-filters":
            self.app.push_screen(
                GraphFiltersScreen(
                    getattr(self, "_graph_filters", GraphFilters()), tuple(self.documents)
                ),
                self._apply_graph_filters,
            )
            return
        if event.button.id == "add-evidence":
            self._open_file_picker()
        elif event.button.id == "index-evidence-rag":
            self._start_chat_index()
        elif event.button.id == "cancel-rag-index":
            self._cancel_rag_index()
        elif event.button.id == "cancel-evidence-upload":
            self._upload_cancel.set()
            self._set_operation_status("● Cancelling upload...", "running")
        elif event.button.id == "analyze-evidence":
            self._start_graph_analysis()
        elif event.button.id == "cancel-graph-analysis":
            self._raven_app.cancel_graph_analysis(self.investigation.investigation_id)
            self._sync_graph_analysis_job()
        elif event.button.id == "show-graph-table":
            self._set_graph_view_mode("table")
        elif event.button.id == "show-terminal-graph":
            self._set_graph_view_mode("terminal")
        elif event.button.id == "open-interactive-graph":
            self._open_interactive_graph()
        elif event.button.id == "fit-graph":
            self.query_one("#graph-canvas", GraphCanvas).fit()
        elif event.button.id == "zoom-out-graph":
            self.query_one("#graph-canvas", GraphCanvas).zoom_out()
        elif event.button.id == "zoom-in-graph":
            self.query_one("#graph-canvas", GraphCanvas).zoom_in()
        elif event.button.id == "verify-graph-item":
            self._start_graph_review(GraphItemStatus.VERIFIED)
        elif event.button.id == "reject-graph-item":
            self._start_graph_review(GraphItemStatus.REJECTED)
        elif event.button.id == "propose-graph-item":
            self._start_graph_review(GraphItemStatus.PROPOSED)
        elif event.button.id == "load-graph-run":
            self._load_selected_graph_run()
        elif event.button.id == "export-current-graph":
            self._export_graph()
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
        selected = self.query_one("#graph-items-table", GraphItemsTable).select_matching(
            event.value
        )
        if selected is not None:
            self._select_graph_item(selected)
            if isinstance(selected, GraphEntity):
                self.query_one("#graph-canvas", GraphCanvas).select_entity(selected.entity_id)
        if selected is None:
            self.notify(
                f'No graph entity matches "{event.value.strip()}".',
                title="Entity not found",
                severity="warning",
            )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "graph-items-table":
            return
        item = self.query_one("#graph-items-table", GraphItemsTable).selected_item()
        if item is not None:
            self._select_graph_item(item)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "graph-items-table":
            return
        item = self.query_one("#graph-items-table", GraphItemsTable).selected_item()
        if item is None:
            return
        self._select_graph_item(item)
        detail = (
            self._entity_detail(item)
            if isinstance(item, GraphEntity)
            else self._relationship_detail((item,))
        )
        self.app.push_screen(
            GraphInspectorScreen(item, detail, tuple(self.documents)),
            self._inspector_result,
        )

    def _inspector_result(self, result: tuple[str, str] | None) -> None:
        if result is None:
            return
        action, value = result
        if action == "review":
            self._start_graph_review(GraphItemStatus(value))
        else:
            document = next((d for d in self.documents if d.document_id == value), None)
            if document is not None:
                self._load_evidence_preview(document)

    def on_graph_canvas_view_changed(self, event: GraphCanvas.ViewChanged) -> None:
        self.query_one("#graph-zoom-label", Static).update(event.label)

    def on_graph_canvas_selection_changed(self, event: GraphCanvas.SelectionChanged) -> None:
        selection = event.selection
        if isinstance(selection, GraphEntity):
            self._selected_graph_item_id = selection.entity_id
            self.query_one("#graph-selection-detail", Static).update(self._entity_detail(selection))
        elif isinstance(selection, tuple) and selection:
            relationship = selection[0]
            self._selected_graph_item_id = relationship.relationship_id
            self.query_one("#graph-selection-detail", Static).update(
                self._relationship_detail(selection)
            )
        else:
            self._selected_graph_item_id = None
            self.query_one("#graph-selection-detail", Static).update(
                "SELECTED ITEM\nClick a node or edge, or focus the graph and use J/K."
            )

    def _select_graph_item(self, item: GraphEntity | GraphRelationship) -> None:
        if isinstance(item, GraphEntity):
            self._selected_graph_item_id = item.entity_id
            self.query_one("#graph-selection-detail", Static).update(self._entity_detail(item))
            return
        self._selected_graph_item_id = item.relationship_id
        self.query_one("#graph-selection-detail", Static).update(self._relationship_detail((item,)))

    def _set_graph_view_mode(self, mode: str) -> None:
        self._graph_view_mode = mode
        table = self.query_one("#graph-items-table", GraphItemsTable)
        canvas = self.query_one("#graph-canvas", GraphCanvas)
        terminal_controls = self.query_one("#graph-terminal-controls", Horizontal)
        table_button = self.query_one("#show-graph-table", Button)
        terminal_button = self.query_one("#show-terminal-graph", Button)
        showing_terminal = mode == "terminal"
        table.set_class(showing_terminal, "hidden")
        canvas.set_class(not showing_terminal, "hidden")
        terminal_controls.set_class(not showing_terminal, "hidden")
        table_button.variant = "default" if showing_terminal else "primary"
        terminal_button.variant = "primary" if showing_terminal else "default"
        self.query_one("#graph-navigation-hint", Static).update(
            "Arrows pan · J/K select · +/- zoom"
            if showing_terminal
            else "Rows select graph items · Enter inspect"
        )
        if showing_terminal:
            canvas.fit()
            canvas.focus()
        else:
            table.focus()

    def _apply_graph_filters(self, filters: GraphFilters | None) -> None:
        if filters is None:
            return
        self._graph_filters = filters
        self.query_one("#graph-items-table", GraphItemsTable).set_graph(self.graph, filters)
        self.query_one("#graph-filters", Button).label = (
            "Filters ●" if filters != GraphFilters() else "Filters"
        )
        self._set_graph_view_mode("table")

    def _start_graph_review(self, status: GraphItemStatus) -> None:
        if self.graph is None or self._selected_graph_item_id is None:
            self.notify("Select a graph node or relationship first.", severity="warning")
            return
        self._review_graph_item(self.graph, self._selected_graph_item_id, status)

    @work(thread=True, exclusive=True, group="graph-review", exit_on_error=False)
    def _review_graph_item(
        self, graph: InvestigationGraph, item_id: str, status: GraphItemStatus
    ) -> None:
        try:
            reviewed = self._raven_app.review_graph_item(graph, item_id, status)
        except Exception as error:
            logger.error("Graph review failed. error_type=%s", type(error).__name__)
            self.app.call_from_thread(
                self.notify,
                "Unable to persist the graph review; check Raven log.",
                title="Review not saved",
                severity="error",
            )
        else:
            self.app.call_from_thread(self._graph_reviewed, reviewed, status)

    def _graph_reviewed(self, reviewed: InvestigationGraph, status: GraphItemStatus) -> None:
        if not self.is_mounted:
            return
        item_id = self._selected_graph_item_id
        self._show_graph(reviewed)
        if item_id:
            self.query_one("#graph-items-table", GraphItemsTable).select_item(item_id)
        self.notify(
            f"Selected graph item marked {status.value.upper()}.",
            title="Review saved",
        )

    @work(thread=True, exclusive=True, group="graph-runs", exit_on_error=False)
    def _load_graph_runs(self) -> None:
        try:
            runs = self._raven_app.graph_run_history(self.investigation.investigation_id)
        except Exception as error:
            logger.warning("Graph run history unavailable. error_type=%s", type(error).__name__)
            self.app.call_from_thread(self._show_graph_runs, ())
        else:
            self.app.call_from_thread(self._show_graph_runs, runs)

    def _show_graph_runs(self, runs: tuple[GraphAnalysisRun, ...]) -> None:
        if not self.is_mounted:
            return
        self._graph_runs.update({run.run_id: run for run in runs})
        self._refresh_graph_provenance()
        table = self.query_one("#graph-runs-table", DataTable)
        table.clear()
        for run in runs:
            table.add_row(
                run.updated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                run.status.value.replace("_", " ").title(),
                f"{run.evidence_completed}/{run.evidence_total}",
                str(run.entity_count),
                str(run.relationship_count),
                run.preparation_mode.value.replace("_", " ").title(),
                run.model_name or "—",
                run.run_id[:12],
                key=run.run_id,
            )
        status = self.query_one("#graph-runs-status", Static)
        status.set_classes("ready")
        status.update(f"● {len(runs)} retained graph runs")

    def _load_selected_graph_run(self) -> None:
        table = self.query_one("#graph-runs-table", DataTable)
        if table.row_count == 0:
            return
        run_id = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        self._load_graph_run_snapshot(run_id)

    @work(thread=True, exclusive=True, group="graph-run-snapshot", exit_on_error=False)
    def _load_graph_run_snapshot(self, run_id: str) -> None:
        graph = self._raven_app.graph_run_snapshot(self.investigation.investigation_id, run_id)
        if graph is not None:
            self.app.call_from_thread(self._show_graph, graph)
            self.app.call_from_thread(
                self.notify, f"Loaded graph run {run_id[:12]}.", title="Run restored"
            )

    @work(thread=True, exclusive=True, group="graph-export", exit_on_error=False)
    def _export_graph(self) -> None:
        if self.graph is None:
            self.app.call_from_thread(
                self.notify, "Generate or load a graph first.", severity="warning"
            )
            return
        try:
            paths = self._raven_app.export_graph(self.investigation, self.graph)
        except Exception as error:
            logger.error("Graph export failed. error_type=%s", type(error).__name__)
            self.app.call_from_thread(self.notify, "Unable to export graph.", severity="error")
        else:
            self.app.call_from_thread(
                self.notify,
                f"Saved {len(paths)} files in {paths[0].parent}",
                title="Graph exported",
            )

    @work(thread=True, exclusive=True, group="graph-browser", exit_on_error=False)
    def _open_interactive_graph(self) -> None:
        if self.graph is None:
            self.app.call_from_thread(
                self.notify, "Generate or load a graph first.", severity="warning"
            )
            return
        try:
            paths = self._raven_app.export_graph(self.investigation, self.graph)
            html_path = next(path for path in paths if path.suffix == ".html")
            opened = webbrowser.open_new_tab(html_path.resolve().as_uri())
        except Exception as error:
            logger.error("Interactive graph open failed. error_type=%s", type(error).__name__)
            self.app.call_from_thread(
                self.notify,
                "Unable to create the interactive graph.",
                title="Visualization unavailable",
                severity="error",
            )
            return
        message = (
            f"Opened {html_path.name} in the browser."
            if opened
            else f"Saved interactive graph to {html_path} (browser launch was unavailable)."
        )
        self.app.call_from_thread(self.notify, message, title="Interactive graph ready")

    def on_evidence_table_delete_requested(self, event: EvidenceTable.DeleteRequested) -> None:
        if self._busy or self._rag_indexing:
            return
        self.app.push_screen(
            ConfirmEvidenceDelete(event.document),
            lambda confirmed: self._delete_confirmed(event.document, confirmed),
        )

    def on_evidence_table_inspect_requested(self, event: EvidenceTable.InspectRequested) -> None:
        if not self._busy:
            self._load_evidence_preview(event.document)

    @work(thread=True, exclusive=True, group="evidence-preview", exit_on_error=False)
    def _load_evidence_preview(self, document: EvidenceDocument) -> None:
        try:
            pages = self._raven_app.evidence_page_previews(document)
        except InvestigationError as error:
            pages = (f"Unable to extract this document.\n\n{error}",)
        except Exception as error:
            logger.warning(
                "Evidence preview failed. document_id=%s error_type=%s",
                document.document_id,
                type(error).__name__,
            )
            pages = ("Unable to extract this document; check the Raven log.",)
        self.app.call_from_thread(
            self.app.push_screen,
            EvidenceInspectorScreen(
                document,
                pages,
                self.investigation.analysis_language,
                self.investigation,
            ),
        )

    def _open_file_picker(self) -> None:
        if not self._busy:
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
        self._set_rag_controls_disabled(self._rag_indexing)
        self.query_one("#cancel-evidence-upload", Button).remove_class("hidden")
        self._set_operation_status(
            "● Adding document · waiting for active analysis to stop if necessary...", "running"
        )
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
        self.query_one(EvidenceTable).add_document(document)
        self._finish_operation("● Evidence added", "success")
        self._applied_rag_job_id = None
        self._sync_rag_index_job()
        self.refresh_catalogs()

    def _upload_cancelled(self) -> None:
        if self.is_mounted:
            self._finish_operation("● Upload cancelled", "cancelled")

    def _delete_confirmed(self, document: EvidenceDocument, confirmed: bool | None) -> None:
        if not confirmed or self._busy:
            return
        self._busy = True
        self._set_rag_controls_disabled(self._rag_indexing)
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
        self.graph = None
        self.query_one("#graph-canvas", GraphCanvas).set_graph(None)
        self.query_one("#graph-statistics", Static).update("0 entities · 0 relationships")
        self.query_one("#workspace-graph-metric", Static).update("GRAPH\nPending")
        self.query_one(EvidenceTable).remove_document(document.document_id)
        self._finish_operation("● Evidence deleted", "success")

    def _delete_failed(self, document: EvidenceDocument, detail: str) -> None:
        if not self.is_mounted:
            return
        self.query_one(EvidenceTable).disabled = False
        self._operation_failed(detail)

    def _operation_failed(self, detail: str) -> None:
        if not self.is_mounted:
            return
        self._finish_operation("● Operation failed", "error")
        self.query_one("#evidence-operation-status", Static).tooltip = detail
        self.notify(detail, title="Evidence operation failed", severity="error")

    def _finish_operation(self, label: str, state: str) -> None:
        self._busy = False
        self._set_rag_controls_disabled(self._rag_indexing)
        self.query_one("#cancel-evidence-upload", Button).add_class("hidden")
        self._set_operation_status(label, state)
        self._refresh_empty_states()
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

    def _start_chat_index(self, *, silent: bool = False) -> None:
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
        self._rag_indexing = True
        self._set_rag_controls_disabled(True)
        self._begin_rag_progress(len(self.documents))
        try:
            job = self._raven_app.enqueue_rag_index(self.investigation, tuple(self.documents))
        except (InvestigationChatError, InvestigationError) as error:
            self._chat_failed(str(error), silent)
            return
        self._set_rag_status(f"● {job.message}", "running")
        self._sync_rag_index_job()

    def _cancel_rag_index(self) -> None:
        if not self._rag_indexing:
            return
        self._raven_app.cancel_rag_index(self.investigation.investigation_id)
        self._set_rag_status(
            "● Cancellation requested after the active embedding step...", "running"
        )

    def _sync_rag_index_job(self) -> None:
        if not self.is_mounted:
            return
        job = self._raven_app.rag_index_job(self.investigation.investigation_id)
        if job is None:
            if self._rag_indexing:
                self._finish_rag_operation("● RAG indexing cancelled", "cancelled")
            return
        active = job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
        self._rag_indexing = active
        self._set_rag_controls_disabled(active)
        if active:
            progress = self._raven_app.rag_index_progress(self.investigation.investigation_id)
            if progress is not None:
                self._show_rag_index_progress(progress)
            self.query_one("#rag-index-progress-strip", Horizontal).remove_class("hidden")
            self._update_rag_progress(job.completed, job.total)
            self._set_rag_status(f"● {job.message}", "running")
            return
        if job.job_id == self._applied_rag_job_id:
            return
        self._applied_rag_job_id = job.job_id
        if job.status is JobStatus.COMPLETED:
            self.documents = [
                replace(document, rag_state=EvidenceIngestionState.READY)
                for document in self.documents
            ]
            for document in self.documents:
                self.query_one(EvidenceTable).update_document(document)
            self._finish_rag_operation(f"● {job.message}", "success")
        elif job.status is JobStatus.CANCELLED:
            self._finish_rag_operation("● RAG indexing cancelled", "cancelled")
        elif job.status is JobStatus.FAILED:
            self.documents = [
                replace(document, rag_state=EvidenceIngestionState.FAILED)
                if document.rag_state is EvidenceIngestionState.PROCESSING
                else document
                for document in self.documents
            ]
            for document in self.documents:
                self.query_one(EvidenceTable).update_document(document)
            self._finish_rag_operation(f"● {job.message}", "error")

    @work(thread=True, exclusive=True, group="chat-operation", exit_on_error=False)
    def _index_chat_kb(self, silent: bool) -> None:
        try:
            count = self._raven_app.index_investigation_knowledge_base(
                self.investigation,
                tuple(self.documents),
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
        if not self.is_mounted:
            return
        # Automatic indexing may emit progress before the upload callback adds its row.
        # The latest queue snapshot is applied again once the document is visible.
        if not any(document.document_id == progress.document_id for document in self.documents):
            return
        self.documents = [
            replace(document, rag_state=progress.state)
            if document.document_id == progress.document_id
            else document
            for document in self.documents
        ]
        updated = next(
            document for document in self.documents if document.document_id == progress.document_id
        )
        self.query_one(EvidenceTable).update_document(updated)
        if progress.state is EvidenceIngestionState.READY:
            self._rag_verified_chunks[progress.document_id] = progress.chunk_count
        action = {
            EvidenceIngestionState.PROCESSING: "Indexing",
            EvidenceIngestionState.READY: "Indexed",
            EvidenceIngestionState.FAILED: "Failed",
            EvidenceIngestionState.PENDING: "Pending",
        }[progress.state]
        state = {
            EvidenceIngestionState.PROCESSING: "running",
            EvidenceIngestionState.READY: "success",
            EvidenceIngestionState.FAILED: "error",
            EvidenceIngestionState.PENDING: "cancelled",
        }[progress.state]
        self._update_rag_progress(progress.completed, progress.total)
        phase = progress.detail or action
        self._set_rag_status(
            f"● {phase} · {progress.document_name} ({progress.completed}/{progress.total})",
            state,
        )

    def _chat_indexed(self, count: int) -> None:
        if not self.is_mounted:
            return
        self.documents = [
            replace(document, rag_state=EvidenceIngestionState.READY) for document in self.documents
        ]
        table = self.query_one(EvidenceTable)
        for document in self.documents:
            table.update_document(document)
        chunks = sum(self._rag_verified_chunks.values())
        noun = "document" if count == 1 else "documents"
        chunk_label = f" · {chunks} chunks" if chunks else ""
        self._finish_chat_operation(
            f"● KB verified in Qdrant · {count} {noun}{chunk_label}", "success"
        )
        self._finish_rag_operation(
            f"● RAG verified in Qdrant · {count} {noun}{chunk_label}",
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
                        event.citations,
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
        citations: tuple[EvidenceCitation, ...] = (),
    ) -> None:
        if self._active_response is not None and self._active_response.is_mounted:
            self._last_assistant_markdown = self._active_response.markdown_source
            self._last_assistant_sources = sources
            await self._active_response.complete(
                sources, usage, show_usage=True, citations=citations
            )
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
            self._finish_rag_operation(f"● RAG failed · {detail}", "error")
        status = self.query_one("#chat-operation-status", Static)
        status.tooltip = detail
        self.query_one("#evidence-operation-status", Static).tooltip = detail
        if not silent:
            self.notify(detail, title="Investigation chat failed", severity="error")

    def _finish_chat_operation(self, label: str, state: str) -> None:
        self._chat_busy = False
        self._set_chat_controls_disabled(False)
        self._set_chat_status(label, state)

    def _finish_rag_operation(self, label: str, state: str) -> None:
        self._rag_indexing = False
        self._set_rag_controls_disabled(False)
        if not self._busy:
            self._set_operation_status(label, state)
        self._finish_rag_progress(state)

    def _begin_rag_progress(self, total: int) -> None:
        self._rag_progress_completed = 0
        self._rag_progress_total = total
        self._rag_verified_chunks.clear()
        strip = self.query_one("#rag-index-progress-strip", Horizontal)
        strip.set_classes("running")
        self.query_one("#rag-index-spinner", LoadingIndicator).remove_class("hidden")
        self.query_one("#rag-index-progress", ProgressBar).update(
            total=max(total, 1),
            progress=0,
        )
        self.query_one("#rag-index-progress-detail", Static).update(f"0 / {total} documents")

    def _update_rag_progress(self, completed: int, total: int) -> None:
        self._rag_progress_completed = completed
        self._rag_progress_total = total
        self.query_one("#rag-index-progress", ProgressBar).update(
            total=max(total, 1),
            progress=completed,
        )
        percentage = 100 if total == 0 else round(completed * 100 / total)
        self.query_one("#rag-index-progress-detail", Static).update(
            f"{completed} / {total} · {percentage}%"
        )

    def _finish_rag_progress(self, state: str) -> None:
        strip = self.query_one("#rag-index-progress-strip", Horizontal)
        strip.set_classes(state)
        self.query_one("#rag-index-spinner", LoadingIndicator).add_class("hidden")
        if state == "success":
            self._update_rag_progress(self._rag_progress_total, self._rag_progress_total)
            noun = "document" if self._rag_progress_total == 1 else "documents"
            detail = f"Complete · {self._rag_progress_total} {noun}"
        else:
            detail = (
                f"{state.title()} · {self._rag_progress_completed} / {self._rag_progress_total}"
            )
        self.query_one("#rag-index-progress-detail", Static).update(detail)
        self.set_timer(2.5, self._hide_finished_rag_progress)

    def _hide_finished_rag_progress(self) -> None:
        if not self._rag_indexing:
            self.query_one("#rag-index-progress-strip", Horizontal).add_class("hidden")

    def _set_rag_controls_disabled(self, disabled: bool) -> None:
        self.query_one("#index-evidence-rag", Button).disabled = disabled or self._busy
        self.query_one("#add-evidence", Button).disabled = self._busy
        self.query_one("#cancel-rag-index", Button).set_class(not disabled, "hidden")
        self.query_one(EvidenceTable).disabled = self._busy

    def _set_rag_status(self, label: str, state: str) -> None:
        if not self._busy:
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
            document.rag_state is EvidenceIngestionState.READY for document in self.documents
        )
        entities = len(self.graph.entities) if self.graph is not None else 0
        relationships = len(self.graph.relationships) if self.graph is not None else 0
        context_window = self._chat_context_window()
        if self._chat_last_usage is None:
            latest_call = (
                "- Context input (provider reported): **not available**\n"
                "- Generated output: **not available**\n"
                "- Tokens used: **not available**"
            )
        else:
            occupancy = self._chat_last_usage.input_tokens / context_window * 100
            latest_call = (
                f"- Context input (provider reported): "
                f"**{self._chat_last_usage.input_tokens:,} tokens**\n"
                f"- Generated output: **{self._chat_last_usage.output_tokens:,} tokens**\n"
                f"- Tokens used: **{self._chat_last_usage.total_tokens:,} tokens**\n"
                f"- Context occupancy before generation: **{occupancy:.1f}%**"
            )
        return (
            "## Chat statistics\n\n"
            "### Latest model call\n\n"
            f"{latest_call}\n"
            f"- Configured context window: **{context_window:,} tokens**\n\n"
            "### Chat cumulative usage\n\n"
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
                f"{document.page_label} pages · RAG {document.rag_state.value} · "
                f"graph {document.graph_state.value}"
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
        self._chat_last_usage = usage[-1] if usage else None
        self._refresh_chat_usage()

    def _add_chat_usage(self, usage: TokenUsage) -> None:
        self._chat_input_tokens += usage.input_tokens
        self._chat_output_tokens += usage.output_tokens
        self._chat_total_tokens += usage.total_tokens
        self._chat_last_usage = usage
        self._refresh_chat_usage()

    def _chat_context_window(self) -> int:
        return self._raven_app.settings.with_environment().ai.context_size

    def _chat_usage_summary(self) -> str:
        context_window = self._chat_context_window()
        if self._chat_last_usage is None:
            return f"CONTEXT N/A/{context_window:,} · USED N/A · CHAT {self._chat_total_tokens:,}"
        return (
            f"CONTEXT {self._chat_last_usage.input_tokens:,}/{context_window:,} · "
            f"USED {self._chat_last_usage.total_tokens:,} · "
            f"CHAT {self._chat_total_tokens:,}"
        )

    def _refresh_chat_usage(self) -> None:
        if not self.is_mounted:
            return
        summary = self.query_one("#chat-token-usage", Static)
        summary.update(self._chat_usage_summary())
        context_window = self._chat_context_window()
        if self._chat_last_usage is None:
            summary.tooltip = (
                "The provider did not report token usage for the latest call. "
                f"Configured context window: {context_window:,} tokens. "
                f"Chat cumulative usage: {self._chat_total_tokens:,} tokens."
            )
            return
        occupancy = self._chat_last_usage.input_tokens / context_window * 100
        summary.tooltip = (
            "Provider-reported latest call · "
            f"context input: {self._chat_last_usage.input_tokens:,}/{context_window:,} "
            f"({occupancy:.1f}%) · generated: {self._chat_last_usage.output_tokens:,} · "
            f"used: {self._chat_last_usage.total_tokens:,} · "
            f"chat cumulative: {self._chat_total_tokens:,}"
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

    def _start_graph_analysis(self) -> None:
        if self._graph_busy:
            return
        if not self.documents:
            self.notify(
                "Add at least one Evidence document before graph analysis.",
                title="No Evidence",
                severity="warning",
            )
            return
        mode = EvidencePreparationMode.from_flags(
            compress_evidence=self.query_one("#graph-compress-evidence", Checkbox).value,
            chunk_evidence=self.query_one("#graph-chunk-evidence", Checkbox).value,
        )
        try:
            job = self._raven_app.enqueue_graph_analysis(
                self.investigation,
                tuple(self.documents),
                mode,
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
        elif self._graph_busy:
            self._graph_cancelled()

    def _apply_graph_analysis_job(self, job: GraphAnalysisJob) -> None:
        if not self.is_mounted:
            return
        active = job.status in {GraphJobStatus.QUEUED, GraphJobStatus.RUNNING}
        self._graph_busy = active
        compression = self.query_one("#graph-compress-evidence", Checkbox)
        chunking = self.query_one("#graph-chunk-evidence", Checkbox)
        if active:
            compression.value = job.preparation_mode.compress_evidence
            chunking.value = job.preparation_mode.chunk_evidence
        compression.disabled = active
        chunking.disabled = active
        self.query_one("#analyze-evidence", Button).disabled = active
        cancel = self.query_one("#cancel-graph-analysis", Button)
        cancel.set_class(not active, "hidden")
        if active:
            queue_label = "Queued" if job.status is GraphJobStatus.QUEUED else "Running"
            progress = job.progress
            self._set_graph_status(
                f"● {queue_label} · {progress.message} ({progress.completed}/{progress.total})",
                "running",
            )
            return
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
        self._graph_runs[result.run.run_id] = result.run
        self._show_graph(result.graph)
        states = dict(result.evidence_states)
        if states:
            self.documents = [
                replace(
                    document,
                    graph_state=states.get(document.document_id, document.graph_state),
                )
                for document in self.documents
            ]
            table = self.query_one(EvidenceTable)
            for document in self.documents:
                if document.document_id in states:
                    table.update_document(document)
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
        summary = " ".join(detail.split())
        if len(summary) > 180:
            summary = f"{summary[:177]}..."
        self._finish_graph_operation(f"● Analysis failed · {summary}", "error")
        status = self.query_one("#graph-analysis-status", Static)
        status.tooltip = detail
        self.notify(detail, title="Graph analysis failed", severity="error")

    def _show_graph(self, graph: InvestigationGraph) -> None:
        if not self.is_mounted:
            return
        self.graph = graph
        self.set_class(not graph.entities, "without-graph")
        self.query_one("#graph-items-table", GraphItemsTable).set_graph(
            graph, getattr(self, "_graph_filters", GraphFilters())
        )
        self.query_one("#graph-canvas", GraphCanvas).set_graph(graph)
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
        self._refresh_graph_provenance()
        timeline = graph_timeline(graph)
        timeline_text = (
            "\n".join(
                f"{entry.timestamp}  ·  {entry.label}  [{entry.entity_type}]  {entry.status}"
                for entry in timeline
            )
            if timeline
            else "No temporal identifiers found. Agents may emit date, datetime, start_date "
            "or end_date identifiers."
        )
        self.query_one("#timeline-workspace", DerivedEvidenceView).show_results(
            timeline_text, len(timeline)
        )
        locations = graph_map(graph)
        map_text = render_world_map(locations, width=max(40, min(100, self.size.width - 8)))
        self.query_one("#map-workspace", DerivedEvidenceView).show_results(map_text, len(locations))
        self.query_one("#chat-context-summary", Static).update(self._chat_context_label())
        self._load_graph_runs()

    def _refresh_graph_provenance(self) -> None:
        if not self.is_mounted:
            return
        provenance = self.query_one("#graph-provenance-hint", Static)
        if self.graph is None:
            provenance.set_classes("")
            provenance.update(
                "PROVENANCE\nAI output is Evidence-grounded and PROPOSED. "
                "It is not a verified fact."
            )
            return
        run = self._graph_runs.get(self.graph.run_id)
        if run is None:
            provenance.set_classes("running")
            provenance.update("PROVENANCE\nLoading graph run metadata...")
            return
        model = run.model_name or "unknown"
        if model.startswith("deterministic"):
            provenance.set_classes("warning")
            provenance.update(
                "⚠ DETERMINISTIC IOC-ONLY LEGACY RUN\n"
                "Semantic AI analysis did not complete for this graph. Run Analyze Evidence "
                "again after verifying the inference node."
            )
            return
        provenance.set_classes("success")
        provenance.update(
            "AI SEMANTIC RUN · PROPOSED\n"
            f"Model: {model}\n"
            f"Dictionary: {run.dictionary_domain}\n"
            "All candidates remain subject to analyst validation."
        )

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
            + "\n\nRATIONALE\n"
            + rationale
        )

    def _finish_graph_operation(self, label: str, state: str) -> None:
        self._graph_busy = False
        self.query_one("#analyze-evidence", Button).disabled = False
        self.query_one("#graph-compress-evidence", Checkbox).disabled = False
        self.query_one("#graph-chunk-evidence", Checkbox).disabled = False
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
